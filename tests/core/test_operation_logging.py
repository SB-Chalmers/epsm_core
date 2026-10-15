# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Public operation logging keeps calculation inputs and host configuration separate."""

import inspect
import logging

from epsm_core.preparation import prepare_geometry


def test_public_operation_accepts_explicit_context():
    parameter = inspect.signature(prepare_geometry).parameters["log_context"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


def test_import_does_not_install_output_handlers():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import epsm_core; import logging; assert not any(isinstance(h, logging.StreamHandler) for h in logging.getLogger('epsm_core').handlers)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr


def test_rejected_operation_keeps_context_and_reports_failure(caplog):
    import pytest

    with caplog.at_level(logging.DEBUG):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            prepare_geometry(
                None, log_context={"study_id": "logging-test", "operation_id": "parent"}
            )
    records = [record for record in caplog.records if hasattr(record, "epsm_event")]
    assert records[0].epsm_event.endswith(".started")
    assert records[-1].epsm_event.endswith(".failed")
    assert records[0].epsm_context["parent_operation_id"] == "parent"
    assert records[-1].epsm_context["study_id"] == "logging-test"
    assert records[-1].epsm_details["duration_s"] >= 0
    assert not any(record.exc_info for record in records)


def test_district_identity_preparation_inherits_thread_context(monkeypatch, caplog, tmp_path):
    from types import SimpleNamespace

    import epsm_core.district as district
    from epsm_core._logging import current_context

    observed = []

    def identity(building):
        observed.append(current_context().get("study_id"))
        return building.identifier

    class Runner:
        compiler = SimpleNamespace(run_id=identity)

        def __init__(self, *args):
            pass

        def run(self, building, directory):
            return building.identifier

    monkeypatch.setattr(district, "EnergyPlusRunner", Runner)
    monkeypatch.setattr(
        district.DistrictPlan,
        "resolved_buildings",
        lambda self: (SimpleNamespace(identifier="first"), SimpleNamespace(identifier="second")),
    )
    plan = district.DistrictPlan(buildings=())
    with caplog.at_level(logging.DEBUG):
        result = plan.run(tmp_path, workers=2, log_context={"study_id": "district-test"})
    assert result == {"first": "first", "second": "second"}
    assert observed == ["district-test", "district-test"]
