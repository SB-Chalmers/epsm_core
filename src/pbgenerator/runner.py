from __future__ import annotations

import logging
import math
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

from honeybee_energy.run import run_idf

from .building_params import BuildingParams
from .idf_builder import write_idf


# ---------------------------------------------------------------------------
# Shared geometry helpers (engine-agnostic)
# ---------------------------------------------------------------------------

def _polygon_area_perimeter(pts: list[list[float]]) -> tuple[float, float]:
    """Return (area m², perimeter m) for a 2-D polygon given as [[x,y,...], ...]."""
    n = len(pts)
    area = 0.0
    perim = 0.0
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        area += x1 * y2 - x2 * y1
        perim += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    return abs(area) / 2.0, perim


def _wall_areas_by_orientation(
    pts: list[list[float]],
    total_wall_height: float,
    wwr,  # FacadeWWR
) -> tuple[dict[str, float], dict[str, float]]:
    """Decompose footprint perimeter into N/S/E/W wall and window areas.

    For each polygon edge the outward normal bearing is computed and classified
    as north / east / south / west (±45° sectors).  Window area = gross × wwr.

    Returns (wall_net_by_orient, window_by_orient) dicts.
    """
    n = len(pts)
    wwr_map = {"north": wwr.north, "east": wwr.east, "south": wwr.south, "west": wwr.west}
    gross: dict[str, float] = {k: 0.0 for k in wwr_map}

    # Sign of polygon area determines winding (CCW → positive via shoelace).
    signed_area = sum(
        pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
        for i in range(n)
    ) / 2.0
    is_ccw = signed_area > 0

    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx ** 2 + dy ** 2)
        if length < 0.01:
            continue

        # Outward normal: CCW polygon → (dy, -dx); CW → (-dy, dx).
        nx, ny = (dy, -dx) if is_ccw else (-dy, dx)
        # Compass bearing of outward normal (0 = N, 90 = E, 180 = S, 270 = W)
        # atan2(east, north) → east component = nx, north component = ny
        bearing = (math.degrees(math.atan2(nx, ny)) + 360.0) % 360.0
        if bearing < 45.0 or bearing >= 315.0:
            orient = "north"
        elif bearing < 135.0:
            orient = "east"
        elif bearing < 225.0:
            orient = "south"
        else:
            orient = "west"
        gross[orient] += length * total_wall_height

    window = {o: gross[o] * wwr_map[o] for o in gross}
    wall_net = {o: gross[o] * (1.0 - wwr_map[o]) for o in gross}
    return wall_net, window


def _resolve_u_values(params: BuildingParams) -> dict[str, float]:
    """Resolve ISO 13790 U-values (with standard surface resistances) from construction_set.

    Honeybee OpaqueConstruction.u_value gives material-only U (no films).
    We add standard ISO 13790 surface resistances:
      walls/floor  Rsi=0.13 + Rse=0.04 = 0.17 m²K/W
      roof         Rsi=0.10 + Rse=0.04 = 0.14 m²K/W
    """
    from .constructions import get_construction_set, _degrade_for_thermal_bridges

    cs = get_construction_set(params.construction_set)
    tb = params.thermal_bridge_fraction

    wall_c = _degrade_for_thermal_bridges(cs.wall, tb)
    # Pick the more-insulating of TOP_FLOOR / ROOF as the top envelope
    # surface: for cold-attic templates (BETSI_CONC_SLAB) the TOP_FLOOR
    # carries the MW lever and the ROOF is a bare weather shell; for
    # compact-flat templates (BETSI_CONC_TOWER / POINT) the ROOF carries
    # the MW lever and TOP_FLOOR is bare interzone concrete. The lower
    # u_value identifies the heated-envelope surface in either case.
    _top_candidates = [c for c in (cs.top_floor, cs.roof) if c is not None]
    top_envelope = min(_top_candidates, key=lambda c: c.u_value)
    roof_c = _degrade_for_thermal_bridges(top_envelope, tb)
    floor_c = _degrade_for_thermal_bridges(cs.ground_floor or cs.floor, tb)
    glaz = cs.window.materials[0]

    # Apply Sveby solar shading factor to effective SHGC
    effective_shgc = glaz.shgc * params.solar_shading_factor

    return {
        "u_wall":  1.0 / (1.0 / wall_c.u_value  + 0.17),
        "u_roof":  1.0 / (1.0 / roof_c.u_value   + 0.14),
        "u_floor": 1.0 / (1.0 / floor_c.u_value  + 0.17),
        "u_window": glaz.u_factor,          # already includes film resistances
        "g_value": effective_shgc,
    }


