from epsm_core import CompilerSettings, HourlyOutputRequest
from epsm_core.compiler import ENERGY_VARIABLES, EnergyPlusCompiler


def test_explicit_outputs_preserve_core_and_change_identity(building, energyplus):
    standard = EnergyPlusCompiler(energyplus)
    surrogate = EnergyPlusCompiler(
        energyplus,
        settings=CompilerSettings(
            hourly_outputs=(HourlyOutputRequest(name="Site Outdoor Air Drybulb Temperature"),)
        ),
    )
    model, report = surrogate.compile(building)
    base, _ = standard.compile(building)
    names = {v["variable_name"] for v in model["Output:Variable"].values()}
    base_names = {v["variable_name"] for v in base["Output:Variable"].values()}
    assert base_names < names
    assert "SITE OUTDOOR AIR DRYBULB TEMPERATURE" in names
    assert set(ENERGY_VARIABLES) <= names
    assert report.run_id != standard.run_id(building)
    assert report.data["compiler_settings"]["hourly_outputs"]


def test_rotated_boundary_rounding_midpoint_is_not_an_open_edge(building, energyplus):
    from epsm_core import Footprint, GeometrySpec

    # These shared vertices straddle a seven-decimal rounding midpoint when
    # reconstructed by subtraction/addition in opposite edge directions.
    polygon = Footprint(
        exterior=(
            (0.0, 15.563230066359885),
            (5.591351773859223, 1.658770553075449),
            (17.783001657083723, 6.561356168554411),
            (20.42149691228714, 0.0),
            (62.85692464366568, 17.064410442824276),
            (54.62707761460304, 37.53022612466313),
        )
    )
    spec = building.updated(
        geometry=GeometrySpec.from_footprint(polygon, storeys=2, storey_height_m=2.6722381722467845)
    )
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert report.data["validation"]["status"] == "passed"
    assert len(report.data["zones"]) == 2

    import pytest

    from epsm_core.surface_checks import validate_surfaces

    model["BuildingSurface:Detailed"].pop(next(iter(model["BuildingSurface:Detailed"])))
    with pytest.raises(ValueError):
        validate_surfaces(model, report.data["zones"])
