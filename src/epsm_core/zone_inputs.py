# File: zone_inputs.py
# Purpose: Share existing zone operation and reference-area selection.
# SPDX-License-Identifier: MIT
# License: MIT; see the project-root LICENSE.
# Date created: 2026-10-14

"""Pure selection of existing Core operations, with exact-zone precedence.

This preserves the compiler's common-zone and residential-load conventions.
It performs no emission, schedule I/O or thermal calculation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .specs import AirflowSpec, BuildingSpec, UseSpec, ZoneUseSpec


@dataclass(frozen=True)
class ZoneOperationInput:
    """Selected zone inputs retained before solver-specific emission."""

    use: UseSpec
    airflow: AirflowSpec
    load_reference_area_m2: float
    load_reference_area_basis: str
    schedule_prefix: str
    assignments: tuple[ZoneUseSpec, ...]


def resolve_zone_operations(spec: BuildingSpec, zones: dict) -> tuple[UseSpec, dict[str, ZoneOperationInput], float]:
    """Select the existing common/base/zone overrides without mutating inputs."""
    g = spec.geometry
    common_use = spec.common_use or spec.use.updated(
        heating_setpoint=spec.use.heating_setpoint.constant(g.zoning.apartments.common_heating_setpoint_c),
        occupant_density_per_m2=0, equipment_gain_w_m2=0,
        lighting_gain_w_m2=0, dhw_kwh_m2_year=0,
    )
    for assignment in spec.zone_uses:
        matches = [name for name, data in zones.items() if data["conditioned"] and
                   (name == assignment.zone_name if assignment.zone_name is not None else
                    data.get("zone_kind", data.get("physical_zone_kind")) == assignment.zone_kind)]
        if not matches:
            raise ValueError(f"Zone-use selector matches no conditioned zone: {assignment}")
    for exchange in spec.unconditioned_exchange:
        if not any(not data["conditioned"] and data.get("physical_zone_kind") == exchange.zone_kind
                   for data in zones.values()):
            raise ValueError(f"Exchange selector matches no unconditioned {exchange.zone_kind}")
    has_common = any(data.get("zone_kind") in ("common", "stairwell") for data in zones.values())
    residential_area = sum(data["floor_area_m2"] for data in zones.values()
                           if data["conditioned"] and data.get("zone_kind") not in ("common", "stairwell"))
    load_scale = (g.conditioned_floor_area_m2 / residential_area
                  if has_common and g.zoning.apartments.conserve_residential_loads else 1)
    residential_use = spec.use.updated(**{
        name: getattr(spec.use, name) * load_scale for name in (
            "occupant_density_per_m2", "equipment_gain_w_m2", "lighting_gain_w_m2", "dhw_kwh_m2_year")})
    result = {}
    for zone, data in zones.items():
        if not data["conditioned"]:
            continue
        common = data.get("zone_kind") in ("common", "stairwell")
        use = common_use if common else residential_use
        airflow = (spec.common_airflow or spec.airflow) if common else spec.airflow
        prefix = "common_" if common else ""
        scale = spec.load_reference_area_m2 / g.conditioned_floor_area_m2 \
            if spec.load_reference_area_m2 is not None else 1
        area = data["floor_area_m2"] * scale
        basis = "explicit" if spec.load_reference_area_m2 is not None else "conditioned_floor_area_default"
        assignments = tuple(sorted(
            (assignment for assignment in spec.zone_uses if assignment.zone_name == zone or
             (assignment.zone_kind is not None and assignment.zone_kind ==
              data.get("zone_kind", data.get("physical_zone_kind")))),
            key=lambda assignment: assignment.zone_name is not None))
        for assignment in assignments:
            use = assignment.use or use
            airflow = assignment.airflow or airflow
            if assignment.reference_area_m2 is not None:
                area = assignment.reference_area_m2
                basis = "zone_override"
        if assignments:
            prefix = zone + "_operation_"
        result[zone] = ZoneOperationInput(use, airflow, area, basis, prefix, assignments)
    if spec.load_reference_area_m2 is not None and abs(
            sum(item.load_reference_area_m2 for item in result.values()) - spec.load_reference_area_m2) > 1e-6:
        raise ValueError("Zone reference areas must sum to the declared building load reference area")
    return common_use, result, load_scale
