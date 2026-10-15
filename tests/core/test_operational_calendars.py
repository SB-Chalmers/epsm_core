"""Independent calendar, integral and EnergyPlus handover checks (2026-10-03)."""

from calendar import monthrange
from datetime import date, timedelta

import pytest
from profile_inputs import nonresidential_converter, residential_converter

from epsm_core import (
    BuildingBuilder,
    SchedulePeriod,
    ScheduleSpec,
    UnconditionedExchangeSpec,
    ZoneUseSpec,
)
from epsm_core.compiler import EnergyPlusCompiler


def active_days(year, count):
    """Synthetic unit-test calendar, not an inferred Swedish holiday calendar."""
    days = []
    day = date(year, 1, 1)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def test_actual_weekdays_leap_day_and_period_precedence():
    schedule = ScheduleSpec(
        values=(0,) * 24,
        weekday_values=((1,) * 24,) * 5 + ((0,) * 24,) * 2,
        periods=(
            SchedulePeriod(
                start_date="2024-02-29",
                end_date="2024-02-29",
                values=(0.25,) * 24,
                source="documented closure",
            ),
        ),
    )
    hours = schedule.hourly(2024)
    assert len(hours) == 8784
    assert hours[:24] == (1,) * 24  # Monday, 1 January
    assert hours[5 * 24 : 6 * 24] == (0,) * 24
    assert hours[59 * 24 : 60 * 24] == (0.25,) * 24
    with pytest.raises(ValueError, match="differs"):
        schedule.hourly(2023)
    assert schedule.compact_data(2024)[-2:] == [{"field": "Until: 24:00"}, {"field": 1.0}]


def test_annual_rules_reject_wrong_length_overlap_and_nonfinite():
    with pytest.raises(ValueError, match="length"):
        ScheduleSpec.annual([1] * 8760, calendar_year=2024)
    with pytest.raises(ValueError):
        ScheduleSpec.annual([float("nan")] * 8760, calendar_year=2023)
    with pytest.raises(ValueError, match="overlap"):
        ScheduleSpec(
            values=(0,) * 24,
            periods=(
                SchedulePeriod(
                    start_date="2023-01-01", end_date="2023-01-04", values=(1,) * 24, source="a"
                ),
                SchedulePeriod(
                    start_date="2023-01-04", end_date="2023-01-05", values=(0,) * 24, source="b"
                ),
            ),
        )


def test_fraction_and_setpoint_checks_include_calendar_overrides(building):
    bad = ScheduleSpec(values=(0,) * 24, weekday_values=((2,) * 24,) * 7)
    with pytest.raises(ValueError, match="occupancy_fraction"):
        building.use.updated(occupancy_fraction=bad)
    heating = ScheduleSpec(
        values=(21,) * 24,
        periods=(
            SchedulePeriod(
                start_date="2023-02-01",
                end_date="2023-02-02",
                values=(32,) * 24,
                source="invalid test setpoint",
            ),
        ),
    )
    with pytest.raises(ValueError, match="below cooling"):
        building.use.updated(heating_setpoint=heating)
    with pytest.raises(ValueError, match="mechanical_vent_fraction"):
        building.airflow.updated(mechanical_vent_fraction=bad)


@pytest.mark.parametrize("year", [2023, 2024])
def test_residential_monthly_energy_conserves_source_totals(year):
    standard = residential_converter()
    use = standard.use_spec(calendar_year=year)
    assert sum(
        use.equipment_fraction.hourly(year)
    ) * use.equipment_gain_w_m2 / 1000 == pytest.approx(14.7)
    fractions = use.dhw_fraction.hourly(year)
    cursor = 0
    for month, energy in enumerate(standard.data["use"]["dhw_monthly_kwh_m2"], 1):
        hours = monthrange(year, month)[1] * 24
        actual_share = sum(fractions[cursor : cursor + hours]) / sum(fractions)
        expected_share = energy / sum(standard.data["use"]["dhw_monthly_kwh_m2"])
        assert actual_share == pytest.approx(expected_share)
        cursor += hours


def test_office_calendar_and_electrical_heat_boundary():
    profile = nonresidential_converter("office")
    defaults = profile.building_assumptions(
        calendar_year=2023,
        active_dates=active_days(2023, 225),
        calendar_source="synthetic test calendar",
    )
    from epsm_core import AirflowSpec, UseSpec

    use = UseSpec.model_validate(defaults["use"])
    electric = sum(use.equipment_fraction.hourly(2023)) * use.equipment_gain_w_m2 / 1000
    assert electric == pytest.approx(50)
    assert electric * use.equipment_heat_fraction == pytest.approx(35)
    assert sum(use.occupancy_fraction.hourly(2023)) == pytest.approx(225 * 9 * 0.7)
    assert defaults["airflow"]["mechanical_vent_l_s_m2"] == 1.3
    airflow = AirflowSpec(topology="FT", envelope_infiltration_ach=0.2, **defaults["airflow"])
    assert sum(airflow.mechanical_vent_fraction.hourly(2023)) == 225 * 12
    assert use.occupancy_fraction.source == "synthetic test calendar"


