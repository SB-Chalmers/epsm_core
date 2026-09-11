"""Reproducible, private EnergyPlus experiments; no compiler fidelity profiles.

Run from the checkout: python benchmarks/optimization.py freeze /path/to/artifacts
Then: python benchmarks/optimization.py compare /path/to/artifacts
Artifacts include exact inputs, SQL, diagnostics, per-process resource usage and hashes.
"""
# ruff: noqa: E402 -- Standalone script adds the checkout to sys.path before package imports.

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import random
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from epsm_core import EnergyPlusCompiler, Footprint, ScheduleSpec, ZoningSpec
from epsm_core.compiler import ENERGY_VARIABLES
from epsm_core.context import resolve_context, synthetic_context
from epsm_core.diagnostics import (
    WHOLE_BUILDING_AREA_DETAIL_RULE,
    WHOLE_BUILDING_AREA_RULE,
    compiler_warning_conditions,
    error_diagnostics,
)
from epsm_core.specs import BuildingSpec
from epsm_core.vertex_order import serialize_vertices
from epsm_core.weather import climate_from_epw
from examples.building import example_spec

SOLAR = "Enclosure Windows Total Transmitted Solar Radiation Energy"


def validation_outputs(model):
    requests = model.setdefault("Output:Variable", {})
    for index, name in enumerate(
        (
            "Surface Outside Face Incident Solar Radiation Rate per Area",
            "Surface Window Transmitted Solar Radiation Energy",
            "Surface Outside Face Sunlit Fraction",
        )
    ):
        keys = (
            list(model.get("FenestrationSurface:Detailed", {}))
            if index == 1
            else [
                key
                for key, obj in model["BuildingSurface:Detailed"].items()
                if obj.get("sun_exposure") == "SunExposed"
            ]
        )
        for frequency in ("Monthly", "Hourly"):
            for ki, key in enumerate(keys):
                requests[f"validation_{index}_{frequency}_{ki}"] = dict(
                    key_value=key, variable_name=name, reporting_frequency=frequency
                )
    diagnostics = model.setdefault("Output:Diagnostics", {"validation": dict(diagnostics=[])})
    next(iter(diagnostics.values()))["diagnostics"].append(dict(key="DisplayExtraWarnings"))


def full_context(spec, model):
    full = copy.deepcopy(model)
    full["Shading:Building:Detailed"] = {
        face.name: dict(
            number_of_vertices=len(face.vertices),
            vertices=[
                {f"vertex_{axis}_coordinate": value for axis, value in zip("xyz", point)}
                for point in serialize_vertices(face.vertices)
            ],
        )
        for face in resolve_context(spec.geometry, spec.context).surfaces
    }
    return full


def context_experiments(compiler, directory, *, pruned=False):
    """Stratified annual radius series; pruning and mirroring are held fixed."""
    climates = ("*Malmo*.epw", "*Gothenburg*.epw", "*Kiruna*.epw")
    for ci, pattern in enumerate(climates):
        weather = sorted((ROOT / "data/weather").glob(pattern))[0]
        for si, (name, base) in enumerate(cases()):
            angle = (0, 45, 90)[(ci + si) % 3]
            seed = (0, 17, 41)[(ci + si) % 3]
            geometry = base.geometry.updated(orientation_deg=angle)
            for radius in (80, 100, 120, 160, 240):
                spec = base.updated(
                    geometry=geometry,
                    climate=climate_from_epw(weather),
                    context=synthetic_context(
                        geometry,
                        "urban_highrise_dense",
                        seed=seed,
                        radius_m=radius,
                        max_buildings=2048,
                    ),
                )
                model, report = compiler.compile(spec)
                validation_outputs(model)
                # No radius-dependent change to the pruning or mirroring configuration.
                if not pruned:
                    model = full_context(spec, model)
                # Explicit validation capacity, identical for every radius; no retry.
                next(iter(model["ShadowCalculation"].values()))[
                    "maximum_figures_in_shadow_overlap_calculations"
                ] = 1000000
                folder = "context_pruned" if pruned else "context"
                target = directory / folder / f"{ci}-{name}-a{angle}-s{seed}-r{radius}"
                if target.exists():
                    continue
                run(compiler, spec, model, report, target)


