"""
Step 9 — Identify archetype buildings per hierarchical cluster.

Following Dahlström et al. (2024): for each cluster, compute the centroid
(mean of clustering features), find the real building closest to it
(Euclidean distance on standardised features), and designate it as the
archetype. Then simulate ONLY the archetype building for each cluster.

Outputs:
  - EDA/archetypes_hierarchical.csv
  - EDA/figures/archetype_identification.png
"""
import logging
import traceback
import re
import unicodedata
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler

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

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

EDA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EDA_DIR.parent
IDF_DIR = PROJECT_DIR / "idf" / "archetypes"
OUTPUT_DIR = PROJECT_DIR / "results" / "archetypes"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

CLUSTER_FEATURES = [
    "fp_area", "fp_perimeter", "fp_compactness", "fp_slenderness",
    "floors", "atemp", "derived_volume", "atemp_per_apt", "n_footprints",
]


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


def identify_archetypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each cluster, find the building closest to the centroid
    (Euclidean distance on standardised clustering features).

    Returns DataFrame with one row per cluster: the archetype building.
    """
    results = []

    for cluster_name, group in df.groupby("global_cluster"):
        if len(group) == 0:
            continue

        # Deduplicate to unique buildings
        unique = group.drop_duplicates(subset="FormularId")
        feat = unique[CLUSTER_FEATURES].values

        # Standardise within this cluster's parent group
        scaler = StandardScaler()
        feat_std = scaler.fit_transform(feat)

        # Centroid = mean of standardised features
        centroid = feat_std.mean(axis=0)

        # Euclidean distance from each building to centroid
        dists = np.sqrt(((feat_std - centroid) ** 2).sum(axis=1))
        idx_closest = dists.argmin()

        arch = unique.iloc[idx_closest].copy()
        arch["dist_to_centroid"] = dists[idx_closest]
        arch["cluster_size"] = len(unique)

        # Representativeness (Eq. 7 from Dahlström et al.)
        # Using normalised features (min-max) for R_i calculation
        feat_norm = (feat - feat.min(axis=0)) / (feat.max(axis=0) - feat.min(axis=0) + 1e-12)
        centroid_norm = feat_norm.mean(axis=0)
        arch_norm = feat_norm[idx_closest]
        R_i = np.mean(1 - np.abs(centroid_norm - arch_norm)) * 100
        arch["representativeness"] = round(R_i, 1)

        # Cluster spread (Eq. 10 from Dahlström et al.)
        S_tot = np.mean(feat_norm.std(axis=0)) * 100
        arch["cluster_spread"] = round(S_tot, 1)

        # Distinctness (Eq. 11)
        D_i = 0.5 * (R_i / 100) + 0.5 * (1 - S_tot / 100)
        arch["distinctness"] = round(D_i * 100, 1)

        results.append(arch)

    return pd.DataFrame(results)


def simulate_building(formular_id, fastighet, husnr, adress, cluster_name):
    """Run CMF_1960_1 simulation for a single archetype building."""
    tag = _safe_id(f"{cluster_name}_{fastighet}")
    log.info("=" * 60)
    log.info("ARCHETYPE  %s  (FormularId=%d, %s)", cluster_name, formular_id, adress)
    log.info("=" * 60)

    all_fps = load_footprints(formular_id=formular_id, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    candidates = _dedup_footprints(flerfamilj if flerfamilj else all_fps)
    log.info("  %d unique footprint(s) after dedup", len(candidates))

    epc = load_epc_metadata(formular_id)
    vent_sys = detect_ventilation_system(formular_id)
    epc_energy = load_epc_energy(formular_id)
    floors = epc["num_floors"]
    basement_floors = epc["num_basement_floors"]

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
        "EP_epc": epc["energi_prestanda"],
        "EP_sim": round(comp["epc_total_kwh"] / total_atemp, 1),
        "EPC_ratio": round(comp["epc_ratio"], 2),
    }


def main():
    # ── Load cluster data ───────────────────────────────────────────────
    clusters = pd.read_csv(EDA_DIR / "clusters_1960s_hierarchical.csv")

    # Get IdHusnr from features CSV
    full_data = pd.read_csv(EDA_DIR / "uddevalla_mfh_features.csv")
    husnr_map = (
        full_data[["FormularId", "IdHusnr"]]
        .drop_duplicates(subset="FormularId")
        .set_index("FormularId")["IdHusnr"]
    )

    # ── Step 1: Identify archetype buildings ────────────────────────────
    log.info("Identifying archetype buildings per cluster...")
    archetypes = identify_archetypes(clusters)

    # Print summary table
    print(f"\n{'='*100}")
    print(f"  ARCHETYPE IDENTIFICATION — Dahlström et al. (2024) method")
    print(f"{'='*100}")
    print(f"  {'Cluster':<18s} {'n':>4s} {'Archetype':>20s} {'EP':>5s} "
          f"{'Atemp':>6s} {'Fl':>3s} {'R_i':>6s} {'S_tot':>6s} {'D_i':>6s}")
    print(f"  {'-'*18} {'-'*4} {'-'*20} {'-'*5} {'-'*6} {'-'*3} {'-'*6} {'-'*6} {'-'*6}")

    for _, a in archetypes.iterrows():
        print(f"  {a['global_cluster']:<18s} {a['cluster_size']:4.0f} "
              f"{a['IdFastBet']:>20s} {a['ep']:5.0f} {a['atemp']:6.0f} "
              f"{a['floors']:3.0f} {a['representativeness']:5.1f}% "
              f"{a['cluster_spread']:5.1f}% {a['distinctness']:5.1f}%")

    # Save archetypes CSV
    arch_csv = EDA_DIR / "archetypes_hierarchical.csv"
    archetypes.to_csv(arch_csv, index=False)
    log.info("Saved %d archetypes to %s", len(archetypes), arch_csv)

    # ── Step 2: Simulate archetype buildings ────────────────────────────
    log.info("\nSimulating archetype buildings...")
    sim_results = []
    failed = []

    for _, a in archetypes.iterrows():
        fid = int(a["FormularId"])
        fastighet = a["IdFastBet"]
        husnr = int(husnr_map.get(fid, 0))
        adress = a["IdAdr"]
        cluster_name = a["global_cluster"]

        try:
            r = simulate_building(fid, fastighet, husnr, adress, cluster_name)
            r["cluster_size"] = int(a["cluster_size"])
            r["cluster_mean_ep"] = round(a["ep"], 1)  # archetype EP from EPC
            r["representativeness"] = a["representativeness"]
            r["distinctness"] = a["distinctness"]
            sim_results.append(r)
            log.info("  %s → EP_sim=%.1f, EPC_ratio=%.2f",
                     cluster_name, r["EP_sim"], r["EPC_ratio"])
        except Exception:
            log.error("  FAILED %s (%s, fid=%d)", cluster_name, fastighet, fid)
            traceback.print_exc()
            failed.append({"Cluster": cluster_name, "FormularId": fid,
                           "Error": traceback.format_exc()[-200:]})

    if not sim_results:
        log.warning("No results to analyse")
        return

    results_df = pd.DataFrame(sim_results)
    results_df.to_csv(EDA_DIR / "results_archetypes_cmf1960.csv", index=False)

    # ── Step 3: Summary ─────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  ARCHETYPE SIMULATION RESULTS")
    print(f"{'='*100}")
    print(f"  {'Cluster':<18s} {'n':>4s} {'Archetype':>15s} {'EP_epc':>7s} "
          f"{'EP_sim':>7s} {'Ratio':>6s} {'R_i':>6s} {'D_i':>6s}")
    print(f"  {'-'*18} {'-'*4} {'-'*15} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*6}")

    for _, r in results_df.iterrows():
        print(f"  {r['Cluster']:<18s} {r['cluster_size']:4.0f} "
              f"{r['Fastighet']:>15s} {r['EP_epc']:7.0f} {r['EP_sim']:7.1f} "
              f"{r['EPC_ratio']:6.2f} {r['representativeness']:5.1f}% "
              f"{r['distinctness']:5.1f}%")

    # Overall stats
    print(f"\n  Total archetypes simulated: {len(results_df)}")
    print(f"  Mean EPC ratio: {results_df['EPC_ratio'].mean():.2f}")
    print(f"  Within ±10%: {((results_df['EPC_ratio'] >= 0.9) & (results_df['EPC_ratio'] <= 1.1)).mean()*100:.0f}%")
    print(f"  Within ±20%: {((results_df['EPC_ratio'] >= 0.8) & (results_df['EPC_ratio'] <= 1.2)).mean()*100:.0f}%")

    if failed:
        print(f"\n  Failed: {len(failed)}")
        for f in failed:
            print(f"    {f['Cluster']}: {f['Error']}")

    # ── Step 4: Plot ────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # 1: Scatter EP_sim vs EP_epc
    ax = axes[0]
    groups = {"S-vent": "tab:blue", "F-vent": "tab:orange",
              "FTX-vent": "tab:red", "FT-vent": "tab:green",
              "Renovated": "tab:purple"}
    for _, r in results_df.iterrows():
        grp = r["Cluster"].rsplit("_C", 1)[0]
        color = groups.get(grp, "gray")
        ax.scatter(r["EP_epc"], r["EP_sim"], c=color, s=r["cluster_size"],
                   alpha=0.7, edgecolors="k", linewidths=0.5)
    ep_range = [40, max(results_df["EP_epc"].max(), results_df["EP_sim"].max()) + 20]
    ax.plot(ep_range, ep_range, "r--", alpha=0.5)
    ax.plot(ep_range, [x * 1.1 for x in ep_range], "orange", linestyle=":", alpha=0.3)
    ax.plot(ep_range, [x * 0.9 for x in ep_range], "orange", linestyle=":", alpha=0.3)
    ax.set_xlabel("EP (EPC, kWh/m²)")
    ax.set_ylabel("EP (simulated, kWh/m²)")
    ax.set_title("Archetype EP: Simulated vs. Measured")
    ax.set_aspect("equal")
    ax.set_xlim(ep_range)
    ax.set_ylim(ep_range)

    # 2: Ratio distribution
    ax = axes[1]
    ax.hist(results_df["EPC_ratio"], bins=15, edgecolor="k", alpha=0.7, color="steelblue")
    ax.axvline(x=1.0, color="red", linestyle="--")
    ax.axvline(x=results_df["EPC_ratio"].mean(), color="orange", linestyle="-",
               label=f"Mean ({results_df['EPC_ratio'].mean():.2f})")
    ax.set_xlabel("EPC Ratio (sim/measured)")
    ax.set_ylabel("Count")
    ax.set_title("Archetype Accuracy Distribution")
    ax.legend()

    # 3: Representativeness vs distinctness
    ax = axes[2]
    for _, r in results_df.iterrows():
        grp = r["Cluster"].rsplit("_C", 1)[0]
        color = groups.get(grp, "gray")
        ax.scatter(r["representativeness"], r["distinctness"], c=color,
                   s=r["cluster_size"], alpha=0.7, edgecolors="k", linewidths=0.5)
        ax.annotate(r["Cluster"][-4:], (r["representativeness"], r["distinctness"]),
                    fontsize=6, ha="left")
    ax.set_xlabel("Representativeness R_i (%)")
    ax.set_ylabel("Distinctness D_i (%)")
    ax.set_title("Cluster Quality Metrics")

    # Legend for groups
    for grp, color in groups.items():
        ax.scatter([], [], c=color, label=grp, s=50)
    ax.legend(fontsize=7, loc="lower left")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "archetype_identification.png", dpi=150)
    plt.close()
    log.info("Saved archetype_identification.png")


if __name__ == "__main__":
    main()
