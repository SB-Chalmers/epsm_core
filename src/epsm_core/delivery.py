# File: delivery.py
# Purpose: Hourly exhaust-air heat-pump accounting downstream of EnergyPlus demand.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-03
# Changelog:
#   2026-10-03 - Add documented calendar, operational and archetype-application support.
#   2026-09-06 - Document delivery interfaces, examples, constraints and processing rationale.

"""Hourly exhaust-air heat-pump accounting downstream of EnergyPlus demand.

Notes
-----
EnergyPlus ideal heating and DHW demands are converted downstream into exhaust-air heat-
pump and backup inputs. Arrays represent one-hour intervals. Available source heat is
sensible-only, with constant COP and explicitly chosen load priority.

Examples
--------
Supply a validated BuildingSpec as ``building``.

Example::

    from epsm_core.delivery import fvp_delivery

    delivery = fvp_delivery(building, [2.0], [1.0], [21.0])
"""

import numpy as np


def fvp_delivery(spec, heating_kwh, dhw_kwh, exhaust_temperature_c):
    """Allocate hourly exhaust-air heat-pump output between heating and hot water.

    Parameters
    ----------
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    heating_kwh : array_like
        Nonnegative demand per one-hour interval in kWh; inputs must broadcast together.
    dhw_kwh : array_like
        Nonnegative demand per one-hour interval in kWh; inputs must broadcast together.
    exhaust_temperature_c : array_like
        Hourly exhaust-air temperature in degrees Celsius, broadcast with demand.

    Returns
    -------
    dict
        Broadcast arrays for FVP heat, electricity, backup input and extracted heat, in kWh.

    Notes
    -----
    Returns an empty mapping when FVP is absent. Assumes one-hour intervals, nonnegative
    demands and constant COP; only sensible exhaust heat is recovered. No timestep-duration
    conversion or input clipping is supplied.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``.

    Example::

        from epsm_core.delivery import fvp_delivery

        delivery = fvp_delivery(building, [2.0], [1.0], [21.0])
    """

    # 1. Allocate hourly exhaust-air heat-pump output between heating and hot water.
    fvp = spec.delivery.fvp
    if fvp is None:
        return {}
    heating, dhw, temp = np.broadcast_arrays(heating_kwh, dhw_kwh, exhaust_temperature_c)
    reference_area = spec.load_reference_area_m2 or spec.geometry.conditioned_floor_area_m2
    flow_m3_s = spec.airflow.mechanical_vent_l_s_m2 * reference_area / 1000
    # Sensible-only evaporator availability. Latent recovery is deliberately not invented.
    source_kw = 1.2 * 1006 * flow_m3_s * np.maximum(temp - fvp.exhaust_min_temperature_c, 0) / 1000
    available = np.minimum(fvp.capacity_kw, source_kw / (1 - 1 / fvp.cop))
    first, second = (dhw, heating) if fvp.dhw_priority else (heating, dhw)
    supplied_first = np.minimum(first, available)
    supplied_second = np.minimum(second, np.maximum(available - supplied_first, 0))
    produced = supplied_first + supplied_second
    return {
        "fvp_heat_kwh": produced,
        "fvp_electricity_kwh": produced / fvp.cop,
        "backup_input_kwh": (heating + dhw - produced) / fvp.backup_efficiency,
        "fvp_extracted_heat_kwh": produced * (1 - 1 / fvp.cop),
    }
