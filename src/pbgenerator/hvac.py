from __future__ import annotations

import os

from honeybee.altnumber import no_limit
from honeybee.room import Room
from honeybee_energy.hvac.idealair import IdealAirSystem
from honeybee_energy.load.infiltration import Infiltration
from honeybee_energy.load.ventilation import Ventilation
from honeybee_energy.load.setpoint import Setpoint

from .building_params import BuildingParams
from .schedule import make_constant_fractional, make_constant_temp_schedule


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# Sensible / latent heat recovery effectiveness by ventilation system type.
# S   = natural ventilation (självdrag), no mechanical system, no recovery
# F   = exhaust only (frånluft), no recovery
# FT  = supply + exhaust, no heat exchanger
# FTX = supply + exhaust with plate/rotary HX
#
# FTX seasonal-effective sensible recovery = 0.65, NOT manufacturer nameplate
# (typically 0.80-0.85).  Field studies of installed Swedish FTX consistently
# report a 15-20 percentage-point shortfall vs nameplate due to:
#   - frost-defrost bypass cycling at OA < ~-5 °C (significant fraction of
#     Swedish heating season)
#   - HX fouling in 1960s retrofit installs (older filters, less maintenance)
#   - duct heat losses upstream of the supply diffuser when ducts run in
#     unheated attics/shafts
# References: Roulet et al. 2001 (real heat recovery 51-65% vs nameplate
# 70-85%); Boverket BETSI follow-up FTX measurements; Dahlström 2025 §1.4.
# Cross-validation: lowering 0.80→0.65 closes the post-mech-vent-fix
# residual ratio gap (0.89→~0.94) on the 3-city n=457 FTX cohort.
#
# Dahlström parity (DAHLSTROM_PARITY=1): 0.75 (Dahlström 2025 §1.4 nameplate).
#
# Note: FVP (frånluftvärmepump) is a *heating system*, not a ventilation type.
# Its COP benefit is handled in reporting.py as a delivered-energy correction.
_DAHLSTROM_PARITY: bool = bool(int(os.environ.get("DAHLSTROM_PARITY", "0")))
_FTX_RECOVERY: float = 0.75 if _DAHLSTROM_PARITY else 0.65

_VENT_RECOVERY: dict[str, tuple[float, float]] = {
    "S":   (0.0,          0.0),
    "F":   (0.0,          0.0),
    "FT":  (0.0,          0.0),
    "FTX": (_FTX_RECOVERY, 0.0),
}


