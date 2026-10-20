"""EnergyPlus-only geometry constraints are available before engine setup."""

from dataclasses import replace

import pytest

from epsm_core import Building, Footprint, Weather, run_building
from epsm_core.building_adapter import to_spec
from epsm_core.specs import ClimateSpec, ZoningSpec


def courtyard_building(*, zoning="per_storey"):
    building = Building(preset="illustrative-reference")
    courtyard = Footprint(
        exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
        holes=(((10, 10), (10, 20), (20, 20), (20, 10)),),
    )
    geometry = building.geometry.updated(
        parts=(building.geometry.parts[0].updated(footprint=courtyard),),
        zoning=ZoningSpec(mode=zoning),
    )
    building.geometry = geometry
    return building


def test_preflight_rejects_courtyard_kiva_but_prescribed_passes_geometry_only():
    from epsm_core import FoundationSpec, GroundTemperatureSpec, preflight_energyplus

    building = courtyard_building()
    climate = ClimateSpec(
        epw_path="unused.epw", weather_sha256="0" * 64, latitude_deg=0,
        longitude_deg=0, elevation_m=0, time_zone_hours=0,
    )
    result = preflight_energyplus(to_spec(building, climate))
    assert not result
    assert any("explicit prescribed temperatures" in issue for issue in result.unsupported)

    prescribed = building.copy()
    prescribed.foundation = FoundationSpec(method="prescribed_temperature")
    prescribed.ground_temperature = GroundTemperatureSpec(
        monthly_temperatures_c=(12.0,) * 12, source="measured-monthly-v1"
    )
    assert preflight_energyplus(to_spec(prescribed, climate))

    ordinary = Building(preset="illustrative-reference")
    assert preflight_energyplus(to_spec(ordinary, climate))


@pytest.mark.energyplus
def test_prescribed_courtyard_compiles_after_preflight(energyplus, synthetic_weather):
    from epsm_core import (
        EnergyPlusCompiler,
        FoundationSpec,
        GroundTemperatureSpec,
        preflight_energyplus,
    )

    building = courtyard_building()
    building.foundation = FoundationSpec(method="prescribed_temperature")
    building.ground_temperature = GroundTemperatureSpec(
        monthly_temperatures_c=(12.0,) * 12, source="measured-monthly-v1"
    )
    spec = to_spec(building, Weather.from_epw(synthetic_weather))
    assert preflight_energyplus(spec)
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert report.data["foundation"]["method"] == "prescribed_temperature"


def test_energyplus_run_preflights_before_creating_runner_or_output(monkeypatch, tmp_path,
                                                                  synthetic_weather):
    import epsm_core.runner as runner

    building = courtyard_building()
    created = []

    class NeverRunner:
        def __init__(self, *args, **kwargs):
            created.append(True)
            raise AssertionError("runner must not be constructed")

    monkeypatch.setattr(runner, "EnergyPlusRunner", NeverRunner)
    monkeypatch.setattr(Weather, "from_epw", lambda *_: (_ for _ in ()).throw(
        AssertionError("unsupported geometry must fail before weather I/O")))
    directory = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="not ready"):
        run_building(building, weather=synthetic_weather, directory=directory)
    assert not created
    assert not directory.exists()


def test_energyplus_footing_layer_limit_fails_before_geometry_or_weather(monkeypatch, tmp_path):
    from epsm_core import ConstructionSpec, LayerSpec, MaterialSpec

    building = Building(preset="illustrative-reference")
    material = MaterialSpec(name="explicit footing concrete", conductivity_w_mk=1.7,
                            density_kg_m3=2300, specific_heat_j_kgk=880)
    footing = ConstructionSpec(layers=(LayerSpec(material=material, thickness_m=.1),) * 11)
    building.foundation = building.foundation.updated(footing_wall=footing)
    assert building.readiness()
    assert building.readiness(engine="epsm_rc")

    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported footing layers must fail before geometry, weather or runner setup")

    monkeypatch.setattr("epsm_core.pipeline.resolve_geometry", forbidden)
    monkeypatch.setattr("epsm_core.preflight._preflight_building_kiva", forbidden)
    monkeypatch.setattr(Weather, "from_epw", forbidden)
    monkeypatch.setattr("epsm_core.runner.EnergyPlusRunner", forbidden)
    readiness = building.readiness(engine="energyplus")
    assert not readiness
    assert any("foundation.footing_wall" in issue and "10 layers" in issue
               for issue in readiness.unsupported)
    directory = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="foundation.footing_wall"):
        run_building(building, weather="unused.epw", directory=directory)
    assert not directory.exists()


def test_whole_building_adapter_preserves_physical_mass_overrides_and_inventory():
    from epsm_data.domain.enums import BuildingElement as Role

    building = Building(preset="illustrative-reference")
    building.geometry = building.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    floor = next(item for item in building.elements if item.role == Role.INTERMEDIATE_FLOOR)
    component = floor.construction.components[0]
    slot = component.layers[0]
    layer = slot.layer
    materials = tuple(replace(item, thickness=item.thickness * 2) for item in layer.materials)
    changed_layer = replace(layer, thickness=layer.thickness * 2, materials=materials)
    changed_component = replace(
        component, layers=(replace(slot, layer=changed_layer), *component.layers[1:])
    )
    construction = replace(
        floor.construction,
        components=(changed_component, *floor.construction.components[1:]),
    )
    building.assign_construction(construction, element_ids=[floor.identifier])
    before = tuple(item.to_dict() for item in building.quantities())
    climate = ClimateSpec(
        epw_path="unused.epw", weather_sha256="0" * 64, latitude_deg=0,
        longitude_deg=0, elevation_m=0, time_zone_hours=0,
    )

    spec = to_spec(building, climate)

    assert spec.internal_mass_constructions
    assert tuple(item.to_dict() for item in building.quantities()) == before
