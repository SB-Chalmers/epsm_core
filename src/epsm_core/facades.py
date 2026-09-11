# File: facades.py
# Purpose: Deterministic facade-local openings and geometric shading, shared by all consumers.
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
#   2026-09-11 - Generate facade openings and shading with shared graph vertices.
#   2026-09-06 - Document facades interfaces, examples, constraints and processing rationale.

"""Deterministic facade-local openings and geometric shading, shared by all consumers.

Notes
-----
Logical windows are placed on original facade/storey runs and then intersected with
thermal parent faces. Shading uses logical geometry so pane subdivision does not
duplicate reveals or overhangs. Wall panelization requires reopening resolution
afterward.

Examples
--------
Example::

    from epsm_core.facades import window_rectangles

    from epsm_core.specs import WindowLayoutSpec

    rects, label = window_rectangles(10, 3, 0.2, WindowLayoutSpec())
    assert label == "scaled" and len(rects) == 1
"""

import math
from dataclasses import dataclass

import numpy as np
from shapely import unary_union
from shapely.geometry import Polygon, box


@dataclass(frozen=True)
class Opening:
    """One thermal pane linked to its parent wall and logical window.

    Attributes
    ----------
    name : str
        Identifier or field name interpreted by the current operation.  Required at
        construction.
    parent : str
        Thermal parent surface name for a pane.  Required at construction.
    vertices : list
        Ordered three-dimensional metric surface vertices; winding controls the normal.
        Required at construction.
    area : float
        Geometric pane or surface area in square metres.  Required at construction.
    metadata : dict
        Facade, storey, logical-window and other provenance fields.  Required at
        construction.

    Notes
    -----
    A physical window can be split into multiple Opening records by thermal partitions. area
    is pane area in m2; metadata retains logical vertices and facade/storey identity. Frozen
    fields do not deeply freeze vertices or metadata.

    Examples
    --------
    Example::

        from epsm_core.facades import Opening

        opening = Opening(
            "pane",
            "wall",
            [(0, 0, 1), (1, 0, 1), (1, 0, 2), (0, 0, 2)],
            1,
            {"logical_window": "window_0"},
        )
    """

    name: str
    parent: str
    vertices: list
    area: float
    metadata: dict


def _minimize(f, lo, hi):
    """Search a bounded scalar objective using sampled minima and golden sections.

    Parameters
    ----------
    f : callable
        Scalar objective evaluated repeatedly within the search interval.
    lo : float
        Lower or upper bounded-search coordinate.
    hi : float
        Lower or upper bounded-search coordinate.

    Returns
    -------
    float
        Candidate coordinate with the smallest evaluated objective.

    Notes
    -----
    Evaluates 65 samples and refines sampled local minima for 45 iterations. Endpoints are
    included; narrow unsampled minima can be missed, so this is not a proof of global
    optimality.

    Examples
    --------
    Example::

        from epsm_core.facades import _minimize

        assert abs(_minimize(lambda x: (x - 2) ** 2, 0, 4) - 2) < 1e-6
    """
    # 1. Search a bounded scalar objective using sampled minima and golden sections.
    if hi - lo < 1e-10:
        return lo
    # NOTE: Sampling can miss narrow minima; this bounded search is not a global certificate.
    xs = np.linspace(lo, hi, 65)
    ys = [f(x) for x in xs]
    candidates = [(ys[0], lo), (ys[-1], hi)]
    for i in range(1, len(xs) - 1):
        if ys[i] <= ys[i - 1] and ys[i] <= ys[i + 1]:
            a, b = xs[i - 1], xs[i + 1]
            for _ in range(45):
                c, d = a + (b - a) * 0.38196601125, a + (b - a) * 0.61803398875
                if f(c) <= f(d):
                    b = d
                else:
                    a = c
            x = (a + b) / 2
            candidates.append((f(x), x))
    return float(min(candidates)[1])


