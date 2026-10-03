"""Skewed source footprints retain coverage under strict generated-edge checks."""

import numpy as np
import pytest
from epsm_core.roofs import roof_faces
from epsm_core.specs import RoofSpec
from epsm_core.surface_checks import MIN_EDGE_M, properties
from epsm_core.vertex_order import clean_generated_ring
from shapely import Polygon, unary_union


def test_skewed_eave_uses_same_height_in_roof_and_wall():
    polygon = Polygon([(0, 0), (20, 0.0002), (20, 10), (0, 10)])
    faces = roof_faces(polygon, RoofSpec(shape="gable", pitch_deg=30), 6)
    assert (
        unary_union([Polygon([(x, y) for x, y, z in f]) for f in faces])
        .symmetric_difference(polygon)
        .area
        < 1e-7
    )
    assert any(x == 20 and y == 0.0002 and z == 6 for f in faces for x, y, z in f)
    for face in faces:
        properties(np.array(face))
    with pytest.raises(ValueError, match="Near-coincident"):
        properties(np.array([(0, 0, 6), (0, 0, 6 + MIN_EDGE_M / 2), (10, 0, 8)]))


def test_ring_keeps_pooled_vertex_objects():
    points = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)]
    assert all(a is b for a, b in zip(points, clean_generated_ring(points)))
