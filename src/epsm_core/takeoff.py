"""Geometric quantity drivers for renovation measures, derived from a Building.

Ventilation sizing (airflow, units, risers, terminals, ducts), PV array sizing
from roof area, and envelope target areas. Values are keyed by
``epsm_data.contract.QuantityDriver``; no price or factor is read here.
"""

from __future__ import annotations

import math

from epsm_data.contract import QuantityDriver as Q


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
    return {Q.FLOOR_AREA_M2: floor_area, Q.AIRFLOW_L_S: airflow,
            Q.AHU_COUNT: float(math.ceil(airflow / layout.ahu_max_airflow_l_s)),
            Q.RISER_COUNT: float(risers * systems),
            Q.SUPPLY_TERMINAL_COUNT: float(supply), Q.EXHAUST_TERMINAL_COUNT: float(exhaust),
            Q.DUCT_LENGTH_M: systems * network + (supply + exhaust) * layout.branch_length_m}


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
    return {Q.PV_AREA_M2: area, Q.PV_CAPACITY_KWP: area * layout.module_w_m2 / 1000}


def envelope_drivers(elements, typical_window_area_m2=None):
    """Area drivers of targeted envelope elements; windows also get a unit count."""
    area = sum(e.area_m2 for e in elements)
    if typical_window_area_m2 is not None:
        return {Q.WINDOW_AREA_M2: area, Q.WINDOW_COUNT: area / typical_window_area_m2}
    return {Q.ELEMENT_AREA_M2: area}
