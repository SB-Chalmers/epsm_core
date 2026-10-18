# File: zoning.py
# Purpose: Deterministic planar thermal partitions derived from exposed facade segments.
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
#   2026-09-06 - Document zoning interfaces, examples, constraints and processing rationale.

"""Deterministic planar thermal partitions derived from exposed facade segments.

These polygons are compiler cells, not physical walls or invented building parts.
Finite facade strips stop at party walls; distance bisectors allocate their overlaps.

Notes
-----
Finite exposed-facade strips and signed-distance bisectors define private thermal
regions. Reviewed party walls do not create perimeter strips. Precision, mitre and
overlap-work limits constrain numerical complexity; final regions must cover the
original floorplate without overlap.

Examples
--------
Example::

    from epsm_core.zoning import perimeter_core_partitions

    from shapely.geometry import box
    from epsm_core.geometry import facade_edges

    p = box(0, 0, 20, 20)
    regions = perimeter_core_partitions(p, list(facade_edges(p, "main")), 4.5)
"""

from dataclasses import dataclass
from math import hypot, isfinite

from shapely import STRtree, set_precision, unary_union
from shapely.geometry import LineString, MultiPoint, Polygon

from .geometry import facade_edges

GRID = 1e-8
AREA_TOLERANCE = 1e-7
MAX_EXPOSED_FACADES = 512
MAX_OVERLAP_PAIRS = 20_000


@dataclass(frozen=True)
class PlanarZone:
    """Private thermal floorplate region with optional exposed-facade lineage.

    Attributes
    ----------
    polygon : object
        Metric planar region; ownership and zoning meaning come from the enclosing record.
        Required at construction.
    kind : str
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Default: ``''``.

    Notes
    -----
    kind distinguishes perimeter and core regions. These regions are computational cells,
    not additional physical ownership parts or newly inferred construction walls.

    Examples
    --------
    Example::

        from epsm_core.zoning import PlanarZone

        from shapely.geometry import box

        region = PlanarZone(box(0, 0, 2, 2), "core")
    """

    polygon: object
    kind: str
    facade_id: str = ""


def polygon_components(geometry):
    """Recursively extract nontrivial polygons in stable spatial order.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry in metric plan coordinates; supported component handling is
        described in Notes.

    Returns
    -------
    list of Polygon
        Components sorted by bounds and area.

    Notes
    -----
    Empty and nonpolygonal members are ignored; Polygon areas at or below AREA_TOLERANCE are
    discarded.

    Examples
    --------
    Example::

        from epsm_core.zoning import polygon_components

        from shapely.geometry import box

        assert len(polygon_components(box(0, 0, 2, 2))) == 1
    """
    # 1. Recursively extract nontrivial polygons in stable spatial order.
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > AREA_TOLERANCE else []
    if not hasattr(geometry, "geoms"):
        return []
    return sorted(
        (p for child in geometry.geoms for p in polygon_components(child)),
        key=lambda p: (*p.bounds, p.area),
    )


