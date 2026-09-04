"""Small CLI over the same public compile/run API."""

import argparse
import json
import subprocess
from pathlib import Path

from .compiler import EnergyPlusCompiler
from .runner import EnergyPlusRunner
from .specs import BuildingSpec


def main(argv=None):
    parser = argparse.ArgumentParser(prog="epsm-core")
    parser.add_argument("--energyplus", help="EnergyPlus 24.2 executable")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="Print the canonical BuildingSpec JSON Schema")
    for name in ("validate", "compile", "run", "export-idf"):
        p = sub.add_parser(name)
        p.add_argument("spec", type=Path)
        if name != "validate":
            p.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps(BuildingSpec.model_json_schema(), indent=2))
        return
    building = BuildingSpec.model_validate_json(args.spec.read_text())
    if args.command == "validate":
        print(building.physical_hash())
    elif args.command == "run":
        result = EnergyPlusRunner(args.energyplus).run(building, args.output)
        print(json.dumps(result.scalars, indent=2))
    else:
        compiler = EnergyPlusCompiler(args.energyplus)
        if args.output.exists() and any(args.output.iterdir()):
            raise FileExistsError("Output directory must be empty")
        compiler.write(building, args.output)
        if args.command == "export-idf":
            subprocess.run(
                [
                    str(compiler.executable),
                    "--convert-only",
                    "--output-directory",
                    str(args.output.resolve()),
                    str((args.output / "model.epJSON").resolve()),
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
