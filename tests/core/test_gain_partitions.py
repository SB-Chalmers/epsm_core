"""Internal-gain partition validation, budgets and compiler propagation."""

import pytest
from pydantic import ValidationError

from epsm_core import (
    ApartmentLayoutSpec,
    Building,
    EnergyPlusCompiler,
    GainPartitionSpec,
    ScheduleSpec,
    Weather,
    ZoneUseSpec,
    WindowLayoutSpec,
    ZoningSpec,
)
from epsm_core.gains import equipment_partition_fractions


def explicit_partitions(**changes):
    values = {
        "policy": "explicit",
        "people_fraction_radiant": 0.25,
        "people_sensible_heat_fraction": None,
        "equipment_fraction_radiant": 0.2,
        "equipment_fraction_latent": 0.1,
        "lighting_fraction_radiant": 0.3,
        "lighting_fraction_visible": 0.2,
        "lighting_return_air_fraction": 0.1,
    }
    values.update(changes)
    return GainPartitionSpec(**values)


def annual_heat_profile(year, values):
    """Repeat a short test pattern across a full year for schedule validation."""
    return ScheduleSpec.annual(
        (values * (8760 if year == 2023 else 8784))[: (8784 if year == 2024 else 8760)],
        calendar_year=year,
        source="synthetic gain-partition test schedule",
    )


@pytest.mark.parametrize(
    "fractions",
    [
        {"equipment_fraction_radiant": 0.8, "equipment_fraction_latent": 0.3},
        {"lighting_fraction_radiant": 0.5, "lighting_fraction_visible": 0.4,
         "lighting_return_air_fraction": 0.2},
        {"people_fraction_radiant": 1.01},
        {"equipment_fraction_radiant": float("nan")},
    ],
)
def test_explicit_partitions_reject_out_of_budget_fractions(fractions):
    with pytest.raises((ValidationError, ValueError)):
        explicit_partitions(**fractions)


def test_explicit_policy_requires_complete_channels_and_legacy_rejects_overrides():
    with pytest.raises((ValidationError, ValueError)):
        GainPartitionSpec(policy="explicit")
    with pytest.raises((ValidationError, ValueError)):
        GainPartitionSpec(policy="epsm_legacy_v1", people_fraction_radiant=0.25)
    legacy = GainPartitionSpec(policy="epsm_legacy_v1")
    assert legacy.policy == "epsm_legacy_v1"


def test_legacy_equipment_budget_preserves_hourly_minimum_radiant_cap(building):
    year = building.climate.calendar_year
    heat = annual_heat_profile(year, (0.1, 0.5, 0.8, 0.2))
    use = building.use.updated(
        equipment_heat_fraction_schedule=heat,
        equipment_fraction=ScheduleSpec.constant(0.5),
    )
    channels = equipment_partition_fractions(use, year)
    activity = use.equipment_fraction.hourly(year)
    available = heat.hourly(year)

    for hour in (0, 1, 2, 3, 4):
        radiant = min(0.3, available[hour])
        expected_shares = {
            "radiant": radiant,
            "latent": 0.0,
            "convective": available[hour] - radiant,
            "lost": 1 - available[hour],
        }
        assert sum(channels[name][hour] for name in expected_shares) == pytest.approx(1)
        for channel, share in expected_shares.items():
            assert channels[channel][hour] == pytest.approx(share)
            assert activity[hour] * channels[channel][hour] == pytest.approx(
                activity[hour] * share
            )


def test_legacy_scalar_heat_below_radiant_default_is_rejected(building):
    for partitions in (None, GainPartitionSpec(policy="epsm_legacy_v1")):
        with pytest.raises((ValidationError, ValueError), match="(?i)(partition|heat|fraction)"):
            building.use.updated(
                equipment_heat_fraction=0.2,
                equipment_heat_fraction_schedule=None,
                gain_partitions=partitions,
            )


