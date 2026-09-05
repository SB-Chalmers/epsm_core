"""Isolated EnergyPlus execution; completion requires valid SQL and diagnostics."""

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .compiler import EnergyPlusCompiler
from .delivery import fvp_delivery
from .pv import run_pvwatts
from .results import read_results


class SimulationError(RuntimeError):
    pass


def error_diagnostics(path):
    text = Path(path).read_text(errors="replace") if Path(path).exists() else ""
    return {
        "warning_count": len(re.findall(r"\*\*\s+Warning\s+\*\*", text)),
        "severe_count": len(re.findall(r"\*\*\s+Severe\s+\*\*", text)),
        "fatal_count": len(re.findall(r"\*\*\s+Fatal\s+\*\*", text)),
        "invalid_view_factor_count": text.count("FixViewFactors: View factors not complete"),
        "err_path": str(path),
    }


class EnergyPlusRunner:
    def __init__(self, energyplus=None):
        self.compiler = EnergyPlusCompiler(energyplus)

    def run(self, spec, directory, *, timeout_seconds=1800):
        directory = Path(directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"Run directory must be empty: {directory}")
        report = self.compiler.write(spec, directory)
        command = [
            str(self.compiler.executable),
            "-w",
            spec.climate.epw_path,
            "-d",
            str(directory),
            str(directory / "model.epJSON"),
        ]
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
                raise SimulationError(f"EnergyPlus timeout; diagnostics at {directory}") from error
        diagnostics = error_diagnostics(directory / "eplusout.err")
        if (
            result.returncode
            or diagnostics["fatal_count"]
            or diagnostics["severe_count"]
            or diagnostics["invalid_view_factor_count"]
        ):
            raise SimulationError(
                f"EnergyPlus failed: {diagnostics}; see {directory / 'process.log'}"
            )
        output = read_results(directory / "eplusout.sql", spec, report, diagnostics)
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
            generation = np.zeros(8760)
            for pv in spec.renewables.pv_systems:
                generation += run_pvwatts(pv, spec.climate)["pv_hourly_kwh"]
            output.hourly["pv_generation_kwh"] = generation
            output.units["pv_generation_kwh"] = "kWh"
            output.scalars["pv_generation_kwh"] = float(generation.sum())
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
