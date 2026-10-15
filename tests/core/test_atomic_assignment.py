"""Resolved inputs commit together without changing the physical geometry."""

import pytest
from epsm_data import ConstructionOperation
from epsm_data.domain import ConstructionSet
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    Equipment,
    FacadeOverride,
    Footprint,
    FVPSpec,
    GlazingSpec,
    InputAssignmentReport,
    SourceRecord,
)


def wall(building):
    return next(e for e in building.elements if e.role == Role.EXT_WALL)


def test_replace_changes_only_supplied_roles_and_preserves_openings_and_context(synthetic_weather):
    building = Building(preset="illustrative-reference")
    building.facade = building.facade.updated(overrides=(
        FacadeOverride(facade_id=building.geometry.facades()[0].facade_id, wwr=0),))
    before = building.snapshot().to_dict()
    window = building.construction_set.elements[Role.WINDOW].with_changes(u_value=0.9)
    top = building.construction_set.elements[Role.TOP_FLOOR]
    roof = top.with_changes(application=Role.ROOF,
        components=tuple(c.with_changes(application=Role.ROOF) for c in top.components))
    selected = ConstructionSet(elements={Role.WINDOW: window, Role.ROOF: roof})
    report = building.assign_inputs(construction_set=selected,
        operation=building.operation.with_changes(equipment_gain_w_m2=8))
    assert isinstance(report, InputAssignmentReport)
    assert report.unmatched == ("construction:ROOF",)
    assert "operation" in report.replaced
    assert report.applied == ()
    after = building.snapshot().to_dict()
    for key in ("geometry", "facade", "context", "foundation", "ground_temperature"):
        assert after[key] == before[key]
    for old, new in zip(before["elements"], after["elements"]):
        for key in ("identifier", "role", "area_m2", "part_id", "facade_id", "storey"):
            assert old[key] == new[key]
        if old["role"] != Role.WINDOW.value:
            assert old == new
    assert all(e.construction.u_value == 0.9 for e in building.elements if e.role == Role.WINDOW)
    assert building.operation.equipment_gain_w_m2 == 8
    spec = building.to_spec(synthetic_weather)
    for element in building.elements:
        if element.role == Role.WINDOW:
            assert spec.facade.value_for("glazing", element.facade_id,
                                         element.storey).u_value_w_m2k == 0.9


def test_fill_missing_preserves_per_element_assignments_and_configured_sections():
    building = Building(preset="illustrative-reference")
    selected = wall(building)
    missing = next(e for e in building.elements if e.role == Role.EXT_WALL
                   and e.identifier != selected.identifier)
    building.elements = tuple(e.with_changes(construction=None) if e.id == missing.id else e
                              for e in building.elements)
    old_operation = building.operation
    report = building.assign_inputs(construction_set=building.construction_set,
        operation=old_operation.with_changes(equipment_gain_w_m2=8), mode="fill_missing")
    assert f"construction:{missing.id}" in report.applied
    assert f"construction:{selected.id}" in report.retained
    assert "operation" in report.retained
    assert building.operation == old_operation
    assert next(e for e in building.elements if e.id == selected.id) == selected
    assert next(e for e in building.elements if e.id == missing.id).construction is not None


def test_fully_retained_fill_missing_is_a_snapshot_and_provenance_noop():
    building = Building(preset="illustrative-reference")
    before = building.snapshot()
    incoming = building.construction_set.with_changes(version_id="11111111-1111-1111-1111-111111111111",
                                                       valid_from_year=2020)
    report = building.assign_inputs(construction_set=incoming, mode="fill_missing",
        provenance={"records": [SourceRecord(field_path="construction_set", status="assumed",
                                              source="unused-new-source")]})
    assert not report.applied and not report.replaced
    assert building.snapshot().sha256 == before.sha256


def test_partial_assignment_preserves_sources_for_uncovered_roles():
    building = Building(preset="illustrative-reference")
    before = building.provenance
    source = next(r for r in before.records if r.field_path == "construction_set")
    incoming = SourceRecord(field_path="construction_set", status="assumed", source="new-wall")
    building.assign_inputs(construction_set=ConstructionSet(elements={Role.EXT_WALL:
        wall(building).construction}), provenance={"records": [incoming]})
    records = {r.field_path: r for r in building.provenance.records}
    assert records["construction_set.elements.WINDOW"].source == source.source
    assert records["construction_set.elements.EXT_WALL"].source == "new-wall"
    assert "construction_set" not in records


