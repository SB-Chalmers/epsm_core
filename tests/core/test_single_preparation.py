"""A physical snapshot shares one validated preparation across consumers."""

import pickle
from dataclasses import replace
from io import StringIO

import pytest

from epsm_core import Building, EnergyPlusCompiler, Weather, preflight_energyplus
from epsm_core.building import BuildingSnapshot
from epsm_core.resolved import resolve_snapshot_inputs
from epsm_core.specs.schedules import ScheduleSpec, hourly_schedule_scope
from epsm_core.weather import validate_epw_calendar


def test_snapshot_preparation_resolves_geometry_and_owners_once(monkeypatch, synthetic_weather):
    from epsm_core import building_adapter, pipeline

    physical = Building(preset="illustrative-reference")
    weather = Weather.from_epw(synthetic_weather)
    snapshot = physical.snapshot()
    expected = physical.to_spec(weather)
    counts = {}

    def count(owner, name):
        original = getattr(owner, name)

        def recorded(*args, **kwargs):
            counts[name] = counts.get(name, 0) + 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, recorded)

    count(BuildingSnapshot, "to_building")
    count(Building, "readiness")
    count(pipeline, "resolve_geometry")
    count(building_adapter, "_physical_element_owners")
    prepared = resolve_snapshot_inputs(snapshot, weather, engine="epsm_rc")
    assert counts == {"to_building": 1, "readiness": 1, "resolve_geometry": 1,
                      "_physical_element_owners": 1}
    assert prepared.spec == expected
    assert prepared.resolved.source_snapshot_id == snapshot.sha256
    assert prepared.resolved.source_spec_hash == expected.physical_hash()
    assert all(face["physical_element_id"] for face in prepared.resolved.surfaces)

    # Returned working values cannot modify retained snapshots or another call.
    prepared.building.identifier = "edited working building"
    prepared.spec.surface_constructions["working-only"] = prepared.spec.envelope.wall
    following = resolve_snapshot_inputs(snapshot, weather)
    assert following.spec == expected
    assert following.building.identifier == physical.identifier
    assert following.resolved.to_dict() == prepared.resolved.to_dict()


def test_resolved_view_parses_once_and_remains_portable(monkeypatch, building):
    from epsm_core import resolved

    view = resolved.resolve_building(building)
    original = resolved.json.loads
    reads = []

    def recorded(*args, **kwargs):
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(resolved.json, "loads", recorded)
    assert view.zones
    assert view.geometry
    assert view.source_spec_hash
    assert len(reads) == 1
    restored = pickle.loads(pickle.dumps(view))
    assert restored.to_dict() == view.to_dict()
    with pytest.raises(TypeError):
        restored.zones["changed"] = {}


def test_snapshot_restoration_decodes_each_assignment_once(monkeypatch):
    from epsm_core import building

    data = Building(preset="illustrative-reference").to_dict()
    original = building._decode_element
    decoded = []

    def recorded(value):
        decoded.append(1)
        return original(value)

    monkeypatch.setattr(building, "_decode_element", recorded)
    restored = Building.from_dict(data)
    assert len(decoded) == len(data["elements"])
    assert restored.to_dict() == data
    data["elements"][0]["area_m2"] = -1
    assert restored.elements[0].area_m2 >= 0
    invalid = restored.to_dict()
    invalid["elements"].append(invalid["elements"][0])
    with pytest.raises(ValueError, match="identifiers must be unique"):
        Building.from_dict(invalid)


def test_schedule_scope_reuses_equal_values_and_keeps_years_and_calls_separate(monkeypatch):
    original = ScheduleSpec._expand_hourly
    expanded = []

    def recorded(self, year):
        expanded.append(year)
        return original(self, year)

    monkeypatch.setattr(ScheduleSpec, "_expand_hourly", recorded)
    schedule = ScheduleSpec.constant(0.5)
    same = ScheduleSpec.model_validate(schedule.model_dump())
    with hourly_schedule_scope():
        first = schedule.hourly(2023)
        with hourly_schedule_scope():
            assert same.hourly(2023) is first
        assert len(same.hourly(2024)) == 8784
        with pytest.raises(TypeError):
            same.hourly(2023.0)
        with pytest.raises(TypeError):
            first[0] = 99
    with hourly_schedule_scope():
        assert schedule.hourly(2023) == first
    assert expanded == [2023, 2024, 2023.0, 2023]


def test_schedule_scope_cleans_up_after_failure_and_preserves_calendar_validation():
    schedule = ScheduleSpec.annual([1] * 8760, calendar_year=2023)
    with pytest.raises(ValueError, match="differs"):
        with hourly_schedule_scope():
            schedule.hourly(2024)
    with hourly_schedule_scope():
        assert schedule.hourly(2023) == (1,) * 8760


def test_annual_schedule_scope_uses_existing_tuple_without_json_serialization(monkeypatch):
    schedule = ScheduleSpec.annual([1] * 8760, calendar_year=2023)

    def forbidden(*args, **kwargs):
        pytest.fail("An immutable annual vector needs no JSON serialization for reuse")

    monkeypatch.setattr(ScheduleSpec, "model_dump_json", forbidden)
    with hourly_schedule_scope():
        assert schedule.hourly(2023) is schedule.annual_values
        with pytest.raises(ValueError, match="differs"):
            schedule.hourly(2024)


def test_layer_limit_belongs_to_energyplus_not_physical_rc_inputs(synthetic_weather):
    physical = Building(preset="illustrative-reference")
    wall = next(item for item in physical.elements if item.role.value == "EXT_WALL")
    component = wall.construction.components[0]
    layers = tuple(replace(component.layers[0], position=i) for i in range(11))
    construction = replace(wall.construction,
                           components=(replace(component, layers=layers),))
    physical.assign_construction(construction, element_ids=[wall.identifier])
    assert physical.readiness(engine="epsm_rc")
    assert not physical.readiness(engine="energyplus")
    prepared = resolve_snapshot_inputs(physical.snapshot(), Weather.from_epw(synthetic_weather),
                                       engine="epsm_rc")
    assert len(prepared.spec.envelope.wall.layers) == 11
    readiness = preflight_energyplus(prepared.spec)
    assert not readiness
    assert any("10 layers" in issue for issue in readiness.unsupported)
    # Direct specification compilation must retain the limit even if a caller
    # bypasses physical readiness and the public preflight operation.
    compiler = object.__new__(EnergyPlusCompiler)
    with pytest.raises(ValueError, match="10 layers"):
        compiler.compile(prepared.spec)


def test_epw_calendar_accepts_captured_text_without_reopening_or_closing(monkeypatch,
                                                                     synthetic_weather):
    from pathlib import Path

    expected = validate_epw_calendar(synthetic_weather, 2023)
    captured = synthetic_weather.read_text(encoding="utf-8-sig")

    def forbidden(*args, **kwargs):
        pytest.fail("An explicitly captured EPW must not reopen a file")

    monkeypatch.setattr(Path, "open", forbidden)
    stream = StringIO(captured)
    assert validate_epw_calendar(stream, 2023) == expected
    assert not stream.closed
    truncated = StringIO("\n".join(captured.splitlines()[:-1]) + "\n")
    with pytest.raises(ValueError, match="calendar"):
        validate_epw_calendar(truncated, 2023)
    assert not truncated.closed
