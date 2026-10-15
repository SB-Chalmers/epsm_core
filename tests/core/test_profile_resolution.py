"""Portable source/custom definitions resolve without a catalogue or hidden I/O."""

import hashlib
import json
from datetime import date, timedelta

import pytest
from epsm_data import OperatingProfile, load_operating_profile, select_operating_profile

from epsm_core import OperationProfile, ResolvedOperatingProfile, resolve_operating_profile


def project_calendar(year, count):
    dates = []
    current = date(year, 1, 1)
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return {"calendar_year": year, "active_dates": dates, "calendar_source": "test:calendar"}


# Captured before the ownership refactor using Core's existing source factories.
# These cover every resolved schedule and physical input in each complete mapping.
BASELINES = {
    ("multi_family", 2023): "e82504013d129929f1232530e3864a1214e48aaaac54ac0c9e87360c575cd855",
    ("multi_family", 2024): "35f692738866901dba0ce36b7e8f3346e6843f9916d1d296e93d0084a1890ff4",
    ("office", 2023): "b9369ce7defc5700babf8565329e40b1f02130c748294b846d22f70f75c93d18",
    ("office", 2024): "ae27f850a4267d14b30284331cd15c0a849302b6fa2f3482c9cd1580a6c48c32",
    ("school", 2023): "bbcc3853dbd488be8456cbf65c2627460f7b7b698d4eb09f386ae9a7cbe12a85",
    ("school", 2024): "03541b937606b7d11666527c14c418b4c14d1a4c45ef457a31b15148baa2779a",
}


