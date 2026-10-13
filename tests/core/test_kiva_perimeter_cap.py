"""Kiva's reported exposed perimeter must fit the emitted floor boundary."""

import json
from pathlib import Path

from shapely.geometry import Polygon

from epsm_core import EnergyPlusCompiler, GeometrySpec

OFFICE_GEOMETRY = Path(__file__).parent / "fixtures/kiva_office_geometry.json"


def test_exposed_perimeter_is_capped_to_emitted_floor(building, energyplus):
    geometry = GeometrySpec.model_validate(json.loads(OFFICE_GEOMETRY.read_text()))
    model, report = EnergyPlusCompiler(energyplus).compile(building.updated(geometry=geometry))
    assert report.data["validation"]["status"] == "passed"
    for obj in model["SurfaceProperty:ExposedFoundationPerimeter"].values():
        floor = model["BuildingSurface:Detailed"][obj["surface_name"]]
        outline = Polygon(
            (v["vertex_x_coordinate"], v["vertex_y_coordinate"])
            for v in floor["vertices"]
        )
        assert obj["total_exposed_perimeter"] <= outline.length + 1e-8
