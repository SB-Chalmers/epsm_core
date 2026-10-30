"""Material-backed U targets preserve physical identity and authoring history."""

import json

import pytest
from epsm_data import ConstructionOperation
from epsm_data.domain import LayerMaterial
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    BuildingSnapshot,
    ConstructionSpec,
    Weather,
    solve_element_insulation,
    thermal_construction,
)


def wall(building):
    return next(e for e in building.elements if e.role == Role.EXT_WALL)


def composite_wall():
    original = wall(Building(preset="illustrative-reference")).construction
    component = original.components[0]
    insulation, concrete = component.layers
    layer = insulation.layer.with_changes(
        materials=(LayerMaterial(insulation.layer.materials[0].material, .8, .15),
                   LayerMaterial(concrete.layer.materials[0].material, .2, .15)),
        is_composite=True)
    # Select by component name and zero-based layer index, not flattened index
    # or LayerSlot.position. An earlier component remains untouched.
    first = component.with_changes(name="outer", layers=(concrete,))
    selected = component.with_changes(name="insulation", layers=(
        insulation.with_changes(layer=layer, position=7),))
    return original.with_changes(components=(first, selected))


def test_solve_preserves_composite_material_graph_and_untouched_components():
    original = composite_wall()
    before = thermal_construction(original)
    solved = solve_element_insulation(original, "insulation", 0, .3)
    assert thermal_construction(solved).u_value_w_m2k == pytest.approx(.3)
    assert thermal_construction(original) == before
    assert solved.components[0] == original.components[0]
    assert (solved.name, solved.archetype, solved.age, solved.application) == (
        original.name, original.archetype, original.age, original.application)
    old = original.components[1].layers[0]
    new = solved.components[1].layers[0]
    assert new.position == old.position == 7
    assert (new.layer.name, new.layer.layer_code, new.layer.is_composite) == (
        old.layer.name, old.layer.layer_code, True)
    assert [s.material for s in new.layer.materials] == [s.material for s in old.layer.materials]
    assert [s.area_fraction for s in new.layer.materials] == [.8, .2]
    assert all(s.thickness == new.layer.thickness for s in new.layer.materials)
    assert new.layer.thickness != old.layer.thickness


def test_target_uses_existing_core_reporting_films_for_internal_constructions():
    building = Building(preset="illustrative-reference")
    element = building.construction_set.elements[Role.INTERMEDIATE_FLOOR]
    solved = solve_element_insulation(element, element.components[0].name, 0, 1)
    films = thermal_construction(element).surface_resistance_m2k_w
    assert thermal_construction(solved).surface_resistance_m2k_w == films
    assert thermal_construction(solved).u_value_w_m2k == pytest.approx(1)
    # Data reports its role-specific films; it is not the Core reporting target.
    assert solved.u_value != pytest.approx(1)


@pytest.mark.parametrize("kwargs,match", [
    ({"target_u_w_m2k": 0}, "positive"),
    ({"target_u_w_m2k": float("nan")}, "finite"),
    ({"target_u_w_m2k": float("inf")}, "finite"),
    ({"target_u_w_m2k": True}, "positive"),
    ({"layer_index": -1}, "layer_index"),
    ({"layer_index": True}, "layer_index"),
    ({"layer_index": 1.0}, "layer_index"),
    ({"layer_index": 2}, "layer_index"),
    ({"component_name": "missing"}, "component"),
    ({"component_name": ""}, "component"),
    ({"min_thickness_m": 0}, "positive"),
    ({"max_thickness_m": float("inf")}, "finite"),
    ({"min_thickness_m": .2, "max_thickness_m": .1}, "bounds"),
    ({"target_u_w_m2k": 10}, "Infeasible"),
    ({"max_thickness_m": .01}, "Infeasible"),
])
def test_invalid_targets_and_selectors_fail_without_changing_input(kwargs, match):
    original = composite_wall()
    before = thermal_construction(original)
    arguments = {"component_name": "insulation", "layer_index": 0,
                 "target_u_w_m2k": .3, **kwargs}
    with pytest.raises(ValueError, match=match):
        solve_element_insulation(original, **arguments)
    assert thermal_construction(original) == before


def test_unsupported_windows_and_unequal_depths_are_rejected():
    building = Building(preset="illustrative-reference")
    with pytest.raises(ValueError, match="layered Element"):
        solve_element_insulation(building.construction_set.elements[Role.WINDOW], "x", 0, .3)
    original = composite_wall()
    layered_window = original.with_changes(application=Role.WINDOW, components=tuple(
        component.with_changes(application=Role.WINDOW) for component in original.components))
    with pytest.raises(ValueError, match="non-window"):
        solve_element_insulation(layered_window, "insulation", 0, .3)
    component = original.components[0]
    slot = component.layers[0]
    layer = slot.layer.with_changes(materials=(
        slot.layer.materials[0].with_changes(thickness=.1),))
    unsupported = original.with_changes(components=(
        component.with_changes(layers=(slot.with_changes(layer=layer),)),
        original.components[1]))
    with pytest.raises(ValueError, match="equal parallel path depths"):
        solve_element_insulation(unsupported, "insulation", 0, .3)


