import pytest
from shapely import constrained_delaunay_triangles, unary_union
from shapely.geometry import Polygon, box
from epsm_core.geometry import horizontal_patches


@pytest.mark.parametrize('polygon', [
    box(0,0,10,8),
    Polygon([(0,0),(10,0),(10,3),(3,3),(3,8),(0,8)]),
    Polygon([(0,0),(10,0),(10,8),(0,8)], [[(3,3),(3,5),(5,5),(5,3)]]),
    Polygon([(0,0),(6,0),(9,3),(9,6),(6,9),(0,9),(-3,6),(-3,3)]),
])
def test_horizontal_patches_are_convex_conservative_and_repeatable(polygon):
    faces = horizontal_patches(polygon)
    assert all(p.equals(p.convex_hull) and len(p.exterior.coords) <= 5 and not p.interiors for p in faces)
    assert all(p.exterior.is_ccw for p in faces)
    assert sum(p.area for p in faces) == pytest.approx(polygon.area, rel=1e-12)
    assert unary_union(faces).symmetric_difference(polygon).area < 1e-9
    assert [p.wkb for p in faces] == [p.wkb for p in horizontal_patches(polygon)]
    if polygon.equals(box(0,0,10,8)):
        assert len(faces) == 1
