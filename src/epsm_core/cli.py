# File: cli.py
# Purpose: Small CLI over the same public compile/run API.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document cli interfaces, examples, constraints and processing rationale.

"""Small CLI over the same public compile/run API.

Notes
-----
Commands delegate to the same public interfaces used from Python. Schema and validation
operate without engine discovery; compile, run and export-idf require EnergyPlus 24.2.
The view command serves local artifacts until interrupted.

Examples
--------
Example::

    from epsm_core.cli import main

    main(["schema"])
"""

import argparse
import json
import subprocess
from pathlib import Path

from .compiler import EnergyPlusCompiler
from .runner import EnergyPlusRunner
from .settings import CompilerSettings
from .specs import BuildingSpec


def main(argv=None):
    """Dispatch schema, validation, compilation, simulation, export or preview commands.

    Parameters
    ----------
    argv : sequence of str or None
        Command arguments excluding the executable name; None reads sys.argv. Default:
        ``None``.

    Returns
    -------
    None
        Results are printed or written to the requested paths.

    Raises
    ------
    FileExistsError
        Rejected conditions: Output directory must be empty.

    Notes
    -----
    argv=None reads process arguments. argparse exits on invalid syntax; view blocks until
    Ctrl-C. Compilation/run/export require EnergyPlus 24.2; schema and validation do not
    instantiate the engine.

    Examples
    --------
    Example::

        from epsm_core.cli import main

        main(["schema"])
    """

    # 1. Dispatch schema, validation, compilation, simulation, export or preview commands.
    parser = argparse.ArgumentParser(prog="epsm-core")
    parser.add_argument("--energyplus", help="EnergyPlus 24.2 executable")
    parser.add_argument("--shadow-max-figures", type=int, default=10000000)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="Print the canonical BuildingSpec JSON Schema")
    for name in ("validate", "compile", "run", "export-idf"):
        p = sub.add_parser(name)
        p.add_argument("spec", type=Path)
        if name != "validate":
            p.add_argument("output", type=Path)
    view = sub.add_parser("view", help="Inspect existing epJSON without simulation")
    view.add_argument("epjson", type=Path)
    view.add_argument(
        "--headless", action="store_true", help="Print loopback URL without launching browser"
    )
    args = parser.parse_args(argv)
    if args.command == "view":
        import time

        from .viewer import view_epjson

        with view_epjson(args.epjson, launch_browser=not args.headless) as handle:
            print(handle.url, flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return
    if args.command == "schema":
        print(json.dumps(BuildingSpec.model_json_schema(), indent=2))
        return
    building = BuildingSpec.model_validate_json(args.spec.read_text())
    if args.command == "validate":
        print(building.physical_hash())
    elif args.command == "run":
        result = EnergyPlusRunner(
            args.energyplus, settings=CompilerSettings(shadow_max_figures=args.shadow_max_figures)
        ).run(building, args.output)
        print(json.dumps(result.scalars, indent=2))
    else:
        compiler = EnergyPlusCompiler(
            args.energyplus, settings=CompilerSettings(shadow_max_figures=args.shadow_max_figures)
        )
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
