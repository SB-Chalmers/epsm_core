"""Bounded preparation of real small-cap context outlines, preserving source evidence."""

import json
from pathlib import Path

import pytest
from shapely.affinity import scale
from shapely.geometry import Point, Polygon, box

from epsm_core import EnergyPlusCompiler
from epsm_core.context import (
    _prepare_small_context_caps,
    mirror_suppression_eligibility,
    resolve_context,
)
from epsm_core.specs import ContextBuilding, ContextSpec, Footprint, GeometrySpec

CASES = json.loads(
    (Path(__file__).parent / "fixtures/small_context_cap_footprints.json").read_text()
)


def footprint(p):
    return Footprint(
        exterior=tuple(p.exterior.coords), holes=tuple(tuple(r.coords) for r in p.interiors)
    )


def setup_case(case, *, polygon=None, enabled=True):
    p = Polygon(case["exterior"], holes=case["holes"]) if polygon is None else polygon
    target = GeometrySpec.from_footprint(
        footprint(box(-50, -50, -40, -40)), storeys=1, storey_height_m=3
    )
    context = ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="neighbour", footprints=(footprint(p),), height_m=case["height_m"]
            ),
        ),
        simplify_small_caps=enabled,
    )
    return target, context


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["context_id"])
def test_real_small_caps_prepare_closed_shells_without_mutating_source(case):
    geometry, context = setup_case(case)
    source = context.model_dump_json()
    resolved = resolve_context(geometry, context)
    cleanup = resolved.report["footprint_cleanup"]
    assert cleanup["applied_count"] == 1
    record = cleanup["footprints"][0]
    assert record["max_boundary_displacement_m"] <= 0.05
    assert record["symmetric_difference_area_fraction"] <= 0.005
    assert record["perimeter_change_fraction"] <= 0.01
    assert all(v["remaining_small_patch_count"] == 0 for v in resolved.report["cap_tessellation"])
    assert context.model_dump_json() == source
    assert mirror_suppression_eligibility(resolved)["mirror_suppression_eligible"]
    assert resolved.report["buildings"][0]["volume_m3"] == pytest.approx(
        record["prepared_area_m2"] * case["height_m"]
    )
    assert resolved.report["buildings"][0]["source_volume_m3"] == pytest.approx(
        footprint(Polygon(case["exterior"], holes=case["holes"])).area_m2 * case["height_m"]
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["context_id"])
def test_strict_optout_preserves_real_outlines_and_small_caps(case):
    geometry, context = setup_case(case, enabled=False)
    resolved = resolve_context(geometry, context)
    assert resolved.report["footprint_cleanup"]["applied_count"] == 0
    assert any(v["remaining_small_patch_count"] for v in resolved.report["cap_tessellation"])
    assert resolved.report["buildings"][0]["volume_m3"] == pytest.approx(
        resolved.report["buildings"][0]["source_volume_m3"]
    )


def test_large_relative_changes_are_declined_even_within_five_centimetres():
    ring = [list(v) for v in CASES[0]["exterior"]]
    anchor = ring[0]
    ring[1:3] = [
        [anchor[0] + 2 * (x - anchor[0]), anchor[1] + 2 * (y - anchor[1])] for x, y in ring[1:3]
    ]
    p = scale(Polygon(ring), xfact=0.02, yfact=0.02, origin=(0, 0))
    geometry, context = setup_case(CASES[0], polygon=p)
    prepared, audit = _prepare_small_context_caps(geometry, context, (0, 0))
    assert prepared[0].equals_exact(p, 0)
    assert audit["applied_count"] == 0
    assert audit["footprints"][0]["symmetric_difference_area_fraction"] > 0.005
    assert "bounds" in audit["footprints"][0]["reason"]


def test_new_neighbour_overlap_or_changed_contact_declines_entire_candidate():
    case = CASES[1]
    p = Polygon(case["exterior"])
    q = p.simplify(0.05, preserve_topology=True).simplify(0, preserve_topology=True)
    added = q.difference(p)
    assert added.area > 0
    neighbours = list(added.geoms) if added.geom_type == "MultiPolygon" else [added]
    geometry, context = setup_case(case)
    context = context.updated(
        buildings=(
            *context.buildings,
            *(
                ContextBuilding(identifier=f"contact-{i}", footprints=(footprint(v),), height_m=3)
                for i, v in enumerate(neighbours)
            ),
        )
    )
    prepared, audit = _prepare_small_context_caps(geometry, context, (0, 0))
    assert prepared[0].equals_exact(p, 0)
    assert "contact/overlap" in audit["footprints"][0]["reason"]


def test_courtyard_and_ordinary_rectangular_context_are_preserved():
    p = Polygon(CASES[1]["exterior"], holes=[box(5, 5, 8, 8).exterior.coords])
    assert p.is_valid
    geometry, context = setup_case(CASES[1], polygon=p)
    prepared, audit = _prepare_small_context_caps(geometry, context, (0, 0))
    assert audit["applied_count"] == 1
    assert len(prepared[0].interiors) == 1
    assert not prepared[0].covers(Point(6, 6))
    geometry, context = setup_case(CASES[1], polygon=box(0, 0, 10, 10))
    prepared, audit = _prepare_small_context_caps(geometry, context, (0, 0))
    assert prepared[0].equals_exact(box(0, 0, 10, 10), 0)
    assert audit["applied_count"] == 0


def test_native_compiler_reports_preparation_and_leaves_thermal_footprint_unchanged(
    building, energyplus
):
    case = CASES[0]
    p = Polygon([(x + 50, y + 50) for x, y in case["exterior"]])
    _, context = setup_case(case, polygon=p)
    spec = building.updated(context=context)
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert report.data["context"]["footprint_cleanup"]["applied_count"] == 1
    assert report.data["context"]["mirror_suppression_eligible"]
    assert report.data["context"]["detached_mirroring_disabled"]
    assert report.data["conditioned_floor_area_m2"] == pytest.approx(1800)
    assert model["Shading:Building:Detailed"]
    assert spec.geometry == building.geometry


def test_synthetic_generation_preserves_explicit_preparation_optout():
    from epsm_core.context import synthetic_context

    geometry, context = setup_case(CASES[0], enabled=False)
    generated = synthetic_context(geometry, "rural", existing=context, radius_m=60)
    assert generated.simplify_small_caps is False
    assert generated.buildings[0] == context.buildings[0]
