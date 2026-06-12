from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FacadeWWR:
    north: float
    east: float
    south: float
    west: float


@dataclass(frozen=True)
class BuildingParams:
    num_floors: int
    floor_height: float
    wwr: FacadeWWR
    construction_set: str
    apartment_depth: float
    t_heating: float
    t_cooling: float
    ventilation_system: str             # "S", "F", "Fmed", "FT", "FTX", or "FVP"
    infiltration_ach: float             # uncontrolled envelope leakage (ACH), BETSI empirical
    mech_vent_l_s_m2: float             # mechanical ventilation (l/s per m² floor)
    occupant_density: float
    lighting_w_m2: float
    equipment_w_m2: float
    infiltration_on: float
    dhw_kwh_m2: float
    bldg_services_w_m2: float
    residential_pct: int = 100          # EgenAtempBostad (0-100)
    garage_pct: float = 0.0             # heated-garage share of Atemp (0-100)
    num_basement_floors: int = 0        # heated basement floors (EgenAntalKallarplan)
    basement_floor_height: float = 2.7  # floor-to-floor height of basement [m]
    basement_depth_below_grade: float = 2.0  # depth of basement below ground [m]
    basement_wwr: float = 0.05          # WWR for above-grade strip of basement walls
    cold_attic: bool = False              # add unconditioned attic zone above top floor
    thermal_bridge_fraction: float = 0.0   # fractional UA increase for thermal bridges (e.g. 0.20 = +20%)
    dhw_vvc_kwh_m2: float = 0.0            # DHW circulation (VVC) pipe losses (kWh/m²/yr)
    solar_shading_factor: float = 1.0      # Sveby solar shading multiplier on SHGC (0.5 = curtains+fixed)
    vent_recovery_eff: float | None = None  # If set, overrides _VENT_RECOVERY[vent_sys] sensible HRV
                                            # (used as calibration lever; represents installed HRV,
                                            # FVP retrofit, or under-ventilation in F/S systems)
    core_setpoint_C: float | None = None    # If set (and a core zone exists from
                                            # apartment_depth > 0), the core is heated
                                            # to this setpoint instead of being left
                                            # unconditioned.  Models semi-heated
                                            # stair/corridor shafts (~18 °C typical
                                            # for 1960s Swedish lamellhus).

    # Natural ventilation via ZoneVentilation:WindandStackOpenArea.
    # All four fields default to None/off — set nat_vent_t_open_c to enable.
    nat_vent_t_open_c: float | None = None  # Min indoor temp [°C] to open windows
                                            # (None = natural ventilation disabled).
                                            # Typical: 24.0 °C
    nat_vent_min_outdoor_t_c: float = 18.0  # Min outdoor temp [°C] below which
                                            # windows stay closed (prevents winter
                                            # opening when indoor > trigger).
    nat_vent_max_outdoor_t_c: float = 26.0  # Max outdoor temp [°C] above which
                                            # windows stay closed (too hot outside).
    nat_vent_max_wind_ms: float = 6.0       # Max wind speed [m/s] — close if gusty.
    nat_vent_opening_frac: float = 0.06     # Operable window area as a fraction of
                                            # zone floor area (≈ WWR 0.15 × 40%
                                            # operable = 0.06).


@dataclass(frozen=True)
class Config:
    footprint_pts: list[list[float]]
    building: BuildingParams
    weather_file: Path
    idf_dir: Path
    output_dir: Path
    energyplus_cmd: str


def load_config(config_path: Path) -> Config:
    data = json.loads(config_path.read_text())

    fp = data["footprint_pts"]
    if not isinstance(fp, list) or len(fp) < 3:
        raise ValueError("footprint_pts must be a list of at least 3 [x, y] coordinate pairs")

    b = data.get("building", {})
    raw_wwr = b.get("wwr", 0.35)
    if isinstance(raw_wwr, dict):
        wwr = FacadeWWR(
            north=float(raw_wwr.get("north", 0.35)),
            east=float(raw_wwr.get("east", 0.35)),
            south=float(raw_wwr.get("south", 0.35)),
            west=float(raw_wwr.get("west", 0.35)),
        )
    else:
        v = float(raw_wwr)
        wwr = FacadeWWR(north=v, east=v, south=v, west=v)
    building = BuildingParams(
        num_floors=int(b.get("num_floors", 1)),
        floor_height=float(b.get("floor_height", 3.2)),
        wwr=wwr,
        construction_set=str(b.get("construction_set", "CMF_1960_2")),
        apartment_depth=float(b.get("apartment_depth", 0.0)),
        t_heating=float(b.get("t_heating", 21.0)),
        t_cooling=float(b.get("t_cooling", 25.0)),
        ventilation_system=str(b.get("ventilation_system", "F")).upper(),
        infiltration_ach=float(b.get("infiltration_ach", 0.10)),
        mech_vent_l_s_m2=float(b.get("mech_vent_l_s_m2", 0.35)),
        occupant_density=float(b.get("occupant_density", 0.028)),
        lighting_w_m2=float(b.get("lighting_w_m2", 0.0)),
        equipment_w_m2=float(b.get("equipment_w_m2", 1.68)),
        infiltration_on=float(b.get("infiltration_on", 1.0)),
        dhw_kwh_m2=float(b.get("dhw_kwh_m2", 21.0)),
        bldg_services_w_m2=float(b.get("bldg_services_w_m2", 0.0)),
    )

    footprint = [[float(c) for c in pt] for pt in fp]

    raw_weather = data.get("weather_file", "auto")
    if raw_weather == "auto":
        from .weather import nearest_epw_from_footprint
        weather_file = nearest_epw_from_footprint(footprint)
    else:
        weather_file = Path(raw_weather).expanduser()

    return Config(
        footprint_pts=footprint,
        building=building,
        weather_file=weather_file,
        idf_dir=Path(data.get("idf_dir", data.get("output_dir", "./results"))).expanduser(),
        output_dir=Path(data.get("output_dir", "./results")).expanduser(),
        energyplus_cmd=data.get("energyplus_cmd", "energyplus"),
    )
