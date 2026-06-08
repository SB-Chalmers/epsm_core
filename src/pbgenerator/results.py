"""Typed, unit-aware simulation results for a building.

Replaces the previous loose ``dict[str, float]`` returned by the runner.  A
:class:`BuildingResults` retains:

* annual scalar metrics (heating/cooling/DHW/site energy and EUI) as
  :class:`~pbgenerator.units.Quantity` values with explicit units;
* every EnergyPlus *reported variable* as an hourly (or sub-hourly)
  :class:`~pbgenerator.units.TimeSeries`, including zone air temperatures;
* monthly aggregates derived from the hourly series;
* optional EPC-comparable metrics and PV production results.

The :meth:`BuildingResults.from_energyplus_sql` constructor reads the full
``ReportVariableData`` table so nothing the IDF requested is thrown away.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .series import (
    FloorResults,
    ZoneCollection,
    _SignalHost,
    build_floors,
    build_zones,
)
from .units import (
    DEG_C,
    GJ,
    J,
    KWH,
    KWH_PER_M2,
    Quantity,
    TimeSeries,
)

log = logging.getLogger(__name__)

_GJ_TO_KWH = 277.7777777778
_J_TO_KWH = 1.0 / 3.6e6

# EnergyPlus variable names whose annual sums map onto the headline metrics.
_HEATING_VAR = "Zone Ideal Loads Zone Total Heating Energy"
_COOLING_VAR = "Zone Ideal Loads Zone Total Cooling Energy"
_DHW_VAR = "Water Use Equipment Heating Energy"
_ZONE_TEMP_VAR = "Zone Mean Air Temperature"


@dataclass
class BuildingResults(_SignalHost):
    """Container for one simulation's outputs, with units on every field."""

    engine: str = "energyplus"

    # Headline annual metrics.
    heating: Quantity = field(default_factory=lambda: Quantity(float("nan"), KWH))
    cooling: Quantity = field(default_factory=lambda: Quantity(float("nan"), KWH))
    dhw: Quantity = field(default_factory=lambda: Quantity(float("nan"), KWH))
    site_energy: Quantity = field(default_factory=lambda: Quantity(float("nan"), KWH))

    # Normalised metrics (populated when a heated floor area is known).
    heating_eui: Quantity | None = None
    cooling_eui: Quantity | None = None
    site_eui: Quantity | None = None
    atemp_m2: float | None = None

    # Full time-series store, keyed by "<VariableName>::<KeyValue>".
    hourly: dict[str, TimeSeries] = field(default_factory=dict)
    monthly: dict[str, TimeSeries] = field(default_factory=dict)

    # Optional add-ons.
    epc_comparison: dict | None = None
    pv: "object | None" = None  # PVResults, kept loose to avoid import cycle

    # Raw artifact locations (sql, err, idf) for traceability.
    artifacts: dict[str, str] = field(default_factory=dict)

    # -- convenience accessors --------------------------------------------

    def zone_temperatures(self) -> dict[str, TimeSeries]:
        """Return hourly mean-air-temperature series keyed by zone."""
        return {
            k.split("::", 1)[1] if "::" in k else k: ts
            for k, ts in self.hourly.items()
            if ts.name == _ZONE_TEMP_VAR
        }

    def variable(self, name: str, key: str = "") -> TimeSeries | None:
        """Look up a single hourly series by EnergyPlus variable name (+ key)."""
        if key:
            return self.hourly.get(f"{name}::{key}")
        # Return the first matching variable regardless of key.
        for k, ts in self.hourly.items():
            if ts.name == name:
                return ts
        return None

    # -- friendly, keyless time-series access -----------------------------

    def _series_for(self, variable: str) -> list[TimeSeries]:
        """All per-zone hourly series for one EnergyPlus variable name."""
        return [ts for ts in self.hourly.values() if ts.name == variable]

    @property
    def zones(self) -> ZoneCollection:
        """Per-zone views, addressable by index or zone name.

        Example::

            res.zones[0].air_temperature.hourly
            res.zones["FLOOR1_ROOM_..."].lighting.monthly
        """
        return build_zones(self.hourly)

    @property
    def floors(self) -> list[FloorResults]:
        """Per-floor views (zones grouped by storey), each aggregating its zones.

        Example::

            res.floors[0].zones[1].air_temperature.hourly
            res.floors[0].heating_load.annual
        """
        return build_floors(self.hourly)

    def as_dict(self) -> dict[str, float]:
        """Backwards-compatible flat metrics dict (kWh)."""
        return {
            "heating_kwh": self.heating.value,
            "cooling_kwh": self.cooling.value,
            "dhw_kwh": self.dhw.value,
            "site_kwh": self.site_energy.value,
        }

    def compute_eui(self, atemp_m2: float) -> None:
        """Populate the EUI quantities from a heated floor area (m²)."""
        if not atemp_m2 or atemp_m2 <= 0:
            return
        self.atemp_m2 = float(atemp_m2)
        self.heating_eui = Quantity(self.heating.value / atemp_m2, KWH_PER_M2)
        self.cooling_eui = Quantity(self.cooling.value / atemp_m2, KWH_PER_M2)
        self.site_eui = Quantity(self.site_energy.value / atemp_m2, KWH_PER_M2)

    def build_monthly(self) -> None:
        """Derive 12-month aggregates from the stored hourly series.

        Energy fluxes (unit J/Wh/kWh) are summed; temperatures (degC) and
        other intensive quantities are averaged.
        """
        self.monthly = {}
        for k, ts in self.hourly.items():
            if ts.timestep != "hourly" or len(ts) != 8760:
                continue
            try:
                if ts.unit in (J, "Wh", KWH, "W"):
                    self.monthly[k] = ts.to_monthly()
                else:
                    self.monthly[k] = ts.to_monthly_mean()
            except ValueError:
                continue

    # -- constructors ------------------------------------------------------

    @classmethod
    def from_energyplus_sql(
        cls,
        sql_path: str | Path,
        *,
        atemp_m2: float | None = None,
        keep_hourly: bool = True,
        build_monthly: bool = True,
    ) -> "BuildingResults":
        """Build a full results object from an ``eplusout.sql`` file."""
        sql_path = Path(sql_path)
        res = cls(engine="energyplus")
        res.artifacts["sql"] = str(sql_path)

        con = sqlite3.connect(sql_path)
        cur = con.cursor()

        # 1) Headline annual energy sums (in Joules → kWh).
        cur.execute(
            """
            SELECT VariableName, SUM(VariableValue)
            FROM ReportVariableData rv
            JOIN ReportVariableDataDictionary d
              ON rv.ReportVariableDataDictionaryIndex = d.ReportVariableDataDictionaryIndex
            WHERE VariableName IN (?, ?, ?)
            GROUP BY VariableName
            """,
            (_HEATING_VAR, _COOLING_VAR, _DHW_VAR),
        )
        heating_j = cooling_j = dhw_j = 0.0
        for var_name, total in cur.fetchall():
            try:
                v = float(total)
            except (TypeError, ValueError):
                continue
            if var_name == _HEATING_VAR:
                heating_j += v
            elif var_name == _COOLING_VAR:
                cooling_j += v
            elif var_name == _DHW_VAR:
                dhw_j += v

        res.heating = Quantity(heating_j * _J_TO_KWH, KWH)
        res.cooling = Quantity(cooling_j * _J_TO_KWH, KWH)
        res.dhw = Quantity(dhw_j * _J_TO_KWH, KWH)

        # 2) Total site energy from the tabular summary (in GJ → kWh).
        site_gj = (heating_j + cooling_j) / 1e9
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
        if row:
            try:
                site_gj = float(row[0])
            except (TypeError, ValueError):
                pass
        res.site_energy = Quantity(site_gj * _GJ_TO_KWH, KWH)

        # 3) Full per-variable time series (every variable the IDF requested).
        if keep_hourly:
            res.hourly = _extract_all_series(cur)

        con.close()

        if atemp_m2:
            res.compute_eui(atemp_m2)
        if build_monthly and res.hourly:
            res.build_monthly()
        return res

    @classmethod
    def from_metrics(
        cls,
        metrics: dict[str, float],
        *,
        engine: str = "energyplus",
        atemp_m2: float | None = None,
    ) -> "BuildingResults":
        """Build a metrics-only results object (e.g. from the 5R1C engine)."""
        res = cls(
            engine=engine,
            heating=Quantity(metrics.get("heating_kwh", float("nan")), KWH),
            cooling=Quantity(metrics.get("cooling_kwh", float("nan")), KWH),
            dhw=Quantity(metrics.get("dhw_kwh", float("nan")), KWH),
            site_energy=Quantity(metrics.get("site_kwh", float("nan")), KWH),
        )
        if atemp_m2:
            res.compute_eui(atemp_m2)
        return res


