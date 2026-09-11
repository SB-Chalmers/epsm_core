"""Probe the pinned executable's close-vertex behavior on a small chamfered shade."""

import copy
import sys
from pathlib import Path

from optimization import EnergyPlusCompiler, cases, run


def main():
    root = Path(sys.argv[1]).resolve()
    compiler = EnergyPlusCompiler("/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    _, spec = next(cases())
    spec = spec.updated(context=type(spec.context)())
    base, report = compiler.compile(spec)
    for distance in (1e-6, 1e-5, 1e-4, 1e-3, 1e-2):
        model = copy.deepcopy(base)
        model["RunPeriod"]["annual"].update(end_month=1, end_day_of_month=1)
        # A short diagonal edge, not a redundant collinear intermediate vertex.
        points = [
            (0, -5, 0),
            (10, -5, 0),
            (10, -5, 10 - distance),
            (10 - distance, -5, 10),
            (0, -5, 10),
        ]
        model["Shading:Building:Detailed"] = {
            "probe": dict(
                number_of_vertices=5,
                vertices=[{f"vertex_{a}_coordinate": v for a, v in zip("xyz", p)} for p in points],
            )
        }
        model["Output:Diagnostics"] = {
            "probe": dict(diagnostics=[dict(key="DisplayExtraWarnings")])
        }
        run(compiler, spec, model, report, root / f"edge-{distance}")


if __name__ == "__main__":
    main()
