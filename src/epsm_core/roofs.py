# File: roofs.py
# Purpose: Validated pitched attic shells; skeleton failures never become flat roofs.
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
#   2026-09-06 - Document roofs interfaces, examples, constraints and processing rationale.

"""Validated pitched attic shells; skeleton failures never become flat roofs.

Notes
-----
Pitched roofs use plane-based gable/mono-pitch geometry or the optional straight-
skeleton backend for hips. Projected coverage, orientation and overlap checks prevent
silent loss of courtyards or roof area. Failed generation is never replaced by a flat
roof here.

Examples
--------
Example::

    from epsm_core.roofs import roof_faces

    from shapely.geometry import box
    from epsm_core.specs import RoofSpec

    faces = roof_faces(box(0, 0, 20, 10), RoofSpec(shape="gable"), 6)
"""

import math
from importlib.metadata import PackageNotFoundError, version

import numpy as np
from shapely import constrained_delaunay_triangles, unary_union
from shapely.geometry import LineString, Polygon
from shapely.ops import split

from .geometry import facade_edges
from .surface_checks import properties


def backend_versions():
    """Report the installed optional straight-skeleton distribution version.

    Returns
    -------
    dict
        py_straight_skeleton version string, or None when absent.

    Notes
    -----
    Metadata discovery does not import or execute the geometry backend. The report
    contributes to compiler run identity.

    Examples
    --------
    Example::

        from epsm_core.roofs import backend_versions

        assert "py_straight_skeleton" in backend_versions()
    """

    try:
        return {"py_straight_skeleton": version("py_straight_skeleton")}
    except PackageNotFoundError:
        return {"py_straight_skeleton": None}


def skeleton(polygon):
    """Compute a straight skeleton from consistently oriented polygon rings.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.

    Returns
    -------
    object
        Backend skeleton with nodes, faces and arc iterator.

    Raises
    ------
    ValueError
        Rejected conditions: Hip roofs and skeleton circulation require epsm_core[geometry].

    Notes
    -----
    Requires epsm_core[geometry]. Backend failures become ValueError with their original
    cause; no flat-roof fallback is supplied.

    Examples
    --------
    Install epsm_core[geometry] for the straight-skeleton backend.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.roofs import skeleton

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygon = geometry.footprints[0].polygon
        sk = skeleton(polygon)
    """

    # 1. Compute a straight skeleton from consistently oriented polygon rings.
    try:
        from py_straight_skeleton import compute_skeleton
    except ImportError as exc:
        raise ValueError("Hip roofs and skeleton circulation require epsm_core[geometry]") from exc
    try:
        from shapely.geometry.polygon import orient

        p = orient(polygon, sign=1)
        return compute_skeleton(
            list(p.exterior.coords)[:-1], [list(r.coords)[:-1] for r in p.interiors]
        )
    except Exception as exc:
        raise ValueError(f"Straight skeleton failed: {exc}") from exc


