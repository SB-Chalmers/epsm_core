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
# Date modified: 2026-10-05
# Changelog:
#   2026-10-05 - Add opt-in, audited context simplification for pure shadow-limit failures.
#   2026-10-03 - Add documented calendar, operational and archetype-application support.
#   2026-09-12 - Record the configured overlap capacity in shadow-limit diagnostics.
#   2026-09-11 - Remove recovery retries and automatic previews; preserve classified failure evidence.
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
import os
import subprocess
import time
from pathlib import Path

import numpy as np

from epsm_core._logging import bind_context, context_logger, current_context
from epsm_core._logging import operation as logged_operation

from .compiler import EnergyPlusCompiler
from .delivery import fvp_delivery
from .diagnostics import WHOLE_BUILDING_AREA_RULE, compiler_warning_conditions, error_diagnostics
from .failures import (
    ENERGYPLUS_NUMERICAL_FAILURE,
    EXTERNAL_ENVIRONMENT_FAILURE,
    SHADOW_COMPLEXITY_LIMIT,
    engine_failure_code,
)
from .heating_delivery import heating_delivery
from .pv import run_pvwatts
from .results import read_results
from .warning_review import approve_validated_psychrometrics, psychrometric_review_pending


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

    def __init__(self, message, *, code=ENERGYPLUS_NUMERICAL_FAILURE):
        self.code = code
        super().__init__(f"{code}: {message}")


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

    @logged_operation("simulation")
    def run(
        self,
        spec,
        directory,
        *,
        timeout_seconds=1800,
        warning_rules=(),
        review_psychrometric_warnings=True,
        recover_context_shadows=False,
    ):
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
        review_psychrometric_warnings : bool
            Permit bounded 24.2 psychrometric warnings after full output validation
            for annual heating. False restores warning-strict behavior. Default True.
        recover_context_shadows : bool
            Opt in to audited 1 m then 2 m context-only simplification after a
            pure shadow-capacity failure. Defaults False; supplied outlines remain
            strict unless enabled. See docs/shadow-recovery.md.
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

        options = dict(
            timeout_seconds=timeout_seconds,
            warning_rules=warning_rules,
            review_psychrometric_warnings=review_psychrometric_warnings,
        )
        if recover_context_shadows:
            from .shadow_recovery import run_with_context_shadow_recovery

            return run_with_context_shadow_recovery(self._run_once, spec, directory, **options)
        return self._run_once(spec, directory, **options)

    def _run_once(
        self,
        spec,
        directory,
        *,
        timeout_seconds=1800,
        warning_rules=(),
        review_psychrometric_warnings=True,
    ):
        """Execute one unchanged scene; retries belong to the opt-in public wrapper."""

        # 1. Compile, execute and validate a simulation before writing its completion marker.
        directory = Path(directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"Run directory must be empty: {directory}")
        from .weather import validate_epw_calendar

        compile_start = time.perf_counter()
        # 2. Emit validated inputs before launching the single simulation process.
        try:
            report = self.compiler.write(spec, directory)
        except (ValueError, OSError) as error:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "building.json").write_text(spec.model_dump_json(indent=2))
            diagnostics = dict(
                accepted=False,
                failure="compilation",
                failure_detail=str(error),
                failure_code=getattr(error, "code", EXTERNAL_ENVIRONMENT_FAILURE),
                compiler_sha256=self.compiler.compiler_hash,
                engine_sha256=self.compiler.engine_hash,
                schema_sha256=self.compiler.schema_hash,
                compiler_settings=self.compiler.settings.model_dump(mode="json"),
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            raise
        compile_seconds = time.perf_counter() - compile_start
        try:
            calendar = validate_epw_calendar(spec.climate.epw_path, spec.climate.calendar_year)
            (directory / "calendar.json").write_text(json.dumps(calendar, indent=2))
        except Exception as error:
            diagnostics = dict(
                accepted=False,
                failure="weather_calendar",
                failure_detail=str(error),
                failure_code=EXTERNAL_ENVIRONMENT_FAILURE,
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            raise SimulationError(
                f"Weather calendar rejected; artifacts at {directory}: {error}",
                code=EXTERNAL_ENVIRONMENT_FAILURE,
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
        bind_context(run_id=report.run_id)
        logger = context_logger(__name__)
        logger.debug(
            "Launching EnergyPlus",
            extra={
                "epsm_event": "simulation.engine.started",
                "epsm_details": {
                    "executable": command[0],
                    "directory": str(directory),
                    "stdout_stderr": str(directory / "process.log"),
                },
            },
        )
        simulation_start = time.perf_counter()
        with (directory / "process.log").open("w") as log:
            try:
                result = subprocess.run(
                    command,
                    cwd=directory,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                    env={**os.environ, "OMP_NUM_THREADS": "1", "EP_OMP_NUM_THREADS": "1"},
                )
            except subprocess.TimeoutExpired as error:
                diagnostics = error_diagnostics(directory / "eplusout.err")
                diagnostics.update(
                    accepted=False, failure="timeout", failure_code=EXTERNAL_ENVIRONMENT_FAILURE
                )
                (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
                raise SimulationError(
                    f"EnergyPlus timeout; diagnostics at {directory}",
                    code=EXTERNAL_ENVIRONMENT_FAILURE,
                ) from error
            except OSError as error:
                diagnostics = dict(
                    accepted=False,
                    failure="process_start",
                    failure_code=EXTERNAL_ENVIRONMENT_FAILURE,
                    failure_detail=str(error),
                )
                (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
                raise SimulationError(
                    f"Could not launch EnergyPlus; artifacts at {directory}: {error}",
                    code=EXTERNAL_ENVIRONMENT_FAILURE,
                ) from error
        simulation_seconds = time.perf_counter() - simulation_start
        logger.log(
            10 if current_context().get("batch_mode") else 20,
            "EnergyPlus exited",
            extra={
                "epsm_event": "simulation.engine.completed",
                "epsm_details": {
                    "returncode": result.returncode,
                    "duration_s": simulation_seconds,
                    "process_log": str(directory / "process.log"),
                    "engine_errors": str(directory / "eplusout.err"),
                },
            },
        )

        # 4. Validate every attempt under the same strict diagnostic policy.
        def diagnose(attempt_directory, report, returncode):
            compiled_model = json.loads((attempt_directory / "model.epJSON").read_text())
            conditions = compiler_warning_conditions(spec, compiled_model, report)
            diagnostics = error_diagnostics(
                attempt_directory / "eplusout.err",
                rules=(WHOLE_BUILDING_AREA_RULE, *warning_rules),
                conditions=conditions,
            )
            if returncode:
                diagnostics.update(accepted=False, process_returncode=returncode)
            return diagnostics, compiled_model

        diagnostics, compiled_model = diagnose(directory, report, result.returncode)
        end_path = directory / "eplusout.end"
        review_pending = review_psychrometric_warnings and psychrometric_review_pending(
            diagnostics, compiled_model, end_path.read_text() if end_path.exists() else ""
        )
        diagnostics.update(policy_version="evidence-2", warning_review_pending=bool(review_pending))
        if not diagnostics["accepted"]:
            diagnostics["failure_code"] = engine_failure_code(diagnostics)
            if diagnostics["failure_code"] == SHADOW_COMPLEXITY_LIMIT:
                context = report.data["context"]
                shadow_settings = next(iter(compiled_model["ShadowCalculation"].values()))
                diagnostics["shadow_complexity"] = dict(
                    maximum_figures_in_shadow_overlap_calculations=shadow_settings[
                        "maximum_figures_in_shadow_overlap_calculations"
                    ],
                    receiving_surfaces=sorted(
                        {
                            name
                            for m in diagnostics["messages"]
                            if m["category"] == "shadow_overlap_limit"
                            for name in m["affected_objects"]
                        }
                    ),
                    context_radius_m=context.get("generation", {}).get("radius_m"),
                    emitted_shading_faces=context["visibility"]["retained_count"]
                    + context["unqualified_surface_count"],
                    pruning=context["visibility"]["method"],
                    mirror_suppression=context["mirror_suppression_eligible"],
                    recommended_action="Inspect retained model and overlap diagnostics; "
                    "a valid dense model may exceed PolygonClipping capacity. No retry performed.",
                )
        (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
        if (
            result.returncode
            or (not diagnostics["accepted"] and not review_pending)
            or diagnostics["fatal_count"]
            or diagnostics["severe_count"]
            or diagnostics["invalid_view_factor_count"]
        ):
            raise SimulationError(
                f"Simulation acceptance rejected: {diagnostics}; see {directory / 'process.log'}",
                code=diagnostics.get("failure_code", ENERGYPLUS_NUMERICAL_FAILURE),
            )
        try:
            diagnostics["zoning"] = report.data.get("zoning", {})
            # 5. Require exact hourly calendars and reconciled annual energy before accepting
            # SQL results.
            output = read_results(directory / "eplusout.sql", spec, report, diagnostics)
            if review_pending:
                approve_validated_psychrometrics(diagnostics, output, report)
                diagnostics["warning_review_pending"] = False
        except Exception as error:
            failure_code = getattr(error, "code", ENERGYPLUS_NUMERICAL_FAILURE)
            diagnostics.update(
                accepted=False,
                failure="result_validation",
                warning_review_pending=False,
                disposition="rejected",
                failure_detail=str(error),
                failure_code=failure_code,
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            raise SimulationError(
                f"Result validation failed; artifacts at {directory}: {error}",
                code=failure_code,
            ) from error
        output.scalars.update(
            compile_seconds=compile_seconds,
            simulation_seconds=simulation_seconds,
            zone_count=len(report.data["zones"]),
            surface_count=len(report.data["surfaces"]),
            logical_window_count=report.data["logical_window_count"],
            thermal_pane_count=report.data["thermal_pane_count"],
            shading_surface_count=sum(
                not s.get("physical_parent") for s in report.data["shading"].values()
            ),
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
            if spec.delivery.heating:
                extra = heating_delivery(spec, output.hourly["space_heating_demand_kwh"], report)
                output.hourly.update(extra)
                output.units.update({key: "kWh" for key in extra})
                output.scalars.update({key: float(value.sum()) for key, value in extra.items()})
                diagnostics["heating_delivery"] = spec.delivery.heating.model_dump(mode="json")
            if spec.renewables.pv_systems:
                generation = np.zeros(spec.climate.hours_in_year)
                for pv in spec.renewables.pv_systems:
                    generation += run_pvwatts(pv, spec.climate)["pv_hourly_kwh"]
                output.hourly["pv_generation_kwh"] = generation
                output.units["pv_generation_kwh"] = "kWh"
                output.scalars["pv_generation_kwh"] = float(generation.sum())
        except Exception as error:
            diagnostics.update(
                accepted=False,
                disposition="rejected",
                failure="delivery_or_pv",
                failure_detail=str(error),
            )
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
            raise SimulationError(
                f"Delivery/PV validation failed; artifacts at {directory}: {error}"
            ) from error
        # 7. Persist assumptions and final diagnostics before writing the completion marker.
        diagnostics["model_assumptions"] = dict(
            foundation=report.data["foundation"],
            ground_temperature=report.data["ground_temperature"],
            approximations=report.data["approximations"],
            empirical_validation="not_evaluated_by_core",
        )
        (directory / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
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
