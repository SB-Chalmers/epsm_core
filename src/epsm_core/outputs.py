# File: outputs.py
# Purpose: Discover owned result names and conditional availability without EnergyPlus.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# Date created: 2026-10-21
"""Public output contracts, separate from physical calculations and engine execution.

Only outputs guaranteed by Core's result interpreter appear as available.
Additional free-text EnergyPlus variable requests remain unverified until the
engine's output dictionary establishes their existence, key scope and units.
"""

from __future__ import annotations

DEMAND_OUTPUTS = ("space_heating_demand", "cooling_demand", "dhw_load")


def _rows(
    name, unit, *, available=True, reason=None, resolutions=("hourly", "annual"), level="building"
):
    return [
        dict(
            name=name,
            resolution=resolution,
            level=level,
            unit=unit,
            available=bool(available),
            **({"reason": reason} if reason else {}),
        )
        for resolution in resolutions
    ]


def delivery_output_capabilities(building=None):
    """Describe Core's shared space-heating/fan result fields without calculating.

    Parameters
    ----------
    building : epsm_core.Building, optional
        Already loaded authoring model. Missing delivery remains unavailable.

    Returns
    -------
    list of dict
        Names, hourly/annual resolutions, building scope, kWh units and explicit
        availability. RC uses this same public contract for delegated accounting.
    """
    hvac = getattr(building, "hvac", None)
    heating = hvac.delivery.heating if hvac is not None else None
    result = []
    for name in ("space_heating_carrier_input_kwh", "net_distribution_loss_kwh"):
        result.extend(
            _rows(
                name,
                "kWh",
                available=heating is not None,
                reason=None if heating is not None else "Requires explicit heating delivery",
            )
        )
    fan = heating is not None and heating.specific_fan_power_w_per_l_s is not None
    result.extend(
        _rows(
            "ventilation_fan_electricity_kwh",
            "kWh",
            available=fan,
            reason=None if fan else "Requires explicit specific fan power",
        )
    )
    return result


def output_capabilities(building=None, *, weather=None, settings=None):
    """Discover EnergyPlus result contracts without starting or compiling an engine.

    Parameters
    ----------
    building : epsm_core.Building, optional
        Loaded physical inputs, used for conditional delivery/PV and zone names.
    weather : epsm_core.Weather, optional
        Inspected calendar metadata. Together with a complete Building this
        resolves exact native zone-temperature keys through public resolution.
    settings : CompilerSettings or dict, optional
        Explicit additional hourly requests. Free-text requests are retained in
        ``unverified_requests`` and never advertised as guaranteed outputs.

    Returns
    -------
    dict
        Versioned ``outputs`` descriptors and calendar support. Available output
        descriptors state exact names, resolution, level and units. The catalogue
        does not guarantee successful numerical execution or weather accuracy.

    Examples
    --------
    >>> rows = output_capabilities()["outputs"]
    >>> next(row["unit"] for row in rows if row["name"] == "space_heating_demand_kwh")
    'kWh'
    """
    from .compiler import OUTPUT_VARIABLES
    from .settings import CompilerSettings

    settings = (
        settings
        if isinstance(settings, CompilerSettings)
        else CompilerSettings.model_validate(settings or {})
    )
    outputs = []
    for name in DEMAND_OUTPUTS:
        outputs.extend(_rows(name + "_kwh", "kWh"))
        outputs.extend(_rows(name + "_eui_kwh_m2", "kWh/m2", resolutions=("annual",)))
        if name != "dhw_load":
            outputs.extend(
                _rows("peak_hourly_average_" + name + "_kw", "kW", resolutions=("annual",))
            )
    outputs.extend(_rows("ideal_thermal_load_kwh", "kWh"))
    outputs.extend(_rows("ideal_thermal_load_eui_kwh_m2", "kWh/m2", resolutions=("annual",)))
    outputs.extend(_rows("maximum_hourly_average_zone_temperature_c", "C", resolutions=("annual",)))
    outputs.extend(delivery_output_capabilities(building))
    hvac = getattr(building, "hvac", None)
    fvp = hvac is not None and hvac.delivery.fvp is not None
    for name in (
        "fvp_heat_kwh",
        "fvp_electricity_kwh",
        "backup_input_kwh",
        "fvp_extracted_heat_kwh",
    ):
        outputs.extend(
            _rows(
                name, "kWh", available=fvp, reason=None if fvp else "Requires explicit FVP delivery"
            )
        )
    pv = hvac is not None and bool(hvac.renewables.pv_systems)
    outputs.extend(
        _rows(
            "pv_generation_kwh",
            "kWh",
            available=pv,
            reason=None if pv else "Requires a declared PV system",
        )
    )
    unresolved, zone_names = [], set()
    if building is not None and weather is not None:
        try:
            resolved = building.resolve(weather)
            zone_names = {name.upper() for name in resolved.zones}
            for name in resolved.zones:
                outputs.extend(
                    _rows(
                        f"Zone Mean Air Temperature::{name.upper()}",
                        "C",
                        resolutions=("hourly",),
                        level="zone",
                    )
                )
        except (TypeError, ValueError, OSError) as error:
            unresolved.append(str(error))
    return dict(
        format="epsm-output-capabilities/1",
        engine="energyplus",
        outputs=outputs,
        calendar={"supports_leap": True, "reference": "selected Core calendar"},
        unverified_requests=[
            request.model_dump(mode="json")
            for request in settings.hourly_outputs
            if not (
                request.key == "*" and request.name in {name.upper() for name in OUTPUT_VARIABLES}
            )
            and not (request.name == "ZONE MEAN AIR TEMPERATURE" and request.key in zone_names)
        ],
        unresolved_native_outputs=unresolved,
    )
