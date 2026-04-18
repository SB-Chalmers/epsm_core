"""
Step 15 — Simulate all 222 buildings with cluster-calibrated archetypes.

Uses the calibrated lever values from Step 14 (results_multilever_v2.csv)
to run EnergyPlus for every unique building in the 8 clusters.

Each building gets:
  - Construction set from its cluster's calibrated wall/roof/floor/window values
  - Infiltration ACH from its cluster's calibrated value
  - Thermal bridge fraction from its cluster's calibrated value
  - Heating system efficiency from its cluster's calibrated value

Outputs:
  EDA/results_all_222.csv          — per-building simulation results
  EDA/figures/all_222_results.png  — 4-panel error analysis plot
"""
import csv
import logging
import re
import traceback
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
IDF_DIR = PROJECT_DIR / "idf" / "all_222"
OUTPUT_DIR = PROJECT_DIR / "results" / "all_222"
RESULTS_CSV = EDA_DIR / "results_all_222.csv"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# MATERIALS & SPEC BUILDER  (same as Step 14)
# ═══════════════════════════════════════════════════════════════════

MAT = {
    "concrete":   ("4 in. Normalweight Concrete Wall",  "6000000026"),
    "conc_floor": ("100mm Normalweight concrete floor", "6000000026"),
    "conc_roof":  ("6 in. Heavyweight Concrete Roof",   "6000000026"),
    "conc_bsmt":  ("8 in. Concrete Block Basement Wall","6000000026"),
    "mw_old":     ("Mineral Wool Old (created)",        "6000000123"),
    "gypsum":     ("G01 13mm gypsum board",             "6000000020"),
    "plaster":    ("25mm Stucco",                       "6000000020"),
    "eps":        ("I02 50mm insulation board",         "6000000131"),
    "roof_felt":  ("Built-up Roofing",                  "6000000132"),
}


def _L(mat_key, thickness):
    hb, bov = MAT[mat_key]
    return {"honeybee_id": hb, "boverket_id": bov, "thickness": thickness}


def _make_spec(template, wall_mw, roof_mw, floor_eps, window_u, spec_id):
    """Build a construction spec with calibrated thicknesses + window U."""
    is_tower = "TOWER" in template
    bsmt_mw = 0.085

    return {
        "archetype_id": spec_id,
        "display_name": f"Calibrated ({spec_id})",
        "construction_year": 1970 if is_tower else 1968,
        "building_typology": "multi_family",
        "elements": {
            "EXT_WALL": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("plaster", 0.015),
                _L("mw_old", wall_mw),
                _L("concrete", 0.150),
                _L("gypsum", 0.013),
            ]}]},
            "ROOF": {"components": [{"shearing_layer": "Skin", "layers": [
                _L("roof_felt", 0.006),
                _L("mw_old", roof_mw),
                _L("conc_roof", 0.150),
            ]}]},
            "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_floor", 0.150),
                _L("mw_old", roof_mw),
            ]}]},
            "INTERMEDIATE_FLOOR": {"components": [{"shearing_layer": "Structure",
                "layers": [_L("conc_floor", 0.200)]}]},
            "GROUND_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", floor_eps),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("eps", 0.050),
                _L("conc_floor", 0.150),
            ]}]},
            "BASEMENT_WALL": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_bsmt", 0.200),
                _L("mw_old", bsmt_mw),
            ]}]},
            "WINDOW": {"u_value": window_u, "shgc": 0.70, "vt": 0.65},
        },
    }


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
    from epsm_data import build_archetype_from_spec
    aid = spec["archetype_id"]
    arch = build_archetype_from_spec(spec, json_path, skip_api=True)
    cset = ConstructionSetDef.from_epsm_archetype(arch)
    CONSTRUCTION_SETS[aid] = (lambda cs: lambda: cs)(cset)
    return aid


# ═══════════════════════════════════════════════════════════════════
# BUILD CLUSTER CONSTRUCTION SETS
# ═══════════════════════════════════════════════════════════════════

