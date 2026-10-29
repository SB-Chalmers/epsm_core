"""Delivered energy per carrier from simulation results, with hourly PV netting."""

from types import SimpleNamespace

import numpy as np
import pytest

from epsm_core import Building
from epsm_core.delivered import delivered_energy
from epsm_core.specs.physics import FVPSpec

HOURS = np.arange(8760)
DAY = (HOURS % 24 >= 8) & (HOURS % 24 < 17)


def result(building, **extra):
    hourly = {"space_heating_demand_kwh": np.full(8760, 4.0), "dhw_load_kwh": np.full(8760, 1.5),
              "space_heating_carrier_input_kwh": np.full(8760, 4.0),
              "ventilation_fan_electricity_kwh": np.full(8760, 0.4), **extra}
    return SimpleNamespace(hourly=hourly,
                           diagnostics={"building_snapshot_id": building.snapshot().sha256})


def test_declared_delivery_maps_demands_to_carriers():
    building = Building(preset="illustrative-reference")
    without_dhw = delivered_energy(result(building), building)
    assert without_dhw.annual_purchased == pytest.approx(
        {"district_heating": 4.0 * 8760, "electricity": 0.4 * 8760})
    assert without_dhw.boundary == "space_heating_and_fans"
    with_dhw = delivered_energy(result(building), building, dhw_carrier="electricity",
                                dhw_efficiency=2.5)
    assert with_dhw.annual_purchased["electricity"] == pytest.approx((0.4 + 1.5 / 2.5) * 8760)
    assert with_dhw.boundary == "space_heating_fans_and_dhw"


def test_pv_is_netted_hour_by_hour_and_surplus_exported():
    building = Building(preset="illustrative-reference")
    generation = np.where(DAY, 1.0, 0.0)
    delivered = delivered_energy(result(building, pv_generation_kwh=generation), building)
    self_used = np.minimum(generation, 0.4).sum()
    assert sum(delivered.pv_self_consumed) == pytest.approx(self_used)
    assert delivered.annual_purchased["electricity"] == pytest.approx(0.4 * 8760 - self_used)
    assert delivered.annual_exported["electricity"] == pytest.approx(generation.sum() - self_used)
    no_netting = delivered_energy(result(building, pv_generation_kwh=generation), building, pv=False)
    assert not no_netting.exported


def test_heat_pump_backup_needs_a_declared_carrier_and_states_must_match():
    building = Building(preset="illustrative-reference")
    building.hvac = building.hvac.with_changes(
        airflow=building.hvac.airflow.model_dump() | {
            "topology": "F", "sensible_recovery_effectiveness": 0.0},
        delivery=building.hvac.delivery.model_copy(update={
            "heating": None, "fvp": FVPSpec(cop=3, capacity_kw=10)}))
    run = result(building, fvp_electricity_kwh=np.full(8760, 1.0),
                 backup_input_kwh=np.full(8760, 0.5))
    with pytest.raises(ValueError, match="fvp_backup_carrier"):
        delivered_energy(run, building)
    delivered = delivered_energy(run, building, fvp_backup_carrier="district_heating")
    assert delivered.annual_purchased == pytest.approx(
        {"electricity": 8760.0, "district_heating": 4380.0})
    assert set(delivered.uses) == {"space_heating", "dhw"}
    with pytest.raises(ValueError, match="different building state"):
        delivered_energy(result(Building(preset="illustrative-reference")), building)
