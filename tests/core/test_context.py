"""Surroundings are deterministic, inspectable geometry with no building loads."""

import math

import numpy as np
import pytest
from shapely.affinity import translate
from shapely.geometry import Polygon

from epsm_core.context import resolve_context, synthetic_context, validate_context
from epsm_core.district import DistrictPlan
from epsm_core.specs import (
    BuildingPart,
    ContextBuilding,
    ContextSpec,
    Footprint,
    GeometrySpec,
    RoofSpec,
)
from epsm_core.surface_checks import properties


def geometry(footprint=None, **kwargs):
    return GeometrySpec(
        parts=(
            BuildingPart(
                identifier="main",
                footprint=footprint or Footprint.rectangle(30, 20),
                storey_elevations_m=(0, 3, 6),
            ),
        ),
        **kwargs,
    )


def neighbour(identifier="neighbour", x=50, y=0, height=12, footprint=None):
    return ContextBuilding(
        identifier=identifier,
        footprints=(
            footprint or Footprint(exterior=((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10))),
        ),
        height_m=height,
    )


@pytest.mark.parametrize(
    "preset,heights,clearance",
    [
        ("rural", (3, 9), 20),
        ("urban_lowrise_dense", (6, 15), 10),
        ("urban_highrise_dense", (24, 60), 10),
    ],
)
def test_synthetic_scenarios_are_reproducible_and_clear(preset, heights, clearance):
    target = geometry()
    context = synthetic_context(target, preset)
    assert context == synthetic_context(target, preset)
    assert context.buildings
    assert context.generation["achieved_building_count"] == len(context.buildings)
    assert all(heights[0] <= b.height_m <= heights[1] for b in context.buildings)
    assert all(
        footprint.polygon.distance(target.parts[0].footprint.polygon) >= clearance
        for building in context.buildings
        for footprint in building.footprints
    )
    validate_context(target, context)


def test_urban_height_scenarios_preserve_horizontal_geometry():
    low = synthetic_context(geometry(), "urban_lowrise_dense", seed=31)
    high = synthetic_context(geometry(), "urban_highrise_dense", seed=31)
    assert [b.footprints for b in low.buildings] == [b.footprints for b in high.buildings]
    assert [b.identifier for b in low.buildings] == [b.identifier for b in high.buildings]
    assert all(a.height_m < b.height_m for a, b in zip(low.buildings, high.buildings))
    assert low != synthetic_context(geometry(), "urban_lowrise_dense", seed=32)


def test_supplied_neighbours_are_retained_and_excluded_from_generation():
    target = geometry()
    original = synthetic_context(target, "urban_lowrise_dense")
    supplied = ContextSpec(buildings=(original.buildings[0].updated(identifier="observed"),))
    result = synthetic_context(target, "urban_lowrise_dense", existing=supplied)
    assert result.buildings[0] == supplied.buildings[0]
    assert len(result.buildings) == len(original.buildings)
    validate_context(target, result)


def test_courtyards_are_not_automatically_populated():
    target = geometry(
        Footprint(
            exterior=((-80, -80), (80, -80), (80, 80), (-80, 80)),
            holes=(((-60, -60), (-60, 60), (60, 60), (60, -60)),),
        )
    )
    context = synthetic_context(target, "urban_lowrise_dense", radius_m=160)
    courtyard = Polygon(target.parts[0].footprint.holes[0])
    assert context.buildings
    assert all(not courtyard.intersects(b.footprints[0].polygon) for b in context.buildings)
    # Explicitly supplied courtyard buildings remain valid.
    validate_context(target, ContextSpec(buildings=(neighbour(x=0, y=0),)))


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"max_buildings": 1}, "exceeds max_buildings"),
        ({"radius_m": 1e9}, "candidates"),
        ({"spacing_m": 0}, "spacing_m"),
        ({"size_range_m": (12, 10)}, "minimum exceeds"),
        ({"height_range_m": (0, 1)}, "height_range_m"),
        ({"clearance_m": -1}, "clearance_m"),
        ({"radius_m": math.inf}, "radius_m"),
    ],
)
def test_synthetic_limits_are_explicit(kwargs, match):
    with pytest.raises(ValueError, match=match):
        synthetic_context(geometry(), "urban_lowrise_dense", **kwargs)


def test_custom_context_checks_identifiers_and_intersections():
    target = geometry()
    with pytest.raises(ValueError, match="overlaps target"):
        validate_context(target, ContextSpec(buildings=(neighbour(x=29),)))
    with pytest.raises(ValueError, match="overlap"):
        validate_context(target, ContextSpec(buildings=(neighbour("one"), neighbour("two", x=59))))
    with pytest.raises(ValueError, match="unique"):
        ContextSpec(buildings=(neighbour(), neighbour(x=80)))
    with pytest.raises(ValueError):
        ContextBuilding(identifier="empty", footprints=(), height_m=12)
    validate_context(target, ContextSpec(buildings=(neighbour(x=30),)))


def test_resolver_transforms_the_entire_scene_and_preserves_metadata():
    target = geometry(orientation_deg=90)
    context = ContextSpec(buildings=(neighbour().updated(base_elevation_m=2),))
    resolved = resolve_context(target, context)
    assert resolved.report["building_count"] == 1
    assert resolved.report["surface_count"] == 5
    assert resolved.report["validation"] == "passed"
    points = np.asarray([v for surface in resolved.surfaces for v in surface.vertices])
    assert np.min(points, axis=0) == pytest.approx([0, -60, 2])
    assert np.max(points, axis=0) == pytest.approx([10, -50, 14])
    assert all(s.building_id == "neighbour" for s in resolved.surfaces)
    assert {s.kind for s in resolved.surfaces} == {"Wall", "Roof"}
    for surface in resolved.surfaces:
        properties(np.asarray(surface.vertices))


