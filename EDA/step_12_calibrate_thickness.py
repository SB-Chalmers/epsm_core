"""
Step 12 — Insulation thickness calibration per cluster.

For each of the 8 cluster archetypes, binary-searches the mineral wool
thickness in the EXT_WALL layer of the BETSI template to minimise
|EP_sim − EP_epc|.  All other layers and parameters stay fixed.

The calibration lever is the exterior-wall MW thickness only — roof and
floor insulation thicknesses are held at BETSI-median values.  Wall
insulation dominates the EP variation for these building types (Step 2
RF/SHAP confirmed).

Bounds from BETSI empirical data:
  - Mineral wool old λ=0.042 W/mK
  - Thickness range: 30–200 mm (30 mm ≈ U=1.0, 200 mm ≈ U=0.20)

Pipeline:
  1. For each cluster archetype, use bisection on MW thickness
  2. At each trial, build spec → register → simulate → compare EP
  3. Converge when |EP_sim - EP_epc| < 2 kWh/m² or after 8 iterations
  4. Output calibrated specs and results

Outputs:
  EDA/results_calibrated.csv
  EDA/calibration_log.csv
  EDA/figures/calibration_results.png
"""
import copy
import logging
import traceback
import re
import unicodedata
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.pbgenerator.epc_io import (
    load_footprints,
    load_epc_metadata,
    detect_ventilation_system,
    load_epc_energy,
)
from src.pbgenerator.archetypes import cmf_1960
from src.pbgenerator.building_params import FacadeWWR
from src.pbgenerator.geometry import solve_depth_for_atemp, build_rooms
from src.pbgenerator.runner import run
from src.pbgenerator.weather import nearest_epw
from src.pbgenerator.reporting import log_epc_comparison
from src.pbgenerator.constructions import (
    ConstructionSetDef, CONSTRUCTION_SETS,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

EDA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EDA_DIR.parent
IDF_DIR = PROJECT_DIR / "idf" / "calibration"
OUTPUT_DIR = PROJECT_DIR / "results" / "calibration"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# BETSI TEMPLATE SPECS (same as Step 11, but mutable for calibration)
# ═══════════════════════════════════════════════════════════════════

MAT = {
    "brick":       ("M01 100mm brick",                   "6000000082"),
    "concrete":    ("4 in. Normalweight Concrete Wall",  "6000000026"),
    "conc_floor":  ("100mm Normalweight concrete floor", "6000000026"),
    "conc_roof":   ("6 in. Heavyweight Concrete Roof",  "6000000026"),
    "conc_bsmt":   ("8 in. Concrete Block Basement Wall","6000000026"),
    "mw_old":      ("Mineral Wool Old (created)",        "6000000123"),
    "gypsum":      ("G01 13mm gypsum board",             "6000000020"),
    "plaster":     ("25mm Stucco",                       "6000000020"),
    "eps":         ("I02 50mm insulation board",         "6000000131"),
    "roof_felt":   ("Built-up Roofing",                  "6000000132"),
}

def _L(mat_key, thickness):
    hb, bov = MAT[mat_key]
    return {"honeybee_id": hb, "boverket_id": bov, "thickness": thickness}


def _make_conc_slab_spec(wall_mw_thickness):
    """BETSI_CONC_SLAB template with adjustable wall MW thickness."""
    return {
        "archetype_id": f"CAL_SLAB_{int(wall_mw_thickness*1000)}",
        "display_name": f"Calibrated slab (MW={wall_mw_thickness*1000:.0f}mm)",
        "construction_year": 1968,
        "building_typology": "multi_family",
        "elements": {
            "EXT_WALL": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("plaster", 0.015),
                _L("mw_old", wall_mw_thickness),
                _L("concrete", 0.150),
                _L("gypsum", 0.013),
            ]}]},
            "ROOF": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("roof_felt", 0.006),
                _L("mw_old", 0.270),
                _L("conc_roof", 0.150),
            ]}]},
            "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_floor", 0.150),
                _L("mw_old", 0.270),
            ]}]},
            "INTERMEDIATE_FLOOR": {"components": [{"shearing_layer": "Structure",
                "layers": [_L("conc_floor", 0.200)]}]},
            "GROUND_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", 0.105),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", 0.050),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_WALL": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_bsmt", 0.200),
                _L("mw_old", 0.085),
            ]}]},
            "WINDOW": {"u_value": 2.00, "shgc": 0.70, "vt": 0.65},
        },
    }