def _extract_all_series(cur: sqlite3.Cursor) -> dict[str, TimeSeries]:
    """Read every reported variable from a connected E+ SQL cursor.

    Units are taken from ``ReportVariableDataDictionary.Units`` so each series
    is self-describing.  Series are returned keyed by
    ``"<VariableName>::<KeyValue>"``.
    """
    # Map each dictionary index to (name, key, unit, frequency).
    cur.execute(
        """
        SELECT ReportVariableDataDictionaryIndex,
               VariableName, KeyValue, VariableUnits, ReportingFrequency
        FROM ReportVariableDataDictionary
        """
    )
    meta: dict[int, tuple[str, str, str, str]] = {}
    for idx, name, key, units, freq in cur.fetchall():
        meta[int(idx)] = (
            name or "",
            key or "",
            (units or "").strip() or "-",
            (freq or "").strip().lower() or "hourly",
        )

    # Pull all sample values in time order for each dictionary index.
    cur.execute(
        """
        SELECT ReportVariableDataDictionaryIndex, VariableValue
        FROM ReportVariableData
        ORDER BY ReportVariableDataDictionaryIndex, TimeIndex
        """
    )
    buckets: dict[int, list[float]] = {}
    for idx, value in cur.fetchall():
        try:
            buckets.setdefault(int(idx), []).append(float(value))
        except (TypeError, ValueError):
            continue

    series: dict[str, TimeSeries] = {}
    for idx, values in buckets.items():
        name, key, unit, freq = meta.get(idx, ("", "", "-", "hourly"))
        # Normalise EnergyPlus unit label "C" → canonical "degC".
        canon_unit = DEG_C if unit in ("C", "degC", "Celsius") else unit
        ts = TimeSeries(values, canon_unit, freq, name=name, key=key)
        store_key = f"{name}::{key}" if key else name
        series[store_key] = ts
    return series


__all__ = ["BuildingResults"]
