"""Hourly conservation and native compiler regressions for mixed programmes."""

import math

import pytest

from epsm_core import GainPartitionSpec, ProgramBlend, ProgramComponent
from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.specs import AirflowSpec, SchedulePeriod, ScheduleSpec, UseSpec


def mixture(year=2024):
    residential = UseSpec(
        heating_setpoint=ScheduleSpec.constant(21),
        occupancy_category="residential",
        occupant_density_per_m2=0.02,
        occupant_activity_w=80,
        equipment_gain_w_m2=2,
        equipment_heat_fraction=1,
        dhw_kwh_m2_year=25,
    )
    office = residential.updated(
        occupancy_category="non_residential",
        occupant_density_per_m2=0.1,
        occupant_activity_w=108,
        equipment_gain_w_m2=10,
        equipment_heat_fraction=0.7,
        dhw_kwh_m2_year=2,
        occupancy_fraction=ScheduleSpec(
            values=(0,) * 24,
            weekday_values=((0,) * 8 + (1,) * 8 + (0,) * 8,) * 5 + ((0,) * 24,) * 2,
            periods=(
                SchedulePeriod(
                    start_date=f"{year}-02-29" if year == 2024 else f"{year}-02-28",
                    end_date=f"{year}-02-29" if year == 2024 else f"{year}-02-28",
                    values=(0,) * 24,
                    source="synthetic closure",
                ),
            ),
        ),
        equipment_fraction=ScheduleSpec(values=(0,) * 12 + (1,) * 12),
        dhw_fraction=ScheduleSpec(values=(1,) * 8 + (0,) * 16),
    )
    airflow = AirflowSpec(topology="F", envelope_infiltration_ach=0.2, mechanical_vent_l_s_m2=0.35)
    return ProgramBlend(
        source="synthetic area survey",
        components=(
            ProgramComponent(
                name="residential",
                area_fraction=0.8,
                use=residential,
                airflow=airflow,
                source="synthetic residential",
            ),
            ProgramComponent(
                name="office",
                area_fraction=0.2,
                use=office,
                airflow=airflow.updated(
                    mechanical_vent_l_s_m2=1, mechanical_vent_fraction=office.occupancy_fraction
                ),
                source="synthetic office",
            ),
        ),
    )


@pytest.mark.parametrize("year", [2023, 2024])
def test_hourly_load_people_heat_electricity_ventilation_and_dhw_conservation(year):
    blend = mixture(year)
    use, air = blend.resolve(calendar_year=year)
    assert len(use.occupancy_fraction.annual_values) == (8784 if year == 2024 else 8760)
    for rate, fraction in (
        ("occupant_density_per_m2", "occupancy_fraction"),
        ("equipment_gain_w_m2", "equipment_fraction"),
        ("lighting_gain_w_m2", "lighting_fraction"),
    ):
        actual = [getattr(use, rate) * v for v in getattr(use, fraction).hourly(year)]
        profiles = [getattr(c.use, fraction).hourly(year) for c in blend.components]
        expected = [
            sum(
                c.area_fraction * getattr(c.use, rate) * profile[h]
                for c, profile in zip(blend.components, profiles)
            )
            for h in range(len(actual))
        ]
        assert actual == pytest.approx(expected)
    people = use.occupancy_fraction.hourly(year)
    activity = use.occupant_activity_schedule.hourly(year)
    equipment = use.equipment_fraction.hourly(year)
    heat = use.equipment_heat_fraction_schedule.hourly(year)
    for h in (0, 8, 12, 16, 24, 24 * 59 + 12):
        assert use.occupant_density_per_m2 * people[h] * activity[h] == pytest.approx(
            sum(
                c.area_fraction
                * c.use.occupant_density_per_m2
                * c.use.occupancy_fraction.hourly(year)[h]
                * c.use.occupant_activity_w
                for c in blend.components
            )
        )
        assert use.equipment_gain_w_m2 * equipment[h] * heat[h] == pytest.approx(
            sum(
                c.area_fraction
                * c.use.equipment_gain_w_m2
                * c.use.equipment_fraction.hourly(year)[h]
                * c.use.equipment_heat_fraction
                for c in blend.components
            )
        )
        assert air.mechanical_vent_l_s_m2 * air.mechanical_vent_fraction.hourly(year)[
            h
        ] == pytest.approx(
            sum(
                c.area_fraction
                * c.airflow.mechanical_vent_l_s_m2
                * c.airflow.mechanical_vent_fraction.hourly(year)[h]
                for c in blend.components
            )
        )
        dhw = use.dhw_fraction.hourly(year)
        assert use.dhw_kwh_m2_year * dhw[h] / sum(dhw) == pytest.approx(
            sum(
                c.area_fraction
                * c.use.dhw_kwh_m2_year
                * c.use.dhw_fraction.hourly(year)[h]
                / sum(c.use.dhw_fraction.hourly(year))
                for c in blend.components
            )
        )
    assert use.occupancy_category == "unspecified"


