import math

import pytest

from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.constructions import bridge_equivalent, solve_insulation
from epsm_core.specs import *


def test_roundtrip_and_validation(building):
    assert BuildingSpec.model_validate_json(building.model_dump_json()) == building
    assert building.updated(identifier="another").physical_hash() == building.physical_hash()
    with pytest.raises(ValueError):
        building.geometry.updated(floors=0)
    with pytest.raises(ValueError):
        building.airflow.updated(topology="F")
    with pytest.raises(ValueError):
        Footprint(exterior=((0, 0), (10, 10), (0, 10), (10, 0)))


def test_u_solver(building):
    assembly = solve_insulation(building.envelope.wall, 0, 0.4)
    assert assembly.u_value_w_m2k == pytest.approx(0.4)
    assert bridge_equivalent(assembly, 0.25).u_value_w_m2k == pytest.approx(0.5)
    with pytest.raises(ValueError):
        solve_insulation(assembly, 0, 10)


def test_shape_utilities():
    l_shape = Footprint.l_shape(30, 20, 10, 8)
    u_shape = Footprint.u_shape(30, 20, 10, 8)
    assert l_shape.area_m2 == u_shape.area_m2 == 520
    assert l_shape.scaled_to_area(1000).area_m2 == pytest.approx(1000)
    assert u_shape.perimeter_m == 116
    with pytest.raises(ValueError):
        Footprint.u_shape(30, 20, 30, 10)


@pytest.mark.parametrize("zoning", ["whole_building", "per_storey"])
@pytest.mark.parametrize("roof", ["compact", "cold_attic"])
def test_model(building, energyplus, zoning, roof):
    b = building.updated(
        geometry=building.geometry.updated(zoning=zoning),
        envelope=building.envelope.updated(roof_topology=roof),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert "Site:GroundTemperature:BuildingSurface" not in model
    assert report.data["conditioned_floor_area_m2"] == 1800
    assert (
        sum(z["floor_area_m2"] for z in report.data["zones"].values() if z["conditioned"]) == 1800
    )
    expected = "top"
    assert any(
        s["construction_name"] == expected for s in model["BuildingSurface:Detailed"].values()
    )
    assert len(model["ZoneInfiltration:DesignFlowRate"]) == (1 if zoning == "whole_building" else 3)


def test_rotation(building, energyplus):
    b = building.updated(
        facade=building.facade.updated(overrides=(FacadeOverride(facade_id="c0.r0.e0", wwr=0.3),))
    )
    compiler = EnergyPlusCompiler(energyplus)
    _, r0 = compiler.compile(b)
    _, r1 = compiler.compile(b.updated(geometry=b.geometry.updated(orientation_deg=90)))
    first, second = r0.data["facades"], r1.data["facades"]
    assert [x["local_wwr"] for x in first] == [x["local_wwr"] for x in second]
    assert first[0]["cardinal"] != second[0]["cardinal"]
    assert math.isclose(
        sum(x["window_area_m2"] for x in first), sum(x["window_area_m2"] for x in second)
    )


def test_holes_multipolygon(building, energyplus):
    hole = Footprint(
        exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
        holes=(((10, 10), (20, 10), (20, 20), (10, 20)),),
    )
    other = Footprint(exterior=((50, 0), (60, 0), (60, 10), (50, 10)))
    b = building.updated(geometry=building.geometry.updated(footprints=(hole, other)))
    _, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["footprint_area_m2"] == 900
    assert sum(f["area_m2"] for f in report.data["foundations"]) == pytest.approx(900)
    assert sum(f["exposed_perimeter_m"] for f in report.data["foundations"]) == pytest.approx(200)


def test_compile_to_disk(building, energyplus, tmp_path):
    report = EnergyPlusCompiler(energyplus).write(building, tmp_path)
    assert (tmp_path / "model.epJSON").is_file()
    assert len(report.run_id) == 64
