"""Typed EPC assumptions and thermal DHW conservation at the compiler boundary."""

from datetime import date, timedelta

import pytest

from epsm_core import (
    DHWProfileSpec,
    EnergyPlusCompiler,
    ProgramBlend,
    ProgramComponent,
    ScheduleSpec,
    SourceRecord,
    load_dhw_profile,
    load_sveby_school_v1,
    load_sveby_spec,
)


@pytest.mark.parametrize(
    ("building_type", "expected"),
    [("single_family", 20), ("multi_family", 25), ("office", 2), ("school", 2),
     ("non_residential", 2)],
)
def test_public_typed_epc_profiles(building_type, expected):
    profile = load_dhw_profile(building_type, purpose="epc_normal_use")
    assert isinstance(profile, DHWProfileSpec)
    assert profile.building_type == building_type
    assert profile.purpose == "epc_normal_use"
    assert profile.version == "1"
    assert profile.area_basis == "Atemp"
    assert profile.dhw_kwh_m2_year == expected
    assert DHWProfileSpec.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize(
    ("building_type", "purpose", "version"),
    [("residential", "epc_normal_use", "1"), ("unknown", "epc_normal_use", "1"),
     ("single_family", "operational", "1"), ("single_family", "epc_normal_use", "2")],
)
def test_unknown_profile_selection_is_rejected(building_type, purpose, version):
    with pytest.raises(ValueError):
        load_dhw_profile(building_type, purpose=purpose, version=version)


def test_profile_selection_requires_explicit_purpose():
    with pytest.raises(TypeError):
        load_dhw_profile("single_family")


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf")])
def test_profile_rejects_invalid_annual_demand(invalid):
    profile = load_dhw_profile("single_family", purpose="epc_normal_use")
    with pytest.raises(ValueError):
        profile.updated(dhw_kwh_m2_year=invalid)


def test_profile_is_frozen():
    profile = load_dhw_profile("single_family", purpose="epc_normal_use")
    with pytest.raises(ValueError):
        profile.dhw_kwh_m2_year = 25


def test_epc_profiles_preserve_published_operational_defaults():
    assert load_sveby_spec().use_spec().dhw_kwh_m2_year == 21
    assert load_sveby_school_v1().data["use"]["dhw_kwh_m2_year"] == 10
    assert load_dhw_profile("school", purpose="epc_normal_use").dhw_kwh_m2_year == 2


def test_profile_application_preserves_schedules_and_other_use_inputs():
    original = load_sveby_spec().use_spec(calendar_year=2024)
    before = original.model_dump_json()
    profile = load_dhw_profile("multi_family", purpose="epc_normal_use")
    changed = profile.apply_to(original)
    assert changed.dhw_kwh_m2_year == 25
    assert changed.model_dump(exclude={"dhw_kwh_m2_year"}) == original.model_dump(
        exclude={"dhw_kwh_m2_year"}
    )
    assert changed.dhw_fraction.hourly(2024) == original.dhw_fraction.hourly(2024)
    assert original.model_dump_json() == before


def test_profile_provenance_identifies_selected_assumption_and_source():
    profile = load_dhw_profile("multi_family", purpose="epc_normal_use")
    record = profile.source_record()
    assert isinstance(record, SourceRecord)
    assert record.field_path == "use.dhw_kwh_m2_year"
    assert record.status == "assumed"
    assert record.assumption_profile == profile.profile_id
    assert profile.source_uri in record.source
    assert profile.source_locator in record.source
    assert profile.source_record("common_use.dhw_kwh_m2_year").field_path == (
        "common_use.dhw_kwh_m2_year"
    )


def _compiled_schedule_hours(model, name, year):
    """Read emitted AllDays blocks without using ScheduleSpec's hourly resolver."""
    fields = [item["field"] for item in model["Schedule:Compact"][name]["data"]]
    previous = date(year, 1, 1) - timedelta(days=1)
    hourly = []
    cursor = 0
    while cursor < len(fields):
        assert fields[cursor].startswith("Through: ")
        month, day = map(int, fields[cursor].split(": ")[1].split("/"))
        end = date(year, month, day)
        assert fields[cursor + 1] == "For: AllDays"
        cursor += 2
        daily = []
        while cursor < len(fields) and fields[cursor].startswith("Until: "):
            end_hour, minute = map(int, fields[cursor].split(": ")[1].split(":"))
            assert minute == 0
            daily.extend([fields[cursor + 1]] * (end_hour - len(daily)))
            cursor += 2
        assert len(daily) == 24
        hourly.extend(daily * (end - previous).days)
        previous = end
    assert previous == date(year, 12, 31)
    return hourly


