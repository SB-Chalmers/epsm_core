"""Carrier accounting checks independent of EnergyPlus (engineering conservation)."""

from types import SimpleNamespace

import numpy as np
import pytest

from epsm_core import AirflowSpec, DeliverySpec, HeatingDeliverySpec, ScheduleSpec
from epsm_core.heating_delivery import heating_delivery, heating_delivery_for_domain


def test_heat_and_net_loss_conservation_with_separate_scheduled_fans(building):
    spec = building.updated(
        load_reference_area_m2=1000,
        delivery=DeliverySpec(
            heating=HeatingDeliverySpec(
                carrier="district_heat",
                efficiency=0.9,
                net_distribution_loss_kwh_m2_year=5,
                specific_fan_power_w_per_l_s=2,
                source="synthetic conservation check",
            )
        ),
    )
    hours = spec.climate.hours_in_year
    airflow = spec.airflow.updated(
        mechanical_vent_l_s_m2=1,
        mechanical_vent_fraction=ScheduleSpec(values=(1,) * 12 + (0,) * 12),
    )
    report = SimpleNamespace(
        data={
            "zones": {
                "test": {
                    "conditioned": True,
                    "load_reference_area_m2": 1000,
                    "airflow_input": airflow.model_dump(mode="json"),
                }
            }
        }
    )
    result = heating_delivery(spec, np.full(hours, 10.0), report)
    assert result["net_distribution_loss_kwh"].sum() == pytest.approx(5000)
    assert result["space_heating_carrier_input_kwh"].sum() == pytest.approx(
        (10 * hours + 5000) / 0.9
    )
    assert result["ventilation_fan_electricity_kwh"].sum() == pytest.approx(hours / 2 * 2)


def test_explicit_heat_pump_and_invalid_delivery_inputs(building):
    with pytest.raises(ValueError):
        HeatingDeliverySpec(carrier="heat_pump", source="test")
    model = HeatingDeliverySpec(
        carrier="heat_pump", heat_pump_cop=ScheduleSpec.constant(3), source="test"
    )
    spec = building.updated(delivery=DeliverySpec(heating=model))
    result = heating_delivery(spec, np.ones(spec.climate.hours_in_year), SimpleNamespace(data={}))
    assert result["space_heating_carrier_input_kwh"].sum() == pytest.approx(
        spec.climate.hours_in_year / 3
    )
    with pytest.raises(ValueError, match="nonnegative"):
        heating_delivery(spec, -np.ones(spec.climate.hours_in_year), SimpleNamespace(data={}))
    with pytest.raises(ValueError, match="active"):
        spec = building.updated(
            delivery=DeliverySpec(
                heating=HeatingDeliverySpec(
                    carrier="district_heat",
                    net_distribution_loss_kwh_m2_year=1,
                    loss_fraction=ScheduleSpec.constant(0),
                    source="test",
                )
            )
        )
        heating_delivery(spec, np.ones(spec.climate.hours_in_year), SimpleNamespace(data={}))


def test_domain_delivery_preserves_accounting_without_revalidating_airflow(building, monkeypatch):
    spec = building.updated(delivery=DeliverySpec(heating=HeatingDeliverySpec(
        carrier="heat_pump", efficiency=.9, heat_pump_cop=ScheduleSpec.constant(3),
        net_distribution_loss_kwh_m2_year=5, specific_fan_power_w_per_l_s=2,
        source="explicit domain conservation check")))
    airflow = spec.airflow.updated(mechanical_vent_fraction=ScheduleSpec(values=(0, 1) * 12))
    demand = np.full(spec.climate.hours_in_year, 10.)
    report = SimpleNamespace(data={"load_reference_area_m2": 100., "zones": {"domain": {
        "conditioned": True, "load_reference_area_m2": 100.,
        "airflow_input": airflow.model_dump(mode="json")}}})
    expected = heating_delivery(spec, demand, report)

    def forbidden(*args, **kwargs):
        pytest.fail("An already validated domain airflow must not be reconstructed")

    monkeypatch.setattr(AirflowSpec, "model_validate", forbidden)
    actual = heating_delivery_for_domain(spec, demand, reference_area_m2=100., airflow=airflow)
    for name in expected:
        np.testing.assert_array_equal(actual[name], expected[name])
    assert actual["net_distribution_loss_kwh"].sum() == pytest.approx(500)
    with pytest.raises(ValueError, match="finite and positive"):
        heating_delivery_for_domain(spec, demand, reference_area_m2=float("nan"), airflow=airflow)
    with pytest.raises(TypeError, match="AirflowSpec"):
        heating_delivery_for_domain(spec, demand, reference_area_m2=100., airflow={})
