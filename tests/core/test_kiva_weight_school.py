"""Tiny wall/perimeter differences must not perturb Kiva instance weights."""

import json
from math import hypot
from pathlib import Path

import pytest

from epsm_core import EnergyPlusCompiler, GeometrySpec

GEOMETRY = Path(__file__).parent / "fixtures/kiva_school_geometry.json"


def test_basement_wall_weights_follow_emitted_edges(building, energyplus):
    geometry = GeometrySpec.model_validate(json.loads(GEOMETRY.read_text()))
    model, _ = EnergyPlusCompiler(energyplus).compile(building.updated(geometry=geometry))
    floor_name = "part_1_basement_-1_floor_0"
    exposed = model["SurfaceProperty:ExposedFoundationPerimeter"][floor_name + "_perimeter"][
        "total_exposed_perimeter"
    ]
    walls = [
        obj
        for obj in model["BuildingSurface:Detailed"].values()
        if obj["zone_name"] == "part_1_basement_-1"
        and obj["surface_type"] == "Wall"
        and obj["outside_boundary_condition"] == "Foundation"
    ]
    length = 0.0
    for wall in walls:
        xy = [(v["vertex_x_coordinate"], v["vertex_y_coordinate"]) for v in wall["vertices"]]
        length += max(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(xy, xy[1:] + xy[:1]))
    assert walls
    assert exposed == pytest.approx(length, abs=1e-8)