def test_invalid_fractions_and_heterogeneous_systems_require_explicit_zones():
    blend = mixture()
    with pytest.raises(ValueError, match="sum to one"):
        blend.updated(components=(blend.components[0],))
    changed = blend.components[1].updated(
        airflow=blend.components[1].airflow.updated(topology="FT")
    )
    with pytest.raises(ValueError, match="topology"):
        blend.updated(components=(blend.components[0], changed)).resolve(calendar_year=2024)
    changed = blend.components[1].updated(
        use=blend.components[1].use.updated(heating_setpoint=ScheduleSpec.constant(20))
    )
    different = blend.updated(components=(blend.components[0], changed))
    with pytest.raises(ValueError, match="setpoints"):
        different.resolve(calendar_year=2024)
    assert (
        different.resolve(calendar_year=2024, control_use=blend.components[0].use)[
            0
        ].heating_setpoint.values[0]
        == 21
    )
    with pytest.raises(ValueError, match="calendar"):
        blend.resolve(calendar_year=2023)


def test_native_load_emission_preserves_electricity_and_heat(building):
    year = building.climate.calendar_year
    use, air = mixture(year).resolve(calendar_year=year)
    spec = building.updated(use=use, airflow=air)
    objects = {}

    def add(kind, name, **fields):
        objects[(kind, name)] = fields

    EnergyPlusCompiler._loads(add, "mixed", 100, 280, spec)
    sensible = objects["ElectricEquipment", "mixed_equipment_sensible"]
    lost = objects["ElectricEquipment", "mixed_equipment_lost"]
    assert objects["ElectricEquipment", "mixed_equipment_radiant"]["fraction_radiant"] == 1
    assert sensible["fraction_lost"] == 0
    assert lost["fraction_lost"] == 1
    assert sensible["design_level"] == lost["design_level"] == pytest.approx(360)
    assert sensible["fraction_radiant"] + sensible["fraction_lost"] <= 1
    assert lost["fraction_radiant"] + lost["fraction_lost"] <= 1
    assert objects["People", "mixed_people"]["number_of_people"] == pytest.approx(3.6)
    assignment = mixture(year).zone_assignment(calendar_year=year, zone_kind="occupied")
    assert assignment.use.occupant_activity_schedule is not None


def test_zero_load_and_nested_blends_are_finite():
    blend = mixture()
    empty = blend.components[0].use.updated(
        occupant_density_per_m2=0, equipment_gain_w_m2=0, dhw_kwh_m2_year=0
    )
    zero = blend.updated(components=tuple(c.updated(use=empty) for c in blend.components))
    use, _ = zero.resolve(calendar_year=2024)
    assert all(math.isfinite(v) for v in use.occupant_activity_schedule.all_values)
    assert not any(use.dhw_fraction.all_values)
    resolved, air = blend.resolve(calendar_year=2024)
    single = ProgramBlend(
        source="nested blend",
        components=(
            ProgramComponent(
                name="mixed", area_fraction=1, use=resolved, airflow=air, source="resolved blend"
            ),
        ),
    )
    again, _ = single.resolve(calendar_year=2024)
    assert again.occupant_activity_schedule.annual_values == pytest.approx(
        resolved.occupant_activity_schedule.annual_values
    )


