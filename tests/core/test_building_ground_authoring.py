"""Ground-boundary inputs stay explicit in gradual Building authoring."""

import copy
import json

from epsm_core import (
    Building,
    BuildingSnapshot,
    ConstructionSpec,
    EnergyPlusCompiler,
    Footprint,
    FoundationSpec,
    GroundTemperatureSpec,
    LayerSpec,
    MaterialSpec,
    Weather,
)


def kiva_inputs(**changes):
    return FoundationSpec(
        method="kiva",
        source="study-ground-survey-v1",
        soil_conductivity_w_mk=1.6,
        soil_density_kg_m3=1800,
        soil_specific_heat_j_kgk=900,
        exposed_perimeter_fraction=0.75,
        wall_height_above_grade_m=0.2,
        wall_depth_below_slab_m=0.1,
        deep_ground_boundary="GroundWater",
        deep_ground_depth_m=30,
        far_field_width_m=25,
        **changes,
    )


def test_ground_inputs_are_optional_and_gate_energy_readiness():
    building = Building()
    assert building.foundation is None
    assert building.ground_temperature is None
    assert "foundation" in building.readiness().missing

    building.foundation = FoundationSpec(method="kiva", source="study-ground-survey-v1")
    missing = building.readiness().missing
    assert "foundation.soil_conductivity_w_mk" in missing
    assert "foundation.deep_ground_depth_m" in missing
    restored = Building.from_snapshot(building.snapshot())
    assert restored.foundation.model_fields_set == {"method", "source"}
    assert restored.snapshot().to_dict()["foundation"] == {
        "method": "kiva", "source": "study-ground-survey-v1"
    }
    try:
        restored.to_spec(None)
    except ValueError as error:
        assert "not ready" in str(error)
    else:
        raise AssertionError("Incomplete ground configuration reached the adapter")


def test_complete_kiva_inputs_roundtrip_without_injected_defaults():
    building = Building(preset="illustrative-reference")
    config = kiva_inputs()
    building.foundation = config

    encoded = building.snapshot().to_dict()
    assert encoded["schema"] == "epsm.building/3"
    assert encoded["foundation"] == config.model_dump(mode="json", exclude_unset=True)
    restored = Building.from_snapshot(building.snapshot())
    assert restored.foundation.model_fields_set == config.model_fields_set
    json_snapshot = BuildingSnapshot.from_dict(json.loads(json.dumps(restored.to_dict())))
    assert json_snapshot.sha256 == restored.snapshot().sha256


def test_ground_temperature_requires_method_and_all_explicit_fields():
    building = Building(preset="illustrative-reference")
    building.foundation = FoundationSpec(method="prescribed_temperature")
    building.ground_temperature = GroundTemperatureSpec(source="measured-monthly-v1")
    assert "ground_temperature.monthly_temperatures_c" in building.readiness().missing


def test_adapter_and_compiler_keep_authored_kiva_configuration(energyplus, synthetic_weather):
    building = Building(preset="illustrative-reference")
    config = kiva_inputs()
    building.foundation = config
    spec = building.to_spec(Weather.from_epw(synthetic_weather))

    assert spec.envelope.foundation.method == config.method
    assert spec.envelope.foundation.source == config.source
    for field in config.model_fields_set:
        assert getattr(spec.envelope.foundation, field) == getattr(config, field)
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert all(report.data["foundation"]["inputs"][field] == getattr(config, field)
               for field in config.model_fields_set)


