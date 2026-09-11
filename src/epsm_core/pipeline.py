# File: pipeline.py
# Purpose: Shared geometry resolution for compilation, quantities and inspection.
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
#   2026-09-11 - Require read-only geometry validation before serialization.
#   2026-09-06 - Document pipeline interfaces, examples, constraints and processing rationale.

"""Shared geometry resolution for compilation, quantities and inspection.

Notes
-----
This is the common resolution path for thermal compilation, nominal quantities and
inspection. It resolves topology before windows and shading. Optional receiving-wall
subdivision is followed by a fresh opening pass to repair thermal parent references.

Examples
--------
Supply a validated BuildingSpec as ``building``.

Example::

    from epsm_core.pipeline import resolve_geometry

    resolved = resolve_geometry(building, panelize=False)
"""

from dataclasses import dataclass

from .facades import panelize_receiving_walls, resolve_openings, shading_geometry
from .geometry import local_polygons
from .surface_checks import validate_surfaces
from .topology import build_surface_graph


@dataclass
class ResolvedGeometry:
    """Shared resolved geometry consumed by compiler, quantities and inspection.

    Attributes
    ----------
    polygons : list
        Local metric footprints in the same order as geometry.parts.  Required at
        construction.
    origin : tuple
        Source-frame translation origin in metres, before scene rotation.  Required at
        construction.
    graph : object
        Mutable resolved surfaces, zone metrics, internal slabs and geometry reports.
        Required at construction.
    openings : list
        Thermal panes with parent-wall and logical-window metadata.  Required at
        construction.
    facades : list
        Per-thermal-parent facade reports from opening resolution.  Required at
        construction.
    shading : list
        Validated shading-only polygon records.  Required at construction.

    Notes
    -----
    graph and contained lists are mutable working artifacts. logical_window_count
    deduplicates thermal panes by their logical opening ID.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.pipeline import resolve_geometry

        resolved = resolve_geometry(building)
    """

    polygons: list
    origin: tuple
    graph: object
    openings: list
    facades: list
    shading: list

    @property
    def logical_window_count(self):
        """Count distinct physical windows across thermal pane subdivisions.

        Returns
        -------
        int
            Number of distinct logical_window metadata IDs.

        Notes
        -----
        A window split over multiple thermal parents is counted once. Each opening must carry
        logical_window metadata.

        Examples
        --------
        Supply a ResolvedGeometry as ``resolved`` from resolve_geometry.

        Example::

            count = resolved.logical_window_count
        """

        return len({o.metadata["logical_window"] for o in self.openings})


def resolve_geometry(spec, *, panelize=False):
    """Resolve a shared surface graph, openings and shading for all consumers.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    panelize : bool
        Subdivide shaded receiving walls and re-resolve openings when true. Default:
        ``False``.

    Returns
    -------
    ResolvedGeometry
        Local footprints, source origin, graph and facade artifacts.

    Notes
    -----
    When panelize is true and shading exists, opaque receiving walls are subdivided and
    openings resolved again. This bounds shadow complexity without changing physical
    windows.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.pipeline import resolve_geometry

        resolved = resolve_geometry(building, panelize=False)
    """

    # 1. Resolve a shared surface graph, openings and shading for all consumers.
    polygons, origin = local_polygons(spec.geometry)
    graph = build_surface_graph(spec, polygons)
    openings, facades = resolve_openings(spec, graph)
    shading = shading_geometry(spec, graph, openings)
    if panelize and shading:
        graph = panelize_receiving_walls(graph, openings)
        openings, facades = resolve_openings(spec, graph)

    # Assert physical geometry before any serializer receives it. This view
    # references source coordinates and does not rotate or repair the graph.
    def coordinates(points):
        return [
            {f"vertex_{axis}_coordinate": value for axis, value in zip("xyz", point)}
            for point in points
        ]

    validate_surfaces(
        {
            "BuildingSurface:Detailed": {
                face.name: dict(
                    zone_name=face.zone,
                    surface_type=face.kind,
                    construction_name=face.construction,
                    outside_boundary_condition=face.boundary,
                    outside_boundary_condition_object=face.adjacent,
                    vertices=coordinates(face.vertices),
                )
                for face in graph.surfaces
            },
            "FenestrationSurface:Detailed": {
                opening.name: dict(
                    building_surface_name=opening.parent, vertices=coordinates(opening.vertices)
                )
                for opening in openings
            },
            "Shading:Building:Detailed": {
                shade["name"]: dict(vertices=coordinates(shade["vertices"])) for shade in shading
            },
        },
        graph.zones,
    )
    return ResolvedGeometry(polygons, origin, graph, openings, facades, shading)
