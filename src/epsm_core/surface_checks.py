# File: surface_checks.py
# Purpose: Engine-independent checks of emitted epJSON surfaces and openings.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-13
# Changelog:
#   2026-09-13 - Share a small safety margin for geometry created by Core.
#   2026-09-11 - Assert geometry invariants, exact adjacency and validated edge tolerances.
#   2026-09-06 - Document surface_checks interfaces, examples, constraints and processing rationale.

"""Engine-independent checks of emitted epJSON surfaces and openings.

Notes
-----
Checks operate on emitted epJSON without executing EnergyPlus. They validate polygon
planarity, reciprocal construction order, outward volume, directed-edge closure and
contained nonoverlapping openings. Numerical tolerances are explicit and do not repair
failed geometry.

Examples
--------
Example::

    from epsm_core.surface_checks import properties

    import numpy as np

    area, normal, drop = properties(
        np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
    )
    assert area == 2 and drop == 2
"""

from collections import defaultdict
from itertools import product

import numpy as np
from shapely.geometry import Polygon

# Pinned 24.2 GetVertices probes reject distances <0.01 m. Keep a 1 µm margin.
MIN_EDGE_M = 0.010001
# Geometry generators use a slightly larger margin so coordinate serialization cannot
# move a valid edge back onto the engine boundary.
MIN_GENERATED_EDGE_M = 0.01001


def vertices(obj):
    """Decode either supported epJSON vertex representation into a numeric array.

    Parameters
    ----------
    obj : dict
        One epJSON surface or opening object with coordinate fields.

    Returns
    -------
    numpy.ndarray
        Shape (N, 3), preserving source order.

    Notes
    -----
    Accepts detailed surfaces with a vertices list or fenestration objects with numbered
    coordinate fields. Missing fields propagate KeyError.

    Examples
    --------
    Example::

        from epsm_core.surface_checks import vertices

        obj = {
            "vertices": [
                {
                    "vertex_x_coordinate": 0,
                    "vertex_y_coordinate": 0,
                    "vertex_z_coordinate": 0,
                }
            ]
        }
        assert vertices(obj).shape == (1, 3)
    """

    # 1. Decode either supported epJSON vertex representation into a numeric array.
    if "vertices" in obj:
        return np.array([[v[f"vertex_{a}_coordinate"] for a in "xyz"] for v in obj["vertices"]])
    return np.array(
        [
            [obj[f"vertex_{i}_{a}_coordinate"] for a in "xyz"]
            for i in range(1, int(obj["number_of_vertices"]) + 1)
        ]
    )


def properties(v):
    """Validate a planar polygon and compute its area and unit normal.

    Parameters
    ----------
    v : array_like
        Ordered three-dimensional metric surface vertices; winding controls the normal.

    Returns
    -------
    tuple
        Area in m2, outward unit normal and dominant axis index to drop for projection.

    Raises
    ------
    ValueError
        Rejected conditions: Nonfinite or zero-area surface; Nonplanar surface; Self-
        intersecting surface.

    Notes
    -----
    Uses the area vector from successive cross products. Rejects area <=1e-8 m2, nonfinite
    coordinates, nonplanarity above 1e-6 m and self-intersection. Vertex winding defines
    normal direction.

    Examples
    --------
    Example::

        from epsm_core.surface_checks import properties

        import numpy as np

        area, normal, drop = properties(
            np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
        )
        assert area == 2 and drop == 2
    """

    # 1. Validate a planar polygon and compute its area and unit normal.
    v = np.asarray(v, dtype=float)
    if v.ndim != 2 or v.shape[1] != 3 or len(v) < 3 or not np.isfinite(v).all():
        raise ValueError("Nonfinite or zero-area surface")
    edges = np.roll(v, -1, axis=0) - v
    lengths = np.linalg.norm(edges, axis=1)
    if np.any(lengths < MIN_EDGE_M):
        raise ValueError(
            f"Near-coincident consecutive surface vertices; minimum edge {MIN_EDGE_M} m"
        )
    if np.any(
        np.linalg.norm(np.cross(edges, np.roll(edges, 1, axis=0)), axis=1)
        <= 1e-10 * lengths * np.roll(lengths, 1)
    ):
        raise ValueError("Collinear surface vertex contributes no boundary")
    local = v - v[0]
    normal = np.sum(np.cross(local, np.roll(local, -1, axis=0)), axis=0) / 2
    area = np.linalg.norm(normal)
    if not np.isfinite(v).all() or area <= 1e-8:
        raise ValueError("Nonfinite or zero-area surface")
    normal /= area
    if np.max(np.abs((v - v[0]) @ normal)) > 1e-6:
        raise ValueError("Nonplanar surface")
    drop = int(np.argmax(abs(normal)))
    p = Polygon(np.delete(v, drop, axis=1))
    if not p.is_valid:
        raise ValueError("Self-intersecting surface")
    return float(area), normal, drop


