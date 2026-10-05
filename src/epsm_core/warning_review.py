"""Evidence-backed, bounded psychrometric warnings for annual heating.

EnergyPlus 24.2 source and cohort evidence: docs/warning-acceptance.md.
This review never substitutes for engine completion or SQL result validation.
"""

import re

import numpy as np

POLICY_VERSION = "psychrometric-annual-heating-1"
RANGE_SUMMARY = "Temperature out of range [-100. to 200.] (PsyPsatFnTemp)"
WET_PATTERN = r"WetBulb not converged after (?:101|max) iterations\(PsyTwbFnTdbWPb\)"


def _number(text, label):
    """Read one finite numeric value from a detailed warning continuation."""
    match = re.search(label + r"\s*=\s*([-+0-9.eE]+)", text)
    if not match:
        return None
    try:
        value = float(match[1])
    except ValueError:
        return None
    return value if np.isfinite(value) else None


def _kind(message):
    """Recognize only the audited warning signatures and detailed contexts."""
    if message["severity"] != "warning":
        return None
    summary = message["summary"].strip()
    text = message["original_text"]
    if not re.search(r"Environment=ANNUAL(?:,|\s)", text):
        return None
    if re.search(r"during (?:Warmup|Sizing) [1-9][0-9]* times", text):
        return None
    if summary == RANGE_SUMMARY:
        callers = re.findall(r"Routine=([^,\n]+)", text)
        if callers and all(c.strip() == "PsyTwbFnTdbWPb" for c in callers):
            return "wetbulb_iteration_temperature"
    if re.fullmatch(WET_PATTERN, summary):
        temperature = _number(text, "Input Temperature")
        humidity = _number(text, "Input Humidity Ratio")
        pressure = _number(text, "Input Pressure")
        final = _number(text, "Resultant Temperature")
        if (
            temperature is not None
            and 0 <= temperature <= 5
            and humidity is not None
            and 0 <= humidity <= 0.01
            and pressure is not None
            and 31000 <= pressure <= 120000
            and final is not None
            and abs(final) <= 0.5
        ):
            return "near_freezing_wetbulb_iteration_limit"
    return None


def psychrometric_review_pending(diagnostics, model, engine_end):
    """Allow output inspection only for complete engines and bounded known warnings.

    Limits reflect the audited 24.2 evidence, including finer-timestep reruns:
    at most five internal temperature excursions and one near-freezing local
    iteration-limit event per annual run. Humidity-controlled systems are excluded.
    """
    if (
        diagnostics.get("engine_version") != "24.2"
        or diagnostics.get("process_returncode", 0)
        or diagnostics.get("severe_count", 0)
        or diagnostics.get("fatal_count", 0)
        or "EnergyPlus Completed Successfully" not in engine_end
    ):
        return False
    systems = model.get("ZoneHVAC:IdealLoadsAirSystem", {})
    if not systems or any(
        str(system.get(key, "")).lower() != "none"
        for system in systems.values()
        for key in ("humidification_control_type", "dehumidification_control_type")
    ):
        return False
    pending = [m for m in diagnostics["messages"] if not m["approved"]]
    if not pending:
        return False
    totals = {"wetbulb_iteration_temperature": 0, "near_freezing_wetbulb_iteration_limit": 0}
    for message in pending:
        kind = _kind(message)
        if kind is None or message["occurrence_count"] < 1:
            return False
        totals[kind] += message["occurrence_count"]
    return (
        totals["wetbulb_iteration_temperature"] <= 5
        and totals["near_freezing_wetbulb_iteration_limit"] <= 1
    )


def approve_validated_psychrometrics(diagnostics, output, report):
    """Approve pending warnings only after reconciled finite annual-heating outputs.

    Cooling, humidity and latent-load accuracy are not qualified by this rule.
    Keep every original warning, occurrence count and review limit in the receipt.
    """
    if diagnostics.get("geometry_totals") != "engine_area_volume_reconciled":
        raise ValueError("Psychrometric review requires reconciled engine geometry")
    if not output.hourly or any(not np.isfinite(v).all() for v in output.hourly.values()):
        raise ValueError("Psychrometric review requires finite hourly outputs")
    heating = output.hourly.get("space_heating_demand_kwh")
    if heating is None or np.any(heating < 0):
        raise ValueError("Psychrometric review requires nonnegative hourly heating")
    temperatures = {
        k.split("::", 1)[1].upper(): v
        for k, v in output.hourly.items()
        if k.startswith("Zone Mean Air Temperature::")
    }
    for zone in report.data["zones"]:
        values = temperatures.get(zone.upper())
        if values is None or np.any(values <= -100) or np.any(values >= 200):
            raise ValueError(
                "Psychrometric review requires zone temperatures inside the psychrometric domain"
            )
    for message in diagnostics["messages"]:
        if not message["approved"]:
            kind = _kind(message)
            if kind is None:
                raise ValueError("Unreviewed warning cannot be promoted")
            message.update(
                approved=True,
                disposition="accepted_with_warning",
                exception_rule={
                    "identifier": kind,
                    "version": POLICY_VERSION,
                    "engine_version": "24.2",
                    "scope": "annual_space_heating_demand",
                },
            )
    diagnostics.update(
        accepted=True,
        disposition="accepted_with_warnings",
        warning_review={
            "version": POLICY_VERSION,
            "scope": "annual_space_heating_demand",
            "temperature_excursion_limit": 5,
            "near_freezing_iteration_limit": 1,
            "evidence": [
                "engine_completed_successfully",
                "full_calendar_validated",
                "hourly_annual_energy_reconciled",
                "engine_geometry_reconciled",
                "finite_hourly_outputs",
                "zone_temperature_domain_checked",
            ],
            "unqualified_outputs": ["cooling", "humidity_control", "latent_load_accuracy"],
        },
    )
    diagnostics.pop("failure_code", None)
