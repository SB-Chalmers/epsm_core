"""Campaign-scale persistence: :class:`SimStore`.

A :class:`SimStore` is a single on-disk *campaign* that holds every simulation's
inputs, scalar results and full time series, designed for runs of ~10⁵
buildings feeding a machine-learning surrogate.

Layout (a directory)::

    <campaign>/
        runs.duckdb                 # one wide row per sim (params + scalar results)
        timeseries/
            run_id=<id>/data.parquet   # long-format, float32, zstd

* **runs.duckdb** — a DuckDB table ``runs`` with one column per scalar input
  and output (see :func:`pbgenerator.serialize.flatten_run`).  This is the
  feature/target table you load for training::

      df = store.read_runs()        # pandas DataFrame, one row per sim

* **timeseries/** — a Hive-partitioned Parquet dataset (partitioned by
  ``run_id``).  Each sim writes *its own* partition file, so parallel workers
  never contend for a lock.  Rows are long-format
  ``(run_id, variable, key, unit, timestep, t, value)`` with ``value`` stored
  as ``float32`` and zstd compression — per-zone × per-variable × 8760 samples
  compress to a few hundred KB per building.

Write paths are split so the two halves can run in different processes:

* :meth:`write_timeseries` touches *only* the filesystem (pyarrow) and is safe
  to call from a worker process.
* :meth:`upsert_run` writes the DuckDB row and should run in a single
  (main) process.
* :meth:`write` does both, for serial / single-process use.

``run_id`` is the SHA-1 of the building's *input* description
(:func:`serialize.building_to_dict` with ``include_results=False``), so the
same inputs always map to the same id — making :meth:`has_run` a reliable
resume / dedupe check.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .serialize import building_to_dict, flatten_run, to_json
from .units import TimeSeries

if TYPE_CHECKING:  # pragma: no cover - typing only
    import duckdb
    import pandas as pd

    from .building import Building
    from .results import BuildingResults

log = logging.getLogger(__name__)

_RUNS_TABLE = "runs"
# run_id is supplied by the hive partition (timeseries/run_id=<id>/), so it is
# intentionally NOT a column in the file itself.
_TS_SCHEMA = pa.schema([
    ("variable", pa.string()),
    ("key", pa.string()),
    ("unit", pa.string()),
    ("timestep", pa.string()),
    ("t", pa.int32()),
    ("value", pa.float32()),
])


def compute_run_id(building: "Building") -> str:
    """Deterministic 16-char id from a building's *inputs* (not its results)."""
    payload = building_to_dict(building, include_results=False)
    blob = to_json(payload)  # default=str handles Paths; key order is stable
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


