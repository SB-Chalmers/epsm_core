"""Deterministic planar geometry, extrusion and facade identity."""

from __future__ import annotations

import math

from shapely import constrained_delaunay_triangles
from shapely.affinity import rotate, translate
from shapely.geometry import LineString
from shapely.geometry.polygon import orient


def local_polygons(geometry):
    origin = (
        min(p.polygon.bounds[0] for p in geometry.footprints),
        min(p.polygon.bounds[1] for p in geometry.footprints),
    )
    polygons = [translate(p.polygon, -origin[0], -origin[1]) for p in geometry.footprints]
    # Positive azimuth is clockwise from north, matching EnergyPlus conventions.
    return [rotate(p, -geometry.orientation_deg, origin=(0, 0)) for p in polygons], origin


def horizontal_patches(polygon):
    """Keep simple polygons intact; tessellate holes with constrained triangulation."""
    if not polygon.interiors:
        return [orient(polygon, sign=1)]
    triangles = constrained_delaunay_triangles(polygon)
    patches = sorted(
        (orient(p, sign=1) for p in triangles.geoms),
        key=lambda p: (p.centroid.x, p.centroid.y, p.area),
    )
    if abs(sum(p.area for p in patches) - polygon.area) > polygon.area * 1e-9:
        raise ValueError("Tessellation failed area conservation")
    return patches


def facade_edges(polygon, component):
    # Preserve input edge indices even when normals require reversing a ring.
    for ri, ring in enumerate((polygon.exterior, *polygon.interiors)):
        coords = list(ring.coords)[:-1]
        reverse = bool(ring.is_ccw) != (ri == 0)
        for ei, a in enumerate(coords):
            b = coords[(ei + 1) % len(coords)]
            if reverse:
                a, b = b, a
            if math.dist(a, b) < 1e-6:
                raise ValueError("Zero-length facade edge")
            yield f"c{component}.r{ri}.e{ei}", a, b


def wall_vertices(a, b, bottom, top):
    return [(a[0], a[1], bottom), (b[0], b[1], bottom), (b[0], b[1], top), (a[0], a[1], top)]


def horizontal_vertices(polygon, height, upward=True):
    coords = list(orient(polygon, sign=1).exterior.coords)[:-1]
    if not upward:
        coords.reverse()
    return [(x, y, height) for x, y in coords]


def exposed_segments(patch, whole):
    coords = list(patch.exterior.coords)[:-1][::-1]  # floor normal points downward
    values = []
    for i, a in enumerate(coords):
        line = LineString([a, coords[(i + 1) % len(coords)]])
        values.append(line.intersection(whole.boundary).length >= line.length - 1e-6)
    return values


def cardinal(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    azimuth = math.degrees(math.atan2(dy, -dx)) % 360
    return ("north", "east", "south", "west")[int((azimuth + 45) // 90) % 4]
