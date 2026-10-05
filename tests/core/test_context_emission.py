"""Direct-solar geometry preservation for below-datum and touching context."""

from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from epsm_core import EnergyPlusCompiler, EnergyPlusRunner
from epsm_core.context import ContextSurface, emittable_context_surfaces
from epsm_core.specs import ContextBuilding, ContextSpec, Footprint
from epsm_core.surface_checks import properties


def hits(faces, receiver, ray):
    receiver = np.asarray(receiver)
    ray = np.asarray(ray)
    result = []
    for face in faces:
        p = np.asarray(face.vertices)
        _, n, _ = properties(p)
        denominator = n @ ray
        if abs(denominator) < 1e-10:
            continue
        t = (n @ (p[0] - receiver)) / denominator
        if t < 1e-8:
            continue
        point = receiver + t * ray
        axis = int(np.argmax(np.abs(n)))
        indices = [i for i in range(3) if i != axis]
        if Polygon(p[:, indices]).buffer(1e-8).covers(Point(point[indices])):
            result.append(float(t))
    return min(result) if result else None


def test_clipping_preserves_original_above_receiver_vertices_and_sun_hits():
    wall = ContextSurface(
        "wall", ((10, -5, -15), (10, 5, -15), (10, 5, 5), (10, -5, 5)), "n", 0, "Wall"
    )
    roof = ContextSurface(
        "roof", ((10, -5, 5), (20, -5, 5), (20, 5, 5), (10, 5, 5)), "n", 0, "Roof"
    )
    emitted, audit = emittable_context_surfaces((wall, roof), ((0, 0, 0), (0, 0, 2)))
    assert audit["clipped"][0]["name"] == "wall"
    assert min(v[2] for f in emitted for v in f.vertices) >= 0
    assert (10, 5, 5) in emitted[0].vertices and (10, -5, 5) in emitted[0].vertices
    for height in (0, 1, 2, 4):
        for lateral in (-0.4, 0, 0.4):
            for rise in (0.01, 0.1, 0.4, 1):
                ray = (1, lateral, rise)
                before = hits((wall, roof), (0, 0, height), ray)
                after = hits(emitted, (0, 0, height), ray)
                assert (before is None) == (after is None)
                if before is not None:
                    assert before == pytest.approx(after)


def test_internal_interfaces_aliases_and_below_receiver_faces_are_audited():
    wall = ContextSurface(
        "wall", ((10, -5, 0), (10, 5, 0), (10, 5, 5), (10, -5, 5)), "n", 0, "Wall"
    )
    opposite = replace(wall, name="opposite", vertices=wall.vertices[::-1], building_id="other")
    emitted, audit = emittable_context_surfaces((wall, opposite), ((0, 0, 0),))
    assert not emitted
    assert len(audit["omitted"]) == 2
    alias = replace(wall, name="alias")
    emitted, audit = emittable_context_surfaces((wall, alias), ((0, 0, 0),))
    assert len(emitted) == 1
    underground = replace(
        wall, name="underground", vertices=tuple((x, y, z - 20) for x, y, z in wall.vertices)
    )
    emitted, audit = emittable_context_surfaces((underground,), ((0, 0, 0),))
    assert not emitted
    assert audit["warning_acceptance_changed"] is False


def test_actual_negative_receivers_are_not_silently_moved_to_grade():
    wall = ContextSurface(
        "wall", ((10, -5, -2), (10, 5, -2), (10, 5, 5), (10, -5, 5)), "n", 0, "Wall"
    )
    emitted, audit = emittable_context_surfaces((wall,), ((0, 0, -3),))
    assert emitted[0].vertices == wall.vertices
    assert audit["minimum_outdoor_receiver_z_m"] == -3


def test_native_context_clipping_uses_outdoor_faces_and_preserves_source(building, energyplus):
    context = ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="lower-terrain",
                footprints=(Footprint(exterior=((32, 0), (42, 0), (42, 10), (32, 10))),),
                base_elevation_m=-15,
                height_m=20,
            ),
        )
    )
    spec = building.updated(
        context=context,
        geometry=building.geometry.updated(basement_depth_m=2.5, basement_conditioned=True),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert report.data["context"]["emission"]["minimum_outdoor_receiver_z_m"] == 0
    assert report.data["context"]["emission"]["source_shells_preserved"]
    assert spec.context.buildings[0].base_elevation_m == -15
    assert all(
        v["vertex_z_coordinate"] >= 0
        for x in model["Shading:Building:Detailed"].values()
        for v in x["vertices"]
    )
    assert report.data["conditioned_floor_area_m2"] > 0
    assert all(
        v["vertex_z_coordinate"] == 0
        for x in model["Shading:Site:Detailed"].values()
        for v in x["vertices"]
    )


@pytest.mark.energyplus
def test_lower_terrain_context_passes_strict_annual_engine_policy(building, energyplus, tmp_path):
    context = ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="lower-terrain",
                footprints=(Footprint(exterior=((32, 0), (42, 0), (42, 10), (32, 10))),),
                base_elevation_m=-15,
                height_m=20,
            ),
        )
    )
    result = EnergyPlusRunner(energyplus).run(
        building.updated(
            context=context,
            geometry=building.geometry.updated(basement_depth_m=2.5, basement_conditioned=True),
        ),
        tmp_path / "lower",
    )
    assert result.diagnostics["severe_count"] == 0
    assert result.scalars["space_heating_demand_kwh"] > 0