def dominant_direction(polygon):
    """Find the long-axis angle of the minimum rotated rectangle.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.

    Returns
    -------
    float
        Counterclockwise angle from +X in [0, 180).

    Notes
    -----
    Valid nondegenerate polygon input is required. Equal-length edges use tuple ordering for
    a deterministic tie-break.

    Examples
    --------
    Example::

        from epsm_core.roofs import dominant_direction

        from shapely.geometry import box

        assert dominant_direction(box(0, 0, 20, 10)) == 0
    """

    # 1. Find the long-axis angle of the minimum rotated rectangle.
    with np.errstate(divide="ignore", invalid="ignore"):
        points = list(polygon.minimum_rotated_rectangle.exterior.coords)
    edges = [(math.dist(a, b), a, b) for a, b in zip(points, points[1:])]
    _, a, b = max(edges)
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def roof_faces(polygon, roof, base, orientation=0):
    """Construct upward-oriented pitched roof triangles preserving footprint coverage.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    roof : RoofSpec
        Effective pitched-roof geometry and direction controls.
    base : float
        Vertical elevation in metres in the current scene datum.
    orientation : float
        Clockwise scene orientation in degrees from the source frame. Default: ``0``.

    Returns
    -------
    list
        Triangles of world (x, y, z) coordinates in metres.

    Raises
    ------
    ValueError
        Rejected conditions: Roof has vertical or degenerate face; Invalid skeleton roof
        face; Roof faces overlap or fail to preserve footprint/courtyard coverage.

    Notes
    -----
    Intended for mono_pitch, gable or hip roofs. Gable direction denotes ridge azimuth,
    mono-pitch direction denotes upslope. Hip roofs use skeleton node heights. Degenerate
    facets are discarded only below tolerance; coverage and overlaps are checked
    independently.

    Examples
    --------
    Example::

        from epsm_core.roofs import roof_faces

        from shapely.geometry import box
        from epsm_core.specs import RoofSpec

        faces = roof_faces(box(0, 0, 20, 10), RoofSpec(shape="gable"), 6)
    """

    # 1. Construct upward-oriented pitched roof triangles preserving footprint coverage.
    slope = math.tan(math.radians(roof.pitch))
    faces = []
    if roof.shape == "hip":
        sk = skeleton(polygon)
        for indices in sk.get_faces():
            v = [
                [sk.nodes[i].position.x, sk.nodes[i].position.y, base + sk.nodes[i].time * slope]
                for i in indices
            ]
            if len(v) >= 3:
                faces.append(v)
    else:
        angle = (
            dominant_direction(polygon)
            if roof.direction_deg is None
            else 90 - roof.direction_deg - orientation
        )
        # Direction is the ridge for gables, upslope azimuth for mono-pitch.
        u = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
        if roof.shape == "gable":
            u = np.array([-u[1], u[0]])
        coords = np.array(polygon.exterior.coords)
        lo, hi = min(coords @ u), max(coords @ u)
        mid = (lo + hi) / 2

        def z(x, y):
            """Evaluate roof-plane elevation from the active projected slope direction.

            Parameters
            ----------
            x : float
                Local horizontal coordinate in metres.
            y : float
                Local second coordinate in metres; roof helpers use plan y, facade helpers use
                relative height.

            Returns
            -------
            float
                Height in metres above the scene datum.

            Notes
            -----
            Captures base, slope and projected footprint span. Gables use the nearer eave distance;
            mono-pitch uses one upslope distance.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                z(0, 0)
            """

            distance = np.array([x, y]) @ u - lo
            if roof.shape == "gable":
                distance = min(distance, hi - lo - distance)
            return base + max(0, float(distance)) * slope

        patches = [polygon]
        if roof.shape == "gable":
            center = u * mid
            direction = np.array([-u[1], u[0]])
            reach = max(1, polygon.length) * 4
            patches = list(
                split(
                    polygon, LineString([center - direction * reach, center + direction * reach])
                ).geoms
            )
        for patch in patches:
            for t in constrained_delaunay_triangles(patch).geoms:
                faces.append([[x, y, z(x, y)] for x, y in list(t.exterior.coords)[:-1]])
    # 2. Normalize facet orientation and independently track projected roof coverage.
    footprints = []
    normalized = []
    for v in faces:
        # Plane clipping at a reflex corner can produce a numerical sliver.
        # Coverage is checked independently below, so discarding sub-tolerance
        # facets cannot silently remove a material piece of the roof.
        if Polygon([(x, y) for x, y, _ in v]).area <= 1e-10:
            continue
        area, normal, _ = properties(np.array(v))
        if normal[2] < 0:
            v = v[::-1]
        if abs(normal[2]) < 1e-8:
            raise ValueError("Roof has vertical or degenerate face")
        q = Polygon([(x, y) for x, y, _ in v])
        if not q.is_valid:
            raise ValueError("Invalid skeleton roof face")
        # Triangulation ensures EnergyPlus receives convex planar facets.
        origin = np.array(v[0])
        n = properties(np.array(v))[1]
        node_heights = {(x, y): z for x, y, z in v}
        for t in constrained_delaunay_triangles(q).geoms:
            if t.area <= 1e-10:
                continue
            triangle = []
            for x, y in list(t.exterior.coords)[:-1]:
                z = (
                    node_heights[(x, y)]
                    if roof.shape == "hip"
                    else origin[2] - (n[0] * (x - origin[0]) + n[1] * (y - origin[1])) / n[2]
                )
                triangle.append([x, y, float(z)])
            if properties(np.array(triangle))[1][2] < 0:
                triangle.reverse()
            normalized.append(triangle)
        footprints.append(q)
    # 3. Reject missing or overlapping projected roof area, including courtyards.
    union = unary_union(footprints)
    if (
        union.symmetric_difference(polygon).area > max(1e-7, polygon.area * 1e-8)
        or sum(p.area for p in footprints) - union.area > 1e-7
    ):
        raise ValueError("Roof faces overlap or fail to preserve footprint/courtyard coverage")
    return normalized


