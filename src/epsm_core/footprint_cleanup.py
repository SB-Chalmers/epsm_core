"""Bounded source-footprint preparation shared by all geometry consumers."""

import json
from dataclasses import asdict
from functools import lru_cache
from hashlib import sha256

from shapely.affinity import translate

from .preparation import geometry_change_metrics, geometry_edge_lineage

VERSION = "footprint-cleanup-2"


@lru_cache(maxsize=256)
def prepared_footprints(geometry):
    source = [p.footprint.polygon for p in geometry.parts]
    cfg = geometry.footprint_cleanup
    prepared, reports = [], []
    for part, polygon in zip(geometry.parts, source):
        origin = polygon.bounds[:2]
        local = translate(polygon, -origin[0], -origin[1])
        candidate = (
            local.simplify(cfg.tolerance_m, preserve_topology=True) if cfg.enabled else local
        )
        # Shapely's zero-tolerance pass removes duplicates and collinear source points.
        if cfg.enabled:
            candidate = candidate.simplify(0, preserve_topology=True)
        candidate = translate(candidate, *origin) if cfg.enabled else polygon
        change = abs(candidate.area - polygon.area) / polygon.area
        metrics = geometry_change_metrics(polygon, candidate)
        displacement = (
            metrics["boundary_displacement_m"]
            if cfg.implementation_version == VERSION
            else polygon.boundary.hausdorff_distance(candidate.boundary)
        )
        if (
            not candidate.is_valid
            or candidate.geom_type != "Polygon"
            or len(candidate.interiors) != len(polygon.interiors)
        ):
            raise ValueError(f"Footprint cleanup changes topology: {part.identifier}")
        if change > cfg.max_area_change_fraction + 1e-12 or displacement > cfg.tolerance_m + 1e-8:
            raise ValueError(
                f"Footprint cleanup exceeds area/displacement limits: {part.identifier}"
            )
        # Version 2 additionally bounds exchanged outline area and boundary length.
        # Keep explicit version-1 inputs readable with their legacy acceptance limits.
        if cfg.enabled and cfg.implementation_version == VERSION:
            for key, limit in (
                ("symmetric_difference_fraction", cfg.max_symmetric_difference_fraction),
                ("perimeter_change_fraction", cfg.max_perimeter_change_fraction),
            ):
                if metrics[key] is None or metrics[key] > limit + 1e-12:
                    raise ValueError(f"Footprint cleanup exceeds {key}: {part.identifier}")
            radius = cfg.tolerance_m + 1e-8
            if not polygon.boundary.equals(candidate.boundary) and not (
                polygon.boundary.covered_by(candidate.boundary.buffer(radius, quad_segs=32))
                and candidate.boundary.covered_by(polygon.boundary.buffer(radius, quad_segs=32))
            ):
                raise ValueError(
                    f"Footprint cleanup exceeds continuous displacement: {part.identifier}"
                )
        if (
            cfg.enabled
            and any(w.facade_id.startswith(part.identifier + ".") for w in geometry.party_walls)
            and not candidate.equals_exact(polygon, 0)
        ):
            raise ValueError(
                f"Footprint cleanup would change referenced facade IDs: {part.identifier}; disable cleanup or prepare explicit references"
            )
        prepared.append(candidate)

        def count(p):
            return sum(len(r.coords) - 1 for r in (p.exterior, *p.interiors))

        reports.append(
            dict(
                part_id=part.identifier,
                source_vertices=count(polygon),
                prepared_vertices=count(candidate),
                source_area_m2=polygon.area,
                prepared_area_m2=candidate.area,
                source_perimeter_m=polygon.length,
                prepared_perimeter_m=candidate.length,
                area_change_fraction=change,
                max_displacement_m=displacement,
                changed=not candidate.equals_exact(polygon, 0),
                edge_lineage=[
                    dict(
                        asdict(edge),
                        facade_id=edge.facade_id.replace("p0.", part.identifier + ".", 1),
                        source_edges=[
                            fid.replace("p0.", part.identifier + ".", 1)
                            for fid in edge.source_edges
                        ],
                    )
                    for edge in geometry_edge_lineage(polygon, candidate, cfg.tolerance_m + 1e-8)
                ],
                symmetric_difference_fraction=metrics["symmetric_difference_fraction"],
                perimeter_change_fraction=metrics["perimeter_change_fraction"],
            )
        )
    for i, a in enumerate(source):
        for j in range(i + 1, len(source)):
            old = a.intersection(source[j])
            new = prepared[i].intersection(prepared[j])
            changed_contact = old.is_empty != new.is_empty
            if not old.is_empty and not new.is_empty:
                changed_contact = changed_contact or old.hausdorff_distance(new) > 1e-8
            if new.area > 1e-8 or changed_contact:
                raise ValueError("Footprint cleanup changes shared part boundaries")
    report = dict(
        version=cfg.implementation_version,
        settings=cfg.model_dump(mode="json"),
        parts=reports,
        source_sha256=sha256(
            json.dumps(
                [p.footprint.model_dump(mode="json") for p in geometry.parts], sort_keys=True
            ).encode()
        ).hexdigest(),
    )
    return tuple(prepared), report


def validate_facade_references(geometry, facade, report=None):
    """Reject cleanup on parts with explicit window OR balcony references.

    Edge indices can change even when net area and outline are identical. Never
    silently remap physical properties by index. Disable cleanup or supply reviewed
    prepared rings and references. Unreferenced parts can still be simplified.
    """
    if facade is None:
        return
    if report is None:
        _, report = prepared_footprints(geometry)
    references = (*facade.overrides, *facade.balconies)
    referenced = {item.facade_id.split(".r")[0] for item in references}
    if any(part["changed"] and part["part_id"] in referenced for part in report["parts"]):
        raise ValueError(
            "Footprint cleanup would change referenced facade IDs; disable cleanup "
            "or supply reviewed prepared geometry and references"
        )
