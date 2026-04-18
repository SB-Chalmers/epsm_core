"""
Step 8 — Apply CMF_1960_1 archetype to all S-vent_C4 buildings.

Runs EnergyPlus simulations for every unique building (FormularId) in
the hierarchical cluster S-vent_C4 (4 buildings, all natural-draft ventilation).

Outputs:
  - results/svent_c4/   (EnergyPlus output per building)
  - idf/svent_c4/       (IDF files per building)
  - EDA/results_svent_c4_cmf1960.csv
  - EDA/figures/svent_c4_error_analysis.png
"""
import csv
import logging
import re
import traceback
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

EDA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EDA_DIR.parent
IDF_DIR = PROJECT_DIR / "idf" / "svent_c4"
OUTPUT_DIR = PROJECT_DIR / "results" / "svent_c4"
RESULTS_CSV = EDA_DIR / "results_svent_c4_cmf1960.csv"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


def _safe_id(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", s)
    return s


def _dedup_footprints(fps: list) -> list:
    seen: set[str] = set()
    unique = []
    for fp in fps:
        if fp.objektidentitet not in seen:
            seen.add(fp.objektidentitet)
            unique.append(fp)
    return unique


def simulate_building(formular_id: int, fastighet: str, husnr: int, adress: str):
    """Run CMF_1960_1 simulation for a single building. Returns result dict."""
    tag = _safe_id(f"{fastighet}_h{husnr}")
    log.info("=" * 60)
    log.info("START  %s  (FormularId=%d, %s)", tag, formular_id, adress)
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
    log.info("  vent_sys=%s, year=%s, basement=%d",
             vent_sys, epc["construction_year"], basement_floors)

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
        log.info("  PRE-FLIGHT: fp_area=%.0f m² × %d fl = %.0f m² > EPC %d m²"
                 " → solved depths: %s",
                 total_fp_area, total_floors, sim_atemp_est, epc_atemp,
                 [f"{d:.1f}" for d in fp_depths])
    else:
        fp_depths = [0.0] * len(candidates)
        if epc_atemp and epc_atemp > 0:
            log.info("  PRE-FLIGHT: fp_area=%.0f m² × %d fl = %.0f m²"
                     " ≤ EPC %d m² → depth=0 (full footprint)",
                     total_fp_area, total_floors, sim_atemp_est, epc_atemp)

    garage_pct = 0.0
    if epc["garage_m2"] and epc["atemp"]:
        garage_pct = min(100.0 - epc["residential_pct"],
                         epc["garage_m2"] / epc["atemp"] * 100.0)

    total_heating_kwh = 0.0
    total_cooling_kwh = 0.0
    total_dhw_kwh = 0.0
    total_site_kwh = 0.0
    total_atemp = 0.0
    total_gross = 0.0
    depths = []

    for idx, fp in enumerate(candidates):
        fp_tag = f"{tag}_fp{idx}" if len(candidates) > 1 else tag
        depth = fp_depths[idx]
        depths.append(depth)

        bldg = build_rooms(
            footprint_pts=fp.footprint_pts,
            floor_height=2.7, num_floors=floors,
            wwr=FacadeWWR(0, 0, 0, 0),
            apartment_depth=depth,
            identifier="preview",
            num_basement_floors=basement_floors,
        )
        log.info("  fp%d: depth=%.1fm  perim_atemp=%.0f m²  gross=%.0f m²",
                 idx, depth, bldg.perimeter_floor_area, bldg.total_floor_area)

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

        total_heating_kwh += sim["heating_kwh"]
        total_cooling_kwh += sim["cooling_kwh"]
        total_dhw_kwh += sim["dhw_kwh"]
        total_site_kwh += sim["site_kwh"]
        total_atemp += bldg.perimeter_floor_area
        total_gross += bldg.total_floor_area

    log.info("  TOTAL: perim_atemp=%.0f m², gross=%.0f m²,"
             " epc_atemp=%s (%d footprint(s))",
             total_atemp, total_gross, epc["atemp"], len(candidates))

    agg_sim = {
        "heating_kwh": total_heating_kwh,
        "cooling_kwh": total_cooling_kwh,
        "dhw_kwh": total_dhw_kwh,
        "site_kwh": total_site_kwh,
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
        "FormularId": formular_id,
        "Fastighet": fastighet,
        "Husnr": husnr,
        "Adress": adress,
        "Byggar": epc["construction_year"],
        "Atemp_epc": epc["atemp"],
        "Atemp_sim": round(total_atemp, 1),
        "Apt_depth": round(max(depths), 1),
        "Floors": floors,
        "Num_footprints": len(candidates),
        "Ventilation": vent_sys,
        "Res_pct": epc["residential_pct"],
        "Garage_pct": round(garage_pct, 1),
        "EP_epc": epc["energi_prestanda"],
        "Heating_kwh_m2": round(total_heating_kwh / total_atemp, 1),
        "Cooling_kwh_m2": round(total_cooling_kwh / total_atemp, 1),
        "DHW_kwh_m2": round(total_dhw_kwh / total_atemp, 1),
        "EP_sim": round(comp["epc_total_kwh"] / total_atemp, 1),
        "EPC_ratio": round(comp["epc_ratio"], 2),
    }


def analyse_results(results_df: pd.DataFrame):
    """Generate error analysis plots and print summary statistics."""
    df = results_df.copy()
    df["error_abs"] = df["EP_sim"] - df["EP_epc"]
    df["error_pct"] = (df["EP_sim"] - df["EP_epc"]) / df["EP_epc"] * 100

    print(f"\n{'='*70}")
    print(f"  S-VENT_C4 — CMF_1960_1 ARCHETYPE APPLICABILITY ANALYSIS")
    print(f"{'='*70}")
    print(f"  Total buildings simulated: {len(df)}")
    print(f"  Mean EPC_ratio:  {df['EPC_ratio'].mean():.2f}")
    print(f"  Median EPC_ratio: {df['EPC_ratio'].median():.2f}")
    print(f"  Std EPC_ratio:   {df['EPC_ratio'].std():.2f}")
    print(f"  MAE:             {df['error_abs'].abs().mean():.1f} kWh/m²")
    print(f"  RMSE:            {np.sqrt((df['error_abs']**2).mean()):.1f} kWh/m²")
    print(f"  Within ±10%:     {((df['EPC_ratio'] >= 0.9) & (df['EPC_ratio'] <= 1.1)).mean()*100:.0f}%")
    print(f"  Within ±20%:     {((df['EPC_ratio'] >= 0.8) & (df['EPC_ratio'] <= 1.2)).mean()*100:.0f}%")
    print(f"  Within ±30%:     {((df['EPC_ratio'] >= 0.7) & (df['EPC_ratio'] <= 1.3)).mean()*100:.0f}%")

    # Per building detail
    print(f"\n  PER-BUILDING RESULTS:")
    for _, r in df.iterrows():
        print(f"    {r['Fastighet']:20s}  EP_epc={r['EP_epc']:5.0f}  "
              f"EP_sim={r['EP_sim']:5.1f}  ratio={r['EPC_ratio']:.2f}  "
              f"floors={r['Floors']}  atemp={r['Atemp_epc']}")

    # Fjällvägen 28
    fjv = df[df["FormularId"] == 1033661]
    if len(fjv):
        r = fjv.iloc[0]
        print(f"\n  FJÄLLVÄGEN 28:")
        print(f"    EP_epc={r['EP_epc']}, EP_sim={r['EP_sim']}, "
              f"ratio={r['EPC_ratio']}, vent={r['Ventilation']}")

    # ── Plots ───────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # 1: Sim vs EPC scatter
    ax = axes[0]
    ax.scatter(df["EP_epc"], df["EP_sim"], alpha=0.8, s=100,
               c="tab:blue", edgecolors="k", linewidths=0.5, zorder=3)
    if len(fjv):
        ax.scatter(fjv["EP_epc"], fjv["EP_sim"], c="red", s=200,
                   marker="*", zorder=5, label="Fjällvägen 28", edgecolors="k")
    for _, r in df.iterrows():
        ax.annotate(r["Fastighet"][:12], (r["EP_epc"], r["EP_sim"]),
                    fontsize=7, ha="left", va="bottom")
    ep_range = [min(df["EP_epc"].min(), df["EP_sim"].min()) - 10,
                max(df["EP_epc"].max(), df["EP_sim"].max()) + 10]
    ax.plot(ep_range, ep_range, "r--", alpha=0.5, label="y=x")
    ax.plot(ep_range, [x * 1.1 for x in ep_range], "orange",
            linestyle=":", alpha=0.4, label="±10%")
    ax.plot(ep_range, [x * 0.9 for x in ep_range], "orange",
            linestyle=":", alpha=0.4)
    ax.set_xlabel("EP (EPC measured, kWh/m²)")
    ax.set_ylabel("EP (CMF_1960_1 simulated, kWh/m²)")
    ax.set_title("Simulated vs. Measured EP — S-vent_C4")
    ax.legend(fontsize=8)
    ax.set_aspect("equal")
    ax.set_xlim(ep_range)
    ax.set_ylim(ep_range)

    # 2: Bar chart: EPC vs Sim per building
    ax = axes[1]
    x = np.arange(len(df))
    w = 0.35
    ax.bar(x - w/2, df["EP_epc"], w, label="EPC measured", color="steelblue",
           edgecolor="k", linewidth=0.5)
    ax.bar(x + w/2, df["EP_sim"], w, label="CMF_1960_1 simulated",
           color="coral", edgecolor="k", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([f[:12] for f in df["Fastighet"]], rotation=45, ha="right")
    ax.set_ylabel("EP (kWh/m²)")
    ax.set_title("EPC vs. Simulated EP — S-vent_C4")
    ax.legend()

    # 3: EPC ratio bar
    ax = axes[2]
    colors = ["green" if 0.9 <= r <= 1.1 else "orange" if 0.8 <= r <= 1.2
              else "red" for r in df["EPC_ratio"]]
    ax.barh(x, df["EPC_ratio"], color=colors, edgecolor="k", linewidth=0.5)
    ax.axvline(x=1.0, color="red", linestyle="--", alpha=0.7)
    ax.axvline(x=0.9, color="orange", linestyle=":", alpha=0.5)
    ax.axvline(x=1.1, color="orange", linestyle=":", alpha=0.5)
    ax.set_yticks(x)
    ax.set_yticklabels([f[:12] for f in df["Fastighet"]])
    ax.set_xlabel("EPC Ratio (sim / measured)")
    ax.set_title("Archetype Accuracy — S-vent_C4")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "svent_c4_error_analysis.png", dpi=150)
    plt.close()
    print(f"\n  → Saved svent_c4_error_analysis.png")


def main():
    # ── Load hierarchical cluster assignments ───────────────────────────
    clusters = pd.read_csv(EDA_DIR / "clusters_1960s_hierarchical.csv")
    c4 = clusters[clusters["global_cluster"] == "S-vent_C4"].drop_duplicates(
        subset="FormularId"
    )
    log.info("S-vent_C4: %d unique buildings", len(c4))

    # Get IdHusnr from full features CSV
    full_data = pd.read_csv(EDA_DIR / "uddevalla_mfh_features.csv")
    husnr_map = (
        full_data[["FormularId", "IdHusnr"]]
        .drop_duplicates(subset="FormularId")
        .set_index("FormularId")["IdHusnr"]
    )

    # ── Simulate all buildings ──────────────────────────────────────────
    results = []
    failed = []

    for _, row in c4.iterrows():
        fid = int(row["FormularId"])
        fastighet = row["IdFastBet"]
        husnr = int(husnr_map.get(fid, 0))
        adress = row["IdAdr"]

        try:
            r = simulate_building(fid, fastighet, husnr, adress)
            results.append(r)
        except Exception:
            log.error("FAILED  %s (FormularId=%d)", fastighet, fid)
            traceback.print_exc()
            failed.append({"FormularId": fid, "Fastighet": fastighet,
                           "Error": traceback.format_exc()[-200:]})

    # ── Save results + analysis ─────────────────────────────────────────
    if results:
        results_df = pd.DataFrame(results)
        results_df.to_csv(RESULTS_CSV, index=False)
        log.info("Wrote %d results to %s", len(results_df), RESULTS_CSV)
        analyse_results(results_df)
    else:
        log.warning("No results to analyse")

    log.info("=" * 60)
    log.info("DONE   %d simulated, %d failed", len(results), len(failed))
    if failed:
        for f in failed:
            log.info("  FAILED: %s (%d): %s",
                     f["Fastighet"], f["FormularId"], f["Error"])


if __name__ == "__main__":
    main()