# Local coordinates of the neighbour cap that triggered two small-area warnings
# for national case ef0d3a3f-6dea-4748-a79d-0d64bc8ca554 (5 October 2026).
SMALL_CAP = (
    (0.3586873390013352, 9.651631633751094),
    (0.33382968459045514, 9.653134286403656),
    (0.3297248505987227, 9.58765232283622),
    (0.0, 4.278285555541515),
    (71.55388463661075, 0.0),
    (71.93468045210466, 5.377569111064076),
    (34.21443923958577, 7.628258845768869),
)


def test_cap_coalescing_preserves_exact_coverage_boundary_and_sun_hits():
    from shapely.ops import unary_union

    from epsm_core.context import _context_horizontal_patches
    from epsm_core.geometry import horizontal_patches, horizontal_vertices

    footprint = Polygon(SMALL_CAP)
    original = horizontal_patches(footprint)
    patches, audit = _context_horizontal_patches(footprint)
    assert min(p.area for p in original) < 0.001
    assert min(p.area for p in patches) >= 0.001
    assert audit["merged_patch_count"] == 2
    assert audit["remaining_small_patch_count"] == 0
    assert unary_union(patches).equals(footprint)
    assert sum(p.area for p in patches) == pytest.approx(footprint.area)
    boundary_nodes = {
        xy for p in patches for xy in p.exterior.coords if footprint.boundary.covers(Point(xy))
    }
    assert set(footprint.exterior.coords) <= boundary_nodes
    assert all(p.equals(p.convex_hull) and len(p.exterior.coords) <= 5 for p in patches)

    def cap_faces(polygons):
        return tuple(
            ContextSurface(str(i), tuple(horizontal_vertices(p, 8)), "n", 0, "Roof")
            for i, p in enumerate(polygons)
        )

    for x in (0, 1, 10, 35, 71):
        for y in (0, 3, 6, 10):
            before = hits(cap_faces(original), (x, y, 0), (0, 0, 1))
            after = hits(cap_faces(patches), (x, y, 0), (0, 0, 1))
            assert before == after


def test_cap_coalescing_keeps_courtyard_holes():
    from shapely.ops import unary_union

    from epsm_core.context import _context_horizontal_patches

    footprint = Polygon(
        ((0, 0), (20, 0), (20, 20), (0, 20)), holes=[((5, 5), (5, 15), (15, 15), (15, 5))]
    )
    patches, audit = _context_horizontal_patches(footprint)
    assert unary_union(patches).equals(footprint)
    assert not unary_union(patches).covers(Point(10, 10))
    assert audit["symmetric_difference_m2"] == 0


def test_unmergeable_small_cap_is_preserved_and_reported():
    from epsm_core.context import _context_horizontal_patches

    footprint = Polygon(((0, 0), (0.03, 0), (0, 0.03)))
    patches, audit = _context_horizontal_patches(footprint)
    assert patches[0].equals(footprint)
    assert audit["remaining_small_patch_count"] == 1
    assert audit["merged_patch_count"] == 0


@pytest.mark.energyplus
def test_small_cap_passes_strict_engine_policy_after_exact_coalescing(
    building, energyplus, tmp_path
):
    context = ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="cap-sliver",
                footprints=(Footprint(exterior=tuple((x + 40, y) for x, y in SMALL_CAP)),),
                height_m=8,
            ),
        )
    )
    result = EnergyPlusRunner(energyplus).run(
        building.updated(context=context), tmp_path / "cap", review_psychrometric_warnings=False
    )
    assert result.diagnostics["accepted"]
    assert not result.diagnostics["messages"]


def test_small_surface_warning_remains_a_geometry_rejection(tmp_path):
    from epsm_core.diagnostics import error_diagnostics
    from epsm_core.failures import GEOMETRY_INVARIANT_FAILURE, engine_failure_code

    path = tmp_path / "eplusout.err"
    path.write_text(
        "   ** Warning ** GetSurfaceData: Very small surface area[5.0E-004], Surface=CAP\n"
    )
    diagnostics = error_diagnostics(path)
    assert not diagnostics["accepted"]
    assert diagnostics["messages"][0]["category"] == "invalid_geometry"
    assert engine_failure_code(diagnostics) == GEOMETRY_INVARIANT_FAILURE
