import copy

import pytest
from epsm_core import EnergyPlusCompiler, GroundTemperatureSpec
from epsm_core.geometry import local_polygons
from epsm_core.specs import Footprint
from epsm_core.surface_checks import properties, validate_surfaces, vertices
from shapely.geometry import Point


@pytest.mark.parametrize("reverse_outer", [False, True])
@pytest.mark.parametrize("reverse_hole", [False, True])
@pytest.mark.parametrize("angle", [0, 37, 181])
def test_courtyard_winding_and_rotation_preserve_outward_faces(
    building, energyplus, reverse_outer, reverse_hole, angle
):
    outer = [(100, 200), (130, 200), (130, 220), (100, 220)]
    hole = [(110, 205), (110, 215), (120, 215), (120, 205)]
    if reverse_outer:
        outer.reverse()
    if reverse_hole:
        hole.reverse()
    part = building.geometry.parts[0].updated(
        footprint=Footprint(exterior=tuple(outer), holes=(tuple(hole),))
    )
    building = building.updated(
        envelope=building.envelope.updated(ground_temperature=GroundTemperatureSpec())
    )
    spec = building.updated(
        geometry=building.geometry.updated(parts=(part,), orientation_deg=angle)
    )
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    polygon = local_polygons(spec.geometry)[0][0]
    assert polygon.area == pytest.approx(500)
    for obj in model["BuildingSurface:Detailed"].values():
        if obj["surface_type"] == "Wall" and obj["outside_boundary_condition"] == "Outdoors":
            v = vertices(obj)
            normal = properties(v)[1]
            mid = v.mean(axis=0)
            assert not polygon.contains(Point(*(mid + normal * 1e-4)[:2]))
            assert polygon.contains(Point(*(mid - normal * 1e-4)[:2]))
    for obj in model["FenestrationSurface:Detailed"].values():
        parent = model["BuildingSurface:Detailed"][obj["building_surface_name"]]
        assert properties(vertices(obj))[1] @ properties(vertices(parent))[1] > 1 - 1e-8


def test_reversed_window_is_rejected_even_when_contained(building, energyplus):
    model, report = EnergyPlusCompiler(energyplus).compile(building)
    model = copy.deepcopy(model)
    obj = next(iter(model["FenestrationSurface:Detailed"].values()))
    for i, p in enumerate(vertices(obj)[::-1], 1):
        for a, v in zip("xyz", p):
            obj[f"vertex_{i}_{a}_coordinate"] = float(v)
    with pytest.raises(ValueError, match="Window normal"):
        validate_surfaces(model, report.data["zones"])
