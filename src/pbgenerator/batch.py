"""Parallel batch deployment helper.

Wraps :class:`concurrent.futures.ProcessPoolExecutor` with the conventions
used across the EDA / paper deployment scripts:

* one row per building (``DataFrame`` or list of dicts)
* user supplies a pure ``simulate_fn(row) -> dict`` that returns one result
  row (or raises an exception)
* results are appended to ``out_csv`` as soon as each worker completes
  (so the run is interruptible); failures land in a parallel
  ``*_failures.csv``
* ``resume=True`` skips rows whose primary-key value already appears in
  ``out_csv``
* an optional ``cleanup_fn(row)`` is called in the worker's ``finally``
  block to delete per-building scratch (E+ run dirs, IDF dumps)

Example::

    from pbgenerator.batch import deploy

    def simulate(row):
        # ... build params, run E+, return result dict
        return {"FormularId": row["FormularId"], "ep_sim": 145.2, ...}

    deploy(
        rows=cohort_df,
        simulate_fn=simulate,
        out_csv="results/gothenburg_a1.csv",
        primary_key="FormularId",
        n_workers=12,
    )
"""
from __future__ import annotations

import csv
import logging
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .store import SimStore

log = logging.getLogger(__name__)

SimulateFn = Callable[[dict], dict]
CleanupFn = Callable[[dict], None]


def _worker_wrapper(payload: tuple[SimulateFn, dict, CleanupFn | None]):
    """Run a single simulate_fn in a child process.

    Returns ``(result_dict, traceback_str)`` — exactly one is None.
    Catching here keeps a single failed building from killing the pool.
    """
    simulate_fn, row, cleanup_fn = payload
    try:
        return simulate_fn(row), None
    except Exception:
        return None, traceback.format_exc()
    finally:
        if cleanup_fn is not None:
            try:
                cleanup_fn(row)
            except Exception:
                log.warning("cleanup_fn failed", exc_info=True)