def window_rectangles(length, height, wwr, layout):
    """Place feasible rectangular windows in wall-local metric coordinates.

    Parameters
    ----------
    length : float
        Positive facade-run horizontal length in metres.
    height : float
        Positive wall height above the run bottom, in metres.
    wwr : float
        Dimensionless window-to-wall area fraction; upstream FacadeSpec restricts it below
        0.95.
    layout : WindowLayoutSpec
        Window placement mode, preferred patterns and dimensional bounds.

    Returns
    -------
    tuple
        List of (left, sill, right, head) bounds and selected pattern label.

    Raises
    ------
    ValueError
        Rejected conditions: Explicit windows do not fit wall height/length or minimum
        opening gap; Window count exceeds 10000 on one facade run.

    Notes
    -----
    Scaled mode preserves WWR by square-root scaling and ignores explicit sill/dimension
    controls. Dimension mode follows dimensions rather than WWR. WWR mode searches bounded
    counts and dimensions, rejecting infeasible targets instead of reducing glazing
    silently.

    Examples
    --------
    Example::

        from epsm_core.facades import window_rectangles

        from epsm_core.specs import WindowLayoutSpec

        rects, label = window_rectangles(10, 3, 0.2, WindowLayoutSpec())
        assert label == "scaled" and len(rects) == 1
    """
    # 1. Place feasible rectangular windows in wall-local metric coordinates.
    label = layout.pattern
    if label == "auto":
        label = (
            "low"
            if wwr < layout.low_threshold
            else "high"
            if wwr > layout.high_threshold
            else "mid"
        )
    p = getattr(layout, label)
    sill = layout.sill_height_m
    if layout.sill_height_ratio is not None:
        sill = height * layout.sill_height_ratio
    # 2. Select placement behavior; dimension-driven layouts need not match requested WWR.
    # NOTE: This mode follows WWR alone; explicit sill and dimension inputs are not applied.
    if layout.mode == "scaled":
        if not wwr:
            return [], "scaled"
        f = math.sqrt(wwr)
        return [
            ((1 - f) * length / 2, (1 - f) * height / 2, (1 + f) * length / 2, (1 + f) * height / 2)
        ], "scaled"
    if layout.mode == "dimensions":
        w, h, spacing = layout.window_width_m, layout.window_height_m, layout.center_spacing_m
        s = p.sill_m if sill is None else sill
        if spacing < w + p.gap_m or s + h > height - p.head_m + 1e-9 or w > length - 2 * p.end_m:
            raise ValueError(
                "Explicit windows do not fit wall height/length or minimum opening gap"
            )
        n = max(1, int((length - 2 * p.end_m - w) / spacing + 1 + 1e-9))
    else:
        if not wwr:
            return [], label
        smin, smax = (p.min_sill_m, p.max_sill_m) if sill is None else (sill, sill)
        wmin = layout.window_width_m or p.min_width_m
        wmax = layout.window_width_m or p.max_width_m
        hmin = layout.window_height_m or p.min_height_m
        hmax = min(layout.window_height_m or p.max_height_m or height, height - p.head_m - smin)
        usable = length - 2 * p.end_m
        target = length * height * wwr
        candidates, intervals = [], []
        max_count = max(0, int((usable + p.gap_m) / (wmin + p.gap_m)))
        if max_count > 10000:
            raise ValueError("Window count exceeds 10000 on one facade run")
        # 3. Search only geometrically feasible counts before optimizing preferred dimensions.
        for count in range(1, max_count + 1):
            maxw = min(
                wmax,
                (usable - (count - 1) * p.gap_m) / count,
                p.max_spacing_m - p.gap_m if count > 1 else wmax,
            )
            if maxw < wmin or hmax < hmin:
                continue
            intervals.append(
                (count * wmin * hmin / (length * height), count * maxw * hmax / (length * height))
            )
            low, high = max(hmin, target / count / maxw), min(hmax, target / count / wmin)
            if low > high + 1e-10:
                continue

            def dimensions(h):
                """Derive width, sill and spacing for the active window count and height.

                Parameters
                ----------
                h : float
                    Candidate window height in metres within the active feasible interval.

                Returns
                -------
                tuple
                    Width, sill and centre spacing in metres.

                Notes
                -----
                Preserves target area exactly through width = target / count / height, then respects
                sill and spacing bounds from the enclosing search.

                Examples
                --------
                Within the enclosing operation, after its captured state has been initialized::

                    dimensions(1.2)
                """

                # 1. Derive width, sill and spacing for the active window count and height.
                w = target / count / h
                s = min(max(p.sill_m if sill is None else sill, smin), smax, height - p.head_m - h)
                maxspace = (usable - w) / (count - 1) if count > 1 else p.max_spacing_m
                spacing = min(layout.center_spacing_m or p.spacing_m, p.max_spacing_m, maxspace)
                spacing = max(spacing, w + p.gap_m)
                return w, s, spacing

            def score(h):
                """Score deviation from preferred window dimensions and spacing.

                Parameters
                ----------
                h : float
                    Candidate window height in metres within the active feasible interval.

                Returns
                -------
                float
                    Sum of normalized squared deviations.

                Notes
                -----
                The score chooses among geometrically feasible windows; denominators for height and sill
                are bounded to avoid excessive scaling near zero.

                Examples
                --------
                Within the enclosing operation, after its captured state has been initialized::

                    score(1.2)
                """

                # 1. Score deviation from preferred window dimensions and spacing.
                w, s, spacing = dimensions(h)
                preferred_h = p.height_m or height - p.head_m - (p.sill_m if sill is None else sill)
                return (
                    ((w - p.width_m) / p.width_m) ** 2
                    + ((h - preferred_h) / max(preferred_h, 0.1)) ** 2
                    + ((s - p.sill_m) / max(p.sill_m, 0.1)) ** 2
                    + ((spacing - p.spacing_m) / p.spacing_m) ** 2
                )

            h = _minimize(score, low, max(low, high))
            w, s, spacing = dimensions(h)
            if layout.center_spacing_m is not None:
                spacing = layout.center_spacing_m
                if spacing < w + p.gap_m or (count - 1) * spacing + w > usable + 1e-8:
                    continue
            candidates.append((score(h), count, w, h, s, spacing))
        if not candidates:
            ranges = ", ".join(f"{a:.4f}–{b:.4f}" for a, b in intervals)
            raise ValueError(
                f"Infeasible WWR {wwr:g} for {length:g} × {height:g} m {label} facade; achievable WWR intervals [{ranges}]; check width, sill, height, head/end margins and spacing bounds"
            )
        _, n, w, h, s, spacing = min(candidates)
    # 4. Centre the chosen run while preserving margins, spacing and exact dimensions.
    start = (length - ((n - 1) * spacing + w)) / 2
    return [(start + i * spacing, s, start + i * spacing + w, s + h) for i in range(n)], label


