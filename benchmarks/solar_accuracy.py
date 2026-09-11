"""Surface-resolved comparisons and nested-radius acceptance (no annual cancellation)."""

from __future__ import annotations

import json
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from optimization import accuracy, dump, signals

signals = lru_cache(maxsize=6)(signals)

INCIDENT = "Surface Outside Face Incident Solar Radiation Rate per Area"
TRANSMITTED = "Surface Window Transmitted Solar Radiation Energy"
SUNLIT = "Surface Outside Face Sunlit Fraction"


@lru_cache(maxsize=6)
def solar(path):
    result = {}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        for name, key, month, day, hour, minute, value in db.execute(
            """
            SELECT d.Name,d.KeyValue,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r
            JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE d.Name IN (?,?,?) AND d.ReportingFrequency='Hourly'
            AND e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
            ORDER BY d.Name,d.KeyValue,t.TimeIndex""",
            (INCIDENT, TRANSMITTED, SUNLIT),
        ):
            result.setdefault((name, key), {})[(month, day, hour, minute)] = value
    return result


def compare(a_path, b_path):
    a, b = solar(a_path), solar(b_path)
    failures, details = [], {}
    if a.keys() != b.keys() or not a:
        return dict(passed=False, reason="Missing/mismatched validation surface outputs")
    for (variable, key), reference in a.items():
        candidate = b[(variable, key)]
        if reference.keys() != candidate.keys():
            failures.append((variable, key, "unaligned samples"))
            continue
        stamps = list(reference)
        av = np.array(list(reference.values()))
        bv = np.array([candidate[t] for t in stamps])
        if variable == SUNLIT:
            irradiance = a.get((INCIDENT, key))
            if irradiance is None:
                failures.append((variable, key, "missing daylight mask"))
                continue
            mask = np.array([irradiance[t] > 1 for t in stamps])
            error = abs(av - bv)[mask]
            if not len(error):
                continue
            mae, p95 = float(error.mean()), float(np.quantile(error, 0.95))
            fraction = float(np.mean(error > 0.1))
            duration = longest = 0
            for bad in (abs(av - bv) > 0.1) & mask:
                duration = duration + 1 if bad else 0
                longest = max(longest, duration)
            passed = mae <= 0.01 and p95 <= 0.05 and fraction <= 0.01
            details[key + "::sunlit"] = dict(
                mae=mae,
                p95=p95,
                fraction_differing_by_over_01=fraction,
                maximum_duration_hours=longest,
                passed=passed,
            )
        else:
            factor = 0.001 if variable == INCIDENT else 1 / 3.6e6
            av, bv = av * factor, bv * factor
            months = np.array([t[0] for t in stamps])
            annual_error = float(abs(av.sum() - bv.sum()))
            monthly = [
                float(abs(av[months == m].sum() - bv[months == m].sum())) for m in range(1, 13)
            ]
            # Incident: kWh/m2. Transmitted: kWh per window; absolute floor 0.1 kWh.
            passed = annual_error <= max(0.01 * abs(av.sum()), 0.1) and all(
                error <= max(0.02 * abs(av[months == m].sum()), 0.1)
                for m, error in enumerate(monthly, 1)
            )
            details[key + "::" + variable] = dict(
                annual_absolute_error=annual_error,
                monthly_absolute_errors=monthly,
                passed=bool(passed),
            )
        if not passed:
            failures.append((variable, key))
    return dict(passed=not failures, failures=failures, surfaces=details)


def assess_pair(reference, candidate):
    report = json.loads(json.loads((reference / "compilation.json").read_text())["report_json"])
    physical = accuracy(
        signals(reference / "eplusout.sql"),
        signals(candidate / "eplusout.sql"),
        report["conditioned_floor_area_m2"],
    )
    shading = compare(reference / "eplusout.sql", candidate / "eplusout.sql")
    warnings = all(
        json.loads((p / "metrics.json").read_text())["accepted"] for p in (reference, candidate)
    )
    return dict(
        passed=warnings and shading["passed"] and all(v["passed"] for v in physical.values()),
        diagnostics_passed=warnings,
        physical=physical,
        shading=shading,
    )


def main():
    root = Path(sys.argv[1])
    summary = {}
    context_folder = sys.argv[2] if len(sys.argv) > 2 else "context"
    if (root / context_folder).exists():
        groups = {}
        for path in sorted((root / context_folder).iterdir()):
            if (path / "metrics.json").exists() and (path / "eplusout.sql").exists():
                group, radius = path.name.rsplit("-r", 1)
                groups.setdefault(group, {})[int(radius)] = path
        for group, paths in groups.items():
            summary[group] = {}
            for radius in sorted(paths):
                larger = [r for r in sorted(paths) if r > radius]
                # Two larger contexts are required. Check every available larger radius.
                pairs = {str(r): assess_pair(paths[r], paths[radius]) for r in larger}
                summary[group][radius] = dict(
                    passed=len(pairs) >= 2 and all(v["passed"] for v in pairs.values()),
                    comparisons=pairs,
                )
            print(group, {r: data["passed"] for r, data in summary[group].items()}, flush=True)
        dump(root / f"{context_folder}-accuracy.json", summary)
    shadow = root / "shadow_checked"
    if shadow.exists():
        results = {}
        for name in ("rectangle", "l_shape", "courtyard"):
            for label, a, b in (
                ("pruning", "full", "pruned"),
                ("mirroring", "mirror_reference", "mirror_suppressed"),
            ):
                first, second = shadow / f"{name}-{a}", shadow / f"{name}-{b}"
                if all((p / "eplusout.sql").exists() for p in (first, second)):
                    results[name + "-" + label] = assess_pair(first, second)
                    print(name, label, results[name + "-" + label]["passed"], flush=True)
        dump(root / "shadow-accuracy.json", results)


if __name__ == "__main__":
    main()