def test_building_assignment_preserves_occurrences_and_updates_actual_quantities():
    building = Building(preset="illustrative-reference")
    selected = wall(building)
    building.assign_construction(composite_wall(), element_ids=(selected.identifier,))
    before = building.snapshot()
    original = next(e for e in building.elements if e.identifier == selected.identifier)
    defaults = building.construction_set
    old_quantities = {q.occurrence_id: q for q in building.quantities()}
    returned = building.assign_element_u_value(.3, component_name="insulation", layer_index=0,
                                             element_ids=(selected.identifier,))
    assert returned is building
    after = next(e for e in building.elements if e.identifier == selected.identifier)
    assert after.component_ids == original.component_ids
    assert building.construction_set == defaults
    assert building.stages == ()
    assert building.material_flows == ()
    assert building.authoring_links == ()
    assert before.sha256 != building.snapshot().sha256
    assert before.to_building().elements == tuple(
        original if e.identifier == original.identifier else e for e in building.elements)
    quantities = {q.occurrence_id: q for q in building.quantities()}
    assert quantities.keys() == old_quantities.keys()
    for key, quantity in quantities.items():
        assert quantity.material_id == old_quantities[key].material_id
        if quantity.element_id != selected.identifier or quantity.component_id != after.component_ids[1]:
            assert quantity == old_quantities[key]
    layer = after.construction.components[1].layers[0].layer
    selected_quantities = [q for q in quantities.values() if q.element_id == selected.identifier
                           and q.component_id == after.component_ids[1]]
    assert len(selected_quantities) == 2
    assert sum(q.volume_m3 for q in selected_quantities) == pytest.approx(
        after.area_m2 * layer.thickness)
    for quantity, share in zip(selected_quantities, layer.materials):
        assert quantity.mass_kg == pytest.approx(
            after.area_m2 * layer.thickness * share.area_fraction * share.material.density)
    restored = BuildingSnapshot.from_dict(json.loads(json.dumps(building.snapshot().to_dict())))
    assert restored.sha256 == building.snapshot().sha256
    restored_wall = next(e for e in restored.to_building().elements
                         if e.identifier == selected.identifier)
    assert thermal_construction(restored_wall.construction).u_value_w_m2k == pytest.approx(.3)
    assert restored.quantities() == building.quantities()


def test_multi_element_assignment_is_atomic_when_a_later_solve_fails():
    building = Building(preset="illustrative-reference")
    first, second = [e for e in building.elements if e.role == Role.EXT_WALL][:2]
    construction = first.construction
    component = construction.components[0]
    slot = component.layers[1]
    thick_layer = slot.layer.with_changes(thickness=10, materials=tuple(
        share.with_changes(thickness=10) for share in slot.layer.materials))
    impossible = construction.with_changes(components=(component.with_changes(layers=(
        component.layers[0], slot.with_changes(layer=thick_layer))),))
    building.assign_construction(impossible, element_ids=(second.identifier,))
    before = building.snapshot()
    with pytest.raises(ValueError, match="Infeasible"):
        building.assign_element_u_value(.3, component_name=component.name, layer_index=0,
                                       element_ids=(first.identifier, second.identifier))
    assert building.snapshot().sha256 == before.sha256


def test_resolved_engine_inputs_use_the_solved_physical_assignment(synthetic_weather):
    building = Building(preset="illustrative-reference")
    first, second = [e for e in building.elements if e.role == Role.EXT_WALL][:2]
    original = thermal_construction(second.construction)
    building.assign_element_u_value(.2, component_name=first.construction.components[0].name,
                                   layer_index=0, element_ids=(first.identifier,))
    identity = building.snapshot().sha256
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    for identifier, expected in ((first.identifier, .2), (second.identifier, original.u_value_w_m2k)):
        records = [item for item in resolved.surfaces if item["physical_element_id"] == identifier]
        assert records
        assert all(ConstructionSpec.model_validate(item["construction"]).u_value_w_m2k
                   == pytest.approx(expected) for item in records)
    assert building.snapshot().sha256 == identity


@pytest.mark.parametrize("identifiers", [(), ("missing",), "main.wall", (1,), None, 4])
def test_explicit_physical_targets_are_required(identifiers):
    building = Building(preset="illustrative-reference")
    before = building.snapshot()
    with pytest.raises(ValueError, match="element_ids"):
        building.assign_element_u_value(.3, component_name=wall(building).construction.components[0].name,
                                       layer_index=0, element_ids=identifiers)
    assert building.snapshot().sha256 == before.sha256


def test_missing_construction_and_duplicate_targets_leave_building_unchanged():
    building = Building(preset="illustrative-reference")
    first, second = [e for e in building.elements if e.role == Role.EXT_WALL][:2]
    building.elements = tuple(e.with_changes(construction=None)
                              if e.identifier == second.identifier else e for e in building.elements)
    before = building.snapshot()
    component_name = first.construction.components[0].name
    with pytest.raises(ValueError, match="layered Element"):
        building.assign_element_u_value(.3, component_name=component_name, layer_index=0,
                                       element_ids=(first.identifier, second.identifier))
    with pytest.raises(ValueError, match="distinct"):
        building.assign_element_u_value(.3, component_name=component_name, layer_index=0,
                                       element_ids=(first.identifier, first.identifier))
    assert building.snapshot().sha256 == before.sha256


def test_post_renovation_authoring_does_not_invent_an_intervention():
    baseline = Building(preset="illustrative-reference")
    selected = wall(baseline)
    child = baseline.renovate(ConstructionOperation(
        "replace_element", selected.role, element=selected.construction))
    stages = child.stages
    flows = child.material_flows
    child.assign_element_u_value(.2, component_name=selected.construction.components[0].name,
                                 layer_index=0, element_ids=(selected.identifier,))
    assert child.stages == stages
    assert child.material_flows == flows
    assert child.authoring_links[-1].changes_material_inventory
    assert any("material history" in message for message in child.material_history_requirements)
    assert baseline.snapshot().sha256 == stages[0].before.sha256