def build_cluster_csets(cal_df, json_path):
    """Build and register one construction set per cluster. Returns dict
    of cluster_name → {cset_id, infiltration_ach, tb_frac, sys_eff}."""
    cluster_params = {}
    for _, row in cal_df.iterrows():
        cluster = row["Cluster"]
        template = row["BETSI_template"]
        wall_mw = row["wall_mw_mm"] / 1000.0
        roof_mw = row["roof_mw_mm"] / 1000.0
        floor_eps = row["floor_eps_mm"] / 1000.0
        window_u = row["window_u"]

        spec_id = f"CAL_{_safe_id(cluster)}"
        spec = _make_spec(template, wall_mw, roof_mw, floor_eps, window_u, spec_id)
        cset_id = _build_and_register(spec, json_path)

        cluster_params[cluster] = {
            "cset_id": cset_id,
            "infiltration_ach": row["infiltration_ach"],
            "thermal_bridge_frac": row["thermal_bridge_pct"] / 100.0,
            "heating_sys_eff": row["heating_sys_eff"],
        }
        log.info("  Built %s → wall=%.0fmm roof=%.0fmm win_u=%.2f infil=%.3f",
                 cluster, row["wall_mw_mm"], row["roof_mw_mm"],
                 window_u, row["infiltration_ach"])

    return cluster_params


# ═══════════════════════════════════════════════════════════════════
# SIMULATE ONE BUILDING
# ═══════════════════════════════════════════════════════════════════