def test_explicit_equipment_budget_is_not_capped_and_checks_minimum_schedule(building):
    year = building.climate.calendar_year
    heat = annual_heat_profile(year, (0.5, 0.8, 0.4))
    use = building.use.updated(
        equipment_heat_fraction_schedule=heat,
        gain_partitions=explicit_partitions(),
        equipment_fraction=ScheduleSpec.constant(0.5),
    )
    channels = equipment_partition_fractions(use, year)
    activity = use.equipment_fraction.hourly(year)
    available = heat.hourly(year)
    for hour in (0, 1, 2):
        expected_shares = {
            "radiant": 0.2,
            "latent": 0.1,
            "convective": available[hour] - 0.3,
            "lost": 1 - available[hour],
        }
        assert sum(channels[name][hour] for name in expected_shares) == pytest.approx(1)
        for channel, share in expected_shares.items():
            assert channels[channel][hour] == pytest.approx(share)
            assert activity[hour] * channels[channel][hour] == pytest.approx(
                activity[hour] * share
            )

    too_low = annual_heat_profile(year, (0.2, 0.8))
    with pytest.raises((ValidationError, ValueError), match="(?i)(partition|heat|fraction)"):
        building.use.updated(
            equipment_heat_fraction_schedule=too_low,
            gain_partitions=explicit_partitions(),
        )


def test_explicit_people_lighting_and_equipment_fields_reach_epjson(building, energyplus):
    partitions = explicit_partitions()
    use = building.use.updated(
        gain_partitions=partitions,
        equipment_gain_w_m2=4,
        lighting_gain_w_m2=5,
    )
    model, report = EnergyPlusCompiler(energyplus).compile(building.updated(use=use))
    zone_name, zone = next(iter(report.data["zones"].items()))
    budget = zone["gain_partitions"]
    assert budget["policy"] == "explicit"
    assert budget["selection"] == "explicit"
    assert budget["people"]["fraction_radiant"] == pytest.approx(0.25)
    assert budget["people"]["sensible_heat_fraction_source"] == "engine_autocalculate"
    assert budget["equipment"]["fraction_radiant"]["minimum"] == pytest.approx(0.2)
    assert budget["equipment"]["fraction_latent"]["maximum"] == pytest.approx(0.1)
    assert budget["lighting"]["fraction_convective"] == pytest.approx(0.4)

    people = model["People"][zone_name + "_people"]
    assert people["fraction_radiant"] == pytest.approx(0.25)
    assert "sensible_heat_fraction" not in people
    lighting = model["Lights"][zone_name + "_lighting"]
    assert lighting["fraction_radiant"] == pytest.approx(0.3)
    assert lighting["fraction_visible"] == pytest.approx(0.2)
    assert lighting["return_air_fraction"] == pytest.approx(0.1)
    equipment = model["ElectricEquipment"][zone_name + "_equipment"]
    assert equipment["fraction_radiant"] == pytest.approx(0.2)
    assert equipment["fraction_latent"] == pytest.approx(0.1)
    assert equipment["fraction_lost"] == pytest.approx(0)


