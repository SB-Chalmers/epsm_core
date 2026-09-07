# File: apartments.py
# Purpose: Bounded schematic residential layouts with explicit, inspectable fallbacks.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document apartments interfaces, examples, constraints and processing rationale.

"""Bounded schematic residential layouts with explicit, inspectable fallbacks.

Notes
-----
Layout generation first resolves baseline windows, then searches circulation and
dwelling cuts under bounded area, access and frontage constraints. All conditioned parts
must succeed. The outer topology resolver owns any explicitly requested per-storey
fallback.

Examples
--------
Install epsm_core[geometry] for the straight-skeleton backend.

Example::

    from epsm_core.specs.geometry import ApartmentLayoutSpec
    from epsm_core.specs.geometry import Footprint
    from epsm_core.specs.geometry import GeometrySpec
    from epsm_core.apartments import infer_floorplate

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
    polygon = geometry.footprints[0].polygon
    controls = ApartmentLayoutSpec()
    window_segments = []
    plan, reason = infer_floorplate(polygon, controls, window_segments)
    assert (plan is None) != (reason is None)
"""

from collections import Counter
from dataclasses import dataclass

import numpy as np
from shapely import set_precision, unary_union
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, box

from .roofs import dominant_direction, skeleton


def _polygons(g):
    """Extract immediate usable polygon parts from a clipping result.

    Parameters
    ----------
    g : BaseGeometry
        Shapely clipping result whose polygonal components are needed.

    Returns
    -------
    list of Polygon
        Polygon members, excluding empty geometry.

    Notes
    -----
    Collection members smaller than 1e-7 m2 are removed. Unlike zoning.polygon_components,
    this helper does not recursively descend nested collections.

    Examples
    --------
    Install epsm_core[geometry] for the straight-skeleton backend.

    Example::

        from epsm_core.apartments import _polygons

        from shapely.geometry import box

        assert len(_polygons(box(0, 0, 2, 2))) == 1
    """

    # 1. Extract immediate usable polygon parts from a clipping result.
    if g.is_empty:
        return []
    return (
        [g]
        if g.geom_type == "Polygon"
        else [p for p in g.geoms if p.geom_type == "Polygon" and p.area > 1e-7]
    )


