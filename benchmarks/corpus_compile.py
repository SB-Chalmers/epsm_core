"""Compile every accepted prepared footprint; preserve every rejected specification."""

import json
import sys
from pathlib import Path

from optimization import ROOT, EnergyPlusCompiler, dump, example_spec
from shapely.geometry import shape

from epsm_core import BuildingPart, Footprint, GeometrySpec


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = EnergyPlusCompiler("/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    base = example_spec(
        ROOT / "data/weather/SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw"
    )
    results = {}
    for path in sorted((ROOT / "tests/fixtures/footprints").glob("*.json")):
        artifact = json.loads(path.read_text())
        if artifact.get("status") != "accepted":
            continue
        polygon = shape(artifact["cleaned_geometry"])
        polygons = [polygon] if polygon.geom_type == "Polygon" else list(polygon.geoms)
        spec = None
        try:
            geometry = GeometrySpec(
                parts=tuple(
                    BuildingPart(
                        identifier=f"part_{i}",
                        footprint=Footprint(
                            exterior=tuple(p.exterior.coords)[:-1],
                            holes=tuple(tuple(r.coords)[:-1] for r in p.interiors),
                        ),
                        storey_elevations_m=(0, 3, 6, 9),
                    )
                    for i, p in enumerate(polygons)
                )
            )
            spec = base.updated(geometry=geometry)
            _, report = compiler.compile(spec)
            results[path.stem] = dict(passed=True, surfaces=len(report.data["surfaces"]))
        except ValueError as error:
            results[path.stem] = dict(passed=False, error=str(error))
            if spec is not None:
                dump(output / (path.stem + ".json"), spec.model_dump(mode="json"))
        if len(results) % 25 == 0:
            print(
                len(results),
                "compiled",
                sum(not r["passed"] for r in results.values()),
                "rejected",
                flush=True,
            )
    dump(output / "results.json", results)
    print(len(results), "total", sum(r["passed"] for r in results.values()), "passed", flush=True)


if __name__ == "__main__":
    main()