@pytest.mark.parametrize("inputs", [
    {"operation": {"equipment_gain_w_m2": -1}},
    {"thermal_bridge_uplift_fraction": float("nan")},
    {"facade_properties": {"default_wwr": 0.5}},
    {"facade_properties": {"glazing": {"u_value_w_m2k": -1}}},
    {"provenance": {"records": [{"field_path": "", "status": "assumed"}]}},
    {"mode": "unknown"},
])
def test_invalid_late_input_leaves_every_assignment_unchanged(inputs):
    building = Building(preset="illustrative-reference")
    before = building.snapshot()
    with pytest.raises((TypeError, ValueError)):
        building.assign_inputs(construction_set=building.construction_set, **inputs)
    assert building.snapshot().sha256 == before.sha256


def test_incomplete_building_stays_incomplete_without_inventing_openings_or_systems():
    building = Building.from_footprint(Footprint.rectangle(10, 8), storeys=1, storey_height_m=3)
    reference = Building(preset="illustrative-reference")
    before = building.geometry
    report = building.assign_inputs(construction_set=reference.construction_set,
        facade_properties={"glazing": reference.facade.glazing})
    assert building.geometry == before
    assert building.facade is None and building.hvac is None and building.operation is None
    assert "facade_properties" in report.unmatched
    assert "facade (explicit opening/opaque-area information)" in building.readiness().missing
    assert not any(e.role == Role.WINDOW for e in building.elements)


def test_geometry_first_basement_does_not_relabel_roles_or_guess_a_ground_recipe():
    building = Building.from_footprint(Footprint.rectangle(10, 8), storeys=1,
                                      storey_height_m=3, basement_depth_m=2)
    before = tuple((e.identifier, e.role, e.area_m2) for e in building.elements)
    ground = Building(preset="illustrative-reference").construction_set.elements[Role.GROUND_FLOOR]
    basement = ground.with_changes(application=Role.BASEMENT_FLOOR,
        components=tuple(c.with_changes(application=Role.BASEMENT_FLOOR) for c in ground.components))
    report = building.assign_inputs(construction_set=ConstructionSet(
        elements={Role.BASEMENT_FLOOR: basement}))
    assert report.unmatched == ("construction:BASEMENT_FLOOR",)
    assert tuple((e.identifier, e.role, e.area_m2) for e in building.elements) == before
    assert all(e.construction is None for e in building.elements)


def test_provenance_replaces_only_applied_fields_and_snapshots_remain_independent():
    building = Building(preset="illustrative-reference")
    previous = building.snapshot()
    record = SourceRecord(field_path="operation", status="assumed", source="project-profile")
    building.assign_inputs(operation=building.operation.with_changes(equipment_gain_w_m2=9),
        provenance={"records": [record]})
    assert record in building.provenance.records
    assert any(r.field_path == "geometry" for r in building.provenance.records)
    assert previous.to_building().operation.equipment_gain_w_m2 != 9
    assert Building.from_dict(building.to_dict()).snapshot().sha256 == building.snapshot().sha256
    report = building.assign_inputs(operation=building.operation,
        provenance={"records": [record.updated(source="ignored")]}, mode="fill_missing")
    assert "operation" in report.retained
    assert record in building.provenance.records


def test_specific_source_record_for_replaced_section_is_retained():
    building = Building(preset="illustrative-reference")
    record = SourceRecord(field_path="operation.equipment_gain_w_m2", status="assumed",
                          source="specific-gain-source")
    building.assign_inputs(operation=building.operation.with_changes(equipment_gain_w_m2=9),
                           provenance={"records": [record]})
    assert record in building.provenance.records


def test_assignment_keeps_renovation_flows_and_marks_later_authoring_changes():
    baseline = Building(preset="illustrative-reference")
    selected = wall(baseline)
    child = baseline.renovate(ConstructionOperation("replace_element", Role.EXT_WALL,
                                                  element=selected.construction))
    stage = child.stages[0]
    flows = child.material_flows
    child.assign_inputs(construction_set=ConstructionSet(elements={Role.EXT_WALL:
        selected.construction}))
    assert child.stages[0] is stage and child.material_flows is flows
    assert child.material_history_requirements
    assert stage.after.sha256 != child.snapshot().sha256
    assert not baseline.stages


