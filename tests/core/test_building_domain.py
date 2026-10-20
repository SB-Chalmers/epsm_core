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
    reference = Building(preset="illustrative-reference")
    assert reference.readiness(engine="energyplus")
    assert reference.readiness(engine="epsm_rc")
    complete = Building.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        construction_set=reference.construction_set, facade=reference.facade,
        hvac=reference.hvac, operation=reference.operation,
        foundation=reference.foundation,
        thermal_bridge_uplift_fraction=reference.thermal_bridge_uplift_fraction,
        load_reference_area_policy=reference.load_reference_area_policy)
    assert complete.readiness()
    assert "illustrative-reference" in repr(reference)
    with pytest.raises(ValueError):
        reference.geometry = {"parts": []}
    assert reference.readiness()


def test_operation_assignment_preserves_public_domain_interface():
    from epsm_core import OperationProfile

    building = Building(preset="illustrative-reference")
    assert isinstance(building.operation, OperationProfile)
    changed = building.operation.with_changes(equipment_gain_w_m2=10)
    building.operation = changed
    assert isinstance(building.operation, OperationProfile)
    assert building.operation.equipment_gain_w_m2 == 10
    assert building.copy().operation.with_changes(equipment_gain_w_m2=5).equipment_gain_w_m2 == 5
    before = building.operation
    with pytest.raises(ValueError):
        building.operation = building.operation.model_dump() | {"equipment_gain_w_m2": -1}
    assert building.operation == before


@pytest.mark.parametrize("label", ["x" * 500, "'\\\n\x00\u2028\u200b\U0001f600" * 80],
                         ids=("long", "escaped-unicode"))