def _compiled_dhw_hourly_kwh(model, year):
    """Integrate emitted water flow and supply temperatures into thermal energy."""
    total = None
    for equipment in model["WaterUse:Equipment"].values():
        hot = model["Schedule:Constant"][
            equipment["hot_water_supply_temperature_schedule_name"]
        ]["hourly_value"]
        cold = model["Schedule:Constant"][
            equipment["cold_water_supply_temperature_schedule_name"]
        ]["hourly_value"]
        fractions = _compiled_schedule_hours(
            model, equipment["flow_rate_fraction_schedule_name"], year
        )
        # Water density [kg/m3], heat capacity [J/kg/K], flow [m3/s], 1 h [s].
        peak_kwh = equipment["peak_flow_rate"] * 998.2 * 4180 * (hot - cold) * 3600 / 3.6e6
        energy = [peak_kwh * fraction for fraction in fractions]
        total = energy if total is None else [a + b for a, b in zip(total, energy)]
    assert total is not None
    return total


@pytest.mark.parametrize("year", [2023, 2024])
@pytest.mark.parametrize(("building_type", "rate"), [("single_family", 20), ("multi_family", 25)])
def test_compiled_dhw_conserves_typed_demand_on_atemp(building, energyplus, year, building_type, rate):
    base_use = load_sveby_spec().use_spec(calendar_year=year)
    use = load_dhw_profile(building_type, purpose="epc_normal_use").apply_to(base_use)
    atemp = 900
    candidate = building.updated(
        use=use,
        load_reference_area_m2=atemp,
        climate=building.climate.updated(calendar_year=year),
    )
    assert candidate.geometry.conditioned_floor_area_m2 == 1800
    model, report = EnergyPlusCompiler(energyplus).compile(candidate)
    energy = _compiled_dhw_hourly_kwh(model, year)
    assert len(energy) == (8784 if year == 2024 else 8760)
    assert sum(energy) == pytest.approx(rate * atemp)
    assert report.data["load_reference_area_m2"] == atemp
    # Profile selection changes annual volume and retains the published monthly timing.
    fractions = base_use.dhw_fraction.hourly(year)
    fraction_sum = sum(fractions)
    assert energy == pytest.approx([rate * atemp * v / fraction_sum for v in fractions])


@pytest.mark.parametrize("year", [2023, 2024])
def test_selected_profiles_conserve_mixed_programme_dhw(building, energyplus, year):
    residential = load_dhw_profile("multi_family", purpose="epc_normal_use").apply_to(
        building.use.updated(occupancy_category="residential")
    )
    office = load_dhw_profile("office", purpose="epc_normal_use").apply_to(
        building.use.updated(
            occupancy_category="non_residential",
            dhw_fraction=ScheduleSpec(
                values=(0,) * 8 + (1,) * 8 + (0,) * 8,
                weekday_values=((0,) * 8 + (1,) * 8 + (0,) * 8,) * 5 + ((0,) * 24,) * 2,
            ),
        )
    )
    blend = ProgramBlend(
        source="synthetic Atemp shares",
        components=(
            ProgramComponent(name="homes", area_fraction=0.7, use=residential,
                             airflow=building.airflow, source="synthetic homes"),
            ProgramComponent(name="offices", area_fraction=0.3, use=office,
                             airflow=building.airflow, source="synthetic offices"),
        ),
    )
    mixed_use, mixed_airflow = blend.resolve(calendar_year=year)
    atemp = 900
    candidate = building.updated(
        use=mixed_use, airflow=mixed_airflow, load_reference_area_m2=atemp,
        climate=building.climate.updated(calendar_year=year),
    )
    model, _ = EnergyPlusCompiler(energyplus).compile(candidate)
    energy = _compiled_dhw_hourly_kwh(model, year)
    assert sum(energy) == pytest.approx((0.7 * 25 + 0.3 * 2) * atemp)
    profiles = [component.use.dhw_fraction.hourly(year) for component in blend.components]
    denominators = [sum(fraction) for fraction in profiles]
    expected = [
        atemp * sum(
            component.area_fraction * component.use.dhw_kwh_m2_year * fraction[hour]
            / denominator
            for component, fraction, denominator in zip(blend.components, profiles, denominators)
        )
        for hour in range(len(energy))
    ]
    assert energy == pytest.approx(expected)