def simulate_building(formular_id, cluster_name, cluster_params):
    """Simulate a single building with its cluster's calibrated params."""
    cp = cluster_params[cluster_name]
    tag = _safe_id(f"b{formular_id}")

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
        fp_depths = [
            solve_depth_for_atemp(fp.footprint_pts,
                                  epc_atemp * (a / total_area),
                                  total_floors)
            for fp, a in zip(candidates, fp_areas)
        ]
    else:
        fp_depths = [0.0] * len(candidates)

    garage_pct = 0.0
    if epc["garage_m2"] and epc["atemp"]:
        garage_pct = min(100.0 - epc["residential_pct"],
                         epc["garage_m2"] / epc["atemp"] * 100.0)

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
        params = replace(params,
                         construction_set=cp["cset_id"],
                         infiltration_ach=cp["infiltration_ach"],
                         thermal_bridge_fraction=cp["thermal_bridge_frac"])

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

    # Apply heating system efficiency
    sys_eff = cp["heating_sys_eff"]
    delivered_heating = total_heating / sys_eff

    agg_sim = {
        "heating_kwh": delivered_heating,
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

    return {
        "FormularId": formular_id,
        "Cluster": cluster_name,
        "Byggar": epc["construction_year"],
        "Atemp_epc": epc["atemp"],
        "Atemp_sim": round(total_atemp, 1),
        "Floors": floors,
        "Num_footprints": len(candidates),
        "Ventilation": vent_sys,
        "EP_epc": epc["energi_prestanda"],
        "Heating_kwh_m2": round(delivered_heating / total_atemp, 1),
        "EP_sim": round(ep_sim, 1),
        "EPC_ratio": round(ep_sim / epc["energi_prestanda"], 2)
            if epc["energi_prestanda"] else None,
    }


# ═══════════════════════════════════════════════════════════════════
# ANALYSIS & PLOTS
# ═══════════════════════════════════════════════════════════════════

def analyse_results(results_df):
    df = results_df.copy()
    df["error_abs"] = df["EP_sim"] - df["EP_epc"]
    df["error_pct"] = (df["EP_sim"] - df["EP_epc"]) / df["EP_epc"] * 100

    print(f"\n{'='*70}")
    print(f"  ALL 222 BUILDINGS — CALIBRATED ARCHETYPE RESULTS")
    print(f"{'='*70}")
    print(f"  Buildings simulated: {len(df)}")
    print(f"  Mean EPC ratio:   {df['EPC_ratio'].mean():.2f}")
    print(f"  Median EPC ratio: {df['EPC_ratio'].median():.2f}")
    print(f"  Std EPC ratio:    {df['EPC_ratio'].std():.2f}")
    print(f"  MAE:              {df['error_abs'].abs().mean():.1f} kWh/m²")
    print(f"  RMSE:             {np.sqrt((df['error_abs']**2).mean()):.1f} kWh/m²")
    w10 = ((df['EPC_ratio'] >= 0.9) & (df['EPC_ratio'] <= 1.1)).mean() * 100
    w20 = ((df['EPC_ratio'] >= 0.8) & (df['EPC_ratio'] <= 1.2)).mean() * 100
    w30 = ((df['EPC_ratio'] >= 0.7) & (df['EPC_ratio'] <= 1.3)).mean() * 100
    print(f"  Within ±10%:      {w10:.0f}%")
    print(f"  Within ±20%:      {w20:.0f}%")
    print(f"  Within ±30%:      {w30:.0f}%")

    # By cluster
    print(f"\n  BY CLUSTER:")
    print(f"  {'Cluster':<16s} {'n':>4s} {'EP_epc':>7s} {'EP_sim':>7s} "
          f"{'Ratio':>6s} {'MAE':>6s} {'±10%':>5s}")
    print(f"  {'-'*16} {'-'*4} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*5}")
    for cluster in sorted(df["Cluster"].unique()):
        sub = df[df["Cluster"] == cluster]
        mae = sub["error_abs"].abs().mean()
        pct10 = ((sub['EPC_ratio'] >= 0.9) & (sub['EPC_ratio'] <= 1.1)).mean() * 100
        print(f"  {cluster:<16s} {len(sub):4d} {sub['EP_epc'].mean():7.0f} "
              f"{sub['EP_sim'].mean():7.1f} {sub['EPC_ratio'].mean():6.2f} "
              f"{mae:6.1f} {pct10:5.0f}%")

    # By ventilation
    print(f"\n  BY VENTILATION SYSTEM:")
    for vent in sorted(df["Ventilation"].unique()):
        sub = df[df["Ventilation"] == vent]
        print(f"    {vent:3s}: n={len(sub):3d}, "
              f"mean_ratio={sub['EPC_ratio'].mean():.2f}, "
              f"median={sub['EPC_ratio'].median():.2f}, "
              f"MAE={sub['error_abs'].abs().mean():.1f}, "
              f"EP_epc={sub['EP_epc'].mean():.0f}, "
              f"EP_sim={sub['EP_sim'].mean():.0f}")

    # ── Plots ──────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    # 1: Sim vs EPC scatter, coloured by cluster
    ax = axes[0, 0]
    clusters = sorted(df["Cluster"].unique())
    cmap = plt.cm.get_cmap("tab10", len(clusters))
    for i, cluster in enumerate(clusters):
        sub = df[df["Cluster"] == cluster]
        ax.scatter(sub["EP_epc"], sub["EP_sim"], label=f"{cluster} ({len(sub)})",
                   alpha=0.6, s=40, c=[cmap(i)], edgecolors="k", linewidths=0.3)
    ep_min = min(df["EP_epc"].min(), df["EP_sim"].min()) - 10
    ep_max = max(df["EP_epc"].max(), df["EP_sim"].max()) + 10
    ep_range = [ep_min, ep_max]
    ax.plot(ep_range, ep_range, "r--", alpha=0.5, label="y=x")
    ax.plot(ep_range, [x * 1.2 for x in ep_range], "orange",
            linestyle=":", alpha=0.3)
    ax.plot(ep_range, [x * 0.8 for x in ep_range], "orange",
            linestyle=":", alpha=0.3)
    ax.set_xlabel("EP_epc (kWh/m²)")
    ax.set_ylabel("EP_sim (kWh/m²)")
    ax.set_title("Simulated vs. Measured EP — All 222 Buildings")
    ax.legend(fontsize=7, loc="upper left")
    ax.set_aspect("equal")
    ax.set_xlim(ep_range)
    ax.set_ylim(ep_range)

    # 2: EPC ratio histogram
    ax = axes[0, 1]
    ax.hist(df["EPC_ratio"], bins=30, edgecolor="black", alpha=0.7, color="steelblue")
    ax.axvline(x=1.0, color="red", linestyle="--", label="Perfect (1.0)")
    ax.axvline(x=df["EPC_ratio"].mean(), color="orange", linestyle="-",
               label=f"Mean ({df['EPC_ratio'].mean():.2f})")
    ax.set_xlabel("EPC Ratio (sim / measured)")
    ax.set_ylabel("Count")
    ax.set_title("Distribution of EPC Ratio")
    ax.legend()

    # 3: EPC ratio by cluster (boxplot)
    ax = axes[1, 0]
    cluster_groups = [df[df["Cluster"] == c]["EPC_ratio"].values for c in clusters]
    bp = ax.boxplot(cluster_groups, labels=[c.replace("-vent_", "\n") for c in clusters],
                    patch_artist=True)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(cmap(i))
        patch.set_alpha(0.5)
    ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.7)
    ax.axhline(y=0.8, color="orange", linestyle=":", alpha=0.5)
    ax.axhline(y=1.2, color="orange", linestyle=":", alpha=0.5)
    ax.set_ylabel("EPC Ratio")
    ax.set_title("Accuracy by Cluster")
    ax.tick_params(axis="x", rotation=45, labelsize=8)

    # 4: Error vs EP_epc
    ax = axes[1, 1]
    ax.scatter(df["EP_epc"], df["error_pct"], alpha=0.5, s=30,
               edgecolors="k", linewidths=0.3, c="steelblue")
    ax.axhline(y=0, color="red", linestyle="--", alpha=0.7)
    ax.axhspan(-20, 20, color="green", alpha=0.05)
    ax.set_xlabel("EP_epc (kWh/m²)")
    ax.set_ylabel("Error (%)")
    ax.set_title("Prediction Error vs. Measured EP")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "all_222_results.png", dpi=150)
    plt.close()
    print(f"\n  → Saved figures/all_222_results.png")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    json_path = _find_opaque_json()

    # ── Load calibrated lever values ────────────────────────────────
    cal_df = pd.read_csv(EDA_DIR / "results_multilever_v2.csv")
    log.info("Loaded calibrated levers for %d clusters", len(cal_df))

    # ── Build construction sets ─────────────────────────────────────
    cluster_params = build_cluster_csets(cal_df, json_path)

    # ── Load all 222 buildings ──────────────────────────────────────
    clusters = pd.read_csv(EDA_DIR / "clusters_betsi.csv")
    buildings = (
        clusters[["FormularId", "global_cluster"]]
        .drop_duplicates(subset="FormularId")
    )
    log.info("Total unique buildings: %d", len(buildings))

    # ── Check for previously completed results (resume support) ─────
    already_done = set()
    prev_results = []
    if RESULTS_CSV.exists():
        prev = pd.read_csv(RESULTS_CSV)
        already_done = set(prev["FormularId"].unique())
        prev_results = prev.to_dict("records")
        log.info("  Resuming: %d already done", len(already_done))

    remaining = buildings[~buildings["FormularId"].isin(already_done)]
    log.info("  %d remaining to simulate", len(remaining))

    # ── Simulate ─────────────────────────────────────────────────────
    new_results = []
    failed = []

    for i, (_, row) in enumerate(remaining.iterrows()):
        fid = int(row["FormularId"])
        cluster = row["global_cluster"]

        log.info("─" * 60)
        log.info("[%d/%d] FormularId=%d  cluster=%s",
                 i + 1, len(remaining), fid, cluster)

        try:
            r = simulate_building(fid, cluster, cluster_params)
            new_results.append(r)
            log.info("  → EP_epc=%s, EP_sim=%.1f, ratio=%.2f",
                     r["EP_epc"], r["EP_sim"], r["EPC_ratio"])
        except Exception:
            log.error("FAILED FormularId=%d cluster=%s", fid, cluster)
            traceback.print_exc()
            failed.append({"FormularId": fid, "Cluster": cluster,
                           "Error": traceback.format_exc()[-200:]})

        # Incremental save every 10 buildings
        if (i + 1) % 10 == 0:
            all_so_far = prev_results + new_results
            pd.DataFrame(all_so_far).to_csv(RESULTS_CSV, index=False)
            log.info("  [checkpoint] saved %d results", len(all_so_far))

    # ── Final save ──────────────────────────────────────────────────
    all_results = prev_results + new_results
    if all_results:
        results_df = pd.DataFrame(all_results)
        results_df.to_csv(RESULTS_CSV, index=False)
        log.info("Wrote %d results to %s", len(results_df), RESULTS_CSV)

        if failed:
            print(f"\n  ⚠ {len(failed)} buildings failed:")
            for f in failed:
                print(f"    FormularId={f['FormularId']}  {f['Cluster']}")
            print(f"  Successfully simulated: {len(results_df)}/{len(buildings)}")

        analyse_results(results_df)
    else:
        log.warning("No results to analyse")


if __name__ == "__main__":
    main()