def test_prescribed_ground_profile_roundtrips_through_adapter_and_compiler(
        energyplus, synthetic_weather):
    building = Building(preset="illustrative-reference")
    method = FoundationSpec(method="prescribed_temperature")
    temperatures = GroundTemperatureSpec(
        monthly_temperatures_c=tuple(float(month) for month in range(1, 13)),
        source="site-monitoring-monthly-v1",
    )
    building.foundation = method
    building.ground_temperature = temperatures

    restored = Building.from_snapshot(building.snapshot())
    json_restored = BuildingSnapshot.from_dict(json.loads(json.dumps(restored.to_dict()))).to_building()
    assert json_restored.snapshot().sha256 == restored.snapshot().sha256
    assert restored.foundation.model_fields_set == {"method"}
    assert restored.ground_temperature.model_fields_set == {
        "monthly_temperatures_c", "source"
    }
    spec = restored.to_spec(Weather.from_epw(synthetic_weather))
    assert spec.envelope.foundation.method == "prescribed_temperature"
    assert spec.envelope.ground_temperature == temperatures
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert model["Site:GroundTemperature:BuildingSurface"]["ground_temperature"] == {
        f"{month}_ground_temperature": float(index)
        for index, month in enumerate((
            "january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december",
        ), start=1)
    }
    assert report.data["foundation"]["method"] == "prescribed_temperature"


def test_footing_material_requires_authored_depth_and_width():
    building = Building(preset="illustrative-reference")
    material = MaterialSpec(name="concrete", conductivity_w_mk=1.7,
                            density_kg_m3=2300, specific_heat_j_kgk=880)
    building.foundation = kiva_inputs(footing_material=material)
    assert "foundation.footing_depth_m" in building.readiness().missing
    assert "foundation.footing_width_m" in building.readiness().missing

    building.foundation = kiva_inputs(
        footing_material=material, footing_depth_m=0.4, footing_width_m=0.45)
    assert "foundation.footing_depth_m" not in building.readiness().missing
    assert "foundation.footing_width_m" not in building.readiness().missing


def test_prescribed_temperature_rejects_kiva_footing_wall():
    building = Building(preset="illustrative-reference")
    material = MaterialSpec(name="concrete", conductivity_w_mk=1.7,
                            density_kg_m3=2300, specific_heat_j_kgk=880)
    footing_wall = ConstructionSpec(
        layers=(LayerSpec(material=material, thickness_m=0.2),))
    building.foundation = FoundationSpec(
        method="prescribed_temperature", footing_wall=footing_wall)
    building.ground_temperature = GroundTemperatureSpec(
        monthly_temperatures_c=(10.0,) * 12, source="site-monitoring-monthly-v1")

    readiness = building.readiness()
    assert not readiness.ready
    assert "prescribed_temperature cannot include Kiva parameters" in readiness.missing
    try:
        building.to_spec(None)
    except ValueError as error:
        assert "not ready" in str(error)
    else:
        raise AssertionError("Conflicting footing wall reached the adapter")


def test_from_footprint_accepts_ground_inputs_as_building_options():
    config = kiva_inputs()
    building = Building.from_footprint(
        Footprint.rectangle(8, 6), storeys=1, storey_height_m=3,
        foundation=config,
    )
    assert building.foundation == config
    assert building.snapshot().to_dict()["foundation"] == config.model_dump(
        mode="json", exclude_unset=True)


def test_named_reference_supplies_versioned_ground_defaults():
    building = Building(preset="illustrative-reference")
    assert building.preset_revision == "2"
    assert building.foundation is not None
    assert building.foundation.model_fields_set >= {
        "method", "source", "soil_conductivity_w_mk", "soil_density_kg_m3",
        "soil_specific_heat_j_kgk", "wall_height_above_grade_m",
        "wall_depth_below_slab_m", "exposed_perimeter_fraction",
        "deep_ground_boundary", "deep_ground_depth_m", "far_field_width_m",
    }
    assert any(r.source == "illustrative-reference@2"
               for r in building.provenance.records if r.field_path == "foundation")


def test_older_snapshots_keep_missing_ground_state_and_origin_identity():
    source = Building(preset="illustrative-reference")
    data = copy.deepcopy(source.to_dict())
    data["schema"] = "epsm.building/2"
    data.pop("foundation", None)
    data.pop("ground_temperature", None)
    original = BuildingSnapshot.from_dict(data)

    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert restored.foundation is None
    assert restored.ground_temperature is None
    restored.identifier = "edited"
    assert restored.snapshot().to_dict()["foundation"] is None
