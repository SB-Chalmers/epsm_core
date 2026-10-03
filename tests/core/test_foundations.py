"""Foundation defaults, migration, perimeter conservation and engine smoke checks."""

import os
from pathlib import Path

import pytest

from epsm_core import EnergyPlusCompiler, FoundationSpec, GroundTemperatureSpec
from epsm_core.failures import CompilationError
from epsm_core.specs import (
    ApartmentLayoutSpec,
    EnvelopeSpec,
    Footprint,
    WindowLayoutSpec,
    ZoningSpec,
)


def test_default_and_legacy_roundtrips(building):
    env = building.envelope
    assert env.foundation.method == "kiva" and env.ground_temperature is None
    legacy = env.updated(ground_temperature=GroundTemperatureSpec())
    assert legacy.foundation.method == "prescribed_temperature"
    old = legacy.model_dump()
    old.pop("foundation")
    assert EnvelopeSpec.model_validate(old) == legacy
    assert EnvelopeSpec.model_validate_json(env.model_dump_json()) == env
    assert EnvelopeSpec.model_validate_json(legacy.model_dump_json()) == legacy
    assert building.updated(envelope=legacy).physical_hash() != building.physical_hash()
    with pytest.raises(ValueError, match="conflicts"):
        env.updated(foundation=FoundationSpec(), ground_temperature=GroundTemperatureSpec())
    with pytest.raises(ValueError, match="requires"):
        env.updated(foundation=FoundationSpec(method="prescribed_temperature"))
    for value in [0, -1, float("nan")]:
        with pytest.raises(ValueError):
            FoundationSpec(soil_conductivity_w_mk=value)


@pytest.mark.parametrize("zoning", ["whole_building", "per_storey", "perimeter_core", "apartments"])
@pytest.mark.parametrize("basement", ["none", "heated", "unheated"])
def test_ground_geometry_and_exterior_perimeter(building, energyplus, zoning, basement):
    geometry = building.geometry.updated(
        zoning=ZoningSpec(mode=zoning, apartments=ApartmentLayoutSpec(max_candidates=1000))
        if zoning == "apartments"
        else ZoningSpec(mode=zoning),
        orientation_deg=45 if zoning == "rotated_apartments" else 0,
        basement_depth_m=0 if basement == "none" else 2.5,
        basement_conditioned=basement == "heated",
    )
    b = building.updated(
        geometry=geometry,
        facade=building.facade.updated(layout=WindowLayoutSpec(mode="wwr")),
        use=building.use.updated(occupancy_category="residential"),
        envelope=building.envelope.updated(
            dwelling_partition=building.envelope.intermediate_floor,
            common_partition=building.envelope.intermediate_floor,
        ),
    )
    compiler = EnergyPlusCompiler(energyplus)
    model, report = compiler.compile(b)
    legacy, lr = compiler.compile(
        b.updated(envelope=b.envelope.updated(ground_temperature=GroundTemperatureSpec()))
    )
    assert "Site:GroundTemperature:BuildingSurface" not in model
    assert report.data["foundation"]["method"] == "kiva"
    assignments = report.data["foundation"]["assignments"]
    assert sum(a["floor_area_m2"] for a in assignments) == pytest.approx(600)
    assert sum(a["exposed_perimeter_m"] for a in assignments) == pytest.approx(100)
    assert report.data["conditioned_floor_area_m2"] == lr.data["conditioned_floor_area_m2"]
    assert report.data["conditioned_volume_m3"] == lr.data["conditioned_volume_m3"]
    assert model["Material"] == legacy["Material"]
    assert model["ZoneInfiltration:DesignFlowRate"] == legacy["ZoneInfiltration:DesignFlowRate"]
    assert model["Construction"] == legacy["Construction"]
    assert all(
        model["BuildingSurface:Detailed"][a["floor"]]["outside_boundary_condition"] == "Foundation"
        for a in assignments
    )


@pytest.mark.parametrize("angle", [0, 45, 90])
def test_apartment_perimeter_is_rotation_invariant(building, energyplus, angle):
    b = building.updated(
        geometry=building.geometry.updated(
            orientation_deg=angle,
            zoning=ZoningSpec(
                mode="apartments", apartments=ApartmentLayoutSpec(max_candidates=1000)
            ),
        ),
        facade=building.facade.updated(layout=WindowLayoutSpec(mode="wwr")),
        use=building.use.updated(occupancy_category="residential"),
        envelope=building.envelope.updated(
            dwelling_partition=building.envelope.intermediate_floor,
            common_partition=building.envelope.intermediate_floor,
        ),
    )
    _, report = EnergyPlusCompiler(energyplus).compile(b)
    assert sum(
        a["exposed_perimeter_m"] for a in report.data["foundation"]["assignments"]
    ) == pytest.approx(100, abs=1e-5)


