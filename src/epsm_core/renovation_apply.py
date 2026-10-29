"""How each epsm_data operation changes a Building during ``Building.renovate``.

``ResolvedMeasure`` is the one input shape ``renovate`` works with; catalogue
candidates, executable Data measures and bare operations are normalised into it.
Each operation type has one applier, registered in ``APPLIERS``. An applier
changes the child building in place and returns the physical elements it changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from epsm_data.domain import ConstructionSet
from epsm_data.renovation import (
    AirtightnessOperation,
    ConstructionOperation,
    DHWOperation,
    PVOperation,
    SystemOperation,
)


@dataclass(frozen=True)
class ResolvedMeasure:
    """A measure ready to apply: operations, targets, installed products and quantities.

    ``retains_existing`` keeps a replaced element's installed occurrence (a window
    upgrade). ``quantities`` carries the geometric drivers costing needs.
    """

    measure_id: str
    operations: tuple
    target_element_ids: tuple[str, ...] = ()
    installations: tuple = ()
    quantities: object | None = None
    retains_existing: bool = False
    requires_measure_ids: tuple[str, ...] = ()
    incompatible_measure_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.measure_id:
            raise ValueError("Resolved measures need an identity")
        if not self.operations:
            raise ValueError("Renovation measure has no resolved physical operations")
        unknown = [op for op in self.operations if type(op) not in APPLIERS]
        if unknown:
            raise TypeError(f"No applier for {type(unknown[0]).__name__}")

    @classmethod
    def of(cls, measure):
        """Normalise a resolved measure, a Data ``RenovationMeasure`` or a bare operation."""
        if isinstance(measure, cls):
            return measure
        if type(measure) in APPLIERS:
            return cls(measure.action, (measure,))
        from epsm_data import RenovationMeasure

        if isinstance(measure, RenovationMeasure):
            return cls(measure.measure_id, measure.operations, measure.target_element_ids,
                       requires_measure_ids=measure.requires_measure_ids,
                       incompatible_measure_ids=measure.incompatible_measure_ids)
        raise TypeError(f"Cannot renovate with {type(measure).__name__}")


def _no_selectors(selected, what):
    if selected:
        raise ValueError(f"{what} does not accept element selectors")


def apply_construction(child, operation, measure, selected):
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
            if not measure.retains_existing:
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
    child._elements = tuple(changed.get(e.identifier, e) for e in child.elements)
    return set(changed)


def apply_system(child, operation, measure, selected):
    from .building import HVACSystem

    _no_selectors(selected, "HVAC replacement")
    child.hvac = HVACSystem.from_template(operation.template, previous=child.hvac)
    return set()


def apply_airtightness(child, operation, measure, selected):
    _no_selectors(selected, "Infiltration reduction")
    if child.hvac is None:
        raise ValueError("Infiltration reduction requires an airflow specification")
    airflow = child.hvac.airflow
    remaining = 1 - operation.fraction
    child.hvac = child.hvac.with_changes(airflow=airflow.model_copy(update={
        "envelope_infiltration_ach": airflow.envelope_infiltration_ach * remaining,
        "envelope_infiltration_l_s_m2": None if airflow.envelope_infiltration_l_s_m2 is None
        else airflow.envelope_infiltration_l_s_m2 * remaining}))
    return set()


def apply_pv(child, operation, measure, selected):
    from .specs.physics import PVSpec

    _no_selectors(selected, "PV installation")
    if child.hvac is None:
        raise ValueError("PV installation needs an HVAC system to hold renewables")
    pv = PVSpec(dc_capacity_kw=operation.dc_capacity_kw, tilt_deg=operation.tilt_deg,
                azimuth_deg=operation.azimuth_deg, system_losses_pct=operation.system_losses_pct)
    renewables = child.hvac.renewables
    child.hvac = child.hvac.with_changes(renewables=renewables.model_copy(
        update={"pv_systems": (*renewables.pv_systems, pv)}))
    return set()


def apply_dhw(child, operation, measure, selected):
    _no_selectors(selected, "DHW reduction")
    if child.operation is None:
        raise ValueError("DHW reduction needs an operation profile")
    remaining = 1 - operation.fraction
    child.operation = child.operation.with_changes(
        dhw_kwh_m2_year=child.operation.dhw_kwh_m2_year * remaining)
    # Zone-specific use overrides carry their own hot-water demand.
    child.zone_uses = tuple(
        zone.updated(use=zone.use.updated(dhw_kwh_m2_year=zone.use.dhw_kwh_m2_year * remaining))
        if zone.use is not None else zone for zone in child.zone_uses)
    return set()


APPLIERS = {
    ConstructionOperation: apply_construction,
    SystemOperation: apply_system,
    AirtightnessOperation: apply_airtightness,
    PVOperation: apply_pv,
    DHWOperation: apply_dhw,
}