class SimStore:
    """A campaign store backing a large simulation sweep.

    Parameters
    ----------
    root:
        Directory for the campaign (created if missing).
    include_monthly:
        When ``True`` (default) monthly aggregates are persisted alongside the
        hourly series in the Parquet partitions.
    """

    def __init__(self, root: str | Path, *, include_monthly: bool = True) -> None:
        self.root = Path(root)
        self.ts_dir = self.root / "timeseries"
        self.runs_db = self.root / "runs.duckdb"
        self.include_monthly = include_monthly
        self.root.mkdir(parents=True, exist_ok=True)
        self.ts_dir.mkdir(parents=True, exist_ok=True)
        self._con: "duckdb.DuckDBPyConnection | None" = None

    # -- duckdb connection (lazy; main-process writer) --------------------

    @property
    def con(self) -> "duckdb.DuckDBPyConnection":
        if self._con is None:
            import duckdb

            self._con = duckdb.connect(str(self.runs_db))
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> "SimStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __getstate__(self) -> dict:
        # Never ship a live DuckDB connection across a process boundary; workers
        # only ever call write_timeseries/stage (filesystem, no DB).
        state = self.__dict__.copy()
        state["_con"] = None
        return state

    # -- time series (filesystem only; worker-safe) -----------------------

    def timeseries_path(self, run_id: str) -> Path:
        return self.ts_dir / f"run_id={run_id}" / "data.parquet"

    def write_timeseries(self, run_id: str, results: "BuildingResults") -> Path:
        """Write one run's full time series to its Parquet partition.

        Safe to call from a worker process (pyarrow only, no DB).  Overwrites
        any existing partition for ``run_id``.
        """
        series: list[tuple[str, TimeSeries]] = list(results.hourly.items())
        if self.include_monthly:
            series += [(f"monthly::{k}", ts) for k, ts in results.monthly.items()]

        variables: list[str] = []
        keys: list[str] = []
        units: list[str] = []
        timesteps: list[str] = []
        t_idx: list[int] = []
        values: list[float] = []
        for _store_key, ts in series:
            n = len(ts.values)
            if n == 0:
                continue
            variables.extend([ts.name] * n)
            keys.extend([ts.key] * n)
            units.extend([ts.unit] * n)
            timesteps.extend([ts.timestep] * n)
            t_idx.extend(range(n))
            values.extend(ts.values)

        table = pa.table(
            {
                "variable": pa.array(variables, pa.string()),
                "key": pa.array(keys, pa.string()),
                "unit": pa.array(units, pa.string()),
                "timestep": pa.array(timesteps, pa.string()),
                "t": pa.array(np.asarray(t_idx, dtype=np.int32)),
                "value": pa.array(np.asarray(values, dtype=np.float32)),
            },
            schema=_TS_SCHEMA,
        )
        path = self.timeseries_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="zstd", use_dictionary=True)
        return path

    def read_timeseries(self, run_id: str) -> dict[str, TimeSeries]:
        """Reconstruct one run's *hourly* (native) series, keyed ``"<variable>::<key>"``.

        Derived monthly aggregates are excluded here; use :meth:`read_results`
        to get the full :class:`BuildingResults` with both hourly and monthly.
        """
        out: dict[str, TimeSeries] = {}
        for ts in self._read_all_series(run_id):
            if ts.timestep == "monthly":
                continue
            out[f"{ts.name}::{ts.key}" if ts.key else ts.name] = ts
        return out

    def read_results(self, run_id: str) -> "BuildingResults":
        """Reconstruct a :class:`BuildingResults` (hourly + monthly) for a run.

        Scalar metrics (heating/cooling/EUI …) are read back from the ``runs``
        table when present, so the returned object mirrors the original.
        """
        from .results import BuildingResults

        res = BuildingResults()
        for ts in self._read_all_series(run_id):
            key = f"{ts.name}::{ts.key}" if ts.key else ts.name
            if ts.timestep == "monthly":
                res.monthly[key] = ts
            else:
                res.hourly[key] = ts
        self._apply_scalar_metrics(res, run_id)
        return res

    def _read_all_series(self, run_id: str) -> list[TimeSeries]:
        """Every stored series for a run (hourly + monthly), as TimeSeries."""
        path = self.timeseries_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No time series stored for run_id={run_id!r}")
        cols = pq.ParquetFile(path).read().to_pydict()
        out: list[TimeSeries] = []
        n = len(cols["value"])
        i = 0
        while i < n:
            name = cols["variable"][i]
            key = cols["key"][i]
            unit = cols["unit"][i]
            timestep = cols["timestep"][i]
            j = i
            vals: list[float] = []
            while (
                j < n
                and cols["variable"][j] == name
                and cols["key"][j] == key
                and cols["timestep"][j] == timestep
            ):
                vals.append(cols["value"][j])
                j += 1
            out.append(TimeSeries(vals, unit, timestep, name=name, key=key))
            i = j
        return out

    def _apply_scalar_metrics(self, res: "BuildingResults", run_id: str) -> None:
        """Populate headline metrics on *res* from the stored ``runs`` row."""
        from .units import KWH, KWH_PER_M2, Quantity

        if not self.has_run(run_id):
            return
        row = self.con.execute(
            f"SELECT heating_kwh, cooling_kwh, dhw_kwh, site_kwh, "
            f"heating_eui, cooling_eui, site_eui, atemp_m2 "
            f"FROM {_RUNS_TABLE} WHERE run_id = ? LIMIT 1",
            [run_id],
        ).fetchone()
        if not row:
            return
        heating, cooling, dhw, site, h_eui, c_eui, s_eui, atemp = row
        if heating is not None:
            res.heating = Quantity(heating, KWH)
        if cooling is not None:
            res.cooling = Quantity(cooling, KWH)
        if dhw is not None:
            res.dhw = Quantity(dhw, KWH)
        if site is not None:
            res.site_energy = Quantity(site, KWH)
        if h_eui is not None:
            res.heating_eui = Quantity(h_eui, KWH_PER_M2)
        if c_eui is not None:
            res.cooling_eui = Quantity(c_eui, KWH_PER_M2)
        if s_eui is not None:
            res.site_eui = Quantity(s_eui, KWH_PER_M2)
        if atemp is not None:
            res.atemp_m2 = float(atemp)

    def read_timeseries_frame(self, run_id: str | None = None) -> "pd.DataFrame":
        """Long-format time series as a pandas DataFrame.

        ``run_id=None`` reads the whole campaign (all partitions); pass a
        specific id to read just that partition.
        """
        if run_id is not None:
            df = pq.ParquetFile(self.timeseries_path(run_id)).read().to_pandas()
            df.insert(0, "run_id", run_id)
            return df
        dataset = pq.ParquetDataset(self.ts_dir, partitioning="hive")
        return dataset.read().to_pandas()

    # -- runs table (duckdb; main-process writer) -------------------------

    def has_run(self, run_id: str) -> bool:
        if not self.runs_db.exists():
            return False
        exists = self.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
            [_RUNS_TABLE],
        ).fetchone()
        if not exists:
            return False
        row = self.con.execute(
            f"SELECT 1 FROM {_RUNS_TABLE} WHERE run_id = ? LIMIT 1", [run_id]
        ).fetchone()
        return row is not None

    def upsert_run(self, row: dict) -> None:
        """Insert (or replace) one scalar row in the ``runs`` table.

        The schema grows automatically: any column present in *row* but not yet
        in the table is added.  Replacing by ``run_id`` keeps writes idempotent
        for resumed campaigns.
        """
        import pandas as pd

        run_id = row.get("run_id")
        if not run_id:
            raise ValueError("row must include a 'run_id'")
        df = pd.DataFrame([row])
        con = self.con
        con.register("_incoming", df)
        try:
            tables = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [_RUNS_TABLE],
            ).fetchone()
            if not tables:
                con.execute(f"CREATE TABLE {_RUNS_TABLE} AS SELECT * FROM _incoming")
                return
            self._ensure_columns(df)
            con.execute(f"DELETE FROM {_RUNS_TABLE} WHERE run_id = ?", [run_id])
            con.execute(f"INSERT INTO {_RUNS_TABLE} BY NAME SELECT * FROM _incoming")
        finally:
            con.unregister("_incoming")

    def _ensure_columns(self, df: "pd.DataFrame") -> None:
        existing = {
            r[0]
            for r in self.con.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{_RUNS_TABLE}'"
            ).fetchall()
        }
        for col, dtype in df.dtypes.items():
            if col in existing:
                continue
            sql_type = _duckdb_type(dtype)
            self.con.execute(
                f'ALTER TABLE {_RUNS_TABLE} ADD COLUMN "{col}" {sql_type}'
            )

    def read_runs(self) -> "pd.DataFrame":
        """The whole ``runs`` table as a pandas DataFrame (features + targets)."""
        tables = self.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
            [_RUNS_TABLE],
        ).fetchone()
        if not tables:
            import pandas as pd

            return pd.DataFrame()
        return self.con.execute(f"SELECT * FROM {_RUNS_TABLE}").df()

    # alias: the runs table *is* the training table
    training_frame = read_runs

    def n_runs(self) -> int:
        tables = self.con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
            [_RUNS_TABLE],
        ).fetchone()
        if not tables:
            return 0
        return int(self.con.execute(f"SELECT COUNT(*) FROM {_RUNS_TABLE}").fetchone()[0])

    # -- combined write (serial / single-process) -------------------------

    def write(
        self,
        building: "Building",
        *,
        run_id: str | None = None,
        status: str = "ok",
        extra: dict | None = None,
    ) -> str:
        """Persist a simulated building's scalars *and* time series.

        Returns the ``run_id``.  Requires ``building.results`` to be populated
        (call ``building.simulate(...)`` first) for time series to be written.
        """
        rid = run_id or compute_run_id(building)
        if building.results is not None:
            self.write_timeseries(rid, building.results)
        row = self.run_row(building, run_id=rid, status=status, extra=extra)
        self.upsert_run(row)
        return rid

    def stage(
        self,
        building: "Building",
        *,
        status: str = "ok",
        extra: dict | None = None,
    ) -> dict:
        """Worker-side half of :meth:`write`: persist time series, return the row.

        Writes the building's time-series Parquet partition (filesystem only,
        no DB) and returns the flat ``runs`` row.  Safe to call inside a
        :class:`~concurrent.futures.ProcessPoolExecutor` worker; the returned
        row is small and is meant to be handed back to the main process, which
        calls :meth:`upsert_run` (e.g. via :func:`pbgenerator.batch.deploy`
        with ``store=``).
        """
        rid = compute_run_id(building)
        if building.results is not None:
            self.write_timeseries(rid, building.results)
        return self.run_row(building, run_id=rid, status=status, extra=extra)

    def run_row(
        self,
        building: "Building",
        *,
        run_id: str | None = None,
        status: str = "ok",
        extra: dict | None = None,
    ) -> dict:
        """Build the flat ``runs`` row for *building* (incl. id + provenance)."""
        rid = run_id or compute_run_id(building)
        row = {"run_id": rid, "status": status}
        row.update(flatten_run(building))
        row["timeseries_path"] = str(self.timeseries_path(rid).relative_to(self.root))
        if extra:
            row.update(extra)
        return row


def _duckdb_type(dtype) -> str:
    """Map a pandas dtype to a DuckDB column type for ALTER TABLE ADD COLUMN."""
    import pandas as pd

    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE"
    return "VARCHAR"


__all__ = ["SimStore", "compute_run_id"]
