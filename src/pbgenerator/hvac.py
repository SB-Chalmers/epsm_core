from __future__ import annotations

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
# FTX = supply + exhaust with plate/rotary HX (~80 % sensible recovery)
#
# Note: FVP (frånluftvärmepump) is a *heating system*, not a ventilation type.
# Its COP benefit is handled in reporting.py as a delivered-energy correction.
_VENT_RECOVERY: dict[str, tuple[float, float]] = {
    "S":   (0.0,  0.0),
    "F":   (0.0,  0.0),
    "FT":  (0.0,  0.0),
    "FTX": (0.80, 0.0),
}


def apply_hvac(rooms: list[Room], params: BuildingParams) -> None:
    """Apply HVAC, setpoints, infiltration and ventilation to rooms.

    Airflow split:
    - Ventilation object  → mechanical outdoor air (l/s per m² floor).
      The IdealAirSystem picks this up via DetailedSpecification and applies
      heat recovery (sensible_heat_recovery) to this airstream.
    - Infiltration object → uncontrolled envelope leakage (ACH), no recovery.
      Set as flow_per_exterior_area derived from the empirical ACH value.

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

    inf_sched = make_constant_fractional("INF_SCH", p.infiltration_on)
    htg_sched = make_constant_temp_schedule("HTG_SCH", _clamp(p.t_heating, 5.0, 30.0))
    # Cooling setpoint set to 100 °C → cooling never activates.
    clg_sched = make_constant_temp_schedule("CLG_SCH", 100.0)

    # Mechanical ventilation: l/s per m² floor → m³/s per m² floor
    mech_flow_m3s = _clamp(p.mech_vent_l_s_m2, 0.0, 5.0) / 1000.0

    # Envelope leakage: empirical ACH (BETSI-derived).
    # Convert ACH → flow_per_exterior_area per room (geometry-dependent).
    inf_ach = _clamp(p.infiltration_ach, 0.0, 3.0)

    for idx, room in enumerate(rooms):
        tag = f"R{idx}"

        # Convert ACH to flow_per_exterior_area for this room's geometry.
        vol = room.volume
        ext_area = room.exposed_area   # exterior wall + roof area
        if ext_area > 0 and inf_ach > 0:
            leak_flow_per_ext = inf_ach * vol / 3600.0 / ext_area
        else:
            leak_flow_per_ext = 0.0

        # Infiltration: envelope leakage only
        room.properties.energy.infiltration = Infiltration(
            f"Inf_{tag}", flow_per_exterior_area=leak_flow_per_ext, schedule=inf_sched,
        )

        # Mechanical ventilation: IdealAirSystem reads this via
        # DetailedSpecification and applies heat recovery to it.
        room.properties.energy.ventilation = Ventilation(
            f"MechVent_{tag}", flow_per_area=mech_flow_m3s,
        )

        room.properties.energy.setpoint = Setpoint(
            f"Setpoint_{tag}", heating_schedule=htg_sched, cooling_schedule=clg_sched,
        )
        room.properties.energy.hvac = IdealAirSystem(
            f"IdealAir_{tag}",
            heating_limit=no_limit,
            cooling_limit=no_limit,
            economizer_type='NoEconomizer',
            sensible_heat_recovery=sens_rec,
            latent_heat_recovery=lat_rec,
        )