def resolve_openings(spec, graph):
    """Place logical windows on original facade runs and split them among thermal parents.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    graph : SurfaceGraph
        Mutable resolved surfaces, zone metrics, internal slabs and geometry reports.

    Returns
    -------
    tuple
        Opening records and per-parent facade reports.

    Raises
    ------
    ValueError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    Facade-local coordinates are rounded to 1e-8 m to coalesce rotation noise. A logical
    window can create several thermal panes; nonrectangular pane intersections are rejected.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; a resolved SurfaceGraph as ``graph``
    from the same building and coordinate frame.

    Example::

        from epsm_core.facades import resolve_openings

        openings, reports = resolve_openings(building, graph)
    """
    # 1. Place logical windows on original facade runs and split them among thermal parents.
    from .geometry import facade_edges, local_polygons

    polygons, _ = local_polygons(spec.geometry)
    axes = {
        fid: (part, a, b)
        for part, polygon in zip(spec.geometry.parts, polygons)
        for fid, a, b in facade_edges(polygon, part.identifier)
    }
    # 2. Group exterior main-storey walls by original facade identity, not thermal cuts.
    groups = {}
    for face in graph.surfaces:
        if face.kind == "Wall" and face.boundary == "Outdoors" and face.cell_kind == "main":
            groups.setdefault((face.facade_id, face.storey), []).append(face)
    openings, reports = [], []
    for (fid, storey), faces in sorted(groups.items()):
        layout = spec.facade.value_for("layout", fid, storey)
        wwr = spec.facade.wwr_for(fid, storey)
        part, a, b = axes[fid]
        origin = np.array([*a, part.storey_elevations_m[storey]], dtype=float)
        u = np.array([b[0] - a[0], b[1] - a[1], 0.0], dtype=float)
        u /= np.linalg.norm(u)

        def project(v):
            """Project a world vertex onto the active facade's horizontal/vertical axes.

            Parameters
            ----------
            v : array_like
                Ordered three-dimensional metric surface vertices; winding controls the normal.

            Returns
            -------
            tuple of float
                Rounded horizontal distance and relative height in metres.

            Notes
            -----
            Rounding is local to the facade and much smaller than the surface validation tolerance;
            original physical coordinates remain the reference.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                project(faces[0].vertices[0])
            """

            a = np.array(v) - origin
            # Shared thermal vertices may differ at machine precision after rotation.
            # Snap only facade-local coordinates, well below the surface validation tolerance.
            return (round(float(a @ u), 8), round(float(a[2]), 8))

        def world(x, y):
            """Lift facade-local horizontal and vertical offsets into world coordinates.

            Parameters
            ----------
            x : float
                Local horizontal coordinate in metres.
            y : float
                Local second coordinate in metres; roof helpers use plan y, facade helpers use
                relative height.

            Returns
            -------
            list of float
                Three metric coordinates.

            Notes
            -----
            Uses the active facade origin and unit horizontal axis; the second argument is elevation
            relative to the storey bottom.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                world(1.0, 0.9)
            """

            v = origin + x * u + np.array([0, 0, y])
            return v.tolist()

        # 3. Work in a common facade plane so windows can span multiple thermal parents.
        shapes = {f.name: Polygon([project(v) for v in f.vertices]) for f in faces}
        union = unary_union(list(shapes.values()))
        parts = list(union.geoms) if hasattr(union, "geoms") else [union]
        # Decompose nonrectangular exposure at changes in its horizontal extent.
        rectangles = []
        for shape in parts:
            xs = sorted({v[0] for v in shape.exterior.coords})
            for x0, x1 in zip(xs, xs[1:]):
                cut = shape.intersection(box(x0, shape.bounds[1] - 1, x1, shape.bounds[3] + 1))
                for q in list(cut.geoms) if hasattr(cut, "geoms") else [cut]:
                    if q.area > 1e-8:
                        rectangles.append(q)
        # Merge collinear splits whenever their union is rectangular.
        merged = True
        while merged:
            merged = False
            for i in range(len(rectangles)):
                for j in range(i + 1, len(rectangles)):
                    q = rectangles[i].union(rectangles[j])
                    if q.geom_type == "Polygon" and abs(q.envelope.area - q.area) < 1e-8:
                        rectangles[i] = q.envelope
                        rectangles.pop(j)
                        merged = True
                        break
                if merged:
                    break
        parts = rectangles
        # 4. Place logical windows on complete rectangular runs, then intersect each parent.
        for ri, shape in enumerate(sorted(parts, key=lambda p: p.bounds)):
            x0, y0, x1, y1 = shape.bounds
            rects, label = window_rectangles(x1 - x0, y1 - y0, wwr, layout)
            for wi, (a, b, c, d) in enumerate(rects):
                opening = box(x0 + a, y0 + b, x0 + c, y0 + d)
                logical = f"{fid}_floor{storey}_run{ri}_window{wi}"
                for face in faces:
                    piece = opening.intersection(shapes[face.name])
                    if piece.area < 1e-9:
                        continue
                    px0, py0, px1, py1 = piece.bounds
                    if abs(piece.area - piece.envelope.area) > 1e-7:
                        raise ValueError(
                            f"Window {logical} crosses a nonrectangular thermal boundary"
                        )
                    name = logical + "_" + face.name
                    metadata = dict(
                        facade_id=fid,
                        storey=storey,
                        part_id=face.part_id,
                        zone=face.zone,
                        pattern=label,
                        logical_window=logical,
                        logical_vertices=[
                            world(x0 + a, y0 + b),
                            world(x0 + c, y0 + b),
                            world(x0 + c, y0 + d),
                            world(x0 + a, y0 + d),
                        ],
                        requested_wwr=wwr if layout.mode != "dimensions" else None,
                    )
                    openings.append(
                        Opening(
                            name,
                            face.name,
                            [world(px0, py0), world(px1, py0), world(px1, py1), world(px0, py1)],
                            piece.area,
                            metadata,
                        )
                    )
        for face in faces:
            area = sum(o.area for o in openings if o.parent == face.name)
            from .geometry import cardinal

            reports.append(
                dict(
                    surface=face.name,
                    facade_id=fid,
                    part_id=face.part_id,
                    zone=face.zone,
                    storey=storey,
                    local_wwr=area / face.area,
                    requested_wwr=wwr if layout.mode != "dimensions" else None,
                    pattern=label,
                    cardinal=cardinal(face.vertices[0], face.vertices[1]),
                    gross_area_m2=face.area,
                    requested_window_area_m2=face.area * wwr
                    if layout.mode != "dimensions"
                    else None,
                    window_area_m2=area,
                )
            )
    return openings, reports


