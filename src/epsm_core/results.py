"""Validated hourly EnergyPlus SQL results, retaining every requested signal."""

import sqlite3
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import numpy as np

from .compiler import ENERGY_VARIABLES


@dataclass(frozen=True)
class SimulationResult:
    run_id: str
    scalars: dict[str, float]
    hourly: dict[str, np.ndarray]
    units: dict[str, str]
    diagnostics: dict
    artifacts: dict[str, str]


def read_results(sql_path, spec, report, diagnostics):
    hourly, units, annual = {}, {}, {}
    with sqlite3.connect(sql_path) as db:
        definitions = {
            row[0]: row[1:]
            for row in db.execute(
                "SELECT ReportDataDictionaryIndex, Name, KeyValue, Units, ReportingFrequency FROM ReportDataDictionary WHERE IsMeter=0"
            ).fetchall()
        }
        rows = db.execute(
            """SELECT d.ReportDataDictionaryIndex,d.Value FROM ReportData d JOIN Time t ON t.TimeIndex=d.TimeIndex
                JOIN EnvironmentPeriods e ON e.EnvironmentPeriodIndex=t.EnvironmentPeriodIndex
                WHERE COALESCE(t.WarmupFlag,0)=0 AND e.EnvironmentType=3
                ORDER BY d.ReportDataDictionaryIndex,t.TimeIndex"""
        )
        for index, grouped in groupby(rows, key=lambda r: r[0]):
            values = np.fromiter((r[1] for r in grouped), dtype=float)
            if index not in definitions:
                continue
            name, key, unit, frequency = definitions[index]
            signal = f"{name}::{key}"
            if frequency.lower() == "hourly":
                if len(values) != 8760 or not np.isfinite(values).all():
                    raise ValueError(f"Invalid hourly signal {signal}: {len(values)} samples")
                hourly[signal], units[signal] = values, unit
            elif frequency.lower() in ("run period", "runperiod"):
                annual[name] = annual.get(name, 0) + values.sum()
    if not hourly:
        raise ValueError("SQL contains no hourly results")
    scalar = {}
    for name, output in zip(
        ENERGY_VARIABLES, ("space_heating_demand", "cooling_demand", "dhw_load")
    ):
        signals = [v for k, v in hourly.items() if k.startswith(name + "::")]
        if not signals:
            raise ValueError(f"Missing required EnergyPlus signal: {name}")
        values = np.sum(signals, axis=0) / 3.6e6
        if np.any(values < -1e-6):
            raise ValueError(f"Negative energy in {name}")
        total = float(values.sum())
        if name not in annual or not np.isclose(total, annual[name] / 3.6e6, rtol=0.001, atol=1e-6):
            raise ValueError(f"Annual/hourly disagreement for {name}")
        scalar[output + "_kwh"] = total
        scalar[output + "_eui_kwh_m2"] = total / spec.geometry.conditioned_floor_area_m2
        hourly[output + "_kwh"] = values
        units[output + "_kwh"] = "kWh"
    scalar["ideal_thermal_load_kwh"] = scalar["space_heating_demand_kwh"] + scalar["dhw_load_kwh"]
    scalar["ideal_thermal_load_eui_kwh_m2"] = (
        scalar["ideal_thermal_load_kwh"] / spec.geometry.conditioned_floor_area_m2
    )
    hourly["ideal_thermal_load_kwh"] = hourly["space_heating_demand_kwh"] + hourly["dhw_load_kwh"]
    units["ideal_thermal_load_kwh"] = "kWh"
    return SimulationResult(
        report.run_id,
        scalar,
        hourly,
        units,
        diagnostics,
        {"sql": str(sql_path), "err": str(Path(sql_path).with_suffix(".err"))},
    )
