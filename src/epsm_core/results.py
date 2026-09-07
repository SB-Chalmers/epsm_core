# File: results.py
# Purpose: Validated hourly EnergyPlus SQL results, retaining every requested signal.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document results interfaces, examples, constraints and processing rationale.

"""Validated hourly EnergyPlus SQL results, retaining every requested signal.

Notes
-----
SQL extraction excludes warmup and non-weather environments, checks every hourly
calendar and reconciles requested annual energy sums. Raw signals retain their reported
units; derived demand uses kWh. Missing ground-conduction evidence prevents acceptance.

Examples
--------
Example::

    from epsm_core.results import SimulationResult

    result = SimulationResult("example", {}, {}, {}, {}, {})
"""

import sqlite3
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import numpy as np

from .compiler import ENERGY_VARIABLES
from .weather import hourly_axis


@dataclass(frozen=True)
class SimulationResult:
    """Validated hourly simulation data with scalar summaries and artifact references.

    Attributes
    ----------
    run_id : str
        Content-derived run identity including compiler, engine and physical inputs.
        Required at construction.
    scalars : dict[str, float]
        Named annual/aggregate results and execution metrics.  Required at construction.
    hourly : dict[str, np.ndarray]
        Named hourly NumPy arrays; original EnergyPlus signals retain their native units.
        Required at construction.
    units : dict[str, str]
        Unit labels keyed by signal/result name.  Required at construction.
    diagnostics : dict
        Structured acceptance decisions and original diagnostic evidence.  Required at
        construction.
    artifacts : dict[str, str]
        Explicit paths to retained output artifacts.  Required at construction.
    time_axis : np.ndarray | None
        Optional datetime64[h] local-standard-time hour-start labels.  Default: ``None``.

    Notes
    -----
    The dataclass is frozen, but contained dictionaries and arrays remain mutable; the
    runner adds downstream delivery/PV outputs after SQL parsing. Raw signals retain
    original units and derived energy arrays use kWh.

    Examples
    --------
    Example::

        from epsm_core.results import SimulationResult

        result = SimulationResult("example", {}, {}, {}, {}, {})
    """

    run_id: str
    scalars: dict[str, float]
    hourly: dict[str, np.ndarray]
    units: dict[str, str]
    diagnostics: dict
    artifacts: dict[str, str]
    time_axis: np.ndarray | None = None


