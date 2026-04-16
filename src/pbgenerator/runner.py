from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

from honeybee_energy.run import run_idf

from .building_params import BuildingParams
from .idf_builder import write_idf


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
    idf_dir: Path,
    output_dir: Path,
    energyplus_cmd: str = "energyplus",
    context_shades=None,
) -> dict[str, float]:
    """Write an IDF, run EnergyPlus via Honeybee, and return energy results."""
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