def exposed_facades(part, polygon, parts, polygons, bottom, top, party_ids=(), part_tops=None,
                    *, party_walls=()):
    """Find directed facade segments exposed in at least one storey height band.

    Parameters
    ----------
    part : BuildingPart
        Physical ownership part associated with the current footprint.
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    parts : sequence of BuildingPart
        Physical ownership parts in the same order as the supplied polygons.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.
    bottom : float
        Vertical elevation in metres in the current scene datum.
    top : float
        Vertical elevation in metres in the current scene datum.
    party_ids : collection of str
        Confirmed party-wall facade identifiers excluded from exposed perimeter strips.
        Default: ``()``.
    part_tops : dict or None
        Optional per-part top elevations including attic shading extents. Default: ``None``.
    party_walls : sequence of PartyWall
        Optional rectangular contact patches. A horizontal segment is excluded
        only if their union covers the complete storey height at that segment.

    Returns
    -------
    list of tuple
        Facade ID and start/end coordinates in metres.

    Notes
    -----
    A neighbour suppresses an entire storey's exposure only if it reaches the storey top.
    Legacy complete party facade IDs are excluded. Partial contact patches exclude
    only segments fully covered through this storey; their outdoor upper/lower
    remnants still create perimeter strips. Exact vertical subdivision occurs
    later in the surface builder.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.zoning import exposed_facades
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        part = geometry.parts[0]
        polygon = geometry.footprints[0].polygon
        polygons, origin = local_polygons(geometry)
        segments = exposed_facades(part, polygon, geometry.parts, polygons, 0, 3)
    """
    # 1. Find directed facade segments exposed in at least one storey height band.
    covering = unary_union(
        [
            q
            for other, q in zip(parts, polygons)
            if other.identifier != part.identifier
            and other.storey_elevations_m[0] <= bottom + GRID
            and (part_tops or {}).get(other.identifier, other.storey_elevations_m[-1]) >= top - GRID
        ]
    )
    segments = []
    for fid, a, b in facade_edges(polygon, part.identifier):
        if fid in party_ids:
            continue
        line = LineString([a, b])
        contact_covers = []
        from .party_walls import contact_bounds

        rectangles = [contact_bounds(wall, line, part.storey_elevations_m[0],
                                     part.storey_elevations_m[-1])
                      for wall in party_walls if wall.facade_id == fid]
        xs = sorted({x for rectangle in rectangles for x in rectangle[:2]})
        for lo, hi in zip(xs, xs[1:]):
            middle = (lo + hi) / 2
            heights = sorted((max(bottom, z0), min(top, z1))
                             for x0, x1, z0, z1 in rectangles
                             if x0 <= middle <= x1 and z0 < top and z1 > bottom)
            reached = bottom
            for z0, z1 in heights:
                if z0 > reached + GRID:
                    break
                reached = max(reached, z1)
            if reached >= top - GRID:
                contact_covers.append(LineString([line.interpolate(lo), line.interpolate(hi)]))
        remainder = line.difference(covering.union(unary_union(contact_covers)))
        pieces = [remainder] if remainder.geom_type == "LineString" else remainder.geoms
        for piece in pieces:
            if piece.geom_type != "LineString" or piece.length < GRID:
                continue
            first, last = tuple(piece.coords[0]), tuple(piece.coords[-1])
            # Difference can reverse a segment. Retain the facade's inward-left normal.
            if line.project(piece.interpolate(0)) > line.project(piece.interpolate(piece.length)):
                first, last = last, first
            segments.append((fid, first, last))
    return sorted(segments, key=lambda item: (*sorted((item[1], item[2])), item[0]))


def _half_plane(bounds, a, b, c):
    """Clip an expanded bounding rectangle to a linear half-plane.

    Parameters
    ----------
    bounds : tuple of float
        Enclosing (min_x, min_y, max_x, max_y) rectangle.
    a : float
        Coefficient of x in a*x + b*y + c <= 0.
    b : float
        Coefficient of y in a*x + b*y + c <= 0.
    c : float
        Constant offset in a*x + b*y + c <= 0.

    Returns
    -------
    Polygon
        Region satisfying a*x + b*y + c <= 0.

    Notes
    -----
    The rectangle extends one bounding-box span beyond each side. It represents the half-
    plane only over the domain needed by the caller.

    Examples
    --------
    Example::

        from epsm_core.zoning import _half_plane

        assert _half_plane((0, 0, 2, 2), 1, 0, -1).bounds[2] == 1
    """
    # 1. Clip an expanded bounding rectangle to a linear half-plane.
    x0, y0, x1, y1 = bounds
    margin = max(x1 - x0, y1 - y0, 1)
    vertices = [
        (x0 - margin, y0 - margin),
        (x1 + margin, y0 - margin),
        (x1 + margin, y1 + margin),
        (x0 - margin, y1 + margin),
    ]
    result = []
    for p, q in zip(vertices, vertices[1:] + vertices[:1]):
        fp, fq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if fp <= 0:
            result.append(p)
        if (fp < 0 < fq) or (fq < 0 < fp):
            t = fp / (fp - fq)
            result.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return Polygon(result) if len(result) >= 3 else Polygon()


