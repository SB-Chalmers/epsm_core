"""Load-reference area is separate from physical floor area and inventory."""

import copy
import json

import pytest
from pydantic import ValidationError

from epsm_core import Building, BuildingSnapshot, EnergyPlusCompiler, Footprint, Weather


def area_scaled_airflow(building):
    return building.hvac.airflow.updated(
        envelope_infiltration_ach=0,
        envelope_infiltration_l_s_m2=0.2,
        mechanical_vent_l_s_m2=0.35,
    )


def test_reference_area_requires_one_explicit_choice_for_energy_only():
    building = Building()
    assert building.load_reference_area_m2 is None
    assert building.load_reference_area_policy is None
    assert building.effective_load_reference_area_m2 is None
    assert building.load_reference_area_basis == "missing"
    assert "load_reference_area_m2 or load_reference_area_policy" in building.readiness().missing
    assert "load_reference_area_m2 or load_reference_area_policy" not in \
        building.readiness("quantities").missing


def test_from_footprint_accepts_load_reference_inputs_explicitly():
    building = Building.from_footprint(
        Footprint.rectangle(8, 6), storeys=1, storey_height_m=3,
        load_reference_area_m2=900,
    )
    assert building.effective_load_reference_area_m2 == 900
    assert building.load_reference_area_basis == "explicit"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_explicit_reference_area_must_be_finite_and_positive(value):
    with pytest.raises((ValueError, ValidationError)):
        Building(load_reference_area_m2=value)
    building = Building()
    with pytest.raises((ValueError, ValidationError)):
        building.load_reference_area_m2 = value


def test_area_policy_and_numeric_area_are_mutually_exclusive_and_atomic():
    with pytest.raises(ValueError, match="[Cc]hoose either"):
        Building(preset="illustrative-reference", load_reference_area_m2=900,
                 load_reference_area_policy="conditioned_floor_area")

    explicit_policy = Building(preset="illustrative-reference",
                               load_reference_area_policy="conditioned_floor_area")
    with pytest.raises(ValueError, match="[Cc]lear the policy"):
        explicit_policy.load_reference_area_m2 = 900
    assert explicit_policy.load_reference_area_m2 is None
    assert explicit_policy.load_reference_area_policy == "conditioned_floor_area"

    explicit_area = Building(preset="illustrative-reference", load_reference_area_m2=900)
    with pytest.raises(ValueError, match="[Cc]lear the area"):
        explicit_area.load_reference_area_policy = "conditioned_floor_area"
    assert explicit_area.load_reference_area_m2 == 900
    assert explicit_area.load_reference_area_policy is None
    with pytest.raises((ValueError, ValidationError)):
        explicit_area.load_reference_area_policy = "footprint_area"


def test_preset_policy_can_be_overridden_by_explicit_area_without_stale_provenance():
    explicit = Building(preset="illustrative-reference", load_reference_area_m2=900)
    assert explicit.load_reference_area_policy is None
    assert not any(r.field_path == "load_reference_area_policy"
                   for r in explicit.provenance.records)

    building = Building(preset="illustrative-reference")
    assert building.load_reference_area_policy == "conditioned_floor_area"
    assert building.load_reference_area_basis == "policy"
    assert building.effective_load_reference_area_m2 == building.geometry.conditioned_floor_area_m2
    assert any(r.field_path == "load_reference_area_policy"
               and r.assumption_profile == "illustrative-reference@5"
               for r in building.provenance.records)

    building.load_reference_area_m2 = 1000
    assert building.load_reference_area_policy is None
    assert building.effective_load_reference_area_m2 == 1000
    assert building.load_reference_area_basis == "explicit"
    assert not any(r.field_path == "load_reference_area_policy"
                   for r in building.provenance.records)


def test_policy_tracks_geometry_and_explicit_area_survives_json_copy_and_renovation():
    from epsm_data import ConstructionOperation, RenovationMeasure
    from epsm_data.domain.enums import BuildingElement as Role

    policy = Building(preset="illustrative-reference")
    before = policy.effective_load_reference_area_m2
    part = policy.geometry.parts[0]
    policy.geometry = policy.geometry.updated(parts=(part.updated(
        storey_elevations_m=(0, 2.8, 5.6, 8.4, 11.2)),))
    assert policy.effective_load_reference_area_m2 > before
    assert policy.effective_load_reference_area_m2 == policy.geometry.conditioned_floor_area_m2

    building = Building(preset="illustrative-reference", load_reference_area_m2=1000)
    restored = BuildingSnapshot.from_dict(json.loads(json.dumps(building.to_dict()))).to_building()
    assert restored.effective_load_reference_area_m2 == 1000
    assert restored.load_reference_area_basis == "explicit"
    assert restored.copy().effective_load_reference_area_m2 == 1000
    target = next(e for e in restored.elements if e.role == Role.EXT_WALL)
    measure = RenovationMeasure(
        "reference-area-preservation", "envelope", "Like for like", "Test", "wall",
        operations=(ConstructionOperation("replace_element", Role.EXT_WALL,
                                          element=target.construction),),
        target_element_ids=(target.identifier,),
    )
    child = restored.renovate(measure)
    assert child.effective_load_reference_area_m2 == 1000
    assert child.snapshot().to_dict()["load_reference_area_m2"] == 1000


