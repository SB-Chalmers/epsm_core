"""Explicit gain partitions work through real physical Building execution."""
import json

import pytest

from epsm_core import (
    Building, Footprint, GainPartitionSpec, GeometrySpec, ScheduleSpec, Weather, run_building,
)


@pytest.mark.energyplus
@pytest.mark.parametrize("sensible", [None, 0.6])
def test_explicit_gain_partitions_reach_real_run(sensible, energyplus, synthetic_weather, tmp_path):
    building = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(8, 6), storeys=1, storey_height_m=3))
    partitions = GainPartitionSpec(
        policy="explicit", people_fraction_radiant=.25, people_sensible_heat_fraction=sensible,
        equipment_fraction_radiant=.2, equipment_fraction_latent=.1,
        lighting_fraction_radiant=.3, lighting_fraction_visible=.2, lighting_return_air_fraction=.1)
    building.operation = building.operation.with_changes(
        gain_partitions=partitions, equipment_fraction=ScheduleSpec.constant(.5),
        equipment_heat_fraction_schedule=ScheduleSpec.constant(.7), lighting_gain_w_m2=.6)
    directory = tmp_path / "custom-gains"
    result = run_building(building, weather=Weather.from_epw(synthetic_weather),
                         directory=directory, energyplus=energyplus)
    assert result.diagnostics["accepted"]
    report = json.loads(json.loads((directory / "compilation.json").read_text())["report_json"])
    gains = next(iter(report["zones"].values()))["gain_partitions"]
    assert gains["selection"] == "explicit"
    assert gains["people"]["sensible_heat_fraction"] == sensible
    assert gains["equipment"]["fraction_lost"]["minimum"] == pytest.approx(.3)
