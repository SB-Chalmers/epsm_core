"""Compare bounded MFH layout prototypes on the frozen diagnostic footprints."""

import argparse
import hashlib
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "output/analysis/mfh-zoning-2026-10-13/.matplotlib"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as PolygonPatch  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from experiments.mfh_zoning.mfh_layouts import MfhLayoutPolicy, generate_mfh_layout  # noqa: E402

METHODS = (("offset", None), ("modules", None), ("corridor", None),
           ("slicing", None), ("grid", 0.5), ("grid", None))
COLORS = ("#92C5DE", "#F4A582", "#A6D96A", "#FDAE61", "#B2ABD2",
          "#80CDC1", "#FFD92F", "#E78AC3", "#8DA0CB", "#66C2A5")
CORE = "#777777"


def label(method, grid):
    return method if method != "grid" else ("grid 0.5" if grid else "grid adaptive")


def draw(ax, result, name, method):
    footprint = result.footprint
    bounds = footprint.bounds
    pad = max(bounds[2]-bounds[0], bounds[3]-bounds[1]) * 0.06
    ax.set_xlim(bounds[0]-pad, bounds[2]+pad)
    ax.set_ylim(bounds[1]-pad, bounds[3]+pad)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    for i, polygon in enumerate(result.occupied):
        ax.add_patch(PolygonPatch(polygon.exterior.coords, facecolor=COLORS[i % len(COLORS)],
                                  edgecolor="#283646", linewidth=0.55))
    for polygon in result.common:
        ax.add_patch(PolygonPatch(polygon.exterior.coords, facecolor=CORE,
                                  edgecolor="#283646", linewidth=0.7))
    ax.add_patch(PolygonPatch(footprint.exterior.coords, fill=False,
                              edgecolor="#111111", linewidth=1.2))
    title = f"{name} | {method}\n{result.status}"
    if result.status != "fallback":
        areas = sorted(round(q.area) for q in result.occupied)
        title += (f" | common {100*result.metrics['common_fraction']:.1f}%"
                  f" | {len(areas)} areas {areas}")
        if method.startswith("grid"):
            title += f" | {result.metrics.get('grid_size_m', 'none')} m"
    else:
        title += f" | {result.reason}"
    ax.set_title(title, fontsize=7.2, loc="left", wrap=True)


def plot_group(group, entries, output, phase):
    for page in range(0, len(entries), 5):
        subset = entries[page:page+5]
        fig, axes = plt.subplots(len(subset), len(METHODS), figsize=(24, 3.6*len(subset)))
        if len(subset) == 1:
            axes = [axes]
        for row, (name, results) in enumerate(subset):
            for col, ((method, grid), result) in enumerate(zip(METHODS, results)):
                draw(axes[row][col], result, name, label(method, grid))
        fig.suptitle(f"MFH thermal layout comparison: {group}, page {page//5+1}"
                     " | colours: occupied zones, grey: common area", fontsize=15)
        fig.tight_layout(rect=(0, 0, 1, .975), h_pad=2.0)
        stem = output / f"{phase}-{group}-{page//5+1}"
        fig.savefig(stem.with_suffix(".png"), dpi=160)
        fig.savefig(stem.with_suffix(".svg"))
        plt.close(fig)


def summary(rows):
    by_method = defaultdict(list)
    for row in rows:
        by_method[row["method"]].append(row)
    result = {}
    for method, cases in by_method.items():
        runtimes = sorted(r["metrics"].get("runtime_s", 0) for r in cases)
        result[method] = dict(
            counts=dict(Counter(r["status"] for r in cases)),
            rejection_reasons=dict(Counter(r["reason"] for r in cases if r["status"] == "fallback")),
            median_runtime_s=statistics.median(runtimes),
            p95_runtime_s=runtimes[min(len(runtimes)-1, int(.95*len(runtimes)))],
            complete_mean_abs_fraction_error=(statistics.mean(abs(r["metrics"]["fraction_error"])
                                              for r in cases if r["status"] == "complete")
                                              if any(r["status"] == "complete" for r in cases) else None),
            complete_median_unit_area_m2=(statistics.median(
                u["area_m2"] for r in cases if r["status"] == "complete"
                for u in r["metrics"]["units"])
                if any(r["status"] == "complete" for r in cases) else None),
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("refined",), default="refined",
                        help="Current implementation; initial output is an archived baseline")
    parser.add_argument("--group", choices=("mfh", "synthetic", "regression", "all"), default="all")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "output/analysis/mfh-zoning-2026-10-13"
    output.mkdir(parents=True, exist_ok=True)
    corpus = json.loads((root / "tests/fixtures/mfh_layouts/corpus.json").read_text())
    groups = ("mfh", "synthetic", "regression") if args.group == "all" else (args.group,)
    rows = []
    for group in groups:
        plots = []
        for case in (case for case in corpus["cases"] if case["group"] == group):
            footprint = shape(case["preparation"]["source_geometry"])
            if hashlib.sha256(footprint.wkb).hexdigest() != case["source_sha256"]:
                raise ValueError(f"Source fixture hash changed: {case['id']}")
            results = []
            for method, grid in METHODS:
                policy = MfhLayoutPolicy(grid_size_m=grid)
                result = generate_mfh_layout(footprint, policy, method=method)
                results.append(result)
                rows.append(dict(id=case["id"], group=group, method=label(method, grid),
                                 status=result.status, reason=result.reason,
                                 metrics=result.metrics, preparation=result.preparation))
            plots.append((case["id"][:12], results))
            print(f"{group} {case['id']}: " + ", ".join(
                f"{label(m, g)}={r.status}" for (m, g), r in zip(METHODS, results)), flush=True)
        plot_group(group, plots, output, args.phase)
    payload = dict(phase=args.phase, corpus_sha256=hashlib.sha256(
        (root / "tests/fixtures/mfh_layouts/corpus.json").read_bytes()).hexdigest(),
        cases=rows, by_group={group: summary([r for r in rows if r["group"] == group])
                             for group in groups})
    path = output / f"{args.phase}-comparison.json"
    path.write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print(path, flush=True)


if __name__ == "__main__":
    main()
