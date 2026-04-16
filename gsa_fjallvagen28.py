"""Mini OAT (one-at-a-time) Global Sensitivity Analysis for Fjällvägen 28.

Varies each parameter from a realistic LOW to HIGH bound while holding all
others at the baseline (cmf_1960 defaults).  Outputs a tornado-style table
sorted by impact on the EPC-comparable total (kWh/m²).

Parameters tested:
  infiltration_ach, thermal_bridge_fraction, t_heating, equipment_w_m2,
  dhw_kwh_m2, dhw_vvc_kwh_m2, mech_vent_l_s_m2, floor_height,
  wwr_scale (uniform multiplier on all 4 orientations), occupant_density
"""
import csv
import logging
import time
from dataclasses import replace
from pathlib import Path

from src.pbgenerator.epc_io import load_footprints, load_epc_metadata, detect_ventilation_system
from src.pbgenerator.archetypes import cmf_1960
from src.pbgenerator.building_params import FacadeWWR
from src.pbgenerator.runner import run
from src.pbgenerator.weather import nearest_epw

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

EPC_FORMULAR_ID = 1033661

# ── Load geometry & EPC once ────────────────────────────────────────────────
fp = load_footprints(fastighetsbeteckning="ÄGIR 17", husnummer=1)[0]
epc = load_epc_metadata(EPC_FORMULAR_ID)
vent_sys = detect_ventilation_system(EPC_FORMULAR_ID)

floors = epc["num_floors"]
basement_floors = epc["num_basement_floors"]
weather_file = nearest_epw(fp.centroid_lat, fp.centroid_lon)

# ── Baseline params ─────────────────────────────────────────────────────────
baseline = cmf_1960(
    num_floors=floors,
    ventilation_system=vent_sys,
    num_basement_floors=basement_floors,
    cold_attic=True,
    seed=42,  # deterministic WWR
)
sim_atemp = fp.footprint_area * (floors + basement_floors)
epc_ep = epc["energi_prestanda"]  # 110 kWh/m²
fastighet_kwh = epc["fastighet_kwh"] or 0

# ── Parameter ranges ────────────────────────────────────────────────────────
# (name, low, baseline_value, high, unit)
PARAMS = [
    ("infiltration_ach",        0.05,  baseline.infiltration_ach,       0.30,  "ACH"),
    ("thermal_bridge_fraction", 0.10,  baseline.thermal_bridge_fraction, 0.40, "frac"),
    ("t_heating",               21.0,  baseline.t_heating,              23.5,  "°C"),
    ("equipment_w_m2",          1.0,   baseline.equipment_w_m2,         2.5,   "W/m²"),
    ("dhw_kwh_m2",              18.0,  baseline.dhw_kwh_m2,             25.0,  "kWh/m²"),
    ("dhw_vvc_kwh_m2",          3.0,   baseline.dhw_vvc_kwh_m2,         8.0,  "kWh/m²"),
    ("mech_vent_l_s_m2",        0.30,  baseline.mech_vent_l_s_m2,       0.50, "l/s/m²"),
    ("floor_height",            2.5,   baseline.floor_height,            3.0,  "m"),
    ("wwr_scale",               0.70,  1.0,                             1.30,  "×"),
    ("occupant_density",        0.010, baseline.occupant_density,        0.025, "p/m²"),
]


def _make_params(overrides: dict) -> "BuildingParams":
    """Create BuildingParams from baseline with overrides applied."""
    wwr_scale = overrides.pop("wwr_scale", 1.0)
    base_wwr = baseline.wwr
    scaled_wwr = FacadeWWR(
        north=min(0.95, base_wwr.north * wwr_scale),
        south=min(0.95, base_wwr.south * wwr_scale),
        east=min(0.95, base_wwr.east * wwr_scale),
        west=min(0.95, base_wwr.west * wwr_scale),
    )
    return replace(baseline, wwr=scaled_wwr, **overrides)


def _epc_comparable(results: dict, params) -> float:
    """Compute EPC-comparable total in kWh/m²."""
    heating = results["heating_kwh"]
    dhw = results["dhw_kwh"]
    sveby_airing = 4.0 * sim_atemp  # fgeo=1.0
    dhw_vvc = params.dhw_vvc_kwh_m2 * sim_atemp
    bldg_svc = fastighet_kwh * (sim_atemp / epc["atemp"]) if epc["atemp"] else 0.0
    total = heating + sveby_airing + dhw + dhw_vvc + bldg_svc
    return total / sim_atemp