def test_resolver_preserves_context_roof_holes_and_multiple_footprints():
    footprint = Footprint(
        exterior=((50, 0), (80, 0), (80, 30), (50, 30)),
        holes=(((60, 10), (60, 20), (70, 20), (70, 10)),),
    )
    context = ContextSpec(buildings=(neighbour(footprint=footprint),))
    resolved = resolve_context(geometry(), context)
    roof_area = sum(
        properties(np.asarray(surface.vertices))[0]
        for surface in resolved.surfaces
        if surface.kind == "Roof"
    )
    assert roof_area == pytest.approx(800)


@pytest.mark.parametrize("height", [6, 60])
@pytest.mark.parametrize("outline", ["rectangle", "concave", "courtyard"])
def test_preview_context_caps_cover_the_footprint_at_full_height(height, outline):
    from epsm_core.inspection import geometry_scene
    from epsm_core.viewer import viewer_data

    exterior = ((50, 0), (80, 0), (80, 30), (50, 30))
    if outline == "concave":
        exterior = ((50, 0), (80, 0), (80, 10), (60, 10), (60, 30), (50, 30))
    holes = (((60, 10), (60, 20), (70, 20), (70, 10)),) if outline == "courtyard" else ()
    footprint = Footprint(exterior=exterior, holes=holes)
    context = ContextSpec(buildings=(neighbour(height=height, footprint=footprint),))
    scene, report = geometry_scene(geometry(), context=context)
    caps = [
        obj
        for obj in viewer_data(scene, report)["objects"]
        if obj["kind"] == "context" and obj["metadata"]["surface_type"] == "Roof"
    ]
    assert caps
    triangles = np.concatenate([np.asarray(obj["triangles"]).reshape(-1, 3, 3) for obj in caps])
    assert triangles[:, :, 2] == pytest.approx(height)
    from shapely import unary_union

    coverage = unary_union([Polygon(t[:, :2]) for t in triangles])
    assert coverage.symmetric_difference(footprint.polygon).area < 1e-8
    assert sum(Polygon(t[:, :2]).area for t in triangles) == pytest.approx(footprint.polygon.area)


@pytest.mark.parametrize("shape,roof_height", [("gable", 5), ("mono_pitch", 10)])
def test_district_neighbours_use_actual_pitched_roof_maximum(building, shape, roof_height):
    part = building.geometry.parts[0]
    outline = translate(Footprint.rectangle(30, 20).polygon, xoff=60)
    neighbour_part = part.updated(
        footprint=Footprint(exterior=tuple(outline.exterior.coords)[:-1]),
        roof=RoofSpec(
            shape=shape,
            pitch_deg=math.degrees(math.atan(0.5)),
            direction_deg=90 if shape == "gable" else 0,
        ),
    )
    second = building.updated(
        identifier="second", geometry=building.geometry.updated(parts=(neighbour_part,))
    )
    first = next(DistrictPlan(buildings=(building, second)).resolved_buildings())
    assert first.context.buildings[0].height_m == pytest.approx(
        part.storey_elevations_m[-1] + roof_height
    )
    assert "actual roof maximum" in first.context.generation["district_representation"]


def test_district_flat_cold_attic_height(building):
    part = building.geometry.parts[0]
    outline = translate(part.footprint.polygon, xoff=60)
    second = building.updated(
        identifier="second",
        geometry=building.geometry.updated(
            parts=(
                part.updated(footprint=Footprint(exterior=tuple(outline.exterior.coords)[:-1])),
            ),
            roof=RoofSpec(topology="cold_attic", attic_height_m=2),
        ),
    )
    first = next(DistrictPlan(buildings=(building, second)).resolved_buildings())
    assert first.context.buildings[0].height_m == pytest.approx(part.storey_elevations_m[-1] + 2)


def test_context_only_compilation_uses_shadow_settings_without_adding_physics(building, energyplus):
    from epsm_core.compiler import EnergyPlusCompiler
    from epsm_core.quantities import quantity_takeoff
    from epsm_core.settings import CompilerSettings
    from epsm_core.viewer import viewer_data

    context = ContextSpec(buildings=(neighbour(),))
    shaded = building.updated(context=context)
    compiler = EnergyPlusCompiler(energyplus, settings=CompilerSettings(shadow_max_figures=50_000))
    baseline, base_report = compiler.compile(building)
    model, report = compiler.compile(shaded)
    settings = model["ShadowCalculation"]["detailed_geometry"]
    assert settings["maximum_figures_in_shadow_overlap_calculations"] == 50_000
    assert report.data["context"]["building_count"] == 1
    assert report.data["context"]["surface_count"] == 5
    assert report.data["conditioned_floor_area_m2"] == base_report.data["conditioned_floor_area_m2"]
    for kind in ("Zone", "People", "Lights", "ElectricEquipment", "WaterUse:Equipment"):
        assert model[kind] == baseline[kind]
    assert quantity_takeoff(shaded) == quantity_takeoff(building)
    objects = viewer_data(model, report.data)["objects"]
    neighbours = [o for o in objects if o["kind"] == "context"]
    assert len(neighbours) == 5
    assert all(o["metadata"]["building_id"] == "neighbour" for o in neighbours)
