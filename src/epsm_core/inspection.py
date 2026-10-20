# File: inspection.py
# Purpose: Geometry inspection without weather files, materials or an EnergyPlus installation.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-20
# Changelog:
#   2026-10-20 - Export pure polygon scenes; move display lifecycle out of Core.
#   2026-09-06 - Document inspection interfaces, examples, constraints and processing rationale.

"""Geometry inspection without weather files, materials or an EnergyPlus installation.

Notes
-----
Geometry, windows and shading are resolved through the same pipeline as compilation. The
resulting scene is intentionally incomplete as simulation input: it needs no weather,
loads or physical material definitions. Public scene exports return detached polygon
data without writing artifacts, opening a browser or starting a server.

Examples
--------
Example::

    from epsm_core.specs.geometry import Footprint
    from epsm_core.specs.geometry import GeometrySpec
    from epsm_core.inspection import geometry_scene

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
    scene, report = geometry_scene(geometry)
    assert report["geometry_only"] is True
"""

from dataclasses import asdict
from types import SimpleNamespace

from .context import resolve_context
from .pipeline import resolve_geometry
from .scene import scene_data
from .specs import ContextSpec, FacadeSpec, GlazingSpec


def geometry_scene(geometry, *, facade=None, context=None):
    """Assemble an engine-independent epJSON-shaped preview and metadata report.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts, metric coordinate frame, orientation and zoning controls.
    facade : FacadeSpec or None
        Window and shading controls; None uses the preview's zero-glazing default. Default:
        ``None``.
    context : ContextSpec or None
        Explicit shading neighbours; existing context is retained by synthetic generation.
        Default: ``None``.

    Returns
    -------
    tuple of dict
        Scene objects and geometry-only compilation report.

    Notes
    -----
    The scene is not a simulation-ready input. Missing facade settings explicitly produce
    zero glazing; context and physical geometry still undergo shared validation.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.inspection import geometry_scene

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        scene, report = geometry_scene(geometry)
        assert report["geometry_only"] is True
    """
    return _geometry_scene(geometry, facade=facade, context=context)


def _geometry_scene(geometry, *, facade=None, context=None, physical=None):
    """Assemble loaded geometry and optionally attach original physical owners."""
    # 1. Assemble an engine-independent epJSON-shaped preview and metadata report.
    if facade is None:
        facade = FacadeSpec(
            default_wwr=0, glazing=GlazingSpec(u_value_w_m2k=1, solar_heat_gain_coefficient=0)
        )
    spec = SimpleNamespace(geometry=geometry, facade=facade)
    resolved = resolve_geometry(spec)
    graph = resolved.graph
    scene = {
        "GlobalGeometryRules": {"geometry": {"coordinate_system": "World"}},
        "BuildingSurface:Detailed": {},
        "FenestrationSurface:Detailed": {},
        "Shading:Building:Detailed": {},
    }

    def coordinates(verts):
        """Encode metric vertex triples as epJSON coordinate dictionaries.

        Parameters
        ----------
        verts : array_like
            Ordered three-dimensional metric surface vertices; winding controls the normal.

        Returns
        -------
        list of dict
            vertex_x_coordinate, vertex_y_coordinate and vertex_z_coordinate records.

        Notes
        -----
        Only field representation changes; vertex order and numeric values are retained.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            coordinates([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        """

        return [
            dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
            for x, y, z in verts
        ]

    for f in graph.surfaces:
        scene["BuildingSurface:Detailed"][f.name] = dict(
            vertices=coordinates(f.vertices),
            zone_name=f.zone,
            surface_type=f.kind,
            construction_name=f.construction,
            outside_boundary_condition=f.boundary,
            outside_boundary_condition_object=f.adjacent,
        )
    for o in resolved.openings:
        scene["FenestrationSurface:Detailed"][o.name] = dict(
            vertices=coordinates(o.vertices), surface_type="Window", building_surface_name=o.parent
        )
    surroundings = resolve_context(geometry, context or ContextSpec(), origin=resolved.origin)
    shades = list(resolved.shading) + [
        dict(
            name=f.name,
            vertices=f.vertices,
            kind="context",
            surface_type=f.kind,
            building_id=f.building_id,
            footprint_index=f.footprint_index,
        )
        for f in surroundings.surfaces
    ]
    for s in shades:
        scene["Shading:Building:Detailed"][s["name"]] = dict(vertices=coordinates(s["vertices"]))
    report = dict(
        geometry_only=True,
        origin_m=resolved.origin,
        orientation_deg=geometry.orientation_deg,
        source_crs=geometry.source_crs,
        zones=graph.zones,
        facades=resolved.facades,
        facade_catalog=[asdict(f) for f in geometry.facades()],
        surfaces={
            f.name: dict(
                part_id=f.part_id,
                facade_id=f.facade_id,
                storey=f.storey,
                zone=f.zone,
                area_m2=f.area,
                annotations=f.annotations,
            )
            for f in graph.surfaces
        },
        openings={o.name: o.metadata for o in resolved.openings},
        shading={s["name"]: {k: v for k, v in s.items() if k != "vertices"} for s in shades},
        internal_mass=graph.internal_mass,
        layout=graph.layout_report,
        zoning=getattr(graph, "zoning_report", {}),
        context=surroundings.report,
        logical_window_count=resolved.logical_window_count,
        thermal_pane_count=len(resolved.openings),
        parts=[p.model_dump(mode="json") for p in geometry.parts],
    )
    if physical is not None:
        from .building_adapter import _physical_element_owners

        owners = _physical_element_owners(physical, resolved)
        report.update(building_id=physical.identifier, snapshot_id=physical.snapshot().sha256)
        for section in ("surfaces", "openings"):
            for name, owner in owners[section].items():
                report[section][name].update(physical_element_id=owner.identifier,
                    physical_component_ids=owner.component_ids)
        for mass in report["internal_mass"]:
            owner = owners["internal_mass"].get(mass["name"])
            if owner is not None:
                mass.update(physical_element_id=owner.identifier,
                            physical_component_ids=owner.component_ids)
    return scene, report



def geometry_scene_data(geometry, *, facade=None, context=None):
    """Export an engine-independent neutral polygon scene from loaded geometry.

    Parameters
    ----------
    geometry : GeometrySpec
        Physical parts in a metric source coordinate frame.
    facade : FacadeSpec or None, optional
        Explicit windows and shading; absent facade produces zero glazing.
    context : ContextSpec or None, optional
        Explicit neighbouring physical geometry in the same coordinate frame.

    Returns
    -------
    dict
        Detached JSON values using ``epsm.scene/1``, metres and Z-up coordinates.
        Original polygons, opening rings and geometry metadata are retained.

    Notes
    -----
    Uses the same validated geometry pipeline as compilation without requiring
    weather, constructions or an EnergyPlus installation. No files are read or
    written. Consumers own rendering and display lifecycle.

    Examples
    --------
    >>> from epsm_core import Footprint, GeometrySpec, geometry_scene_data
    >>> geometry = GeometrySpec.from_footprint(Footprint.rectangle(4, 3), storeys=1, storey_height_m=3)
    >>> geometry_scene_data(geometry)['report']['geometry_only']
    True
    """
    model, report = geometry_scene(geometry, facade=facade, context=context)
    return scene_data(model, report)


def _building_scene_data(building):
    """Export physical Building geometry without thermal readiness or source I/O."""
    if building.geometry is None:
        raise ValueError("Building has no geometry; assign geometry before exporting a scene")
    model, report = _geometry_scene(building.geometry, facade=building.facade,
                                    context=building.context, physical=building)
    return scene_data(model, report)