def apply_roofs(spec, polygons, graph):
    """Replace provisional attic shells with validated pitched roof and wall facets.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    polygons : sequence of Polygon
        Local metric footprints in the same order as geometry.parts.
    graph : SurfaceGraph
        Mutable resolved surfaces, zone metrics, internal slabs and geometry reports.

    Returns
    -------
    SurfaceGraph
        The same graph after in-place surface and zone updates.

    Raises
    ------
    ValueError
        Rejected conditions: Pitched roof has no attic cell.

    Notes
    -----
    Touching pitched parts are rejected because intersecting roof ownership is not inferred.
    Updates attic volume by integrating triangular roof heights above the base.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; a resolved SurfaceGraph as ``graph``
    from the same building and coordinate frame.

    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.roofs import apply_roofs
        from epsm_core.geometry import local_polygons

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygons, origin = local_polygons(geometry)
        graph = apply_roofs(building, polygons, graph)
    """

    # 1. Replace provisional attic shells with validated pitched roof and wall facets.
    from .topology import Surface

    for part, polygon in zip(spec.geometry.parts, polygons):
        roof = part.roof or spec.geometry.roof
        if roof.shape == "flat":
            continue
        for other, q in zip(spec.geometry.parts, polygons):
            if (
                other.identifier != part.identifier
                and polygon.boundary.intersection(q.boundary).length > 1e-7
            ):
                raise ValueError(
                    f"Pitched roof on touching part {part.identifier}: combine equal-height footprints or supply separated roof parts; intersecting part roofs are not inferred"
                )
        # 2. Replace only the active part's provisional attic shell, retaining its floor
        # boundary.
        old = [f for f in graph.surfaces if f.part_id == part.identifier and f.cell_kind == "attic"]
        if not old:
            raise ValueError("Pitched roof has no attic cell")
        zone = old[0].zone
        base = part.storey_elevations_m[-1]
        faces = roof_faces(polygon, roof, base, spec.geometry.orientation_deg)
        graph.surfaces[:] = [
            f
            for f in graph.surfaces
            if not (
                f.part_id == part.identifier
                and f.cell_kind == "attic"
                and f.kind in ("Roof", "Wall")
            )
        ]

        def add(v, kind, index, fid=""):
            """Append one validated attic roof or wall face to the enclosing graph.

            Parameters
            ----------
            v : array_like
                Ordered three-dimensional metric surface vertices; winding controls the normal.
            kind : str
                Surface, object or region classification consumed by the enclosing builder.
            index : int
                Zero-based index in the enclosing registry or generated face sequence.
            fid : str
                Original facade identity to attach to an attic wall; empty for roof facets. Default:
                ``''``.

            Returns
            -------
            None
                Adds a Surface with the active part and attic zone identity.

            Notes
            -----
            Computes geometric area before insertion; weather_shell is used for the unconditioned
            attic exterior.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                add(faces[0], "Roof", 0)
            """

            # 1. Append one validated attic roof or wall face to the enclosing graph.
            area = properties(np.array(v))[0]
            graph.surfaces.append(
                Surface(
                    f"{part.identifier}_attic_{kind}_{index}",
                    zone,
                    v,
                    kind,
                    "weather_shell",
                    "Outdoors",
                    part_id=part.identifier,
                    facade_id=fid,
                    storey=part.floors,
                    area=area,
                    cell_kind="attic",
                )
            )

        for i, v in enumerate(faces):
            add(v, "Roof", i)
        # Roof boundary vertices include ridge intersections and hole rings.
        # 3. Use ridge and boundary nodes to close gable/edge walls without mismatched cuts.
        points = {tuple(v) for face in faces for v in face}
        wi = 0
        for fid, a, b in facade_edges(polygon, part.identifier):
            line = LineString([a, b])
            candidates = []
            from shapely.geometry import Point

            for x, y, z in points:
                if line.distance(Point(x, y)) < 1e-7:
                    candidates.append((line.project(Point(x, y)), x, y, z))
            candidates = sorted(set(candidates))
            for left, right in zip(candidates, candidates[1:]):
                _, x0, y0, z0 = left
                _, x1, y1, z1 = right
                if math.dist((x0, y0), (x1, y1)) < 1e-8 or max(z0, z1) - base < 1e-8:
                    continue
                v = [[x0, y0, base], [x1, y1, base], [x1, y1, z1], [x0, y0, z0]]
                v = [p for i, p in enumerate(v) if math.dist(p, v[i - 1]) > 1e-8]
                add(v, "Wall", wi, fid)
                wi += 1
        # 4. Integrate triangular heights to update actual attic volume rather than the
        # placeholder extrusion.
        volume = sum(
            Polygon([(x, y) for x, y, _ in v]).area * sum(z - base for _, _, z in v) / 3
            for v in faces
        )
        data = graph.zones[zone]
        # A pitched part uses its own attic zone, including in whole-building mode.
        data["volume_m3"] = volume
        data["elevations_m"] = [base, max(z for face in faces for _, _, z in face)]
        data["roof_shape"] = roof.shape
    return graph
