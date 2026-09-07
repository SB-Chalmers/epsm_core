# File: runner.py
# Purpose: Isolated EnergyPlus execution; completion requires valid SQL and diagnostics.
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
#   2026-09-06 - Document runner interfaces, examples, constraints and processing rationale.

"""Isolated EnergyPlus execution; completion requires valid SQL and diagnostics.

Notes
-----
Runs require empty output directories. Compilation, EPW calendar, process diagnostics,
SQL results and optional delivery/PV accounting are validated in sequence. Failed stages
retain available diagnostic artifacts; result.json is written only after all stages
succeed.

Examples
--------
Replace example paths with existing local inputs; output paths must be writable.

Example::

    from epsm_core.runner import EnergyPlusRunner

    runner = EnergyPlusRunner(energyplus="/path/to/EnergyPlus/energyplus")
"""

import json
import subprocess
import time
from pathlib import Path

import numpy as np

from .compiler import EnergyPlusCompiler
from .delivery import fvp_delivery
from .diagnostics import WHOLE_BUILDING_AREA_RULE, compiler_warning_conditions, error_diagnostics
from .pv import run_pvwatts
from .results import read_results


class SimulationError(RuntimeError):
    """Signal a failed simulation or downstream result-validation stage.

    Notes
    -----
    Failed runs retain logs, diagnostics and preview artifacts where those were produced.
    This exception does not imply that all output files exist or that an incomplete run may
    be reused.

    Examples
    --------
    Example::

        from epsm_core.runner import SimulationError

        error = SimulationError("EnergyPlus timeout; inspect retained diagnostics")
    """

    pass


