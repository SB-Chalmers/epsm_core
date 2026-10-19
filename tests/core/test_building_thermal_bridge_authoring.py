"""Thermal-bridge uplift remains an explicit, nonphysical authoring choice."""

import copy
import json

import pytest
from pydantic import ValidationError

from epsm_core import Building, BuildingSnapshot, EnergyPlusCompiler, Footprint, Weather


def test_thermal_bridge_is_optional_energy_input_but_not_quantity_input():
    building = Building()
    assert building.thermal_bridge_uplift_fraction is None
    assert "thermal_bridge_uplift_fraction" in building.readiness().missing
    assert "thermal_bridge_uplift_fraction" not in building.readiness("quantities").missing


def test_from_footprint_accepts_thermal_bridge_as_building_input():
    building = Building.from_footprint(
        Footprint.rectangle(8, 6), storeys=1, storey_height_m=3,
        thermal_bridge_uplift_fraction=0.15,
    )
    assert building.thermal_bridge_uplift_fraction == 0.15
    assert building.snapshot().to_dict()["thermal_bridge_uplift_fraction"] == 0.15


@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf"), float("-inf")])
def test_thermal_bridge_requires_finite_nonnegative_value(value):
    with pytest.raises((ValueError, ValidationError)):
        Building(thermal_bridge_uplift_fraction=value)
    building = Building()
    with pytest.raises((ValueError, ValidationError)):
        building.thermal_bridge_uplift_fraction = value


def test_thermal_bridge_reaches_compiler_without_changing_material_physics(
        energyplus, synthetic_weather):
    building = Building(preset="illustrative-reference")
    baseline_inventory = building.quantities().to_dict()
    baseline_spec = building.to_spec(Weather.from_epw(synthetic_weather))
    baseline_model, baseline_report = EnergyPlusCompiler(energyplus).compile(baseline_spec)

    building.thermal_bridge_uplift_fraction = 0.12
    assert building.to_spec(Weather.from_epw(synthetic_weather)).envelope.thermal_bridge_uplift_fraction == 0.12
    assert building.quantities().to_dict() == baseline_inventory
    uplifted_model, uplifted_report = EnergyPlusCompiler(energyplus).compile(
        building.to_spec(Weather.from_epw(synthetic_weather)))

    before = baseline_report.data["constructions"]["wall"]
    after = uplifted_report.data["constructions"]["wall"]
    assert after["nominal_u_w_m2k"] == pytest.approx(before["nominal_u_w_m2k"])
    assert after["applied_u_w_m2k"] == pytest.approx(after["nominal_u_w_m2k"] * 1.12)
    nominal = before["nominal"]["layers"]
    applied = after["applied"]["layers"]
    assert len(nominal) == len(applied)
    for original, equivalent in zip(nominal, applied):
        assert equivalent["thickness_m"] == original["thickness_m"]
        assert equivalent["material"]["density_kg_m3"] == original["material"]["density_kg_m3"]
        assert equivalent["material"]["specific_heat_j_kgk"] == original["material"]["specific_heat_j_kgk"]
    capacity_before = sum(
        layer["thickness_m"] * layer["material"]["density_kg_m3"]
        * layer["material"]["specific_heat_j_kgk"] for layer in nominal)
    capacity_after = sum(
        layer["thickness_m"] * layer["material"]["density_kg_m3"]
        * layer["material"]["specific_heat_j_kgk"] for layer in applied)
    assert capacity_after == pytest.approx(capacity_before)
    assert uplifted_model["Material"] != baseline_model["Material"]


def test_thermal_bridge_survives_snapshot_copy_and_renovation():
    from epsm_data import ConstructionOperation, RenovationMeasure
    from epsm_data.domain.enums import BuildingElement as Role

    building = Building(preset="illustrative-reference", thermal_bridge_uplift_fraction=0.08)
    encoded = json.loads(json.dumps(building.snapshot().to_dict()))
    restored = BuildingSnapshot.from_dict(encoded).to_building()
    assert restored.thermal_bridge_uplift_fraction == 0.08
    assert restored.copy().thermal_bridge_uplift_fraction == 0.08

    target = next(e for e in restored.elements if e.role == Role.EXT_WALL)
    measure = RenovationMeasure(
        "thermal-bridge-preservation", "envelope", "Like for like", "Test", "wall",
        operations=(ConstructionOperation("replace_element", Role.EXT_WALL,
                                          element=target.construction),),
        target_element_ids=(target.identifier,),
    )
    child = restored.renovate(measure)
    assert child.thermal_bridge_uplift_fraction == 0.08
    assert child.snapshot().to_dict()["thermal_bridge_uplift_fraction"] == 0.08


def test_older_snapshot_with_no_thermal_bridge_stays_missing():
    data = copy.deepcopy(Building(preset="illustrative-reference").to_dict())
    data["schema"] = "epsm.building/3"
    data.pop("thermal_bridge_uplift_fraction", None)
    data.pop("load_reference_area_m2", None)
    data.pop("load_reference_area_policy", None)
    if data.get("operation") is not None:
        data["operation"].pop("gain_partitions", None)
    original = BuildingSnapshot.from_dict(data)

    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert restored.thermal_bridge_uplift_fraction is None
    assert "thermal_bridge_uplift_fraction" in restored.readiness().missing
    assert "thermal_bridge_uplift_fraction" not in restored.readiness("quantities").missing
    restored.identifier = "edited"
    edited = restored.snapshot().to_dict()
    assert edited["schema"] == "epsm.building/8"
    assert edited["thermal_bridge_uplift_fraction"] is None


def test_explicit_zero_is_not_classified_as_a_preset_assumption():
    building = Building(preset="illustrative-reference", thermal_bridge_uplift_fraction=0.0)
    assert building.thermal_bridge_uplift_fraction == 0.0
    assert not any(r.field_path == "thermal_bridge_uplift_fraction"
                   for r in building.provenance.records)


def test_explicit_null_legacy_state_retains_identity():
    data = Building(preset="illustrative-reference").to_dict()
    data["schema"] = "epsm.building/3"
    data["thermal_bridge_uplift_fraction"] = None
    if data.get("operation") is not None:
        data["operation"].pop("gain_partitions", None)
    original = BuildingSnapshot.from_dict(data)
    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert "thermal_bridge_uplift_fraction" in restored.readiness().missing
