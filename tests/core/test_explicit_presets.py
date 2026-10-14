"""Explicit assumptions and saved-authoring compatibility."""
import copy

import pytest
from pydantic import ValidationError

from epsm_core import Building, BuildingBuilder, BuildingSnapshot, Footprint, GeometrySpec


def test_no_argument_authoring_does_not_resolve_assumptions(monkeypatch):
    def forbidden():
        raise AssertionError("implicit standard lookup")
    monkeypatch.setattr("epsm_core.standards.load_sveby_spec", forbidden)
    building = Building()
    assert building.preset is None
    assert all(getattr(building, name) is None for name in
               ("geometry", "construction_set", "facade", "hvac", "operation",
                "thermal_bridge_uplift_fraction"))
    assert {"geometry", "hvac", "operation"} <= set(building.readiness().missing)
    assert Building.from_snapshot(building.snapshot()).to_dict() == building.to_dict()
    builder = BuildingBuilder()
    assert builder.profile is None and builder.assumptions == {}
    with pytest.raises(ValidationError):
        builder.build(identifier="incomplete")


def test_explicit_preset_records_version_and_preserves_overrides():
    geometry = GeometrySpec.from_footprint(Footprint.rectangle(8, 6), storeys=1,
                                          storey_height_m=3)
    building = Building(preset="illustrative-reference", geometry=geometry)
    assert building.geometry == geometry
    assert building.preset_revision == "4"
    records = building.provenance.records
    assert not any(r.field_path == "geometry" for r in records)
    assert {r.field_path for r in records} == {
        "construction_set", "facade", "hvac", "operation", "foundation",
        "thermal_bridge_uplift_fraction", "load_reference_area_policy",
    }
    assert all(r.status == "assumed" and r.assumption_profile == "illustrative-reference@4"
               for r in records)
    assert building.snapshot().to_dict()["schema"] == "epsm.building/5"
    assert building.copy().to_dict() == building.to_dict()
    building.operation = building.operation.with_changes(equipment_gain_w_m2=9)
    assert not any(r.field_path == "operation" for r in building.provenance.records)


def test_explicit_builder_profile_retains_override_provenance(building):
    builder = BuildingBuilder(building_use="residential")
    result = builder.build(**{**building.model_dump(), "use": {"equipment_gain_w_m2": 9}})
    assert result.use.equipment_gain_w_m2 == 9
    record = next(r for r in result.provenance.records if r.field_path == "use.equipment_gain_w_m2")
    assert record.source == "user" and record.assumption_profile is None
    assert any(r.assumption_profile == builder.profile for r in result.provenance.records)


def legacy_snapshot(building):
    data = copy.deepcopy(building.to_dict())
    data["schema"] = "epsm.building/1"
    data.pop("preset_revision", None)
    data.pop("provenance", None)
    data.pop("foundation", None)
    data.pop("ground_temperature", None)
    data.pop("thermal_bridge_uplift_fraction", None)
    data.pop("load_reference_area_m2", None)
    data.pop("load_reference_area_policy", None)
    return BuildingSnapshot.from_dict(data)


def test_legacy_snapshot_keeps_identity_until_an_edit(monkeypatch):
    original = legacy_snapshot(Building(preset="illustrative-reference"))
    def forbidden():
        raise AssertionError("preset re-resolution on restore")
    monkeypatch.setattr("epsm_data.reference_construction_set", forbidden)
    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert restored.preset_revision is None
    assert restored.provenance.records == ()
    restored.identifier = "edited"
    assert restored.snapshot().to_dict()["schema"] == "epsm.building/5"
    assert original.to_dict()["schema"] == "epsm.building/1"


def test_legacy_empty_lineage_has_no_synthetic_authoring_link():
    original = legacy_snapshot(Building(preset="illustrative-reference"))
    restored = original.to_building()
    lineage = restored.lineage_to_dict()
    restored.restore_lineage(lineage)
    assert restored.snapshot().sha256 == original.sha256
    assert restored.authoring_links == ()


def test_legacy_renovation_lineage_preserves_all_snapshot_references():
    from epsm_data import ConstructionOperation, RenovationMeasure
    from epsm_data.domain.enums import BuildingElement as Role
    baseline = Building(preset="illustrative-reference")
    target = next(e for e in baseline.elements if e.role == Role.EXT_WALL)
    intervention = RenovationMeasure("test", "envelope", "Test", "Like for like", "wall",
        operations=(ConstructionOperation("replace_element", target.role,
                                         element=target.construction),),
        target_element_ids=(target.identifier,))
    child = baseline.renovate(intervention)
    history = child.lineage_to_dict()
    for stage in history["stages"]:
        for side in ("before", "after"):
            stage[side]["schema"] = "epsm.building/1"
            stage[side].pop("preset_revision")
            stage[side].pop("provenance")
            stage[side].pop("foundation", None)
            stage[side].pop("ground_temperature", None)
            stage[side].pop("thermal_bridge_uplift_fraction", None)
            stage[side].pop("load_reference_area_m2", None)
            stage[side].pop("load_reference_area_policy", None)
    history["parent_snapshot_id"] = BuildingSnapshot.from_dict(history["stages"][-1]["before"]).sha256
    original = BuildingSnapshot.from_dict(history["stages"][-1]["after"])
    restored = original.to_building()
    restored.restore_lineage(history)
    assert restored.snapshot().sha256 == original.sha256
    assert restored.authoring_links == ()
    restored.operation = restored.operation.with_changes(equipment_gain_w_m2=9)
    assert restored.snapshot().to_dict()["schema"] == "epsm.building/5"
    assert restored.authoring_links[-1].before.sha256 == original.sha256
    assert not restored.authoring_links[-1].changes_material_inventory


def test_unknown_builder_profile_selection_rejected():
    with pytest.raises(ValueError, match="Unknown building_use"):
        BuildingBuilder(building_use="warehouse")


def test_preset_identity_cannot_disagree_with_its_provenance():
    building = Building(preset="illustrative-reference")
    with pytest.raises(AttributeError, match="Preset identity"):
        building.preset_revision = "invented"
    with pytest.raises(AttributeError, match="Preset identity"):
        building.preset = "other"
    with pytest.raises(AttributeError, match="Preset identity"):
        del building.preset_revision