def test_concave_merge_overrides_and_hash(building, energyplus):
    b = building.updated(
        geometry=building.geometry.updated(
            parts=(building.geometry.parts[0].updated(footprint=Footprint.l_shape(30, 20, 10, 8)),)
        )
    )
    cfg = FoundationSpec(
        exposed_perimeter_fraction=0.5,
        soil_conductivity_w_mk=2.5,
        footing_material=b.envelope.ground.layers[-1].material,
        footing_wall=b.envelope.basement_wall,
    )
    b = b.updated(envelope=b.envelope.updated(foundation=cfg))
    model, r = EnergyPlusCompiler(energyplus).compile(b)
    a = r.data["foundation"]["assignments"][0]
    assert a["floor_area_m2"] == pytest.approx(520)
    assert r.data["surfaces"][a["floor"]]["area_m2"] == pytest.approx(520)
    assert not set(r.data["foundation"]["merged_ground_faces"]) & set(r.data["surfaces"])
    assert a["exposed_perimeter_m"] == pytest.approx(50)
    assert model["Foundation:Kiva:Settings"]["foundation_settings"]["soil_conductivity"] == 2.5
    assert "kiva_footing" in model["Material"]
    assert "kiva_footing_wall" in model["Construction"]
    assert cfg.model_dump(mode="json") == r.data["foundation"]["inputs"]
    assert b.physical_hash() != building.physical_hash()


def test_unsupported_courtyard_and_shallow_boundary(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    hole = Footprint(
        exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
        holes=(((10, 10), (20, 10), (20, 20), (10, 20)),),
    )
    b = building.updated(
        geometry=building.geometry.updated(
            parts=(building.geometry.parts[0].updated(footprint=hole),)
        )
    )
    with pytest.raises(CompilationError, match="holes"):
        compiler.compile(b)
    compiler.compile(
        b.updated(envelope=b.envelope.updated(ground_temperature=GroundTemperatureSpec()))
    )
    b = building.updated(
        geometry=building.geometry.updated(basement_depth_m=2.5),
        envelope=building.envelope.updated(foundation=FoundationSpec(deep_ground_depth_m=2)),
    )
    with pytest.raises(CompilationError, match="below the slab"):
        compiler.compile(b)


@pytest.mark.skipif(
    os.environ.get("EPSM_KIVA_SMOKE") != "1", reason="Explicit EnergyPlus smoke gate"
)
@pytest.mark.parametrize(
    "zoning,basement",
    [
        ("per_storey", "none"),
        ("whole_building", "heated"),
        ("per_storey", "unheated"),
        ("perimeter_core", "none"),
        ("apartments", "none"),
        ("rotated_apartments", "none"),
        ("concave", "none"),
    ],
)
def test_energyplus_smoke(building, energyplus, tmp_path, zoning, basement):
    from epsm_core import EnergyPlusRunner
    from epsm_core.weather import climate_from_epw

    weather = Path(
        os.environ.get(
            "EPSM_KIVA_SMOKE_EPW",
            str(
                Path(__file__).resolve().parents[3]
                / "epsm_workflows/output/archetype-pilot-mf-se02-f-2026-09-30/weather/weather-2018.epw"
            ),
        )
    )
    if not weather.exists():
        pytest.skip("Pinned smoke AMY weather unavailable")
    geometry = building.geometry.updated(
        zoning=(
            ZoningSpec(mode="apartments", apartments=ApartmentLayoutSpec(max_candidates=1000))
            if zoning in {"apartments", "rotated_apartments"}
            else ZoningSpec(mode="per_storey" if zoning == "concave" else zoning)
        ),
        orientation_deg=45 if zoning == "rotated_apartments" else 0,
        basement_depth_m=0 if basement == "none" else 2.5,
        basement_conditioned=basement == "heated",
    )
    if zoning == "concave":
        geometry = geometry.updated(
            parts=(geometry.parts[0].updated(footprint=Footprint.l_shape(30, 20, 10, 8)),)
        )
    b = building.updated(
        facade=building.facade.updated(layout=WindowLayoutSpec(mode="wwr")),
        geometry=geometry,
        climate=climate_from_epw(weather, calendar_year=2018),
        use=building.use.updated(occupancy_category="residential"),
        envelope=building.envelope.updated(
            dwelling_partition=building.envelope.intermediate_floor,
            common_partition=building.envelope.intermediate_floor,
        ),
    )
    runner = EnergyPlusRunner(energyplus=energyplus)
    result = runner.run(b, tmp_path / f"{zoning}-{basement}")
    assert result  # run raises on any unapproved engine warning
