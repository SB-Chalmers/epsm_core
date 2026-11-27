"""Evidence-backed, bounded psychrometric warnings for annual heating.

EnergyPlus 24.2 source and cohort evidence: docs/warning-acceptance.md.
This review never substitutes for engine completion or SQL result validation.
"""

import re

import numpy as np

POLICY_VERSION = "psychrometric-annual-heating-2"
TEMPERATURE_EXCURSION_LIMIT = 20
NEAR_FREEZING_LIMIT = 3
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
        # Version 2: the resultant only has to be a physical wet bulb for the input
        # (at most the dry bulb, within 15 K of it). Version 1 also required |result| <= 0.5,
        # which rejected ordinary cases such as 4.58 C -> 2.43 C (epsm_core #94).
        if (
            temperature is not None
            and 0 <= temperature <= 10
            and humidity is not None
            and 0 <= humidity <= 0.01
            and pressure is not None
            and 31000 <= pressure <= 120000
            and final is not None
            and temperature - 15 <= final <= temperature + 0.01
        ):
            return "near_freezing_wetbulb_iteration_limit"
    return None


def psychrometric_review_pending(diagnostics, model, engine_end):
    """Allow output inspection only for complete engines and bounded known warnings.

    Limits reflect the audited 24.2 evidence, including finer-timestep reruns:
    at most twenty internal temperature excursions and three near-freezing local
    iteration-limit events per annual run (version 2). Humidity-controlled systems are excluded.
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
    # Version 2 limits (epsm_core #94): 20 internal temperature excursions and 3 local
    # iteration-limit events per annual run. Rerunning two rejected cases at 12 and 20
    # timesteps per hour kept the warnings and moved annual heating by under 0.03 %.
    return (
        totals["wetbulb_iteration_temperature"] <= TEMPERATURE_EXCURSION_LIMIT
        and totals["near_freezing_wetbulb_iteration_limit"] <= NEAR_FREEZING_LIMIT
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
            "temperature_excursion_limit": TEMPERATURE_EXCURSION_LIMIT,
            "near_freezing_iteration_limit": NEAR_FREEZING_LIMIT,
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


ATTIC_VIEW_FACTOR_POLICY = "attic-view-factor-reciprocity-1"
ATTIC_VIEW_FACTOR_TOLERANCE = 0.02
ATTIC_VIEW_FACTOR_ROW_SUM_FRACTION = 0.005


def review_attic_view_factors(diagnostics):
    """Approve EnergyPlus's incomplete-view-factor warning for a closed, unconditioned attic.

    EnergyPlus approximates view factors in a zone with many facets, then enforces
    reciprocity. In a large triangulated cold attic the enforced tolerance can exceed its
    0.001 guideline although the shell is closed: the row sum stays at the surface count.
    The warning is approved only when every rejected message is this warning, the zone is a
    generated attic space, the reciprocity tolerance is at most 0.02 and the row sum is
    within 0.5 % of ideal (epsm_core #93). The attic is unconditioned, so the error only
    reaches heating through the attic's radiant exchange.
    """
    pending = [m for m in diagnostics.get("messages", []) if not m["approved"]]
    if not pending or any(m["category"] != "incomplete_view_factors" for m in pending):
        return False
    if diagnostics.get("severe_count") or diagnostics.get("fatal_count") or diagnostics.get("process_returncode"):
        return False
    for message in pending:
        text = message["original_text"]
        zone = re.search(r'zone="([^"]+)"', text)
        tol = re.search(r"tolerance \(ideal is 0\)=\[([-+0-9.eE]+)\]", text)
        row = re.search(r"Row Sum \(ideal is (\d+)\)=\[([-+0-9.eE]+)\]", text)
        if not (zone and tol and row) or "_ATTIC_" not in zone[1].upper():
            return False
        ideal, value = float(row[1]), float(row[2])
        if float(tol[1]) > ATTIC_VIEW_FACTOR_TOLERANCE or abs(value - ideal) > ATTIC_VIEW_FACTOR_ROW_SUM_FRACTION * ideal:
            return False
    for message in pending:
        message.update(
            approved=True,
            disposition="accepted_with_warning",
            exception_rule={
                "identifier": "attic_view_factor_reciprocity",
                "version": ATTIC_VIEW_FACTOR_POLICY,
                "maximum_reciprocity_tolerance": ATTIC_VIEW_FACTOR_TOLERANCE,
                "maximum_row_sum_fraction": ATTIC_VIEW_FACTOR_ROW_SUM_FRACTION,
            },
        )
    diagnostics.update(
        accepted=all(m["approved"] for m in diagnostics["messages"]),
        invalid_view_factor_count=0,
        attic_view_factor_review=ATTIC_VIEW_FACTOR_POLICY,
    )
    return True
