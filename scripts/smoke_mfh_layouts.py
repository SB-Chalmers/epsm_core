"""Reproduce three-day EnergyPlus checks using the archived Core trial patch."""

import json
import subprocess
import sys
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
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests/core"))
    from conftest import building

    output = root / "output/analysis/mfh-zoning-2026-10-13"
    corpus = json.loads((root / "tests/fixtures/mfh_layouts/corpus.json").read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    base = building.__wrapped__(output)
    compiler = EnergyPlusCompiler(energyplus="/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    requests = (("compact", "compact_400", "modules"),
                ("slab", "slab_1120", "modules"),
                ("multiple_core", "rectangle_450", "modules"),
                ("simplified", "square_867", "offset"))
    records = []
    for label, identifier, method in requests:
        polygon = shape(cases[identifier]["preparation"]["cleaned_geometry"])
        footprint = Footprint(exterior=tuple(polygon.exterior.coords[:-1]))
        part = base.geometry.parts[0].updated(footprint=footprint)
        spec = base.updated(
            geometry=base.geometry.updated(parts=(part,), zoning=ZoningSpec(
                mode="mfh", mfh=MfhLayoutSpec(method=method))),
            envelope=base.envelope.updated(common_partition=base.envelope.wall,
                                           dwelling_partition=base.envelope.intermediate_floor),
            use=base.use.updated(occupancy_category="residential"))
        case_dir = output / "smoke" / label
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            model, report = compiler.compile(spec)
            period = model["RunPeriod"]["annual"]
            period.update(end_month=1, end_day_of_month=3)
            source = case_dir / "model.epJSON"
            source.write_text(json.dumps(model, indent=2) + "\n")
            process = subprocess.run([
                str(compiler.executable), "-w", str(base.climate.epw_path),
                "-d", str(case_dir), str(source)], capture_output=True, text=True,
                timeout=180, check=False)
            err = (case_dir / "eplusout.err").read_text() if (case_dir / "eplusout.err").exists() else ""
            fields = dict(compile_success=True, simulation_success=process.returncode == 0,
                          returncode=process.returncode,
                          layout_status=report.data["layout"]["status"],
                          error_tail="\n".join(err.splitlines()[-20:]),
                          stdout_tail="\n".join(process.stdout.splitlines()[-8:]))
        except Exception as exc:
            fields = dict(compile_success=False, simulation_success=False,
                          error=f"{type(exc).__name__}: {exc}")
        records.append(dict(case=label, source_id=identifier, method=method, **fields))
        print(label, fields.get("layout_status"), fields["simulation_success"],
              fields.get("error", ""), flush=True)
    (output / "energyplus-smoke.json").write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    main()