def _make_conc_tower_spec(wall_mw_thickness):
    """BETSI_CONC_TOWER template with adjustable wall MW thickness."""
    return {
        "archetype_id": f"CAL_TOWER_{int(wall_mw_thickness*1000)}",
        "display_name": f"Calibrated tower (MW={wall_mw_thickness*1000:.0f}mm)",
        "construction_year": 1970,
        "building_typology": "multi_family",
        "elements": {
            "EXT_WALL": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("plaster", 0.015),
                _L("mw_old", wall_mw_thickness),
                _L("concrete", 0.150),
                _L("gypsum", 0.013),
            ]}]},
            "ROOF": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("roof_felt", 0.006),
                _L("mw_old", 0.290),
                _L("conc_roof", 0.150),
            ]}]},
            "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_floor", 0.150),
                _L("mw_old", 0.290),
            ]}]},
            "INTERMEDIATE_FLOOR": {"components": [{"shearing_layer": "Structure",
                "layers": [_L("conc_floor", 0.200)]}]},
            "GROUND_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", 0.130),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", 0.050),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_WALL": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_bsmt", 0.200),
                _L("mw_old", 0.085),
            ]}]},
            "WINDOW": {"u_value": 1.90, "shgc": 0.70, "vt": 0.65},
        },
    }


TEMPLATE_MAKERS = {
    "BETSI_CONC_SLAB": _make_conc_slab_spec,
    "BETSI_CONC_TOWER": _make_conc_tower_spec,
}


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _find_opaque_json():
    import epsm_data
    root = Path(epsm_data.__file__).resolve().parent.parent
    p = root / "Data" / "opaque_material.json"
    if not p.exists():
        p = root / "data" / "opaque_material.json"
    return p


