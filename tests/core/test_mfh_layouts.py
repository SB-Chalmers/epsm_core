"""Property checks for the experimental, opt-in Shapely floorplate study."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box, shape

from epsm_core.preparation import prepare_geometry
from epsm_core.zoning import validate_partitions
from experiments.mfh_zoning.mfh_layouts import MfhLayoutPolicy, generate_mfh_layout

CORPUS = Path(__file__).parents[1] / "fixtures/mfh_layouts/corpus.json"


def test_saved_mfh_sources_and_preparation_are_reproducible():
    cases = json.loads(CORPUS.read_text())["cases"]
    assert len([c for c in cases if c["group"] == "mfh"]) == 15
    for case in cases:
        source = shape(case["preparation"]["source_geometry"])
        assert hashlib.sha256(source.wkb).hexdigest() == case["source_sha256"]
        fresh = prepare_geometry(source)
        assert fresh.status == case["preparation"]["status"]
        assert fresh.cleaned_geometry.equals_exact(
            shape(case["preparation"]["cleaned_geometry"]), 1e-9)


@pytest.mark.parametrize("polygon", [box(0, 0, 30, 15), box(0, 0, 20, 20),
                                     box(0, 0, 80, 14)])
def test_compact_modules_cover_supported_floorplates(polygon):
    result = generate_mfh_layout(polygon, method="modules")
    assert result.status == "complete", result.reason
    validate_partitions(result.footprint, [*result.common, *result.occupied])
    assert 0 < result.metrics["common_fraction"] <= 0.2
    assert all(25 <= q.area <= 120 for q in result.occupied)
    assert all(u["frontage_m"] >= 1.2 and u["access_m"] >= 0.9
               for u in result.metrics["units"])


def test_rotation_translation_and_ring_order_keep_valid_partition():
    original = box(0, 0, 30, 15)
    reversed_ring = Polygon(list(original.exterior.coords)[::-1])
    for polygon in (original, reversed_ring,
                    rotate(original, 23, origin=(0, 0)),
                    translate(rotate(original, 23, origin=(0, 0)), 320000, 6470000)):
        result = generate_mfh_layout(polygon, method="modules")
        assert result.status == "complete", result.reason
        validate_partitions(result.footprint, [*result.common, *result.occupied])
        assert abs(result.metrics["common_fraction"] - 0.078) < 1e-5


def test_unsupported_geometry_and_exhausted_grid_budget_are_explicit():
    courtyard = box(0, 0, 40, 40).difference(box(10, 10, 30, 30))
    assert generate_mfh_layout(courtyard).reason == "courtyard_requires_reviewed_layout"
    assert generate_mfh_layout(box(0, 0, 8, 8)).reason == "small_footprint"
    exhausted = generate_mfh_layout(
        box(0, 0, 30, 15), MfhLayoutPolicy(max_grid_cells=1), method="grid")
    assert exhausted.status == "fallback"
    assert exhausted.reason == "grid_cell_budget"
