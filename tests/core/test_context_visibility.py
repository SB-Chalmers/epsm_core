import numpy as np
import pytest

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


def test_visibility_retains_grazing_faces_and_is_deterministic(building):
    resolved = resolve_context(building.geometry, context())
    points = np.array([(0, 0, 0), (30, 0, 8.4), (30, 20, 8.4)])
    retained, audit = visible_context_surfaces(resolved, points)
    assert (retained, audit) == visible_context_surfaces(resolved, points[::-1])
    grazing = [s for s in resolved.surfaces if all(abs(v[1]) < 1e-8 for v in s.vertices)]
    assert grazing and all(s in retained for s in grazing)
    for s in resolved.surfaces:
        if s not in retained:
            v = np.asarray(s.vertices)
            n = properties(v)[1]
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
