import math
import shutil

import pytest

import epsm_core.compiler as compiler_module
from epsm_core.compiler import EnergyPlusCompiler
from epsm_core.constructions import bridge_equivalent, internal_mass_halves, solve_insulation
from epsm_core.specs import *
from epsm_core.weather import file_sha256


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


def test_internal_mass_preserves_layers_and_capacity(building, energyplus):
    assembly = building.envelope.wall  # asymmetric multilayer case
    halves = internal_mass_halves(assembly)

    def capacity(layers):
        return sum(
            x.thickness_m * x.material.density_kg_m3 * x.material.specific_heat_j_kgk
            for x in layers
        )

    assert sum(capacity(h.layers) for h in halves) == pytest.approx(capacity(assembly.layers))
    assert halves[0].layers[-1].material == assembly.layers[0].material
    assert halves[1].layers[-1].material == assembly.layers[-1].material
    b = building.updated(
        envelope=building.envelope.updated(intermediate_floor=assembly),
        geometry=building.geometry.updated(zoning=ZoningSpec(mode="whole_building")),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    masses = model["InternalMass"]
    assert len(masses) == 2 * (b.geometry.parts[0].floors - 1)
    total_capacity = 0
    for mass in masses.values():
        assert mass["surface_area"] == b.geometry.footprint_area_m2
        layers = ConstructionSpec.model_validate(
            report.data["constructions"][mass["construction_name"]]["applied"]
        ).layers
        total_capacity += mass["surface_area"] * capacity(layers)
    assert total_capacity == pytest.approx(
        b.geometry.footprint_area_m2 * (b.geometry.parts[0].floors - 1) * capacity(assembly.layers)
    )


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
        geometry=building.geometry.updated(
            zoning=ZoningSpec(mode=zoning), roof=RoofSpec(topology=roof)
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert "Site:GroundTemperature:BuildingSurface" not in model
    assert "Foundation:Kiva" in model
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
        facade=building.facade.updated(overrides=(FacadeOverride(facade_id="main.r0.e0", wwr=0.3),))
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
    b = building.updated(
        envelope=building.envelope.updated(ground_temperature=GroundTemperatureSpec()),
        geometry=building.geometry.updated(
            parts=(
                building.geometry.parts[0].updated(footprint=hole),
                building.geometry.parts[0].updated(identifier="other", footprint=other),
            )
        )
    )
    _, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["footprint_area_m2"] == 900
    assert sum(f["area_m2"] for f in report.data["ground_surfaces"]) == pytest.approx(900)


def test_compile_to_disk(building, energyplus, tmp_path):
    report = EnergyPlusCompiler(energyplus).write(building, tmp_path)
    assert (tmp_path / "model.epJSON").is_file()
    assert len(report.run_id) == 64


def test_compiler_reuses_only_unchanged_weather(monkeypatch, building, energyplus, tmp_path):
    """One compiler reads an unchanged EPW once and notices later file changes."""
    weather_path = tmp_path / "weather.epw"
    shutil.copyfile(building.climate.epw_path, weather_path)
    climate = building.climate.updated(
        epw_path=str(weather_path),
        weather_sha256=file_sha256(weather_path),
    )
    candidate = building.updated(climate=climate)
    actual_reader = compiler_module.climate_from_epw
    reads = []

    def counted_reader(path):
        reads.append(path)
        return actual_reader(path)

    monkeypatch.setattr(compiler_module, "climate_from_epw", counted_reader)
    compiler = EnergyPlusCompiler(energyplus)
    compiler.compile(candidate)
    compiler.compile(candidate)

    assert reads == [weather_path.resolve()]

    with weather_path.open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="EPW checksum differs"):
        compiler.compile(candidate)
    assert reads == [weather_path.resolve(), weather_path.resolve()]
