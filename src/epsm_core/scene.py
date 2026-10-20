# File: scene.py
# Purpose: Pure polygon scene data from loaded Core geometry and epJSON objects.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group, Chalmers University of Technology
# Date created: 2026-10-20 (extracted from viewer.py; original notices retained)
# Date modified: 2026-10-20
# Changelog:
#   2026-10-20 - Export neutral polygon scenes without rendering, hosting or file access.

"""Versioned polygon data for consumers of already loaded physical geometry.

Scenes retain source vertices, opening rings and physical metadata. Consumers own
triangulation, visual representations of internal mass and display lifecycle.
Nothing in this module reads files, initializes an engine or configures logging.
"""

import json

import numpy as np
from shapely import unary_union
from shapely.geometry import Polygon

from .surface_checks import properties, vertices


def scene_schema():
    """Return the JSON Schema for Core's neutral ``epsm.scene/1`` handoff.

    Returns
    -------
    dict
        A fresh Draft 2020-12 schema describing polygon coordinates, units,
        required object identities and metadata. No files are read or written.

    Notes
    -----
    This describes exchanged data; Core geometry validation continues to own
    physical validity. Consumers may retain this schema with release provenance
    and use it without a runtime dependency on Core. It does not prescribe a
    renderer, triangulation algorithm or visual representation of internal mass.

    Examples
    --------
    >>> from epsm_core import scene_schema
    >>> scene_schema()['properties']['units']['const']
    'm'
    """
    point = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
    polygon = {"type": "array", "items": {"$ref": "#/$defs/point"}, "minItems": 3}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "EPSM neutral polygon scene version 1",
        "type": "object",
        "required": [
            "schema",
            "units",
            "up_axis",
            "objects",
            "report",
            "diagnostics",
            "preparation",
            "internal_mass",
        ],
        "additionalProperties": False,
        "properties": {
            "schema": {"const": "epsm.scene/1"},
            "units": {"const": "m"},
            "up_axis": {"const": "Z"},
            "objects": {"type": "array", "items": {"$ref": "#/$defs/object"}},
            "report": {"type": "object"},
            "diagnostics": {"type": "object"},
            "preparation": {"type": ["object", "null"]},
            "internal_mass": {"type": "object"},
        },
        "$defs": {
            "point": point,
            "polygon": polygon,
            "object": {
                "type": "object",
                "required": ["id", "name", "kind", "vertices", "holes", "metadata"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "name": {"type": "string"},
                    "kind": {"type": "string"},
                    "vertices": {"$ref": "#/$defs/polygon"},
                    "holes": {"type": "array", "items": {"$ref": "#/$defs/polygon"}},
                    "metadata": {"type": "object"},
                    "parent": {"type": ["string", "null"]},
                    "normal": {"$ref": "#/$defs/point"},
                    "area_m2": {"type": "number", "minimum": 0},
                    "net_area_m2": {"type": "number", "minimum": 0},
                    "boundary": {"type": ["string", "null"]},
                    "zone": {"type": ["string", "null"]},
                    "construction_name": {"type": "string"},
                    "layers": {"type": "array", "items": {"type": "object"}},
                    "construction_report": {"type": "object"},
                    "epjson": {"type": "object"},
                },
            },
        },
    }


