"""
Calibrate infiltration_ach for S-vent_C4 buildings.

Sweeps infiltration_ach from 0.30 to 0.70 in 0.05 steps, simulates all 4
S-vent_C4 buildings at each value, and reports which value minimises MAE.
"""
import dataclasses
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

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

EDA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EDA_DIR.parent
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

ACH_VALUES = [round(0.30 + i * 0.05, 2) for i in range(9)]  # 0.30 .. 0.70


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


def simulate_building(formular_id, fastighet, husnr, adress, ach_override):
    """Simulate one building with a specific infiltration_ach."""
    tag = _safe_id(f"{fastighet}_h{husnr}")
    ach_tag = f"ach{int(ach_override*100):03d}"
    idf_dir = PROJECT_DIR / "idf" / "svent_c4_cal" / f"{tag}_{ach_tag}"
    out_dir = PROJECT_DIR / "results" / "svent_c4_cal" / f"{tag}_{ach_tag}"

    all_fps = load_footprints(formular_id=formular_id, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    candidates = _dedup_footprints(flerfamilj if flerfamilj else all_fps)

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
        # Override infiltration_ach
        params = dataclasses.replace(params, infiltration_ach=ach_override)

        weather_file = nearest_epw(fp.centroid_lat, fp.centroid_lon)

        sim = run(
            name=f"{fp_tag}_{ach_tag}",
            footprint_pts=fp.footprint_pts,
            params=params,
            weather_file=weather_file,
            idf_dir=idf_dir,
            output_dir=out_dir,
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
        "FormularId": formular_id,
        "Fastighet": fastighet,
        "Floors": floors,
        "Atemp_epc": epc["atemp"],
        "EP_epc": epc["energi_prestanda"],
        "EP_sim": round(comp["epc_total_kwh"] / total_atemp, 1),
        "EPC_ratio": round(comp["epc_ratio"], 2),
        "ach": ach_override,
    }


def main():
    clusters = pd.read_csv(EDA_DIR / "clusters_1960s_hierarchical.csv")
    c4 = clusters[clusters["global_cluster"] == "S-vent_C4"].drop_duplicates(
        subset="FormularId"
    )

    full_data = pd.read_csv(EDA_DIR / "uddevalla_mfh_features.csv")
    husnr_map = (
        full_data[["FormularId", "IdHusnr"]]
        .drop_duplicates(subset="FormularId")
        .set_index("FormularId")["IdHusnr"]
    )

    buildings = []
    for _, row in c4.iterrows():
        buildings.append({
            "fid": int(row["FormularId"]),
            "fastighet": row["IdFastBet"],
            "husnr": int(husnr_map.get(row["FormularId"], 0)),
            "adress": row["IdAdr"],
        })

    log.info("S-vent_C4: %d buildings × %d ACH values = %d simulations",
             len(buildings), len(ACH_VALUES), len(buildings) * len(ACH_VALUES))

    all_results = []
    for ach in ACH_VALUES:
        log.info("── ACH = %.2f ──", ach)
        for b in buildings:
            try:
                r = simulate_building(b["fid"], b["fastighet"], b["husnr"],
                                      b["adress"], ach)
                all_results.append(r)
                log.info("  %s: EP_sim=%.1f, ratio=%.2f",
                         b["fastighet"], r["EP_sim"], r["EPC_ratio"])
            except Exception:
                log.error("  FAILED %s at ACH=%.2f", b["fastighet"], ach)
                traceback.print_exc()

    df = pd.DataFrame(all_results)
    df.to_csv(EDA_DIR / "results_svent_c4_calibration.csv", index=False)

    # ── Analysis ────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  S-VENT_C4 INFILTRATION CALIBRATION SWEEP")
    print(f"{'='*80}")

    summary = []
    for ach in ACH_VALUES:
        sub = df[df["ach"] == ach]
        mae = (sub["EP_sim"] - sub["EP_epc"]).abs().mean()
        rmse = np.sqrt(((sub["EP_sim"] - sub["EP_epc"])**2).mean())
        mean_ratio = sub["EPC_ratio"].mean()
        median_ratio = sub["EPC_ratio"].median()
        within_10 = ((sub["EPC_ratio"] >= 0.9) & (sub["EPC_ratio"] <= 1.1)).mean()
        summary.append({
            "ach": ach, "MAE": mae, "RMSE": rmse,
            "mean_ratio": mean_ratio, "median_ratio": median_ratio,
            "within_10pct": within_10,
        })
        print(f"  ACH={ach:.2f}  MAE={mae:5.1f}  RMSE={rmse:5.1f}  "
              f"mean_ratio={mean_ratio:.2f}  ±10%={within_10*100:.0f}%")

    sdf = pd.DataFrame(summary)
    best_mae = sdf.loc[sdf["MAE"].idxmin()]
    best_ratio = sdf.loc[(sdf["mean_ratio"] - 1.0).abs().idxmin()]

    print(f"\n  Best by MAE:        ACH={best_mae['ach']:.2f}  "
          f"MAE={best_mae['MAE']:.1f}  ratio={best_mae['mean_ratio']:.2f}")
    print(f"  Best by mean ratio: ACH={best_ratio['ach']:.2f}  "
          f"MAE={best_ratio['MAE']:.1f}  ratio={best_ratio['mean_ratio']:.2f}")

    # Per-building detail at best ACH
    best_ach = best_mae["ach"]
    print(f"\n  Per-building at ACH={best_ach:.2f}:")
    best_sub = df[df["ach"] == best_ach]
    for _, r in best_sub.iterrows():
        print(f"    {r['Fastighet']:20s}  fl={r['Floors']}  EP_epc={r['EP_epc']:3.0f}  "
              f"EP_sim={r['EP_sim']:5.1f}  ratio={r['EPC_ratio']:.2f}")

    # ── Plot ────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # 1: MAE vs ACH
    ax = axes[0]
    ax.plot(sdf["ach"], sdf["MAE"], "o-", color="steelblue", linewidth=2)
    ax.axvline(x=best_mae["ach"], color="red", linestyle="--", alpha=0.7,
               label=f"Best MAE: {best_mae['ach']:.2f}")
    ax.set_xlabel("Infiltration ACH")
    ax.set_ylabel("MAE (kWh/m²)")
    ax.set_title("Mean Absolute Error vs. Infiltration")
    ax.legend()
    ax.grid(alpha=0.3)

    # 2: Mean ratio vs ACH
    ax = axes[1]
    ax.plot(sdf["ach"], sdf["mean_ratio"], "o-", color="coral", linewidth=2)
    ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.7, label="Perfect (1.0)")
    ax.axvline(x=best_ratio["ach"], color="green", linestyle="--", alpha=0.7,
               label=f"Closest to 1.0: {best_ratio['ach']:.2f}")
    ax.set_xlabel("Infiltration ACH")
    ax.set_ylabel("Mean EPC Ratio (sim/measured)")
    ax.set_title("Mean Ratio vs. Infiltration")
    ax.legend()
    ax.grid(alpha=0.3)

    # 3: Per-building ratio curves
    ax = axes[2]
    for fid in df["FormularId"].unique():
        sub = df[df["FormularId"] == fid].sort_values("ach")
        label = sub["Fastighet"].iloc[0]
        marker = "*" if fid == 1033661 else "o"
        ax.plot(sub["ach"], sub["EPC_ratio"], f"{marker}-", label=label,
                linewidth=1.5, markersize=8 if fid == 1033661 else 5)
    ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.7)
    ax.axhline(y=0.9, color="orange", linestyle=":", alpha=0.4)
    ax.axhline(y=1.1, color="orange", linestyle=":", alpha=0.4)
    ax.set_xlabel("Infiltration ACH")
    ax.set_ylabel("EPC Ratio (sim/measured)")
    ax.set_title("Per-Building Accuracy vs. Infiltration")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "svent_c4_infiltration_calibration.png", dpi=150)
    plt.close()
    print(f"\n  → Saved svent_c4_infiltration_calibration.png")


if __name__ == "__main__":
    main()
