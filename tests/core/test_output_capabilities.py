"""Output discovery follows owner contracts without starting EnergyPlus."""

from importlib.resources import files

import pytest

from epsm_core import Building, Weather


def test_public_output_catalogue_has_normalized_and_explicit_zone_signals(monkeypatch):
    import epsm_core
    from epsm_core import output_capabilities
    from epsm_core.specs import DeliverySpec

    def forbidden(*args, **kwargs):
        raise AssertionError("Output discovery initialized EnergyPlus")

    monkeypatch.setattr(epsm_core.EnergyPlusCompiler, "__init__", forbidden)
    building = Building(preset="illustrative-reference")
    building.hvac = building.hvac.with_changes(delivery=DeliverySpec())
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    catalogue = output_capabilities(building, weather=weather)
    outputs = {(row["name"], row["resolution"], row["level"]): row for row in catalogue["outputs"]}
    assert outputs["space_heating_demand_kwh", "hourly", "building"]["unit"] == "kWh"
    assert outputs["space_heating_demand_kwh", "annual", "building"]["available"]
    assert not outputs["space_heating_carrier_input_kwh", "annual", "building"]["available"]
    zones = building.resolve(weather).zones
    assert all(
        (f"Zone Mean Air Temperature::{name.upper()}", "hourly", "zone") in outputs
        for name in zones
    )


def test_arbitrary_compiler_request_is_recorded_as_unverified():
    from epsm_core import CompilerSettings, HourlyOutputRequest, output_capabilities

    settings = CompilerSettings(hourly_outputs=(HourlyOutputRequest(name="Imaginary Energy"),))
    catalogue = output_capabilities(settings=settings)
    assert catalogue["unverified_requests"][0]["name"] == "IMAGINARY ENERGY"
    assert all(row["name"] != "Imaginary Energy" for row in catalogue["outputs"])


@pytest.mark.energyplus
def test_guaranteed_normalized_descriptors_match_actual_engine_results(
    building, energyplus, tmp_path
):
    from epsm_core import EnergyPlusRunner, output_capabilities

    result = EnergyPlusRunner(energyplus).run(building, tmp_path / "engine")
    for descriptor in output_capabilities()["outputs"]:
        if not descriptor["available"]:
            continue
        collection = result.hourly if descriptor["resolution"] == "hourly" else result.scalars
        assert descriptor["name"] in collection
        assert result.units[descriptor["name"]] == descriptor["unit"]