def _run_case(tag: str, params) -> dict:
    """Run one simulation; return results dict augmented with epc_kwh_m2."""
    t0 = time.time()
    results = run(
        name=f"gsa_{tag}",
        footprint_pts=fp.footprint_pts,
        params=params,
        weather_file=weather_file,
        idf_dir=Path("idf"),
        output_dir=Path("results"),
    )
    elapsed = time.time() - t0
    epc_kwh_m2 = _epc_comparable(results, params)
    log.info("  [%s] EPC-comp = %.1f kWh/m²  (%.0fs)", tag, epc_kwh_m2, elapsed)
    results["epc_kwh_m2"] = epc_kwh_m2
    return results


# ── Run GSA ─────────────────────────────────────────────────────────────────
log.info("=== Mini GSA for Fjällvägen 28 ===")
log.info("EPC target: %d kWh/m²  |  Atemp(sim): %.0f m²  |  Vent: %s",
         epc_ep, sim_atemp, vent_sys)
log.info("Baseline WWR: N=%.3f S=%.3f E=%.3f W=%.3f",
         baseline.wwr.north, baseline.wwr.south, baseline.wwr.east, baseline.wwr.west)
log.info("")

# 1) Baseline run
log.info("Running baseline...")
base_results = _run_case("baseline", baseline)
base_epc = base_results["epc_kwh_m2"]
log.info("Baseline EPC-comp: %.1f kWh/m²  (target: %d)", base_epc, epc_ep)
log.info("")

# 2) OAT sweeps
rows = []
for name, lo, mid, hi, unit in PARAMS:
    log.info("Parameter: %s  [%.3f → %.3f → %.3f %s]", name, lo, mid, hi, unit)

    # LOW
    p_lo = _make_params({name: lo} if name != "wwr_scale" else {"wwr_scale": lo})
    r_lo = _run_case(f"{name}_lo", p_lo)

    # HIGH
    p_hi = _make_params({name: hi} if name != "wwr_scale" else {"wwr_scale": hi})
    r_hi = _run_case(f"{name}_hi", p_hi)

    delta_lo = r_lo["epc_kwh_m2"] - base_epc
    delta_hi = r_hi["epc_kwh_m2"] - base_epc
    swing = r_hi["epc_kwh_m2"] - r_lo["epc_kwh_m2"]

    rows.append({
        "parameter": name,
        "unit": unit,
        "low": lo,
        "baseline": mid,
        "high": hi,
        "epc_lo": r_lo["epc_kwh_m2"],
        "epc_base": base_epc,
        "epc_hi": r_hi["epc_kwh_m2"],
        "delta_lo": delta_lo,
        "delta_hi": delta_hi,
        "swing": swing,
        "abs_swing": abs(swing),
    })
    log.info("  → swing = %.1f kWh/m²  (lo: %+.1f, hi: %+.1f)\n",
             swing, delta_lo, delta_hi)

# ── Sort by absolute swing & print tornado ──────────────────────────────────
rows.sort(key=lambda r: r["abs_swing"], reverse=True)

log.info("=" * 80)
log.info("TORNADO SENSITIVITY TABLE  (sorted by |swing|)")
log.info("%-28s %6s %8s %8s %8s %8s %8s %8s",
         "Parameter", "Unit", "Low", "Base", "High",
         "EPC_lo", "EPC_hi", "Swing")
log.info("-" * 80)
for r in rows:
    log.info("%-28s %6s %8.3f %8.3f %8.3f %8.1f %8.1f %+8.1f",
             r["parameter"], r["unit"],
             r["low"], r["baseline"], r["high"],
             r["epc_lo"], r["epc_hi"], r["swing"])
log.info("-" * 80)
log.info("Baseline EPC-comp: %.1f kWh/m²  |  EPC target: %d kWh/m²  |  Gap: %+.1f",
         base_epc, epc_ep, base_epc - epc_ep)

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = Path("results/gsa_fjallvagen28.csv")
csv_path.parent.mkdir(exist_ok=True)
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "parameter", "unit", "low", "baseline", "high",
        "epc_lo", "epc_base", "epc_hi", "delta_lo", "delta_hi", "swing",
    ])
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in w.fieldnames})
log.info("\nResults saved to %s", csv_path)
