"""Two-worker production batch with sampled aggregate EnergyPlus RSS."""

import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
from optimization import BuildingSpec, EnergyPlusCompiler, dump, run


def main():
    root = Path(sys.argv[1]).resolve()
    campaign = sys.argv[2] if len(sys.argv) > 2 else ""
    folder = "batch" + ("-" + campaign if campaign else "")
    compiler = EnergyPlusCompiler("/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    inputs = []
    for directory in sorted((root / "baseline").iterdir()):
        spec = BuildingSpec.model_validate_json((directory / "building.json").read_text())
        candidate, report = compiler.compile(spec)
        reference = json.loads((directory / "model.epJSON").read_text())
        inputs.append((directory.name, spec, reference, candidate, report))
    labels = ["reference", "candidate"]
    random.Random(17).shuffle(labels)
    summary = {}
    for label in labels:
        stop = threading.Event()
        memory = []
        parent = psutil.Process()

        def sample():
            while not stop.is_set():
                rss = 0
                for process in parent.children(recursive=True):
                    try:
                        if process.name().lower().startswith("energyplus"):
                            rss += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                memory.append(rss)
                stop.wait(0.05)

        sampler = threading.Thread(target=sample)
        sampler.start()
        jobs = [
            (name, spec, reference if label == "reference" else candidate, report, index)
            for index in range(4)
            for name, spec, reference, candidate, report in inputs
        ]
        random.Random(17).shuffle(jobs)

        def simulate(job):
            name, spec, model, report, index = job
            return run(compiler, spec, model, report, root / folder / f"{label}-{name}-{index}")

        start = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                metrics = list(pool.map(simulate, jobs))
        finally:
            elapsed = time.perf_counter() - start
            stop.set()
            sampler.join()
        summary[label] = dict(
            workers=2,
            buildings=len(jobs),
            wall_seconds=elapsed,
            buildings_per_minute=60 * len(jobs) / elapsed,
            total_cpu_seconds=sum(m["cpu_seconds"] for m in metrics),
            two_core_cpu_utilization=sum(m["cpu_seconds"] for m in metrics) / (2 * elapsed),
            peak_aggregate_rss_bytes=max(memory),
            failure_rate=sum(not m["accepted"] for m in metrics) / len(metrics),
            worker_wall_seconds=[m["wall_seconds"] for m in metrics],
            io_wait="not exposed by macOS",
            compilation="precompiled for both configurations",
        )
    summary["throughput_improvement_fraction"] = (
        summary["candidate"]["buildings_per_minute"] / summary["reference"]["buildings_per_minute"]
        - 1
    )
    dump(root / ("throughput" + ("-" + campaign if campaign else "") + ".json"), summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
