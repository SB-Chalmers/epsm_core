"""Bounded source-footprint preparation shared by all geometry consumers."""

import json
from functools import lru_cache
from hashlib import sha256

from shapely.affinity import translate

VERSION = "footprint-cleanup-1"


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
        displacement = polygon.boundary.hausdorff_distance(candidate.boundary)
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
        version=VERSION,
        settings=cfg.model_dump(mode="json"),
        parts=reports,
        source_sha256=sha256(
            json.dumps(
                [p.footprint.model_dump(mode="json") for p in geometry.parts], sort_keys=True
            ).encode()
        ).hexdigest(),
    )
    return tuple(prepared), report
