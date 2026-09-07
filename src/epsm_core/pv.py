# File: pv.py
# Purpose: Optional NREL PySAM PVWatts V8 generation using the building's EPW.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document pv interfaces, examples, constraints and processing rationale.

"""Optional NREL PySAM PVWatts V8 generation using the building's EPW.

Notes
-----
The optional PySAM backend evaluates PVWatts V8 against an explicitly supplied EPW.
Weather identity and hourly/annual consistency are checked before returning generation.
Installing or importing the core does not require or run PySAM.

Examples
--------
Supply a PVSpec as ``pv``; a ClimateSpec as ``climate`` pointing to a real checksum-
matched EPW. Install epsm_core[pv] and supply a complete hourly EPW.

Example::

    from epsm_core.pv import run_pvwatts

    generation = run_pvwatts(pv, climate)
    assert len(generation["pv_hourly_kwh"]) == climate.hours_in_year
"""

import numpy as np


def run_pvwatts(pv, climate):
    """Evaluate a PV system against its checksum-verified EPW using PVWatts V8.

    Parameters
    ----------
    pv : PVSpec
        PVWatts system design with DC capacity, orientation and losses.
    climate : ClimateSpec
        Weather-file checksum, site metadata and simulation calendar.

    Returns
    -------
    dict
        Annual kWh, hourly kWh array and dimensionless capacity factor.

    Raises
    ------
    ValueError
        Rejected conditions: EPW checksum mismatch; PVWatts output failed hourly validation;
        PVWatts annual/hourly energy mismatch.
    ImportError
        Rejected conditions: Install epsm_core[pv] to evaluate PVWatts V8.

    Notes
    -----
    Requires epsm_core[pv] and a readable EPW. PySAM runs in-process; hourly AC watts become
    kWh for one-hour intervals. Nonfinite, negative or calendar-mismatched output and annual
    disagreement are rejected.

    Examples
    --------
    Supply a PVSpec as ``pv``; a ClimateSpec as ``climate`` pointing to a real checksum-
    matched EPW. Install epsm_core[pv] and supply a complete hourly EPW.

    Example::

        from epsm_core.pv import run_pvwatts

        generation = run_pvwatts(pv, climate)
        assert len(generation["pv_hourly_kwh"]) == climate.hours_in_year
    """

    # 1. Evaluate a PV system against its checksum-verified EPW using PVWatts V8.
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
    if len(hourly) != climate.hours_in_year or not np.isfinite(hourly).all() or (hourly < 0).any():
        raise ValueError("PVWatts output failed hourly validation")
    annual = float(model.Outputs.annual_energy)
    if not np.isclose(hourly.sum(), annual, rtol=0.001):
        raise ValueError("PVWatts annual/hourly energy mismatch")
    return dict(
        pv_generation_kwh=annual,
        pv_hourly_kwh=hourly,
        capacity_factor=float(model.Outputs.capacity_factor) / 100,
    )