def scene_data(model, report=None, diagnostics=None, preparation=None):
    """Export world-coordinate polygons and metadata as detached JSON values.

    Parameters
    ----------
    model : dict
        Loaded epJSON-shaped object mapping with World coordinates in metres.
        Geometry-only mappings from Core inspection are accepted.
    report : dict or None, optional
        Loaded compilation or geometry report. Physical owner IDs, construction
        evidence, context visibility and internal-mass records are retained.
    diagnostics : dict or None, optional
        Loaded acceptance decisions; no new simulation acceptance is inferred.
    preparation : dict or None, optional
        Loaded preparation evidence for source and cleaned outlines.

    Returns
    -------
    dict
        ``epsm.scene/1`` with ``units='m'`` and ``up_axis='Z'``. Each object has
        its original polygon ``vertices`` and opening ``holes`` as vertex rings.
        Areas are in square metres, normals are dimensionless unit vectors.
        ``objects``, ``report``, ``diagnostics``, ``preparation`` and
        ``internal_mass`` contain JSON values only and do not alias inputs.

    Raises
    ------
    ValueError
        Relative coordinates, invalid polygons, openings outside their parent,
        overlapping opening interiors or nonfinite JSON values.
    TypeError
        Source metadata cannot be represented as JSON values.

    Notes
    -----
    Opening rings remain separate from their parent polygon. Net areas account
    for their union, but no cutout mesh, triangles or virtual slab geometry is
    generated. Opening polygons must be covered by their parent and may touch
    each other at edges, but positive interior overlap above a numerical area
    tolerance is rejected. No input polygon is repaired, clipped or merged.
    Surface winding, source fields and physical identities are kept.
    No readiness check, weather access, engine discovery or file I/O occurs.

    Examples
    --------
    >>> from epsm_core import scene_data
    >>> scene_data({})['schema']
    'epsm.scene/1'
    """
    report = report or {}
    rules = next(iter(model.get("GlobalGeometryRules", {}).values()), {})
    if rules.get("coordinate_system", "World") != "World":
        raise ValueError("Scenes require World coordinates; convert relative coordinates first")
    openings = {}
    for name, obj in model.get("FenestrationSurface:Detailed", {}).items():
        openings.setdefault(obj["building_surface_name"], []).append((name, obj))
    objects = []

    def add_polygon(name, obj, kind, *, holes=(), parent=None):
        """Retain one source polygon and its geometric, physical and source fields."""
        points = vertices(obj).astype(float)
        area, normal, _ = properties(points)
        rings = [(hole_name, vertices(hole).astype(float)) for hole_name, hole in holes]
        u = points[1] - points[0]
        u /= np.linalg.norm(u)
        w = np.cross(normal, u)

        def project(ring):
            return [((point - points[0]) @ u, (point - points[0]) @ w) for point in ring]

        polygon = Polygon(project(points))
        if not polygon.is_valid:
            raise ValueError(f"Invalid opening coverage for scene object {name}")
        # Raw opening rings are handed to consumers without clipping. Reject
        # unsupported coverage here so a renderer cannot silently change the
        # physical opening areas. Edge contacts contribute no overlap area.
        area_tolerance = max(1e-8, polygon.area * 1e-10)
        cutouts = []
        for hole_name, ring in rings:
            cutout = Polygon(project(ring))
            if not cutout.is_valid or cutout.area <= 0:
                raise ValueError(
                    f"Opening {hole_name} has invalid polygon coverage on parent {name}"
                )
            if not polygon.covers(cutout):
                raise ValueError(f"Opening {hole_name} lies outside parent {name}")
            for prior_name, prior in cutouts:
                if cutout.intersection(prior).area > area_tolerance:
                    raise ValueError(
                        f"Openings {prior_name} and {hole_name} overlap on parent {name}"
                    )
            cutouts.append((hole_name, cutout))
        net = polygon.difference(unary_union([cutout for _, cutout in cutouts]))
        if not net.is_valid:
            raise ValueError(f"Invalid opening coverage for scene object {name}")
        metadata = dict(report.get("surfaces", {}).get(parent or name, {}))
        metadata.update(report.get("openings", {}).get(name, {}))
        metadata.update(report.get("shading", {}).get(name, {}))
        zone = metadata.get("zone", obj.get("zone_name"))
        metadata.update(
            {
                key: value
                for key, value in report.get("zones", {}).get(zone, {}).items()
                if key in ("zone_kind", "apartment_type")
            }
        )
        construction_name = obj.get("construction_name", "")
        construction = report.get("constructions", {}).get(
            construction_name.removesuffix("_reverse"), {}
        )
        raw_construction = model.get("Construction", {}).get(construction_name, {})
        layers = [
            dict(
                name=name,
                **model.get("Material", {}).get(
                    name, model.get("WindowMaterial:SimpleGlazingSystem", {}).get(name, {})
                ),
            )
            for name in raw_construction.values()
        ]
        objects.append(
            dict(
                id=name,
                name=name,
                kind=kind,
                parent=parent,
                vertices=points.tolist(),
                holes=[ring.tolist() for _, ring in rings],
                normal=normal.tolist(),
                area_m2=float(area),
                net_area_m2=float(net.area),
                metadata=metadata,
                boundary=obj.get("outside_boundary_condition"),
                zone=zone,
                construction_name=construction_name,
                layers=layers,
                construction_report=construction,
                epjson=obj,
            )
        )

    for name, obj in model.get("BuildingSurface:Detailed", {}).items():
        add_polygon(name, obj, "surface", holes=openings.get(name, ()))
    for name, obj in model.get("FenestrationSurface:Detailed", {}).items():
        add_polygon(name, obj, "opening", parent=obj["building_surface_name"])
    for name, obj in model.get("Shading:Building:Detailed", {}).items():
        add_polygon(name, obj, report.get("shading", {}).get(name, {}).get("kind", "context"))
    # Shadow-engine visibility does not remove a neighbour's physical shell.
    for hidden in report.get("context", {}).get("visibility", {}).get("hidden", []):
        if hidden["name"] in model.get("Shading:Building:Detailed", {}):
            continue
        obj = dict(
            vertices=[
                dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                for x, y, z in hidden["vertices"]
            ]
        )
        add_polygon(hidden["name"], obj, "context")
        objects[-1]["metadata"]["shadow_export"] = hidden["reason"]
    payload = dict(
        schema="epsm.scene/1",
        units="m",
        up_axis="Z",
        objects=objects,
        report=report,
        diagnostics=diagnostics or {},
        preparation=preparation,
        internal_mass=model.get("InternalMass", {}),
    )
    # JSON normalization detaches nested source fields, converts tuples to arrays
    # and rejects values that downstream consumers could not safely decode.
    return json.loads(json.dumps(payload, allow_nan=False))