def test_reference_area_scales_loads_and_area_flows_not_physical_geometry(
        energyplus, synthetic_weather):
    weather = Weather.from_epw(synthetic_weather)
    baseline = Building(preset="illustrative-reference")
    baseline.hvac = baseline.hvac.with_changes(airflow=area_scaled_airflow(baseline))
    baseline.operation = baseline.operation.with_changes(lighting_gain_w_m2=0.6)
    baseline_area = baseline.effective_load_reference_area_m2
    explicit = baseline.copy()
    explicit.load_reference_area_m2 = baseline_area * 2

    compiler = EnergyPlusCompiler(energyplus)
    before_model, before = compiler.compile(baseline.to_spec(weather))
    after_model, after = compiler.compile(explicit.to_spec(weather))
    assert baseline.to_spec(weather).load_reference_area_m2 == baseline_area
    assert explicit.to_spec(weather).load_reference_area_m2 == baseline_area * 2

    for kind, field in (("People", "number_of_people"),
                        ("ElectricEquipment", "design_level"),
                        ("Lights", "lighting_level"),
                        ("WaterUse:Equipment", "peak_flow_rate"),
                        ("ZoneInfiltration:DesignFlowRate", "design_flow_rate"),
                        ("DesignSpecification:OutdoorAir", "outdoor_air_flow_per_zone")):
        before_total = sum(item[field] for item in before_model[kind].values())
        after_total = sum(item[field] for item in after_model[kind].values())
        assert after_total == pytest.approx(before_total * 2)

    assert after.data["conditioned_floor_area_m2"] == before.data["conditioned_floor_area_m2"]
    assert after.data["conditioned_volume_m3"] == before.data["conditioned_volume_m3"]
    assert {name: row["area_m2"] for name, row in after.data["surfaces"].items()} == {
        name: row["area_m2"] for name, row in before.data["surfaces"].items()
    }
    assert explicit.quantities().to_dict() == baseline.quantities().to_dict()

    volume_airflow = baseline.hvac.airflow.updated(
        envelope_infiltration_ach=0.2, envelope_infiltration_l_s_m2=None,
        mechanical_vent_l_s_m2=0,
    )
    volume_based = baseline.copy()
    volume_based.hvac = volume_based.hvac.with_changes(airflow=volume_airflow)
    doubled_volume_reference = volume_based.copy()
    doubled_volume_reference.load_reference_area_m2 = baseline_area * 2
    volume_model, volume_report = compiler.compile(volume_based.to_spec(weather))
    volume_area_model, volume_area_report = compiler.compile(
        doubled_volume_reference.to_spec(weather))
    def infiltration(model):
        return sorted(item["air_changes_per_hour"]
                      for item in model["ZoneInfiltration:DesignFlowRate"].values())
    assert infiltration(volume_area_model) == infiltration(volume_model)
    assert volume_area_report.data["conditioned_volume_m3"] == \
        volume_report.data["conditioned_volume_m3"]


def test_old_snapshot_stays_missing_until_edited():
    data = copy.deepcopy(Building(preset="illustrative-reference").to_dict())
    data["schema"] = "epsm.building/4"
    data.pop("load_reference_area_m2", None)
    data.pop("load_reference_area_policy", None)
    if data.get("operation") is not None:
        data["operation"].pop("gain_partitions", None)
    original = BuildingSnapshot.from_dict(data)
    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert restored.effective_load_reference_area_m2 is None
    assert restored.load_reference_area_basis == "missing"
    assert "load_reference_area_m2 or load_reference_area_policy" in restored.readiness().missing
    restored.identifier = "edited"
    saved = restored.snapshot().to_dict()
    assert saved["schema"] == "epsm.building/8"
    assert saved["load_reference_area_m2"] is None
    assert saved["load_reference_area_policy"] is None
