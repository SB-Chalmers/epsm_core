import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from epsm_core.preparation import prepare_geometry

ROOT = Path(__file__).parents[1] / "fixtures/footprints"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


@pytest.mark.parametrize(
    "case", MANIFEST["cases"], ids=lambda c: c["municipality"] + "-" + c["building_id"][:8]
)
def test_raw_corpus(case):
    artifact = json.loads((ROOT / f"{case['municipality']}-{case['building_id']}.json").read_text())
    assert artifact["raw_geometry_verified"]
    result = prepare_geometry(shape(artifact["source_geometry"]))
    assert result.status == case["status"]
    assert result.cleaned_geometry.equals_exact(shape(artifact["cleaned_geometry"]), 1e-8)
    if result.status == "accepted":
        repeated = prepare_geometry(result.cleaned_geometry)
        assert repeated.status == "accepted"
        assert repeated.cleaned_geometry.wkb == result.cleaned_geometry.wkb
        assert result.metrics["source_topology"] == result.metrics["cleaned_topology"]
        assert result.metrics["area_change_fraction"] <= 0.005
        assert result.metrics["perimeter_change_fraction"] <= 0.01
        assert result.metrics["boundary_displacement_m"] <= 0.1
        assert all(edge.source_edges for edge in result.edge_lineage)
