"""
Step 16 — Post-hoc certainty scoring for calibrated archetype parameters.

This script computes confidence/certainty metrics from existing calibration
artifacts, without running new EnergyPlus simulations.

Inputs:
  - EDA/results_multilever_v2.csv
  - EDA/calibration_multilever_v2_log.csv

Outputs:
  - EDA/results_multilever_v2_certainty.csv

Certainty components (all scaled to [0, 1]):
  1) fit_conf:
       Confidence from EP fit quality (EPC ratio closeness to 1.0).
  2) bound_conf:
       Confidence from distance to parameter bounds (edge-hugging => lower confidence).
  3) identifiability_conf:
       Confidence from post-hoc local flatness in the calibration log.
       If many values around the optimum give similarly small error, identifiability
       is lower; if acceptable values are narrow, identifiability is higher.

Overall score:
  certainty_overall = 0.35*fit_conf + 0.35*bound_conf + 0.30*identifiability_conf
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

EDA_DIR = Path(__file__).resolve().parent

# Step 14 bounds in output units (mm where applicable)
BOUNDS: Dict[str, Tuple[float, float]] = {
    "wall_mw_mm": (45.0, 200.0),
    "roof_mw_mm": (30.0, 400.0),
    "floor_eps_mm": (10.0, 130.0),
    "window_u": (1.5, 2.6),
    "infiltration_ach": (0.15, 1.0),
    "thermal_bridge_pct": (10.0, 50.0),
    "heating_sys_eff": (0.8, 1.0),
}

# Mapping from results columns -> calibration log lever names
LEVER_COL_TO_LOG = {
    "wall_mw_mm": "wall_mw",
    "roof_mw_mm": "roof_mw",
    "floor_eps_mm": "floor_eps",
    "window_u": "window_u",
    "infiltration_ach": "infiltration_ach",
    "thermal_bridge_pct": "thermal_bridge_frac",
    "heating_sys_eff": "heating_sys_eff",
}

MM_COLS = {"wall_mw_mm", "roof_mw_mm", "floor_eps_mm"}
PCT_COLS = {"thermal_bridge_pct"}


def fit_confidence(epc_ratio: pd.Series, tolerance: float = 0.20) -> pd.Series:
    """Map |ratio-1| to [0,1], with 1.0 at perfect fit and 0 at +/- tolerance."""
    score = 1.0 - (epc_ratio - 1.0).abs() / tolerance
    return score.clip(lower=0.0, upper=1.0)


def bound_distance_confidence(value: float, lo: float, hi: float) -> float:
    """Distance to nearest bound normalized by half-range (0=edge, 1=center)."""
    half = (hi - lo) / 2.0
    if half <= 0:
        return 0.0
    d = min(value - lo, hi - value) / half
    return float(np.clip(d, 0.0, 1.0))


def to_result_units(log_values: pd.Series, result_col: str) -> pd.Series:
    """Convert lever values in log units to the units used in results CSV."""
    vals = log_values.astype(float).copy()
    if result_col in MM_COLS:
        vals = vals * 1000.0
    elif result_col in PCT_COLS:
        vals = vals * 100.0
    return vals


def identifiability_from_log(
    sub: pd.DataFrame,
    optimum_val: float,
    lo: float,
    hi: float,
    err_band: float = 5.0,
) -> float:
    """
    Compute identifiability confidence from log points.

    Steps:
      1) Select points where |error| <= err_band (acceptable EP match).
      2) Measure width of acceptable values relative to full lever range.
      3) Confidence is 1 - normalized width.

    Sparse-log safeguards:
      - If no acceptable points exist, fall back to nearest points around optimum
        and use a conservative penalty.
      - Require at least 2 points for width estimate, else return low confidence.
    """
    if sub.empty:
        return 0.15

    vals = sub["value_units"].astype(float)
    errs = sub["error"].astype(float).abs()

    ok = sub[errs <= err_band]
    if len(ok) >= 2:
        vmin = float(ok["value_units"].min())
        vmax = float(ok["value_units"].max())
        width = max(0.0, vmax - vmin)
        full = max(1e-9, hi - lo)
        return float(np.clip(1.0 - width / full, 0.0, 1.0))

    # Fallback: take closest 4 points to optimum and infer local flatness roughly
    # If local error span is small over a wide value span, certainty is low.
    if len(sub) >= 2:
        local = sub.assign(dist=(vals - optimum_val).abs()).sort_values("dist").head(4)
        lvals = local["value_units"].astype(float)
        lerrs = local["error"].astype(float).abs()
        vspan = float(lvals.max() - lvals.min())
        espan = float(lerrs.max() - lerrs.min())
        full = max(1e-9, hi - lo)

        # More value spread with little error change => lower identifiability.
        flatness_penalty = np.clip((vspan / full) * (1.0 / (1.0 + espan)), 0.0, 1.0)
        conf = 0.55 - 0.35 * flatness_penalty
        return float(np.clip(conf, 0.15, 0.75))

    return 0.15


def main() -> None:
    results_path = EDA_DIR / "results_multilever_v2.csv"
    log_path = EDA_DIR / "calibration_multilever_v2_log.csv"
    out_path = EDA_DIR / "results_multilever_v2_certainty.csv"

    res = pd.read_csv(results_path)
    log = pd.read_csv(log_path)

    # Drop check rows to keep real trial points only.
    log = log[~log["lever"].astype(str).str.endswith("_check")].copy()

    # Fit confidence (cluster-level)
    res["fit_conf"] = fit_confidence(res["EPC_ratio"])

    # Per-lever bound confidence
    lever_bound_conf_cols = []
    for col, (lo, hi) in BOUNDS.items():
        c = f"{col}_bound_conf"
        res[c] = res[col].astype(float).apply(lambda x: bound_distance_confidence(x, lo, hi))
        lever_bound_conf_cols.append(c)

    res["bound_conf"] = res[lever_bound_conf_cols].mean(axis=1)

    # Per-lever identifiability from post-hoc log analysis
    lever_ident_conf_cols = []
    for result_col, log_lever in LEVER_COL_TO_LOG.items():
        out_col = f"{result_col}_ident_conf"
        lever_ident_conf_cols.append(out_col)
        lo, hi = BOUNDS[result_col]

        conf_values = []
        for _, r in res.iterrows():
            cluster = r["Cluster"]
            opt = float(r[result_col])

            sub = log[(log["cluster"] == cluster) & (log["lever"] == log_lever)].copy()
            if sub.empty:
                conf_values.append(0.15)
                continue

            sub["value_units"] = to_result_units(sub["value"], result_col)
            conf = identifiability_from_log(sub, optimum_val=opt, lo=lo, hi=hi)
            conf_values.append(conf)

        res[out_col] = conf_values

    res["identifiability_conf"] = res[lever_ident_conf_cols].mean(axis=1)

    # Overall certainty
    res["certainty_overall"] = (
        0.35 * res["fit_conf"]
        + 0.35 * res["bound_conf"]
        + 0.30 * res["identifiability_conf"]
    )

    # Compact interpretation bands
    bins = [-0.01, 0.40, 0.65, 0.85, 1.01]
    labels = ["low", "medium", "high", "very_high"]
    res["certainty_band"] = pd.cut(res["certainty_overall"], bins=bins, labels=labels)

    # Save
    res.to_csv(out_path, index=False)

    # Print summary
    cols = [
        "Cluster",
        "EPC_ratio",
        "fit_conf",
        "bound_conf",
        "identifiability_conf",
        "certainty_overall",
        "certainty_band",
    ]
    print("\nPost-hoc certainty summary:")
    print(res[cols].round(3).to_string(index=False))
    print("\nMean certainty_overall:", round(float(res["certainty_overall"].mean()), 3))
    print("Wrote:", out_path)


if __name__ == "__main__":
    main()
