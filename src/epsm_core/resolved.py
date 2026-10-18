# File: resolved.py
# Purpose: Expose immutable shared geometry, assignments and operation inputs.
# SPDX-License-Identifier: MIT
# License: MIT; see the project-root LICENSE.
# Date created: 2026-10-14

"""Portable read-only resolved inputs built by Core's existing pipeline.

The working graph stays private and mutable. This view retains nominal physical
constructions, prior to solver-specific bridge adjustments, Kiva floor merging,
internal-mass splitting. Coordinates retain the translated and rotated metric
scene from the shared pipeline. No engine is initialized.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .building import BuildingSnapshot
from .pipeline import resolve_geometry
from .specs import BuildingSpec
from .zone_inputs import resolve_zone_operations


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ResolvedBuildingInput:
    """Immutable JSON-backed view of resolved Core inputs.

    ``data`` and the record properties expose recursively read-only mappings and
    tuples. ``to_dict()`` creates a detached writable export. Surface names are
    scoped to the source and recorded panelization setting; physical owner IDs
    and logical-window IDs remain distinct from thermal face/pane names.
    """

    _json: str

    @classmethod
    def from_dict(cls, data: dict) -> ResolvedBuildingInput:
        """Capture a detached portable view with an explicit format version."""
        if data.get("schema") != "epsm.resolved_building/1":
            raise ValueError("Unsupported resolved Building input schema")
        return cls(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False))

    @property
    def data(self) -> Mapping:
        return _freeze(json.loads(self._json))

    def to_dict(self) -> dict:
        """Return a new nested writable tree without modifying this view."""
        return json.loads(self._json)

    @property
    def source_id(self):
        return self.data["source_id"]

    @property
    def source_kind(self):
        return self.data["source_kind"]

    @property
    def source_snapshot_id(self):
        return self.data["source_snapshot_id"]

    @property
    def source_spec_hash(self):
        return self.data["source_spec_hash"]

    @property
    def geometry(self):
        return self.data["geometry"]

    @property
    def climate(self):
        return self.data["climate"]

    @property
    def surfaces(self):
        return self.data["surfaces"]

    @property
    def openings(self):
        return self.data["openings"]

    @property
    def zones(self):
        return self.data["zones"]

    @property
    def internal_mass(self):
        return self.data["internal_mass"]

    @property
    def operations(self):
        return self.data["operations"]

    @property
    def boundaries(self):
        return self.data["boundaries"]

    @property
    def shading(self):
        return self.data["shading"]

    @property
    def physical_elements(self):
        return self.data["physical_elements"]

    @property
    def logical_window_count(self):
        return len({opening["logical_window"] for opening in self.openings})

    def __repr__(self):
        return f"ResolvedBuildingInput(characters={len(self._json)})"


def _resolve(spec: BuildingSpec, *, snapshot: BuildingSnapshot | None = None,
             geometry_cache=None) -> ResolvedBuildingInput:
    # Revalidate a detached copy: frozen Pydantic fields can contain mutable maps.
    spec = BuildingSpec.model_validate(spec.model_dump())
    resolved = resolve_geometry(spec, panelize=True, cache=geometry_cache)
    graph = resolved.graph
    unknown_surfaces = set(spec.surface_constructions) - {face.name for face in graph.surfaces}
    if unknown_surfaces:
        raise ValueError(f"Unknown surface construction targets: {sorted(unknown_surfaces)}")
    if set(spec.internal_mass_constructions) - {mass["name"] for mass in graph.internal_mass}:
        raise ValueError("Unknown physical internal-mass construction targets")
    physical = snapshot.to_building() if snapshot is not None else None
    owners = {"surfaces": {}, "internal_mass": {}, "openings": {}}
    if physical is not None:
        from .building_adapter import _physical_element_owners

        owners = _physical_element_owners(physical, resolved)
    opening_areas = defaultdict(float)
    for opening in resolved.openings:
        opening_areas[opening.parent] += opening.area
    surfaces = []
    for face in graph.surfaces:
        role = face.construction.removesuffix("_reverse").removeprefix("unconditioned_")
        assembly = spec.surface_constructions.get(face.name, getattr(spec.envelope, role, None))
        owner = owners["surfaces"].get(face.name)
        surfaces.append({
            "name": face.name, "zone": face.zone, "kind": face.kind,
            "vertices": face.vertices, "part_id": face.part_id, "facade_id": face.facade_id,
            "storey": face.storey, "cell_kind": face.cell_kind,
            "boundary": face.boundary, "adjacent": face.adjacent,
            "construction_role": face.construction, "reverse": face.construction.endswith("_reverse"),
            "construction": assembly.model_dump(mode="json") if assembly is not None else None,
            "physical_element_id": owner.identifier if owner is not None else None,
            "physical_component_ids": owner.component_ids if owner is not None else (),
            "gross_area_m2": face.area, "opening_area_m2": opening_areas[face.name],
            "net_area_m2": face.area - opening_areas[face.name],
        })
    openings = []
    for opening in resolved.openings:
        owner = owners["openings"].get(opening.name)
        glazing = spec.facade.value_for("glazing", opening.metadata["facade_id"], opening.metadata["storey"])
        openings.append({
            "name": opening.name, "parent": opening.parent, "vertices": opening.vertices,
            "area_m2": opening.area, "logical_window": opening.metadata["logical_window"],
            "logical_vertices": opening.metadata.get("logical_vertices"), "metadata": opening.metadata,
            "construction": glazing.model_dump(mode="json"),
            "physical_element_id": owner.identifier if owner is not None else None,
        })
    internal_mass = []
    for mass in graph.internal_mass:
        owner = owners["internal_mass"].get(mass["name"])
        assembly = spec.internal_mass_constructions.get(mass["name"], spec.envelope.intermediate_floor)
        internal_mass.append({**mass, "construction": assembly.model_dump(mode="json"),
                              "physical_element_id": owner.identifier if owner is not None else None,
                              "physical_component_ids": owner.component_ids if owner is not None else ()})
    _, operations, _ = resolve_zone_operations(spec, graph.zones)
    zones = {}
    for name, zone in graph.zones.items():
        operation = operations.get(name)
        basis = operation.load_reference_area_basis if operation is not None else None
        if physical is not None and basis == "explicit" and physical.load_reference_area_policy is not None:
            basis = physical.load_reference_area_policy
        zones[name] = {**zone,
            "operation": operation.use.model_dump(mode="json") if operation is not None else None,
            "airflow": operation.airflow.model_dump(mode="json") if operation is not None else None,
            "load_reference_area_m2": operation.load_reference_area_m2 if operation is not None else None,
            "load_reference_area_basis": basis,
            "operation_sources": [assignment.source for assignment in operation.assignments]
                                 if operation is not None else [],
            "operation_references": [assignment.model_dump(mode="json") for assignment in operation.assignments]
                                    if operation is not None else [],
            "unconditioned_exchange": [exchange.model_dump(mode="json") for exchange in spec.unconditioned_exchange
                                       if not zone["conditioned"] and exchange.zone_kind == zone.get("physical_zone_kind")],
        }
    source_hash = spec.physical_hash()
    return ResolvedBuildingInput.from_dict({
        "schema": "epsm.resolved_building/1", "panelize": True,
        "source_id": snapshot.sha256 if snapshot is not None else source_hash,
        "source_kind": "building_snapshot" if snapshot is not None else "building_spec",
        "source_snapshot_id": snapshot.sha256 if snapshot is not None else None,
        "source_spec_hash": source_hash, "identifier": spec.identifier,
        "climate": spec.climate.model_dump(mode="json"),
        "provenance": spec.provenance.model_dump(mode="json"),
        "authoring": {"preset": physical.preset, "preset_revision": physical.preset_revision}
                     if physical is not None else None,
        "geometry": {**spec.geometry.model_dump(mode="json"),
                     "origin_m": resolved.origin, "orientation_deg": spec.geometry.orientation_deg,
                     "coordinate_frame": "local_metric_after_scene_rotation",
                     "local_footprints": [polygon.__geo_interface__ for polygon in resolved.polygons]},
        "surfaces": surfaces, "openings": openings, "zones": zones,
        "internal_mass": internal_mass, "shading": resolved.shading,
        "facades": resolved.facades,
        "physical_elements": [element.to_dict() for element in physical.elements] if physical is not None else [],
        "boundaries": {"foundation": spec.envelope.foundation.model_dump(mode="json"),
                       "ground_temperature": spec.envelope.ground_temperature.model_dump(mode="json")
                                             if spec.envelope.ground_temperature is not None else None,
                       "thermal_bridge_uplift_fraction": spec.envelope.thermal_bridge_uplift_fraction},
        "operations": {
            "use": spec.use.model_dump(mode="json"), "airflow": spec.airflow.model_dump(mode="json"),
            "common_use": spec.common_use.model_dump(mode="json") if spec.common_use is not None else None,
            "common_airflow": spec.common_airflow.model_dump(mode="json") if spec.common_airflow is not None else None,
            "zone_uses": [assignment.model_dump(mode="json") for assignment in spec.zone_uses],
            "unconditioned_exchange": [exchange.model_dump(mode="json") for exchange in spec.unconditioned_exchange],
            "load_reference_area_m2": spec.load_reference_area_m2,
            "load_reference_area_basis": physical.load_reference_area_basis if physical is not None else
                                         "explicit" if spec.load_reference_area_m2 is not None else "conditioned_floor_area_default",
            "load_reference_area_policy": physical.load_reference_area_policy if physical is not None else None,
            "delivery": spec.delivery.model_dump(mode="json"), "renewables": spec.renewables.model_dump(mode="json"),
        },
    })


def resolve_building(spec: BuildingSpec, *, geometry_cache=None) -> ResolvedBuildingInput:
    """Resolve an already validated spec without reading weather or initializing an engine.

    Reuses Core topology, openings, physical assignment overrides and operation
    selection. The source identity is the spec's physical hash; physical Building
    convenience methods instead retain their exact authoring snapshot identity.
    """
    return _resolve(spec, geometry_cache=geometry_cache)


def resolve_snapshot(snapshot: BuildingSnapshot, weather, *, geometry_cache=None) -> ResolvedBuildingInput:
    """Resolve an authoring snapshot with explicitly supplied Weather or ClimateSpec.

    Conversion requires complete authoring inputs. Passing a weather-file path
    retains the existing explicit weather-inspection behavior of ``to_spec``;
    already inspected Weather or ClimateSpec performs no file access here.
    """
    return _resolve(snapshot.to_spec(weather, geometry_cache=geometry_cache),
                    snapshot=snapshot, geometry_cache=geometry_cache)