def test_program_blend_carries_equal_gain_partition_policy():
    base = mixture()
    policy = GainPartitionSpec(
        policy="explicit",
        people_fraction_radiant=0.25,
        people_sensible_heat_fraction=None,
        equipment_fraction_radiant=0.2,
        equipment_fraction_latent=0.1,
        lighting_fraction_radiant=0.3,
        lighting_fraction_visible=0.2,
        lighting_return_air_fraction=0.1,
    )
    components = tuple(
        component.updated(use=component.use.updated(gain_partitions=policy))
        for component in base.components
    )
    blend = base.updated(components=components)

    effective, _ = blend.resolve(calendar_year=2024)
    assert effective.gain_partitions == policy


@pytest.mark.parametrize("change", ["field", "policy", "missing_vs_selected"])
def test_program_blend_rejects_mixed_gain_partition_configurations(change):
    base = mixture()
    policy = GainPartitionSpec(
        policy="explicit",
        people_fraction_radiant=0.25,
        people_sensible_heat_fraction=None,
        equipment_fraction_radiant=0.2,
        equipment_fraction_latent=0.1,
        lighting_fraction_radiant=0.3,
        lighting_fraction_visible=0.2,
        lighting_return_air_fraction=0.1,
    )
    first = base.components[0].use.updated(gain_partitions=policy)
    if change == "field":
        second = base.components[1].use.updated(
            gain_partitions=policy.updated(equipment_fraction_radiant=0.15)
        )
    elif change == "policy":
        second = base.components[1].use.updated(
            gain_partitions=GainPartitionSpec(policy="epsm_legacy_v1")
        )
    else:
        second = base.components[1].use
    components = (
        base.components[0].updated(use=first),
        base.components[1].updated(use=second),
    )
    with pytest.raises(ValueError, match="(?i)(gain|partition|policy)"):
        base.updated(components=components).resolve(calendar_year=2024)


def test_blended_native_compiler_schema(building, energyplus):
    year = building.climate.calendar_year
    use, air = mixture(year).resolve(calendar_year=year)
    spec = building.updated(use=use, airflow=air)
    model, _ = EnergyPlusCompiler(energyplus).compile(spec)
    assert "activity" in model["Schedule:Compact"]
    assert "activity" not in model["Schedule:Constant"]
    assert any(name.endswith("_equipment_sensible") for name in model["ElectricEquipment"])
    assert any(name.endswith("_equipment_lost") for name in model["ElectricEquipment"])
    assert type(spec).model_validate_json(spec.model_dump_json()) == spec


@pytest.mark.energyplus
def test_blended_annual_electricity_and_dhw(building, energyplus, tmp_path):
    from epsm_core import CompilerSettings, EnergyPlusRunner, HourlyOutputRequest

    year = building.climate.calendar_year
    blend = mixture(year)
    use, air = blend.resolve(calendar_year=year)
    area = 900
    settings = CompilerSettings(
        hourly_outputs=(HourlyOutputRequest(name="Zone Electric Equipment Electricity Energy"),)
    )
    output = EnergyPlusRunner(energyplus, settings=settings).run(
        building.updated(use=use, airflow=air, load_reference_area_m2=area), tmp_path / "mixed"
    )
    assert output.scalars["dhw_load_kwh"] == pytest.approx(use.dhw_kwh_m2_year * area, rel=0.005)
    assert output.diagnostics["severe_count"] == 0
    expected = sum(
        c.area_fraction
        * c.use.equipment_gain_w_m2
        * area
        * sum(c.use.equipment_fraction.hourly(year))
        / 1000
        for c in blend.components
    )
    # Requested native zone totals include both sensible and lost objects.
    signals = [
        values
        for name, values in output.hourly.items()
        if name.upper().startswith("ZONE ELECTRIC EQUIPMENT ELECTRICITY ENERGY::")
    ]
    assert signals, output.hourly.keys()
    assert sum(sum(values) for values in signals) / 3.6e6 == pytest.approx(expected, rel=0.005)