def read_results(sql_path, spec, report, diagnostics):
    """Read and reconcile annual and hourly EnergyPlus SQL signals.

    Parameters
    ----------
    sql_path : str or Path
        Completed EnergyPlus SQLite output file.
    spec : BuildingSpec
        Validated building input; geometry-only helpers also accept an object exposing the
        fields they consume.
    report : CompilationReport or dict
        Compilation metadata; SQL/compiler consumers use CompilationReport, viewer_data uses
        its decoded data mapping.
    diagnostics : dict
        Structured acceptance decisions and original diagnostic evidence.

    Returns
    -------
    SimulationResult
        Original signals plus derived energy totals and time axis.

    Raises
    ------
    ValueError
        Rejected conditions: SQL contains no hourly results; Missing ground-contact surface
        conduction output.

    Notes
    -----
    Requires a completed SQL artifact, matching specification and CompilationReport. Warmup
    and non-weather environments are excluded. Every hourly signal must cover the exact
    calendar; Joules are converted to kWh and annual sums checked at relative 0.001
    tolerance.

    Examples
    --------
    Supply a validated BuildingSpec as ``building``; the matching CompilationReport as
    ``report``; parsed diagnostic evidence as ``diagnostics``. Replace example paths with
    existing local inputs; output paths must be writable.

    Example::

        from epsm_core.results import read_results

        result = read_results("output/run/eplusout.sql", building, report, diagnostics)
    """

    # 1. Read and reconcile annual and hourly EnergyPlus SQL signals.
    from datetime import datetime, timedelta

    hourly, units, annual = {}, {}, {}
    axis = hourly_axis(spec.climate.calendar_year)
    start = datetime(spec.climate.calendar_year, 1, 1)
    # Compare the exact SQL calendar for every signal without repeatedly converting
    # millions of Python datetimes in detailed multi-zone models.
    expected_calendar = []
    for hour in range(spec.climate.hours_in_year):
        stamp = start + timedelta(hours=hour)
        expected_calendar.append((stamp.month, stamp.day, stamp.hour + 1, 0, 60))
    # 2. Select weather-run rows only, excluding warmup and preserving per-signal time order.
    # NOTE: sqlite3 can create a missing path; callers must supply an existing completed SQL file.
    with sqlite3.connect(sql_path) as db:
        definitions = {
            row[0]: row[1:]
            for row in db.execute(
                "SELECT ReportDataDictionaryIndex, Name, KeyValue, Units, ReportingFrequency FROM ReportDataDictionary WHERE IsMeter=0"
            ).fetchall()
        }
        rows = db.execute(
            """SELECT d.ReportDataDictionaryIndex,d.Value,t.Month,t.Day,t.Hour,t.Minute,t.Interval FROM ReportData d JOIN Time t ON t.TimeIndex=d.TimeIndex
                JOIN EnvironmentPeriods e ON e.EnvironmentPeriodIndex=t.EnvironmentPeriodIndex
                WHERE COALESCE(t.WarmupFlag,0)=0 AND e.EnvironmentType=3
                ORDER BY d.ReportDataDictionaryIndex,t.TimeIndex"""
        )
        for index, grouped in groupby(rows, key=lambda r: r[0]):
            records = list(grouped)
            values = np.array([r[1] for r in records], dtype=float)
            if index not in definitions:
                continue
            name, key, unit, frequency = definitions[index]
            signal = f"{name}::{key}"
            if frequency.lower() == "hourly":
                if len(values) != spec.climate.hours_in_year or not np.isfinite(values).all():
                    raise ValueError(f"Invalid hourly signal {signal}: {len(values)} samples")
                if any(row[2:] != expected for row, expected in zip(records, expected_calendar)):
                    raise ValueError(
                        f"Missing, repeated, non-hourly or unordered calendar hours: {signal}"
                    )
                hourly[signal], units[signal] = values, unit
            elif frequency.lower() in ("run period", "runperiod"):
                annual[name] = annual.get(name, 0) + values.sum()
    # 3. Require actual hourly output before deriving aggregate demand.
    if not hourly:
        raise ValueError("SQL contains no hourly results")
    # 4. Convert Joules to kWh and independently reconcile annual totals for each demand signal.
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
        scalar[output + "_eui_kwh_m2"] = total / report.data["conditioned_floor_area_m2"]
        hourly[output + "_kwh"] = values
        units[output + "_kwh"] = "kWh"
    scalar["ideal_thermal_load_kwh"] = scalar["space_heating_demand_kwh"] + scalar["dhw_load_kwh"]
    scalar["ideal_thermal_load_eui_kwh_m2"] = (
        scalar["ideal_thermal_load_kwh"] / report.data["conditioned_floor_area_m2"]
    )
    hourly["ideal_thermal_load_kwh"] = hourly["space_heating_demand_kwh"] + hourly["dhw_load_kwh"]
    units["ideal_thermal_load_kwh"] = "kWh"
    # 5. Require conduction evidence for every reported ground-contact surface.
    ground_names = {f["surface"].upper() for f in report.data["ground_surfaces"]}
    ground = [
        v / 3.6e6
        for key, v in hourly.items()
        if key.startswith("Surface Inside Face Conduction Heat Transfer Energy::")
        and key.split("::", 1)[1] in ground_names
    ]
    if len(ground) != len(ground_names):
        raise ValueError("Missing ground-contact surface conduction output")
    scalar["annual_absolute_ground_transfer_kwh"] = float(sum(np.abs(v).sum() for v in ground))
    return SimulationResult(
        report.run_id,
        scalar,
        hourly,
        units,
        diagnostics,
        {"sql": str(sql_path), "err": str(Path(sql_path).with_suffix(".err"))},
        time_axis=axis,
    )
