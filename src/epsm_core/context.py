# File: context.py
# Purpose: Inspectable surroundings and shared, engine-independent shading geometry.
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
#   2026-09-06 - Document context interfaces, examples, constraints and processing rationale.

"""Inspectable surroundings and shared, engine-independent shading geometry.

Context is expressed in the target geometry's metric coordinate frame. Synthetic
presets describe controlled scenarios, not calibrated neighbourhood archetypes.
They create ordinary :class:`ContextSpec` inputs before any simulation occurs.

Notes
-----
Validation, generation and extrusion share the target metric coordinate frame. Boundary
contact is allowed but plan-area overlap is rejected. Synthetic presets describe
illustrative shading scenarios, while custom neighbours remain explicit input records.

Examples
--------
Example::

    from epsm_core.specs.geometry import Footprint
    from epsm_core.specs.geometry import GeometrySpec
    from epsm_core.context import synthetic_context

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
    context = synthetic_context(geometry, "rural", seed=7, radius_m=80)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from shapely import STRtree, unary_union
from shapely.affinity import rotate, translate
from shapely.geometry import Point, Polygon, box

from .geometry import facade_edges, horizontal_patches, horizontal_vertices, wall_vertices
from .specs import ContextBuilding, ContextSpec, Footprint, GeometrySpec
from .surface_checks import properties

_PRESETS = {
    "rural": (64.0, (10.0, 18.0), (3.0, 9.0), 20.0),
    "urban_lowrise_dense": (32.0, (20.0, 26.0), (6.0, 15.0), 10.0),
    "urban_highrise_dense": (32.0, (20.0, 26.0), (24.0, 60.0), 10.0),
}
_MAX_CANDIDATES = 100_000
_AREA_TOLERANCE = 1e-8


def validate_context(geometry: GeometrySpec, context: ContextSpec) -> None:
    """Reject overlapping target and neighbour footprints in the shared metric frame.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.
    context : ContextSpec
        Explicit shading neighbours; existing context is retained by synthetic generation.

    Returns
    -------
    None
        Successful validation has no return payload.

    Raises
    ------
    ValueError
        Rejected conditions: Context building identifiers must be unique; Context buildings
        require an identifier and nonempty footprints.

    Notes
    -----
    Boundary contact is allowed, and custom neighbours may fit within courtyard holes. Base
    elevation does not excuse a plan-area overlap; tolerance is 1e-8 square metres.

    Examples
    --------
    Example::

        from epsm_core.specs.context import ContextSpec
        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.context import validate_context

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        validate_context(geometry, ContextSpec())
    """
    # 1. Reject overlapping target and neighbour footprints in the shared metric frame.
    identifiers = [b.identifier for b in context.buildings]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Context building identifiers must be unique")
    target = unary_union([p.footprint.polygon for p in geometry.parts])
    polygons, owners = [], []
    for building in context.buildings:
        if not building.identifier.strip() or not building.footprints:
            raise ValueError("Context buildings require an identifier and nonempty footprints")
        for footprint in building.footprints:
            polygon = footprint.polygon
            if polygon.intersection(target).area > _AREA_TOLERANCE:
                raise ValueError(
                    f"Context building {building.identifier!r} overlaps target geometry"
                )
            polygons.append(polygon)
            owners.append(building.identifier)
    tree = STRtree(polygons)
    for i, polygon in enumerate(polygons):
        for j in tree.query(polygon, predicate="intersects"):
            if i < j and polygon.intersection(polygons[j]).area > _AREA_TOLERANCE:
                raise ValueError(f"Context footprints overlap: {owners[i]!r} and {owners[j]!r}")


def _positive(value, name, *, allow_zero=False):
    """Validate and normalize a finite positive scalar.

    Parameters
    ----------
    value : object
        Scalar or JSON-compatible value consumed by this operation.
    name : str
        Identifier or field name interpreted by the current operation.
    allow_zero : bool
        Permit zero in addition to strictly positive finite values. Default: ``False``.

    Returns
    -------
    float
        Input converted to float.

    Raises
    ------
    ValueError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    allow_zero relaxes strict positivity to nonnegativity. name is used only in the
    diagnostic message.

    Examples
    --------
    Example::

        from epsm_core.context import _positive

        assert _positive(0, "clearance", allow_zero=True) == 0.0
    """

    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")
    return float(value)


def _range(values, name):
    """Validate an ordered pair of strictly positive finite bounds.

    Parameters
    ----------
    values : sequence of float
        Exactly two finite positive values in nondecreasing order.
    name : str
        Identifier or field name interpreted by the current operation.

    Returns
    -------
    tuple of float
        Inclusive lower and upper values.

    Raises
    ------
    ValueError
        If the input or generated result violates the constraints described in Notes.

    Notes
    -----
    Exactly two values are required; equal bounds describe a fixed size or height.

    Examples
    --------
    Example::

        from epsm_core.context import _range

        assert _range((3, 3), "height") == (3.0, 3.0)
    """

    # 1. Validate an ordered pair of strictly positive finite bounds.
    if len(values) != 2:
        raise ValueError(f"{name} must contain a minimum and maximum")
    low, high = (_positive(v, name) for v in values)
    if low > high:
        raise ValueError(f"{name} minimum exceeds maximum")
    return low, high


def synthetic_context(
    geometry: GeometrySpec,
    preset: str,
    *,
    seed: int = 0,
    radius_m: float = 100,
    clearance_m: float | None = None,
    spacing_m: float | None = None,
    size_range_m: tuple[float, float] | None = None,
    height_range_m: tuple[float, float] | None = None,
    max_buildings: int = 128,
    existing: ContextSpec | None = None,
) -> ContextSpec:
    """Generate reproducible illustrative neighbours on a bounded candidate grid.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.
    preset : str
        One of rural, urban_lowrise_dense or urban_highrise_dense.
    seed : int
        Deterministic local random seed; bool is rejected. Default: ``0``.
    radius_m : float
        Positive radius limiting candidate centres around the target bounds centre. Default:
        ``100``.
    clearance_m : float | None
        Minimum nonnegative footprint clearance from the target; None uses the preset.
        Default: ``None``.
    spacing_m : float | None
        Positive candidate-grid centre spacing; None uses the preset. Default: ``None``.
    size_range_m : tuple[float, float] | None
        Ordered positive minimum/maximum draw bounds in metres; None uses the preset.
        Default: ``None``.
    height_range_m : tuple[float, float] | None
        Ordered positive minimum/maximum draw bounds in metres; None uses the preset.
        Default: ``None``.
    max_buildings : int
        Positive generated-neighbour limit, excluding supplied context; exceeding it raises.
        Default: ``128``.
    existing : ContextSpec | None
        Explicit shading neighbours; existing context is retained by synthetic generation.
        Default: ``None``.

    Returns
    -------
    ContextSpec
        Existing and generated buildings with generation metadata.

    Raises
    ------
    ValueError
        Rejected conditions: seed must be an integer; max_buildings must be a positive
        integer.

    Notes
    -----
    Candidate centres are radius-limited; footprint sizes may extend beyond that radius.
    Separate random streams keep horizontal placement independent of height draws.
    Courtyards are excluded automatically. Limits raise errors instead of silently
    truncating a scenario.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.context import synthetic_context

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        context = synthetic_context(geometry, "rural", seed=7, radius_m=80)
    """
    # 1. Generate reproducible illustrative neighbours on a bounded candidate grid.
    if preset not in _PRESETS:
        raise ValueError(f"Unknown context preset {preset!r}; choose {', '.join(_PRESETS)}")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not isinstance(max_buildings, int) or isinstance(max_buildings, bool) or max_buildings < 1:
        raise ValueError("max_buildings must be a positive integer")
    spacing, sizes, heights, clearance = _PRESETS[preset]
    spacing = _positive(spacing if spacing_m is None else spacing_m, "spacing_m")
    sizes = _range(sizes if size_range_m is None else size_range_m, "size_range_m")
    heights = _range(heights if height_range_m is None else height_range_m, "height_range_m")
    clearance = _positive(
        clearance if clearance_m is None else clearance_m, "clearance_m", allow_zero=True
    )
    radius = _positive(radius_m, "radius_m")
    existing = ContextSpec() if existing is None else existing
    validate_context(geometry, existing)
    grid_radius = radius / spacing
    if not math.isfinite(grid_radius) or grid_radius > math.sqrt(_MAX_CANDIDATES) / 2:
        raise ValueError(
            f"Context grid exceeds {_MAX_CANDIDATES} candidates. "
            "Reduce radius_m or increase spacing_m."
        )
    half_grid = math.ceil(grid_radius)
    candidate_bound = (2 * half_grid + 1) ** 2
    if candidate_bound > _MAX_CANDIDATES:
        raise ValueError(
            f"Context grid needs {candidate_bound} candidates; maximum is {_MAX_CANDIDATES}. "
            "Reduce radius_m or increase spacing_m."
        )

    # Filling target holes protects courtyards, without excluding spaces between
    # disconnected components or across the opening of a U-shaped building.
    # 2. Exclude courtyard voids from automatic placement while retaining exterior concavities.
    target = unary_union([Polygon(p.footprint.polygon.exterior) for p in geometry.parts])
    left, bottom, right, top = target.bounds
    centre_x, centre_y = (left + right) / 2, (bottom + top) / 2
    supplied = [p.polygon for b in existing.buildings for p in b.footprints]
    occupied = unary_union(supplied) if supplied else Polygon()
    plan_rng, height_rng = random.Random(seed), random.Random(f"context-height:{seed}")
    generated = []
    identifiers = {b.identifier for b in existing.buildings}
    candidates_considered = 0
    # Stable order across presets and seeds. Draw all random values per candidate
    # so obstacle rejection cannot couple later footprints to accepted heights.
    # 3. Draw geometry and height independently in stable candidate order for repeatability.
    for row in range(-half_grid, half_grid + 1):
        for column in range(-half_grid, half_grid + 1):
            x, y = centre_x + column * spacing, centre_y + row * spacing
            if Point(x, y).distance(Point(centre_x, centre_y)) > radius:
                continue
            candidates_considered += 1
            width, length = plan_rng.uniform(*sizes), plan_rng.uniform(*sizes)
            height = height_rng.uniform(*heights)
            polygon = box(x - width / 2, y - length / 2, x + width / 2, y + length / 2)
            if polygon.intersects(target) or polygon.distance(target) < clearance:
                continue
            if polygon.intersection(occupied).area > _AREA_TOLERANCE:
                continue
            if len(generated) >= max_buildings:
                raise ValueError(
                    f"Context generation exceeds max_buildings={max_buildings}; "
                    "reduce radius_m, increase spacing_m or explicitly raise the limit."
                )
            identifier = f"synthetic_{row + half_grid}_{column + half_grid}"
            if identifier in identifiers:
                raise ValueError(
                    f"Generated context identifier conflicts with existing: {identifier}"
                )
            generated.append(
                ContextBuilding(
                    identifier=identifier,
                    footprints=(Footprint(exterior=tuple(polygon.exterior.coords)[:-1]),),
                    height_m=height,
                )
            )
            occupied = occupied.union(polygon)

    # 4. Retain supplied neighbours and record achieved counts and scenario assumptions.
    result = ContextSpec(
        buildings=(*existing.buildings, *generated),
        generation={
            "preset": preset,
            "seed": seed,
            "radius_m": radius,
            "clearance_m": clearance,
            "spacing_m": spacing,
            "size_range_m": list(sizes),
            "height_range_m": list(heights),
            "max_buildings": max_buildings,
            "candidate_count": candidates_considered,
            "generated_building_count": len(generated),
            "supplied_building_count": len(existing.buildings),
            "achieved_building_count": len(existing.buildings) + len(generated),
            "assumption": "Illustrative geometric shading scenario; not a calibrated neighbourhood",
            **({"supplied_generation": existing.generation} if existing.generation else {}),
        },
    )
    validate_context(geometry, result)
    return result


@dataclass(frozen=True)
class ContextSurface:
    """One validated world-frame shading face with neighbour provenance.

    Attributes
    ----------
    name : str
        Identifier or field name interpreted by the current operation.  Required at
        construction.
    vertices : tuple[tuple[float, float, float], ...]
        Ordered three-dimensional metric surface vertices; winding controls the normal.
        Required at construction.
    building_id : str
        Owning physical part or neighbouring-building identifier.  Required at construction.
    footprint_index : int
        Zero-based footprint index within the owning context building.  Required at
        construction.
    kind : str
        Supported measure discriminator or geometric classification, according to the
        record.  Required at construction.

    Notes
    -----
    Vertices are in the same local metric scene as the target. kind is Wall or Roof; the
    record deliberately carries no thermal zone or construction.

    Examples
    --------
    Example::

        from epsm_core.context import ContextSurface

        face = ContextSurface(
            "context_0", ((0, 0, 3), (1, 0, 3), (0, 1, 3)), "next", 0, "Roof"
        )
    """

    name: str
    vertices: tuple[tuple[float, float, float], ...]
    building_id: str
    footprint_index: int
    kind: str


@dataclass(frozen=True)
class ContextResolution:
    """Shading surfaces and an inspectable context-generation report.

    Attributes
    ----------
    surfaces : tuple[ContextSurface, ...]
        Mutable thermal face list, or immutable shading tuple in ContextResolution.
        Required at construction.
    report : dict
        Compilation metadata; SQL/compiler consumers use CompilationReport, viewer_data uses
        its decoded data mapping.  Required at construction.

    Notes
    -----
    Frozen record identity does not deeply freeze the report dictionary. resolve_context
    validates geometry before constructing this result.

    Examples
    --------
    Example::

        from epsm_core.context import ContextResolution

        resolution = ContextResolution((), {"surface_count": 0})
    """

    surfaces: tuple[ContextSurface, ...]
    report: dict


def resolve_context(
    geometry: GeometrySpec, context: ContextSpec, *, origin=None
) -> ContextResolution:
    """Extrude and validate opaque shading surfaces in the target's local frame.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.
    context : ContextSpec
        Explicit shading neighbours; existing context is retained by synthetic generation.
    origin : tuple of float or None
        Source-frame (x, y) translation origin in metres; None derives target minimum
        bounds. Default: ``None``.

    Returns
    -------
    ContextResolution
        Validated wall/roof surfaces and generation report.

    Notes
    -----
    Applies the same translation then clockwise rotation as the target. Context has no
    thermal zones, constructions or loads. Surfaces include walls and roofs, but no floor.

    Examples
    --------
    Example::

        from epsm_core.specs.context import ContextSpec
        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.context import resolve_context

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        resolved = resolve_context(geometry, ContextSpec())
        assert resolved.surfaces == ()
    """
    # 1. Extrude and validate opaque shading surfaces in the target's local frame.
    validate_context(geometry, context)
    if origin is None:
        origin = (
            min(p.footprint.polygon.bounds[0] for p in geometry.parts),
            min(p.footprint.polygon.bounds[1] for p in geometry.parts),
        )
    # 2. Extrude neighbours in the same translated and rotated frame as the target.
    surfaces, buildings = [], []
    for bi, building in enumerate(context.buildings):
        count = 0
        for pi, footprint in enumerate(building.footprints):
            p = rotate(
                translate(footprint.polygon, -origin[0], -origin[1]),
                -geometry.orientation_deg,
                origin=(0, 0),
            )
            base, top = building.base_elevation_m, building.base_elevation_m + building.height_m
            shapes = [("Wall", wall_vertices(a, b, base, top)) for _, a, b in facade_edges(p, pi)]
            shapes.extend(
                ("Roof", horizontal_vertices(patch, top)) for patch in horizontal_patches(p)
            )
            for si, (kind, points) in enumerate(shapes):
                properties(np.asarray(points, dtype=float))
                surfaces.append(
                    ContextSurface(
                        name=f"context_{bi}_{pi}_{si}",
                        vertices=tuple(tuple(float(v) for v in point) for point in points),
                        building_id=building.identifier,
                        footprint_index=pi,
                        kind=kind,
                    )
                )
                count += 1
        buildings.append(
            {
                "identifier": building.identifier,
                "height_m": building.height_m,
                "base_elevation_m": building.base_elevation_m,
                "footprint_count": len(building.footprints),
                "surface_count": count,
            }
        )
    # 3. Return validated shading geometry with explicit representation and generation evidence.
    return ContextResolution(
        surfaces=tuple(surfaces),
        report={
            "building_count": len(buildings),
            "surface_count": len(surfaces),
            "buildings": buildings,
            "generation": context.generation,
            "validation": "passed",
            "representation": "Opaque vertical footprint extrusions for shading only",
        },
    )