class EnergyPlusRunner:
    """Execute isolated compiled models and accept only validated results.

    Attributes
    ----------
    compiler : EnergyPlusCompiler
        Compiler owning executable discovery, settings and compilation identities.

    Notes
    -----
    Owns a compiler and requires empty run directories. Calendar, process, diagnostics, SQL,
    delivery and PV checks precede the final result.json marker.

    Examples
    --------
    Replace example paths with existing local inputs; output paths must be writable.

    Example::

        from epsm_core.runner import EnergyPlusRunner

        runner = EnergyPlusRunner(energyplus="/path/to/EnergyPlus/energyplus")
    """

    def __init__(self, energyplus=None, *, settings=None):
        """Bind a runner to a validated EnergyPlus compiler installation.

        Parameters
        ----------
        energyplus : str or Path or None
            EnergyPlus 24.2 executable; None uses ENERGYPLUS_EXE then PATH. Default: ``None``.
        settings : CompilerSettings or None
            Explicit engine controls; None uses CompilerSettings defaults. Default: ``None``.

        Returns
        -------
        None
            Initializes the compiler used by subsequent runs.

        Notes
        -----
        Resolving the compiler executes the engine version command and reads/hashes the
        executable and schema; no simulation starts here.

        Examples
        --------
        Replace example paths with existing local inputs; output paths must be writable.

        Example::

            from epsm_core.runner import EnergyPlusRunner

            runner = EnergyPlusRunner(energyplus="/path/to/EnergyPlus/energyplus")
        """

        self.compiler = EnergyPlusCompiler(energyplus, settings=settings)

    def run(self, spec, directory, *, timeout_seconds=1800, warning_rules=()):
        """Compile, execute and validate a simulation before writing its completion marker.

        Parameters
        ----------
        spec : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.
        directory : str or Path or None
            Local artifact directory; consult Notes for creation, overwrite and default-path
            behavior.
        timeout_seconds : float
            Maximum wall-clock seconds allowed for the EnergyPlus subprocess. Default: ``1800``.
        warning_rules : sequence of WarningRule
            Explicit versioned warning exceptions; severe/fatal and always-fail categories
            cannot be waived. Default: ``()``.

        Returns
        -------
        SimulationResult
            Validated hourly signals, scalars, units and artifact paths.

        Raises
        ------
        FileExistsError
            If the input or generated result violates the constraints described in Notes.
        SimulationError
            If the input or generated result violates the constraints described in Notes.

        Notes
        -----
        Requires an empty output directory, EnergyPlus 24.2 and a complete EPW. Writes model,
        logs, calendar, diagnostics and previews. Timeout and validation failures retain
        diagnostic artifacts. result.json is written last; partial output does not indicate
        success.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``; an initialized EnergyPlusRunner as
        ``runner`` (EnergyPlus 24.2 required).

        Example::

            result = runner.run(building, "output/new-run", timeout_seconds=1800)
        """

        # 1. Compile, execute and validate a simulation before writing its completion marker.
        directory = Path(directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"Run directory must be empty: {directory}")
        from .weather import validate_epw_calendar

        compile_start = time.perf_counter()
        # 2. Emit validated inputs and a preview before launching any simulation process.
        report = self.compiler.write(spec, directory)
        compile_seconds = time.perf_counter() - compile_start
        from .viewer import write_viewer

        write_viewer(directory / "model.epJSON", directory / "preview")
        try:
            calendar = validate_epw_calendar(spec.climate.epw_path, spec.climate.calendar_year)
            (directory / "calendar.json").write_text(json.dumps(calendar, indent=2))
        except Exception as error:
            diagnostics = dict(
                accepted=False, failure="weather_calendar", failure_detail=str(error)
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            write_viewer(directory / "model.epJSON", directory / "preview")
            raise SimulationError(
                f"Weather calendar rejected; preview at {directory}: {error}"
            ) from error
        # 3. Run in the isolated artifact directory and retain combined process output.
        command = [
            str(self.compiler.executable),
            "-w",
            spec.climate.epw_path,
            "-d",
            str(directory),
            str(directory / "model.epJSON"),
        ]
        simulation_start = time.perf_counter()
        with (directory / "process.log").open("w") as log:
            try:
                result = subprocess.run(
                    command,
                    cwd=directory,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as error:
                diagnostics = error_diagnostics(directory / "eplusout.err")
                diagnostics.update(accepted=False, failure="timeout")
                (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
                write_viewer(directory / "model.epJSON", directory / "preview")
                raise SimulationError(f"EnergyPlus timeout; diagnostics at {directory}") from error
        simulation_seconds = time.perf_counter() - simulation_start
        # 4. Derive warning exceptions from emitted evidence, then evaluate actual engine
        # diagnostics.
        conditions = compiler_warning_conditions(
            spec, json.loads((directory / "model.epJSON").read_text()), report
        )
        diagnostics = error_diagnostics(
            directory / "eplusout.err",
            rules=(WHOLE_BUILDING_AREA_RULE, *warning_rules),
            conditions=conditions,
        )
        if result.returncode:
            diagnostics.update(accepted=False, process_returncode=result.returncode)
        (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
        write_viewer(directory / "model.epJSON", directory / "preview")
        if (
            result.returncode
            or not diagnostics["accepted"]
            or diagnostics["fatal_count"]
            or diagnostics["severe_count"]
            or diagnostics["invalid_view_factor_count"]
        ):
            raise SimulationError(
                f"EnergyPlus failed: {diagnostics}; see {directory / 'process.log'}"
            )
        try:
            diagnostics["zoning"] = report.data.get("zoning", {})
            # 5. Require exact hourly calendars and reconciled annual energy before accepting
            # SQL results.
            output = read_results(directory / "eplusout.sql", spec, report, diagnostics)
        except Exception as error:
            diagnostics.update(
                accepted=False, failure="result_validation", failure_detail=str(error)
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            write_viewer(directory / "model.epJSON", directory / "preview")
            raise SimulationError(
                f"Result validation failed; artifacts at {directory}: {error}"
            ) from error
        output.scalars.update(
            compile_seconds=compile_seconds,
            simulation_seconds=simulation_seconds,
            zone_count=len(report.data["zones"]),
            surface_count=len(report.data["surfaces"]),
            logical_window_count=report.data["logical_window_count"],
            thermal_pane_count=report.data["thermal_pane_count"],
            shading_surface_count=len(report.data["shading"]),
        )
        try:
            # 6. Account for heat-pump delivery and optional PV only after thermal-demand
            # validation.
            if spec.delivery.fvp:
                temps, weights = [], []
                for zone, data in report.data["zones"].items():
                    if data["conditioned"]:
                        temps.append(output.hourly[f"Zone Mean Air Temperature::{zone.upper()}"])
                        weights.append(data["floor_area_m2"])
                extra = fvp_delivery(
                    spec,
                    output.hourly["space_heating_demand_kwh"],
                    output.hourly["dhw_load_kwh"],
                    np.average(temps, axis=0, weights=weights),
                )
                output.hourly.update(extra)
                output.units.update({key: "kWh" for key in extra})
                output.scalars.update({key: float(value.sum()) for key, value in extra.items()})
            if spec.renewables.pv_systems:
                generation = np.zeros(spec.climate.hours_in_year)
                for pv in spec.renewables.pv_systems:
                    generation += run_pvwatts(pv, spec.climate)["pv_hourly_kwh"]
                output.hourly["pv_generation_kwh"] = generation
                output.units["pv_generation_kwh"] = "kWh"
                output.scalars["pv_generation_kwh"] = float(generation.sum())
        except Exception as error:
            diagnostics.update(accepted=False, failure="delivery_or_pv", failure_detail=str(error))
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            write_viewer(directory / "model.epJSON", directory / "preview")
            raise SimulationError(
                f"Delivery/PV validation failed; artifacts at {directory}: {error}"
            ) from error
        # 7. Persist assumptions and final diagnostics before writing the completion marker.
        diagnostics["model_assumptions"] = dict(
            ground_temperature=report.data["ground_temperature"],
            approximations=report.data["approximations"],
            empirical_validation="not_evaluated_by_core",
        )
        (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
        write_viewer(directory / "model.epJSON", directory / "preview")
        # Marker is written last and never substitutes for external store validation.
        (directory / "result.json").write_text(
            json.dumps(
                dict(
                    run_id=output.run_id,
                    scalars=output.scalars,
                    units=output.units,
                    diagnostics=output.diagnostics,
                ),
                indent=2,
            )
        )
        return output
