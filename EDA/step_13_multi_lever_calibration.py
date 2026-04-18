"""
Step 13 — Multi-lever calibration.

Step 12 showed that wall insulation thickness alone cannot close the gap
for 6/8 clusters.  This step sweeps ALL available calibration levers:

  Envelope levers (construction spec):
    1. wall_mw    — exterior wall mineral wool thickness  [30–200 mm]
    2. roof_mw    — roof mineral wool thickness           [50–300 mm]
    3. floor_eps  — ground floor EPS thickness            [10–130 mm]
    4. window_u   — window U-value                        [1.5–3.0 W/m²K]

  Ventilation / system levers (BuildingParams):
    5. infiltration_ach — envelope air leakage            [0.15–1.0 ACH]

Phase 1: Sensitivity scan on F-vent_C0 (n=120, largest cluster)
  — each lever pushed to its extreme individually, then all combined
  — quantifies the maximum ΔEP available from each lever

Phase 2: Coordinate descent for all 8 clusters
  — bisection on each lever in order: wall_mw → roof_mw → window_u →
    infiltration_ach → floor_eps
  — converge when |EP_sim − EP_epc| < 2 kWh/m²

Outputs:
  EDA/sensitivity_scan.csv
  EDA/results_multilever.csv
  EDA/figures/multilever_calibration.png
"""
import logging
import traceback
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, replace, field
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
IDF_DIR = PROJECT_DIR / "idf" / "multilever"
OUTPUT_DIR = PROJECT_DIR / "results" / "multilever"
FIG_DIR = EDA_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# LEVER DEFINITIONS
# ═══════════════════════════════════════════════════════════════════
# ep_dir: +1 → increasing lever increases EP_sim
#         −1 → increasing lever decreases EP_sim

LEVERS = OrderedDict([
    ("wall_mw",         {"lo": 0.030, "hi": 0.200, "ep_dir": -1}),
    ("roof_mw",         {"lo": 0.050, "hi": 0.300, "ep_dir": -1}),
    ("window_u",        {"lo": 1.50,  "hi": 3.00,  "ep_dir": +1}),
    ("infiltration_ach",{"lo": 0.15,  "hi": 1.00,  "ep_dir": +1}),
    ("floor_eps",       {"lo": 0.010, "hi": 0.130, "ep_dir": -1}),
])

BETSI_DEFAULTS = {
    "BETSI_CONC_SLAB":  {"wall_mw": 0.155, "roof_mw": 0.270,
                         "floor_eps": 0.105, "window_u": 2.00},
    "BETSI_CONC_TOWER": {"wall_mw": 0.195, "roof_mw": 0.290,
                         "floor_eps": 0.130, "window_u": 1.90},
}

TOLERANCE = 2.0       # kWh/m² — convergence threshold
MAX_BISECT = 6        # iterations per lever