def infer_floorplate(polygon, controls, window_segments, hints=()):
    """Search bounded facade-aligned apartment strips around skeleton circulation.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    controls : ApartmentLayoutSpec
        Explicit apartment area mix, access/frontage limits and bounded-search controls.
    window_segments : sequence of LineString
        Metric facade opening spans that candidate apartment cuts must avoid.
    hints : sequence of Polygon
        Optional explicit stair-core footprints in the same frame as the floorplate.
        Default: ``()``.

    Returns
    -------
    tuple
        Layout dictionary and None on success, or None and a failure reason.

    Notes
    -----
    Requires the optional straight-skeleton backend. This is a schematic search, not a
    reviewed dwelling plan: four states per cut position and a bounded candidate count may
    miss feasible layouts. Windows constrain cuts; access and frontage are geometric length
    checks.

    Examples
    --------
    Install epsm_core[geometry] for the straight-skeleton backend.

    Example::

        from epsm_core.specs.geometry import ApartmentLayoutSpec
        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.apartments import infer_floorplate

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygon = geometry.footprints[0].polygon
        controls = ApartmentLayoutSpec()
        window_segments = []
        plan, reason = infer_floorplate(polygon, controls, window_segments)
        assert (plan is None) != (reason is None)
    """
    # 1. Search bounded facade-aligned apartment strips around skeleton circulation.
    angle = dominant_direction(polygon)
    p = rotate(polygon, -angle, origin=(0, 0))
    windows = [rotate(w, -angle, origin=(0, 0)) for w in window_segments]
    x0, y0, x1, y1 = p.bounds
    try:
        sk = skeleton(p)
        arcs = []
        for a, b in sk.arc_iterator():
            if a.time > 1e-7 and b.time > 1e-7:
                arcs.append(
                    LineString([(a.position.x, a.position.y), (b.position.x, b.position.y)])
                )
        # Extend terminal spines toward exterior walls, retaining an end apartment bay.
        endpoints = Counter(tuple(v) for arc in arcs for v in (arc.coords[0], arc.coords[-1]))
        extensions = []
        for arc in arcs:
            for end, other in ((arc.coords[0], arc.coords[-1]), (arc.coords[-1], arc.coords[0])):
                if endpoints[tuple(end)] != 1:
                    continue
                end = np.array(end)
                direction = end - np.array(other)
                direction /= np.linalg.norm(direction)
                ray = LineString([end, end + direction * p.length * 2])
                cut = ray.intersection(p)
                lines = [cut] if cut.geom_type == "LineString" else list(getattr(cut, "geoms", []))
                from shapely.geometry import Point

                for segment in lines:
                    if segment.geom_type == "LineString" and segment.distance(Point(end)) < 1e-7:
                        distance = max(ray.project(Point(v)) for v in segment.coords) - 3
                        if distance > 0:
                            extensions.append(LineString([end, end + direction * distance]))
                        break
        network = unary_union(arcs + extensions) if arcs else p.representative_point()
    except ValueError as exc:
        return None, str(exc)
    # 2. Buffer connected skeleton circulation and require a usable single corridor region.
    corridors = network.buffer(
        controls.corridor_width_m / 2, cap_style="square", join_style="mitre"
    ).intersection(p)
    if len(_polygons(corridors)) != 1:
        return None, "Skeleton circulation is disconnected"
    centers = [network.representative_point()]
    if network.geom_type == "LineString":
        centers = [network.interpolate(t, normalized=True) for t in (0.5, 0.35, 0.65)]
    core_candidates = (
        [unary_union([rotate(h, -angle, origin=(0, 0)) for h in hints])] if hints else []
    )
    if not core_candidates:
        core_candidates = [
            box(
                c.x - controls.core_length_m / 2,
                c.y - controls.core_width_m / 2,
                c.x + controls.core_length_m / 2,
                c.y + controls.core_width_m / 2,
            )
            for c in centers
        ]
    best = None
    examined = 0
    # 3. Search only interior cores connected to circulation; preserve any explicit hints.
    for core in core_candidates:
        if not p.contains(core) or core.intersection(corridors).area < 1e-6:
            continue
        common = unary_union([corridors, core])
        if len(_polygons(common)) != 1:
            continue
        # Candidate cuts include facade corners, uniform search points and window gaps.
        values = {x0, x1, *[x for x, y in p.exterior.coords]}
        values.update(np.arange(x0 + 0.5, x1, 0.5))
        extents = sorted([(w.bounds[0], w.bounds[2]) for w in windows])
        values.update((b + c) / 2 for (a, b), (c, d) in zip(extents, extents[1:]) if c > b)
        xs = []
        for x in sorted(values):
            if x in (x0, x1) or not any(
                w.bounds[0] - 0.01 < x < w.bounds[2] + 0.01 for w in windows
            ):
                xs.append(float(x))
        if len(xs) > controls.max_candidates:
            xs = [
                xs[i]
                for i in sorted(
                    set(np.linspace(0, len(xs) - 1, controls.max_candidates, dtype=int))
                )
            ]
        # Keep a small beam per position; evaluate the actual achieved type mix.
        # 4. Keep a bounded beam of partial layouts, ranking the actually achieved type mix.
        states = {0: [([], Counter(), 0.0)]}
        for i in range(len(xs) - 1):
            if i not in states:
                continue
            for j in range(i + 1, len(xs)):
                band = p.intersection(box(xs[i], y0 - 1, xs[j], y1 + 1)).difference(common)
                pieces = _polygons(band)
                if not pieces:
                    continue
                if any(q.area > max(t.max_area_m2 for t in controls.types) + 1e-7 for q in pieces):
                    break
                assignments = []
                for q in pieces:
                    eligible = [
                        t
                        for t in controls.types
                        if t.min_area_m2 - 1e-7 <= q.area <= t.max_area_m2 + 1e-7
                    ]
                    if (
                        not eligible
                        or q.boundary.intersection(p.boundary).length < controls.min_frontage_m
                        or q.boundary.intersection(common.boundary).length < controls.min_access_m
                    ):
                        break
                    assignments.append((q, eligible))
                if len(assignments) != len(pieces):
                    continue
                for units, counts, cost in states[i]:
                    chosen = []
                    new = counts.copy()
                    for q, eligible in assignments:
                        total = sum(new.values()) + 1
                        typ = min(
                            eligible,
                            key=lambda t: (
                                new[t.name] / total - t.target_share,
                                abs(q.area - (t.min_area_m2 + t.max_area_m2) / 2),
                                t.name,
                            ),
                        )
                        new[typ.name] += 1
                        chosen.append((q, typ.name))
                    total = sum(new.values())
                    mix = sum((new[t.name] / total - t.target_share) ** 2 for t in controls.types)
                    item = (units + chosen, new, mix)
                    states.setdefault(j, []).append(item)
                    states[j] = sorted(
                        states[j], key=lambda s: (s[2], sum(q.length for q, t in s[0]))
                    )[:4]
                examined += 1
                if examined >= controls.max_candidates**2:
                    break
            if examined >= controls.max_candidates**2:
                break
        # 5. Accept only complete floorplate coverage before splitting landing and stairwell.
        for units, counts, cost in states.get(len(xs) - 1, []):
            cover = unary_union([common, *[q for q, _ in units]])
            if cover.symmetric_difference(p).area > 1e-7:
                continue
            score = (cost, common.area, sum(q.length for q, t in units))
            if best is None or score < best[0]:
                # Landing is the western third; the remaining core is a continuous stairwell.
                wells = []
                for core_part in _polygons(core):
                    a, b, c, d = core_part.bounds
                    landing = core_part.intersection(box(a - 1, b - 1, a + (c - a) / 3, d + 1))
                    wells.append(core_part.difference(landing))
                well = unary_union(wells)
                common_floor = common.difference(well)
                parts = [(rotate(q, angle, origin=(0, 0)), "dwelling", t) for q, t in units]
                parts += [
                    (rotate(q, angle, origin=(0, 0)), "common", "") for q in _polygons(common_floor)
                ]
                parts += [
                    (rotate(q, angle, origin=(0, 0)), "stairwell", "") for q in _polygons(well)
                ]
                best = (score, parts, dict(counts))
        if examined >= controls.max_candidates**2:
            break
    # 6. Report search failure explicitly; a bounded search cannot prove infeasibility.
    if best is None:
        return (
            None,
            f"No complete layout within a {controls.max_candidates}-position bounded cut search satisfies apartment area, frontage, access and window-clear cuts",
        )
    return dict(parts=best[1], unit_counts=best[2], candidates=examined), None