def test_facade_properties_preserve_layout_and_report_is_bounded_detached():
    building = Building(preset="illustrative-reference")
    original = building.facade
    report = building.assign_inputs(facade_properties={"solar_shading_factor": 0.71})
    assert building.facade.default_wwr == original.default_wwr
    assert building.facade.layout == original.layout
    assert building.facade.solar_shading_factor == 0.71
    exported = report.to_dict()
    exported["replaced"].clear()
    assert report.replaced == ("facade_properties",)
    assert len(repr(report)) <= 160 and "\n" not in repr(report)


def test_glazing_properties_reach_physical_windows_and_engine_without_changing_openings(
        synthetic_weather):
    building = Building(preset="illustrative-reference")
    areas = tuple((e.identifier, e.area_m2) for e in building.elements)
    glazing = GlazingSpec(u_value_w_m2k=0.8, solar_heat_gain_coefficient=0.4,
                          visible_transmittance=0.6)
    building.assign_inputs(facade_properties={"glazing": glazing})
    assert tuple((e.identifier, e.area_m2) for e in building.elements) == areas
    spec = building.to_spec(synthetic_weather)
    assert all(e.construction.u_value == 0.8 for e in building.elements if e.role == Role.WINDOW)
    assert all(spec.facade.value_for("glazing", e.facade_id, e.storey) == glazing
               for e in building.elements if e.role == Role.WINDOW)


def test_explicit_glazing_wins_window_performance_and_keeps_its_own_source():
    building = Building(preset="illustrative-reference")
    glazing = building.facade.glazing.updated(u_value_w_m2k=0.8)
    building.assign_inputs(construction_set=building.construction_set,
        facade_properties={"glazing": glazing}, provenance={"records": [
            SourceRecord(field_path="construction_set", status="assumed", source="catalogue"),
            SourceRecord(field_path="facade.glazing", status="assumed", source="project-glazing"),
        ]})
    records = {r.field_path: r.source for r in building.provenance.records}
    for element in building.elements:
        if element.role == Role.WINDOW:
            path = "elements." + element.identifier + ".construction"
            assert path not in records
            assert records[path + ".u_value"] == "project-glazing"
            assert records[path + ".name"] == "catalogue"
            assert element.construction.u_value == 0.8


@pytest.mark.parametrize("broad", [False, True])
def test_glazing_only_preserves_unchanged_physical_window_metadata_sources(broad):
    building = Building(preset="illustrative-reference")
    window = next(e for e in building.elements if e.role == Role.WINDOW)
    path = "elements." + window.identifier + ".construction"
    metadata_path = path + ".name"
    source_path = path if broad else metadata_path
    source = SourceRecord(field_path=source_path, status="assumed", source="window-identity")
    building.provenance = {"records": [*building.provenance.records, source]}
    building.assign_inputs(facade_properties={"glazing": building.facade.glazing},
        provenance={"records": [SourceRecord(field_path="facade.glazing", status="assumed",
                                              source="new-glazing")]})
    records = {r.field_path: r.source for r in building.provenance.records}
    assert records[metadata_path] == "window-identity"
    assert records[path + ".u_value"] == "new-glazing"
    assert next(e for e in building.elements if e.id == window.id).construction.name == window.construction.name


def test_invalid_effective_operation_hvac_pair_rolls_back_atomically():
    building = Building(preset="illustrative-reference")
    before = building.snapshot()
    operation = building.operation.with_changes(heating_setpoint={"values": (50,) * 24},
                                              cooling_setpoint={"values": (60,) * 24})
    with pytest.raises(ValueError, match="supply limit"):
        building.assign_inputs(operation=operation, construction_set=building.construction_set)
    assert building.snapshot().sha256 == before.sha256
    # The supplied operation is retained rather than paired with HVAC in this mode.
    building.assign_inputs(operation=operation, mode="fill_missing")
    assert building.snapshot().sha256 == before.sha256


def test_invalid_fvp_hvac_pair_is_rejected_even_without_operation():
    reference = Building(preset="illustrative-reference")
    building = Building.empty()
    hvac = reference.hvac.with_changes(delivery={"fvp": FVPSpec(cop=3, capacity_kw=5)})
    before = building.snapshot()
    with pytest.raises(ValueError, match="F ventilation"):
        building.assign_inputs(hvac=hvac)
    assert building.snapshot().sha256 == before.sha256


