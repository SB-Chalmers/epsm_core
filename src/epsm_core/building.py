"""Gradual physical building authoring with shared EPSM Data constructions.

``Building()`` chooses the inspectable ``illustrative-reference`` preset.
``Building.empty()`` and ``Building.from_footprint()`` do not fill missing physics.
Catalogue objects are copied on assignment; runtime results are never snapshotted.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from epsm_data.domain import ConstructionSet, Element, WindowElement
from epsm_data.domain.enums import BuildingElement as ElementRole
from epsm_data.serialization import construction_set_from_dict, construction_set_to_dict

from .inventory import MaterialFlows, material_inventory
from .specs import (
    AirflowSpec,
    ContextSpec,
    DeliverySpec,
    FacadeSpec,
    Footprint,
    GeometrySpec,
    GlazingSpec,
    RenewablesSpec,
    UseSpec,
)


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


@dataclass(frozen=True)
class BuildingSnapshot:
    """Deep immutable resolved physical state, stored as canonical JSON."""

    _json: str

    @classmethod
    def from_dict(cls, data):
        if data.get("schema") != "epsm.building/1":
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

    def quantities(self):
        return self.to_building().quantities()


@dataclass(frozen=True)
class RenovationStage:
    stage_id: str
    order: int
    before: BuildingSnapshot
    after: BuildingSnapshot
    measure_ids: tuple[str, ...]
    material_flows: MaterialFlows
    incompatible_measure_ids: tuple[str, ...] = ()


class Building:
    """Editable physical building, with complete validation at method boundaries.

    The no-argument reference is illustrative, not calibrated Swedish evidence.
    Geometry/construction/HVAC/operation assignments are validated independently.
    ``readiness()`` describes what remains before a thermal simulation.
    """

    def __init__(self, *, preset="illustrative-reference", identifier="building",
                 geometry=None, construction_set=None, facade=None, hvac=None,
                 operation=None, context=None):
        self._elements = ()
        self._stages = ()
        self._material_flows = ()
        self._parent_snapshot_id = None
        self.preset = preset
        self.identifier = identifier
        if preset is not None:
            if preset != "illustrative-reference":
                raise ValueError(f"Unknown Building preset {preset!r}")
            from epsm_data import reference_construction_set, reference_hvac_template

            from .standards import load_sveby_spec

            geometry = geometry or GeometrySpec.from_footprint(
                Footprint.rectangle(20, 12), storeys=3, storey_height_m=2.8)
            construction_set = construction_set or reference_construction_set()
            hvac = hvac or HVACSystem.from_template(reference_hvac_template())
            operation = operation or OperationProfile.model_validate(
                load_sveby_spec().use_spec().model_dump())
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
        self.context = context or ContextSpec()

    def __setattr__(self, name, value):
        kinds = {"geometry": GeometrySpec, "facade": FacadeSpec,
                 "operation": UseSpec, "context": ContextSpec}
        if name in kinds and value is not None:
            kind = kinds[name]
            value = kind.model_validate(value.model_dump() if isinstance(value, kind) else value)
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
        object.__setattr__(self, name, value)
        if name in {"geometry", "construction_set", "facade"}:
            self._rebuild_elements(reassign=name == "construction_set")

    @property
    def id(self):
        return self.identifier

    def __repr__(self):
        return (f"{type(self).__name__}(identifier={self.identifier!r}, "
                f"parts={len(self.geometry.parts) if self.geometry else 0}, "
                f"elements={len(self.elements)}, stages={len(self.stages)}, "
                f"preset={self.preset!r})")

    @classmethod
    def empty(cls, **kwargs):
        return cls(preset=None, **kwargs)

    @classmethod
    def from_footprint(cls, footprint, *, storeys=None, storey_height_m=None,
                       storey_elevations_m=None, identifier="building", construction_set=None,
                       facade=None, hvac=None, operation=None, context=None, **geometry_options):
        geometry = GeometrySpec.from_footprint(
            footprint, storeys=storeys, storey_height_m=storey_height_m,
            storey_elevations_m=storey_elevations_m, **geometry_options)
        return cls.empty(identifier=identifier, geometry=geometry,
                         construction_set=construction_set, facade=facade, hvac=hvac,
                         operation=operation, context=context)

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
        return Readiness(tuple(missing), tuple(unsupported))

    def quantities(self):
        self.readiness("quantities").require()
        return material_inventory(self.elements, self.hvac.equipment if self.hvac else ())

    def snapshot(self):
        return BuildingSnapshot.from_dict({
            "schema": "epsm.building/1", "identifier": self.identifier, "preset": self.preset,
            "geometry": self.geometry.model_dump(mode="json") if self.geometry else None,
            "construction_set": construction_set_to_dict(self.construction_set)
            if self.construction_set else None,
            "facade": self.facade.model_dump(mode="json") if self.facade else None,
            "hvac": self.hvac.to_dict() if self.hvac else None,
            "operation": self.operation.model_dump(mode="json") if self.operation else None,
            "context": self.context.model_dump(mode="json"),
            "elements": [e.to_dict() for e in self.elements],
        })

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
        result.context = data.get("context", {})
        result.elements = [BuildingElement.from_dict(e) for e in data["elements"]]
        result.preset = data.get("preset")
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

    def lineage_to_dict(self):
        """Detached ordered history, separate from the physical snapshot."""
        return {"parent_snapshot_id": self.parent_snapshot_id, "stages": [
            {"stage_id": stage.stage_id, "order": stage.order,
             "before": stage.before.to_dict(), "after": stage.after.to_dict(),
             "measure_ids": list(stage.measure_ids),
             "incompatible_measure_ids": list(stage.incompatible_measure_ids)}
            for stage in self.stages]}

    def restore_lineage(self, data):
        """Restore validated transitions, deriving flows from saved occurrence identities."""
        from .inventory import MaterialInventory

        stages = []
        for order, item in enumerate(data.get("stages", ()), 1):
            if item["order"] != order or not item["stage_id"]:
                raise ValueError("Lineage stages require contiguous order and nonempty identities")
            before = BuildingSnapshot.from_dict(item["before"])
            after = BuildingSnapshot.from_dict(item["after"])
            if stages and stages[-1].after.sha256 != before.sha256:
                raise ValueError("Lineage snapshots do not form an ordered chain")
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
        self._stages = tuple(stages)
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

    def to_spec(self, weather):
        """Compile authoring state to the existing numerical Core input contract."""
        from .building_adapter import to_spec

        return to_spec(self, weather)
