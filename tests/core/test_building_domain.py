"""Cross-layer physical authoring, material lineage and numerical bridge invariants."""

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from epsm_data import (
    ConstructionOperation,
    RenovationMeasure,
    SystemOperation,
    reference_hvac_template,
)
from epsm_data.domain import LayerMaterial
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    BuildingSnapshot,
    CompilerSettings,
    EnergyPlusCompiler,
    Footprint,
    Weather,
    ZoningSpec,
)


def measure(operation, *targets):
    return RenovationMeasure("test.measure", "envelope", "Test", "Test intervention", "wall",
                             operations=(operation,), target_element_ids=targets)


def wall(building):
    return next(e for e in building.elements if e.role == Role.EXT_WALL)


def test_gradual_authoring_and_readiness():
    empty = Building.empty()
    assert not empty.readiness("geometry")
    assert not empty.readiness("energy")
    building = Building.from_footprint(Footprint.rectangle(10, 8), storeys=2, storey_height_m=3)
    assert building.readiness("geometry")
    assert not building.readiness("quantities")
    with pytest.raises(ValueError, match="not ready"):
        building.quantities()
    reference = Building()
    assert reference.readiness(engine="energyplus")
    assert reference.readiness(engine="epsm_rc")
    complete = Building.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        construction_set=reference.construction_set, facade=reference.facade,
        hvac=reference.hvac, operation=reference.operation)
    assert complete.readiness()
    assert "illustrative-reference" in repr(reference)
    with pytest.raises(ValueError):
        reference.geometry = {"parts": []}
    assert reference.readiness()


def test_assignment_snapshot_and_subclass_isolation():
    class AppBuilding(Building):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.results = []
            self.assessment = {"horizon": 50}

        def _copy_runtime_configuration_to(self, child):
            child.assessment = dict(self.assessment)

    building = AppBuilding()
    building.results.append("old")
    building.assessment["horizon"] = 60
    snapshot = building.snapshot()
    child = building.copy()
    assert isinstance(child, AppBuilding) and child.results == []
    assert child.assessment == {"horizon": 60}
    assert child.assessment is not building.assessment
    assert snapshot.sha256 == building.snapshot().sha256 == child.snapshot().sha256
    data = snapshot.to_dict()
    data["elements"][0]["area_m2"] = 999
    assert snapshot.to_dict()["elements"][0]["area_m2"] != 999
    assert "results" not in snapshot.to_dict() and "assessment" not in snapshot.to_dict()
    assert BuildingSnapshot.from_dict(snapshot.to_dict()).sha256 == snapshot.sha256
    with pytest.raises(FrozenInstanceError):
        snapshot._json = "{}"
    child.identifier = "child"
    assert building.identifier == "building"


def test_physical_inventory_is_independent_of_zones_and_preserves_material_fractions():
    building = Building()
    initial = building.quantities()
    building.geometry = building.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    assert building.quantities() == initial
    selected = wall(building)
    component = selected.construction.components[0]
    layer = component.layers[0].layer
    concrete = component.layers[-1].layer.materials[0].material
    mixed = replace(layer, is_composite=True, materials=(
        LayerMaterial(layer.materials[0].material, .25, layer.thickness),
        LayerMaterial(concrete, .75, layer.thickness),
    ))
    changed_component = replace(component, layers=(replace(component.layers[0], layer=mixed),))
    building.assign_construction(replace(selected.construction, components=(changed_component,)),
                                 element_ids=(selected.identifier,))
    quantities = [q for q in building.quantities() if q.element_id == selected.identifier]
    assert len(quantities) == 2
    assert sum(q.volume_m3 for q in quantities) == pytest.approx(selected.area_m2 * layer.thickness)
    assert quantities[1].mass_kg == pytest.approx(selected.area_m2 * .75 * layer.thickness * concrete.density)
    assert quantities[0].material_id in building.quantities().by_material()


