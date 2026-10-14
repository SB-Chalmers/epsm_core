"""Reproduce the native gate using the archived, unapplied Core trial patch."""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely.geometry import shape

from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.specs import Footprint, ZoningSpec


def main():
    try:
        from epsm_core.specs.geometry import MfhLayoutSpec
    except ImportError as exc:
        raise SystemExit("Trial requires output/analysis/mfh-zoning-2026-10-13/core-trial.patch") from exc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("initial", "refined"), default="refined")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests/core"))
    from conftest import building

    output = root / "output/analysis/mfh-zoning-2026-10-13"
    comparison = json.loads((output / f"{args.phase}-comparison.json").read_text())
    corpus = json.loads((root / "tests/fixtures/mfh_layouts/corpus.json").read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    baseline = building.__wrapped__(output)
    compiler = EnergyPlusCompiler(energyplus="/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    records = []
    for row in comparison["cases"]:
        if row["status"] == "fallback":
            continue
        case = cases[row["id"]]
        polygon = shape(case["preparation"]["cleaned_geometry"])
        footprint = Footprint(exterior=tuple(polygon.exterior.coords[:-1]),
                              holes=tuple(tuple(r.coords[:-1]) for r in polygon.interiors))
        method = row["method"].split()[0]
        resolution = 0.5 if row["method"] == "grid 0.5" else None
        zoning = ZoningSpec(mode="mfh", mfh=MfhLayoutSpec(method=method, grid_size_m=resolution))
        part = baseline.geometry.parts[0].updated(footprint=footprint)
        geometry = baseline.geometry.updated(parts=(part,), zoning=zoning)
        spec = baseline.updated(geometry=geometry,
                                envelope=baseline.envelope.updated(
                                    common_partition=baseline.envelope.wall,
                                    dwelling_partition=baseline.envelope.intermediate_floor),
                                use=baseline.use.updated(occupancy_category="residential"))
        start = time.perf_counter()
        try:
            model, report = compiler.compile(spec)
            data = report.data
            zoning_status = data["layout"]["status"]
            common = [z for z in data["zones"].values() if z.get("zone_kind") == "common"]
            fields = dict(success=True, status=zoning_status,
                          matching_status=zoning_status == row["status"],
                          native_surface_count=len(data["surfaces"]),
                          foundation_count=len(model.get("Foundation:Kiva", {})),
                          common_zone_count=len(common),
                          common_area_m2=sum(z["floor_area_m2"] for z in common),
                          common_conditioned_count=sum(z["conditioned"] for z in common),
                          conditioned_area_m2=data["conditioned_floor_area_m2"],
                          gross_area_m2=data["gross_floor_area_m2"],
                          conditioned_volume_m3=data["conditioned_volume_m3"],
                          residential_load_scale=data["residential_load_scale"],
                          validation=data["validation"])
        except Exception as exc:
            fields = dict(success=False, error=f"{type(exc).__name__}: {exc}")
        record = dict(id=row["id"], group=row["group"], method=row["method"],
                      expected_status=row["status"], runtime_s=time.perf_counter()-start, **fields)
        records.append(record)
        print(f"{row['group']} {row['id'][:12]} {row['method']}: "
              f"{'ok' if record['success'] else record['error']}", flush=True)
    path = output / f"{args.phase}-native-validation.json"
    path.write_text(json.dumps(dict(candidates=records, totals={
        group: dict(Counter("compiled" if r["success"] else "failed" for r in records
                            if r["group"] == group))
        for group in ("mfh", "synthetic", "regression")}), indent=2, default=float) + "\n")
    print(path, flush=True)


if __name__ == "__main__":
    main()