def deploy(
    rows: pd.DataFrame | Iterable[dict],
    simulate_fn: SimulateFn,
    out_csv: str | Path,
    *,
    primary_key: str = "FormularId",
    n_workers: int = 12,
    resume: bool = True,
    failures_csv: str | Path | None = None,
    cleanup_fn: CleanupFn | None = None,
    log_every: int = 5,
    store: "SimStore | None" = None,
) -> dict:
    """Run *simulate_fn* over *rows* in parallel and stream results to CSV.

    Parameters
    ----------
    rows:
        Input DataFrame or iterable of dicts.  One simulation per row.
    simulate_fn:
        Callable that takes one row dict and returns a result dict.  Must
        be picklable (top-level function or imported callable).  Should
        include the primary-key field in its return so resume works.
    out_csv:
        Destination CSV.  Header is taken from the first successful row's
        keys; subsequent rows are appended.  If ``resume=False`` and the
        file exists, it is overwritten.
    primary_key:
        Column used to dedupe completed rows when ``resume=True``.
    n_workers:
        Number of worker processes.
    resume:
        If True and *out_csv* exists, skip rows whose primary-key value is
        already present.
    failures_csv:
        Where to write per-row tracebacks.  Defaults to
        ``<out_csv>_failures.csv``.
    cleanup_fn:
        Optional per-row cleanup hook called inside each worker's
        ``finally`` block (e.g. delete the E+ scratch directory).
    log_every:
        Emit a progress line every N completed rows.
    store:
        Optional :class:`~pbgenerator.store.SimStore`.  When set, each
        successful result row is also persisted to the campaign DuckDB
        (``store.upsert_run``).  The worker's ``simulate_fn`` is expected to
        have already written that run's time-series partition (e.g. via
        ``store.stage(building)``, which also returns the flat row to return
        here).  CSV output and CSV-based resume still apply.

    Returns
    -------
    A summary dict with ``n_total``, ``n_ok``, ``n_failed``, ``elapsed_s``,
    ``out_csv``, ``failures_csv``.
    """
    out_csv = Path(out_csv)
    failures_csv = Path(failures_csv) if failures_csv else out_csv.with_name(
        out_csv.stem + "_failures.csv"
    )
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    # ----- Normalise input ------------------------------------------------
    if isinstance(rows, pd.DataFrame):
        df = rows
    else:
        df = pd.DataFrame(list(rows))
    if df.empty:
        log.warning("deploy(): no rows to process")
        return {
            "n_total": 0, "n_ok": 0, "n_failed": 0,
            "elapsed_s": 0.0, "out_csv": str(out_csv),
            "failures_csv": str(failures_csv),
        }

    if primary_key not in df.columns:
        raise ValueError(f"primary_key '{primary_key}' not in input columns")

    # ----- Resume ---------------------------------------------------------
    if resume and out_csv.exists():
        try:
            done_pk = set(pd.read_csv(out_csv)[primary_key].astype(str))
        except Exception:
            done_pk = set()
        before = len(df)
        df = df[~df[primary_key].astype(str).isin(done_pk)]
        log.info("Resume: %d already done, %d remaining", len(done_pk), len(df))
    else:
        if out_csv.exists():
            out_csv.unlink()
        if failures_csv.exists():
            failures_csv.unlink()

    rows_list = df.to_dict(orient="records")
    if not rows_list:
        log.info("Nothing to do.")
        return {
            "n_total": 0, "n_ok": 0, "n_failed": 0,
            "elapsed_s": 0.0, "out_csv": str(out_csv),
            "failures_csv": str(failures_csv),
        }

    log.info("deploy(): %d rows, %d workers → %s",
             len(rows_list), n_workers, out_csv)

    # ----- Run pool -------------------------------------------------------
    fieldnames: list[str] | None = None
    n_ok = 0
    failed: list[dict] = []
    t0 = time.time()
    payloads = [(simulate_fn, r, cleanup_fn) for r in rows_list]

    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(_worker_wrapper, p): p[1] for p in payloads}
        for i, fut in enumerate(as_completed(futures), 1):
            row = futures[fut]
            try:
                result, err = fut.result()
            except Exception:
                result, err = None, traceback.format_exc()

            if result is not None:
                n_ok += 1
                if fieldnames is None:
                    fieldnames = list(result.keys())
                write_header = not out_csv.exists()
                with open(out_csv, "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    if write_header:
                        w.writeheader()
                    w.writerow(result)
                if store is not None:
                    try:
                        store.upsert_run(result)
                    except Exception:
                        log.error("store.upsert_run failed for %s=%s",
                                  primary_key, row.get(primary_key), exc_info=True)
            else:
                failed.append({
                    primary_key: row.get(primary_key),
                    "error": (err or "").splitlines()[-1] if err else "unknown",
                })
                log.error("FAILED %s=%s", primary_key, row.get(primary_key))

            if i % log_every == 0 or i == len(rows_list):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(rows_list) - i) / rate if rate > 0 else float("inf")
                log.info(
                    "%d/%d (%.1f%%)  ok=%d fail=%d  elapsed=%.1fmin  eta=%.1fmin",
                    i, len(rows_list), 100 * i / len(rows_list),
                    n_ok, len(failed), elapsed / 60, eta / 60,
                )

    # ----- Failures -------------------------------------------------------
    if failed:
        with open(failures_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(failed[0].keys()))
            w.writeheader()
            w.writerows(failed)

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("DONE: %d ok, %d failed of %d (%.1f min)",
             n_ok, len(failed), len(rows_list), elapsed / 60)
    return {
        "n_total": len(rows_list),
        "n_ok": n_ok,
        "n_failed": len(failed),
        "elapsed_s": elapsed,
        "out_csv": str(out_csv),
        "failures_csv": str(failures_csv) if failed else None,
    }