def test_targeted_like_for_like_replacement_and_atomic_failure():
    building = Building()
    selected = wall(building)
    before = building.snapshot()
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    child = building.renovate(measure(operation, selected.identifier))
    flow = child.material_flows[-1]
    assert flow.installed and flow.removed and flow.retained
    assert {q.element_id for q in flow.installed} == {selected.identifier}
    assert {q.element_id for q in flow.removed} == {selected.identifier}
    assert not ({q.occurrence_id for q in flow.installed} & {q.occurrence_id for q in flow.removed})
    assert sum(q.mass_kg or 0 for q in flow.installed) == pytest.approx(
        sum(q.mass_kg or 0 for q in flow.removed))
    assert building.snapshot().sha256 == before.sha256 and not building.stages
    assert child.parent_snapshot_id == before.sha256
    with pytest.raises(ValueError, match="unknown"):
        building.renovate(measure(operation, selected.identifier),
                          replace(measure(operation, "missing"), measure_id="second.bad"))
    assert building.snapshot().sha256 == before.sha256
    restored = Building.from_snapshot(child.snapshot()).restore_lineage(child.lineage_to_dict())
    assert restored.material_flows == child.material_flows
    assert restored.stages == child.stages


def test_added_component_retains_existing_occurrences():
    building = Building()
    selected = wall(building)
    component = selected.construction.components[0]
    addition = replace(component, name="new outside insulation", layers=component.layers[:1])
    child = building.renovate(measure(ConstructionOperation(
        "add_component", selected.role, component=addition, position=0), selected.identifier))
    flow = child.material_flows[-1]
    assert len(flow.installed) == 1 and not flow.removed
    assert len(flow.retained) == len(building.quantities())


def test_renovation_prerequisites_and_symmetric_incompatibility():
    building = Building()
    selected = wall(building)
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    first = replace(measure(operation, selected.identifier), measure_id="first")
    second = replace(first, measure_id="second", requires_measure_ids=("first",))
    with pytest.raises(ValueError, match="prerequisites"):
        building.renovate(second)
    with pytest.raises(ValueError, match="prerequisites"):
        building.renovate(second, first)
    with pytest.raises(ValueError, match="repeat"):
        building.renovate(first, first)
    assert building.renovate(first, second).stages[-1].measure_ids == ("first", "second")
    assert len(building.renovate(first).renovate(second).stages) == 2
    exclusive = replace(first, incompatible_measure_ids=("second",))
    with pytest.raises(ValueError, match="[Ii]ncompatible"):
        building.renovate(exclusive, second)
    child = building.renovate(exclusive)
    restored = Building.from_snapshot(child.snapshot()).restore_lineage(child.lineage_to_dict())
    with pytest.raises(ValueError, match="incompatible"):
        restored.renovate(second)
    assert not building.stages


def test_system_renovation_tracks_count_and_preserves_other_equipment():
    building = Building()
    template = reference_hvac_template()
    values = template.to_dict()["values"]
    values["equipment"] = [e for e in values["equipment"] if e["identifier"] == "ventilation"]
    template = template.with_changes(values=values)
    child = building.renovate(SystemOperation("replace_hvac", template))
    flow = child.material_flows[-1]
    assert [(q.material_id, q.count) for q in flow.installed] == [("reference.ftx", 1)]
    assert [(q.material_id, q.count) for q in flow.removed] == [("reference.ftx", 1)]
    assert any(q.material_id == "reference.district_heat_substation" for q in flow.retained)
    assert child.hvac.delivery == building.hvac.delivery


