"""
Step 11 — Simulate cluster archetypes with BETSI construction sets.

Uses the 8 cluster archetypes from Step 10, each mapped to a BETSI
template (CONC_SLAB or CONC_TOWER).  Replaces the generic CMF_1960_1
construction set with BETSI-median layer compositions.

Pipeline:
  1. Build BETSI_CONC_SLAB and BETSI_CONC_TOWER construction sets via
     epsm_data.build_archetype_from_spec (thermal props from opaque_material.json)
  2. Register them in the pbgenerator construction-set registry
  3. For each cluster archetype, simulate with the matched BETSI set
  4. Compare EP_sim vs EP_epc

Outputs:
  EDA/results_betsi.csv
  EDA/figures/archetype_betsi_results.png
"""
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
IDF_DIR = PROJECT_DIR / "idf" / "betsi"
OUTPUT_DIR = PROJECT_DIR / "results" / "betsi"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# BETSI CONSTRUCTION SPECS
# ═══════════════════════════════════════════════════════════════════
# Layer compositions from build_betsi_archetypes.py, insulation
# thicknesses back-calculated from BETSI median U-values.
# Mineral wool old: λ=0.042 W/mK (pre-1975 installations)

def _find_opaque_json():
    """Locate opaque_material.json via installed epsm_data package."""
    import epsm_data
    root = Path(epsm_data.__file__).resolve().parent.parent
    p = root / "Data" / "opaque_material.json"
    if not p.exists():
        # Lowercase fallback
        p = root / "data" / "opaque_material.json"
    return p


# Material shorthand: (honeybee_id, boverket_id)
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


# ── BETSI_CONC_SLAB (concrete slab block, 1960-75) ────────────────
# Target: wall U=0.25, roof U=0.15, floor U=0.27, window U=2.00
SPEC_CONC_SLAB = {
    "archetype_id": "BETSI_CONC_SLAB",
    "display_name": "Concrete slab block (1960-75)",
    "construction_year": 1968,
    "building_typology": "multi_family",
    "elements": {
        "EXT_WALL": {"components": [{"shearing_layer": "Skin", "layers": [
            _L("plaster", 0.015),
            _L("mw_old", 0.155),       # 155mm MW → U≈0.25
            _L("concrete", 0.150),
            _L("gypsum", 0.013),
        ]}]},
        "ROOF": {"components": [{"shearing_layer": "Skin", "layers": [
            _L("roof_felt", 0.006),
            _L("mw_old", 0.270),        # → U≈0.15
            _L("conc_roof", 0.150),
        ]}]},
        "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
            _L("conc_floor", 0.150),
            _L("mw_old", 0.270),
        ]}]},
        "INTERMEDIATE_FLOOR": {"components": [{"shearing_layer": "Structure",
            "layers": [_L("conc_floor", 0.200)]}]},
        "GROUND_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
            _L("eps", 0.105),           # → U≈0.27
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

# ── BETSI_CONC_TOWER (concrete tower slab, 1960-75) ───────────────
# Target: wall U=0.20, roof U=0.14, floor U=0.22, window U=1.90
SPEC_CONC_TOWER = {
    "archetype_id": "BETSI_CONC_TOWER",
    "display_name": "Concrete tower slab (1960-75)",
    "construction_year": 1970,
    "building_typology": "multi_family",
    "elements": {
        "EXT_WALL": {"components": [{"shearing_layer": "Skin", "layers": [
            _L("plaster", 0.015),
            _L("mw_old", 0.195),       # 195mm MW → U≈0.20
            _L("concrete", 0.150),
            _L("gypsum", 0.013),
        ]}]},
        "ROOF": {"components": [{"shearing_layer": "Skin", "layers": [
            _L("roof_felt", 0.006),
            _L("mw_old", 0.290),        # → U≈0.14
            _L("conc_roof", 0.150),
        ]}]},
        "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
            _L("conc_floor", 0.150),
            _L("mw_old", 0.290),
        ]}]},
        "INTERMEDIATE_FLOOR": {"components": [{"shearing_layer": "Structure",
            "layers": [_L("conc_floor", 0.200)]}]},
        "GROUND_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
            _L("eps", 0.130),           # → U≈0.22
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


BETSI_SPECS = {
    "BETSI_CONC_SLAB": SPEC_CONC_SLAB,
    "BETSI_CONC_TOWER": SPEC_CONC_TOWER,
}


# ═══════════════════════════════════════════════════════════════════
# BUILD + REGISTER CONSTRUCTION SETS
# ═══════════════════════════════════════════════════════════════════