def shadow_experiments(compiler, directory):
    for name, spec in cases():
        model, report = compiler.compile(spec)
        validation_outputs(model)
        full = full_context(spec, model)
        mirrored = copy.deepcopy(model)
        for obj in mirrored.get("Output:Diagnostics", {}).values():
            obj["diagnostics"] = [
                d for d in obj["diagnostics"] if d["key"] != "DoNotMirrorDetachedShading"
            ]
        mirrored["Output:Diagnostics"] = {
            k: v for k, v in mirrored["Output:Diagnostics"].items() if v["diagnostics"]
        }
        for label, candidate in (("full", full), ("pruned", model), ("mirrored", mirrored)):
            target = directory / "shadow_checked" / f"{name}-{label}"
            if not target.exists():
                run(compiler, spec, candidate, report, target)
        # A separate fixed-capacity pair isolates mirroring without a capped reference.
        for label, candidate in (("mirror_reference", mirrored), ("mirror_suppressed", model)):
            next(iter(candidate["ShadowCalculation"].values()))[
                "maximum_figures_in_shadow_overlap_calculations"
            ] = 1000000
            run(compiler, spec, candidate, report, directory / "shadow_checked" / f"{name}-{label}")


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def signals(path):
    """Key every sample by its actual interval; never align by array position."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        rows = db.execute(
            """SELECT d.Name,d.KeyValue,d.ReportingFrequency,
          t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value FROM ReportData r
          JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
          AND d.Name IN (?, ?, ?, ?, ?)
          ORDER BY d.Name,d.KeyValue,d.ReportingFrequency,t.TimeIndex""",
            (*ENERGY_VARIABLES, SOLAR, "Zone Mean Air Temperature"),
        )
        result = {}
        for name, key, frequency, *sample in rows:
            result.setdefault((name, key, frequency), {})[tuple(sample[:-1])] = sample[-1]
    return result


def accuracy(reference, candidate, area):
    """Compare independent energy, peak, monthly and hourly-temperature metrics."""
    output = {}
    for name in (*ENERGY_VARIABLES, SOLAR):

        def aggregate(data):
            total = {}
            for (variable, key, frequency), series in data.items():
                if variable == name and frequency.lower() == "hourly":
                    for stamp, value in series.items():
                        total[stamp] = total.get(stamp, 0) + value / 3.6e6
            return total

        a, b = aggregate(reference), aggregate(candidate)
        if not a or a.keys() != b.keys():
            output[name] = dict(passed=False, reason="Missing/misaligned hourly output")
            continue
        annual_a, annual_b = sum(a.values()), sum(b.values())
        monthly = []
        for month in range(1, 13):
            ma = sum(v for t, v in a.items() if t[0] == month)
            mb = sum(v for t, v in b.items() if t[0] == month)
            monthly.append(
                dict(
                    month=month,
                    reference_kwh=ma,
                    candidate_kwh=mb,
                    passed=abs(ma - mb) <= max(0.02 * abs(ma), 0.01 * area),
                )
            )
        peak_a, peak_b = max(a.values()), max(b.values())
        annual_pass = abs(annual_a - annual_b) <= max(0.01 * abs(annual_a), 0.1 * area)
        peak_pass = abs(peak_a - peak_b) <= max(0.02 * abs(peak_a), 0.0001 * area)
        output[name] = dict(
            reference_kwh=annual_a,
            candidate_kwh=annual_b,
            annual_relative_difference=(annual_b - annual_a) / annual_a if annual_a else None,
            peak_relative_difference=(peak_b - peak_a) / peak_a if peak_a else None,
            monthly=monthly,
            passed=annual_pass
            and all(m["passed"] for m in monthly)
            and (peak_pass if name in ENERGY_VARIABLES[:2] else True),
        )
    differences = []
    for signal, a in reference.items():
        if signal[0] != "Zone Mean Air Temperature" or signal[2].lower() != "hourly":
            continue
        b = candidate.get(signal, {})
        if a.keys() != b.keys():
            return {**output, "temperature": dict(passed=False, reason="Misaligned samples")}
        differences.extend(abs(value - b[stamp]) for stamp, value in a.items())
    output["temperature"] = dict(
        maximum_hourly_average_difference_c=max(differences, default=0),
        passed=bool(differences) and max(differences) <= 0.1,
    )
    return output


def summarize(directory):
    summary = {}
    for baseline in sorted((directory / "baseline").iterdir()):
        reference = signals(baseline / "eplusout.sql")
        report = json.loads(json.loads((baseline / "compilation.json").read_text())["report_json"])
        area = report["conditioned_floor_area_m2"]
        groups = {}
        for path in sorted((directory / "experiments").glob(baseline.name + "-*")):
            if not (path / "metrics.json").exists():
                continue
            label = path.name[len(baseline.name) + 1 :].rsplit("-", 1)[0]
            groups.setdefault(label, []).append(path)
        summary[baseline.name] = {}
        for label, paths in groups.items():
            metrics = [json.loads((p / "metrics.json").read_text()) for p in paths]
            comparison = accuracy(reference, signals(paths[0] / "eplusout.sql"), area)
            summary[baseline.name][label] = dict(
                repetitions=len(paths),
                median_wall_seconds=statistics.median(m["wall_seconds"] for m in metrics),
                median_cpu_seconds=statistics.median(m["cpu_seconds"] for m in metrics),
                maximum_peak_rss_bytes=max(m["peak_rss_bytes"] or 0 for m in metrics),
                sql_bytes=metrics[0]["sql_bytes"],
                accuracy=comparison,
                passed=all(m["accepted"] for m in metrics)
                and all(v["passed"] for v in comparison.values()),
            )
    dump(directory / "summary.json", summary)
    for case, variants in summary.items():
        print(
            case,
            {
                label: (round(v["median_wall_seconds"], 3), v["passed"])
                for label, v in variants.items()
            },
        )


def run(compiler, spec, model, report, directory):
    directory.mkdir(parents=True, exist_ok=False)
    dump(directory / "model.epJSON", model)
    dump(directory / "building.json", spec.model_dump(mode="json"))
    dump(directory / "compilation.json", report.model_dump(mode="json"))
    command = [
        str(compiler.executable),
        "-w",
        spec.climate.epw_path,
        "-d",
        str(directory),
        str(directory / "model.epJSON"),
    ]
    if sys.platform == "darwin":
        command = ["/usr/bin/time", "-l", *command]
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "EP_OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    start = time.perf_counter()
    with (directory / "process.log").open("w") as log:
        process = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=directory, timeout=1800
        )
    wall = time.perf_counter() - start
    diagnostics = error_diagnostics(
        directory / "eplusout.err",
        rules=(WHOLE_BUILDING_AREA_RULE, WHOLE_BUILDING_AREA_DETAIL_RULE),
        conditions=compiler_warning_conditions(spec, model, report),
    )
    dump(directory / "diagnostics.json", diagnostics)
    log = (directory / "process.log").read_text()
    cpu = re.search(r"([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys", log)
    rss = re.search(r"(\d+)\s+maximum resident set size", log)
    metrics = dict(
        wall_seconds=wall,
        cpu_seconds=float(cpu[2]) + float(cpu[3]) if cpu else None,
        peak_rss_bytes=int(rss[1]) if rss else None,
        sql_bytes=(directory / "eplusout.sql").stat().st_size
        if (directory / "eplusout.sql").exists()
        else 0,
        shading_faces=len(model.get("Shading:Building:Detailed", {})),
        accepted=diagnostics["accepted"] and process.returncode == 0,
        model_sha256=hashlib.sha256((directory / "model.epJSON").read_bytes()).hexdigest(),
        thread_count=1,
        platform=platform.platform(),
        cache_state="uncontrolled/warm after first run",
    )
    dump(directory / "metrics.json", metrics)
    print(directory.name, json.dumps(metrics), flush=True)
    return metrics


def cases():
    weather = ROOT / "data/weather/SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw"
    base = example_spec(weather)
    # Exercise active cooling as well as heating (the original pilot had no cooling).
    base = base.updated(use=base.use.updated(cooling_setpoint=ScheduleSpec.constant(24)))
    for name, footprint in (
        ("rectangle", Footprint.rectangle(30, 20)),
        ("l_shape", Footprint.l_shape(30, 20, 15, 10)),
        (
            "courtyard",
            Footprint(
                exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
                holes=(((10, 10), (20, 10), (20, 20), (10, 20)),),
            ),
        ),
    ):
        geometry = base.geometry.updated(
            parts=(base.geometry.parts[0].updated(footprint=footprint),),
            zoning=ZoningSpec(mode="whole_building"),
        )
        yield (
            name,
            base.updated(
                geometry=geometry,
                context=synthetic_context(
                    geometry, "urban_highrise_dense", seed=0, radius_m=120, max_buildings=512
                ),
            ),
        )


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument(
        "action", choices=("freeze", "compare", "summarize", "context", "context-pruned", "shadow")
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.action == "summarize":
        summarize(directory)
        return
    compiler = EnergyPlusCompiler(
        os.environ.get("ENERGYPLUS_EXE", "/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    )
    if args.action in ("context", "context-pruned"):
        context_experiments(compiler, directory, pruned=args.action == "context-pruned")
        return
    if args.action == "shadow":
        shadow_experiments(compiler, directory)
        return
    if args.action == "freeze":
        for name, spec in cases():
            model, report = compiler.compile(spec)
            run(compiler, spec, model, report, directory / "baseline" / name)
    else:
        jobs = []
        for path in sorted((directory / "baseline").iterdir()):
            spec = BuildingSpec.model_validate_json((path / "building.json").read_text())
            old = json.loads((path / "model.epJSON").read_text())
            new, report = compiler.compile(spec)
            geometry_only = copy.deepcopy(old)
            for category in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed"):
                geometry_only[category] = new.get(category, {})
            variants = {"reference": old, "geometry": geometry_only, "candidate": new}
            combined4 = copy.deepcopy(new)
            next(iter(combined4["Timestep"].values()))["number_of_timesteps_per_hour"] = 4
            variants["combined4"] = combined4
            for label, value in (("timestep4", 4), ("timestep12", 12)):
                variant = copy.deepcopy(old)
                next(iter(variant["Timestep"].values()))["number_of_timesteps_per_hour"] = value
                variants[label] = variant
            lean = copy.deepcopy(old)
            for category in ("Output:Variable", "Output:SQLite", "OutputControl:Files"):
                lean[category] = new[category]
            for category in ("Output:VariableDictionary", "Output:Table:SummaryReports"):
                lean.pop(category, None)
            variants["outputs"] = lean
            for label, updates in (
                ("capacity", {"maximum_figures_in_shadow_overlap_calculations": 15000}),
                ("clipping", {"polygon_clipping_algorithm": "SlaterBarskyandSutherlandHodgman"}),
            ):
                variant = copy.deepcopy(old)
                next(iter(variant["ShadowCalculation"].values())).update(updates)
                variants[label] = variant
            for repetition in range(args.repetitions):
                for label, model in variants.items():
                    jobs.append(
                        (
                            spec,
                            model,
                            report,
                            directory / "experiments" / f"{path.name}-{label}-{repetition}",
                        )
                    )
        random.Random(20260911).shuffle(jobs)
        for spec, model, report, target in jobs:
            run(compiler, spec, model, report, target)


if __name__ == "__main__":
    main()
