"""Time the public runner, including compilation, SQL validation and old previews.

Arguments: artifact root, package source directory, campaign label.
"""

# ruff: noqa: E402
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root, source, campaign = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
sys.path.insert(0, source)
os.environ["OMP_NUM_THREADS"] = os.environ["EP_OMP_NUM_THREADS"] = "1"

from epsm_core import BuildingSpec, EnergyPlusRunner

runner = EnergyPlusRunner("/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
specs = [
    (path.name, BuildingSpec.model_validate_json((path / "building.json").read_text()))
    for path in sorted((root / "baseline").iterdir())
]


def simulate(item):
    name, spec, repetition = item
    start = time.perf_counter()
    # DistrictPlan uses this same prospective identity call before running.
    identity = runner.compiler.run_id(spec)
    result = runner.run(spec, root / "workflow" / f"{campaign}-{name}-{repetition}-{identity[:8]}")
    return dict(
        case=name,
        wall_seconds=time.perf_counter() - start,
        accepted=result.diagnostics["accepted"],
        compile_seconds=result.scalars["compile_seconds"],
        simulation_seconds=result.scalars["simulation_seconds"],
        scalars=result.scalars,
    )


start = time.perf_counter()
with ThreadPoolExecutor(max_workers=2) as pool:
    metrics = list(pool.map(simulate, [(name, spec, i) for i in range(3) for name, spec in specs]))
elapsed = time.perf_counter() - start
summary = dict(
    campaign=campaign,
    workers=2,
    buildings=len(metrics),
    wall_seconds=elapsed,
    buildings_per_minute=60 * len(metrics) / elapsed,
    runs=metrics,
)
(root / f"workflow-{campaign}.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
print(campaign, elapsed, summary["buildings_per_minute"], "buildings/minute", flush=True)
