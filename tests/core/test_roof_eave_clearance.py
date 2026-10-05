"""Thin eave features require accepted footprint preparation, never collapsed roofs."""

import math

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from epsm_core import EnergyPlusCompiler, FootprintCleanupSpec, GeometrySpec, RoofSpec
from epsm_core.pipeline import resolve_geometry
from epsm_core.preparation import prepare_geometry
from epsm_core.roofs import roof_faces

# Original local outline from national building d019e49c-e4f0-479f-a5ee-cf3082cf6da0.
OUTLINE = (
    (0, 1.575),
    (20.026, 0),
    (20.234, 3.683),
    (20.563, 10.003),
    (0.579, 11.546),
    (0.589, 11.53),
    (0.575, 11.279),
)


@pytest.mark.parametrize("cleanup", [True, False])
@pytest.mark.parametrize("orientation", [0, 45])
def test_original_thin_eave_requires_preparation(building, cleanup, orientation):
    geometry = GeometrySpec.from_footprint(
        Polygon(OUTLINE),
        storeys=3,
        storey_height_m=2.758827514598058,
        roof=RoofSpec(shape="gable", topology="cold_attic", pitch_deg=30),
        footprint_cleanup=FootprintCleanupSpec(enabled=cleanup),
        orientation_deg=orientation,
    )
    with pytest.raises(ValueError, match="roof facet has zero attic clearance.*prepare_geometry"):
        resolve_geometry(building.updated(geometry=geometry), panelize=True)
    assert geometry.parts[0].footprint.polygon.equals_exact(Polygon(OUTLINE), 0)


@pytest.mark.parametrize("shape", ["gable", "mono_pitch"])
@pytest.mark.parametrize("orientation", [0, 45])
def test_prepared_thin_eave_has_closed_positive_attic(building, shape, orientation):
    source = Polygon(OUTLINE)
    prepared = prepare_geometry(source)
    assert prepared.status == "accepted"
    geometry = GeometrySpec.from_footprint(
        prepared.cleaned_geometry,
        storeys=3,
        storey_height_m=2.758827514598058,
        roof=RoofSpec(shape=shape, topology="cold_attic", pitch_deg=30),
        footprint_cleanup=FootprintCleanupSpec(enabled=False),
        orientation_deg=orientation,
    )
    resolved = resolve_geometry(building.updated(geometry=geometry), panelize=True)
    attic = [f for f in resolved.graph.surfaces if f.cell_kind == "attic"]
    base = geometry.parts[0].storey_elevations_m[-1]
    assert attic
    assert all(max(v[2] for v in f.vertices) > base for f in attic if f.kind == "Roof")
    assert resolved.graph.zones[attic[0].zone]["volume_m3"] > 0
    assert prepared.source_geometry.equals_exact(source, 0)
    record = next(
        a
        for a in resolved.graph.approximations
        if isinstance(a, dict) and a.get("kind") == "generated_eave_height_resolution"
    )
    assert record["operation"] == "collapse_subminimum_rises_reject_zero_clearance_facets"
    assert record["maximum_adjustment_m"] == pytest.approx(0.01001)
    assert record["source_xy_changed"] is False
    # resolve_geometry independently checks reciprocal boundaries, closure and volume.


@pytest.mark.parametrize("shape", ["gable", "mono_pitch"])
def test_ordinary_roof_volume_and_coverage_unchanged(shape):
    polygon = box(0, 0, 20, 10)
    roof = RoofSpec(shape=shape, direction_deg=90 if shape == "gable" else 0, pitch_deg=30)
    faces = roof_faces(polygon, roof, 0)
    volume = sum(
        Polygon([(x, y) for x, y, _ in face]).area * sum(z for _, _, z in face) / 3
        for face in faces
    )
    expected = polygon.area * math.tan(math.radians(30)) * (2.5 if shape == "gable" else 5)
    assert volume == pytest.approx(expected)
    union = unary_union([Polygon([(x, y) for x, y, _ in f]) for f in faces])
    assert union.symmetric_difference(polygon).area < 1e-8


def test_prepared_thin_eave_emits_valid_energyplus_model(building, energyplus):
    prepared = prepare_geometry(Polygon(OUTLINE))
    assert prepared.status == "accepted"
    geometry = GeometrySpec.from_footprint(
        prepared.cleaned_geometry,
        storeys=3,
        storey_height_m=2.758827514598058,
        roof=RoofSpec(shape="gable", topology="cold_attic", pitch_deg=30),
        footprint_cleanup=FootprintCleanupSpec(enabled=False),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(building.updated(geometry=geometry))
    assert report.data["validation"]["status"] == "passed"
    assert model["BuildingSurface:Detailed"]