def perimeter_core_partitions(polygon, facades, depth_m=4.5):
    """Partition a floorplate into exposed-facade strips and remaining cores.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    facades : sequence of tuple
        Directed exposed segments as (facade_id, start, end), interior to the left.
    depth_m : float
        Positive finite perimeter-zone depth in metres. Default: ``4.5``.

    Returns
    -------
    tuple of PlanarZone
        Validated nonoverlapping floorplate regions.

    Raises
    ------
    ValueError
        Rejected conditions: Perimeter depth must be finite and positive; Perimeter zoning
        requires a valid nonempty polygon; Perimeter zoning received a collapsed facade
        segment; Perimeter reflex-corner mitre exceeds five times the depth; Inward facade
        strip self-intersects at this perimeter depth.

    Notes
    -----
    Uses finite strips and signed-distance bisectors. Spatial order resolves collinear ties.
    The 1e-8 m grid, facade/pair limits and five-depth mitre bound prevent unstable or
    unbounded geometry work. Failure is explicit.

    Examples
    --------
    Example::

        from epsm_core.zoning import perimeter_core_partitions

        from shapely.geometry import box
        from epsm_core.geometry import facade_edges

        p = box(0, 0, 20, 20)
        regions = perimeter_core_partitions(p, list(facade_edges(p, "main")), 4.5)
    """
    # 1. Partition a floorplate into exposed-facade strips and remaining cores.
    if not isfinite(depth_m) or depth_m <= 0:
        raise ValueError("Perimeter depth must be finite and positive")
    if polygon.is_empty or not polygon.is_valid or polygon.area <= AREA_TOLERANCE:
        raise ValueError("Perimeter zoning requires a valid nonempty polygon")
    if len(facades) > MAX_EXPOSED_FACADES:
        raise ValueError(f"Perimeter zoning exceeds {MAX_EXPOSED_FACADES} exposed facade segments")
    # 2. Use one precision grid and spatial ordering for deterministic ownership ties.
    polygon = set_precision(polygon, GRID)
    facades = sorted(facades, key=lambda item: (*sorted((item[1], item[2])), item[0]))
    normals = []
    offsets = []
    for _, a, b in facades:
        length = hypot(b[0] - a[0], b[1] - a[1])
        if length < GRID:
            raise ValueError("Perimeter zoning received a collapsed facade segment")
        nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        normals.append((nx, ny, -nx * a[0] - ny * a[1]))
        offsets.append(
            [(a[0] + nx * depth_m, a[1] + ny * depth_m), (b[0] + nx * depth_m, b[1] + ny * depth_m)]
        )
    # A concave corner leaves a gap between ordinary rectangles. Intersect the
    # offset lines to fill that gap, preserving a shared mitre between the strips.
    for i, (_, a, b) in enumerate(facades):
        for j, (_, c, d) in enumerate(facades):
            if i == j or hypot(b[0] - c[0], b[1] - c[1]) > GRID * 2:
                continue
            ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
            cross = ux * vy - uy * vx
            if cross >= -GRID:
                continue
            first, second = offsets[i][1], offsets[j][0]
            t = ((second[0] - first[0]) * vy - (second[1] - first[1]) * vx) / cross
            intersection = (first[0] + t * ux, first[1] + t * uy)
            if hypot(intersection[0] - b[0], intersection[1] - b[1]) > 5 * depth_m:
                raise ValueError("Perimeter reflex-corner mitre exceeds five times the depth")
            offsets[i][1] = offsets[j][0] = intersection
    # 3. Clip finite inward strips to the actual footprint, retaining courtyard exclusions.
    strips = []
    for (_, a, b), (inner_a, inner_b), (nx, ny, c) in zip(facades, offsets, normals):
        strip = Polygon([a, b, inner_b, inner_a])
        if not strip.is_valid:
            raise ValueError("Inward facade strip self-intersects at this perimeter depth")
        strip = strip.intersection(polygon)
        strip = strip.intersection(_half_plane(polygon.bounds, -nx, -ny, -c))
        strip = strip.intersection(_half_plane(polygon.bounds, nx, ny, c - depth_m))
        strips.append(set_precision(strip, GRID))
    # 4. Limit overlap work spatially and enforce an explicit pair-count budget.
    tree = STRtree(strips)
    neighbors = []
    overlap_pairs = 0
    for i, strip in enumerate(strips):
        adjacent = []
        for j in sorted(tree.query(strip, predicate="intersects")):
            if i != j and strip.intersection(strips[j]).area > AREA_TOLERANCE:
                adjacent.append(int(j))
                overlap_pairs += int(j > i)
        if overlap_pairs > MAX_OVERLAP_PAIRS:
            raise ValueError(
                f"Perimeter zoning exceeds {MAX_OVERLAP_PAIRS} overlapping strip pairs"
            )
        neighbors.append(adjacent)
    # 5. Allocate only shared strip area by signed-distance bisectors.
    regions = []
    for i, raw in enumerate(strips):
        region = raw
        ai, bi, ci = normals[i]
        for j in neighbors[i]:
            other = strips[j]
            if region.is_empty or not region.intersects(other):
                continue
            aj, bj, cj = normals[j]
            a, b, c = ai - aj, bi - bj, ci - cj
            if abs(a) + abs(b) < 1e-12:
                if c > GRID or (abs(c) <= GRID and j < i):
                    region = region.difference(other)
                continue
            # Remove only the overlap in which the other facade is closer.
            closer = _half_plane(polygon.bounds, -a, -b, -c)
            region = region.difference(other.intersection(closer))
        regions.extend(
            PlanarZone(p, "perimeter", facades[i][0])
            for p in polygon_components(set_precision(region, GRID))
        )
    # 6. Preserve all remaining cores and validate complete nonoverlapping coverage.
    core = polygon.difference(unary_union(strips))
    regions.extend(PlanarZone(p, "core") for p in polygon_components(set_precision(core, GRID)))
    # Collapse sub-centimetre partition/source-corner gaps coherently across
    # all regions. Physical outline is retained; coverage is checked below.
    anchors = MultiPoint(
        [p for ring in (polygon.exterior, *polygon.interiors) for p in ring.coords[:-1]]
    )
    anchor_points = [tuple(p.coords[0]) for p in anchors.geoms]

    def aligned_ring(ring):
        result = []
        for point in ring.coords:
            nearest = min(anchor_points, key=lambda a: hypot(a[0] - point[0], a[1] - point[1]))
            result.append(
                nearest if hypot(nearest[0] - point[0], nearest[1] - point[1]) < 0.010001 else point
            )
        return result

    regions = [
        PlanarZone(
            Polygon(
                aligned_ring(r.polygon.exterior), [aligned_ring(h) for h in r.polygon.interiors]
            ).simplify(0),
            r.kind,
            r.facade_id,
        )
        for r in regions
    ]
    validate_partitions(polygon, [r.polygon for r in regions])
    return tuple(regions)


