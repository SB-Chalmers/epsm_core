"""Run percentage sensitivity and a separate mixed-building geometry stress corpus."""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely.geometry import shape

from epsm_core.preparation import prepare_geometry
from epsm_core.zoning import polygon_components
from experiments.mfh_zoning.mfh_layouts import MfhLayoutPolicy, generate_mfh_layout


def counts(rows):
    values = sorted(r["runtime_s"] for r in rows)
    return dict(status=dict(Counter(r["status"] for r in rows)),
                reasons=dict(Counter(r["reason"] for r in rows if r["status"] == "fallback")),
                median_runtime_s=statistics.median(values),
                p95_runtime_s=values[min(len(values)-1, int(.95*len(values)))],
                median_abs_fraction_error=(statistics.median(
                    abs(r["fraction_error"]) for r in rows if r["fraction_error"] is not None)
                    if any(r["fraction_error"] is not None for r in rows) else None))


def run_sweep(root, output):
    corpus = json.loads((root / "tests/fixtures/mfh_layouts/corpus.json").read_text())
    rows = []
    for target in (0.05, 0.078, 0.10, 0.15):
        for case in (c for c in corpus["cases"] if c["group"] == "mfh"):
            polygon = shape(case["preparation"]["source_geometry"])
            for method in ("modules", "corridor", "auto"):
                result = generate_mfh_layout(
                    polygon, MfhLayoutPolicy(target_unconditioned_fraction=target), method=method)
                rows.append(dict(target=target, id=case["id"], method=method,
                                 status=result.status, reason=result.reason,
                                 runtime_s=result.metrics.get("runtime_s", 0),
                                 fraction_error=result.metrics.get("fraction_error"),
                                 common_fraction=result.metrics.get("common_fraction"),
                                 apartment_count=result.metrics.get("apartment_count", 0)))
        print(f"Target {100*target:g}% complete", flush=True)
    groups = defaultdict(list)
    for row in rows:
        groups[f"{row['target']:.3f}:{row['method']}"].append(row)
    (output / "target-sweep.json").write_text(json.dumps(dict(
        cases=rows, summaries={key: counts(value) for key, value in groups.items()}), indent=2) + "\n")


def run_stress(root, output):
    paths = sorted((root / "tests/fixtures/footprints").glob("*.json"))
    rows = []
    for i, path in enumerate(paths):
        if path.name == "manifest.json":
            continue
        item = json.loads(path.read_text())
        source = shape(item["source_geometry"])
        components = polygon_components(source)
        prep = prepare_geometry(source)
        result = generate_mfh_layout(source, method="auto")
        rows.append(dict(id=path.stem, fixture_status=item.get("status"),
                         preparation_status=prep.status, preparation_reasons=list(prep.reasons),
                         source_area_m2=source.area,
                         holes=sum(len(p.interiors) for p in components),
                         vertices=sum(len(p.exterior.coords)-1 for p in components),
                         status=result.status, reason=result.reason,
                         runtime_s=result.metrics.get("runtime_s", 0),
                         fraction_error=result.metrics.get("fraction_error")))
        if (i+1) % 25 == 0:
            print(f"Stress {i+1}/{len(paths)}", flush=True)
    output_data = dict(description="Separate geometry stress corpus; residential class is unknown.",
                       cases=rows, summary=counts(rows),
                       preparation_statuses=dict(Counter(r["preparation_status"] for r in rows)),
                       accepted_large_count=sum(r["preparation_status"] == "accepted" and
                                                r["source_area_m2"] >= 150 for r in rows),
                       courtyard_count=sum(bool(r["holes"]) for r in rows))
    (output / "mixed-300-stress.json").write_text(json.dumps(output_data, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--stress", action="store_true")
    args = parser.parse_args()
    if not (args.sweep or args.stress):
        parser.error("Select --sweep or --stress")
    root = Path(__file__).resolve().parents[1]
    output = root / "output/analysis/mfh-zoning-2026-10-13"
    output.mkdir(parents=True, exist_ok=True)
    if args.sweep:
        run_sweep(root, output)
    if args.stress:
        run_stress(root, output)


if __name__ == "__main__":
    main()