def test_explicit_scheduled_equipment_emits_four_separate_budget_channels(
        building, energyplus):
    use = building.use.updated(
        gain_partitions=explicit_partitions(),
        equipment_fraction=ScheduleSpec.constant(0.5),
        equipment_heat_fraction_schedule=ScheduleSpec.constant(0.7),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(building.updated(use=use))
    zone_name = next(iter(report.data["zones"]))
    names = [zone_name + suffix for suffix in (
        "_equipment_radiant",
        "_equipment_sensible",
        "_equipment_lost",
        "_equipment_latent",
    )]
    assert len(set(names)) == 4
    assert model["ElectricEquipment"][names[0]]["fraction_radiant"] == 1
    assert model["ElectricEquipment"][names[1]]["fraction_radiant"] == 0
    assert model["ElectricEquipment"][names[2]]["fraction_lost"] == 1
    assert model["ElectricEquipment"][names[3]]["fraction_latent"] == 1
    expected = (0.1, 0.2, 0.15, 0.05)
    schedule_values = []
    for name, expected_share in zip(names, expected):
        schedule_name = model["ElectricEquipment"][name]["schedule_name"]
        data = model["Schedule:Compact"][schedule_name]["data"]
        numbers = [entry["field"] for entry in data
                   if isinstance(entry["field"], (int, float))]
        assert numbers and all(value == pytest.approx(expected_share) for value in numbers)
        schedule_values.append(numbers[0])
    assert sum(schedule_values) == pytest.approx(0.5)


def test_legacy_default_and_named_policy_are_reported(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    _, legacy_report = compiler.compile(building)
    legacy_zone = next(iter(legacy_report.data["zones"].values()))
    legacy = legacy_zone["gain_partitions"]
    assert legacy["policy"] == "epsm_legacy_v1"
    assert legacy["selection"] == "legacy_default"

    selected = building.use.updated(gain_partitions=GainPartitionSpec(policy="epsm_legacy_v1"))
    _, selected_report = compiler.compile(building.updated(use=selected))
    selected_budget = next(iter(selected_report.data["zones"].values()))["gain_partitions"]
    assert selected_budget["policy"] == "epsm_legacy_v1"
    assert selected_budget["selection"] == "policy"


def test_gain_partition_configuration_survives_use_json_and_building_roundtrips(
        synthetic_weather):
    partitions = explicit_partitions()
    authoring = Building(preset="illustrative-reference")
    authoring.operation = authoring.operation.with_changes(gain_partitions=partitions)

    use = authoring.operation
    assert type(use).model_validate_json(use.model_dump_json()) == use
    restored = Building.from_snapshot(authoring.snapshot())
    copied = restored.copy()
    weather = Weather.from_epw(synthetic_weather)
    spec = restored.to_spec(weather)
    assert restored.operation.gain_partitions == partitions
    assert copied.operation.gain_partitions == partitions
    assert spec.use.gain_partitions == partitions


def test_exact_zone_override_wins_over_zone_kind(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    kind_use = building.use.updated(gain_partitions=explicit_partitions(
        equipment_fraction_radiant=0.15,
        equipment_fraction_latent=0.05,
    ))
    exact_use = building.use.updated(gain_partitions=explicit_partitions(
        equipment_fraction_radiant=0.1,
        equipment_fraction_latent=0.2,
    ))
    zone_name = next(iter(compiler.compile(building)[1].data["zones"]))
    spec = building.updated(zone_uses=(
        ZoneUseSpec(zone_kind="main", use=kind_use, source="kind operation"),
        ZoneUseSpec(zone_name=zone_name, use=exact_use, source="exact operation"),
    ))
    _, report = compiler.compile(spec)
    exact_zone = report.data["zones"][zone_name]
    assert exact_zone["operation_sources"] == ["kind operation", "exact operation"]
    assert exact_zone["gain_partitions"]["equipment"]["fraction_radiant"]["minimum"] == pytest.approx(0.1)
    assert exact_zone["gain_partitions"]["equipment"]["fraction_latent"]["maximum"] == pytest.approx(0.2)



def test_common_use_override_emits_its_own_gain_partition_policy(building, energyplus):
    pytest.importorskip("py_straight_skeleton")
    residential = building.updated(
        use=building.use.updated(occupancy_category="residential"),
        facade=building.facade.updated(
            layout=WindowLayoutSpec(mode="wwr"), reveal_depth_m=0.2
        ),
        envelope=building.envelope.updated(
            dwelling_partition=building.envelope.intermediate_floor,
            common_partition=building.envelope.intermediate_floor,
        ),
        geometry=building.geometry.updated(
            zoning=ZoningSpec(
                mode="apartments", apartments=ApartmentLayoutSpec(max_candidates=1000)
            )
        ),
    )
    common_use = building.use.updated(
        equipment_gain_w_m2=2,
        gain_partitions=explicit_partitions(
            equipment_fraction_radiant=0.1,
            equipment_fraction_latent=0.1,
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(
        residential.updated(common_use=common_use)
    )
    assert report.data["layout"]["status"] == "generated"
    common_zones = [
        (name, item) for name, item in report.data["zones"].items()
        if item.get("zone_kind") in ("common", "stairwell")
    ]
    assert common_zones
    for name, item in common_zones:
        budget = item["gain_partitions"]
        assert budget["selection"] == "explicit"
        assert budget["equipment"]["fraction_radiant"]["minimum"] == pytest.approx(0.1)
        assert budget["equipment"]["fraction_latent"]["maximum"] == pytest.approx(0.1)
        equipment = model["ElectricEquipment"][name + "_equipment"]
        assert equipment["fraction_latent"] == pytest.approx(0.1)