def test_domain_representations_are_bounded_and_do_not_inspect_or_do_io(
        label, synthetic_weather, monkeypatch):
    from epsm_core import Equipment, ScheduleSpec

    building = Building(preset="illustrative-reference", identifier=label)
    selected = wall(building)
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    child = building.renovate(operation)
    child.operation = child.operation.updated(heating_setpoint=ScheduleSpec.constant(22))
    snapshot = child.snapshot()
    inventory = child.quantities()
    weather = Weather.from_epw(synthetic_weather)
    objects = [building, Building.empty(identifier=label), snapshot, child.stages[0],
               child.authoring_links[0], child.hvac, child.operation, child.readiness(),
               Equipment(label, label), replace(selected, identifier=label),
               inventory, inventory[0], child.material_flows[0], weather]

    def forbidden(*args, **kwargs):
        pytest.fail("Representation must not calculate state or access external resources")

    for name in ("snapshot", "quantities", "readiness"):
        monkeypatch.setattr(Building, name, forbidden)
    monkeypatch.setattr(BuildingSnapshot, "to_dict", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("pathlib.Path.open", forbidden)
    monkeypatch.setattr("epsm_core.weather.file_sha256", forbidden)
    for value in objects:
        for render in (repr, str):
            text = render(value)
            assert len(text) <= 160
            assert "\n" not in text and "\r" not in text and "\x00" not in text
            assert type(value).__name__ in text
    assert building.identifier == label


def test_assignment_snapshot_and_subclass_isolation():
    class AppBuilding(Building):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.results = []
            self.assessment = {"horizon": 50}

        def _copy_runtime_configuration_to(self, child):
            child.assessment = dict(self.assessment)

    building = AppBuilding(preset="illustrative-reference")
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
    building = Building(preset="illustrative-reference")
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
    building = Building(preset="illustrative-reference")
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
    building = Building(preset="illustrative-reference")
    selected = wall(building)
    component = selected.construction.components[0]
    addition = replace(component, name="new outside insulation", layers=component.layers[:1])
    child = building.renovate(measure(ConstructionOperation(
        "add_component", selected.role, component=addition, position=0), selected.identifier))
    flow = child.material_flows[-1]
    assert len(flow.installed) == 1 and not flow.removed
    assert len(flow.retained) == len(building.quantities())


def test_authoring_between_renovations_keeps_roundtrippable_history():
    from epsm_core import ScheduleSpec

    baseline = Building(preset="illustrative-reference")
    selected = wall(baseline)
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    child = baseline.renovate(operation)
    original_after = child.stages[-1].after
    child.operation = child.operation.updated(heating_setpoint=ScheduleSpec.constant(22))
    authored = child.snapshot()
    assert len(child.authoring_links) == 1
    assert child.authoring_links[0].before == original_after
    assert child.authoring_links[0].after == authored
    assert not child.material_history_requirements
    # A saved current authoring edit and an edit between two stages both roundtrip.
    current = Building.from_snapshot(authored).restore_lineage(child.lineage_to_dict())
    assert current.authoring_links == child.authoring_links
    grandchild = child.renovate(operation)
    assert len(grandchild.stages) == 2
    assert len(grandchild.authoring_links) == 1
    assert grandchild.stages[0].after == original_after
    assert grandchild.stages[1].before == authored
    restored = Building.from_snapshot(grandchild.snapshot()).restore_lineage(
        grandchild.lineage_to_dict())
    assert restored.stages == grandchild.stages
    assert restored.authoring_links == grandchild.authoring_links
    assert not restored.material_history_requirements


def test_material_authoring_changes_require_resolution_without_inventing_flows():
    baseline = Building(preset="illustrative-reference")
    selected = wall(baseline)
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    child = baseline.renovate(operation)
    original_flows = child.material_flows
    child.assign_construction(selected.construction, element_ids=(selected.identifier,))
    assert child.material_flows == original_flows
    assert child.material_history_requirements
    assert child.authoring_links[0].changes_material_inventory
    restored = Building.from_snapshot(child.snapshot()).restore_lineage(child.lineage_to_dict())
    assert restored.material_history_requirements == child.material_history_requirements
    assert restored.material_flows == original_flows
    grandchild = child.renovate(operation)
    assert len(grandchild.stages) == 2
    assert grandchild.material_history_requirements == child.material_history_requirements
    assert grandchild.authoring_links[0].after == grandchild.stages[1].before
    restored = Building.from_snapshot(grandchild.snapshot()).restore_lineage(
        grandchild.lineage_to_dict())
    assert restored.material_history_requirements == grandchild.material_history_requirements


def test_lineage_rejects_missing_authoring_links_and_preserves_previous_state():
    from epsm_core import ScheduleSpec

    baseline = Building(preset="illustrative-reference")
    selected = wall(baseline)
    operation = ConstructionOperation("replace_element", selected.role,
                                      element=selected.construction)
    child = baseline.renovate(operation)
    child.operation = child.operation.updated(heating_setpoint=ScheduleSpec.constant(22))
    child = child.renovate(operation)
    invalid = child.lineage_to_dict()
    invalid["authoring_links"] = []
    before = child.lineage_to_dict()
    with pytest.raises(ValueError, match="authoring link"):
        child.restore_lineage(invalid)
    assert child.lineage_to_dict() == before


def test_renovation_prerequisites_and_symmetric_incompatibility():
    building = Building(preset="illustrative-reference")
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
    building = Building(preset="illustrative-reference")
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


def test_equipment_unknown_area_stays_unknown_in_inventory_and_aggregation():
    inventory = Building(preset="illustrative-reference").quantities()
    equipment = [row for row in inventory if row.kind == "equipment"]
    assert equipment
    for row in equipment:
        assert row.count == 1
        assert row.area_m2 is None
        assert row.volume_m3 is None and row.mass_kg is None
        aggregate = inventory.by_material()[row.material_id]
        assert aggregate["area_m2"] is None
        assert not aggregate["complete"]


def test_targeted_construction_reaches_emitted_surfaces(synthetic_weather):
    building = Building(preset="illustrative-reference")
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


def test_rc_readiness_accepts_context_for_hourly_horizon_method():
    from epsm_core.specs import ContextBuilding, ContextSpec

    building = Building(preset="illustrative-reference")
    building.context = ContextSpec(buildings=(ContextBuilding(
        identifier="neighbour", height_m=15,
        footprints=(Footprint(exterior=((-5, -20), (25, -20), (25, -10), (-5, -10))),),
    ),))
    before = building.snapshot().sha256
    # Older RC adapters must keep rejecting context instead of ignoring it.
    assert not building.readiness(engine="epsm_rc").ready
    assert building.readiness(engine="epsm_rc", rc_context_shading=True).ready
    assert building.snapshot().sha256 == before


def test_rc_readiness_reports_facade_override_shading():
    from epsm_core import FacadeOverride, OverhangSpec

    building = Building(preset="illustrative-reference")
    selected = wall(building)
    building.facade = building.facade.updated(overrides=(FacadeOverride(
        facade_id=selected.facade_id, overhang=OverhangSpec(depth_m=1)),))
    assert not building.readiness(engine="epsm_rc")
    assert building.readiness(engine="energyplus")


def test_thermal_bridge_preserves_zero_window_overrides(synthetic_weather):
    from epsm_core import FacadeOverride, OverhangSpec
    from epsm_core.pipeline import resolve_geometry

    building = Building(preset="illustrative-reference")
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
    building = Building(preset="illustrative-reference")
    selected = wall(building)
    building.elements = tuple(replace(e, **changes) if e.id == selected.id else e
                              for e in building.elements)
    assert building.readiness("quantities")
    assert not building.readiness(engine="energyplus")
    assert not building.readiness(engine="epsm_rc")
    assert any("physical geometry" in issue for issue in building.readiness().unsupported)


def test_energy_readiness_rejects_missing_physical_element():
    building = Building(preset="illustrative-reference")
    building.elements = building.elements[1:]
    assert not building.readiness(engine="energyplus")


def test_layered_window_supports_quantities_but_reports_thermal_limit(synthetic_weather):
    building = Building(preset="illustrative-reference")
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