@dataclass(frozen=True)
class ApartmentRegion:
    """One schematic dwelling, common or stairwell floorplate region.

    Attributes
    ----------
    polygon : object
        Metric planar region; ownership and zoning meaning come from the enclosing record.
        Required at construction.
    kind : str
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.
    apartment_type : str
        Dwelling type label; empty for common, stairwell or nonresidential regions.
        Default: ``''``.

    Notes
    -----
    apartment_type is populated for dwellings. Regions are validated collectively for
    coverage and overlap before becoming thermal cells.

    Examples
    --------
    Install epsm_core[geometry] for the straight-skeleton backend.

    Example::

        from epsm_core.apartments import ApartmentRegion

        from shapely.geometry import box

        region = ApartmentRegion(box(0, 0, 5, 5), "dwelling", "studio")
    """

    polygon: object
    kind: str
    apartment_type: str = ""


def build_apartment_graph(spec, polygons):
    """Build complete experimental apartment partitions and validate their surface graph.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.

    Returns
    -------
    SurfaceGraph
        Generated dwelling, common and stairwell zones with layout report.

    Raises
    ------
    ValueError
        Rejected conditions: Supplied stair core must lie strictly inside one building part.

    Notes
    -----
    All conditioned parts must succeed; the outer zoning resolver owns opt-in fallback.
    Touching ownership parts and party-wall frontage are rejected. Stair cores must fit
    inside a part, and the inferred floorplate is repeated across its storeys.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``. Install epsm_core[geometry] for the
    straight-skeleton backend.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.apartments import build_apartment_graph
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        graph = build_apartment_graph(building, polygons)
    """
    # 1. Build complete experimental apartment partitions and validate their surface graph.
    from .facades import resolve_openings
    from .geometry import local_polygons
    from .surface_checks import validate_surfaces
    from .topology import building_cells, graph_from_cells, with_geometry
    from .zoning import GRID, validate_partitions

    geometry = spec.geometry
    controls = geometry.zoning.apartments
    baseline = with_geometry(
        spec,
        geometry.updated(
            zoning=geometry.zoning.updated(mode="per_storey", on_failure="error", depth_m=4.5)
        ),
    )
    # 2. Resolve baseline windows first so apartment cuts avoid glazing spans.
    base = graph_from_cells(baseline, polygons, building_cells(baseline, polygons))
    openings, _ = resolve_openings(baseline, base)
    _, origin = local_polygons(geometry)
    hints = [
        set_precision(
            rotate(
                translate(h.polygon, -origin[0], -origin[1]),
                -geometry.orientation_deg,
                origin=(0, 0),
            ),
            GRID,
        )
        for h in controls.stair_cores
    ]
    if any(not any(p.contains(h) for p in polygons) for h in hints):
        raise ValueError("Supplied stair core must lie strictly inside one building part")
    # 3. Require every conditioned part to succeed before producing an apartment graph.
    partitions, records = {}, []
    for part, polygon in zip(geometry.parts, polygons):
        if not part.conditioned:
            records.append(
                dict(
                    part_id=part.identifier,
                    status="not_applicable",
                    reason="Unconditioned part retains per-storey cells",
                    unit_counts={},
                )
            )
            continue
        if any(w.facade_id.startswith(part.identifier + ".r") for w in geometry.party_walls):
            raise ValueError(
                f"Apartment layout for {part.identifier}: Party-wall frontage requires a reviewed residential layout"
            )
        if any(
            other.identifier != part.identifier and polygon.distance(q) < 1e-7
            for other, q in zip(geometry.parts, polygons)
        ):
            raise ValueError(
                f"Apartment layout for {part.identifier}: touching ownership parts require a unified floorplate for coherent circulation"
            )
        segments = [
            LineString([(x, y) for x, y, z in o.vertices[:2]])
            for o in openings
            if o.metadata["part_id"] == part.identifier
        ]
        orientation = geometry.orientation_deg
        work = set_precision(rotate(polygon, orientation, origin=(0, 0)), GRID)
        plan, reason = infer_floorplate(
            work,
            controls,
            [set_precision(rotate(w, orientation, origin=(0, 0)), GRID) for w in segments],
            [
                set_precision(rotate(h, orientation, origin=(0, 0)), GRID)
                for h in hints
                if polygon.covers(h)
            ],
        )
        if plan is None:
            raise ValueError(f"Apartment layout for {part.identifier}: {reason}")
        regions = [
            ApartmentRegion(set_precision(rotate(q, -orientation, origin=(0, 0)), GRID), kind, typ)
            for q, kind, typ in plan["parts"]
        ]
        # 4. Verify coverage and overlap before repeating the inferred plan across storeys.
        validate_partitions(polygon, [r.polygon for r in regions])
        for storey in range(part.floors):
            partitions[(part.identifier, storey)] = regions
        records.append(
            dict(
                part_id=part.identifier,
                status="generated",
                reason=None,
                unit_counts={k: v * part.floors for k, v in plan["unit_counts"].items()},
                candidates=plan["candidates"],
            )
        )
    graph = graph_from_cells(spec, polygons, building_cells(spec, polygons, partitions))
    graph.layout_report = dict(
        status="generated",
        parts=records,
        assumptions=controls.model_dump(mode="json"),
        achieved_unit_counts=dict(sum((Counter(r["unit_counts"]) for r in records), Counter())),
    )
    objects = {
        f.name: dict(
            zone_name=f.zone,
            construction_name=f.construction,
            outside_boundary_condition=f.boundary,
            outside_boundary_condition_object=f.adjacent,
            vertices=[
                dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                for x, y, z in f.vertices
            ],
        )
        for f in graph.surfaces
    }
    # 5. Validate the final closed 3-D zones independently of schematic layout scoring.
    validate_surfaces({"BuildingSurface:Detailed": objects}, graph.zones)
    return graph
