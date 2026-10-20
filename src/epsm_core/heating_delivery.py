# File: heating_delivery.py
# Purpose: Explicit space-heat carrier conversion downstream of thermal simulation.
# SPDX-License-Identifier: MIT
# Date created: 2026-10-03
"""Separate ideal space heat, net distribution losses and purchased carrier energy.

Reference: Sveby office 1.0 chapter 3 and school 1.0 chapter 3 distinguish
building operation from business energy. This is explicit engineering accounting,
not a calibrated system-efficiency standard. Constants/COP curves must be supplied
from building evidence. DHW, business electricity and cooling are not silently
added to the space-heat target. Net loss excludes heat already recovered into
the simulated zones; gross recoverable losses need a coupled physical model.
"""

from __future__ import annotations

import math

import numpy as np

from .specs import AirflowSpec


def heating_delivery(spec, heating_kwh, report):
    """Convert one-hour ideal heat to declared carrier input and fan electricity.

    Carrier input = (thermal demand + net losses) / efficiency / COP, where
    COP is applied only to an explicitly declared heat pump. Schedule-integrated
    net losses preserve the annual kWh/m2 on the load reference area. Fan input
    is SFP [W/(L/s)] times scheduled mechanical outdoor flow [L/s] over one hour.
    Fan electricity is reported separately and is not added to district heat.
    No fan-heat gain is fed back into Ideal Loads by this downstream calculation.
    """
    delivery = spec.delivery.heating
    if delivery is None:
        return {}
    area = report.data.get(
        "load_reference_area_m2",
        spec.load_reference_area_m2 or spec.geometry.conditioned_floor_area_m2,
    )
    def flows():
        for zone in report.data["zones"].values():
            if zone["conditioned"]:
                yield zone["load_reference_area_m2"], AirflowSpec.model_validate(zone["airflow_input"])

    return _heating_delivery(spec, heating_kwh, area, flows())


def heating_delivery_for_domain(spec, heating_kwh, *, reference_area_m2: float,
                                airflow: AirflowSpec) -> dict:
    """Convert one reduced domain's heating using its already validated airflow.

    Parameters
    ----------
    spec : BuildingSpec
        Validated annual calendar and declared heating delivery assumptions.
    heating_kwh : array-like
        Finite nonnegative hourly thermal demand in kWh for one complete year.
    reference_area_m2 : float
        Positive load reference area of this domain in square metres.
    airflow : AirflowSpec
        This domain's validated mechanical flow and schedule. No dictionary
        conversion or repeated model validation is performed.

    Returns
    -------
    dict
        Carrier input, net distribution losses and optional separate fan
        electricity, each an hourly kWh array. Empty if heating delivery is absent.

    Notes
    -----
    Uses the same accounting as ``heating_delivery`` and performs no I/O or
    mutation. Domain areas partition the building reference area; callers own
    domain selection. Fan heat does not feed back into the thermal calculation.
    """
    if not isinstance(airflow, AirflowSpec):
        raise TypeError("airflow must be an already validated AirflowSpec")
    if not math.isfinite(reference_area_m2) or reference_area_m2 <= 0:
        raise ValueError("reference_area_m2 must be finite and positive")
    if spec.delivery.heating is None:
        return {}
    return _heating_delivery(spec, heating_kwh, reference_area_m2,
                             ((reference_area_m2, airflow),))


def _heating_delivery(spec, heating_kwh, area, flows):
    """Shared annual accounting for an explicit area and selected mechanical flows."""
    delivery = spec.delivery.heating
    demand = np.asarray(heating_kwh, dtype=float)
    if (
        demand.shape != (spec.climate.hours_in_year,)
        or not np.isfinite(demand).all()
        or (demand < 0).any()
    ):
        raise ValueError("Heating delivery requires a finite nonnegative full hourly year")
    weights = np.asarray(delivery.loss_fraction.hourly(spec.climate.calendar_year))
    weight_sum = weights.sum()
    total_loss = delivery.net_distribution_loss_kwh_m2_year * area
    if total_loss and weight_sum == 0:
        raise ValueError("Nonzero net distribution loss requires an active loss schedule")
    losses = total_loss * weights / weight_sum if weight_sum else weights
    cop = (
        np.asarray(delivery.heat_pump_cop.hourly(spec.climate.calendar_year))
        if delivery.heat_pump_cop is not None
        else 1
    )
    output = {
        "space_heating_carrier_input_kwh": (demand + losses) / delivery.efficiency / cop,
        "net_distribution_loss_kwh": losses,
    }
    if delivery.specific_fan_power_w_per_l_s is not None:
        fan = np.zeros_like(demand)
        for reference_area, airflow in flows:
            flow_l_s = reference_area * airflow.mechanical_vent_l_s_m2
            fan += flow_l_s * np.asarray(
                airflow.mechanical_vent_fraction.hourly(spec.climate.calendar_year)
            )
        output["ventilation_fan_electricity_kwh"] = (
            fan * delivery.specific_fan_power_w_per_l_s / 1000
        )
    return output
