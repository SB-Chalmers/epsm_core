"""Context approximation bounds, strict retry gates and coherent selected artifacts."""

import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from epsm_core.results import SimulationResult
from epsm_core.runner import EnergyPlusRunner, SimulationError
from epsm_core.shadow_recovery import simplify_shadow_context
from epsm_core.specs import ContextBuilding, ContextSpec, Footprint, GeometrySpec

CASES = json.loads((Path(__file__).parent / "fixtures/shadow_capacity_scenes.json").read_text())


def scene(building, case=CASES[1]):
    return building.updated(
        geometry=GeometrySpec.from_footprint(
            Footprint.model_validate(case["target"]), storeys=8, storey_height_m=2.82375
        ),
        context=ContextSpec.model_validate(case["context"]),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["building_id"])
@pytest.mark.parametrize("tolerance", [1.0, 2.0])
def test_real_candidates_keep_target_heights_courtyards_and_bounds(building, case, tolerance):
    source = scene(building, case)
    serialized = source.model_dump_json()
    candidate, audit = simplify_shadow_context(source, tolerance)
    assert candidate is not None
    assert candidate.geometry == source.geometry
    assert source.model_dump_json() == serialized
    assert len(candidate.context.buildings) == len(source.context.buildings)
    for original, prepared in zip(source.context.buildings, candidate.context.buildings):
        assert prepared.identifier == original.identifier
        assert prepared.height_m == original.height_m
        assert prepared.base_elevation_m == original.base_elevation_m
        for p, q in zip(original.footprints, prepared.footprints):
            assert q.holes == p.holes
            assert p.polygon.symmetric_difference(q.polygon).area / p.polygon.area <= 0.10
            assert p.polygon.boundary.hausdorff_distance(q.polygon.boundary) <= tolerance
    assert audit["radius_m"] == 100


def test_courtyard_coordinates_are_exactly_retained(building):
    source = scene(building)
    b = next(b for b in source.context.buildings if "d5d8f5af6b85faf2" in b.identifier)
    f = b.footprints[0]
    p = f.polygon
    hole = p.representative_point().buffer(0.5).exterior.coords
    b = b.updated(footprints=(f.updated(holes=(tuple(hole),)),))
    source = source.updated(context=ContextSpec(buildings=(b,)))
    candidate, _ = simplify_shadow_context(source, 2.0)
    assert candidate is not None
    assert candidate.context.buildings[0].footprints[0].holes == b.footprints[0].holes


def test_rectangle_is_skipped_instead_of_launching_identical_retry(building):
    source = building.updated(
        context=ContextSpec(
            buildings=(
                ContextBuilding(
                    identifier="rectangle",
                    footprints=(
                        Footprint(exterior=((100, 100), (110, 100), (110, 110), (100, 110))),
                    ),
                    height_m=10,
                ),
            )
        )
    )
    candidate, audit = simplify_shadow_context(source, 2.0)
    assert candidate is None
    assert audit["disposition"] == "skipped"


def test_new_overlap_declines_candidate_scene(building):
    source = scene(building)
    _, audit = simplify_shadow_context(source, 2.0)
    item = next(
        x
        for x in audit["footprints"]
        if Polygon(x["prepared_exterior"]).difference(Polygon(x["source_exterior"])).area > 1
    )
    added = Polygon(item["prepared_exterior"]).difference(Polygon(item["source_exterior"]))
    point = added.representative_point()
    tiny = point.buffer(0.01)
    blocker = ContextBuilding(
        identifier="overlap-guard",
        height_m=3,
        footprints=(Footprint(exterior=tuple(tiny.exterior.coords)),),
    )
    source = source.updated(
        context=source.context.updated(buildings=(*source.context.buildings, blocker))
    )
    candidate, audit = simplify_shadow_context(source, 2.0)
    assert candidate is None
    assert audit["reason"] == "contact changed or overlap introduced"