def build_and_register():
    """Build BETSI construction sets and register them in CONSTRUCTION_SETS."""
    from epsm_data import build_archetype_from_spec

    json_path = _find_opaque_json()
    log.info("Using opaque_material.json: %s", json_path)

    for spec_id, spec in BETSI_SPECS.items():
        if spec_id in CONSTRUCTION_SETS:
            log.info("  %s already registered, skipping", spec_id)
            continue

        log.info("  Building %s ...", spec_id)
        arch = build_archetype_from_spec(spec, json_path, skip_api=True)
        cset = ConstructionSetDef.from_epsm_archetype(arch)

        # Bind in closure to avoid late-binding
        CONSTRUCTION_SETS[spec_id] = (lambda cs: lambda: cs)(cset)
        log.info("  → Registered %s", spec_id)

    return True


# ═══════════════════════════════════════════════════════════════════
# SIMULATION
# ═══════════════════════════════════════════════════════════════════

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


def simulate_building(formular_id, fastighet, adress, cluster_name,
                      betsi_template):
    """Run simulation for an archetype building with a BETSI construction set."""
    tag = _safe_id(f"{cluster_name}_{fastighet}")
    log.info("=" * 60)
    log.info("SIMULATE  %s  (%s, %s → %s)",
             cluster_name, adress, fastighet, betsi_template)
    log.info("=" * 60)

    # Load footprints + EPC metadata
    all_fps = load_footprints(formular_id=formular_id, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    candidates = _dedup_footprints(flerfamilj if flerfamilj else all_fps)
    log.info("  %d unique footprint(s)", len(candidates))

    epc = load_epc_metadata(formular_id)
    vent_sys = detect_ventilation_system(formular_id)
    epc_energy = load_epc_energy(formular_id)
    floors = epc["num_floors"]
    basement_floors = epc["num_basement_floors"]

    # Atemp matching via depth solving
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

    total_heating = 0.0
    total_cooling = 0.0
    total_dhw = 0.0
    total_site = 0.0
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

        # Create params with BETSI construction set
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
        params = replace(params, construction_set=betsi_template)

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

    return {
        "Cluster": cluster_name,
        "FormularId": formular_id,
        "Fastighet": fastighet,
        "Adress": adress,
        "Byggar": epc["construction_year"],
        "Floors": floors,
        "Atemp_epc": epc["atemp"],
        "Atemp_sim": round(total_atemp, 1),
        "Ventilation": vent_sys,
        "BETSI_template": betsi_template,
        "EP_epc": epc["energi_prestanda"],
        "EP_sim": round(comp["epc_total_kwh"] / total_atemp, 1),
        "EPC_ratio": round(comp["epc_ratio"], 2),
    }


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    # ── Build + register BETSI construction sets ───────────────────
    log.info("Building BETSI construction sets...")
    build_and_register()

    # ── Load cluster archetypes from Step 10 ───────────────────────
    archetypes = pd.read_csv(EDA_DIR / "archetypes_betsi.csv")

    # Get IdHusnr mapping for footprint lookup
    full_data = pd.read_csv(EDA_DIR / "uddevalla_mfh_features.csv")
    husnr_map = (
        full_data[["FormularId", "IdHusnr"]]
        .drop_duplicates(subset="FormularId")
        .set_index("FormularId")["IdHusnr"]
    )

    # ── Simulate each archetype ────────────────────────────────────
    log.info("\nSimulating %d archetype buildings with BETSI construction sets...",
             len(archetypes))

    sim_results = []
    failed = []

    for _, a in archetypes.iterrows():
        fid = int(a["FormularId"])
        fastighet = a["IdFastBet"]
        adress = a["IdAdr"]
        cluster = a["global_cluster"]
        template = a["betsi_template"]

        try:
            r = simulate_building(fid, fastighet, adress, cluster, template)
            r["cluster_size"] = int(a["cluster_size"])
            r["cluster_mean_ep"] = round(
                float(a["ep"]), 1)
            r["representativeness"] = a["representativeness"]
            r["distinctness"] = a["distinctness"]
            sim_results.append(r)
            log.info("  %s → EP_sim=%.1f, EP_epc=%.0f, ratio=%.2f",
                     cluster, r["EP_sim"], r["EP_epc"], r["EPC_ratio"])
        except Exception:
            log.error("  FAILED %s (%s, fid=%d)", cluster, fastighet, fid)
            traceback.print_exc()
            failed.append({"Cluster": cluster, "FormularId": fid,
                           "Error": traceback.format_exc()[-200:]})

    if not sim_results:
        log.error("No successful simulations!")
        return

    results_df = pd.DataFrame(sim_results)
    results_df.to_csv(EDA_DIR / "results_betsi.csv", index=False)

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  BETSI ARCHETYPE SIMULATION RESULTS")
    print(f"{'='*100}")
    print(f"  {'Cluster':<16s} {'n':>4s} {'BETSI':>18s} "
          f"{'EP_epc':>7s} {'EP_sim':>7s} {'Ratio':>6s} ")
    print(f"  {'-'*16} {'-'*4} {'-'*18} "
          f"{'-'*7} {'-'*7} {'-'*6} ")

    for _, r in results_df.iterrows():
        print(f"  {r['Cluster']:<16s} {r['cluster_size']:4.0f} "
              f"{r['BETSI_template']:>18s} "
              f"{r['EP_epc']:7.0f} {r['EP_sim']:7.1f} "
              f"{r['EPC_ratio']:6.2f}")

    n = len(results_df)
    print(f"\n  Total archetypes: {n}")
    print(f"  Mean EPC ratio: {results_df['EPC_ratio'].mean():.2f}")
    within_10 = ((results_df["EPC_ratio"] >= 0.9)
                 & (results_df["EPC_ratio"] <= 1.1)).mean()
    within_20 = ((results_df["EPC_ratio"] >= 0.8)
                 & (results_df["EPC_ratio"] <= 1.2)).mean()
    print(f"  Within ±10%: {within_10*100:.0f}% ({int(within_10*n)}/{n})")
    print(f"  Within ±20%: {within_20*100:.0f}% ({int(within_20*n)}/{n})")

    if failed:
        print(f"\n  Failed: {len(failed)}")
        for f in failed:
            print(f"    {f['Cluster']}: {f['Error']}")

    # ── Load CMF_1960_1 baseline for comparison ────────────────────
    baseline_path = EDA_DIR / "results_archetypes_cmf1960.csv"
    if baseline_path.exists():
        baseline = pd.read_csv(baseline_path)
        print(f"\n  Comparison to CMF_1960_1 baseline (Step 9):")
        print(f"  {'Metric':<20s} {'CMF_1960_1':>12s} {'BETSI':>12s}")
        print(f"  {'-'*20} {'-'*12} {'-'*12}")
        print(f"  {'Mean ratio':<20s} "
              f"{baseline['EPC_ratio'].mean():12.2f} "
              f"{results_df['EPC_ratio'].mean():12.2f}")
        print(f"  {'Median ratio':<20s} "
              f"{baseline['EPC_ratio'].median():12.2f} "
              f"{results_df['EPC_ratio'].median():12.2f}")

    # ── Plot ───────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # 1: Scatter EP_sim vs EP_epc
    ax = axes[0]
    colors = {"S-vent": "#4C72B0", "F-vent": "#DD8452",
              "FTX-vent": "#C44E52", "Renovated": "#8172B3"}
    for _, r in results_df.iterrows():
        grp = r["Cluster"].rsplit("_C", 1)[0]
        ax.scatter(r["EP_epc"], r["EP_sim"], c=colors.get(grp, "gray"),
                   s=max(20, r["cluster_size"] * 2),
                   alpha=0.7, edgecolors="k", linewidths=0.5)
    ep_min = min(results_df["EP_epc"].min(), results_df["EP_sim"].min()) - 10
    ep_max = max(results_df["EP_epc"].max(), results_df["EP_sim"].max()) + 10
    ax.plot([ep_min, ep_max], [ep_min, ep_max], "k--", alpha=0.4)
    ax.plot([ep_min, ep_max], [ep_min*0.9, ep_max*0.9],
            "orange", ls=":", alpha=0.3)
    ax.plot([ep_min, ep_max], [ep_min*1.1, ep_max*1.1],
            "orange", ls=":", alpha=0.3)
    ax.set(xlabel="EP_epc (kWh/m²)", ylabel="EP_sim (kWh/m²)",
           title="BETSI Archetype: EP_sim vs EP_epc")
    ax.grid(True, alpha=0.3)

    # Legend
    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], marker="o", color="w",
                     markerfacecolor=c, markersize=8, label=g)
              for g, c in colors.items()]
    ax.legend(handles=legend)

    # 2: Bar chart of EPC ratios
    ax = axes[1]
    clusters = results_df["Cluster"].values
    ratios = results_df["EPC_ratio"].values
    bar_colors = [colors.get(c.rsplit("_C", 1)[0], "gray") for c in clusters]
    bars = ax.bar(range(len(clusters)), ratios, color=bar_colors, alpha=0.7,
                  edgecolor="k", linewidth=0.5)
    ax.axhline(1.0, color="k", ls="--", alpha=0.4)
    ax.axhspan(0.9, 1.1, alpha=0.1, color="green")
    ax.set_xticks(range(len(clusters)))
    ax.set_xticklabels(clusters, rotation=45, ha="right", fontsize=8)
    ax.set(ylabel="EPC ratio (sim/measured)", title="Accuracy by Cluster")
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "archetype_betsi_results.png", dpi=150)
    plt.close()
    log.info("  → Saved figures/archetype_betsi_results.png")


if __name__ == "__main__":
    main()
