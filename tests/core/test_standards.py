from profile_inputs import residential_converter

from epsm_core import BuildingBuilder


def test_bundled_sveby_profile_matches_reviewed_values():
    standard = residential_converter()
    assert residential_converter().profile_id == standard.profile_id
    assert standard.source_uri.startswith("https://www.sveby.org/")
    assert standard.completion_default_fields == (
        "cooling_enabled",
        "occupant_density_per_m2",
    )
    assert "monthly_dhw_profile" in standard.unsupported_fields
    assert "window_airing_postprocessing" in standard.unsupported_fields
    assert len(standard.data["use"]["dhw_monthly_kwh_m2"]) == 12
    assert len(
        standard.data["use"][
            "household_electricity_internal_gain_monthly_kwh_m2"
        ]
    ) == 12
    assert (
        standard.data["conditional_system_defaults"][
            "electric_towel_radiator_kwh_per_unit_year"
        ]
        == 500
    )

    use = standard.use_spec()
    assert set(use.heating_setpoint.values) == {21}
    assert set(use.cooling_setpoint.values) == {25}
    assert sum(use.occupancy_fraction.values) == 14
    assert use.occupant_activity_w == 80
    assert use.equipment_gain_w_m2 == 1.68
    assert use.dhw_kwh_m2_year == 21


def test_explicit_residential_builder_supplies_sveby_operational_defaults(building):
    known = building.model_dump(mode="json")
    known.pop("provenance")
    known.pop("use")
    known.pop("common_use")
    known["facade"].pop("solar_shading_factor")
    known["airflow"].pop("mechanical_vent_l_s_m2")

    resolved = BuildingBuilder(building_use="residential").build(**known)

    assert resolved.use.occupancy_category == "residential"
    assert resolved.use.occupant_activity_w == 80
    assert resolved.use.dhw_kwh_m2_year == 21
    assert resolved.common_use.heating_setpoint.values == (18.0,) * 24
    assert resolved.facade.solar_shading_factor == 0.5
    assert resolved.airflow.mechanical_vent_l_s_m2 == 0.35
    assumed = {record.field_path: record for record in resolved.provenance.records}
    assert assumed["use.heating_setpoint.values"].assumption_profile.startswith(
        "sveby.residential.v2.0"
    )


def test_explicit_residential_builder_merges_sveby_with_typed_physical_inputs(building):
    resolved = BuildingBuilder(building_use="residential").build(
        identifier="typed-inputs",
        geometry=building.geometry,
        climate=building.climate,
        envelope=building.envelope,
        facade=building.facade,
        airflow=building.airflow,
    )

    assert resolved.facade.solar_shading_factor == 0.5
    assert resolved.use.occupant_activity_w == 80


def test_explicit_builder_profile_remains_supported(building):
    assumptions = building.model_dump(mode="json")
    assumptions.pop("provenance")
    resolved = BuildingBuilder(
        assumption_profile="caller-owned", assumptions=assumptions
    ).build(identifier="explicit")
    assert resolved.identifier == "explicit"
    assert resolved.provenance.records[0].assumption_profile == "caller-owned"
