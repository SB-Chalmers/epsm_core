"""Archetype definitions for parametric building simulation.

Each archetype bundles the fixed simulation parameters (envelope, HVAC set-points,
internal gains, etc.) for a building typology.  Per-building values such as
``num_floors`` and ``ventilation_system`` are supplied as overrides.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, replace
from typing import Mapping

# ---------------------------------------------------------------------------
# Dahlström parity mode
# ---------------------------------------------------------------------------
# Set DAHLSTROM_PARITY=1 to match the simulation assumptions of Dahlström 2025:
#   • Heating setpoint 20 °C  (default: BETSI mean 22.3 °C)
#   • FTX seasonal HRV 0.75   (default: field-measured 0.65, see hvac.py)
# This flag is propagated to hvac.py via the same env-var so both files
# change together.  Leave unset (or =0) for the standard BETSI-grounded run.
DAHLSTROM_PARITY: bool = bool(int(os.environ.get("DAHLSTROM_PARITY", "0")))

from .building_params import BuildingParams, FacadeWWR
from .constructions import LEVER_BOUNDS, make_construction_set


# ---------------------------------------------------------------------------
# BETSI FB_Klimat.csv — FH WWR distribution per orientation (n ≈ 500 each)
# Standard WWR = window area / gross facade (wall + window + door).
# Source: FINDINGS.md §5.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WWRDistribution:
    """Empirical WWR distribution for one facade orientation."""
    mean: float
    median: float
    p10: float
    p25: float
    p75: float
    p90: float


# BETSI FH all building types, all eras (no year filter available for FH).
BETSI_WWR = {
    "north": WWRDistribution(mean=0.170, median=0.161, p10=0.060, p25=0.100, p75=0.220, p90=0.290),
    "south": WWRDistribution(mean=0.205, median=0.198, p10=0.080, p25=0.125, p75=0.272, p90=0.330),
    "east":  WWRDistribution(mean=0.201, median=0.196, p10=0.070, p25=0.135, p75=0.257, p90=0.320),
    "west":  WWRDistribution(mean=0.214, median=0.214, p10=0.080, p25=0.136, p75=0.273, p90=0.340),
}


def sample_wwr(rng: random.Random | None = None) -> FacadeWWR:
    """Sample facade WWR from BETSI FH empirical distributions.

    Uses a truncated normal fitted to the BETSI percentiles per orientation.
    IQR → σ ≈ IQR / 1.35, clamped to [P10, P90].
    """
    if rng is None:
        rng = random.Random()

    values = {}
    for orient, dist in BETSI_WWR.items():
        sigma = (dist.p75 - dist.p25) / 1.35
        val = rng.gauss(dist.mean, sigma)
        val = max(dist.p10, min(dist.p90, val))  # clamp to [P10, P90]
        values[orient] = round(val, 3)

    return FacadeWWR(**values)


def cmf_1960(
    num_floors: int,
    ventilation_system: str,
    apartment_depth: float = 0.0,
    residential_pct: int = 100,
    garage_pct: float = 0.0,
    num_basement_floors: int = 0,
    wwr: FacadeWWR | None = None,
    seed: int | None = None,
    cold_attic: bool = False,
    core_setpoint_C: float | None = None,
) -> BuildingParams:
    """CMF 1960 archetype – Swedish multi-family concrete, 1961-1975.

    Fixed parameters come from Sveby 2.0, BETSI, and TABULA/EPSM references.

    Args:
        wwr: Explicit WWR override.  If None, sampled from BETSI distribution.
        seed: RNG seed for reproducible WWR sampling (ignored if wwr is provided).
    """
    if wwr is None:
        wwr = sample_wwr(random.Random(seed))

    return BuildingParams(
        num_floors=num_floors,

        # [m] floor-to-floor height including slab.
        # ASSUMPTION — typical miljonprogrammet lamellhus (2.6-2.8 m range).
        # TODO: verify against TABULA SE or BETSI FA.csv measured heights.
        floor_height=2.7,

        # [-] window-to-wall ratio per cardinal direction.
        # Sampled from BETSI FH empirical distribution (FINDINGS.md §5.3).
        # Medians: N=0.16, S=0.20, E=0.20, W=0.21.  [VERIFIED]
        wwr=wwr,

        # Layered constructions from EPSM CMF_1960_2 variant.
        # Wall U=0.40 (TABULA ref 0.41), Window U=2.22 (TABULA). [VERIFIED]
        construction_set="CMF_1960_1",

        apartment_depth=apartment_depth,

        # [°C] heating / cooling set-points.
        # Default: BETSI §17.1 FH mean indoor temperature = 22.3 ± 0.2 °C.
        # Dahlström parity (DAHLSTROM_PARITY=1): 20 °C (Dahlström 2025 §1.3).
        t_heating=20.0 if DAHLSTROM_PARITY else 22.3,
        t_cooling=25.0,

        ventilation_system=ventilation_system,

        # [ACH] uncontrolled envelope leakage (infiltration only, excl. mech vent).
        # BETSI FH tracer-gas total ACH: mean=0.52, P50≈0.47, P75≈0.70.
        # For "S" (självdrag): no mechanical system, so infiltration_ach must
        # represent the FULL natural air exchange.  BETSI median 0.47 ≈ 0.50.
        # Earlier 0.40 (BETSI P25) was a conservative lower bound chosen during
        # Cluster-2 calibration; the central BETSI value is more defensible for
        # population-scale deployment.  Cross-validation: 0.40→0.50 closes the
        # remaining post-mech-vent-fix residual S gap (ratio 0.92→~0.99) on
        # the 3-city n=337 S-vent cohort.  [BETSI §17.2; FINDINGS §3]
        # For mechanical systems (F/FT/FTX/FVP): mech vent 0.35 l/s/m²
        # at 2.7 m ceiling = 0.467 ACH.  Fan-induced depressurisation in
        # 1960s concrete buildings with degraded seals drives significant
        # parasitic leakage through the envelope.  BETSI P25≈0.35 for
        # residual infiltration with exhaust fan running.  Calibrated
        # against 17 Cluster-2 F-vent buildings: 0.15→0.35 closes ~50%
        # of the EP gap (ratio 0.65→~0.80).  [EDA Step 5; BETSI §17.2]
        #
        # Height-aware stack scaling for S buildings (Sherman-Grimsrud):
        # stack-driven ACH scales as sqrt(h_stack), with the 0.50 baseline
        # anchored to a 4-storey reference block. A 2-storey S block then
        # gets 0.50*sqrt(2/4) = 0.35 ACH, matching real-world measurements
        # for small 1950s lamellhus. Mechanical buildings (F/FT/FTX/FVP)
        # are dominated by fan-induced ΔP which is height-independent;
        # we leave their infiltration flat at 0.35.
        infiltration_ach=(
            0.50 * math.sqrt(max(num_floors, 1) / 4.0)
            if ventilation_system == "S" else 0.35
        ),

        # [l/(s·m²)] mechanical outdoor air supply.
        # BBR 9:4 (BFS 2011:6) minimum for residential MFH. [VERIFIED]
        # 85%+ of EPC records use exactly this value (see FINDINGS.md §3.5).
        # For "S" (självdrag): no mechanical system → 0.0.
        mech_vent_l_s_m2=0.0 if ventilation_system == "S" else 0.35,

        # [people/m²] occupant density → 0.017 = ~59 m²/person.
        # Derived from Sveby 2.0: person-heat avg ≈ 1.36 W/m² ÷ 80 W/person.
        # Applied with 14 h/day presence schedule (17:00-07:00).
        # ASSUMPTION — Sveby doesn't give density directly; verify derivation.
        occupant_density=0.017,

        # [W/m²] lighting internal gain — zero because lighting is included
        # in hushållsel, modelled via equipment_w_m2 below.  Sveby 2.0. [VERIFIED]
        lighting_w_m2=0.0,

        # [W/m²] hushållsel internal heat gain (household electricity).
        # Sveby 2.0: 21 kWh/m²/yr × 70% usable heat = 14.7 kWh/m²/yr
        # → 14.7 × 1000 / 8760 = 1.68 W/m².  Excluded from EPC. [VERIFIED]
        equipment_w_m2=1.68,

        # [-] infiltration schedule fraction (0.0–1.0).  1.0 = always on. [VERIFIED]
        infiltration_on=1.0,

        # [kWh/(m²·yr)] domestic hot water demand.
        # Sveby 2.0: 21 kWh/m²Atemp/yr, no zone heat gain. [VERIFIED]
        dhw_kwh_m2=21.0,

        # [kWh/(m²·yr)] DHW circulation (VVC) pipe losses.
        # BETSI: ~80% of FH have VVC systems. Typical losses 5–6 kWh/m²/yr.
        # EPC FjvVV for ÄGIR 17 = 25.0 kWh/m²; DHW 21 + VVC 6 = 27 → close.
        # 6 kWh/m² is upper-median for 1960s buildings.  [BETSI §17]
        dhw_vvc_kwh_m2=6.0,

        # [W/m²] building services electricity (fastighetsel) as zone gain.
        # Set to 0 — fastighetsel is added post-hoc from EPC metered data
        # in reporting.py, not simulated as an internal gain. [VERIFIED]
        bldg_services_w_m2=0.0,

        residential_pct=residential_pct,
        garage_pct=garage_pct,
        num_basement_floors=num_basement_floors,
        cold_attic=cold_attic,

        # BETSI FB_Klimat: thermal bridges add ~15-20% to total UA (§10).
        # 1960s concrete lamellhus with minimal thermal breaks → upper
        # end of range.  25% is defensible for this era.  [BETSI §13.5]
        thermal_bridge_fraction=0.25,

        # Sveby 2.0: total solar shading factor = 0.71 (behavioral, curtains)
        # × 0.71 (fixed, reveal/overhang) ≈ 0.50.  Applied to window SHGC.
        solar_shading_factor=0.50,
        core_setpoint_C=core_setpoint_C,
    )


# ---------------------------------------------------------------------------
# Calibration / sensitivity levers
# ---------------------------------------------------------------------------

# Envelope levers consumed by make_construction_set().
_ENVELOPE_LEVERS = ("wall_mw", "roof_mw", "floor_eps", "window_u")

# Levers that map directly onto BuildingParams fields.
_PARAM_LEVERS = {
    "infiltration_ach":    "infiltration_ach",
    "thermal_bridge_frac": "thermal_bridge_fraction",
    "t_heating":           "t_heating",
    "vent_recovery_eff":   "vent_recovery_eff",
}

# Post-hoc levers — not applied to BuildingParams; the caller divides the
# simulated heating result by this factor (or applies it elsewhere).
_POSTHOC_LEVERS = ("heating_sys_eff",)


def apply_levers(
    params: BuildingParams,
    levers: Mapping[str, float],
    *,
    template: str = "BETSI_CONC_SLAB",
    spec_id: str | None = None,
    validate_bounds: bool = True,
) -> BuildingParams:
    """Return a new ``BuildingParams`` with the given lever values applied.

    Envelope levers (``wall_mw``, ``roof_mw``, ``floor_eps``, ``window_u``)
    register a fresh construction set via
    :func:`pbgenerator.constructions.make_construction_set` and the returned
    id is set on the new params.  ``infiltration_ach`` and
    ``thermal_bridge_frac`` are forwarded onto ``BuildingParams`` directly.

    The post-hoc lever ``heating_sys_eff`` is **not** baked into the params
    (E+ has no first-class system-efficiency knob in our HVAC ideal-loads
    setup); apply it to the simulated heating value at the result step.

    Parameters
    ----------
    params:
        The baseline ``BuildingParams`` to start from (e.g. from ``cmf_1960``).
    levers:
        Mapping of lever name to value.  Any subset of
        :data:`pbgenerator.constructions.LEVER_BOUNDS` keys.
    template:
        Construction-set template used as base for envelope levers.
    spec_id:
        Optional explicit construction-set id; auto-generated if omitted.
    validate_bounds:
        If True (default), values outside :data:`LEVER_BOUNDS` raise
        ``ValueError``.  Set to False for sensitivity sweeps that
        intentionally probe out-of-range values.
    """
    unknown = set(levers) - set(LEVER_BOUNDS)
    if unknown:
        raise ValueError(f"Unknown lever(s): {sorted(unknown)}")

    if validate_bounds:
        for k, v in levers.items():
            lo, hi = LEVER_BOUNDS[k]
            if not (lo <= v <= hi):
                raise ValueError(
                    f"Lever '{k}'={v} outside bounds [{lo}, {hi}]"
                )

    # 1. Build construction set if any envelope lever is touched.
    env_kwargs = {k: levers[k] for k in _ENVELOPE_LEVERS if k in levers}
    if env_kwargs:
        cset_id = make_construction_set(template, spec_id=spec_id, **env_kwargs)
    else:
        cset_id = params.construction_set

    # 2. Apply BuildingParams-resident levers.
    overrides: dict = {"construction_set": cset_id}
    for lever, field_name in _PARAM_LEVERS.items():
        if lever in levers:
            overrides[field_name] = levers[lever]

    return replace(params, **overrides)