def _sveby_internal_gains_array(
    occupant_density: float,
    equipment_w_m2: float,
    lighting_w_m2: float,
    bldg_services_w_m2: float,
    floor_area_m2: float,
    n_hours: int = 8760,
) -> "list[float]":
    """Build an hourly internal-gains array [W] following Sveby Bostadshus 2.0.

    Mirrors the schedules used by the EnergyPlus path (see ``schedule.py`` and
    ``programs.py``):
      * Occupancy: 14 h/day at 80 W/person — 00:00-07:00 and 17:00-24:00.
      * Equipment, lighting, services: constant (Sveby annual averages).

    All values are returned in Watts so the array can be passed directly to
    ``Building5R1C.simulate_with_epw(internal_gains=...)``.
    """
    import numpy as np

    occ_fraction = np.zeros(24)
    occ_fraction[0:7] = 1.0     # 00:00-07:00 occupied
    occ_fraction[7:17] = 0.0    # 07:00-17:00 unoccupied (away/work/school)
    occ_fraction[17:24] = 1.0   # 17:00-24:00 occupied
    daily = np.tile(occ_fraction, n_hours // 24 + 1)[:n_hours]

    occ_gain_per_m2 = 80.0 * occupant_density   # W/m² when occupied
    constant_w_m2 = equipment_w_m2 + lighting_w_m2 + bldg_services_w_m2

    gains_w_m2 = constant_w_m2 + occ_gain_per_m2 * daily
    return (gains_w_m2 * floor_area_m2).tolist()


def _run_5r1c(
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    weather_file: Path,
    atemp_override: float | None = None,
    engine_options: dict | None = None,
) -> dict[str, float]:
    """Run an ISO 13790 5R1C simulation via SweThermalModel.

    Derives all inputs (surface areas, U-values, ventilation) from the same
    BuildingParams / footprint used by the EnergyPlus engine so results are
    directly comparable.  Returns the same ``{heating_kwh, cooling_kwh,
    dhw_kwh, site_kwh}`` dict as the EnergyPlus runner.

    Args:
        atemp_override: Heated floor area (m²) override.  Pass
            ``BuildingRooms.perimeter_floor_area`` to match EnergyPlus when
            ``apartment_depth > 0``.
        engine_options: Optional dict of 5R1C-specific overrides — any key
            corresponds to a ``Building5R1C`` constructor argument and replaces
            the wrapper's default.  Common keys:
              * ``hrv_efficiency`` (float): override the FTX→0.65 / else→0.0 default.
              * ``thermal_capacitance_j_m2k`` (float): override the
                concrete-frame default (260 000 J/m²K).
              * ``frame_factor`` (float): override the no-double-count default 1.0.
              * ``use_sveby_schedule`` (bool, default True): when False, use a
                constant ``internal_gains_w_per_m2`` instead of the 14-h Sveby
                occupancy schedule.
              * any other ``Building5R1C`` field (e.g. ``shading_factor``,
                ``g_value_angle_coefficients``, ``f_shading_overhang``).
    """
    from swethermalmodel.iso13790 import Building5R1C  # type: ignore[import]

    opts = dict(engine_options or {})
    use_sveby_schedule = opts.pop("use_sveby_schedule", True)

    p = params
    floor_height = max(2.2, min(p.floor_height, 6.0))
    num_floors = max(1, p.num_floors)
    total_wall_height = floor_height * num_floors

    fp_area, _ = _polygon_area_perimeter(footprint_pts)
    wall_net, window = _wall_areas_by_orientation(footprint_pts, total_wall_height, p.wwr)

    total_wall_net = sum(wall_net.values())
    total_window = sum(window.values())

    floor_area_m2 = atemp_override if atemp_override is not None else fp_area * num_floors

    if atemp_override is not None and num_floors > 0:
        perim_per_floor = atemp_override / num_floors
        roof_area_m2 = min(perim_per_floor, fp_area)
        ground_area_m2 = min(perim_per_floor, fp_area)
    else:
        roof_area_m2 = fp_area
        ground_area_m2 = fp_area

    uv = _resolve_u_values(p)

    # Mechanical ventilation: l/s per m² → ACH at floor_height ceiling
    ach_vent = p.mech_vent_l_s_m2 * 3.6 / floor_height

    # Heat-recovery efficiency: mirrors hvac._VENT_RECOVERY (FTX=0.65, else=0.0).
    vent_sys = p.ventilation_system.upper()
    hrv_eff_default = 0.65 if "FTX" in vent_sys else 0.0

    # Annual-average internal gains [W/m²] — used as a fallback and to set
    # Building5R1C.internal_gains_w_per_m2 (consumed by simulate_with_epw when
    # internal_gains array is None).
    avg_gains_w_m2 = (
        80.0 * p.occupant_density * (14.0 / 24.0)
        + p.equipment_w_m2
        + p.lighting_w_m2
        + p.bldg_services_w_m2
    )

    # Wrapper defaults — every entry can be overridden via engine_options.
    bldg_kwargs: dict = {
        "floor_area_m2": floor_area_m2,
        "u_walls": uv["u_wall"],
        "u_roof": uv["u_roof"],
        "u_floor": uv["u_floor"],
        "u_windows": uv["u_window"],
        "wall_area_m2": total_wall_net,
        "roof_area_m2": roof_area_m2,
        "floor_area_ground_m2": ground_area_m2,
        "window_area_m2": total_window,
        "window_area_south": window["south"],
        "window_area_north": window["north"],
        "window_area_east": window["east"],
        "window_area_west": window["west"],
        "building_height_m": total_wall_height,
        # ceiling_height_m drives zone volume in 5R1C: floor_area × ceiling_h.
        # Must match the floor-to-floor height used everywhere else.
        "ceiling_height_m": floor_height,
        "ach_infiltration": p.infiltration_ach,
        "ach_ventilation": ach_vent,
        "heat_recovery_efficiency": hrv_eff_default,
        "g_value": uv["g_value"],
        # SimpleGlazingSys SHGC already accounts for frame → frame_factor=1.0
        # so solar isn't multiplied by an extra 0.7.
        "frame_factor": 1.0,
        "shading_factor": 1.0,  # Sveby shading folded into g_value above
        "t_set_heating": p.t_heating,
        "t_set_cooling": p.t_cooling,
        "internal_gains_w_per_m2": avg_gains_w_m2,
        # Concrete-frame Swedish housing → HEAVY thermal mass (260 kJ/m²K)
        # instead of the SweThermalModel MEDIUM default (165).
        "thermal_capacitance_j_m2k": 260_000,
    }

    # Friendly alias: hrv_efficiency → heat_recovery_efficiency
    if "hrv_efficiency" in opts:
        bldg_kwargs["heat_recovery_efficiency"] = opts.pop("hrv_efficiency")

    bldg_kwargs.update(opts)
    bldg = Building5R1C(**bldg_kwargs)

    # Hourly Sveby internal-gains schedule (matches EPlus blended program).
    if use_sveby_schedule:
        gains_array = _sveby_internal_gains_array(
            occupant_density=p.occupant_density,
            equipment_w_m2=p.equipment_w_m2,
            lighting_w_m2=p.lighting_w_m2,
            bldg_services_w_m2=p.bldg_services_w_m2,
            floor_area_m2=floor_area_m2,
        )
        import numpy as np
        res = bldg.simulate_with_epw(weather_file, internal_gains=np.asarray(gains_array))
    else:
        res = bldg.simulate_with_epw(weather_file)

    heating_kwh = float(res["heating_demand_kwh"])
    cooling_kwh = float(res.get("cooling_demand_kwh", 0.0))
    dhw_kwh = p.dhw_kwh_m2 * floor_area_m2

    log.info(
        "5R1C '%s': Atemp=%.0f m²  heating=%.0f kWh (%.1f kWh/m²)  cooling=%.0f kWh",
        name, floor_area_m2, heating_kwh, heating_kwh / max(1, floor_area_m2), cooling_kwh,
    )
    return {
        "heating_kwh": heating_kwh,
        "cooling_kwh": cooling_kwh,
        "dhw_kwh": dhw_kwh,
        "site_kwh": heating_kwh + cooling_kwh,
    }


def _parse_sql_results(sql_path: Path) -> dict[str, float]:
    con = sqlite3.connect(sql_path)
    cur = con.cursor()

    cur.execute(
        """
        SELECT VariableName, SUM(VariableValue)
        FROM ReportVariableData rv
        JOIN ReportVariableDataDictionary d
          ON rv.ReportVariableDataDictionaryIndex = d.ReportVariableDataDictionaryIndex
        WHERE VariableName IN (
          'Zone Ideal Loads Zone Total Heating Energy',
          'Zone Ideal Loads Zone Total Cooling Energy',
          'Water Use Equipment Heating Energy'
        )
        GROUP BY VariableName
        """
    )

    heating_j = 0.0
    cooling_j = 0.0
    dhw_j = 0.0
    for var_name, total_j in cur.fetchall():
        try:
            v = float(total_j)
        except (TypeError, ValueError):
            continue
        if var_name == "Zone Ideal Loads Zone Total Heating Energy":
            heating_j += v
        elif var_name == "Zone Ideal Loads Zone Total Cooling Energy":
            cooling_j += v
        elif var_name == "Water Use Equipment Heating Energy":
            dhw_j += v

    heating_gj = heating_j / 1e9
    cooling_gj = cooling_j / 1e9
    dhw_gj = dhw_j / 1e9

    cur.execute(
        """
        SELECT Value
        FROM TabularDataWithStrings
        WHERE ReportName = 'AnnualBuildingUtilityPerformanceSummary'
          AND TableName = 'Site and Source Energy'
          AND RowName = 'Total Site Energy'
          AND ColumnName = 'Total Energy'
        """
    )

    row = cur.fetchone()
    site_gj = heating_gj + cooling_gj
    if row:
        try:
            site_gj = float(row[0])
        except (TypeError, ValueError):
            pass
    con.close()

    gj_to_kwh = 277.7777777778
    return {
        "heating_kwh": heating_gj * gj_to_kwh,
        "cooling_kwh": cooling_gj * gj_to_kwh,
        "dhw_kwh": dhw_gj * gj_to_kwh,
        "site_kwh": site_gj * gj_to_kwh,
    }


def run(
    name: str,
    footprint_pts: list[list[float]],
    params: BuildingParams,
    weather_file: Path,
    idf_dir: Path | None = None,
    output_dir: Path | None = None,
    energyplus_cmd: str = "energyplus",
    context_shades=None,
    engine: str = "energyplus",
    atemp_override: float | None = None,
    engine_options: dict | None = None,
) -> dict[str, float]:
    """Simulate a building and return ``{heating_kwh, cooling_kwh, dhw_kwh, site_kwh}``.

    Args:
        engine: ``"energyplus"`` (default — full EnergyPlus via Honeybee) or
                ``"5r1c"`` (fast ISO 13790 5R1C via SweThermalModel).
                When ``"5r1c"``, ``idf_dir`` and ``output_dir`` are not used.
        atemp_override: Heated floor area for the 5R1C engine (m²).  When
                ``apartment_depth > 0`` pass ``BuildingRooms.perimeter_floor_area``
                so the 5R1C heated area matches the EnergyPlus Atemp_sim.
        engine_options: Engine-specific overrides.  For ``engine="5r1c"`` any
                key maps to a ``Building5R1C`` constructor argument; commonly
                used keys are ``hrv_efficiency``, ``thermal_capacitance_j_m2k``,
                ``frame_factor``, ``shading_factor``, ``use_sveby_schedule``.
    """
    if engine == "5r1c":
        return _run_5r1c(
            name, footprint_pts, params, weather_file,
            atemp_override=atemp_override,
            engine_options=engine_options,
        )
    if idf_dir is None or output_dir is None:
        raise ValueError("idf_dir and output_dir are required for engine='energyplus'")
    
    log.info("Simulation '%s': %d floors, floor_height=%.1fm, construction=%s, ventilation=%s",
             name, params.num_floors, params.floor_height,
             params.construction_set, params.ventilation_system)
    log.info("Footprint: %d vertices, weather: %s",
             len(footprint_pts), weather_file.name)
    if context_shades:
        log.info("Context shading: %d shade surfaces", len(context_shades))
    idf_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    idf_path = idf_dir / "in.idf"
    write_idf(idf_path, name, footprint_pts, params, context_shades=context_shades)

    # --- Run EnergyPlus via Honeybee (handles ExpandObjects via -x) -------
    sql, _zsz, _rdd, _html, err = run_idf(
        str(idf_path.resolve()),
        str(weather_file.resolve()),
        expand_objects=True,
    )

    # --- Collect outputs --------------------------------------------------
    # run_idf writes outputs next to the IDF; copy them to output_dir
    sim_dir = output_dir / "sim"
    sim_dir.mkdir(exist_ok=True)
    src_dir = idf_path.parent
    for f in src_dir.iterdir():
        if f.name.startswith("eplusout") or f.name == "sqlite.err":
            shutil.copy2(f, sim_dir / f.name)

    results: dict[str, float] = {
        "heating_kwh": float("nan"),
        "cooling_kwh": float("nan"),
        "dhw_kwh": float("nan"),
        "site_kwh": float("nan"),
    }

    sql_path = Path(sql) if sql else sim_dir / "eplusout.sql"
    if sql_path.exists():
        results.update(_parse_sql_results(sql_path))
    else:
        # Check if err file indicates problems
        err_path = Path(err) if err else sim_dir / "eplusout.err"
        if err_path.exists():
            err_text = err_path.read_text()
            if "Fatal" in err_text:
                raise RuntimeError(
                    f"EnergyPlus failed.\n{err_text[-500:]}"
                )

    log.info("Results: heating=%.0f kWh, cooling=%.0f kWh, DHW=%.0f kWh, site=%.0f kWh",
             results["heating_kwh"], results["cooling_kwh"],
             results["dhw_kwh"], results["site_kwh"])
    return results


def simulate_building(
    building,
    *,
    idf_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    engine: str = "energyplus",
    context_shades=None,
    atemp_override: float | None = None,
    engine_options: dict | None = None,
    keep_hourly: bool = True,
):
    """Run a :class:`~pbgenerator.building.Building` and return BuildingResults.

    Unlike :func:`run` (which returns a flat kWh dict), this builds the full
    typed, unit-aware :class:`~pbgenerator.results.BuildingResults` — retaining
    every EnergyPlus reported variable as an hourly time series plus monthly
    aggregates and EUI — and is the engine behind ``Building.simulate``.
    """
    from .results import BuildingResults

    params = building.params
    weather_file = building.location.epw_path
    if weather_file is None:
        raise ValueError("Building location has no weather/EPW file set")
    weather_file = Path(weather_file)

    # --- 5R1C fast path (metrics only) -----------------------------------
    if engine == "5r1c":
        metrics = _run_5r1c(
            building.name, building.footprint_pts, params, weather_file,
            atemp_override=atemp_override, engine_options=engine_options,
        )
        atemp = atemp_override or building.heated_floor_area_m2
        return BuildingResults.from_metrics(metrics, engine="5r1c", atemp_m2=atemp)

    if idf_dir is None or output_dir is None:
        raise ValueError("idf_dir and output_dir are required for engine='energyplus'")
    idf_dir = Path(idf_dir)
    output_dir = Path(output_dir)
    idf_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build geometry once and reuse it for both the IDF and the heated area.
    model = building.build_model(context_shades=context_shades)
    idf_path = idf_dir / "in.idf"
    write_idf(idf_path, building.name, building.footprint_pts, params,
              context_shades=context_shades, model=model)

    sql, _zsz, _rdd, _html, err = run_idf(
        str(idf_path.resolve()),
        str(weather_file.resolve()),
        expand_objects=True,
    )

    sim_dir = output_dir / "sim"
    sim_dir.mkdir(exist_ok=True)
    for f in idf_path.parent.iterdir():
        if f.name.startswith("eplusout") or f.name == "sqlite.err":
            shutil.copy2(f, sim_dir / f.name)

    sql_path = Path(sql) if sql else sim_dir / "eplusout.sql"
    if not sql_path.exists():
        err_path = Path(err) if err else sim_dir / "eplusout.err"
        if err_path.exists() and "Fatal" in err_path.read_text():
            raise RuntimeError(f"EnergyPlus failed.\n{err_path.read_text()[-500:]}")
        raise RuntimeError(f"EnergyPlus produced no SQL output at {sql_path}")

    atemp = atemp_override or building.heated_floor_area_m2
    results = BuildingResults.from_energyplus_sql(
        sql_path, atemp_m2=atemp, keep_hourly=keep_hourly, build_monthly=keep_hourly,
    )
    results.artifacts["idf"] = str(idf_path)
    if err:
        results.artifacts["err"] = str(err)

    site_eui = results.site_eui.value if results.site_eui else float("nan")
    log.info(
        "Results: heating=%.0f kWh, cooling=%.0f kWh, DHW=%.0f kWh, site=%.0f kWh (EUI=%.1f kWh/m2)",
        results.heating.value, results.cooling.value,
        results.dhw.value, results.site_energy.value, site_eui,
    )
    return results
