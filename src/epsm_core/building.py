"""Gradual physical building authoring with shared EPSM Data constructions.

``Building()`` preserves missing inputs; select a named preset explicitly.
``Building.empty()`` and ``Building.from_footprint()`` do not fill missing physics.
Catalogue objects are copied on assignment; runtime results are never snapshotted.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import UUID, uuid4

from epsm_data.domain import ConstructionSet, Element, WindowElement
from epsm_data.domain.enums import BuildingElement as ElementRole
from epsm_data.serialization import construction_set_from_dict, construction_set_to_dict
from pydantic import TypeAdapter

from ._representation import bounded_summary
from .inventory import MaterialFlows, material_inventory
from .specs import (
    AirflowSpec,
    ContextSpec,
    DeliverySpec,
    FacadeSpec,
    Footprint,
    FoundationSpec,
    GainPartitionSpec,
    GeometrySpec,
    GlazingSpec,
    GroundTemperatureSpec,
    ProvenanceSpec,
    RenewablesSpec,
    SourceRecord,
    UseSpec,
)
from .specs.base import Fraction, Nonnegative, Positive


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _copy_construction(value):
    return construction_set_from_dict(construction_set_to_dict(value))


def _encode_element(value):
    if value is None:
        return None
    return construction_set_to_dict(ConstructionSet(
        version_id=UUID(int=0), elements={value.application: value}))


def _decode_element(value):
    return next(iter(construction_set_from_dict(value).elements.values())) if value else None


class OperationProfile(UseSpec):
    """Validated occupancy, gains and thermostat schedules for gradual authoring."""

    def with_changes(self, **changes):
        return self.updated(**changes)

    def __repr__(self):
        return bounded_summary(type(self).__name__, category=self.occupancy_category,
                               occupants_per_m2=self.occupant_density_per_m2,
                               equipment_w_m2=self.equipment_gain_w_m2)

    __str__ = __repr__


@dataclass(frozen=True)
class InputAssignmentReport:
    """Applied physical inputs, retained choices and supplied roles without targets.

    Construction paths identify physical elements, for example
    ``construction:main.ground_floor``. Section paths name the supplied argument.
    This report describes assignment only; use ``Building.readiness()`` for
    remaining simulation requirements. ``to_dict()`` returns detached plain data.
    """

    applied: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    retained: tuple[str, ...] = ()
    unmatched: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("applied", "replaced", "retained", "unmatched"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def to_dict(self):
        """Return assignment paths without sharing mutable report state."""
        return {name: list(getattr(self, name))
                for name in ("applied", "replaced", "retained", "unmatched")}

    def __repr__(self):
        return bounded_summary(type(self).__name__, applied=len(self.applied),
                               replaced=len(self.replaced), retained=len(self.retained),
                               unmatched=len(self.unmatched))

    __str__ = __repr__


@dataclass(frozen=True)
class Equipment:
    """One installed product with a known count and optional external factor references."""

    identifier: str
    product_id: str
    count: float = 1
    description: str = ""
    factor_refs: tuple[tuple[str, str], ...] = ()
    occurrence_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self):
        if not self.identifier or not self.product_id or not math.isfinite(self.count) or self.count <= 0:
            raise ValueError("Equipment requires identities and a finite positive count")
        refs = self.factor_refs.items() if hasattr(self.factor_refs, "items") else self.factor_refs
        object.__setattr__(self, "factor_refs", tuple((str(k), str(v)) for k, v in refs))

    def to_dict(self):
        return {"identifier": self.identifier, "product_id": self.product_id, "count": self.count,
                "description": self.description, "factor_refs": dict(self.factor_refs),
                "occurrence_id": self.occurrence_id}

    def __repr__(self):
        return bounded_summary(type(self).__name__, identifier=self.identifier,
                               product=self.product_id, count=self.count)

    __str__ = __repr__


@dataclass(frozen=True)
class HVACSystem:
    """Explicit airflow, energy delivery and renewable equipment configuration."""

    airflow: AirflowSpec
    delivery: DeliverySpec = DeliverySpec()
    renewables: RenewablesSpec = RenewablesSpec()
    equipment: tuple[Equipment, ...] = ()

    def __post_init__(self):
        for name, kind in (("airflow", AirflowSpec), ("delivery", DeliverySpec),
                           ("renewables", RenewablesSpec)):
            value = getattr(self, name)
            object.__setattr__(self, name, kind.model_validate(
                value.model_dump() if isinstance(value, kind) else value))
        equipment = tuple(Equipment(**e.to_dict()) if isinstance(e, Equipment)
                          else Equipment(**e) for e in self.equipment)
        if len({e.identifier for e in equipment}) != len(equipment):
            raise ValueError("Installed equipment identifiers must be unique")
        object.__setattr__(self, "equipment", equipment)

    def with_changes(self, **changes):
        return replace(self, **changes)

    def __repr__(self):
        return bounded_summary(type(self).__name__, equipment=len(self.equipment),
                               heating=self.delivery.heating is not None,
                               ventilation_l_s_m2=self.airflow.mechanical_vent_l_s_m2)

    __str__ = __repr__

    def to_dict(self):
        return {**{name: getattr(self, name).model_dump(mode="json")
                   for name in ("airflow", "delivery", "renewables")},
                "equipment": [e.to_dict() for e in self.equipment]}

    @classmethod
    def from_template(cls, template, *, previous=None):
        """Resolve a Data HVAC template; unspecified existing systems are retained."""
        data = template.to_dict()["values"]
        values = previous.to_dict() if previous is not None else {}
        for name in ("airflow", "delivery", "renewables"):
            if name in data:
                values[name] = {**values.get(name, {}), **data[name]}
        if "equipment" in data:
            equipment = {e["identifier"]: e for e in values.get("equipment", ())}
            for record in data["equipment"]:
                equipment[record["identifier"]] = record
            values["equipment"] = list(equipment.values())
        return cls(**values)


@dataclass(frozen=True)
class BuildingElement:
    """One physical area with a construction; independent of thermal surfaces."""

    identifier: str
    role: ElementRole
    area_m2: float
    construction: Element | WindowElement | None = None
    part_id: str = "main"
    facade_id: str | None = None
    storey: int | None = None
    elevation_m: float | None = None
    component_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.identifier or not math.isfinite(self.area_m2) or self.area_m2 < 0:
            raise ValueError("Physical element requires an ID and finite nonnegative area")
        object.__setattr__(self, "role", ElementRole(self.role))
        if self.construction is not None:
            if not isinstance(self.construction, (Element, WindowElement)):
                raise TypeError("construction must be an EPSM Data Element or WindowElement")
            if self.construction.application != self.role:
                raise ValueError("Physical element role must match its construction")
        count = (1 if isinstance(self.construction, WindowElement) else
                 len(self.construction.components) if self.construction else 0)
        ids = tuple(self.component_ids) or tuple(str(uuid4()) for _ in range(count))
        if len(ids) != count or len(set(ids)) != len(ids):
            raise ValueError("Each installed component requires a unique occurrence ID")
        object.__setattr__(self, "component_ids", ids)

    @property
    def id(self):
        return self.identifier

    def with_changes(self, **changes):
        if "construction" in changes and "component_ids" not in changes:
            changes["component_ids"] = ()
        return replace(self, **changes)

    def __repr__(self):
        return bounded_summary(type(self).__name__, identifier=self.identifier,
                               role=self.role.value, area_m2=self.area_m2,
                               components=len(self.component_ids))

    __str__ = __repr__

    def to_dict(self):
        return {"identifier": self.identifier, "role": self.role.value,
                "area_m2": self.area_m2, "construction": _encode_element(self.construction),
                "part_id": self.part_id, "facade_id": self.facade_id,
                "storey": self.storey, "elevation_m": self.elevation_m,
                "component_ids": list(self.component_ids)}

    @classmethod
    def from_dict(cls, data):
        values = dict(data)
        values["construction"] = _decode_element(values.get("construction"))
        return cls(**values)


@dataclass(frozen=True)
class Readiness:
    missing: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()

    @property
    def ready(self):
        return not self.missing and not self.unsupported

    def __bool__(self):
        return self.ready

    def require(self):
        if not self:
            raise ValueError("Building is not ready: " + "; ".join((*self.missing, *self.unsupported)))
        return self

    def to_dict(self):
        return {"ready": self.ready, "missing": list(self.missing),
                "unsupported": list(self.unsupported)}

    def __repr__(self):
        return bounded_summary(type(self).__name__, ready=self.ready,
                               missing=len(self.missing), unsupported=len(self.unsupported))

    __str__ = __repr__


@dataclass(frozen=True)
class BuildingSnapshot:
    """Deep immutable resolved physical state, stored as canonical JSON."""

    _json: str

    @classmethod
    def from_dict(cls, data):
        if data.get("schema") not in {
                "epsm.building/1", "epsm.building/2", "epsm.building/3", "epsm.building/4",
                "epsm.building/5", "epsm.building/6"}:
            raise ValueError("Unsupported Building snapshot schema")
        return cls(_json(data))

    @property
    def sha256(self):
        return hashlib.sha256(self._json.encode()).hexdigest()

    @property
    def id(self):
        return self.sha256

    def to_dict(self):
        return json.loads(self._json)

    def to_building(self, building_type=None):
        return (building_type or Building).from_dict(self.to_dict())

    def to_spec(self, weather):
        return self.to_building().to_spec(weather)

    def resolve(self, weather):
        """Resolve retained physical inputs without initializing an engine."""
        from .resolved import resolve_snapshot

        return resolve_snapshot(self, weather)

    def quantities(self):
        return self.to_building().quantities()

    def __repr__(self):
        return bounded_summary(type(self).__name__, format="epsm.building",
                               characters=len(self._json))

    __str__ = __repr__


@dataclass(frozen=True)
class RenovationStage:
    stage_id: str
    order: int
    before: BuildingSnapshot
    after: BuildingSnapshot
    measure_ids: tuple[str, ...]
    material_flows: MaterialFlows
    incompatible_measure_ids: tuple[str, ...] = ()

    def __repr__(self):
        return bounded_summary(type(self).__name__, stage_id=self.stage_id,
                               order=self.order, measures=len(self.measure_ids))

    __str__ = __repr__


@dataclass(frozen=True)
class AuthoringLink:
    """An authoring revision following a renovation, without an assumed intervention.

    Both snapshots are retained. Changing installed identities or quantities
    requires a physical-history decision before lifecycle assessment is complete;
    changing an operating schedule does not invent material flows.
    """

    after_stage: int
    before: BuildingSnapshot
    after: BuildingSnapshot

    @property
    def changes_material_inventory(self):
        """Whether this revision changed installed physical quantities or identities."""
        fields = ("occurrence_id", "material_id", "element_id", "component_id", "layer_id",
                  "area_m2", "volume_m3", "mass_kg", "count", "kind")
        try:
            def inventory(snapshot):
                return sorted(tuple(getattr(row, field) for field in fields)
                              for row in snapshot.quantities())

            return inventory(self.before) != inventory(self.after)
        except (ValueError, TypeError):
            # An incomplete authoring state cannot establish unchanged inventory.
            return True

    def to_dict(self):
        return {"after_stage": self.after_stage,
                "before": self.before.to_dict(), "after": self.after.to_dict()}

    def __repr__(self):
        return bounded_summary(type(self).__name__, after_stage=self.after_stage)

    __str__ = __repr__


def _material_history_requirements(links):
    return tuple(
        f"material history after renovation step {link.after_stage}: authoring changed "
        "installed quantities or identities; resolve as an explicit renovation or revise the baseline"
        for link in links if link.changes_material_inventory)


class Building:
    """Editable physical building, with complete validation at method boundaries.

    The explicitly selected reference preset is illustrative, not calibrated evidence.
    Geometry/construction/HVAC/operation assignments are validated independently.
    ``readiness()`` describes what remains before a thermal simulation.
    """

    def __init__(self, *, preset=None, identifier="building",
                 geometry=None, construction_set=None, facade=None, hvac=None,
                 operation=None, context=None, provenance=None, foundation=None,
                 ground_temperature=None, thermal_bridge_uplift_fraction=None,
                 load_reference_area_m2=None,
                 load_reference_area_policy: Literal["conditioned_floor_area"] | None = None):
        if load_reference_area_m2 is not None and load_reference_area_policy is not None:
            raise ValueError("Choose either load_reference_area_m2 or load_reference_area_policy")
        self._elements = ()
        self._stages = ()
        self._authoring_links = ()
        self._material_flows = ()
        self._parent_snapshot_id = None
        self.preset = preset
        self.preset_revision = "5" if preset is not None else None
        supplied = {name for name, value in (("geometry", geometry),
            ("construction_set", construction_set), ("facade", facade),
            ("hvac", hvac), ("operation", operation), ("foundation", foundation),
            ("ground_temperature", ground_temperature),
            ("thermal_bridge_uplift_fraction", thermal_bridge_uplift_fraction),
            ("load_reference_area_m2", load_reference_area_m2),
            ("load_reference_area_policy", load_reference_area_policy))
            if value is not None}
        self.identifier = identifier
        if preset is not None:
            if preset != "illustrative-reference":
                raise ValueError(f"Unknown Building preset {preset!r}")
            from epsm_data import reference_construction_set, reference_hvac_template

            from .standards import load_sveby_spec

            geometry = geometry if geometry is not None else GeometrySpec.from_footprint(
                Footprint.rectangle(20, 12), storeys=3, storey_height_m=2.8)
            construction_set = construction_set if construction_set is not None else reference_construction_set()
            hvac = hvac if hvac is not None else HVACSystem.from_template(reference_hvac_template())
            if operation is None:
                operation = OperationProfile.model_validate({
                    **load_sveby_spec().use_spec().model_dump(),
                    "gain_partitions": GainPartitionSpec(policy="epsm_legacy_v1"),
                })
            foundation = foundation if foundation is not None else FoundationSpec(
                method="kiva",
                source="energyplus_24_2_kiva_unmeasured_defaults",
                soil_conductivity_w_mk=1.73,
                soil_density_kg_m3=1842.0,
                soil_specific_heat_j_kgk=419.0,
                exposed_perimeter_fraction=1.0,
                wall_height_above_grade_m=0.0,
                wall_depth_below_slab_m=0.0,
                deep_ground_boundary="ZeroFlux",
                deep_ground_depth_m=40.0,
                far_field_width_m=40.0,
            )
            if thermal_bridge_uplift_fraction is None:
                thermal_bridge_uplift_fraction = 0.0
            if load_reference_area_m2 is None and load_reference_area_policy is None:
                load_reference_area_policy = "conditioned_floor_area"
            if facade is None:
                window = construction_set.elements.get(ElementRole.WINDOW)
                facade = FacadeSpec(default_wwr=.2, glazing=GlazingSpec(
                    u_value_w_m2k=window.u_value, solar_heat_gain_coefficient=window.shgc,
                    visible_transmittance=window.vt))
        self.geometry = geometry
        self.construction_set = construction_set
        self.facade = facade
        self.hvac = hvac
        self.operation = operation
        self.foundation = foundation
        self.ground_temperature = ground_temperature
        self.thermal_bridge_uplift_fraction = thermal_bridge_uplift_fraction
        self.load_reference_area_m2 = load_reference_area_m2
        self.load_reference_area_policy = load_reference_area_policy
        self.context = context if context is not None else ContextSpec()
        records = list(ProvenanceSpec.model_validate(provenance or {}).records)
        if preset is not None:
            paths = {r.field_path for r in records}
            records.extend(SourceRecord(field_path=name, status="assumed",
                source="illustrative-reference@5", assumption_profile="illustrative-reference@5")
                for name in ("geometry", "construction_set", "facade", "hvac", "operation",
                             "foundation", "thermal_bridge_uplift_fraction",
                             "load_reference_area_policy")
                if name not in supplied and name not in paths and getattr(self, name) is not None)
        self.provenance = ProvenanceSpec(records=tuple(records))

    def __setattr__(self, name, value):
        if name in {"preset", "preset_revision"} and hasattr(self, name):
            raise AttributeError("Preset identity is retained metadata; create a new Building to select a preset")
        kinds = {"geometry": GeometrySpec, "facade": FacadeSpec,
                 "operation": OperationProfile, "context": ContextSpec, "provenance": ProvenanceSpec}
        kinds.update({"foundation": FoundationSpec, "ground_temperature": GroundTemperatureSpec})
        if name in kinds and value is not None:
            kind = kinds[name]
            if name == "operation" and isinstance(value, UseSpec):
                value = value.model_dump()
            value = kind.model_validate(
                value.model_dump(exclude_unset=True) if isinstance(value, kind) else value)
        elif name == "construction_set" and value is not None:
            if not isinstance(value, ConstructionSet):
                raise TypeError("construction_set must be an EPSM Data ConstructionSet")
            value = _copy_construction(value)
        elif name == "hvac" and value is not None:
            if not isinstance(value, HVACSystem):
                raise TypeError("hvac must be an HVACSystem")
            value = HVACSystem(**value.to_dict())
        elif name == "identifier" and (not isinstance(value, str) or not value.strip()):
            raise ValueError("identifier must be a nonempty string")
        elif name == "thermal_bridge_uplift_fraction" and value is not None:
            value = TypeAdapter(Nonnegative).validate_python(value)
            if not math.isfinite(value):
                raise ValueError("thermal_bridge_uplift_fraction must be finite")
        elif name == "load_reference_area_m2" and value is not None:
            value = TypeAdapter(Positive).validate_python(value)
            if not math.isfinite(value):
                raise ValueError("load_reference_area_m2 must be finite")
            current_policy = getattr(self, "load_reference_area_policy", None)
            if current_policy is not None:
                assumed_profile = f"{getattr(self, 'preset', None)}@{getattr(self, 'preset_revision', None)}"
                policy_record = next((r for r in getattr(
                    self, "provenance", ProvenanceSpec()).records
                    if r.field_path == "load_reference_area_policy"), None)
                if not (policy_record and policy_record.status == "assumed"
                        and policy_record.assumption_profile == assumed_profile):
                    raise ValueError("Clear the policy before setting an explicit load-reference area")
                object.__setattr__(self, "load_reference_area_policy", None)
                if hasattr(self, "provenance"):
                    object.__setattr__(self, "provenance", ProvenanceSpec(records=tuple(
                        r for r in self.provenance.records
                        if r.field_path != "load_reference_area_policy")))
        elif name == "load_reference_area_policy" and value is not None:
            value = TypeAdapter(Literal["conditioned_floor_area"]).validate_python(value)
            if getattr(self, "load_reference_area_m2", None) is not None:
                raise ValueError("Clear the area before setting a load-reference area policy")
        object.__setattr__(self, name, value)
        if name in {"geometry", "construction_set", "facade", "hvac", "operation",
                    "foundation", "ground_temperature", "thermal_bridge_uplift_fraction",
                    "load_reference_area_m2", "load_reference_area_policy"} \
                and hasattr(self, "provenance"):
            object.__setattr__(self, "provenance", ProvenanceSpec(records=tuple(
                r for r in self.provenance.records
                if r.field_path != name and not r.field_path.startswith(name + "."))))
        if name in {"geometry", "construction_set", "facade"}:
            self._rebuild_elements(reassign=name == "construction_set")

    def __delattr__(self, name):
        if name in {"preset", "preset_revision"}:
            raise AttributeError("Preset identity cannot be deleted")
        object.__delattr__(self, name)

    @property
    def id(self):
        return self.identifier

    def __repr__(self):
        return bounded_summary(type(self).__name__, identifier=self.identifier,
                               parts=len(self.geometry.parts) if self.geometry else 0,
                               elements=len(self.elements), stages=len(self.stages),
                               preset=self.preset)

    __str__ = __repr__

    @classmethod
    def empty(cls, **kwargs):
        return cls(preset=None, **kwargs)

    @classmethod
    def from_footprint(cls, footprint, *, storeys=None, storey_height_m=None,
                       storey_elevations_m=None, identifier="building", construction_set=None,
                       facade=None, hvac=None, operation=None, context=None, foundation=None,
                       ground_temperature=None, thermal_bridge_uplift_fraction=None,
                       load_reference_area_m2=None, load_reference_area_policy=None,
                       **geometry_options):
        geometry = GeometrySpec.from_footprint(
            footprint, storeys=storeys, storey_height_m=storey_height_m,
            storey_elevations_m=storey_elevations_m, **geometry_options)
        return cls.empty(identifier=identifier, geometry=geometry,
                         construction_set=construction_set, facade=facade, hvac=hvac,
                         operation=operation, context=context, foundation=foundation,
                         ground_temperature=ground_temperature,
                         thermal_bridge_uplift_fraction=thermal_bridge_uplift_fraction,
                         load_reference_area_m2=load_reference_area_m2,
                         load_reference_area_policy=load_reference_area_policy)

    @property
    def effective_load_reference_area_m2(self):
        """Return the explicit or policy-resolved load area, separate from physical floor area."""
        if self.load_reference_area_m2 is not None:
            return self.load_reference_area_m2
        if self.load_reference_area_policy == "conditioned_floor_area" and self.geometry is not None:
            return self.geometry.conditioned_floor_area_m2
        return None

    @property
    def load_reference_area_basis(self):
        """Report whether the load area is explicit, policy-derived or still missing."""
        if self.load_reference_area_m2 is not None:
            return "explicit"
        if self.load_reference_area_policy is not None:
            return "policy"
        return "missing"

    @property
    def elements(self):
        return self._elements

    @elements.setter
    def elements(self, values):
        values = tuple(values)
        if any(not isinstance(value, BuildingElement) for value in values):
            raise TypeError("elements must contain physical BuildingElement objects")
        if len({value.identifier for value in values}) != len(values):
            raise ValueError("Physical element identifiers must be unique")
        self._elements = tuple(BuildingElement.from_dict(value.to_dict()) for value in values)

    def assign_construction(self, construction, *, element_ids=None):
        """Assign a resolved construction independently to selected physical elements."""
        selected = set(element_ids or [e.identifier for e in self.elements
                                      if e.role == construction.application])
        if not selected or not selected <= {e.identifier for e in self.elements}:
            raise ValueError("Construction targets must identify existing physical elements")
        updated = tuple(e.with_changes(construction=construction) if e.identifier in selected else e
                        for e in self.elements)
        self.elements = updated
        return self

    def assign_inputs(self, *, construction_set=None, operation=None, hvac=None,
                      facade_properties=None, thermal_bridge_uplift_fraction=None,
                      provenance=None, mode="replace"):
        """Validate and commit resolved inputs together, updating this Building.

        Parameters
        ----------
        construction_set : epsm_data.ConstructionSet, optional
            Replace supplied roles only. ``fill_missing`` assigns only physical
            elements that currently have no construction, retaining overrides.
        operation : OperationProfile or mapping, optional
            Validated occupancy, gains and schedules; no calendar is inferred.
        hvac : HVACSystem, optional
            Already resolved systems, including infiltration reference basis.
        facade_properties : mapping, optional
            Only ``glazing`` and ``solar_shading_factor`` are accepted. An absent
            facade stays missing: this operation never guesses opening geometry.
        thermal_bridge_uplift_fraction : float, optional
            Nonnegative finite uplift. Zero explicitly assigns no uplift.
        provenance : ProvenanceSpec or mapping, optional
            Source records for changed inputs. Existing records for retained
            fields survive; replacement drops stale records at changed paths.
        mode : {"replace", "fill_missing"}
            Replace supplied sections or fill absent sections, respectively.
            Omitted sections always stay unchanged.

        Returns
        -------
        InputAssignmentReport
            Physical assignment paths and supplied roles with no geometry target.

        Notes
        -----
        Every supplied value is validated before committing any change, including
        inputs retained in ``fill_missing`` mode. Geometry, actual opening areas,
        element IDs, context, ground configuration and earlier snapshots remain
        unchanged. Authoring changes do not add renovation stages or material
        flows; later material changes remain visible in authoring lineage.
        No catalogue, weather, file or service is loaded.
        """
        if mode not in {"replace", "fill_missing"}:
            raise ValueError("mode must be 'replace' or 'fill_missing'")
        candidate = Building.from_dict(self._snapshot_data())
        records = ProvenanceSpec.model_validate(provenance or {}).records
        supplied = {
            "operation": operation, "hvac": hvac,
            "thermal_bridge_uplift_fraction": thermal_bridge_uplift_fraction,
        }
        # The detached candidate validates all inputs, even those later retained.
        for name, value in supplied.items():
            if value is not None:
                setattr(candidate, name, value)
        if construction_set is not None:
            candidate.construction_set = construction_set
        properties = dict(facade_properties) if facade_properties is not None else None
        if properties is not None:
            if set(properties) - {"glazing", "solar_shading_factor"}:
                raise ValueError("facade_properties accepts glazing and solar_shading_factor only")
            if "glazing" in properties:
                properties["glazing"] = GlazingSpec.model_validate(properties["glazing"])
            if "solar_shading_factor" in properties:
                properties["solar_shading_factor"] = TypeAdapter(Fraction).validate_python(
                    properties["solar_shading_factor"])
        applied, replaced, retained, unmatched, changed = [], [], [], [], set()
        updates = {}
        for name, value in supplied.items():
            if value is None:
                continue
            if mode == "fill_missing" and getattr(self, name) is not None:
                retained.append(name)
            else:
                (applied if getattr(self, name) is None else replaced).append(name)
                updates[name] = getattr(candidate, name)
                changed.add(name)
        if properties is not None:
            if self.facade is None:
                unmatched.append("facade_properties")
            elif mode == "fill_missing":
                retained.append("facade_properties")
            else:
                updates["facade"] = self.facade.updated(**properties)
                replaced.append("facade_properties")
                changed.update("facade." + name for name in properties)
        construction_targets = set()
        if construction_set is not None:
            incoming = candidate.construction_set
            existing = self.construction_set.elements if self.construction_set else {}
            values = dict(existing)
            for role, construction in incoming.elements.items():
                if not any(element.role == role for element in self.elements):
                    unmatched.append("construction:" + role.value)
                elif mode == "replace" or role not in values:
                    values[role] = construction
                    changed.add("construction_set.elements." + role.value)
            if values != dict(existing):
                # A mixed default set is a new authored composition, not the
                # incoming catalogue snapshot with another snapshot's identity.
                updates["construction_set"] = ConstructionSet(elements=values)
            elements = []
            for element in self.elements:
                path = "construction:" + element.identifier
                if element.role not in incoming.elements:
                    retained.append(path)
                    elements.append(element)
                elif mode == "fill_missing" and element.construction is not None:
                    retained.append(path)
                    elements.append(element)
                else:
                    (applied if element.construction is None else replaced).append(path)
                    elements.append(element.with_changes(
                        construction=incoming.elements[element.role]))
                    path = "elements." + element.identifier + ".construction"
                    changed.add(path)
                    construction_targets.add(path)
            # Copy through the public element validation without regenerating openings.
            candidate.elements = elements
            updates["_elements"] = candidate.elements
        glazing_targets = set()
        if properties is not None and self.facade is not None and mode == "replace" \
                and "glazing" in properties:
            glazing = properties["glazing"]
            elements = []
            for element in updates.get("_elements", self.elements):
                if element.role != ElementRole.WINDOW:
                    elements.append(element)
                    continue
                if not isinstance(element.construction, WindowElement):
                    raise ValueError("Glazing properties require physical WindowElement constructions")
                window = element.construction.with_changes(
                    u_value=glazing.u_value_w_m2k, shgc=glazing.solar_heat_gain_coefficient,
                    vt=glazing.visible_transmittance)
                elements.append(element.with_changes(construction=window))
                path = "elements." + element.identifier + ".construction"
                changed.add(path)
                glazing_targets.add(path)
            candidate.elements = elements
            updates["_elements"] = candidate.elements

        def affected(path):
            return any(path == key or path.startswith(key + ".") for key in changed)

        def split_previous(record, value):
            # Broad provenance is narrowed before partial edits, so unchanged
            # roles and facade geometry keep their original sources.
            path = record.field_path
            if affected(path):
                return []
            if not any(key.startswith(path + ".") for key in changed) or not isinstance(value, dict):
                return [record]
            return [child for key, item in value.items()
                    for child in split_previous(record.updated(field_path=path + "." + key), item)]

        state = self._snapshot_data()
        state["elements"] = {element.identifier: element.to_dict() for element in self.elements}

        def source_value(path):
            value = state
            for part in path.split("."):
                if not isinstance(value, dict) or part not in value:
                    return None
                value = value[part]
            return value

        previous = [child for record in self.provenance.records
                    for child in split_previous(record, source_value(record.field_path))]
        for record in records:
            paths = ([record.field_path] if affected(record.field_path) else
                     [key for key in changed if key.startswith(record.field_path + ".")])
            # A construction-set source also describes its actual element assignments.
            if record.field_path == "construction_set" and construction_set is not None:
                paths.extend(key for key in changed if key.startswith("elements.")
                             and key not in glazing_targets)
                paths.extend(path + "." + name for path in glazing_targets & construction_targets
                             for name in ("name", "archetype", "application", "boverket_id"))
            glazing_fields = {"u_value_w_m2k": "u_value",
                              "solar_heat_gain_coefficient": "shgc",
                              "visible_transmittance": "vt"}
            for name, physical_name in glazing_fields.items():
                if record.field_path in {"facade", "facade.glazing", "facade.glazing." + name}:
                    paths.extend(path + "." + physical_name for path in glazing_targets)
            previous.extend(record.updated(field_path=path) for path in sorted(set(paths)))
        updates["provenance"] = ProvenanceSpec(records=tuple(previous))
        # Every value is detached and validated above; committing cannot invoke a
        # setter that rebuilds geometry or removes freshly attached source records.
        for name, value in updates.items():
            object.__setattr__(self, name, value)
        return InputAssignmentReport(tuple(applied), tuple(replaced),
                                     tuple(retained), tuple(unmatched))

    def _rebuild_elements(self, *, reassign=False):
        geometry = getattr(self, "geometry", None)
        if geometry is None:
            self._elements = ()
            return
        previous = {e.identifier: e for e in self._elements}
        from .physical_geometry import physical_elements

        generated = physical_elements(geometry, getattr(self, "facade", None),
                                      getattr(self, "construction_set", None))
        self._elements = tuple(
            replace(e, construction=previous[e.identifier].construction,
                    component_ids=previous[e.identifier].component_ids)
            if not reassign and e.identifier in previous and previous[e.identifier].construction
            else e for e in generated)

    def readiness(self, purpose="energy", *, engine=None, weather=None):
        if engine not in {None, "energyplus", "epsm_rc"}:
            raise ValueError(f"Unsupported simulation engine {engine!r}")
        if purpose not in {"geometry", "energy", "quantities", "inventory", "lca"}:
            raise ValueError(f"Unknown readiness purpose {purpose!r}")
        missing, unsupported = [], []
        if self.geometry is None:
            missing.append("geometry")
        if purpose == "geometry":
            return Readiness(tuple(missing))
        from .physical_geometry import geometry_limitations

        if self.geometry is not None:
            unsupported.extend(geometry_limitations(self.geometry))
        if not self.elements:
            missing.append("physical elements")
        missing.extend(f"construction:{e.identifier}" for e in self.elements
                       if e.construction is None)
        if self.facade is None:
            missing.append("facade (explicit opening/opaque-area information)")
        if purpose not in {"quantities", "inventory", "lca"}:
            if self.geometry is not None and self.facade is not None:
                from .physical_geometry import physical_geometry_mismatches

                unsupported.extend(physical_geometry_mismatches(
                    self.geometry, self.facade, self.elements))
            for name in ("hvac", "operation"):
                if getattr(self, name) is None:
                    missing.append(name)
            missing.extend(self._ground_boundary_missing())
            if self.thermal_bridge_uplift_fraction is None:
                missing.append("thermal_bridge_uplift_fraction")
            if self.load_reference_area_m2 is None and self.load_reference_area_policy is None:
                missing.append("load_reference_area_m2 or load_reference_area_policy")
            elif self.load_reference_area_m2 is not None and self.load_reference_area_policy is not None:
                unsupported.append("Choose either load_reference_area_m2 or load_reference_area_policy")
            if engine == "epsm_rc" and self.geometry is not None:
                if self.geometry.basement_depth_m or any(not p.conditioned for p in self.geometry.parts):
                    unsupported.append("epsm_rc requires a single conditioned domain without basement")
                if self.context.buildings:
                    unsupported.append("epsm_rc does not model explicit context shading")
                if self.facade is not None and (self.facade.balconies
                        or self.facade.reveal_depth_m or self.facade.overhang.depth_m
                        or any(o.reveal_depth_m or (o.overhang and o.overhang.depth_m)
                               for o in self.facade.overrides)):
                    unsupported.append("epsm_rc does not model explicit facade shading geometry")
            for element in self.elements:
                if (element.role == ElementRole.WINDOW and element.construction is not None
                        and not isinstance(element.construction, WindowElement)):
                    unsupported.append(
                        f"{element.identifier}: layered window thermal representation is unsupported")
                if not isinstance(element.construction, Element):
                    continue
                layers = [s.layer for c in element.construction.components for s in c.layers]
                if len(layers) > 10:
                    unsupported.append(f"{element.identifier}: engine bridge supports at most 10 layers")
                if any(abs(m.thickness - layer.thickness) > 1e-9
                       for layer in layers for m in layer.materials):
                    unsupported.append(f"{element.identifier}: unequal parallel thermal path depths")
        if engine == "energyplus" and not missing and not unsupported \
                and self.foundation is not None and self.foundation.method == "kiva":
            from .preflight import _preflight_building_kiva

            unsupported.extend(_preflight_building_kiva(self).unsupported)
        return Readiness(tuple(missing), tuple(unsupported))

    def _ground_boundary_missing(self):
        """Return missing ground inputs without resolving omitted authoring values."""
        missing = []
        foundation = self.foundation
        temperatures = self.ground_temperature
        if foundation is None:
            return ("foundation",)
        supplied = foundation.model_fields_set
        if "method" not in supplied:
            missing.append("foundation.method")
            return tuple(missing)
        if foundation.method == "kiva":
            if temperatures is not None:
                missing.append("Kiva conflicts with prescribed ground temperatures")
            required = (
                "source", "soil_conductivity_w_mk", "soil_density_kg_m3",
                "soil_specific_heat_j_kgk", "exposed_perimeter_fraction",
                "wall_height_above_grade_m", "wall_depth_below_slab_m",
                "deep_ground_boundary", "deep_ground_depth_m", "far_field_width_m",
            )
            missing.extend(f"foundation.{name}" for name in required if name not in supplied)
            if foundation.footing_material is not None:
                missing.extend(f"foundation.{name}" for name in ("footing_depth_m", "footing_width_m")
                               if name not in supplied)
        elif foundation.method == "prescribed_temperature":
            kiva_only = supplied - {"method", "source"}
            if kiva_only:
                missing.append("prescribed_temperature cannot include Kiva parameters")
            if temperatures is None:
                missing.append("ground_temperature")
            else:
                temperature_fields = temperatures.model_fields_set
                missing.extend(f"ground_temperature.{name}" for name in
                               ("monthly_temperatures_c", "source")
                               if name not in temperature_fields)
        return tuple(missing)

    def quantities(self):
        self.readiness("quantities").require()
        return material_inventory(self.elements, self.hvac.equipment if self.hvac else ())

    def _snapshot_data(self):
        return {
            "schema": "epsm.building/6", "identifier": self.identifier, "preset": self.preset,
            "preset_revision": self.preset_revision,
            "provenance": self.provenance.model_dump(mode="json"),
            "geometry": self.geometry.model_dump(mode="json") if self.geometry else None,
            "construction_set": construction_set_to_dict(self.construction_set)
            if self.construction_set else None,
            "facade": self.facade.model_dump(mode="json") if self.facade else None,
            "hvac": self.hvac.to_dict() if self.hvac else None,
            "operation": self.operation.model_dump(mode="json") if self.operation else None,
            "foundation": self.foundation.model_dump(mode="json", exclude_unset=True)
            if self.foundation else None,
            "ground_temperature": self.ground_temperature.model_dump(mode="json", exclude_unset=True)
            if self.ground_temperature else None,
            "thermal_bridge_uplift_fraction": self.thermal_bridge_uplift_fraction,
            "load_reference_area_m2": self.load_reference_area_m2,
            "load_reference_area_policy": self.load_reference_area_policy,
            "context": self.context.model_dump(mode="json"),
            "elements": [e.to_dict() for e in self.elements],
        }

    def snapshot(self):
        """Capture state without rewriting an untouched historical snapshot."""
        data = self._snapshot_data()
        if getattr(self, "_origin_state", None) == _json(data):
            return self._origin_snapshot
        return BuildingSnapshot.from_dict(data)

    @classmethod
    def from_dict(cls, data):
        BuildingSnapshot.from_dict(data)
        result = cls.empty(identifier=data["identifier"])
        result.geometry = data["geometry"]
        result.construction_set = construction_set_from_dict(data["construction_set"]) \
            if data.get("construction_set") else None
        result.facade = data["facade"]
        result.hvac = HVACSystem(**data["hvac"]) if data["hvac"] else None
        result.operation = data["operation"]
        result.foundation = data.get("foundation")
        result.ground_temperature = data.get("ground_temperature")
        result.thermal_bridge_uplift_fraction = data.get("thermal_bridge_uplift_fraction")
        result.load_reference_area_m2 = data.get("load_reference_area_m2")
        result.load_reference_area_policy = data.get("load_reference_area_policy")
        result.context = data.get("context", {})
        result.elements = [BuildingElement.from_dict(e) for e in data["elements"]]
        object.__setattr__(result, "preset", data.get("preset"))
        object.__setattr__(result, "preset_revision", data.get("preset_revision"))
        result.provenance = data.get("provenance", {})
        result._origin_snapshot = BuildingSnapshot.from_dict(data)
        result._origin_state = _json(result._snapshot_data())
        return result

    @classmethod
    def from_snapshot(cls, snapshot):
        return cls.from_dict(snapshot.to_dict())

    def to_dict(self):
        return self.snapshot().to_dict()

    def _copy_runtime_configuration_to(self, child):
        """Optional subclass hook for evaluation settings; never copy result history."""

    def copy(self):
        child = type(self).from_snapshot(self.snapshot())
        child._stages = self._stages
        child._authoring_links = self.authoring_links
        child._material_flows = self._material_flows
        child._parent_snapshot_id = self._parent_snapshot_id
        self._copy_runtime_configuration_to(child)
        return child

    @property
    def stages(self):
        return self._stages

    @property
    def material_flows(self):
        return self._material_flows

    @property
    def parent_snapshot_id(self):
        return self._parent_snapshot_id

    @property
    def authoring_links(self):
        """Preserved edits between stages, plus edits after the most recent stage.

        The current editable state is one authoring revision, not another
        renovation stage. Its material changes are never inferred as installations.
        """
        historical = tuple(link for link in self._authoring_links
                           if link.after_stage < len(self.stages))
        if self.stages:
            before, after = self.stages[-1].after, self.snapshot()
            if before.sha256 != after.sha256:
                return (*historical, AuthoringLink(len(self.stages), before, after))
        return historical

    @property
    def material_history_requirements(self):
        """Unresolved material-affecting authoring edits, including the current draft."""
        return _material_history_requirements(self.authoring_links)

    def lineage_to_dict(self):
        """Detached ordered history, separate from the physical snapshot."""
        links = self.authoring_links
        return {"parent_snapshot_id": self.parent_snapshot_id,
                "authoring_links": [link.to_dict() for link in links],
                "material_history_requirements": list(_material_history_requirements(links)),
                "stages": [
            {"stage_id": stage.stage_id, "order": stage.order,
             "before": stage.before.to_dict(), "after": stage.after.to_dict(),
             "measure_ids": list(stage.measure_ids),
             "incompatible_measure_ids": list(stage.incompatible_measure_ids)}
            for stage in self.stages]}

    def restore_lineage(self, data):
        """Restore renovation and authoring links without inventing material flows.

        Every discontinuity between renovation snapshots or the current state
        requires a matching explicit authoring link. A failed restore is atomic.
        """
        from .inventory import MaterialInventory

        stages = []
        for order, item in enumerate(data.get("stages", ()), 1):
            if item["order"] != order or not item["stage_id"]:
                raise ValueError("Lineage stages require contiguous order and nonempty identities")
            before = BuildingSnapshot.from_dict(item["before"])
            after = BuildingSnapshot.from_dict(item["after"])
            old = {q.occurrence_id: q for q in before.quantities()}
            new = {q.occurrence_id: q for q in after.quantities()}
            flow = MaterialFlows(item["stage_id"], order,
                MaterialInventory(q for key, q in new.items() if key not in old),
                MaterialInventory(q for key, q in old.items() if key not in new),
                MaterialInventory(q for key, q in new.items() if key in old))
            stages.append(RenovationStage(item["stage_id"], order, before, after,
                                         tuple(item["measure_ids"]), flow,
                                         tuple(item.get("incompatible_measure_ids", ()))))
        parent = data.get("parent_snapshot_id")
        if stages and parent != stages[-1].before.sha256:
            raise ValueError("Parent snapshot does not match the final transition")
        links = {}
        for item in data.get("authoring_links", ()):
            order = item["after_stage"]
            if (isinstance(order, bool) or not isinstance(order, int)
                    or not 1 <= order <= len(stages) or order in links):
                raise ValueError("Each authoring link must follow one existing renovation stage")
            links[order] = AuthoringLink(order, BuildingSnapshot.from_dict(item["before"]),
                                        BuildingSnapshot.from_dict(item["after"]))
        for index, stage in enumerate(stages):
            following = stages[index + 1].before if index + 1 < len(stages) else self.snapshot()
            link = links.get(index + 1)
            if stage.after.sha256 == following.sha256:
                if link is not None:
                    raise ValueError("Unchanged lineage states must not have an authoring link")
            elif (link is None or link.before.sha256 != stage.after.sha256
                  or link.after.sha256 != following.sha256):
                raise ValueError("Lineage discontinuity requires a matching authoring link")
        ordered_links = tuple(links[order] for order in sorted(links))
        if ("material_history_requirements" in data
                and tuple(data["material_history_requirements"])
                != _material_history_requirements(ordered_links)):
            raise ValueError("Saved material history requirements differ from the authoring links")
        self._stages = tuple(stages)
        self._authoring_links = ordered_links
        self._material_flows = tuple(stage.material_flows for stage in stages)
        self._parent_snapshot_id = parent
        return self

    def renovate(self, *measures):
        """Apply a transactional ordered stage and return an independent same-type child.

        Explicit replacements create new occurrences even for identical products.
        Unchanged component IDs survive additions/removals and movement in the stack.
        """
        from epsm_data.operations import ConstructionOperation, SystemOperation

        if not measures:
            raise ValueError("renovate requires at least one measure")
        selected_ids = [m.measure_id for m in measures if hasattr(m, "measure_id")]
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError("A renovation bundle cannot repeat a measure ID")
        previous_ids = {identifier for stage in self.stages for identifier in stage.measure_ids}
        excluded = {identifier for stage in self.stages
                    for identifier in stage.incompatible_measure_ids}
        if excluded.intersection(selected_ids):
            raise ValueError("A selected measure is incompatible with an earlier renovation")
        available = set(previous_ids)
        all_ids = previous_ids | set(selected_ids)
        for measure in measures:
            if set(getattr(measure, "incompatible_measure_ids", ())).intersection(all_ids):
                raise ValueError("Incompatible renovation measures selected")
            required = set(getattr(measure, "requires_measure_ids", ()))
            if not required <= available:
                raise ValueError("Renovation prerequisites must occur earlier: "
                                 + ", ".join(sorted(required - available)))
            if hasattr(measure, "measure_id"):
                available.add(measure.measure_id)
        before = self.snapshot()
        old_inventory = {q.occurrence_id: q for q in self.quantities()}
        child = self.copy()
        identifiers = []
        for measure in measures:
            operations = (measure,) if isinstance(measure, (ConstructionOperation, SystemOperation)) \
                else getattr(measure, "operations", ())
            if not operations:
                raise ValueError("Renovation measure has no resolved physical operations")
            identifiers.append(getattr(measure, "measure_id", getattr(measure, "action", "measure")))
            selected = set(getattr(measure, "target_element_ids", ()))
            if selected and not selected <= {e.identifier for e in child.elements}:
                raise ValueError("Renovation targets contain unknown physical elements")
            affected = set()
            for operation in operations:
                if isinstance(operation, SystemOperation):
                    if selected:
                        raise ValueError("HVAC replacement does not accept envelope-element selectors")
                    child.hvac = HVACSystem.from_template(operation.template, previous=child.hvac)
                    continue
                targets = [e for e in child.elements if e.role == operation.role
                           and (not selected or e.identifier in selected)]
                if not targets:
                    raise ValueError(f"No physical targets for {operation.role.value}")
                changed = {}
                for element in targets:
                    if element.construction is None:
                        raise ValueError(f"Target {element.identifier} has no construction")
                    resolved = operation.apply(ConstructionSet(
                        elements={element.role: element.construction})).elements[element.role]
                    ids = list(element.component_ids)
                    if operation.action == "replace_element":
                        ids = []
                    elif operation.action == "add_component":
                        ids.insert(operation.position, str(uuid4()))
                    else:
                        index = next(i for i, c in enumerate(element.construction.components)
                                     if c.name == operation.target_component)
                        if operation.action == "remove_component":
                            ids.pop(index)
                        else:
                            ids[index] = str(uuid4())
                    changed[element.identifier] = element.with_changes(
                        construction=resolved, component_ids=tuple(ids))
                    affected.add(element.identifier)
                child._elements = tuple(changed.get(e.identifier, e) for e in child.elements)
            if selected and affected != selected:
                raise ValueError("Some selected physical elements were not affected by the measure")
        new_inventory = {q.occurrence_id: q for q in child.quantities()}
        from .inventory import MaterialInventory

        stage_id, order = str(uuid4()), len(self.stages) + 1
        flows = MaterialFlows(stage_id, order,
            MaterialInventory(q for key, q in new_inventory.items() if key not in old_inventory),
            MaterialInventory(q for key, q in old_inventory.items() if key not in new_inventory),
            MaterialInventory(q for key, q in new_inventory.items() if key in old_inventory))
        incompatible = tuple(sorted({identifier for measure in measures
                                     for identifier in getattr(measure, "incompatible_measure_ids", ())}))
        stage = RenovationStage(stage_id, order, before, child.snapshot(), tuple(identifiers), flows,
                                incompatible)
        child._stages = (*self.stages, stage)
        child._material_flows = (*self.material_flows, flows)
        child._parent_snapshot_id = before.sha256
        return child

    def resolve(self, weather):
        """Capture and resolve a read-only view with explicit weather context.

        Requires complete authoring inputs and delegates to the existing pipeline.
        Passing Weather or ClimateSpec performs no weather-file I/O; a path is
        inspected by the existing conversion API. No engine is initialized.
        """
        return self.snapshot().resolve(weather)

    def to_spec(self, weather):
        """Compile authoring state to the existing numerical Core input contract."""
        from .building_adapter import to_spec

        return to_spec(self, weather)
