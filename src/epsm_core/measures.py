"""Apply epsm_data renovation candidates with quantities taken from building geometry.

Data defines what a candidate installs; this module chooses the physical targets,
derives every cost and product quantity driver from the building, and hands a
resolved measure to :meth:`Building.renovate`, the single renovation path. No
price or climate factor is read here.

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

import logging
import math
from dataclasses import dataclass

from epsm_data.operations import DHWOperation, PVOperation, SystemOperation

from .building import Building, Installation, MeasureQuantities

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogueMeasure:
    """A renovation candidate resolved for one building; accepted by ``Building.renovate``."""

    measure_id: str
    candidate_id: str
    measure_type: str
    operations: tuple
    target_element_ids: tuple[str, ...]
    installations: tuple[Installation, ...]
    quantities: MeasureQuantities
    retains_existing: bool = False
    requires_measure_ids: tuple[str, ...] = ()
    incompatible_measure_ids: tuple[str, ...] = ()


def _polygon_area(points):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                   in zip(points, (*points[1:], points[0])))) / 2


def building_dimensions(building):
    """Return footprint area, storeys and height of each conditioned geometry part.

    A conditioned basement is served like a storey: it adds one storey of mains
    and extends the risers by the basement depth.
    """
    if building.geometry is None:
        raise ValueError("Ventilation quantities require building geometry")
    geometry = building.geometry
    basement = geometry.basement_depth_m if geometry.basement_conditioned else 0.0
    basement = basement or 0.0
    parts = []
    for part in building.geometry.parts:
        if not part.conditioned:
            continue
        footprint = part.footprint
        area = _polygon_area(footprint.exterior) - sum(_polygon_area(h) for h in footprint.holes)
        elevations = part.storey_elevations_m
        parts.append({"part_id": part.identifier, "footprint_m2": area,
                      "storeys": len(elevations) - 1 + (1 if basement else 0),
                      "height_m": elevations[-1] - elevations[0] + basement})
    if not parts:
        raise ValueError("Ventilation quantities require a conditioned geometry part")
    return parts


def ventilation_drivers(building, layout, existing):
    """Derive airflow, terminal, riser, unit and duct quantities from geometry.

    Risers serve ``riser_area_m2`` of footprint each and run the full part height;
    each new duct network adds risers plus horizontal mains per storey, and each
    new terminal adds one branch. Existing networks are retained, not replaced.
    """
    parts = building_dimensions(building)
    floor_area = building.effective_load_reference_area_m2 or sum(
        p["footprint_m2"] * p["storeys"] for p in parts)
    airflow = layout.mechanical_vent_l_s_m2 * floor_area
    systems = layout.new_duct_systems[existing]
    terminals = layout.new_terminals[existing]
    supply = math.ceil(floor_area / layout.supply_area_per_terminal_m2) if "supply" in terminals else 0
    exhaust = math.ceil(floor_area / layout.exhaust_area_per_terminal_m2) if "exhaust" in terminals else 0
    risers = sum(max(1, math.ceil(p["footprint_m2"] / layout.riser_area_m2)) for p in parts)
    network = sum(max(1, math.ceil(p["footprint_m2"] / layout.riser_area_m2)) * p["height_m"]
                  + p["storeys"] * p["footprint_m2"] * layout.main_duct_m_per_m2 for p in parts)
    return {"floor_area_m2": floor_area, "airflow_l_s": airflow,
            "ahu_count": float(math.ceil(airflow / layout.ahu_max_airflow_l_s)),
            "riser_count": float(risers * systems),
            "supply_terminal_count": float(supply), "exhaust_terminal_count": float(exhaust),
            "duct_length_m": systems * network + (supply + exhaust) * layout.branch_length_m}


def pv_drivers(building, layout):
    """Size a roof array: a share of the footprint on flat roofs, of the roof surface otherwise.

    Pitched parts use their actual outdoor ``ROOF`` element area; parts without
    such elements fall back to the footprint.
    """
    if building.geometry is None:
        raise ValueError("PV sizing requires building geometry")
    roofs = {}
    for element in building.elements:
        if element.role.value == "ROOF" and element.boundary == "Outdoors":
            roofs[element.part_id] = roofs.get(element.part_id, 0.0) + element.area_m2
    area = 0.0
    for part in building.geometry.parts:
        roof = part.roof or building.geometry.roof
        footprint = (_polygon_area(part.footprint.exterior)
                     - sum(_polygon_area(h) for h in part.footprint.holes))
        if roof is None or roof.shape == "flat":
            area += layout.flat_roof_share * footprint
        else:
            area += layout.pitched_roof_share * roofs.get(part.identifier, footprint)
    return {"pv_area_m2": area, "pv_capacity_kwp": area * layout.module_w_m2 / 1000}


def resolve_candidate(building, candidate, *, element_ids=None, measure_id=None,
                      roof_topology=None):
    """Resolve one candidate's operations, quantity drivers and installed products.

    Parameters
    ----------
    building : Building
        State before the measure; quantities come from its geometry and elements.
    candidate : epsm_data.RenovationCandidate
        A candidate loaded with :meth:`RenovationCatalogue.load`.
    element_ids : sequence of str, optional
        Physical elements to renovate; every element of the candidate's role by default.
    measure_id : str, optional
        Identity in the renovation stage; the candidate ID by default.
    roof_topology : str, optional
        Checked against roof candidates that are restricted to a topology.
    """
    if not isinstance(building, Building):
        raise TypeError("building must be an epsm_core Building")
    if not candidate.kind.standalone:
        raise ValueError(f"{candidate.candidate_id} cannot be applied by itself; apply one of "
                         f"{', '.join(candidate.kind.hosts)} with apply_candidates")
    drivers = {"building": 1.0}
    if building.effective_load_reference_area_m2 is not None:
        drivers["floor_area_m2"] = building.effective_load_reference_area_m2
    if candidate.kind.action == "replace_hvac":
        if element_ids:
            raise ValueError("Ventilation candidates do not target envelope elements")
        if building.hvac is None:
            raise ValueError("Ventilation renovation requires an existing HVAC system")
        existing = building.hvac.airflow.topology
        if candidate.from_ventilation and existing not in candidate.from_ventilation:
            raise ValueError(f"{candidate.candidate_id} cannot replace {existing} ventilation")
        drivers |= ventilation_drivers(building, candidate.layout, existing)
        operations = (SystemOperation("replace_hvac", candidate.system_template()),)
        targets = ()
    elif candidate.kind.action == "add_pv":
        if element_ids:
            raise ValueError("PV candidates are sized from the roof, not element selectors")
        drivers |= pv_drivers(building, candidate.pv)
        layout = candidate.pv
        operations = (PVOperation("add_pv", drivers["pv_capacity_kwp"], layout.tilt_deg,
                                  layout.azimuth_deg, layout.system_losses_pct),)
        targets = ()
    elif candidate.kind.action == "reduce_dhw":
        if element_ids:
            raise ValueError("DHW candidates do not target envelope elements")
        if "floor_area_m2" not in drivers:
            raise ValueError("DHW measures need a load reference floor area")
        operations = (DHWOperation("reduce_dhw", candidate.dhw_reduction),)
        targets = ()
    else:
        if (candidate.roof_topologies and roof_topology is not None
                and roof_topology not in candidate.roof_topologies):
            raise ValueError(f"{candidate.candidate_id} applies to {candidate.roof_topologies} roofs")
        selected = set(element_ids or ())
        # By default only the thermal envelope is renovated: shared party walls and
        # internal floors of the same role keep their construction. A candidate may
        # name other boundaries, such as the ceiling over an unheated basement.
        boundaries = set(candidate.target_boundaries or ("Outdoors", "Ground"))
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
        constructions = {_construction_key(e.construction) for e in elements}
        if len(constructions) != 1:
            raise ValueError("Targets have different constructions; renovate them as separate selections")
        operations = candidate.operations_for(elements[0].construction)
        targets = tuple(e.identifier for e in elements)
        area = sum(e.area_m2 for e in elements)
        if candidate.role.value == "WINDOW":
            drivers |= {"window_area_m2": area,
                        "window_count": area / candidate.typical_window_area_m2}
        else:
            drivers["element_area_m2"] = area
    measure_id = measure_id or candidate.candidate_id
    installations = []
    for product in candidate.products:
        amount = drivers.get(product.driver, 0.0) * product.quantity_per_driver
        if amount <= 0:
            continue
        refs = [("boverket_id", product.boverket_id)] if product.boverket_id else []
        # Direct per-unit factors (for example from an EPD) travel with the occurrence.
        refs += [(f"factor:{module}", repr(value)) for module, value in product.factors.items()]
        if product.factors:
            refs.append(("factor_source", product.factor_source))
        installations.append(Installation(
            f"{measure_id}.{product.product_id}", product.product_id, product.description,
            product.unit, amount,
            amount * product.mass_kg_per_unit if product.mass_kg_per_unit is not None else None,
            tuple(refs), targets, candidate.candidate_id))
    return CatalogueMeasure(
        measure_id, candidate.candidate_id, candidate.measure_type, operations, targets,
        tuple(installations),
        MeasureQuantities(measure_id, candidate.candidate_id, candidate.measure_type, drivers),
        candidate.retains_existing)


def resolve_sealing(building, candidate, hosts):
    """Resolve a dependent sealing candidate for the envelope its host measures renovate.

    The nominal reduction is scaled by the renovated share of the outdoor envelope
    area. Applying the catalogue default is logged, since it is an assumption.
    """
    if not hosts:
        raise ValueError(f"{candidate.candidate_id} cannot be applied by itself; apply one of "
                         f"{', '.join(candidate.kind.hosts)} in the same stage")
    areas = {e.identifier: e.area_m2 for e in building.elements if e.boundary == "Outdoors"}
    renovated = sum(areas.get(i, 0.0) for host in hosts for i in host.target_element_ids)
    envelope = sum(areas.values())
    if renovated <= 0 or envelope <= 0:
        raise ValueError(f"{candidate.candidate_id} needs host measures on the outdoor envelope")
    share = min(renovated / envelope, 1.0)
    operation = candidate.airtightness_operation(share)
    logger.warning(
        "Default airtightness assumption applied: %s reduces infiltration by %.1f %% "
        "(nominal %.0f %% x renovated envelope share %.2f)",
        candidate.candidate_id, 100 * operation.fraction,
        100 * candidate.infiltration_reduction, share,
        extra={"epsm_event": "renovation.sealing.default_applied",
               "epsm_context": {"building_id": building.identifier},
               "epsm_details": {"candidate_id": candidate.candidate_id,
                                "host_measure_ids": [h.measure_id for h in hosts],
                                "nominal_reduction": candidate.infiltration_reduction,
                                "envelope_share": share, "reduction": operation.fraction}})
    drivers = {"building": 1.0, "renovated_envelope_area_m2": renovated,
               "envelope_share": share, "infiltration_reduction": operation.fraction}
    return CatalogueMeasure(
        candidate.candidate_id, candidate.candidate_id, candidate.measure_type, (operation,),
        (), (), MeasureQuantities(candidate.candidate_id, candidate.candidate_id,
                                  candidate.measure_type, drivers),
        requires_measure_ids=tuple(h.measure_id for h in hosts))


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
        overlap = claimed.intersection(measure.target_element_ids)
        if overlap or (not measure.target_element_ids
                       and any(m.measure_type == measure.measure_type for m in measures)):
            raise ValueError(f"{measure.measure_id} renovates elements already in this stage")
        claimed.update(measure.target_element_ids)
        measures.append(measure)
        for companion in candidate.companion_candidates if companions else ():
            dependents.setdefault(companion.candidate_id, companion)
            hosted.setdefault(companion.candidate_id, []).append(measure)
    for candidate_id, candidate in dependents.items():
        hosts = hosted.get(candidate_id) or [
            m for m in measures if m.measure_type in candidate.kind.hosts]
        measures.append(resolve_sealing(building, candidate, hosts))
    return building.renovate(*measures)


def _construction_key(construction):
    from epsm_data.serialization import element_to_dict

    return repr(element_to_dict(construction))