def shading_geometry(spec, graph, openings):
    """Generate reveals, overhangs and balconies from logical facade geometry.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    graph : SurfaceGraph
        Mutable resolved surfaces, zone metrics, internal slabs and geometry reports.
    openings : sequence of Opening
        Thermal panes with parent-wall and logical-window metadata.

    Returns
    -------
    list of dict
        Shading surface names, vertices, kinds and metadata.

    Raises
    ------
    ValueError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    Glazing stays coplanar with its thermal wall. Reveals and balconies are shading only. A
    coincident upper reveal is suppressed when already covered by a per-window overhang to
    bound shadow-overlap work.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; a resolved SurfaceGraph as ``graph``
    from the same building and coordinate frame; matching Opening records as ``openings``
    from resolve_openings.

    Example::

        from epsm_core.facades import shading_geometry

        shades = shading_geometry(building, graph, openings)
    """
    # 1. Generate reveals, overhangs and balconies from logical facade geometry.
    shades = []

    def add(name, verts, kind, metadata):
        """Validate and append one shading polygon to the enclosing output list.

        Parameters
        ----------
        name : str
            Identifier or field name interpreted by the current operation.
        verts : array_like
            Ordered three-dimensional metric surface vertices; winding controls the normal.
        kind : str
            Surface, object or region classification consumed by the enclosing builder.
        metadata : dict
            Physical identity and assumption fields attached to the emitted shading face.

        Returns
        -------
        None
            Mutates shades with a JSON-ready vertex list.

        Notes
        -----
        Rejects invalid, nonfinite or nonplanar surfaces through the shared properties check.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            add("shade", [(0, 0, 3), (2, 0, 3), (2, -1, 3), (0, -1, 3)], "overhang", {})
        """

        from .surface_checks import properties

        properties(np.asarray(verts))
        shades.append(dict(name=name, vertices=np.asarray(verts).tolist(), kind=kind, **metadata))

    # 2. Deduplicate logical windows before creating physical shading details.
    logical_openings = {}
    for o in openings:
        logical_openings.setdefault(o.metadata["logical_window"], o)
    for logical_name, o in logical_openings.items():
        fid, floor = o.metadata["facade_id"], o.metadata["storey"]
        depth = spec.facade.value_for("reveal_depth_m", fid, floor)
        v = np.array(o.metadata["logical_vertices"])
        u = v[1] - v[0]
        u /= np.linalg.norm(u)
        outward = np.cross(u, [0, 0, 1])
        h = spec.facade.value_for("overhang", fid, floor)
        if depth:
            for i in range(4):
                # A coincident overhang already contains the upper reveal. Emitting
                # both makes polygon shadow intersections grow exponentially.
                if i == 2 and not h.continuous and h.offset_above_m == 0 and h.depth_m >= depth:
                    continue
                a, b = v[i], v[(i + 1) % 4]
                add(
                    logical_name + f"_reveal_{i}",
                    [a, b, b + outward * depth, a + outward * depth],
                    "reveal",
                    dict(
                        parent=logical_name,
                        **{
                            k: v
                            for k, v in o.metadata.items()
                            if k not in ("zone", "logical_vertices")
                        },
                    ),
                )
        h = spec.facade.value_for("overhang", fid, floor)
        if h.depth_m and not h.continuous:
            a = v[3] - u * h.side_extension_m + [0, 0, h.offset_above_m]
            b = v[2] + u * h.side_extension_m + [0, 0, h.offset_above_m]
            add(
                logical_name + "_overhang",
                [a, b, b + outward * h.depth_m, a + outward * h.depth_m],
                "overhang",
                dict(
                    parent=logical_name,
                    **{
                        k: v for k, v in o.metadata.items() if k not in ("zone", "logical_vertices")
                    },
                ),
            )
    # Continuous overhangs and balconies use original facade coordinates, not window indices.
    from .geometry import facade_edges, local_polygons

    polygons, _ = local_polygons(spec.geometry)
    valid = set()
    # 3. Anchor continuous overhangs and balconies to source facade runs.
    for part, polygon in zip(spec.geometry.parts, polygons):
        for fid, a, b in facade_edges(polygon, part.identifier):
            valid.add(fid)
            start = np.array([*a, 0.0])
            end = np.array([*b, 0.0])
            length = np.linalg.norm(end - start)
            u = (end - start) / length
            outward = np.cross(u, [0, 0, 1])
            for floor, (bottom, top) in enumerate(
                zip(part.storey_elevations_m, part.storey_elevations_m[1:])
            ):
                faces = [
                    f
                    for f in graph.surfaces
                    if f.facade_id == fid
                    and f.storey == floor
                    and f.boundary == "Outdoors"
                    and f.cell_kind == "main"
                ]
                if not faces:
                    continue
                meta = dict(facade_id=fid, storey=floor, part_id=part.identifier)
                h = spec.facade.value_for("overhang", fid, floor)
                if h.depth_m and h.continuous:
                    levels = {}
                    # 5. Retain per-parent area evidence so pane splitting remains auditable.
                    for face in faces:
                        va, vb = np.array(face.vertices[3]), np.array(face.vertices[2])
                        z = round(float(va[2]), 8)
                        levels.setdefault(z, []).append(
                            sorted((float((va - start) @ u), float((vb - start) @ u)))
                        )
                    for z, spans in sorted(levels.items()):
                        merged = []
                        for lo, hi in sorted(spans):
                            if merged and lo <= merged[-1][1] + 1e-7:
                                merged[-1][1] = max(hi, merged[-1][1])
                            else:
                                merged.append([lo, hi])
                        for index, (lo, hi) in enumerate(merged):
                            va = (
                                start + u * (lo - h.side_extension_m) + [0, 0, z + h.offset_above_m]
                            )
                            vb = (
                                start + u * (hi + h.side_extension_m) + [0, 0, z + h.offset_above_m]
                            )
                            add(
                                f"{fid}_floor{floor}_z{z:g}_overhang{index}",
                                [va, vb, vb + outward * h.depth_m, va + outward * h.depth_m],
                                "overhang",
                                meta,
                            )
                for bi, bal in enumerate(spec.facade.balconies):
                    if bal.facade_id != fid or (bal.storeys and floor not in bal.storeys):
                        continue
                    if bal.start_m + bal.width_m > length + 1e-8:
                        raise ValueError(f"Balcony {bi} extends beyond facade {fid}")
                    a = start + u * bal.start_m + [0, 0, bottom + bal.elevation_above_floor_m]
                    b = a + u * bal.width_m
                    c = b + outward * bal.depth_m
                    d = a + outward * bal.depth_m
                    name = f"balcony_{bi}_floor{floor}"
                    add(name, [a, b, c, d], "balcony", meta)
                    for suffix, x, y, height in (
                        ("left", a, d, bal.side_screen_height_m),
                        ("right", b, c, bal.side_screen_height_m),
                        ("front", d, c, bal.front_screen_height_m),
                    ):
                        if height:
                            add(
                                name + "_" + suffix,
                                [x, y, y + [0, 0, height], x + [0, 0, height]],
                                "balcony",
                                meta,
                            )
    # 4. Reject stale facade/storey references even when no shade was generated for them.
    for b in spec.facade.balconies:
        part = next(
            (p for p in spec.geometry.parts if b.facade_id.startswith(p.identifier + ".r")), None
        )
        if part is not None and any(s >= part.floors for s in b.storeys):
            raise ValueError(f"Balcony references nonexistent storey on {b.facade_id}")
        if b.facade_id not in valid:
            raise ValueError(f"Balcony references unknown facade {b.facade_id}")
    return shades


