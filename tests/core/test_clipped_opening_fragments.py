"""Thermal-parent splits must not emit sub-engine-length window fragments."""

import numpy as np

from epsm_core.facades import resolve_openings, window_rectangles
from epsm_core.geometry import facade_edges, local_polygons
from epsm_core.surface_checks import MIN_GENERATED_EDGE_M
from epsm_core.topology import Surface, SurfaceGraph


def test_logical_window_clipped_to_thin_parent_fragment_is_omitted(building):
    part = building.geometry.parts[0]
    polygons, _ = local_polygons(building.geometry)
    facade_id, start, end = next(facade_edges(polygons[0], part.identifier))
    length = float(np.linalg.norm(np.array(end) - np.array(start)))
    height = part.storey_elevations_m[1] - part.storey_elevations_m[0]
    layout = building.facade.value_for("layout", facade_id, 0)
    windows, _ = window_rectangles(length, height, building.facade.wwr_for(facade_id, 0), layout)
    split = windows[0][2] - 0.005
    assert 0.01 < split < length - 0.01
    direction = (np.array(end) - np.array(start)) / length

    def face(name, left, right):
        p = np.array(start) + left * direction
        q = np.array(start) + right * direction
        return Surface(
            name=name,
            zone="main",
            vertices=[(*p, 0), (*q, 0), (*q, height), (*p, height)],
            kind="Wall",
            construction="wall",
            boundary="Outdoors",
            part_id=part.identifier,
            facade_id=facade_id,
            storey=0,
            area=(right - left) * height,
            cell_kind="main",
        )

    graph = SurfaceGraph(
        [face("left", 0, split), face("right", split, length)], {}, [], {facade_id}, []
    )
    openings, reports = resolve_openings(building, graph)
    assert openings
    assert any(o.parent == "left" for o in openings)
    assert all(
        min(np.linalg.norm(np.diff(np.vstack([o.vertices, o.vertices[0]]), axis=0), axis=1))
        >= MIN_GENERATED_EDGE_M
        for o in openings
    )
    assert any("Clipped opening fragment omitted" in (r["opening_suppression_reason"] or "") for r in reports)
    for opening in openings:
        points = np.array(opening.vertices)
        xs = (points[:, :2] - np.array(start)) @ direction
        left, right = (0, split) if opening.parent == "left" else (split, length)
        assert min(xs.min() - left, right - xs.max(), points[:, 2].min(), height - points[:, 2].max()) >= 0.010