def test_targeted_construction_reaches_emitted_surfaces(synthetic_weather):
    building = Building()
    selected = wall(building)
    component = selected.construction.components[0]
    changed_layer = replace(component.layers[0].layer,
        thickness=component.layers[0].layer.thickness * 2,
        materials=tuple(replace(s, thickness=s.thickness * 2)
                        for s in component.layers[0].layer.materials))
    changed = replace(selected.construction, components=(replace(component,
        layers=(replace(component.layers[0], layer=changed_layer), *component.layers[1:])),))
    child = building.renovate(measure(ConstructionOperation(
        "replace_element", selected.role, element=changed), selected.identifier))
    spec = child.to_spec(Weather.from_epw(synthetic_weather))
    assert spec.surface_constructions
    from epsm_core import quantity_takeoff

    assert sum(q.mass_kg or 0 for q in quantity_takeoff(spec)) == pytest.approx(
        sum(q.mass_kg or 0 for q in child.quantities()))
    # Exercise the actual emitter and geometry checks without installing/running an engine.
    compiler = object.__new__(EnergyPlusCompiler)
    compiler.settings = CompilerSettings()
    compiler.validator = SimpleNamespace(iter_errors=lambda _: ())
    compiler._verified_weather = lambda _: spec.climate
    compiler.compiler_hash = compiler.engine_hash = compiler.schema_hash = "0" * 64
    compiler.version = "test-emitter-only"
    model, report = compiler.compile(spec)
    for name in spec.surface_constructions:
        emitted = model["BuildingSurface:Detailed"][name]["construction_name"]
        assert emitted.startswith("physical_override_")
    assert report.data["conditioned_floor_area_m2"] == pytest.approx(720)


def test_weather_fingerprint_detects_mutation(synthetic_weather, tmp_path):
    path = tmp_path / "weather.epw"
    path.write_bytes(synthetic_weather.read_bytes())
    weather = Weather.from_epw(path)
    weather.validate()
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed"):
        weather.validate()


def test_rc_readiness_reports_facade_override_shading():
    from epsm_core import FacadeOverride, OverhangSpec

    building = Building()
    selected = wall(building)
    building.facade = building.facade.updated(overrides=(FacadeOverride(
        facade_id=selected.facade_id, overhang=OverhangSpec(depth_m=1)),))
    assert not building.readiness(engine="epsm_rc")
    assert building.readiness(engine="energyplus")


def test_thermal_bridge_preserves_zero_window_overrides(synthetic_weather):
    from epsm_core import FacadeOverride, OverhangSpec
    from epsm_core.pipeline import resolve_geometry

    building = Building()
    selected = wall(building)
    building.facade = building.facade.updated(overrides=(FacadeOverride(
        facade_id=selected.facade_id, storey=selected.storey, wwr=0,
        overhang=OverhangSpec(depth_m=1)),))
    spec = building.to_spec(Weather.from_epw(synthetic_weather))
    assert spec.facade.value_for("wwr", selected.facade_id, selected.storey) == 0
    assert spec.facade.value_for("overhang", selected.facade_id, selected.storey).depth_m == 1
    resolved = resolve_geometry(spec, panelize=True)
    physical_glazing = sum(e.area_m2 for e in building.elements if e.role == Role.WINDOW)
    assert sum(opening.area for opening in resolved.openings) == pytest.approx(physical_glazing)


@pytest.mark.parametrize("changes", [
    {"area_m2": 99}, {"part_id": "unknown"}, {"facade_id": "unknown"},
    {"storey": 99}, {"elevation_m": 99}, {"identifier": "unknown"},
])
def test_energy_readiness_rejects_physical_metadata_differing_from_geometry(changes):
    building = Building()
    selected = wall(building)
    building.elements = tuple(replace(e, **changes) if e.id == selected.id else e
                              for e in building.elements)
    assert building.readiness("quantities")
    assert not building.readiness(engine="energyplus")
    assert not building.readiness(engine="epsm_rc")
    assert any("physical geometry" in issue for issue in building.readiness().unsupported)


def test_energy_readiness_rejects_missing_physical_element():
    building = Building()
    building.elements = building.elements[1:]
    assert not building.readiness(engine="energyplus")


def test_layered_window_supports_quantities_but_reports_thermal_limit(synthetic_weather):
    building = Building()
    opaque = wall(building).construction
    layered_window = replace(opaque, application=Role.WINDOW, components=tuple(
        replace(c, application=Role.WINDOW) for c in opaque.components))
    building.assign_construction(layered_window)
    assert building.readiness("quantities")
    assert building.quantities()
    for engine in ("energyplus", "epsm_rc"):
        readiness = building.readiness(engine=engine)
        assert not readiness
        assert any("layered window" in issue for issue in readiness.unsupported)
    with pytest.raises(ValueError, match="layered window"):
        building.to_spec(Weather.from_epw(synthetic_weather))