def validate_partitions(polygon, partitions):
    """Require valid, nonempty, nonoverlapping partitions covering the original footprint.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    partitions : dict or sequence
        Generated planar subdivisions; cell building uses (part ID, storey) keys, coverage
        validation uses polygons.

    Returns
    -------
    None
        Successful geometric validation.

    Raises
    ------
    ValueError
        Rejected conditions: Generated thermal partitions must be valid and nonempty;
        Generated thermal partitions do not cover the original floorplate; Generated thermal
        partitions overlap.

    Notes
    -----
    Uses max(1e-7 m2, footprint area * 1e-8) for coverage and overlap checks. It does not
    repair or fill missing regions.

    Examples
    --------
    Example::

        from epsm_core.zoning import validate_partitions

        from shapely.geometry import box

        validate_partitions(box(0, 0, 2, 2), [box(0, 0, 1, 2), box(1, 0, 2, 2)])
    """
    # 1. Require valid, nonempty, nonoverlapping partitions covering the original footprint.
    tolerance = max(AREA_TOLERANCE, polygon.area * 1e-8)
    if not partitions or any(not p.is_valid or p.is_empty for p in partitions):
        raise ValueError("Generated thermal partitions must be valid and nonempty")
    cover = unary_union(partitions)
    if cover.symmetric_difference(polygon).area > tolerance:
        raise ValueError("Generated thermal partitions do not cover the original floorplate")
    if sum(p.area for p in partitions) - cover.area > tolerance:
        raise ValueError("Generated thermal partitions overlap")