@pytest.mark.parametrize("changes, message", [
    ({"mechanical_vent_fraction": {"values": (0.5,) * 24}}, "continuous exhaust"),
    ({"infiltration_coefficients": (0.5, 0.5, 0, 0), "infiltration_source": "test:source"},
     "constant leakage"),
])
def test_known_fvp_flow_contradictions_roll_back(changes, message):
    reference = Building(preset="illustrative-reference")
    airflow = reference.hvac.airflow.updated(topology="F", sensible_recovery_effectiveness=0,
                                             **changes)
    hvac = reference.hvac.with_changes(airflow=airflow,
        delivery={"fvp": FVPSpec(cop=3, capacity_kw=5)})
    building = Building.empty()
    before = building.snapshot()
    with pytest.raises(ValueError, match=message):
        building.assign_inputs(hvac=hvac)
    assert building.snapshot().sha256 == before.sha256


def test_airflow_leaf_patch_preserves_delivery_equipment_and_other_source_records():
    building = Building(preset="illustrative-reference")
    building.hvac = building.hvac.with_changes(equipment=(Equipment("unit", "project:unit"),))
    source = SourceRecord(field_path="hvac", status="assumed", source="installed-system")
    building.provenance = {"records": [*building.provenance.records, source]}
    previous = building.hvac
    patch_source = SourceRecord(field_path="hvac.airflow.envelope_infiltration_ach",
                               status="assumed", source="project:leakage")
    report = building.assign_inputs(airflow_properties={"envelope_infiltration_ach": 0.4},
                                   provenance={"records": [patch_source]})
    assert building.hvac.airflow.envelope_infiltration_ach == 0.4
    assert building.hvac.delivery == previous.delivery and building.hvac.equipment == previous.equipment
    assert building.hvac.airflow.topology == previous.airflow.topology
    assert report.replaced == ("hvac.airflow.envelope_infiltration_ach",)
    records = {r.field_path: r.source for r in building.provenance.records}
    assert records["hvac.delivery"] == records["hvac.equipment"] == "installed-system"
    assert records[patch_source.field_path] == "project:leakage"


@pytest.mark.parametrize("properties", [
    {"envelope_infiltration_ach": -1}, {"topology": "F"},
    {"mechanical_vent_l_s_m2": float("nan")}, {"unknown": 2},
    {"maximum_heating_supply_temperature_c": float("nan")},
    {"mechanical_vent_l_s_m2": float("inf")},
    {"envelope_infiltration_ach": 0.2, "envelope_infiltration_l_s_m2": 0.1},
    {"mechanical_vent_fraction": {"values": (1.5,) * 24}},
    {"infiltration_coefficients": (0.5, 0.5, 0, 0), "infiltration_source": ""},
])
def test_invalid_airflow_patch_rolls_back_even_when_missing_or_retained(properties):
    for building in (Building.empty(), Building(preset="illustrative-reference")):
        before = building.snapshot()
        with pytest.raises(ValueError):
            building.assign_inputs(airflow_properties=properties, mode="fill_missing")
        assert building.snapshot().sha256 == before.sha256


def test_airflow_patch_without_system_is_unmatched_and_does_not_invent_topology():
    building = Building.empty()
    before = building.snapshot()
    report = building.assign_inputs(airflow_properties={"mechanical_vent_l_s_m2": 0.35})
    assert report.unmatched == ("airflow_properties",)
    assert building.snapshot().sha256 == before.sha256 and building.hvac is None


def test_same_call_hvac_then_patch_has_explicit_mode_and_source_precedence():
    hvac = Building(preset="illustrative-reference").hvac
    hvac = hvac.with_changes(airflow=hvac.airflow.updated(envelope_infiltration_ach=0))
    building = Building.empty()
    report = building.assign_inputs(hvac=hvac,
        airflow_properties={"envelope_infiltration_ach": 0.4}, mode="fill_missing")
    assert building.hvac.airflow.envelope_infiltration_ach == 0
    assert "hvac.airflow.envelope_infiltration_ach" in report.retained
    building = Building.empty()
    building.assign_inputs(hvac=hvac, airflow_properties={"envelope_infiltration_ach": 0.4},
        provenance={"records": [
            SourceRecord(field_path="hvac", status="assumed", source="template"),
            SourceRecord(field_path="hvac.airflow.envelope_infiltration_ach", status="assumed",
                         source="explicit-leakage"),
        ]})
    assert building.hvac.airflow.envelope_infiltration_ach == 0.4
    records = {r.field_path: r.source for r in building.provenance.records}
    assert "hvac" not in records
    assert records["hvac.delivery"] == "template"
    assert records["hvac.airflow.envelope_infiltration_ach"] == "explicit-leakage"
