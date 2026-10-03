"""Native airflow controls, EnergyPlus 24.2 DesignFlowRate contract (2026-10-03)."""

import pytest

from epsm_core import ScheduleSpec
from epsm_core.compiler import EnergyPlusCompiler


def test_weather_response_and_independent_airflow_schedules(building, energyplus):
    airflow = building.airflow.updated(
        infiltration_fraction=ScheduleSpec.constant(.5),
        infiltration_coefficients=(.2, .01, .1, 0),
        infiltration_source="declared reference-flow response scenario",
    )
    model, report = EnergyPlusCompiler(energyplus).compile(building.updated(airflow=airflow))
    objects = model["ZoneInfiltration:DesignFlowRate"]
    assert objects
    assert all(o["schedule_name"] == "infiltration_fraction" for o in objects.values())
    assert all(o["temperature_term_coefficient"] == .01 for o in objects.values())
    assert all(o["velocity_term_coefficient"] == .1 for o in objects.values())
    assert report.data["zones"]
    assert "infiltration_fraction" in model["Schedule:Compact"]


def test_default_response_and_missing_source_are_explicit(building):
    assert building.airflow.infiltration_coefficients == (1, 0, 0, 0)
    with pytest.raises(ValueError, match="source"):
        building.airflow.updated(infiltration_coefficients=(.5, 0, .1, 0))
    with pytest.raises(ValueError, match="infiltration_fraction"):
        building.airflow.updated(infiltration_fraction=ScheduleSpec.constant(1.1))
    with pytest.raises(ValueError):
        building.airflow.updated(infiltration_coefficients=(-1, 0, 0, 0))


def test_natural_exchange_fraction_is_separate(building, energyplus):
    airflow = building.airflow.updated(topology="S", mechanical_vent_l_s_m2=0,
        sensible_recovery_effectiveness=0, natural_exchange_ach=.3,
        natural_exchange_fraction=ScheduleSpec.constant(.25))
    model, _ = EnergyPlusCompiler(energyplus).compile(building.updated(airflow=airflow))
    assert all(o["schedule_name"] == "natural_exchange_fraction"
               for o in model["ZoneVentilation:DesignFlowRate"].values())