def panelize_receiving_walls(graph, openings):
    """Split opaque receiving walls at gaps between thermal windows.

    Parameters
    ----------
    graph : SurfaceGraph
        Mutable resolved surfaces, zone metrics, internal slabs and geometry reports.
    openings : sequence of Opening
        Thermal panes with parent-wall and logical-window metadata.

    Returns
    -------
    SurfaceGraph
        The same graph with its surface list replaced.

    Notes
    -----
    Assumes rectangular vertical receiving walls. Window objects still reference old parents
    until resolve_openings is called again by the shared pipeline; do not consume the
    intermediate graph and old openings together.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; a resolved SurfaceGraph as ``graph``
    from the same building and coordinate frame; matching Opening records as ``openings``
    from resolve_openings.

    Example::

        from epsm_core.facades import panelize_receiving_walls
        from epsm_core.facades import resolve_openings

        graph = panelize_receiving_walls(graph, openings)
        openings, reports = resolve_openings(building, graph)
    """
    # 1. Split opaque receiving walls at gaps between thermal windows.
    from dataclasses import replace

    byparent = {}
    for opening in openings:
        byparent.setdefault(opening.parent, []).append(opening)
    surfaces = []
    # 2. Keep uncut faces or subdivide at clear gaps; never cut through a window span.
    for face in graph.surfaces:
        windows = byparent.get(face.name, [])
        if len(windows) < 2:
            surfaces.append(face)
            continue
        v = np.asarray(face.vertices)
        origin = v[0]
        u = v[1] - origin
        length = np.linalg.norm(u)
        u /= length
        height = v[3][2] - v[0][2]
        spans = sorted(
            (
                float((np.asarray(o.vertices[0]) - origin) @ u),
                float((np.asarray(o.vertices[1]) - origin) @ u),
            )
            for o in windows
        )
        cuts = [
            0,
            *[(b + c) / 2 for (a, b), (c, d) in zip(spans, spans[1:]) if c > b + 1e-8],
            length,
        ]
        for i, (a, b) in enumerate(zip(cuts, cuts[1:])):
            bottom = [origin + a * u, origin + b * u]
            verts = [*bottom, bottom[1] + [0, 0, height], bottom[0] + [0, 0, height]]
            surfaces.append(
                replace(
                    face,
                    name=face.name + f"_panel{i}",
                    vertices=graph.vertex_pool.ring(verts),
                    area=(b - a) * height,
                )
            )
    graph.surfaces = surfaces
    return graph
