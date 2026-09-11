import pytest

from epsm_core import EnergyPlusCompiler
from epsm_core.specs import ContextBuilding, ContextSpec, Footprint


def neighbour(base=0):
    return ContextSpec(
        buildings=(
            ContextBuilding(
                identifier="opaque_block",
                footprints=(Footprint(exterior=((50, 0), (60, 0), (60, 10), (50, 10))),),
                height_m=15,
                base_elevation_m=base,
            ),
        )
    )


def disabled(model):
    return any(
        d["key"] == "DoNotMirrorDetachedShading"
        for o in model.get("Output:Diagnostics", {}).values()
        for d in o["diagnostics"]
    )


@pytest.mark.parametrize("angle", [0, 37, 181])
def test_outward_opaque_context_avoids_duplicate_back_faces(building, energyplus, angle):
    spec = building.updated(
        context=neighbour(), geometry=building.geometry.updated(orientation_deg=angle)
    )
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert disabled(model)
    assert report.data["context"]["detached_mirroring_disabled"]
    assert model["Shading:Building:Detailed"]
    assert (
        next(iter(model["ShadowCalculation"].values()))[
            "maximum_figures_in_shadow_overlap_calculations"
        ]
        == 15_000
    )
    assert (
        next(iter(model["ShadowCalculation"].values()))["polygon_clipping_algorithm"]
        == "SutherlandHodgman"
    )


def test_closed_bottom_above_receivers_qualifies(building, energyplus):
    model, report = EnergyPlusCompiler(energyplus).compile(
        building.updated(context=neighbour(base=2))
    )
    assert disabled(model)
    assert report.data["context"]["mirror_suppression_eligible"]
    assert any(s["surface_type"] == "Floor" for s in report.data["shading"].values())


def test_thin_facade_shades_keep_both_sides_with_context(building, energyplus):
    spec = building.updated(context=neighbour(), facade=building.facade.updated(reveal_depth_m=0.2))
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert any(v["kind"] != "context" for v in report.data["shading"].values())
    assert not disabled(model)
    assert not report.data["context"]["detached_mirroring_disabled"]


def test_no_context_preserves_default_mirroring(building, energyplus):
    model, report = EnergyPlusCompiler(energyplus).compile(building)
    assert not disabled(model)
    assert not report.data["context"]["detached_mirroring_disabled"]