def fake_runner(monkeypatch, outcomes):
    runner = object.__new__(EnergyPlusRunner)
    calls = []

    def run_once(spec, directory, **options):
        directory = Path(directory)
        directory.mkdir(parents=True)
        calls.append(spec)
        outcome = outcomes[len(calls) - 1]
        diagnostics = dict(
            accepted=outcome == "success", messages=[], fatal_count=0, severe_count=0
        )
        (directory / "building.json").write_text(spec.model_dump_json())
        (directory / "model.epJSON").write_text(json.dumps({"attempt": directory.name}))
        if outcome != "success":
            diagnostics["messages"] = [dict(category="shadow_overlap_limit", approved=False)]
            if outcome == "mixed":
                diagnostics["messages"].append(dict(category="invalid_geometry", approved=False))
                diagnostics["severe_count"] = 1
            (directory / "diagnostics.json").write_text(json.dumps(diagnostics))
            raise SimulationError("test rejection", code="SHADOW_COMPLEXITY_LIMIT")
        result = SimulationResult(
            directory.name, {}, {}, {}, diagnostics, {"model": str(directory / "model.epJSON")}
        )
        (directory / "diagnostics.json").write_text(json.dumps(diagnostics))
        (directory / "result.json").write_text(
            json.dumps(dict(run_id=result.run_id, diagnostics=diagnostics, scalars={}, units={}))
        )
        return result

    monkeypatch.setattr(runner, "_run_once", run_once)
    return runner, calls


@pytest.mark.parametrize(
    "outcomes", [["success"], ["shadow", "success"], ["shadow", "shadow", "success"]]
)
def test_stops_at_first_success_and_promotes_matching_model(
    monkeypatch, building, tmp_path, outcomes
):
    runner, calls = fake_runner(monkeypatch, outcomes)
    source = scene(building)
    output = runner.run(source, tmp_path, recover_context_shadows=True)
    assert len(calls) == len(outcomes)
    assert all(s.geometry == source.geometry for s in calls)
    manifest = json.loads((tmp_path / "shadow-recovery.json").read_text())
    assert manifest["selected_attempt"] == output.run_id
    assert manifest["approximation_used"] == (len(outcomes) > 1)
    assert manifest["sensitivity_review_required"] == (len(outcomes) > 1)
    assert json.loads((tmp_path / "model.epJSON").read_text())["attempt"] == output.run_id
    assert json.loads((tmp_path / "result.json").read_text())["run_id"] == output.run_id
    assert Path(output.artifacts["model"]) == tmp_path / "model.epJSON"
    assert len(list((tmp_path / "shadow-recovery").iterdir())) == len(outcomes)


def test_default_is_strict_and_does_not_retry(monkeypatch, building, tmp_path):
    runner, calls = fake_runner(monkeypatch, ["shadow"])
    with pytest.raises(SimulationError):
        runner.run(scene(building), tmp_path / "strict")
    assert len(calls) == 1
    assert not (tmp_path / "strict/shadow-recovery.json").exists()


@pytest.mark.parametrize(
    "outcomes", [["mixed"], ["shadow", "mixed"], ["shadow", "shadow", "shadow"]]
)
def test_mixed_or_exhausted_failure_never_gets_success_marker(
    monkeypatch, building, tmp_path, outcomes
):
    runner, calls = fake_runner(monkeypatch, outcomes)
    with pytest.raises(SimulationError):
        runner.run(scene(building), tmp_path, recover_context_shadows=True)
    assert len(calls) == len(outcomes)
    assert not (tmp_path / "result.json").exists()
    assert not json.loads((tmp_path / "diagnostics.json").read_text())["accepted"]
    assert (tmp_path / "shadow-recovery.json").is_file()


def test_courtyard_in_projection_remains_inside_simplified_outer_ring(building):
    source = scene(building)
    b = next(b for b in source.context.buildings if "d5d8f5af6b85faf2" in b.identifier)
    f = b.footprints[0]
    removed = f.polygon.difference(f.polygon.simplify(2, preserve_topology=True))
    hole = removed.representative_point().buffer(0.005)
    assert f.polygon.contains(hole)
    b = b.updated(footprints=(f.updated(holes=(tuple(hole.exterior.coords),)),))
    source = source.updated(context=ContextSpec(buildings=(b,)))
    candidate, audit = simplify_shadow_context(source, 2.0)
    assert candidate is not None
    prepared = candidate.context.buildings[0].footprints[0]
    assert prepared.polygon.is_valid
    assert prepared.holes == b.footprints[0].holes


def test_empty_context_stops_after_original_shadow_failure(monkeypatch, building, tmp_path):
    runner, calls = fake_runner(monkeypatch, ["shadow"])
    with pytest.raises(SimulationError):
        runner.run(building, tmp_path, recover_context_shadows=True)
    assert len(calls) == 1
    manifest = json.loads((tmp_path / "shadow-recovery.json").read_text())
    assert [a.get("disposition") for a in manifest["attempts"][1:]] == ["skipped", "skipped"]
    assert not manifest["approximation_used"]