def test_school_calendar_source_and_activity_counts():
    profile = nonresidential_converter("school")
    with pytest.raises(ValueError, match="source"):
        profile.building_assumptions(
            calendar_year=2023, active_dates=active_days(2023, 220), calendar_source=""
        )
    defaults = profile.building_assumptions(
        calendar_year=2023,
        active_dates=active_days(2023, 220),
        calendar_source="synthetic test calendar",
    )
    from epsm_core import UseSpec

    use = UseSpec.model_validate(defaults["use"])
    assert sum(use.occupancy_fraction.hourly(2023)) == 1320
    assert (
        sum(use.lighting_fraction.hourly(2023)) * use.lighting_gain_w_m2
        + sum(use.equipment_fraction.hourly(2023)) * use.equipment_gain_w_m2
    ) / 1000 == 22
    assert set(use.heating_setpoint.all_values) == {22}
    with pytest.raises(ValueError, match="day count"):
        profile.building_assumptions(
            calendar_year=2023, active_dates=active_days(2023, 219), calendar_source="test"
        )


def test_builder_requires_explicit_nonresidential_profile(building):
    with pytest.raises(ValueError, match="Select"):
        BuildingBuilder(building_use="residential").build(
            **building.updated(
                use=building.use.updated(occupancy_category="non_residential")
            ).model_dump(exclude={"provenance"})
        )
    with pytest.raises(ValueError, match="require year"):
        BuildingBuilder(building_use="office")


def test_custom_actual_use_profile_retains_declared_evidence_status(building):
    builder = BuildingBuilder(
        building_use="office", assumption_profile="observed.office.test", assumptions={}
    )
    spec = building.updated(use=building.use.updated(occupancy_category="non_residential"))
    result = builder.build(
        input_status="assumed",
        source="synthetic integration",
        **spec.model_dump(exclude={"provenance"}),
    )
    assert result.use == spec.use
    assert result.provenance.records
    assert all(record.status == "assumed" for record in result.provenance.records)


def test_physical_zone_kind_override_is_applied(building, energyplus):
    from epsm_core import ZoningSpec

    spec = building.updated(
        geometry=building.geometry.updated(zoning=ZoningSpec(mode="whole_building")),
        zone_uses=(
            ZoneUseSpec(
                zone_kind="main",
                source="documented closure",
                airflow=building.airflow.updated(mechanical_vent_fraction=ScheduleSpec.constant(0)),
            ),
        ),
    )
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert all(
        z["airflow_input"]["mechanical_vent_fraction"]["values"] == [0] * 24
        for z in report.data["zones"].values()
        if z["conditioned"]
    )


def test_native_basement_exchange_and_area_allocation(building, energyplus):
    spec = building.updated(
        geometry=building.geometry.updated(basement_depth_m=2.5),
        unconditioned_exchange=(
            UnconditionedExchangeSpec(
                zone_kind="basement",
                outdoor_air_ach=0.2,
                source="documented synthetic basement exchange",
            ),
        ),
    )
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    basement = [z for z in report.data["zones"].values() if z["physical_zone_kind"] == "basement"]
    assert basement and all(z["exchange_source"].startswith("documented") for z in basement)
    with pytest.raises(ValueError, match="sum to"):
        zone = next(name for name, z in report.data["zones"].items() if z["conditioned"])
        spec = building.updated(
            load_reference_area_m2=900,
            zone_uses=(
                ZoneUseSpec(
                    zone_name=zone,
                    reference_area_m2=901,
                    use=building.use,
                    source="invalid allocation",
                ),
            ),
        )
        EnergyPlusCompiler(energyplus).compile(spec)


def test_native_zone_operation_area_and_scheduled_airflow(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    _, original = compiler.compile(building)
    zone = next(iter(original.data["zones"]))
    off = ScheduleSpec.constant(0)
    custom = building.updated(
        load_reference_area_m2=900,
        zone_uses=(
            ZoneUseSpec(
                zone_name=zone,
                source="measured operation",
                use=building.use.updated(dhw_kwh_m2_year=0),
                airflow=building.airflow.updated(mechanical_vent_fraction=off),
            ),
        ),
    )
    model, report = compiler.compile(custom)
    assert report.data["conditioned_floor_area_m2"] == 1800
    assert report.data["load_reference_area_m2"] == 900
    assert sum(x["number_of_people"] for x in model["People"].values()) == pytest.approx(
        900 * 0.017
    )
    assert all(
        x["outdoor_air_schedule_name"].endswith("mechanical_vent_fraction")
        for x in model["DesignSpecification:OutdoorAir"].values()
    )
    assert model["WaterUse:Equipment"][zone + "_dhw"]["peak_flow_rate"] == 0
    with pytest.raises(ValueError, match="matches no"):
        compiler.compile(
            building.updated(
                zone_uses=(
                    ZoneUseSpec(zone_name="typo", use=building.use, source="invalid selector"),
                )
            )
        )


def test_native_cold_attic_exchange_is_separate_from_leakage(building, energyplus):
    from epsm_core import RoofSpec

    custom = building.updated(
        geometry=building.geometry.updated(roof=RoofSpec(topology="cold_attic")),
        unconditioned_exchange=(
            UnconditionedExchangeSpec(
                zone_kind="attic", outdoor_air_ach=1, source="explicit sensitivity assumption"
            ),
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(custom)
    exchange = [
        x
        for name, x in model["ZoneInfiltration:DesignFlowRate"].items()
        if "unconditioned_exchange" in name
    ]
    assert len(exchange) == 1 and exchange[0]["air_changes_per_hour"] == 1
    assert all(
        z["exchange_source"] == "explicit sensitivity assumption"
        for z in report.data["zones"].values()
        if not z["conditioned"]
    )
