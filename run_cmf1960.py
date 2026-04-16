"""Batch-simulate all CMF_1960 buildings from the Uddevalahem portfolio."""
import csv
import logging
import re
import traceback
import unicodedata
from pathlib import Path

import pandas as pd

from src.pbgenerator.epc_io import (
    load_footprints,
    load_epc_metadata,
    detect_ventilation_system,
    load_epc_energy,
)
from src.pbgenerator.archetypes import cmf_1960
from src.pbgenerator.building_params import FacadeWWR
from src.pbgenerator.geometry import solve_apartment_depth, solve_depth_for_atemp, BuildingRooms, build_rooms
from src.pbgenerator.runner import run
from src.pbgenerator.weather import nearest_epw
from src.pbgenerator.reporting import log_epc_comparison

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

IDF_DIR = Path("idf")
OUTPUT_DIR = Path("results")
RESULTS_CSV = Path("results_cmf1960.csv")
TARGET_DEPTH = 5.0  # desired apartment depth in metres


def _safe_id(name: str) -> str:
    """Remove non-ASCII chars for Honeybee identifiers."""
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", s)
    return s


def _dedup_footprints(fps: list) -> list:
    """Deduplicate FootprintRecords by objektidentitet."""
    seen: set[str] = set()
    unique = []
    for fp in fps:
        if fp.objektidentitet not in seen:
            seen.add(fp.objektidentitet)
            unique.append(fp)
    return unique


def simulate_building(formular_id: int, fastighet: str, husnr: int, adress: str):
    """Run a single building and return a results dict (or None on failure)."""
    tag = _safe_id(f"{fastighet}_h{husnr}")
    log.info("=" * 60)
    log.info("START  %s  (FormularId=%d, %s)", tag, formular_id, adress)
    log.info("=" * 60)

    # Load all footprints, filter to Flerfamiljshus, deduplicate by objektidentitet.
    all_fps = load_footprints(formular_id=formular_id, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    candidates = _dedup_footprints(flerfamilj if flerfamilj else all_fps)
    log.info("  %d unique footprint(s) after dedup", len(candidates))

    epc = load_epc_metadata(formular_id)
    vent_sys = detect_ventilation_system(formular_id)
    epc_energy = load_epc_energy(formular_id)
    floors = epc["num_floors"]
    basement_floors = epc["num_basement_floors"]
    log.info("  vent_sys=%s, year=%s, basement=%d", vent_sys, epc["construction_year"], basement_floors)

    # ── Pre-flight: solve depth so perimeter Atemp ≈ EPC Atemp ────
    total_fp_area = sum(fp.footprint_area for fp in candidates)
    total_floors = floors + basement_floors
    sim_atemp_est = total_fp_area * total_floors
    epc_atemp = epc["atemp"]

    # For multi-footprint properties, allocate EPC Atemp proportionally
    if epc_atemp and epc_atemp > 0 and sim_atemp_est > epc_atemp:
        # Footprint is larger than EPC — solve for depth to match
        # Split target Atemp across footprints proportional to their area
        fp_areas = [fp.footprint_area for fp in candidates]
        total_area = sum(fp_areas)
        fp_depths = []
        for fp, area in zip(candidates, fp_areas):
            fp_target = epc_atemp * (area / total_area)
            d = solve_depth_for_atemp(fp.footprint_pts, fp_target, total_floors)
            fp_depths.append(d)
        log.info("  PRE-FLIGHT: fp_area=%.0f m² × %d fl = %.0f m² > EPC %d m² → solved depths: %s",
                 total_fp_area, total_floors, sim_atemp_est, epc_atemp,
                 [f"{d:.1f}" for d in fp_depths])
    else:
        # Footprint is smaller than or matches EPC — use full footprint (depth=0)
        fp_depths = [0.0] * len(candidates)
        if epc_atemp and epc_atemp > 0:
            log.info("  PRE-FLIGHT: fp_area=%.0f m² × %d fl = %.0f m² ≤ EPC %d m² → depth=0 (full footprint)",
                     total_fp_area, total_floors, sim_atemp_est, epc_atemp)

    # Compute garage share of Atemp for program blending
    garage_pct = 0.0
    if epc["garage_m2"] and epc["atemp"]:
        garage_pct = min(100.0 - epc["residential_pct"],
                         epc["garage_m2"] / epc["atemp"] * 100.0)

    # Simulate each unique footprint and aggregate results.
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
            seed=formular_id,  # reproducible WWR per building
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

    log.info("  TOTAL: perim_atemp=%.0f m²  gross=%.0f m²  epc_atemp=%s  (%d footprint(s))",
             total_atemp, total_gross, epc["atemp"], len(candidates))

    # Aggregate sim results for EPC comparison
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


def main():
    df = pd.read_csv("uddevalahem_epc_list.csv")
    cmf1960 = df[df["Archetype"] == "CMF_1960"].reset_index(drop=True)
    log.info("Found %d CMF_1960 buildings to simulate", len(cmf1960))

    results = []
    failed = []

    for i, row in cmf1960.iterrows():
        fid = int(row["FormularId"])
        fastighet = row["Fastighet"]
        husnr = int(row["Husnr"])
        adress = row["Adress"]

        try:
            r = simulate_building(fid, fastighet, husnr, adress)
            results.append(r)
        except Exception:
            log.error("FAILED  %s h%d (FormularId=%d)", fastighet, husnr, fid)
            traceback.print_exc()
            failed.append({"FormularId": fid, "Fastighet": fastighet, "Husnr": husnr})

    # Write results CSV
    if results:
        fieldnames = list(results[0].keys())
        with open(RESULTS_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(results)
        log.info("Wrote %d results to %s", len(results), RESULTS_CSV)

    log.info("=" * 60)
    log.info("DONE   %d succeeded, %d failed out of %d", len(results), len(failed), len(cmf1960))
    if failed:
        log.info("Failed buildings:")
        for f in failed:
            log.info("  %s h%d (FormularId=%d)", f["Fastighet"], f["Husnr"], f["FormularId"])


if __name__ == "__main__":
    main()
