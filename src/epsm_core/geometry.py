# File: geometry.py
# Purpose: Deterministic planar geometry, extrusion and facade identity.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-11
# Changelog:
#   2026-10-03 - Preserve source facade identities under perimeter precision rounding.
#   2026-09-11 - Generate outward-wound surfaces and prove horizontal decomposition conservation.
#   2026-09-06 - Document geometry interfaces, examples, constraints and processing rationale.

"""Deterministic planar geometry, extrusion and facade identity.

Notes
-----
Plan coordinates are in metres; +Y denotes north and positive scene orientation is
clockwise. Stable facade IDs preserve ring/edge provenance. Horizontal polygons with
courtyard holes are tessellated with an independent area-conservation check.

Examples
--------
Example::

    from epsm_core.geometry import wall_vertices

    assert wall_vertices((0, 0), (2, 0), 0, 3)[2] == (2, 0, 3)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import constrained_delaunay_triangles
from shapely.affinity import rotate, translate
from shapely.geometry import LineString
from shapely.geometry.polygon import orient


def local_polygons(geometry):
    """Translate footprints to a shared local origin and rotate the scene.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.

    Returns
    -------
    tuple
        Local polygon list and original minimum (x, y) in metres.

    Notes
    -----
    Positive orientation is clockwise from north. The origin is computed before rotation; no
    CRS conversion is performed.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
    """

    # 1. Translate footprints to a shared local origin and rotate the scene.
    origin = (
        min(p.polygon.bounds[0] for p in geometry.footprints),
        min(p.polygon.bounds[1] for p in geometry.footprints),
    )
    polygons = [translate(p.polygon, -origin[0], -origin[1]) for p in geometry.footprints]
    if geometry.zoning.mode == "perimeter_core":
        from shapely import set_precision
        # Quantize the whole physical scene once, before any partition intersection.
        # Pointwise rounding retains ring start/winding and source facade IDs.
        # GEOS valid-output rounding may reorder the ring and swap facade identities
        # between zoning modes (test_api logical-window contract).
        polygons = [set_precision(p, 1e-8, mode="pointwise") for p in polygons]
    # Positive azimuth is clockwise from north, matching EnergyPlus conventions.
    return [rotate(p, -geometry.orientation_deg, origin=(0, 0)) for p in polygons], origin


def horizontal_patches(polygon):
    """Produce convex horizontal patches while conserving net area.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.

    Returns
    -------
    list of Polygon
        Counterclockwise patches in deterministic centroid order.

    Raises
    ------
    ValueError
        Rejected conditions: Tessellation failed area conservation.

    Notes
    -----
    Courtyards, concave polygons and faces with more than four vertices use
    constrained Delaunay triangulation; an area mismatch above relative 1e-9
    is rejected. This changes face tessellation, never thermal zoning.

    Examples
    --------
    Example::

        from epsm_core.geometry import horizontal_patches

        from shapely.geometry import box

        patches = horizontal_patches(box(0, 0, 10, 8))
        assert sum(p.area for p in patches) == 80
    """
    # 1. Produce convex horizontal patches while conserving net area.
    # EnergyPlus polygon clipping requires convex receiving surfaces. Keeping
    # concave flat roofs intact produces invalid shadows and explosive overlap
    # calculations. Split only horizontal faces; thermal cells/zones stay intact.
    # Bound convex faces too, avoiding the engine's overlap vertex limit.
    ring = list(polygon.exterior.coords)[:-1]
    collinear = any(
        abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) <= 1e-12
        for a, b, c in zip(ring, ring[1:] + ring[:1], ring[2:] + ring[:2])
    )
    if (
        not polygon.interiors
        and len(polygon.exterior.coords) <= 5
        and polygon.equals(polygon.convex_hull)
        and not collinear
    ):
        return [orient(polygon, sign=1)]
    triangles = constrained_delaunay_triangles(polygon)
    patches = sorted(
        (orient(p, sign=1) for p in triangles.geoms),
        key=lambda p: (p.centroid.x, p.centroid.y, p.area),
    )
    from shapely.ops import unary_union

    tolerance = max(1e-9, polygon.area * 1e-9)
    union = unary_union(patches)
    if (
        abs(sum(p.area for p in patches) - polygon.area) > tolerance
        or abs(sum(p.area for p in patches) - union.area) > tolerance
        or union.symmetric_difference(polygon).area > tolerance
    ):
        raise ValueError("Tessellation failed area conservation")
    return patches


def facade_edges(polygon, component):
    # Preserve input edge indices even when normals require reversing a ring.
    """Yield stable facade IDs and directed boundary endpoints.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    component : str or int
        Stable component identifier used as the facade-ID prefix.

    Yields
    ------
    tuple
        Facade ID, start and end coordinates in metres.

    Raises
    ------
    ValueError
        Rejected conditions: Zero-length facade edge.

    Notes
    -----
    Input ring indices remain the identity even when endpoints are reversed to obtain an
    inward-left normal. Edges shorter than 1e-6 m are rejected.

    Examples
    --------
    Example::

        from epsm_core.geometry import facade_edges

        from shapely.geometry import box

        edges = list(facade_edges(box(0, 0, 10, 8), "main"))
        assert len(edges) == 4
    """

    # 1. Yield stable facade IDs and directed boundary endpoints.
    for ri, ring in enumerate((polygon.exterior, *polygon.interiors)):
        coords = list(ring.coords)[:-1]
        reverse = bool(ring.is_ccw) != (ri == 0)
        for ei, a in enumerate(coords):
            b = coords[(ei + 1) % len(coords)]
            if reverse:
                a, b = b, a
            if math.dist(a, b) < 1e-6:
                raise ValueError("Zero-length facade edge")
            yield f"{component}.r{ri}.e{ei}", a, b


def wall_vertices(a, b, bottom, top):
    """Extrude a directed plan edge into an outward-oriented quadrilateral.

    Parameters
    ----------
    a : tuple of float
        Directed edge start in metric plan coordinates.
    b : tuple of float
        Directed edge end in metric plan coordinates.
    bottom : float
        Vertical elevation in metres in the current scene datum.
    top : float
        Vertical elevation in metres in the current scene datum.

    Returns
    -------
    list
        Four (x, y, z) vertices in metres.

    Notes
    -----
    The edge must have its building interior on the left. This helper assumes top exceeds
    bottom and does not validate heights.

    Examples
    --------
    Example::

        from epsm_core.geometry import wall_vertices

        assert wall_vertices((0, 0), (2, 0), 0, 3)[2] == (2, 0, 3)
    """

    return [(a[0], a[1], bottom), (b[0], b[1], bottom), (b[0], b[1], top), (a[0], a[1], top)]


def horizontal_vertices(polygon, height, upward=True):
    """Lift an exterior ring to a horizontal surface at the requested height.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    height : float
        Absolute scene elevation in metres for the horizontal surface.
    upward : bool
        True produces a +Z normal; False reverses winding for a floor. Default: ``True``.

    Returns
    -------
    list
        Unclosed (x, y, z) vertices in metres.

    Notes
    -----
    Use horizontal_patches first for polygons with holes: this helper emits only the
    exterior ring.

    Examples
    --------
    Example::

        from epsm_core.geometry import horizontal_vertices

        from shapely.geometry import box

        assert all(v[2] == 3 for v in horizontal_vertices(box(0, 0, 2, 2), 3))
    """

    coords = list(orient(polygon, sign=1).exterior.coords)[:-1]
    if not upward:
        coords.reverse()
    return [(x, y, height) for x, y in coords]


def exposed_segments(patch, whole):
    """Identify floor-patch edges lying on the complete footprint boundary.

    Parameters
    ----------
    patch : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    whole : Polygon or MultiPolygon
        Complete footprint used to distinguish exterior from triangulation edges.

    Returns
    -------
    list of bool
        Exposure flags in downward floor-ring order.

    Notes
    -----
    A 1e-6 m length tolerance absorbs intersection noise; internal triangulation edges are
    not exterior perimeter.

    Examples
    --------
    Example::

        from epsm_core.geometry import exposed_segments

        from shapely.geometry import box

        p = box(0, 0, 2, 2)
        assert all(exposed_segments(p, p))
    """

    # 1. Identify floor-patch edges lying on the complete footprint boundary.
    coords = list(patch.exterior.coords)[:-1][::-1]  # floor normal points downward
    values = []
    for i, a in enumerate(coords):
        line = LineString([a, coords[(i + 1) % len(coords)]])
        values.append(line.intersection(whole.boundary).length >= line.length - 1e-6)
    return values


def cardinal(a, b):
    """Classify a directed facade's outward normal into four cardinal sectors.

    Parameters
    ----------
    a : tuple of float
        Directed edge start in metric plan coordinates.
    b : tuple of float
        Directed edge end in metric plan coordinates.

    Returns
    -------
    str
        One of north, east, south or west.

    Notes
    -----
    Coordinates use +Y north. Forty-five-degree ties enter the next clockwise sector.

    Examples
    --------
    Example::

        from epsm_core.geometry import cardinal

        assert cardinal((0, 0), (2, 0)) == "south"
    """

    dx, dy = b[0] - a[0], b[1] - a[1]
    azimuth = math.degrees(math.atan2(dy, -dx)) % 360
    return ("north", "east", "south", "west")[int((azimuth + 45) // 90) % 4]


@dataclass(frozen=True)
class FacadeInfo:
    """Original facade identity and dimensions with scene-oriented azimuth.

    Attributes
    ----------
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Required at
        construction.
    part_id : str
        Owning physical part or neighbouring-building identifier.  Required at construction.
    start_m : tuple[float, float]
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Required at construction.
    end_m : tuple[float, float]
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Required at construction.
    length_m : float
        Original directed facade length in metres.  Required at construction.
    azimuth_deg : float
        Clockwise azimuth from north in degrees; 180 faces south.  Required at construction.
    storeys : tuple[int, ...]
        Zero-based storey indices; for balconies an empty tuple applies to all storeys.
        Required at construction.
    storey_elevations_m : tuple[float, ...]
        Increasing grade-relative elevations including the top of the final storey.
        Required at construction.

    Notes
    -----
    Endpoints stay in source coordinates; azimuth includes geometry orientation. Storey
    indices are zero-based, and elevations include the top of the final storey.

    Examples
    --------
    Example::

        from epsm_core.geometry import FacadeInfo

        info = FacadeInfo("main.r0.e0", "main", (0, 0), (10, 0), 10, 180, (0,), (0, 3))
    """

    facade_id: str
    part_id: str
    start_m: tuple[float, float]
    end_m: tuple[float, float]
    length_m: float
    azimuth_deg: float
    storeys: tuple[int, ...]
    storey_elevations_m: tuple[float, ...]


def facade_catalog(geometry):
    """Describe original facade identity, dimensions and oriented azimuth.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.

    Returns
    -------
    tuple of FacadeInfo
        Records ordered by part, ring and edge.

    Notes
    -----
    Endpoints remain in input coordinates; only reported azimuth includes scene orientation.
    Storey indices are zero-based.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.geometry import facade_catalog

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        catalog = facade_catalog(geometry)
        assert all(f.length_m > 0 for f in catalog)
    """

    # 1. Describe original facade identity, dimensions and oriented azimuth.
    return tuple(
        FacadeInfo(
            fid,
            part.identifier,
            a,
            b,
            math.dist(a, b),
            (math.degrees(math.atan2(b[1] - a[1], a[0] - b[0])) + geometry.orientation_deg) % 360,
            tuple(range(part.floors)),
            part.storey_elevations_m,
        )
        for part in geometry.parts
        for fid, a, b in facade_edges(part.footprint.polygon, part.identifier)
    )
