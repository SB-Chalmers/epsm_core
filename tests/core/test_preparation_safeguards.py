"""Adversarial cleanup cases: cancellation, contacts and physical edge references."""

import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from epsm_core import (
    BalconySpec,
    FacadeOverride,
    FootprintCleanupSpec,
    GeometryPolicy,
    GeometrySpec,
)
from epsm_core.inspection import geometry_scene
from epsm_core.preparation import (
    component_contacts_preserved,
    geometry_change_metrics,
    prepare_geometry,
)


def cancelling_outline(amplitude):
    return Polygon(
        [(0, 0), (0.25, -amplitude), (0.5, 0), (0.75, amplitude), (1, 0), (1, 1), (0, 1)]
    )


def test_net_area_cannot_hide_exchanged_outline():
    result = prepare_geometry(cancelling_outline(0.02))
    assert result.metrics["area_change_fraction"] == pytest.approx(0, abs=1e-12)
    assert result.metrics["symmetric_difference_fraction"] == pytest.approx(0.01)
    assert result.status == "needs_review"
    assert "symmetric_difference_fraction_exceeded" in result.reasons
    assert result.metrics["perimeter_change_fraction"] < result.policy.max_perimeter_fraction


def test_automatic_v2_rejects_cancellation_but_explicit_v1_remains_supported():
    g = GeometrySpec.from_footprint(cancelling_outline(0.004), storeys=1, storey_height_m=3)
    with pytest.raises(ValueError, match="symmetric_difference_fraction"):
        _ = g.footprints
    legacy = g.updated(
        footprint_cleanup=FootprintCleanupSpec(implementation_version="footprint-cleanup-1")
    )
    assert legacy.footprints[0].area_m2 == pytest.approx(1)


def test_automatic_perimeter_limit_is_independent_of_area_limit():
    g = GeometrySpec.from_footprint(
        cancelling_outline(0.004),
        storeys=1,
        storey_height_m=3,
        footprint_cleanup=FootprintCleanupSpec(
            max_symmetric_difference_fraction=1, max_perimeter_change_fraction=0
        ),
    )
    with pytest.raises(ValueError, match="perimeter_change_fraction"):
        _ = g.footprints


def test_contact_partner_switch_is_detected_despite_equal_contact_count():
    old = MultiPolygon([box(0, 0, 1, 1), box(1, 1, 2, 2), box(2.1, 2, 3.1, 3)])
    new = MultiPolygon([box(0, 0, 1, 1), box(1.1, 1, 2.1, 2), box(2.1, 2, 3.1, 3)])
    assert old.is_valid and new.is_valid
    assert not component_contacts_preserved(old, new, 0.001)
    assert component_contacts_preserved(old, MultiPolygon(list(reversed(old.geoms))), 0)


def test_invalid_source_does_not_acquire_a_reliable_outline_metric():
    source = Polygon([(0, 0), (1, 1), (0, 1), (1, 0)])
    assert geometry_change_metrics(source, box(0, 0, 1, 1))["symmetric_difference_fraction"] is None
    assert prepare_geometry(source).status != "accepted"


@pytest.mark.parametrize("reference", ["balcony", "override"])
def test_compile_and_preview_protect_source_edge_references(building, energyplus, reference):
    from epsm_core import EnergyPlusCompiler

    geometry = GeometrySpec.from_footprint(
        Polygon([(0, 0), (5, 0), (10, 0), (10, 8), (0, 8)]), storeys=1, storey_height_m=3
    )
    facade = building.facade.updated(
        **(
            {"balconies": (BalconySpec(facade_id="main.r0.e1", width_m=2, depth_m=1),)}
            if reference == "balcony"
            else {"overrides": (FacadeOverride(facade_id="main.r0.e1", wwr=0.3),)}
        )
    )
    spec = building.updated(geometry=geometry, facade=facade)
    with pytest.raises(ValueError, match="referenced facade IDs"):
        geometry_scene(geometry, facade=facade)
    with pytest.raises(ValueError, match="referenced facade IDs"):
        EnergyPlusCompiler(energyplus).compile(spec)
    raw = geometry.updated(footprint_cleanup=FootprintCleanupSpec(enabled=False))
    scene, _ = geometry_scene(raw, facade=facade)
    assert scene["BuildingSurface:Detailed"]


def test_new_policy_limit_requires_finite_nonnegative_value():
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            GeometryPolicy(max_symmetric_difference_fraction=bad)


def test_automatic_lineage_reports_merged_source_runs():
    from epsm_core.footprint_cleanup import prepared_footprints

    g = GeometrySpec.from_footprint(
        Polygon([(0, 0), (5, 0), (10, 0), (10, 8), (0, 8)]), storeys=1, storey_height_m=3
    )
    _, report = prepared_footprints(g)
    lineage = report["parts"][0]["edge_lineage"]
    merged = next(e for e in lineage if len(e["source_edges"]) == 2)
    assert merged["source_edges"] == ["main.r0.e0", "main.r0.e1"]
    assert merged["changed"]
    assert all(e["source_edges"] for e in lineage)


def test_reference_guard_allows_changes_in_unreferenced_parts(building):
    from epsm_core import Footprint
    from epsm_core.footprint_cleanup import prepared_footprints, validate_facade_references

    main = building.geometry.parts[0]
    annex = main.updated(
        identifier="annex",
        footprint=Footprint(exterior=((40, 0), (45, 0), (50, 0), (50, 8), (40, 8))),
    )
    geometry = building.geometry.updated(parts=(main, annex))
    facade = building.facade.updated(
        balconies=(BalconySpec(facade_id="main.r0.e0", width_m=2, depth_m=1),)
    )
    _, report = prepared_footprints(geometry)
    assert next(p for p in report["parts"] if p["part_id"] == "annex")["changed"]
    validate_facade_references(geometry, facade, report)
