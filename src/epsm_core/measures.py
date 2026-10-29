"""Apply epsm_data renovation candidates with quantities taken from building geometry.

Data defines what a candidate installs as a typed payload; this module resolves
each payload type with one registered resolver, which chooses physical targets
and derives quantity drivers. The result is a ``ResolvedMeasure`` handed to
:meth:`Building.renovate`, the single renovation path. No price or climate factor
is read here.

Examples
--------
>>> from epsm_data import Catalogue, RenovationCatalogue
>>> from epsm_core import Building
>>> from epsm_core.measures import apply_candidates
>>> library = Catalogue.load()
>>> renovations = RenovationCatalogue.load(library)
>>> building = Building(preset="illustrative-reference",
...     construction_set=library.get("mf_se03", state="existing").construction_set)
>>> wall = renovations.filter("insulate_wall")[0]
>>> renovated = apply_candidates(building, wall)
>>> renovated.stages[0].quantities[0].measure_type
'insulate_wall'
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from epsm_data.contract import BOVERKET_REF, CARBON_REFERENCE, CARBON_REFERENCE_ID
from epsm_data.contract import QuantityDriver as Q
from epsm_data.renovation import (
    Airtightness,
    DHWReduction,
    LayerAddition,
    PVArray,
    SystemSwap,
    WindowSwap,
)

from .building import Building, Installation, MeasureQuantities
from .renovation_apply import ResolvedMeasure
from .takeoff import building_dimensions, envelope_drivers, pv_drivers, ventilation_drivers

__all__ = ["RESOLVERS", "Resolution", "apply_candidates", "building_dimensions",
           "pv_drivers", "resolve_candidate", "resolve_sealing", "ventilation_drivers"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resolution:
    """What a payload resolver found: operations, targets and quantity drivers."""

    operations: tuple
    targets: tuple[str, ...]
    drivers: dict
    effects: dict | None = None


def _no_selectors(element_ids, candidate):
    if element_ids:
        raise ValueError(f"{candidate.candidate_id} does not target envelope elements")


def _envelope_targets(building, candidate, element_ids):
    """Targets of an envelope payload: selected elements, or its default boundaries."""
    payload = candidate.payload
    selected = set(element_ids or ())
    # By default only the thermal envelope is renovated: shared party walls and
    # internal floors keep their construction. A layer addition may name other
    # boundaries, such as the ceiling over an unheated basement.
    boundaries = set(getattr(payload, "target_boundaries", ()) or ("Outdoors", "Ground"))
    if ("Internal" in boundaries and candidate.role.value == "GROUND_FLOOR"
            and (building.geometry is None or not building.geometry.basement_depth_m
                 or building.geometry.basement_conditioned)):
        raise ValueError(f"{candidate.candidate_id} needs an unheated basement below the ground floor")
    elements = [e for e in building.elements if e.role == candidate.role
                and (e.identifier in selected if selected else e.boundary in boundaries)]
    if selected - {e.identifier for e in elements}:
        raise ValueError(f"Selected elements are not {candidate.role.value} elements")
    if not elements:
        raise ValueError(f"The building has no {candidate.role.value} elements")
    if any(e.construction is None for e in elements):
        raise ValueError("Every target needs an assigned construction")
    if len({_construction_key(e.construction) for e in elements}) != 1:
        raise ValueError("Targets have different constructions; renovate them as separate selections")
    return elements


def resolve_layers(building, candidate, element_ids, *, roof_topology=None, **_):
    payload = candidate.payload
    if (payload.roof_topologies and roof_topology is not None
            and roof_topology not in payload.roof_topologies):
        raise ValueError(f"{candidate.candidate_id} applies to {payload.roof_topologies} roofs")
    elements = _envelope_targets(building, candidate, element_ids)
    return Resolution(payload.operations_for(elements[0].construction),
                      tuple(e.identifier for e in elements), envelope_drivers(elements))


def resolve_window(building, candidate, element_ids, **_):
    elements = _envelope_targets(building, candidate, element_ids)
    return Resolution(candidate.payload.operations_for(elements[0].construction),
                      tuple(e.identifier for e in elements),
                      envelope_drivers(elements, candidate.payload.typical_window_area_m2))


def resolve_system(building, candidate, element_ids, **_):
    _no_selectors(element_ids, candidate)
    payload = candidate.payload
    if building.hvac is None:
        raise ValueError("Ventilation renovation requires an existing HVAC system")
    existing = building.hvac.airflow.topology
    if payload.from_ventilation and existing not in payload.from_ventilation:
        raise ValueError(f"{candidate.candidate_id} cannot replace {existing} ventilation")
    return Resolution((payload.operation(candidate.candidate_id, candidate.source_references),),
                      (), ventilation_drivers(building, payload.layout, existing))


def resolve_pv(building, candidate, element_ids, **_):
    _no_selectors(element_ids, candidate)
    drivers = pv_drivers(building, candidate.payload)
    return Resolution((candidate.payload.operation(drivers[Q.PV_CAPACITY_KWP]),), (), drivers)


def resolve_dhw(building, candidate, element_ids, **_):
    _no_selectors(element_ids, candidate)
    if building.effective_load_reference_area_m2 is None:
        raise ValueError("DHW measures need a load reference floor area")
    return Resolution((candidate.payload.operation(),), (), {})


def resolve_airtightness(building, candidate, element_ids, *, hosts=(), **_):
    """Scale the nominal reduction by the outdoor envelope share its hosts renovated."""
    _no_selectors(element_ids, candidate)
    if not hosts:
        raise ValueError(f"{candidate.candidate_id} cannot be applied by itself; apply one of "
                         f"{', '.join(candidate.kind.hosts)} in the same stage")
    areas = {e.identifier: e.area_m2 for e in building.elements if e.boundary == "Outdoors"}
    renovated = sum(areas.get(i, 0.0) for host in hosts for i in host.target_element_ids)
    envelope = sum(areas.values())
    if renovated <= 0 or envelope <= 0:
        raise ValueError(f"{candidate.candidate_id} needs host measures on the outdoor envelope")
    share = min(renovated / envelope, 1.0)
    operation = candidate.payload.operation(share)
    logger.warning(
        "Default airtightness assumption applied: %s reduces infiltration by %.1f %% "
        "(nominal %.0f %% x renovated envelope share %.2f)",
        candidate.candidate_id, 100 * operation.fraction,
        100 * candidate.payload.nominal_reduction, share,
        extra={"epsm_event": "renovation.sealing.default_applied",
               "epsm_context": {"building_id": building.identifier},
               "epsm_details": {"candidate_id": candidate.candidate_id,
                                "host_measure_ids": [h.measure_id for h in hosts],
                                "nominal_reduction": candidate.payload.nominal_reduction,
                                "envelope_share": share, "reduction": operation.fraction}})
    return Resolution((operation,), (), {}, {
        "renovated_envelope_area_m2": renovated, "envelope_share": share,
        "infiltration_reduction": operation.fraction})


RESOLVERS = {
    LayerAddition: resolve_layers,
    WindowSwap: resolve_window,
    SystemSwap: resolve_system,
    PVArray: resolve_pv,
    DHWReduction: resolve_dhw,
    Airtightness: resolve_airtightness,
}


def resolve_candidate(building, candidate, *, element_ids=None, measure_id=None,
                      roof_topology=None, hosts=()):
    """Resolve one candidate into a measure ``Building.renovate`` applies.

    Parameters
    ----------
    building : Building
        State before the measure; quantities come from its geometry and elements.
    candidate : epsm_data.RenovationCandidate
        A candidate loaded with :meth:`RenovationCatalogue.load`.
    element_ids : sequence of str, optional
        Physical elements to renovate; the payload's default targets otherwise.
    measure_id : str, optional
        Identity in the renovation stage; the candidate ID by default.
    roof_topology : str, optional
        Checked against layer additions restricted to a roof topology.
    hosts : sequence of ResolvedMeasure, optional
        Host measures in the same stage; only dependent candidates use them.
    """
    if not isinstance(building, Building):
        raise TypeError("building must be an epsm_core Building")
    if not candidate.kind.standalone and not hosts:
        raise ValueError(f"{candidate.candidate_id} cannot be applied by itself; apply one of "
                         f"{', '.join(candidate.kind.hosts)} with apply_candidates")
    resolver = RESOLVERS.get(type(candidate.payload))
    if resolver is None:
        raise TypeError(f"No resolver for {type(candidate.payload).__name__}")
    found = resolver(building, candidate, element_ids, roof_topology=roof_topology, hosts=hosts)
    drivers = {Q.BUILDING: 1.0, **found.drivers}
    if building.effective_load_reference_area_m2 is not None:
        drivers.setdefault(Q.FLOOR_AREA_M2, building.effective_load_reference_area_m2)
    measure_id = measure_id or candidate.candidate_id
    installations = []
    for product in candidate.products:
        amount = drivers.get(product.driver, 0.0) * product.quantity_per_driver
        if amount <= 0:
            continue
        refs = [(BOVERKET_REF, product.boverket_id)] if product.boverket_id else []
        reference = product.carbon_reference
        if reference is not None:
            # The full record travels with the occurrence, as for windows in inventory.
            refs += [(CARBON_REFERENCE_ID, reference.identifier),
                     (CARBON_REFERENCE, json.dumps(reference.to_dict(), sort_keys=True,
                                                   separators=(",", ":")))]
        installations.append(Installation(
            f"{measure_id}.{product.product_id}", product.product_id, product.description,
            product.unit, amount,
            amount * product.mass_kg_per_unit if product.mass_kg_per_unit is not None else None,
            tuple(refs), found.targets, candidate.candidate_id))
    return ResolvedMeasure(
        measure_id, found.operations, found.targets, tuple(installations),
        MeasureQuantities(measure_id, candidate.candidate_id, candidate.measure_type, drivers,
                          found.effects or {}),
        getattr(candidate.payload, "retains_existing", False),
        requires_measure_ids=tuple(h.measure_id for h in hosts))


def resolve_sealing(building, candidate, hosts):
    """Resolve a dependent candidate for the envelope its host measures renovate."""
    return resolve_candidate(building, candidate, hosts=tuple(hosts))


def apply_candidates(building, *selections, companions=True):
    """Apply candidates as one renovation stage and return the renovated child.

    Each selection is a candidate or ``(candidate, element_ids)``. Two selections
    must not renovate the same element. Dependent companions of the selected
    candidates, such as sealing after window replacement, are added after their
    hosts unless ``companions`` is False; a dependent candidate can also be
    selected explicitly but never without a host in the same stage.
    """
    measures, claimed, dependents, hosted = [], set(), {}, {}
    for selection in selections:
        candidate, element_ids = selection if isinstance(selection, tuple) else (selection, None)
        if not candidate.kind.standalone:
            if element_ids:
                raise ValueError(f"{candidate.candidate_id} does not accept element selectors")
            dependents[candidate.candidate_id] = candidate
            continue
        measure = resolve_candidate(building, candidate, element_ids=element_ids)
        kind = candidate.measure_type
        overlap = claimed.intersection(measure.target_element_ids)
        if overlap or (not measure.target_element_ids
                       and any(m.quantities.measure_type == kind for m in measures)):
            raise ValueError(f"{measure.measure_id} renovates elements already in this stage")
        claimed.update(measure.target_element_ids)
        measures.append(measure)
        for companion in candidate.companion_candidates if companions else ():
            dependents.setdefault(companion.candidate_id, companion)
            hosted.setdefault(companion.candidate_id, []).append(measure)
    for candidate_id, candidate in dependents.items():
        hosts = hosted.get(candidate_id) or [
            m for m in measures if m.quantities.measure_type in candidate.kind.hosts]
        measures.append(resolve_sealing(building, candidate, hosts))
    return building.renovate(*measures)


def _construction_key(construction):
    from epsm_data.catalogue.serialization import element_to_dict

    return repr(element_to_dict(construction))
