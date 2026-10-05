"""Regression coverage for conditional psychrometric warning acceptance."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from epsm_core.diagnostics import error_diagnostics
from epsm_core.failures import WARNING_POLICY_REJECTION, engine_failure_code
from epsm_core.warning_review import (
    RANGE_SUMMARY,
    approve_validated_psychrometrics,
    psychrometric_review_pending,
)

MODEL = {
    "ZoneHVAC:IdealLoadsAirSystem": {
        "ideal": {"humidification_control_type": "None", "dehumidification_control_type": "None"}
    }
}
END = "EnergyPlus Completed Successfully-- 1 Warning; 0 Severe Errors"


def diagnostic(tmp_path, text):
    path = tmp_path / "test.err"
    path.write_text(text)
    return error_diagnostics(path)


def range_text(count=1, caller="PsyTwbFnTdbWPb"):
    return (
        f" ** Warning ** {RANGE_SUMMARY}\n ** ~~~ ** Routine={caller}, Environment=ANNUAL,\n"
        " ** ~~~ ** Input Temperature=-209.9\n"
        f" ** ~~~ ** This error occurred {count} total times;\n"
    )


def wet_text(final=0.04, count=1):
    return (
        " ** Warning ** WetBulb not converged after 101 iterations(PsyTwbFnTdbWPb)\n"
        " ** ~~~ ** Routine=Unknown, Environment=ANNUAL,\n ** ~~~ ** Input Temperature = 3.2\n ** ~~~ ** Input Humidity Ratio= 0.0023\n"
        f" ** ~~~ ** Input Pressure = 101325\n ** ~~~ ** Resultant Temperature= {final}\n"
        " ** Warning ** WetBulb not converged after max iterations(PsyTwbFnTdbWPb)\n"
        f" ** ~~~ ** This error occurred {count} total times;\n"
    )


def test_recurring_wetbulb_is_one_event_with_preserved_details(tmp_path):
    d = diagnostic(tmp_path, wet_text())
    assert len(d["messages"]) == d["warning_count"] == 1
    assert "Input Humidity Ratio" in d["messages"][0]["original_text"]
    assert not d["accepted"]
    assert psychrometric_review_pending(d, MODEL, END)


@pytest.mark.parametrize("text", [range_text(), wet_text(), range_text() + wet_text()])
def test_pending_is_not_approved_until_outputs_validate(tmp_path, text):
    d = diagnostic(tmp_path, text)
    assert psychrometric_review_pending(d, MODEL, END) and not d["accepted"]
    output = SimpleNamespace(
        hourly={
            "space_heating_demand_kwh": np.ones(8760),
            "Zone Mean Air Temperature::ZONE": np.full(8760, 21.0),
        }
    )
    report = SimpleNamespace(data={"zones": {"zone": {}}})
    with pytest.raises(ValueError, match="geometry"):
        approve_validated_psychrometrics(d, output, report)
    assert not d["accepted"]
    d["geometry_totals"] = "engine_area_volume_reconciled"
    approve_validated_psychrometrics(d, output, report)
    assert d["accepted"] and d["disposition"] == "accepted_with_warnings"
    assert all(m["original_text"] and m["exception_rule"] for m in d["messages"])


@pytest.mark.parametrize(
    "text",
    [
        range_text(6),
        range_text(caller="CorrectZoneHumRat"),
        wet_text(final=2.0),
        wet_text(count=2),
        " ** Warning ** HVAC solver not converged\n",
        range_text() + " ** Warning ** Very small surface area\n",
        range_text() + " ** Severe ** Invalid model\n",
        range_text() + " ** Fatal ** Failed\n",
    ],
)
def test_unreviewed_and_excessive_warnings_still_reject(tmp_path, text):
    assert not psychrometric_review_pending(diagnostic(tmp_path, text), MODEL, END)


def test_incomplete_engine_wrong_version_and_humidity_controls_reject(tmp_path):
    d = diagnostic(tmp_path, range_text())
    assert not psychrometric_review_pending(d, MODEL, "EnergyPlus Terminated")
    d["engine_version"] = "24.1"
    assert not psychrometric_review_pending(d, MODEL, END)
    d["engine_version"] = "24.2"
    model = deepcopy(MODEL)
    model["ZoneHVAC:IdealLoadsAirSystem"]["ideal"]["humidification_control_type"] = "Humidistat"
    assert not psychrometric_review_pending(d, model, END)
    d["process_returncode"] = 1
    assert not psychrometric_review_pending(d, MODEL, END)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -101.0, 201.0])
def test_invalid_final_temperatures_never_approve(tmp_path, bad):
    d = diagnostic(tmp_path, range_text())
    d["geometry_totals"] = "engine_area_volume_reconciled"
    output = SimpleNamespace(
        hourly={
            "space_heating_demand_kwh": np.ones(8760),
            "Zone Mean Air Temperature::ZONE": np.full(8760, bad),
        }
    )
    with pytest.raises(ValueError):
        approve_validated_psychrometrics(d, output, SimpleNamespace(data={"zones": {"zone": {}}}))
    assert not d["accepted"]


def test_warning_rejection_has_distinct_failure_code(tmp_path):
    d = diagnostic(tmp_path, " ** Warning ** Unknown notice\n")
    assert engine_failure_code(d) == WARNING_POLICY_REJECTION


@pytest.mark.energyplus
@pytest.mark.parametrize("enabled, invalid_output", [(True, False), (False, False), (True, True)])
def test_runner_validates_outputs_before_accepting_reviewed_warning(
    building, energyplus, tmp_path, monkeypatch, enabled, invalid_output
):
    """Inject a known warning into a real completed fixture to test runner ordering."""
    import epsm_core.runner as runner_module
    from epsm_core.runner import EnergyPlusRunner, SimulationError

    actual_process_run = runner_module.subprocess.run
    actual_read = runner_module.read_results
    reads = []

    def run_with_warning(command, *args, **kwargs):
        result = actual_process_run(command, *args, **kwargs)
        if "-d" in command and result.returncode == 0:
            directory = __import__("pathlib").Path(command[command.index("-d") + 1])
            with (directory / "eplusout.err").open("a") as stream:
                stream.write(range_text())
        return result

    def capture_read(*args, **kwargs):
        reads.append(args[3]["warning_review_pending"])
        if invalid_output:
            raise ValueError("Invalid output calendar fixture")
        return actual_read(*args, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "run", run_with_warning)
    monkeypatch.setattr(runner_module, "read_results", capture_read)
    directory = tmp_path / "simulation"
    runner = EnergyPlusRunner(energyplus)
    if enabled and not invalid_output:
        result = runner.run(building, directory, review_psychrometric_warnings=True)
        assert reads == [True]
        assert result.diagnostics["accepted"]
        assert result.diagnostics["disposition"] == "accepted_with_warnings"
        assert (directory / "result.json").exists()
    else:
        with pytest.raises(SimulationError):
            runner.run(building, directory, review_psychrometric_warnings=enabled)
        assert reads == ([True] if enabled else [])
        assert not (directory / "result.json").exists()
        if invalid_output:
            diagnostics = __import__("json").loads((directory / "diagnostics.json").read_text())
            assert not diagnostics["accepted"] and not diagnostics["warning_review_pending"]
            assert diagnostics["failure"] == "result_validation"
