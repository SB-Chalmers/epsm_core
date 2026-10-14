# File: quantities.py
# Purpose: Nominal physical quantity takeoffs; no carbon, cost, tariffs or fabricated masses.
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
#   2026-09-06 - Document quantities interfaces, examples, constraints and processing rationale.

"""Nominal physical quantity takeoffs; no carbon, cost, tariffs or fabricated masses.

Notes
-----
Takeoffs use resolved geometry and nominal layer properties, not thermal-bridge
equivalent conductivities. Reciprocal faces and internal slabs are counted once. Glazing
and equipment retain only known quantities; carbon and cost factor lookup belongs
outside core.

Examples
--------
Supply a validated BuildingSpec as ``building``.

Example::

    from epsm_core.quantities import quantity_takeoff

    items = quantity_takeoff(building)
    assert all(q.mass_kg is None or q.mass_kg >= 0 for q in items)
"""

import hashlib
import json
from collections import defaultdict

from .specs import PhysicalQuantity


def _hash(value):
    """Hash a JSON-serializable physical description in canonical key order.

    Parameters
    ----------
    value : object
        Scalar or JSON-compatible value consumed by this operation.

    Returns
    -------
    str
        SHA-256 hexadecimal digest.

    Notes
    -----
    Whitespace and dictionary insertion order do not affect the digest. Values must be JSON
    serializable.

    Examples
    --------
    Example::

        from epsm_core.quantities import _hash

        assert _hash({"b": 2, "a": 1}) == _hash({"a": 1, "b": 2})
    """

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def quantity_takeoff(building):
    """Derive nominal material, glazing and equipment quantities from resolved geometry.

    Parameters
    ----------
    building : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.

    Returns
    -------
    tuple of PhysicalQuantity
        Items sorted by stable item ID.

    Notes
    -----
    Reciprocal surfaces and physical internal slabs are counted once. Thermal AirBoundary
    partitions are excluded. Glazing area has no invented mass; equipment has a count only.
    Equivalent thermal-bridge materials do not replace nominal materials.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.quantities import quantity_takeoff

        items = quantity_takeoff(building)
        assert all(q.mass_kg is None or q.mass_kg >= 0 for q in items)
    """

    # 1. Derive nominal material, glazing and equipment quantities from resolved geometry.
    from .pipeline import resolve_geometry

    surface_overrides = getattr(building, "surface_constructions", {})
    mass_overrides = getattr(building, "internal_mass_constructions", {})
    resolved = resolve_geometry(building, panelize=bool(surface_overrides))
    graph, openings = resolved.graph, resolved.openings
    opening_areas = defaultdict(float)
    for o in openings:
        opening_areas[o.parent] += o.area
    items = []
    assemblies = defaultdict(float)
    assembly_values = {}
    glazing_areas = defaultdict(float)
    seen = set()
    # 2. Count reciprocal physical assemblies once and subtract actual pane areas.
    for face in graph.surfaces:
        if face.name in seen or face.construction == "partition":
            continue
        seen.add(face.name)
        if face.boundary == "Surface":
            seen.add(face.adjacent)
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        area = face.area
        element_id = face.name
        if (
            face.kind in ("Floor", "Ceiling", "Roof")
            and len({round(v[2], 8) for v in face.vertices}) == 1
        ):
            height = face.vertices[0][2] or 0.0
            element_id = f"{face.part_id}.horizontal.{height:g}.{role}"
        if face.kind == "Wall" and face.facade_id:
            element_id = f"{face.facade_id}.floor{face.storey}.{face.cell_kind}.{role}"
        if face.kind == "Wall" and face.boundary == "Outdoors" and face.cell_kind == "main":
            glazed = opening_areas[face.name]
            area -= glazed
            if glazed:
                glazing_hash = _hash(
                    building.facade.value_for("glazing", face.facade_id, face.storey).model_dump(
                        mode="json"
                    )
                )
                glazing_areas[(element_id, glazing_hash)] += glazed
        assembly = surface_overrides.get(face.name, getattr(building.envelope, role))
        assembly_key = _hash(assembly.model_dump(mode="json"))
        assembly_values[assembly_key] = assembly
        assemblies[(element_id, role, assembly_key)] += area
    # 3. Restore same-zone physical slabs omitted from thermal boundary surfaces.
    for mass in graph.internal_mass:
        # Physical intermediate slab counted once, irrespective of its two radiating faces.
        height = mass["elevation_m"]
        assembly = mass_overrides.get(
            mass["name"], building.envelope.intermediate_floor)
        assembly_key = _hash(assembly.model_dump(mode="json"))
        assembly_values[assembly_key] = assembly
        assemblies[
            (f"{mass['part_id']}.horizontal.{height:g}.intermediate_floor", "intermediate_floor",
             assembly_key)
        ] += mass["area_m2"]
    for (element, digest), area in sorted(glazing_areas.items()):
        items.append(
            PhysicalQuantity(
                item_id=element + ".glazing",
                element_id=element,
                role="glazing",
                kind="glazing",
                physical_sha256=digest,
                area_m2=area,
            )
        )
    # 4. Use nominal layers to derive volume and mass, independent of thermal-bridge uplift.
    for (element, role, assembly_key), area in sorted(assemblies.items()):
        assembly = assembly_values[assembly_key]
        occurrences = defaultdict(int)
        for layer in assembly.layers:
            digest = _hash(layer.model_dump(mode="json"))
            index = occurrences[digest]
            occurrences[digest] += 1
            volume = area * layer.thickness_m
            items.append(
                PhysicalQuantity(
                    item_id=f"{element}.layer.{digest}.{index}",
                    element_id=element,
                    role=role,
                    kind="opaque_layer",
                    physical_sha256=digest,
                    area_m2=area,
                    volume_m3=volume,
                    mass_kg=volume * layer.material.density_kg_m3,
                )
            )
    # 5. Record equipment counts without inventing unspecified embodied masses.
    equipment = [("airflow", building.airflow)]
    if building.delivery.fvp:
        equipment.append(("fvp", building.delivery.fvp))
    equipment += [(f"pv.{i}", pv) for i, pv in enumerate(building.renewables.pv_systems)]
    for identifier, value in equipment:
        element = "equipment." + identifier
        items.append(
            PhysicalQuantity(
                item_id=element,
                element_id=element,
                role=identifier.split(".")[0],
                kind="equipment",
                physical_sha256=_hash(value.model_dump(mode="json")),
                count=1,
            )
        )
    return tuple(sorted(items, key=lambda q: q.item_id))
