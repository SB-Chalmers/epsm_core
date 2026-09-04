"""Optional NREL PySAM PVWatts V8 generation using the building's EPW."""

import numpy as np


def run_pvwatts(pv, climate):
    from .weather import file_sha256

    if file_sha256(climate.epw_path) != climate.weather_sha256:
        raise ValueError("EPW checksum mismatch")
    try:
        import PySAM.Pvwattsv8 as pvwatts
    except ImportError as error:
        raise ImportError("Install epsm_core[pv] to evaluate PVWatts V8") from error
    model = pvwatts.default("PVWattsNone")
    model.SolarResource.solar_resource_file = climate.epw_path
    d = model.SystemDesign
    for key, value in dict(
        system_capacity=pv.dc_capacity_kw,
        tilt=pv.tilt_deg,
        azimuth=pv.azimuth_deg,
        dc_ac_ratio=pv.dc_ac_ratio,
        inv_eff=pv.inverter_efficiency_pct,
        losses=pv.system_losses_pct,
        array_type=pv.array_type,
        module_type=pv.module_type,
        gcr=pv.ground_coverage_ratio,
    ).items():
        setattr(d, key, value)
    model.execute(0)
    # PySAM's ac is average power in watts; a 1-hour timestep gives Wh, converted to kWh.
    hourly = np.asarray(model.Outputs.ac, dtype=float) / 1000
    if len(hourly) != 8760 or not np.isfinite(hourly).all() or (hourly < 0).any():
        raise ValueError("PVWatts output failed hourly validation")
    annual = float(model.Outputs.annual_energy)
    if not np.isclose(hourly.sum(), annual, rtol=0.001):
        raise ValueError("PVWatts annual/hourly energy mismatch")
    return dict(
        pv_generation_kwh=annual,
        pv_hourly_kwh=hourly,
        capacity_factor=float(model.Outputs.capacity_factor) / 100,
    )
