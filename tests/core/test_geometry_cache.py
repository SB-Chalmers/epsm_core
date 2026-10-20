"""Prepared geometry preserves physical identities and isolates mutable consumers."""

import pytest

from epsm_core import Building, EnergyPlusCompiler, ScheduleSpec, Weather
from epsm_core.pipeline import GeometryCache, resolve_geometry


def faces(resolved):
    return [(face.name, face.vertices, face.area, face.construction)
            for face in resolved.graph.surfaces]


def test_geometry_cache_is_bounded_detached_and_clearable(building):
    cache = GeometryCache(max_entries=1)
    expected = faces(resolve_geometry(building))
    first = resolve_geometry(building, cache=cache)
    first.graph.surfaces.clear()
    assert faces(resolve_geometry(building, cache=cache)) == expected
    assert cache.hits == 1
    turned = building.updated(geometry=building.geometry.updated(orientation_deg=23))
    assert faces(resolve_geometry(turned, cache=cache)) != expected
    assert len(cache) == 1
    resolve_geometry(building, cache=cache)
    assert cache.misses == 3
    cache.clear()
    assert len(cache) == cache.hits == cache.misses == 0
    for size in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            GeometryCache(max_entries=size)


def test_geometry_cache_reuses_geometry_but_not_physical_assignments(building):
    cache = GeometryCache()
    first = resolve_geometry(building, cache=cache)
    edited = building.updated(use=building.use.updated(
        heating_setpoint=ScheduleSpec.constant(25)), envelope=building.envelope.updated(
            wall=building.envelope.ground))
    assert faces(resolve_geometry(edited, cache=cache)) == faces(first)
    assert cache.hits == 1
    glazed = building.updated(facade=building.facade.updated(
        glazing=building.facade.glazing.updated(solar_heat_gain_coefficient=.3)))
    assert faces(resolve_geometry(glazed, cache=cache)) == faces(first)
    assert cache.hits == 2
    for changes in ({"default_wwr": .3}, {"reveal_depth_m": .1}):
        resolve_geometry(building.updated(facade=building.facade.updated(**changes)), cache=cache)
    resolve_geometry(building, panelize=True, cache=cache)
    assert cache.misses == 4


def test_geometry_cache_invalidates_changed_implementation(building, monkeypatch):
    cache = GeometryCache()
    resolve_geometry(building, cache=cache)
    monkeypatch.setattr("epsm_core.pipeline._geometry_implementation_identity", lambda: "changed")
    resolve_geometry(building, cache=cache)
    assert cache.misses == 2


def test_geometry_implementation_sources_are_read_once_per_process(building, monkeypatch):
    from pathlib import Path

    from epsm_core import pipeline

    original = Path.read_bytes
    reads = []

    def recorded(path):
        reads.append(path)
        return original(path)

    pipeline._geometry_implementation_identity.cache_clear()
    monkeypatch.setattr(Path, "read_bytes", recorded)
    try:
        cache = GeometryCache()
        resolve_geometry(building, cache=cache)
        first_reads = list(reads)
        assert first_reads
        resolve_geometry(building, cache=cache)
        resolve_geometry(building, cache=GeometryCache())
        assert reads == first_reads
    finally:
        pipeline._geometry_implementation_identity.cache_clear()


@pytest.mark.parametrize("shape", ["concave", "courtyard", "multipart"])
def test_complex_geometry_reuse_preserves_topology_and_windows(building, shape):
    from epsm_core import Footprint

    part = building.geometry.parts[0]
    if shape == "concave":
        footprint = Footprint(exterior=((0, 0), (12, 0), (12, 4), (5, 4), (5, 10), (0, 10)))
    else:
        footprint = Footprint(exterior=((0, 0), (12, 0), (12, 10), (0, 10)),
            holes=(((4, 3), (8, 3), (8, 7), (4, 7)),) if shape == "courtyard" else ())
    parts = (part.updated(footprint=footprint),)
    if shape == "multipart":
        parts += (part.updated(identifier="annex", footprint=Footprint(
            exterior=((30, 0), (38, 0), (38, 6), (30, 6)))),)
    spec = building.updated(geometry=building.geometry.updated(parts=parts))
    cache = GeometryCache()
    before = resolve_geometry(spec, panelize=True)
    for _ in range(2):
        after = resolve_geometry(spec, panelize=True, cache=cache)
        assert faces(after) == faces(before)
        assert after.openings == before.openings
        assert after.graph.zones == before.graph.zones
        assert [p.wkb for p in after.polygons] == [p.wkb for p in before.polygons]


def test_authoring_resolves_once_and_rebinds_materials(synthetic_weather, monkeypatch):
    from epsm_core import pipeline

    physical = Building(preset="illustrative-reference")
    weather = Weather.from_epw(synthetic_weather)
    original = pipeline.resolve_geometry
    calls = []

    def record(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "resolve_geometry", record)
    reference = physical.to_spec(weather)
    assert len(calls) == 1
    cache = GeometryCache()
    assert physical.to_spec(weather, geometry_cache=cache) == reference
    assert physical.snapshot().to_spec(weather, geometry_cache=cache) == reference
    resolved = physical.resolve(weather, geometry_cache=cache)
    assert resolved.source_spec_hash == reference.physical_hash()
    assert cache.hits >= 2
    physical.operation = physical.operation.updated(heating_setpoint=ScheduleSpec.constant(24))
    assert set(physical.to_spec(weather, geometry_cache=cache).use.heating_setpoint.values) == {24}


@pytest.mark.energyplus
def test_compiler_cache_preserves_complete_model_and_owners(building, energyplus):
    cache = GeometryCache()
    compiler = EnergyPlusCompiler(energyplus, geometry_cache=cache)
    first, report = compiler.compile(building)
    second, repeated = compiler.compile(building)
    assert second == first
    assert repeated.data == report.data
    assert cache.hits == 1
    revised = building.updated(envelope=building.envelope.updated(wall=building.envelope.ground))
    changed, _ = compiler.compile(revised)
    uncached, _ = EnergyPlusCompiler(energyplus).compile(revised)
    assert changed == uncached
