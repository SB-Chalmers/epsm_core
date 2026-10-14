"""Real EnergyPlus execution from explicit physical ground authoring."""
import pytest

from epsm_core import (
    Building, Footprint, FoundationSpec, GeometrySpec, GroundTemperatureSpec,
    Weather, run_building,
)


@pytest.mark.energyplus
@pytest.mark.parametrize("method", ["kiva", "prescribed_temperature"])
def test_authored_ground_runs_with_real_energyplus(method, energyplus, synthetic_weather, tmp_path):
    building = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(8, 6), storeys=1, storey_height_m=3))
    if method == "prescribed_temperature":
        building.foundation = FoundationSpec(method=method)
        building.ground_temperature = GroundTemperatureSpec(
            monthly_temperatures_c=(18.0,) * 12, source="synthetic-software-test")
    identity = building.snapshot().sha256
    result = run_building(building, weather=Weather.from_epw(synthetic_weather),
                         directory=tmp_path / method, energyplus=energyplus)
    assert result.diagnostics["building_snapshot_id"] == identity
    assert result.diagnostics["accepted"]