def close(a, b):
    """Compare scalars with shared absolute and relative geometry tolerances.

    Parameters
    ----------
    a : float
        First scalar in the same units as b.
    b : float
        Second scalar in the same units as a.

    Returns
    -------
    bool
        Whether difference is within max(1e-6, 1e-8 * largest magnitude).

    Notes
    -----
    Inputs must use the same units. This helper does not perform unit conversion or finite-
    value validation.

    Examples
    --------
    Example::

        from epsm_core.surface_checks import close

        assert close(1.0, 1.0 + 1e-7)
    """

    return abs(a - b) <= max(1e-6, 1e-8 * max(abs(a), abs(b)))


def validate_surfaces(model, zones):
    """Validate closed zones, reciprocal faces, construction order and openings.

    Parameters
    ----------
    model : dict
        EnergyPlus epJSON object mapping keyed by object type and name.
    zones : dict
        Zone metadata keyed by name, including expected volume_m3.

    Returns
    -------
    dict
        Passed status, reconciled zone volumes and surface/opening counts.

    Raises
    ------
    ValueError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    Checks outward volume, area-vector closure and directed edge incidence, including
    T-junction noding. Windows must be coplanar, inside their parent and nonoverlapping.
    Raises at the first failed invariant.

    Examples
    --------
    Supply the matching CompilationReport as ``report``; the matching compiled epJSON
    dictionary as ``model``.

    Example::

        from epsm_core.surface_checks import validate_surfaces

        validation = validate_surfaces(model, report.data["zones"])
    """

    # 1. Validate closed zones, reciprocal faces, construction order and openings.
    surfaces = model.get("BuildingSurface:Detailed", {})
    by_zone = defaultdict(list)
    signatures = {}
    volumes, area_vectors = defaultdict(float), defaultdict(lambda: np.zeros(3))
    for name, obj in surfaces.items():
        if obj["zone_name"] not in zones:
            raise ValueError(f"Surface has unknown zone: {name}")
        v = vertices(obj)
        area, normal, drop = properties(v)
        signature = (obj["zone_name"], tuple(sorted(map(tuple, v))))
        if signature in signatures:
            raise ValueError(f"Duplicate thermal surfaces: {signatures[signature]} and {name}")
        signatures[signature] = name
        kind = obj.get("surface_type")
        if kind == "Floor" and normal[2] >= -1e-8:
            raise ValueError(f"Floor normal is not downward: {name}")
        if kind in ("Roof", "Ceiling") and normal[2] <= 1e-8:
            raise ValueError(f"Roof/ceiling normal is not upward: {name}")
        # Kiva consumes one complete slab polygon, including concave outlines.
        # Other horizontal receivers retain the convex tessellation requirement.
        if np.ptp(v[:, 2]) < 1e-6 and not (
            kind == "Floor" and obj["outside_boundary_condition"] == "Foundation"
        ):
            polygon = Polygon(v[:, :2])
            if len(v) > 4 or polygon.convex_hull.area - polygon.area > 1e-8:
                raise ValueError(
                    f"Horizontal receiving surface must be convex with <=4 vertices: {name}"
                )
        by_zone[obj["zone_name"]].append((name, v))
        volumes[obj["zone_name"]] += area * np.dot(v[0], normal) / 3
        area_vectors[obj["zone_name"]] += normal * area
        if obj["outside_boundary_condition"] == "Surface":
            adjacent = obj["outside_boundary_condition_object"]
            other = surfaces.get(adjacent)
            if not other or other["outside_boundary_condition_object"] != name:
                raise ValueError(f"Nonreciprocal adjacency: {name}")
            w = vertices(other)
            if len(v) != len(w) or not any(
                np.array_equal(v, np.roll(w[::-1], i, axis=0)) for i in range(len(v))
            ):
                raise ValueError(f"Adjacency vertices or normals mismatch: {name}")
            c, d = obj["construction_name"], other["construction_name"]

            def layers(role):
                """Read a construction's material sequence from the enclosing model.

                Parameters
                ----------
                role : str
                    Construction role or emitted construction name, including reverse suffix where
                    needed.

                Returns
                -------
                list
                    Material references in emitted insertion order.

                Notes
                -----
                A missing construction gives an empty list, allowing geometry-only graphs to undergo
                reciprocal checks without material definitions.

                Examples
                --------
                Within the enclosing operation, after its captured state has been initialized::

                    layers("wall")
                """

                return list(model.get("Construction", {}).get(role, {}).values())

            if layers(c) != layers(d)[::-1]:
                raise ValueError(f"Reciprocal constructions not reversed: {name}")
    if set(by_zone) != set(zones):
        raise ValueError("Zone lacks generated boundary surfaces")
    # 2. Reconcile oriented volume, area-vector closure and split-edge incidence per zone.
    for zone, faces in by_zone.items():
        if volumes[zone] <= 0 or not close(volumes[zone], zones[zone]["volume_m3"]):
            raise ValueError(
                f"Zone volume/outward normals do not reconcile: {zone}: {volumes[zone]}"
            )
        if np.linalg.norm(area_vectors[zone]) > 1e-6:
            raise ValueError(f"Zone boundary area vectors do not close: {zone}")
        # Node collinear 3-D boundary segments at all zone vertices, including T junctions.
        points = np.unique(np.concatenate([v for _, v in faces]), axis=0)
        incidence = defaultdict(list)
        # Canonical identities use the same metric tolerance as edge noding.
        # Decimal rounding alone can split coincident vertices across a midpoint.
        buckets, identities = defaultdict(list), {}
        for point in points:
            key = tuple(np.floor(point / 1e-7).astype(int))
            candidates = [
                q
                for delta in product((-1, 0, 1), repeat=3)
                for q in buckets[tuple(k + d for k, d in zip(key, delta))]
                if np.linalg.norm(point - np.array(q)) < 1e-7
            ]
            identity = min(candidates) if candidates else tuple(point)
            identities[tuple(point)] = identity
            buckets[key].append(identity)
        for name, v in faces:
            for a, b in zip(v, np.roll(v, -1, axis=0)):
                direction = b - a
                length = np.linalg.norm(direction)
                if length < 1e-8:
                    raise ValueError(f"Collapsed edge: {name}")
                t = (points - a) @ direction / (length * length)
                distance = np.linalg.norm(points - a - t[:, None] * direction, axis=1)
                # Reuse actual vertices when noding. Reconstructing b as a + (b-a),
                # or projecting an existing T-junction, can cross a decimal rounding
                # midpoint and assign opposite faces different edge identities.
                nodes = {0.0: identities[tuple(a)], 1.0: identities[tuple(b)]}
                mask = (distance < 1e-7) & (t > 1e-8) & (t < 1 - 1e-8)
                for position, point in zip(t[mask], points[mask]):
                    nodes[float(position)] = identities[tuple(point)]
                ts = sorted(nodes)
                for start, end in zip(ts, ts[1:]):
                    u, w = nodes[start], nodes[end]
                    if u != w:  # Equivalent split parameters can differ by floating-point noise.
                        incidence[tuple(sorted((u, w)))].append((u, w))
        if any(len(pair) != 2 or pair[0] != pair[1][::-1] for pair in incidence.values()):
            raise ValueError(
                f"Zone has open, overlapping or inconsistently oriented boundary edges: {zone}"
            )
    # 3. Validate shading polygons even though they do not enclose thermal zones.
    shade_signatures = {}
    for category in ("Shading:Building:Detailed", "Shading:Site:Detailed"):
        for name, obj in model.get(category, {}).items():
            points = vertices(obj)
            properties(points)
            signature = tuple(sorted(tuple(p) for p in np.round(points, 8)))
            if signature in shade_signatures:
                raise ValueError(
                    f"Duplicate shading surfaces: {shade_signatures[signature]} and {name}"
                )
            shade_signatures[signature] = name
    # 4. Require coplanar contained windows and reject overlaps within each parent.
    openings = defaultdict(list)
    for name, obj in model.get("FenestrationSurface:Detailed", {}).items():
        parent = surfaces.get(obj["building_surface_name"])
        if not parent:
            raise ValueError(f"Window missing parent: {name}")
        v, w = vertices(parent), vertices(obj)
        _, normal, drop = properties(v)
        _, window_normal, _ = properties(w)
        if np.dot(normal, window_normal) < 1 - 1e-8:
            raise ValueError(f"Window normal differs from parent surface: {name}")
        # Same sub-micrometre tolerance as boundary noding: clipped panes are
        # lifted from a common facade frame and may differ by nanometres.
        if np.max(abs((w - v[0]) @ normal)) > 1e-6 or not Polygon(
            np.delete(v, drop, axis=1)
        ).buffer(1e-7).covers(Polygon(np.delete(w, drop, axis=1))):
            raise ValueError(f"Window outside parent surface: {name}")
        p = Polygon(np.delete(w, drop, axis=1))
        if any(p.intersection(q).area > 1e-8 for q in openings[obj["building_surface_name"]]):
            raise ValueError(f"Overlapping windows: {name}")
        openings[obj["building_surface_name"]].append(p)
    return dict(
        status="passed",
        zone_volumes_m3=dict(volumes),
        surface_count=len(surfaces),
        opening_count=sum(map(len, openings.values())),
        tolerance="max(1e-6 absolute, 1e-8 relative)",
    )
