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