def _safe_id(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


def _dedup_footprints(fps):
    seen = set()
    unique = []
    for fp in fps:
        if fp.objektidentitet not in seen:
            seen.add(fp.objektidentitet)
            unique.append(fp)
    return unique


def _build_and_register(spec, json_path):
    """Build a single BETSI construction set and register it."""
    from epsm_data import build_archetype_from_spec
    aid = spec["archetype_id"]
    arch = build_archetype_from_spec(spec, json_path, skip_api=True)
    cset = ConstructionSetDef.from_epsm_archetype(arch)
    CONSTRUCTION_SETS[aid] = (lambda cs: lambda: cs)(cset)
    return aid


# ═══════════════════════════════════════════════════════════════════
# SIMULATE A SINGLE ARCHETYPE AT A GIVEN MW THICKNESS
# ═══════════════════════════════════════════════════════════════════

def simulate_at_thickness(formular_id, cluster_name, betsi_template,
                          wall_mw_m, json_path, trial_id):
    """Run one simulation with a given wall MW thickness. Returns EP_sim."""
    spec_maker = TEMPLATE_MAKERS[betsi_template]
    spec = spec_maker(wall_mw_m)
    cset_id = _build_and_register(spec, json_path)

    epc = load_epc_metadata(formular_id)
    vent_sys = detect_ventilation_system(formular_id)
    epc_energy = load_epc_energy(formular_id)
    floors = epc["num_floors"]
    basement_floors = epc["num_basement_floors"]

    all_fps = load_footprints(formular_id=formular_id, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    candidates = _dedup_footprints(flerfamilj if flerfamilj else all_fps)

    total_fp_area = sum(fp.footprint_area for fp in candidates)
    total_floors = floors + basement_floors
    sim_atemp_est = total_fp_area * total_floors
    epc_atemp = epc["atemp"]

    if epc_atemp and epc_atemp > 0 and sim_atemp_est > epc_atemp:
        fp_areas = [fp.footprint_area for fp in candidates]
        total_area = sum(fp_areas)
        fp_depths = []
        for fp, area in zip(candidates, fp_areas):
            fp_target = epc_atemp * (area / total_area)
            d = solve_depth_for_atemp(fp.footprint_pts, fp_target, total_floors)
            fp_depths.append(d)
    else:
        fp_depths = [0.0] * len(candidates)

    garage_pct = 0.0
    if epc["garage_m2"] and epc["atemp"]:
        garage_pct = min(100.0 - epc["residential_pct"],
                         epc["garage_m2"] / epc["atemp"] * 100.0)

    tag = _safe_id(f"{cluster_name}_t{trial_id}")
    total_heating = total_cooling = total_dhw = total_site = 0.0
    total_atemp = 0.0

    for idx, fp in enumerate(candidates):
        fp_tag = f"{tag}_fp{idx}" if len(candidates) > 1 else tag
        depth = fp_depths[idx]

        bldg = build_rooms(
            footprint_pts=fp.footprint_pts,
            floor_height=2.7, num_floors=floors,
            wwr=FacadeWWR(0, 0, 0, 0),
            apartment_depth=depth,
            identifier="preview",
            num_basement_floors=basement_floors,
        )

        params = cmf_1960(
            num_floors=floors,
            ventilation_system=vent_sys,
            apartment_depth=depth,
            residential_pct=epc["residential_pct"],
            garage_pct=garage_pct,
            num_basement_floors=basement_floors,
            cold_attic=True,
            seed=formular_id,
        )
        params = replace(params, construction_set=cset_id)

        weather_file = nearest_epw(fp.centroid_lat, fp.centroid_lon)

        sim = run(
            name=fp_tag,
            footprint_pts=fp.footprint_pts,
            params=params,
            weather_file=weather_file,
            idf_dir=IDF_DIR / fp_tag,
            output_dir=OUTPUT_DIR / fp_tag,
        )

        total_heating += sim["heating_kwh"]
        total_cooling += sim["cooling_kwh"]
        total_dhw += sim["dhw_kwh"]
        total_site += sim["site_kwh"]
        total_atemp += bldg.perimeter_floor_area

    agg_sim = {
        "heating_kwh": total_heating,
        "cooling_kwh": total_cooling,
        "dhw_kwh": total_dhw,
        "site_kwh": total_site,
    }
    comp = log_epc_comparison(
        agg_sim,
        sim_atemp=total_atemp,
        epc_atemp=epc["atemp"],
        energi_prestanda=epc["energi_prestanda"],
        epc_energy=epc_energy,
        ventilation_system=vent_sys,
    )

    ep_sim = comp["epc_total_kwh"] / total_atemp
    return ep_sim, total_atemp


# ═══════════════════════════════════════════════════════════════════
# BISECTION CALIBRATION
# ═══════════════════════════════════════════════════════════════════

# Bounds: 30 mm (U≈1.0) to 200 mm (U≈0.20)
MW_MIN = 0.030
MW_MAX = 0.200
TOLERANCE = 2.0       # kWh/m² — converge when |EP_sim - EP_epc| < this
MAX_ITER = 8


def calibrate_cluster(formular_id, cluster_name, betsi_template, ep_epc,
                      json_path):
    """Binary search on wall MW thickness to match EP_epc."""
    log.info("─" * 60)
    log.info("CALIBRATING  %s  (EP_epc=%.0f, template=%s)",
             cluster_name, ep_epc, betsi_template)
    log.info("─" * 60)

    lo, hi = MW_MIN, MW_MAX
    trials = []
    best_mw = (lo + hi) / 2
    best_ep = None
    best_err = float("inf")
    trial_id = 0

    for i in range(MAX_ITER):
        mw = (lo + hi) / 2
        trial_id += 1
        log.info("  Trial %d: MW=%.0fmm (lo=%.0f, hi=%.0f)",
                 i + 1, mw * 1000, lo * 1000, hi * 1000)

        ep_sim, atemp_sim = simulate_at_thickness(
            formular_id, cluster_name, betsi_template, mw, json_path, trial_id
        )
        err = ep_sim - ep_epc

        trials.append({
            "cluster": cluster_name,
            "iteration": i + 1,
            "mw_mm": round(mw * 1000, 1),
            "ep_sim": round(ep_sim, 1),
            "ep_epc": round(ep_epc, 0),
            "error": round(err, 1),
            "abs_error": round(abs(err), 1),
        })

        log.info("    → EP_sim=%.1f, error=%.1f kWh/m²", ep_sim, err)

        if abs(err) < best_err:
            best_err = abs(err)
            best_mw = mw
            best_ep = ep_sim

        if abs(err) < TOLERANCE:
            log.info("    ✓ Converged at MW=%.0fmm", mw * 1000)
            break

        # EP_sim < EP_epc → too much insulation → reduce MW
        # EP_sim > EP_epc → too little insulation → increase MW
        if err < 0:
            hi = mw
        else:
            lo = mw

    log.info("  BEST: MW=%.0fmm → EP_sim=%.1f (err=%.1f)",
             best_mw * 1000, best_ep, best_ep - ep_epc)

    return best_mw, best_ep, trials


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    json_path = _find_opaque_json()
    log.info("Using opaque_material.json: %s", json_path)

    # Load results from Step 11 (BETSI baselines)
    archetypes = pd.read_csv(EDA_DIR / "archetypes_betsi.csv")
    betsi_results = pd.read_csv(EDA_DIR / "results_betsi.csv")

    # Merge EP_epc onto archetypes
    ep_map = betsi_results.set_index("Cluster")["EP_epc"].to_dict()

    all_trials = []
    calibrated = []

    for _, a in archetypes.iterrows():
        fid = int(a["FormularId"])
        cluster = a["global_cluster"]
        template = a["betsi_template"]
        ep_epc = ep_map.get(cluster, a["ep"])

        try:
            best_mw, best_ep, trials = calibrate_cluster(
                fid, cluster, template, ep_epc, json_path
            )
            all_trials.extend(trials)
            calibrated.append({
                "Cluster": cluster,
                "FormularId": fid,
                "Fastighet": a["IdFastBet"],
                "Adress": a["IdAdr"],
                "Floors": a["floors"],
                "Atemp_epc": a["atemp"],
                "Ventilation": a["ventilation"],
                "BETSI_template": template,
                "EP_epc": round(ep_epc, 0),
                "EP_sim_calibrated": round(best_ep, 1),
                "EPC_ratio": round(best_ep / ep_epc, 2),
                "wall_mw_mm": round(best_mw * 1000, 1),
                "wall_U_approx": round(
                    1.0 / (0.04 + 0.13 + best_mw / 0.042 + 0.150 / 1.7
                           + 0.013 / 0.16 + 0.015 / 0.72), 2),
                "cluster_size": int(a["cluster_size"]),
            })
        except Exception:
            log.error("FAILED calibrating %s", cluster)
            traceback.print_exc()

    # ── Save results ───────────────────────────────────────────────
    cal_df = pd.DataFrame(calibrated)
    cal_df.to_csv(EDA_DIR / "results_calibrated.csv", index=False)

    trials_df = pd.DataFrame(all_trials)
    trials_df.to_csv(EDA_DIR / "calibration_log.csv", index=False)

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*110}")
    print(f"  CALIBRATION RESULTS — Wall Insulation Thickness Sweep")
    print(f"{'='*110}")
    print(f"  {'Cluster':<16s} {'n':>4s} {'BETSI':>18s} "
          f"{'EP_epc':>7s} {'EP_sim':>7s} {'Ratio':>6s} "
          f"{'MW_mm':>6s} {'U_wall':>7s}")
    print(f"  {'-'*16} {'-'*4} {'-'*18} "
          f"{'-'*7} {'-'*7} {'-'*6} "
          f"{'-'*6} {'-'*7}")

    for _, r in cal_df.iterrows():
        print(f"  {r['Cluster']:<16s} {r['cluster_size']:4.0f} "
              f"{r['BETSI_template']:>18s} "
              f"{r['EP_epc']:7.0f} {r['EP_sim_calibrated']:7.1f} "
              f"{r['EPC_ratio']:6.2f} "
              f"{r['wall_mw_mm']:6.0f} {r['wall_U_approx']:7.2f}")

    n = len(cal_df)
    print(f"\n  Total clusters: {n}")
    print(f"  Mean EPC ratio: {cal_df['EPC_ratio'].mean():.2f}")
    within_10 = ((cal_df["EPC_ratio"] >= 0.9)
                 & (cal_df["EPC_ratio"] <= 1.1)).mean()
    within_20 = ((cal_df["EPC_ratio"] >= 0.8)
                 & (cal_df["EPC_ratio"] <= 1.2)).mean()
    print(f"  Within ±10%: {within_10*100:.0f}% ({int(within_10*n)}/{n})")
    print(f"  Within ±20%: {within_20*100:.0f}% ({int(within_20*n)}/{n})")

    # Compare to Step 11 BETSI baseline
    betsi_df = pd.read_csv(EDA_DIR / "results_betsi.csv")
    print(f"\n  Comparison: BETSI baseline → calibrated")
    print(f"  {'Metric':<20s} {'BETSI':>12s} {'Calibrated':>12s}")
    print(f"  {'-'*20} {'-'*12} {'-'*12}")
    print(f"  {'Mean ratio':<20s} "
          f"{betsi_df['EPC_ratio'].mean():12.2f} "
          f"{cal_df['EPC_ratio'].mean():12.2f}")

    # ── Plot ───────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    colors = {"S-vent": "#4C72B0", "F-vent": "#DD8452",
              "FTX-vent": "#C44E52", "Renovated": "#8172B3"}

    # 1: Scatter EP_sim vs EP_epc
    ax = axes[0]
    for _, r in cal_df.iterrows():
        grp = r["Cluster"].rsplit("_C", 1)[0]
        ax.scatter(r["EP_epc"], r["EP_sim_calibrated"],
                   c=colors.get(grp, "gray"),
                   s=max(20, r["cluster_size"] * 2),
                   alpha=0.7, edgecolors="k", linewidths=0.5)
    ep_min = min(cal_df["EP_epc"].min(), cal_df["EP_sim_calibrated"].min()) - 10
    ep_max = max(cal_df["EP_epc"].max(), cal_df["EP_sim_calibrated"].max()) + 10
    ax.plot([ep_min, ep_max], [ep_min, ep_max], "k--", alpha=0.4)
    ax.plot([ep_min, ep_max], [ep_min*0.9, ep_max*0.9],
            "orange", ls=":", alpha=0.3)
    ax.plot([ep_min, ep_max], [ep_min*1.1, ep_max*1.1],
            "orange", ls=":", alpha=0.3)
    ax.set(xlabel="EP_epc (kWh/m²)", ylabel="EP_sim (kWh/m²)",
           title="Calibrated: EP_sim vs EP_epc")
    ax.grid(True, alpha=0.3)
    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], marker="o", color="w",
                     markerfacecolor=c, markersize=8, label=g)
              for g, c in colors.items()]
    ax.legend(handles=legend)

    # 2: MW thickness per cluster
    ax = axes[1]
    clusters = cal_df["Cluster"].values
    mw_vals = cal_df["wall_mw_mm"].values
    bar_colors = [colors.get(c.rsplit("_C", 1)[0], "gray") for c in clusters]
    ax.barh(range(len(clusters)), mw_vals, color=bar_colors, alpha=0.7,
            edgecolor="k", linewidth=0.5)
    ax.axvline(155, color="green", ls="--", alpha=0.4,
               label="BETSI median (155mm)")
    ax.set_yticks(range(len(clusters)))
    ax.set_yticklabels(clusters, fontsize=8)
    ax.set(xlabel="Wall MW thickness (mm)", title="Calibrated Insulation")
    ax.legend(fontsize=8)
    ax.grid(True, axis="x", alpha=0.3)

    # 3: Convergence traces
    ax = axes[2]
    for cluster_name in cal_df["Cluster"].values:
        ct = trials_df[trials_df["cluster"] == cluster_name]
        grp = cluster_name.rsplit("_C", 1)[0]
        ax.plot(ct["iteration"], ct["abs_error"], "o-",
                color=colors.get(grp, "gray"), alpha=0.7,
                markersize=4, label=cluster_name)
    ax.axhline(TOLERANCE, color="green", ls="--", alpha=0.4,
               label=f"Tolerance ({TOLERANCE} kWh/m²)")
    ax.set(xlabel="Iteration", ylabel="|EP_sim − EP_epc| (kWh/m²)",
           title="Convergence")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "calibration_results.png", dpi=150)
    plt.close()
    log.info("  → Saved figures/calibration_results.png")


if __name__ == "__main__":
    main()
