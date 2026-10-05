"""Exact wall tessellation prevents short ridge/floor T-junction enclosure failures."""

import json
from pathlib import Path

import pytest

from epsm_core import EnergyPlusRunner, GeometrySpec
from epsm_core.pipeline import resolve_geometry
from epsm_core.roofs import _unsplit_convex_attic_wall
from epsm_core.surface_checks import properties


def test_convex_gable_wall_keeps_ridge_and_full_floor_edge():
    nodes = [(0, 0, 0, 4), (9.967, 9.967, 0, 5), (10, 10, 0, 4.98)]
    wall = _unsplit_convex_attic_wall(nodes, 0)
    assert wall is not None and len(wall) == 5
    assert wall[:2] == [[0, 0, 0], [10, 0, 0]]
    assert [9.967, 0, 5] in wall
    expected = 9.967 * 4.5 + 0.033 * 4.99
    assert properties(wall)[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    "nodes",
    [
        [(0, 0, 0, 4), (5, 5, 0, 3), (10, 10, 0, 4)],  # concave roof profile
        [(0, 0, 0, 4), (5, 5, 0, 4), (10, 10, 0, 4)],  # redundant top vertex
        [(0, 0, 0, 4), (5, 5, 0, 5), (9.995, 9.995, 0, 4.01), (10, 10, 0, 4)],
    ],
)
def test_unqualified_wall_profiles_keep_segmented_representation(nodes):
    assert _unsplit_convex_attic_wall(nodes, 0) is None


def original_geometry():
    # Anonymised measured outline from a5318d1c-ca1f-460b-98f7-9dcafe654629.
    # The same geometry produced MAIN_ATTIC_WALL_37's 33 mm unmatched edge.
    return GeometrySpec.model_validate(
        json.loads((Path(__file__).parent / "fixtures" / "attic_ridge_tjunction.json").read_text())
    )


def test_original_attic_has_closed_boundaries_and_unsplit_convex_walls(building):
    resolved = resolve_geometry(building.updated(geometry=original_geometry()), panelize=True)
    walls = [f for f in resolved.graph.surfaces if f.cell_kind == "attic" and f.kind == "Wall"]
    assert any(len(f.vertices) == 5 for f in walls)
    assert all(properties(f.vertices)[0] > 0 for f in walls)
    # resolve_geometry checks directed-edge incidence and volume for every zone.


@pytest.mark.energyplus
def test_original_attic_passes_engine_enclosure_checks(building, energyplus, tmp_path):
    result = EnergyPlusRunner(energyplus).run(
        building.updated(geometry=original_geometry()),
        tmp_path / "ridge",
        review_psychrometric_warnings=False,
    )
    assert result.diagnostics["accepted"]
    assert not any(
        "not fully enclosed" in m["original_text"] for m in result.diagnostics["messages"]
    )
