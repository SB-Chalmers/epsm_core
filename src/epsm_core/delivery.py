"""Hourly exhaust-air heat-pump accounting downstream of EnergyPlus demand."""

import numpy as np


def fvp_delivery(spec, heating_kwh, dhw_kwh, exhaust_temperature_c):
    fvp = spec.delivery.fvp
    if fvp is None:
        return {}
    heating, dhw, temp = np.broadcast_arrays(heating_kwh, dhw_kwh, exhaust_temperature_c)
    flow_m3_s = spec.airflow.mechanical_vent_l_s_m2 * spec.geometry.conditioned_floor_area_m2 / 1000
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
