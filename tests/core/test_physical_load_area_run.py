"""Load-reference area remains distinct in an actual physical Building run."""
import json

import pytest

from epsm_core import Building, Footprint, GeometrySpec, Weather, run_building


@pytest.mark.energyplus
def test_explicit_load_reference_area_reaches_real_run(energyplus, synthetic_weather, tmp_path):
    building = Building(preset="illustrative-reference", load_reference_area_m2=36,
                        geometry=GeometrySpec.from_footprint(
                            Footprint.rectangle(8, 6), storeys=1, storey_height_m=3))
    directory = tmp_path / "explicit-area"
    result = run_building(building, weather=Weather.from_epw(synthetic_weather),
                         directory=directory, energyplus=energyplus)
    assert result.diagnostics["accepted"]
    report = json.loads(json.loads((directory / "compilation.json").read_text())["report_json"])
    assert report["load_reference_area_m2"] == 36
    assert report["conditioned_floor_area_m2"] == 48
    assert report["conditioned_volume_m3"] == 144
