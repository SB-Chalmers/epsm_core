"""Public development contract and shared geometry output invariants."""

import json

import pytest

from epsm_core import (
    CompilerSettings,
    HourlyOutputRequest,
    EnergyPlusCompiler,
    Footprint,
    GeometrySpec,
    RoofSpec,
    ZoningSpec,
)
from epsm_core._version import __version__
from epsm_core.compiler import COMPILER_VERSION, compiler_source_hash
from epsm_core.inspection import geometry_scene
from epsm_core.pipeline import resolve_geometry
from epsm_core.specs import BuildingSpec


def test_current_schema_version_and_roundtrip(building):
    assert __version__ == COMPILER_VERSION == "0.2.0.dev0"
    data = building.model_dump(mode="json")
    assert "schema_version" not in data
    assert BuildingSpec.model_validate_json(json.dumps(data)) == building
    with pytest.raises(ValueError):
        BuildingSpec.model_validate({**data, "schema_version": 3})


def test_nested_source_hash(tmp_path):
    (tmp_path / "nested").mkdir()
    source = tmp_path / "nested" / "geometry.py"
    source.write_text("VALUE = 1\n")
    before = compiler_source_hash(tmp_path)
    source.write_text("VALUE = 2\n")
    assert compiler_source_hash(tmp_path) != before
    before = compiler_source_hash(tmp_path)
    source.rename(tmp_path / "geometry.py")
    assert compiler_source_hash(tmp_path) != before


def test_engine_settings_change_identity(building, energyplus):
    first = EnergyPlusCompiler(energyplus)
    second = EnergyPlusCompiler(energyplus, settings=CompilerSettings(hourly_outputs=(
        HourlyOutputRequest(name="Site Outdoor Air Drybulb Temperature"),)))
    assert first.run_id(building) != second.run_id(building)
    assert first.compiler_hash == second.compiler_hash


def test_convenience_geometry_and_roof():
    g = GeometrySpec.from_footprint(
        Footprint.rectangle(30, 20), storeys=3, storey_height_m=3, height_status="measured"
    )
    assert g.zoning.mode == "per_storey"
    assert g.parts[0].storey_elevations_m == (0, 3, 6, 9)
    assert g.parts[0].height_status == "measured"
    assert RoofSpec(shape="gable").topology == "cold_attic"
    with pytest.raises(ValueError, match="OR"):
        GeometrySpec.from_footprint(
            Footprint.rectangle(2, 2), storeys=1, storey_height_m=3, storey_elevations_m=(0, 3)
        )
    with pytest.raises(ValueError, match="Flat"):
        RoofSpec(pitch_deg=30)


@pytest.mark.parametrize("mode", ["whole_building", "per_storey", "perimeter_core"])
def test_engine_free_geometry_scene(mode, monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError("Geometry preview must not instantiate EnergyPlus")

    monkeypatch.setattr(EnergyPlusCompiler, "__init__", unavailable)
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(30, 20), storeys=2, storey_height_m=3, zoning=ZoningSpec(mode=mode)
    )
    scene, report = geometry_scene(geometry)
    assert scene["BuildingSurface:Detailed"]
    assert report["geometry_only"]
    assert sum(z["floor_area_m2"] for z in report["zones"].values()) == pytest.approx(1200)
    json.dumps((scene, report), allow_nan=False)


def test_logical_windows_and_shading_independent_of_zoning(building):
    b = building.updated(facade=building.facade.updated(reveal_depth_m=0.2))
    scenes = [
        resolve_geometry(b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode=mode))))
        for mode in ("whole_building", "per_storey", "perimeter_core")
    ]

    def logical(scene):
        return {
            o.metadata["logical_window"]: o.metadata["logical_vertices"] for o in scene.openings
        }

    assert logical(scenes[0]) == logical(scenes[1]) == logical(scenes[2])
    assert scenes[0].shading == scenes[1].shading == scenes[2].shading
