import numpy as np
import pytest
from shapely.geometry import Polygon

from epsm_core import EnergyPlusCompiler
from epsm_core.context import resolve_context, visible_context_surfaces
from epsm_core.specs import ContextBuilding, ContextSpec, Footprint
from epsm_core.surface_checks import properties
from epsm_core.viewer import viewer_data


def context(base=0):
    return ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="block",
                footprints=(Footprint(exterior=((50, 0), (60, 0), (60, 10), (50, 10))),),
                height_m=15,
                base_elevation_m=base,
            ),
        )
    )


@pytest.mark.parametrize("angle", [0, 37, 181])
def test_visibility_keeps_complete_physical_preview(building, energyplus, angle):
    spec = building.updated(
        context=context(), geometry=building.geometry.updated(orientation_deg=angle)
    )
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    full = resolve_context(spec.geometry, spec.context)
    visibility = report.data["context"]["visibility"]
    assert 0 < visibility["retained_count"] < visibility["original_count"] == len(full.surfaces)
    shown = [o for o in viewer_data(model, report.data)["objects"] if o["kind"] == "context"]
    assert {o["name"] for o in shown} == {o.name for o in full.surfaces}
    assert sum(o["area_m2"] for o in shown) == pytest.approx(
        sum(properties(np.array(o.vertices))[0] for o in full.surfaces)
    )
    for o in shown:
        source = next(s for s in full.surfaces if s.name == o["name"])
        assert {tuple(p) for p in o["vertices"]} == set(source.vertices)


def test_elevated_closed_context_keeps_visible_bottom(building):
    resolved = resolve_context(building.geometry, context(base=2))
    retained, audit = visible_context_surfaces(resolved, [(0, 0, 0), (30, 20, 8.4)])
    assert any(face.kind == "Floor" for face in retained)
    assert audit["hidden"]


def test_grade_bottom_is_audited_but_not_emitted(building, energyplus):
    """Closed-shell proof caps at target grade must not enter shadow overlap."""
    spec = building.updated(context=context())
    resolved = resolve_context(spec.geometry, spec.context)
    assert any(face.kind == "Floor" for face in resolved.surfaces)

    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    emitted = set(model["Shading:Building:Detailed"])
    grade_caps = {face.name for face in resolved.surfaces if face.kind == "Floor"}
    assert emitted.isdisjoint(grade_caps)
    omissions = report.data["context"]["visibility"]["hidden"]
    assert grade_caps <= {
        item["name"]
        for item in omissions
        if item["reason"].startswith("Bottom cap at or below every receiver")
    }
    assert report.data["context"]["mirror_suppression_eligible"]
    hint = model["Shading:Site:Detailed"]["epsm_shadow_overlap_vertex_capacity"]
    hint_points = [
        (vertex["vertex_x_coordinate"], vertex["vertex_y_coordinate"])
        for vertex in hint["vertices"]
    ]
    assert hint["number_of_vertices"] == len(hint_points) == 16
    # The hint is inside the target ground plane, not any context cap. Check
    # against the emitted target floors to make the physical-inertness proof.
    target_ground = [
        Polygon(
            [
                (vertex["vertex_x_coordinate"], vertex["vertex_y_coordinate"])
                for vertex in surface["vertices"]
            ]
        )
        for surface in model["BuildingSurface:Detailed"].values()
        if surface["surface_type"] == "Floor"
        and surface["outside_boundary_condition"] == "Ground"
    ]
    assert any(polygon.contains(Polygon(hint_points)) for polygon in target_ground)
    assert report.data["context"]["shadow_overlap_vertex_capacity"] == {
        "method": "contained_ground_polygon",
        "surface": "epsm_shadow_overlap_vertex_capacity",
        "input_vertices": 16,
        "energyplus_24_2_capacity": 31,
    }


def test_visibility_retains_grazing_faces_and_is_deterministic(building):
    resolved = resolve_context(building.geometry, context())
    points = np.array([(0, 0, 0), (30, 0, 8.4), (30, 20, 8.4)])
    retained, audit = visible_context_surfaces(resolved, points)
    assert (retained, audit) == visible_context_surfaces(resolved, points[::-1])
    grazing = [s for s in resolved.surfaces if all(abs(v[1]) < 1e-8 for v in s.vertices)]
    assert grazing and all(s in retained for s in grazing)
    omissions = {item["name"]: item for item in audit["hidden"]}
    for s in resolved.surfaces:
        if s not in retained:
            v = np.asarray(s.vertices)
            n = properties(v)[1]
            if s.kind == "Floor":
                assert v[0, 2] <= np.min(points[:, 2]) + 1e-6
                assert omissions[s.name]["reason"].startswith(
                    "Bottom cap at or below every receiver"
                )
            else:
                assert np.max((points - v[0]) @ n) < -1e-6


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_shades_are_rejected_independent_of_order(building, energyplus, reverse):
    import copy

    from epsm_core.surface_checks import validate_surfaces

    spec = building.updated(context=context())
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    shade = copy.deepcopy(next(iter(model["Shading:Building:Detailed"].values())))
    if reverse:
        shade["vertices"].reverse()
    shade["vertices"] = shade["vertices"][1:] + shade["vertices"][:1]
    model["Shading:Building:Detailed"]["duplicate"] = shade
    with pytest.raises(ValueError, match="Duplicate shading surfaces"):
        validate_surfaces(model, report.data["zones"])
