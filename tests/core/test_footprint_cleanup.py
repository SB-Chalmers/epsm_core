"""Bounded preparation and real-building regression geometry."""

from pathlib import Path

import pytest
from epsm_core import (
    EnergyPlusCompiler,
    Footprint,
    FootprintCleanupSpec,
    GeometrySpec,
    PartyWall,
    ZoningSpec,
)
from epsm_core.footprint_cleanup import prepared_footprints
from shapely.geometry import Polygon


def make(points, **kwargs):
    return GeometrySpec.from_footprint(Polygon(points), storeys=2, storey_height_m=3, **kwargs)


def test_default_cleanup_and_explicit_source_preservation():
    points = [(0, 0), (5, 0), (5, 0), (10, 0), (10, 8), (0, 8)]
    g = make(points)
    raw = g.updated(footprint_cleanup=FootprintCleanupSpec(enabled=False))
    assert g.parts[0].footprint == raw.parts[0].footprint
    assert len(g.footprints[0].exterior) == 4
    assert len(raw.footprints[0].exterior) == 6
    assert g.conditioned_floor_area_m2 == raw.conditioned_floor_area_m2 == 160
    polygons, report = prepared_footprints(g)
    assert report["version"] == "footprint-cleanup-1"
    assert report["parts"][0]["source_vertices"] == 6
    again = GeometrySpec.from_footprint(polygons[0], storeys=2, storey_height_m=3)
    assert again.footprints == g.footprints
    assert prepared_footprints(g) == prepared_footprints(g)


def test_area_limit_and_invalid_source():
    g = make([(0, 0), (0.05, -0.005), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    with pytest.raises(ValueError, match="area/displacement"):
        _ = g.footprints
    with pytest.raises(ValueError):
        make([(0, 0), (10, 10), (0, 10), (10, 0)])


def test_holes_and_explicit_references_are_preserved():
    p = Polygon(
        [(0, 0), (40, 0), (40, 40), (0, 40)], holes=[[(10, 10), (10, 30), (30, 30), (30, 10)]]
    )
    g = GeometrySpec.from_footprint(p, storeys=1, storey_height_m=3)
    assert len(g.footprints[0].holes) == 1
    assert g.conditioned_floor_area_m2 == 1200
    g = make([(0, 0), (5, 0), (10, 0), (10, 8), (0, 8)])
    g = g.updated(
        party_walls=(
            PartyWall(
                facade_id="main.r0.e0",
                neighbor_id="next",
                neighbor_conditioning="heated",
                contact_confirmed=True,
                assumption_source="survey",
            ),
        )
    )
    with pytest.raises(ValueError, match="referenced facade"):
        _ = g.footprints


@pytest.mark.parametrize(
    "name",
    [p.stem for p in (Path(__file__).parents[1] / "fixtures/zoning_regressions").glob("*.json")],
)
@pytest.mark.parametrize("depth", [3, 4.5, 6])
def test_real_building_zones_compile_preserve_totals(building, energyplus, name, depth):
    root = Path(__file__).parents[1] / "fixtures/zoning_regressions"
    g = GeometrySpec.model_validate_json((root / (name + ".json")).read_text())
    base = building.updated(geometry=g)
    zoned = base.updated(
        geometry=g.updated(zoning=ZoningSpec(mode="perimeter_core", depth_m=depth))
    )
    compiler = EnergyPlusCompiler(energyplus)
    a, ra = compiler.compile(base)
    b, rb = compiler.compile(zoned)
    assert rb.data["zoning"]["effective_mode"] == "perimeter_core"
    assert rb.data["conditioned_floor_area_m2"] == pytest.approx(
        ra.data["conditioned_floor_area_m2"], abs=1e-5
    )
    assert rb.data["conditioned_volume_m3"] == pytest.approx(
        ra.data["conditioned_volume_m3"], abs=1e-5
    )
    assert a["Material"] == b["Material"]
    assert a["Construction"] == b["Construction"]
    assert sum(
        x["exposed_perimeter_m"] for x in rb.data["foundation"]["assignments"]
    ) == pytest.approx(
        sum(x["exposed_perimeter_m"] for x in ra.data["foundation"]["assignments"]), abs=1e-5
    )
    assert base.airflow.envelope_infiltration_ach == zoned.airflow.envelope_infiltration_ach


def test_shared_contact_and_disconnected_parts():
    from epsm_core import BuildingPart

    a = BuildingPart(
        identifier="a", footprint=Footprint.rectangle(10, 10), storey_elevations_m=(0, 3)
    )
    b = BuildingPart(
        identifier="b",
        footprint=Footprint(exterior=((10, 0), (20, 0), (20, 10), (10, 10))),
        storey_elevations_m=(0, 3),
    )
    g = GeometrySpec(parts=(a, b))
    p, _ = prepared_footprints(g)
    assert p[0].intersection(p[1]).length == 10
    b = b.updated(footprint=Footprint(exterior=((30, 0), (40, 0), (40, 10), (30, 10))))
    p, _ = prepared_footprints(g.updated(parts=(a, b)))
    assert p[0].intersection(p[1]).is_empty


def test_generated_ring_cleanup_checks_starting_vertex():
    from epsm_core.vertex_order import clean_generated_ring

    points = ((5, 0, 0), (10, 0, 0), (10, 8, 0), (0, 8, 0), (0, 0, 0))
    cleaned = clean_generated_ring(points)
    assert len(cleaned) == 4
    assert (5, 0, 0) not in cleaned
    assert set(cleaned).issubset(points)


def test_cleanup_changes_physical_hash_and_reports_source(building, energyplus):
    raw = building.updated(
        geometry=building.geometry.updated(footprint_cleanup=FootprintCleanupSpec(enabled=False))
    )
    assert raw.physical_hash() != building.physical_hash()
    model, report = EnergyPlusCompiler(energyplus).compile(building)
    assert report.data["footprint_cleanup"]["settings"]["enabled"]
    assert report.data["footprint_cleanup"]["source_sha256"]