# ═══════════════════════════════════════════════════════════════════
# MATERIALS & SPEC BUILDER
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
    """Build a construction spec with adjustable thicknesses + window U."""
    is_tower = "TOWER" in template

    roof_mw_actual = roof_mw
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
                _L("mw_old", roof_mw_actual),
                _L("conc_roof", 0.150),
            ]}]},
            "TOP_FLOOR": {"components": [{"shearing_layer": "Structure", "layers": [
                _L("conc_floor", 0.150),
                _L("mw_old", roof_mw_actual),
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


_spec_counter = 0

def _next_spec_id():
    global _spec_counter
    _spec_counter += 1
    return f"ML_{_spec_counter:04d}"


def _build_and_register(spec, json_path):
    from epsm_data import build_archetype_from_spec
    aid = spec["archetype_id"]
    arch = build_archetype_from_spec(spec, json_path, skip_api=True)
    cset = ConstructionSetDef.from_epsm_archetype(arch)
    CONSTRUCTION_SETS[aid] = (lambda cs: lambda: cs)(cset)
    return aid


# ═══════════════════════════════════════════════════════════════════
# ARCHETYPE CONTEXT — caches metadata for repeated simulations
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ArchetypeCtx:
    formular_id: int
    cluster_name: str
    betsi_template: str
    ep_epc: float
    epc: dict
    vent_sys: str
    epc_energy: dict
    candidates: list
    fp_depths: list
    garage_pct: float
    floors: int
    basement_floors: int
    default_infiltration: float  # from cmf_1960()

    @classmethod
    def load(cls, row, ep_epc):
        fid = int(row["FormularId"])
        epc = load_epc_metadata(fid)
        vent_sys = detect_ventilation_system(fid)
        epc_energy = load_epc_energy(fid)
        floors = epc["num_floors"]
        basement_floors = epc["num_basement_floors"]

        all_fps = load_footprints(formular_id=fid, limit=50)
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

        # Get default infiltration from cmf_1960
        dummy_params = cmf_1960(
            num_floors=floors, ventilation_system=vent_sys,
            apartment_depth=0.0, residential_pct=epc["residential_pct"],
            garage_pct=garage_pct, num_basement_floors=basement_floors,
            cold_attic=True, seed=fid,
        )

        return cls(
            formular_id=fid,
            cluster_name=row["global_cluster"],
            betsi_template=row["betsi_template"],
            ep_epc=ep_epc,
            epc=epc,
            vent_sys=vent_sys,
            epc_energy=epc_energy,
            candidates=candidates,
            fp_depths=fp_depths,
            garage_pct=garage_pct,
            floors=floors,
            basement_floors=basement_floors,
            default_infiltration=dummy_params.infiltration_ach,
        )

    def simulate(self, levers: dict, json_path: Path) -> float:
        """Run EnergyPlus with the given lever values. Returns EP_sim."""
        spec_id = _next_spec_id()
        spec = _make_spec(
            self.betsi_template,
            wall_mw=levers["wall_mw"],
            roof_mw=levers["roof_mw"],
            floor_eps=levers["floor_eps"],
            window_u=levers["window_u"],
            spec_id=spec_id,
        )
        cset_id = _build_and_register(spec, json_path)

        tag = _safe_id(f"{self.cluster_name}_{spec_id}")
        total_heating = total_cooling = total_dhw = total_site = 0.0
        total_atemp = 0.0

        for idx, fp in enumerate(self.candidates):
            fp_tag = f"{tag}_fp{idx}" if len(self.candidates) > 1 else tag
            depth = self.fp_depths[idx]

            bldg = build_rooms(
                footprint_pts=fp.footprint_pts,
                floor_height=2.7, num_floors=self.floors,
                wwr=FacadeWWR(0, 0, 0, 0),
                apartment_depth=depth,
                identifier="preview",
                num_basement_floors=self.basement_floors,
            )

            params = cmf_1960(
                num_floors=self.floors,
                ventilation_system=self.vent_sys,
                apartment_depth=depth,
                residential_pct=self.epc["residential_pct"],
                garage_pct=self.garage_pct,
                num_basement_floors=self.basement_floors,
                cold_attic=True,
                seed=self.formular_id,
            )
            params = replace(params,
                             construction_set=cset_id,
                             infiltration_ach=levers["infiltration_ach"])

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
            epc_atemp=self.epc["atemp"],
            energi_prestanda=self.epc["energi_prestanda"],
            epc_energy=self.epc_energy,
            ventilation_system=self.vent_sys,
        )
        return comp["epc_total_kwh"] / total_atemp


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — SENSITIVITY SCAN
# ═══════════════════════════════════════════════════════════════════

def run_sensitivity_scan(ctx: ArchetypeCtx, json_path: Path) -> pd.DataFrame:
    """Push each lever to its extreme individually. Reports ΔEP."""
    defaults = dict(BETSI_DEFAULTS[ctx.betsi_template])
    defaults["infiltration_ach"] = ctx.default_infiltration

    log.info("=" * 70)
    log.info("PHASE 1: Sensitivity scan on %s  (EP_epc=%.0f)",
             ctx.cluster_name, ctx.ep_epc)
    log.info("=" * 70)

    # Baseline with all BETSI defaults
    log.info("  Baseline (BETSI defaults)...")
    ep_base = ctx.simulate(defaults, json_path)
    log.info("    EP_sim = %.1f (gap = %.1f)", ep_base, ep_base - ctx.ep_epc)

    results = [{"lever": "baseline", "value": "BETSI defaults",
                "ep_sim": round(ep_base, 1), "delta_ep": 0.0}]

    # Individual lever extremes
    for lever_name, lever_def in LEVERS.items():
        # Push toward MORE heating (higher EP)
        if lever_def["ep_dir"] > 0:
            extreme = lever_def["hi"]
        else:
            extreme = lever_def["lo"]

        trial = dict(defaults)
        trial[lever_name] = extreme
        log.info("  %s → %.3f  (default=%.3f)...",
                 lever_name, extreme, defaults[lever_name])
        ep_ext = ctx.simulate(trial, json_path)
        delta = ep_ext - ep_base
        log.info("    EP_sim = %.1f  (ΔEP = %+.1f)", ep_ext, delta)
        results.append({
            "lever": lever_name,
            "value": f"{extreme:.3f}",
            "ep_sim": round(ep_ext, 1),
            "delta_ep": round(delta, 1),
        })

    # All extremes combined
    trial = dict(defaults)
    for lever_name, lever_def in LEVERS.items():
        if lever_def["ep_dir"] > 0:
            trial[lever_name] = lever_def["hi"]
        else:
            trial[lever_name] = lever_def["lo"]

    log.info("  ALL EXTREMES combined...")
    ep_all = ctx.simulate(trial, json_path)
    delta_all = ep_all - ep_base
    log.info("    EP_sim = %.1f  (ΔEP = %+.1f)  (EP_epc = %.0f)",
             ep_all, delta_all, ctx.ep_epc)
    results.append({
        "lever": "ALL_EXTREMES",
        "value": "combined",
        "ep_sim": round(ep_all, 1),
        "delta_ep": round(delta_all, 1),
    })

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — COORDINATE DESCENT
# ═══════════════════════════════════════════════════════════════════

def calibrate_coordinate_descent(ctx: ArchetypeCtx, json_path: Path,
                                 max_rounds: int = 2):
    """Bisection on each lever sequentially, iterate until converged."""
    defaults = dict(BETSI_DEFAULTS[ctx.betsi_template])
    defaults["infiltration_ach"] = ctx.default_infiltration

    log.info("─" * 70)
    log.info("PHASE 2: Calibrating %s  (EP_epc=%.0f, template=%s)",
             ctx.cluster_name, ctx.ep_epc, ctx.betsi_template)
    log.info("─" * 70)

    current = dict(defaults)
    all_trials = []

    for round_num in range(1, max_rounds + 1):
        log.info("  Round %d", round_num)
        round_improved = False

        for lever_name, lever_def in LEVERS.items():
            lo = lever_def["lo"]
            hi = lever_def["hi"]
            ep_dir = lever_def["ep_dir"]
            best_val = current[lever_name]
            best_err = float("inf")

            for it in range(MAX_BISECT):
                mid = (lo + hi) / 2
                current[lever_name] = mid
                ep_sim = ctx.simulate(current, json_path)
                err = ep_sim - ctx.ep_epc

                all_trials.append({
                    "cluster": ctx.cluster_name,
                    "round": round_num,
                    "lever": lever_name,
                    "iteration": it + 1,
                    "value": round(mid, 4),
                    "ep_sim": round(ep_sim, 1),
                    "error": round(err, 1),
                })

                if abs(err) < abs(best_err):
                    best_err = err
                    best_val = mid

                log.info("    %s  trial %d: val=%.4f  EP=%.1f  err=%+.1f",
                         lever_name, it + 1, mid, ep_sim, err)

                if abs(err) < TOLERANCE:
                    log.info("    → Converged!")
                    break

                # Bisection direction
                if err * ep_dir > 0:
                    hi = mid
                else:
                    lo = mid

            current[lever_name] = best_val
            if abs(best_err) < abs(float("inf")):
                round_improved = True

            # Check if whole system is converged
            ep_check = ctx.simulate(current, json_path)
            all_trials.append({
                "cluster": ctx.cluster_name,
                "round": round_num,
                "lever": f"{lever_name}_check",
                "iteration": 0,
                "value": round(best_val, 4),
                "ep_sim": round(ep_check, 1),
                "error": round(ep_check - ctx.ep_epc, 1),
            })
            if abs(ep_check - ctx.ep_epc) < TOLERANCE:
                log.info("  → System converged after %s", lever_name)
                return current, ep_check, all_trials

        if not round_improved:
            break

    # Final EP with all calibrated levers
    ep_final = ctx.simulate(current, json_path)
    log.info("  FINAL: EP_sim=%.1f  (EP_epc=%.0f, ratio=%.2f)",
             ep_final, ctx.ep_epc, ep_final / ctx.ep_epc)

    return current, ep_final, all_trials


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    json_path = _find_opaque_json()
    archetypes = pd.read_csv(EDA_DIR / "archetypes_betsi.csv")
    betsi_results = pd.read_csv(EDA_DIR / "results_betsi.csv")
    ep_map = betsi_results.set_index("Cluster")["EP_epc"].to_dict()

    # ── Load all archetype contexts ────────────────────────────────
    log.info("Loading archetype metadata...")
    contexts = {}
    for _, row in archetypes.iterrows():
        cluster = row["global_cluster"]
        ep_epc = ep_map.get(cluster, row["ep"])
        ctx = ArchetypeCtx.load(row, ep_epc)
        contexts[cluster] = ctx
        log.info("  %s: fid=%d, vent=%s, EP_epc=%.0f, default_infil=%.2f",
                 cluster, ctx.formular_id, ctx.vent_sys, ep_epc,
                 ctx.default_infiltration)

    # ── Phase 1: Sensitivity scan on F-vent_C0 ────────────────────
    target = "F-vent_C0"
    sensitivity_df = run_sensitivity_scan(contexts[target], json_path)
    sensitivity_df.to_csv(EDA_DIR / "sensitivity_scan.csv", index=False)

    print(f"\n{'='*70}")
    print(f"  SENSITIVITY SCAN — {target}  (EP_epc={contexts[target].ep_epc:.0f})")
    print(f"{'='*70}")
    print(f"  {'Lever':<20s} {'Extreme':>10s} {'EP_sim':>8s} {'ΔEP':>8s}")
    print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*8}")
    for _, r in sensitivity_df.iterrows():
        print(f"  {r['lever']:<20s} {r['value']:>10s} "
              f"{r['ep_sim']:8.1f} {r['delta_ep']:+8.1f}")

    # ── Phase 2: Coordinate descent for all clusters ──────────────
    log.info("\nStarting Phase 2: Coordinate descent for all %d clusters...\n",
             len(contexts))

    calibrated = []
    all_trials = []

    for cluster_name, ctx in contexts.items():
        try:
            best_levers, ep_final, trials = calibrate_coordinate_descent(
                ctx, json_path
            )
            all_trials.extend(trials)

            wall_u_approx = 1.0 / (
                0.04 + 0.13
                + best_levers["wall_mw"] / 0.042
                + 0.150 / 1.7
                + 0.013 / 0.16
                + 0.015 / 0.72
            )

            calibrated.append({
                "Cluster": cluster_name,
                "FormularId": ctx.formular_id,
                "Ventilation": ctx.vent_sys,
                "BETSI_template": ctx.betsi_template,
                "EP_epc": round(ctx.ep_epc, 0),
                "EP_sim": round(ep_final, 1),
                "EPC_ratio": round(ep_final / ctx.ep_epc, 2),
                "wall_mw_mm": round(best_levers["wall_mw"] * 1000, 1),
                "roof_mw_mm": round(best_levers["roof_mw"] * 1000, 1),
                "floor_eps_mm": round(best_levers["floor_eps"] * 1000, 1),
                "window_u": round(best_levers["window_u"], 2),
                "infiltration_ach": round(best_levers["infiltration_ach"], 3),
                "wall_U_approx": round(wall_u_approx, 2),
            })
            log.info("  %s → EP=%.1f, ratio=%.2f", cluster_name, ep_final,
                     ep_final / ctx.ep_epc)
        except Exception:
            log.error("FAILED %s", cluster_name)
            traceback.print_exc()

    # ── Save results ───────────────────────────────────────────────
    cal_df = pd.DataFrame(calibrated)
    cal_df.to_csv(EDA_DIR / "results_multilever.csv", index=False)
    pd.DataFrame(all_trials).to_csv(
        EDA_DIR / "calibration_multilever_log.csv", index=False)

    # ── Summary ────────────────────────────────────────────────────
    print(f"\n{'='*130}")
    print(f"  MULTI-LEVER CALIBRATION RESULTS")
    print(f"{'='*130}")
    print(f"  {'Cluster':<16s} {'Vent':>4s} {'EP_epc':>7s} {'EP_sim':>7s} "
          f"{'Ratio':>6s} {'Wall':>6s} {'Roof':>6s} {'Floor':>6s} "
          f"{'WinU':>5s} {'Infil':>6s} {'U_wall':>7s}")
    print(f"  {'-'*16} {'-'*4} {'-'*7} {'-'*7} {'-'*6} "
          f"{'-'*6} {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*7}")

    for _, r in cal_df.iterrows():
        print(f"  {r['Cluster']:<16s} {r['Ventilation']:>4s} "
              f"{r['EP_epc']:7.0f} {r['EP_sim']:7.1f} "
              f"{r['EPC_ratio']:6.2f} "
              f"{r['wall_mw_mm']:6.0f} {r['roof_mw_mm']:6.0f} "
              f"{r['floor_eps_mm']:6.0f} "
              f"{r['window_u']:5.2f} {r['infiltration_ach']:6.3f} "
              f"{r['wall_U_approx']:7.2f}")

    n = len(cal_df)
    print(f"\n  Total: {n} clusters")
    print(f"  Mean ratio: {cal_df['EPC_ratio'].mean():.2f}")
    within_10 = ((cal_df["EPC_ratio"] >= 0.9) & (cal_df["EPC_ratio"] <= 1.1))
    within_20 = ((cal_df["EPC_ratio"] >= 0.8) & (cal_df["EPC_ratio"] <= 1.2))
    print(f"  Within ±10%: {within_10.mean()*100:.0f}% ({within_10.sum()}/{n})")
    print(f"  Within ±20%: {within_20.mean()*100:.0f}% ({within_20.sum()}/{n})")

    # Compare to Step 12
    step12 = pd.read_csv(EDA_DIR / "results_calibrated.csv")
    print(f"\n  {'Metric':<25s} {'Step12 (wall)':>14s} {'Step13 (multi)':>14s}")
    print(f"  {'-'*25} {'-'*14} {'-'*14}")
    print(f"  {'Mean ratio':<25s} "
          f"{step12['EPC_ratio'].mean():14.2f} "
          f"{cal_df['EPC_ratio'].mean():14.2f}")
    print(f"  {'Median ratio':<25s} "
          f"{step12['EPC_ratio'].median():14.2f} "
          f"{cal_df['EPC_ratio'].median():14.2f}")

    # ── Plot ───────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    colors = {"S-vent": "#4C72B0", "F-vent": "#DD8452",
              "FTX-vent": "#C44E52", "Renovated": "#8172B3"}

    # 1: Sensitivity bar chart
    ax = axes[0]
    sens = sensitivity_df[sensitivity_df["lever"] != "baseline"]
    ax.barh(range(len(sens)), sens["delta_ep"].values, color=[
        "#C44E52" if d > 0 else "#4C72B0" for d in sens["delta_ep"]
    ], alpha=0.7, edgecolor="k", linewidth=0.5)
    ax.set_yticks(range(len(sens)))
    ax.set_yticklabels(sens["lever"].values, fontsize=9)
    ax.set(xlabel="ΔEP (kWh/m²)", title=f"Sensitivity: {target}")
    ax.axvline(0, color="k", lw=0.5)
    ax.grid(True, axis="x", alpha=0.3)

    # 2: Calibrated EP scatter
    ax = axes[1]
    for _, r in cal_df.iterrows():
        grp = r["Cluster"].rsplit("_C", 1)[0]
        ax.scatter(r["EP_epc"], r["EP_sim"],
                   c=colors.get(grp, "gray"), s=60,
                   alpha=0.7, edgecolors="k", linewidths=0.5)
    ep_min = min(cal_df["EP_epc"].min(), cal_df["EP_sim"].min()) - 10
    ep_max = max(cal_df["EP_epc"].max(), cal_df["EP_sim"].max()) + 10
    ax.plot([ep_min, ep_max], [ep_min, ep_max], "k--", alpha=0.4)
    ax.plot([ep_min, ep_max], [ep_min*0.9, ep_max*0.9],
            "orange", ls=":", alpha=0.3)
    ax.plot([ep_min, ep_max], [ep_min*1.1, ep_max*1.1],
            "orange", ls=":", alpha=0.3)
    ax.set(xlabel="EP_epc (kWh/m²)", ylabel="EP_sim (kWh/m²)",
           title="Multi-lever: EP_sim vs EP_epc")
    ax.grid(True, alpha=0.3)
    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], marker="o", color="w",
                     markerfacecolor=c, markersize=8, label=g)
              for g, c in colors.items()]
    ax.legend(handles=legend, fontsize=8)

    # 3: Lever values heatmap
    ax = axes[2]
    lever_cols = ["wall_mw_mm", "roof_mw_mm", "floor_eps_mm",
                  "window_u", "infiltration_ach"]
    lever_labels = ["Wall MW\n(mm)", "Roof MW\n(mm)", "Floor EPS\n(mm)",
                    "Window U\n(W/m²K)", "Infiltration\n(ACH)"]
    data = cal_df[lever_cols].values.astype(float)
    # Normalize per column for coloring
    normed = (data - data.min(axis=0)) / (data.max(axis=0) - data.min(axis=0) + 1e-9)
    im = ax.imshow(normed.T, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=1)
    ax.set_xticks(range(len(cal_df)))
    ax.set_xticklabels(cal_df["Cluster"].values, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(lever_labels)))
    ax.set_yticklabels(lever_labels, fontsize=8)
    # Annotate with actual values
    for i in range(len(cal_df)):
        for j in range(len(lever_cols)):
            val = data[i, j]
            fmt = ".0f" if j < 3 else (".2f" if j == 3 else ".2f")
            ax.text(i, j, f"{val:{fmt}}", ha="center", va="center", fontsize=7)
    ax.set_title("Calibrated Lever Values")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "multilever_calibration.png", dpi=150)
    plt.close()
    log.info("  → Saved figures/multilever_calibration.png")


if __name__ == "__main__":
    main()