@pytest.mark.parametrize("building_type, year", BASELINES)
def test_standard_resolution_preserves_all_pre_refactor_inputs(building_type, year):
    count = {"office": 225, "school": 220}.get(building_type)
    calendar = project_calendar(year, count) if count else {"calendar_year": year}
    resolved = resolve_operating_profile(select_operating_profile(building_type), calendar=calendar)
    assert isinstance(resolved, ResolvedOperatingProfile)
    assert isinstance(resolved.operation, OperationProfile)
    payload = json.dumps(resolved.to_dict()["assumptions"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(payload.encode()).hexdigest() == BASELINES[building_type, year]
    assert "load_reference_area_m2" in resolved.requirements
    assert "calendar" not in resolved.requirements


@pytest.mark.parametrize("building_type", ["office", "school"])
def test_missing_project_calendar_is_explicit_without_invented_operation(building_type):
    resolved = resolve_operating_profile(select_operating_profile(building_type))
    assert resolved.operation is None
    assert "calendar" in resolved.requirements
    assert "use" not in resolved.assumptions


@pytest.mark.parametrize("calendar", [
    {}, {"calendar_year": 2024}, {"calendar_year": 2024, "active_dates": []},
    project_calendar(2024, 224),
    {"calendar_year": 2024, "active_dates": ["2023-01-02"], "calendar_source": "project"},
    {**project_calendar(2024, 225), "normal_use": "false"},
])
def test_supplied_invalid_office_calendar_raises(calendar):
    with pytest.raises(ValueError):
        resolve_operating_profile(select_operating_profile("office"), calendar=calendar)


def test_custom_profile_uses_same_physical_operation_and_retains_sources():
    profile = OperatingProfile("project:library", {"building_assumptions": {"use": {
        "heating_setpoint": {"values": [19] * 24}, "occupant_density_per_m2": 0.02,
        "equipment_gain_w_m2": 3, "dhw_kwh_m2_year": 7,
    }, "airflow": {"mechanical_vent_l_s_m2": 0.8}}}, ("project:survey",))
    resolved = resolve_operating_profile(profile)
    assert isinstance(resolved.operation, OperationProfile)
    assert resolved.operation.equipment_gain_w_m2 == 3
    assert resolved.profile_id == profile.profile_id
    assert resolved.source_references == ("project:survey",)
    assert "airflow.topology" in resolved.requirements
    assert "airflow.envelope_infiltration_ach" in resolved.requirements
    with pytest.raises(TypeError):
        resolved.assumptions["use"]["equipment_gain_w_m2"] = 9
    exported = resolved.to_dict()
    exported["assumptions"]["use"]["equipment_gain_w_m2"] = 9
    assert resolved.operation.equipment_gain_w_m2 == 3


def test_custom_partial_profile_exposes_missing_use_fields():
    resolved = resolve_operating_profile(OperatingProfile("partial", {
        "building_assumptions": {"use": {"equipment_gain_w_m2": 2}},
    }))
    assert resolved.operation is None
    assert "use.heating_setpoint" in resolved.requirements
    assert resolved.assumptions["use"]["equipment_gain_w_m2"] == 2


def test_custom_overlay_sources_only_authored_fields_and_preserves_prior_temperature():
    previous = resolve_operating_profile(select_operating_profile("multi_family")).operation
    profile = OperatingProfile("project:equipment", {"building_assumptions": {
        "use": {"equipment_gain_w_m2": 9},
    }}, source_references=("project:equipment-survey",))
    resolved = resolve_operating_profile(profile, previous=previous)
    assert resolved.operation.heating_setpoint == previous.heating_setpoint
    assert resolved.operation.equipment_gain_w_m2 == 9
    assert tuple(record.field_path for record in resolved.source_records) == ("use.equipment_gain_w_m2",)


@pytest.mark.parametrize("assumptions", [
    {"use": {"equipment_gain_w_m2": -1}},
    {"airflow": {"mechanical_vent_l_s_m2": -1}},
    {"facade": {"solar_shading_factor": 1.5}},
    {"use": {"unknown_field": 2}},
    {"unknown_section": {}},
    {"use": {"heating_setpoint": {"values": [22] * 24},
              "cooling_setpoint": {"values": [20] * 24}}},
    {"use": {"occupancy_fraction": {"values": [1.5] * 24}}},
    {"use": {"dhw_kwh_m2_year": 10, "dhw_fraction": {"values": [0] * 24}}},
    {"airflow": {"envelope_infiltration_ach": 0.2, "envelope_infiltration_l_s_m2": 0.1}},
    {"airflow": {"mechanical_vent_fraction": {"values": [1.5] * 24}}},
    {"facade": {"default_wwr": 0.99}},
])
def test_invalid_custom_inputs_raise_even_when_other_fields_are_missing(assumptions):
    with pytest.raises(ValueError):
        resolve_operating_profile(OperatingProfile("invalid", {"building_assumptions": assumptions}))


@pytest.mark.parametrize("name", ["sveby_residential_v2", "sveby_office_v1", "sveby_school_v1", "generic_other"])
def test_portable_conversion_and_representation_have_no_resource_reads(name, monkeypatch):
    profile = load_operating_profile(name)
    import epsm_data.profiles

    def denied(*args, **kwargs):
        pytest.fail("Conversion of loaded values must not read package resources")

    monkeypatch.setattr(epsm_data.profiles, "files", denied)
    resolved = resolve_operating_profile(profile)
    assert len(repr(resolved)) <= 160
    assert "\n" not in repr(resolved)
    assert resolved.source_references == profile.source_references
    assert resolved.notes == profile.notes


@pytest.mark.parametrize("options", [
    {"standby_fraction": -1}, {"cooling_enabled": "unknown"},
    {"zone_role": "unknown"}, {"unknown": 1},
])
def test_invalid_supplied_options_raise_even_without_a_project_calendar(options):
    with pytest.raises(ValueError):
        resolve_operating_profile(select_operating_profile("office"), **options)


def test_ben_definition_does_not_replace_sveby_operation_implicitly():
    from epsm_data import select_dhw_profile

    from epsm_core import load_dhw_profile

    ben = select_dhw_profile("multi_family", purpose="epc_normal_use")
    partial = resolve_operating_profile(ben)
    assert partial.operation is None
    assert partial.assumptions["use"] == {"dhw_kwh_m2_year": 25}
    resolved = resolve_operating_profile(select_operating_profile("multi_family"))
    assert resolved.operation.dhw_kwh_m2_year == 21
    assert load_dhw_profile("multi_family", purpose="epc_normal_use").apply_to(
        resolved.operation).dhw_kwh_m2_year == 25
    overlay = resolve_operating_profile(ben, previous=resolved.operation)
    assert overlay.operation == resolved.operation.with_changes(dhw_kwh_m2_year=25)
    assert overlay.source_records == (load_dhw_profile("multi_family", purpose="epc_normal_use").source_record(),)
