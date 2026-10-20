"""Neutral scenes preserve physical polygons without runtime or presentation work."""

import builtins
import json
import socket
import subprocess
import webbrowser
from copy import deepcopy
from pathlib import Path

import pytest

from epsm_core import Building, EnergyPlusCompiler, Footprint, GeometrySpec


def test_scene_preserves_polygons_openings_and_source_metadata():
    from epsm_core import scene_data

    def face(points, **fields):
        return dict(
            vertices=[
                dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                for x, y, z in points
            ],
            **fields,
        )

    wall = [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]]
    window = [[1, 0, 1], [3, 0, 1], [3, 0, 2], [1, 0, 2]]
    model = {
        "BuildingSurface:Detailed": {
            "wall": face(
                wall,
                zone_name="room",
                construction_name="brick",
                outside_boundary_condition="Outdoors",
            )
        },
        "FenestrationSurface:Detailed": {"window": face(window, building_surface_name="wall")},
        "InternalMass": {"slab": {"surface_area": 8}},
    }
    report = {
        "surfaces": {"wall": {"physical_element_id": "physical.wall"}},
        "internal_mass": [{"name": "slab", "vertices": [wall]}],
    }
    diagnostics, preparation = {"accepted": False}, {"status": "review_required"}
    original = deepcopy((model, report, diagnostics, preparation))
    data = scene_data(model, report, diagnostics, preparation)
    assert (data["schema"], data["units"], data["up_axis"]) == ("epsm.scene/1", "m", "Z")
    objects = {obj["name"]: obj for obj in data["objects"]}
    assert set(objects) == {"wall", "window"}
    assert objects["wall"]["id"] == "wall"
    assert objects["wall"]["vertices"] == wall
    assert objects["wall"]["holes"] == [window]
    assert objects["wall"]["area_m2"] == 12
    assert objects["wall"]["net_area_m2"] == 10
    assert objects["wall"]["metadata"]["physical_element_id"] == "physical.wall"
    assert objects["window"]["parent"] == "wall"
    assert objects["window"]["holes"] == []
    assert all("triangles" not in obj for obj in data["objects"])
    assert data["internal_mass"] == model["InternalMass"]
    assert data["diagnostics"] == diagnostics and data["preparation"] == preparation
    assert json.loads(json.dumps(data, allow_nan=False)) == data
    data["objects"][0]["vertices"][0][0] = 99
    data["report"]["surfaces"]["wall"]["physical_element_id"] = "edited"
    assert (model, report, diagnostics, preparation) == original


def test_scene_rejects_relative_coordinates():
    from epsm_core import scene_data

    with pytest.raises(ValueError, match="World"):
        scene_data({"GlobalGeometryRules": {"rules": {"coordinate_system": "Relative"}}})


def _wall_with_openings(ranges):
    """Four-by-three metre wall and explicit one-metre-high opening polygons."""

    def face(points, **fields):
        return dict(
            vertices=[
                dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                for x, y, z in points
            ],
            **fields,
        )

    return {
        "BuildingSurface:Detailed": {"wall": face([[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]])},
        "FenestrationSurface:Detailed": {
            f"window-{index}": face(
                [[left, 0, 1], [right, 0, 1], [right, 0, 2], [left, 0, 2]],
                building_surface_name="wall",
            )
            for index, (left, right) in enumerate(ranges)
        },
    }


def test_scene_rejects_openings_outside_parent_without_clipping():
    from epsm_core import scene_data

    model = _wall_with_openings([(3, 5)])
    original = deepcopy(model)
    with pytest.raises(ValueError, match="[Oo]pening.*outside.*wall"):
        scene_data(model)
    assert model == original


def test_scene_rejects_positive_opening_overlap_without_merging():
    from epsm_core import scene_data

    model = _wall_with_openings([(1, 3), (2, 3.5)])
    original = deepcopy(model)
    with pytest.raises(ValueError, match="[Oo]pening.*overlap.*wall"):
        scene_data(model)
    assert model == original


def test_scene_preserves_adjacent_opening_rings_and_net_area():
    from epsm_core import scene_data

    data = scene_data(_wall_with_openings([(0.5, 2), (2, 3.5)]))
    wall = next(obj for obj in data["objects"] if obj["name"] == "wall")
    assert len(wall["holes"]) == 2
    assert wall["area_m2"] == 12
    assert wall["net_area_m2"] == 9


def test_scene_exports_need_no_files_engine_server_or_browser(monkeypatch, building):
    geometry = GeometrySpec.from_footprint(Footprint.rectangle(12, 8), storeys=2, storey_height_m=3)
    physical = Building.empty(geometry=geometry)
    assert not physical.readiness().ready
    before = physical.to_dict()

    def forbidden(*args, **kwargs):
        raise AssertionError("Scene export must use loaded geometry only")

    for name in ("open", "read_text", "read_bytes", "write_text", "write_bytes", "mkdir"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    monkeypatch.setattr(EnergyPlusCompiler, "__init__", forbidden)

    from epsm_core import geometry_scene_data

    assert geometry.scene() == geometry_scene_data(geometry)
    assert building.scene() == building.geometry.scene(
        facade=building.facade, context=building.context
    )
    scene = physical.scene()
    assert scene["objects"]
    assert all(
        obj["metadata"].get("physical_element_id") in {e.identifier for e in physical.elements}
        for obj in scene["objects"]
        if obj["kind"] == "surface"
    )
    assert physical.to_dict() == before
    json.dumps(scene, allow_nan=False)


def test_physical_scene_requires_geometry_only():
    with pytest.raises(ValueError, match="geometry"):
        Building.empty().scene()


def test_scene_schema_and_source_frame_are_shared_json_contracts():
    from jsonschema import Draft202012Validator

    from epsm_core import scene_schema

    geometry = GeometrySpec.from_footprint(
        Footprint(exterior=((100, 200), (112, 200), (112, 208), (100, 208))),
        storeys=1,
        storey_height_m=3,
        orientation_deg=30,
        source_crs="EPSG:3006",
    )
    physical = Building.empty(identifier="draft", geometry=geometry)
    data = physical.scene()
    schema = scene_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(data)
    assert data["report"]["origin_m"] == [100, 200]
    assert data["report"]["orientation_deg"] == 30
    assert data["report"]["source_crs"] == "EPSG:3006"
    assert data["report"]["building_id"] == "draft"
    assert data["report"]["snapshot_id"] == physical.snapshot().sha256
    schema["properties"]["schema"]["const"] = "edited"
    assert scene_schema()["properties"]["schema"]["const"] == "epsm.scene/1"
    invalid = deepcopy(data)
    invalid["objects"][0]["vertices"][0] = [0, 0]
    assert list(Draft202012Validator(scene_schema()).iter_errors(invalid))
    invalid = deepcopy(data)
    invalid["objects"][0]["id"] = ""
    assert list(Draft202012Validator(scene_schema()).iter_errors(invalid))


def test_core_import_does_not_load_presentation_dependencies():
    subprocess.run(
        [
            __import__("sys").executable,
            "-c",
            "import sys; import epsm_core; "
            "assert not any(n in sys.modules for n in "
            "('epsm_core.viewer', 'epsm_core.notebook', 'epsm_viewer', 'anywidget', 'ipywidgets'))",
        ],
        check=True,
    )