def apply_hvac(rooms: list[Room], params: BuildingParams, *, zone_label: str = "") -> None:
    """Apply HVAC, setpoints, infiltration and ventilation to rooms.

    ``zone_label`` (optional, e.g. ``"CORE"``) is appended to every shared
    schedule identifier and to per-room object tags, so this function can be
    called multiple times on disjoint room lists (e.g. perimeter @ 21 °C and
    core @ 18 °C) without IDF identifier collisions.

    Airflow handling (always-on, deadband-independent):
    - Mechanical ventilation OA is folded into the Infiltration object as
      ``(1 - sens_rec) × mech_vent`` so the heating system always pays the
      preheat penalty.  This avoids EnergyPlus' IdealLoadsAirSystem behaviour
      where the prescribed `DesignSpecification:OutdoorAir` is only delivered
      when the thermostat calls — which silently dropped 30–45 kWh/m² of OA
      load for F/FT/FTX buildings sitting in the heating deadband.
    - The honeybee Ventilation object (→ IdealAir DetailedSpecification) is
      left unset, so IdealAir delivers zero OA.  HRV effectiveness is encoded
      in the infiltration flow itself (FTX 0.80 → only 20 % of mech flow is
      a heating load); the IdealAir `sensible_heat_recovery` field is set to
      0 to avoid double-counting.

    Cooling is effectively disabled by setting the cooling setpoint to 100 °C,
    because these existing residential buildings do not have active cooling
    systems.
    """
    p = params

    vent_sys = p.ventilation_system.upper()
    if vent_sys not in _VENT_RECOVERY:
        raise ValueError(
            f"Unknown ventilation_system '{vent_sys}'. "
            f"Available: {', '.join(sorted(_VENT_RECOVERY))}"
        )
    sens_rec, lat_rec = _VENT_RECOVERY[vent_sys]
    # Calibration lever: override system-default sensible recovery if explicitly set.
    # Interpreted as "effective recovery from any cause" — installed HRV,
    # FVP retrofit, or under-ventilation that reduces OA load.
    if p.vent_recovery_eff is not None:
        sens_rec = _clamp(float(p.vent_recovery_eff), 0.0, 0.95)

    sfx = f"_{zone_label}" if zone_label else ""
    inf_sched = make_constant_fractional(f"INF_SCH{sfx}", p.infiltration_on)
    htg_sched = make_constant_temp_schedule(f"HTG_SCH{sfx}", _clamp(p.t_heating, 5.0, 30.0))
    # Cooling setpoint set to 100 °C → cooling never activates.
    clg_sched = make_constant_temp_schedule(f"CLG_SCH{sfx}", 100.0)

    # Mechanical ventilation: l/s per m² floor → m³/s per m² floor
    mech_flow_m3s = _clamp(p.mech_vent_l_s_m2, 0.0, 5.0) / 1000.0

    # Envelope leakage: empirical ACH (BETSI-derived).
    # Convert ACH → flow_per_exterior_area per room (geometry-dependent).
    inf_ach = _clamp(p.infiltration_ach, 0.0, 3.0)

    for idx, room in enumerate(rooms):
        tag = f"R{idx}{sfx}"

        # Convert ACH to flow_per_exterior_area for this room's geometry.
        vol = room.volume
        ext_area = room.exposed_area   # exterior wall + roof area
        if ext_area > 0 and inf_ach > 0:
            leak_flow_per_ext = inf_ach * vol / 3600.0 / ext_area
        else:
            leak_flow_per_ext = 0.0

        # Mechanical-vent OA after HRV, expressed as a per-floor-area flow,
        # converted to per-exterior-area for this room's geometry so it
        # adds onto the infiltration object.
        floor_area = room.floor_area
        mech_after_hrv_m3s = mech_flow_m3s * (1.0 - sens_rec)
        if ext_area > 0 and mech_after_hrv_m3s > 0 and floor_area > 0:
            mech_per_ext = mech_after_hrv_m3s * floor_area / ext_area
        else:
            mech_per_ext = 0.0

        # Combined always-on OA load: envelope leakage + post-HRV mech-vent.
        # For rooms with no exterior surface (core/corridor zones) ext_area == 0
        # and flow_per_exterior_area would silently give zero.  Fall back to
        # flow_per_zone computed from absolute volume and floor-area flows.
        if ext_area > 0:
            total_per_ext = leak_flow_per_ext + mech_per_ext
            room.properties.energy.infiltration = Infiltration(
                f"Inf_{tag}", flow_per_exterior_area=total_per_ext, schedule=inf_sched,
            )
        else:
            # No envelope leakage for interior zones; still deliver mech-vent OA.
            total_abs_m3s = mech_after_hrv_m3s * floor_area  # m³/s absolute
            if total_abs_m3s > 0:
                # Use ACH as a proxy: EPlus accepts air_changes_per_hour via
                # a workaround — set flow_per_exterior_area to a large value
                # over a proxy area of 1 m² so the absolute flow is correct.
                # Simpler: honeybee Infiltration can encode ACH via the
                # flow_per_exterior_area parameter mapped to unit area.
                # Cleanest: scale to vol-based ACH (ceiling_h from params
                # is unavailable here; use floor_area as shorthand volume).
                ach_core = total_abs_m3s * 3600.0 / (floor_area * p.floor_height)
                # Re-express as per-floor-area so flow = ach × vol = ach × A × h.
                # Since ext_area == 0 won't work, use a virtual_ext = floor_area.
                virtual_ext = floor_area
                room.properties.energy.infiltration = Infiltration(
                    f"Inf_{tag}",
                    flow_per_exterior_area=total_abs_m3s / virtual_ext,
                    schedule=inf_sched,
                )

        # NOTE: Ventilation object intentionally NOT set — IdealAir's
        # DesignSpecification:OutdoorAir only fires on thermostat calls,
        # which leaves the zone in the deadband for much of the year and
        # under-applies the OA preheat load.  HRV is already baked into
        # the infiltration flow above, so set IdealAir's recovery to 0.

        room.properties.energy.setpoint = Setpoint(
            f"Setpoint_{tag}", heating_schedule=htg_sched, cooling_schedule=clg_sched,
        )
        room.properties.energy.hvac = IdealAirSystem(
            f"IdealAir_{tag}",
            heating_limit=no_limit,
            cooling_limit=no_limit,
            economizer_type='NoEconomizer',
            sensible_heat_recovery=0.0,
            latent_heat_recovery=0.0,
        )
