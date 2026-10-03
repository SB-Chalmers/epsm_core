import math

import numpy as np
import pytest

from epsm_core import (
    ApartmentLayoutSpec,
    BalconySpec,
    EnergyPlusCompiler,
    FacadeOverride,
    Footprint,
    OverhangSpec,
    RoofSpec,
    WindowLayoutSpec,
)
from epsm_core.facades import window_rectangles
from epsm_core.quantities import quantity_takeoff
from epsm_core.specs import ZoningSpec
from epsm_core.surface_checks import MIN_GENERATED_EDGE_M, vertices
from epsm_core.viewer import viewer_data


def residential_building(building):
    """Explicit residential occupancy, repeated openings and 0.2 m reveal shading."""
    return building.updated(
        use=building.use.updated(occupancy_category="residential"),
        facade=building.facade.updated(layout=WindowLayoutSpec(mode="wwr"), reveal_depth_m=0.2),
        geometry=building.geometry.updated(zoning=ZoningSpec(mode="per_storey")),
    )


@pytest.mark.parametrize(
    "wwr,pattern",
    [
        (0, "low"),
        (0.1, "low"),
        (0.15, "mid"),
        (0.3, "mid"),
        (0.6, "mid"),
        (0.6001, "high"),
        (0.75, "high"),
        (0.94, "high"),
    ],
)
def test_window_patterns(wwr, pattern):
    rectangles, label = window_rectangles(30, 3, wwr, WindowLayoutSpec(mode="wwr"))
    assert label == pattern
    assert sum((c - a) * (d - b) for a, b, c, d in rectangles) == pytest.approx(90 * wwr)
    assert all(a > 0 and c < 30 and b >= 0 and d < 3 for a, b, c, d in rectangles)
    assert all(r[2] < s[0] for r, s in zip(rectangles, rectangles[1:]))


def test_window_dimensions_and_failure():
    layout = WindowLayoutSpec(
        mode="dimensions",
        window_width_m=1.2,
        window_height_m=1.5,
        center_spacing_m=3.5,
        sill_height_ratio=0.3,
    )
    rects, _ = window_rectangles(10, 3, 0.2, layout)
    assert len(rects) == 3 and rects[0][1] == pytest.approx(0.9)
    with pytest.raises(ValueError, match="OR"):
        layout.updated(sill_height_m=0.9)
    with pytest.raises(ValueError, match="Infeasible WWR"):
        window_rectangles(0.4, 2, 0.3, WindowLayoutSpec(mode="wwr"))


def test_scaled_windows_omit_edges_below_engine_limit():
    """Scaled mode keeps tiny facade runs opaque instead of emitting unsafe edges."""
    wwr = 0.08788
    layout = WindowLayoutSpec(mode="scaled")
    rectangles, label = window_rectangles(0.03272, 2.8, wwr, layout)

    assert label == "scaled"
    assert rectangles == []

    safe_length = MIN_GENERATED_EDGE_M / math.sqrt(wwr)
    rectangles, _ = window_rectangles(safe_length, 2.8, wwr, layout)
    assert rectangles
    assert rectangles[0][2] - rectangles[0][0] == pytest.approx(MIN_GENERATED_EDGE_M)


def test_scaled_window_suppression_is_reported(building, energyplus):
    """The facade audit explains why a requested window was not generated."""
    footprint = Footprint(
        exterior=(
            (0, 0),
            (30, 0),
            (30, 20),
            (10.03272, 20),
            (10.03272, 19),
            (10, 19),
            (10, 20),
            (0, 20),
        )
    )
    part = building.geometry.parts[0].updated(footprint=footprint)
    requested_wwr = 0.08788
    candidate = building.updated(
        geometry=building.geometry.updated(parts=(part,)),
        facade=building.facade.updated(
            default_wwr=requested_wwr,
            layout=WindowLayoutSpec(mode="scaled"),
        ),
    )

    _, report = EnergyPlusCompiler(energyplus).compile(candidate)
    suppressed = [
        facade
        for facade in report.data["facades"]
        if facade["opening_suppression_reason"] is not None
    ]

    assert suppressed
    assert all(facade["requested_wwr"] == pytest.approx(requested_wwr) for facade in suppressed)
    assert all(facade["local_wwr"] == 0 for facade in suppressed)
    assert all(facade["window_area_m2"] == 0 for facade in suppressed)
    assert all(
        "safety limit for EnergyPlus" in facade["opening_suppression_reason"]
        for facade in suppressed
    )
    assert report.data["validation"]["status"] == "passed"


def test_facade_compilation_and_quantities(building, energyplus):
    b = residential_building(building)
    c = EnergyPlusCompiler(energyplus)
    model, report = c.compile(b)
    assert len(model["FenestrationSurface:Detailed"]) > 12
    assert len(model["Shading:Building:Detailed"]) == 4 * len(model["FenestrationSurface:Detailed"])
    assert sum(q.area_m2 for q in quantity_takeoff(b) if q.kind == "glazing") == pytest.approx(
        sum(f["window_area_m2"] for f in report.data["facades"])
    )
    other, _ = c.compile(
        b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode="whole_building")))
    )

    def points(m):
        return sorted(
            tuple(vertices(v).flatten()) for v in m["FenestrationSurface:Detailed"].values()
        )

    assert points(model) == points(other)
    data = viewer_data(
        other,
        c.compile(b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode="whole_building"))))[
            1
        ].data,
    )
    assert any(o["kind"] == "slab_visual" for o in data["objects"])


@pytest.mark.parametrize("shape", ["mono_pitch", "gable", "hip"])
@pytest.mark.parametrize("courtyard", [False, True])
def test_pitched_roofs(building, energyplus, shape, courtyard):
    b = residential_building(building)
    part = b.geometry.parts[0]
    if courtyard:
        part = part.updated(
            footprint=Footprint(
                exterior=((0, 0), (30, 0), (30, 20), (0, 20)),
                holes=(((10, 5), (20, 5), (20, 15), (10, 15)),),
            )
        )
    b = b.updated(
        geometry=b.geometry.updated(parts=(part,), roof=RoofSpec(shape=shape)),
    )
    if courtyard:
        from epsm_core import GroundTemperatureSpec
        b = b.updated(envelope=b.envelope.updated(ground_temperature=GroundTemperatureSpec()))
    m, r = EnergyPlusCompiler(energyplus).compile(b)
    assert r.data["validation"]["status"] == "passed"
    assert any(z.get("roof_shape") == shape for z in r.data["zones"].values())
    assert sum(z["volume_m3"] for z in r.data["zones"].values()) > b.geometry.conditioned_volume_m3


def test_shading_controls_and_overrides(building, energyplus):
    b = residential_building(building)
    b = b.updated(
        facade=b.facade.updated(
            overhang=OverhangSpec(depth_m=0.6),
            balconies=(
                BalconySpec(
                    facade_id="main.r0.e0",
                    storeys=(1, 2),
                    start_m=2,
                    width_m=4,
                    depth_m=1.5,
                    side_screen_height_m=1,
                ),
            ),
            overrides=(FacadeOverride(facade_id="main.r0.e0", storey=0, wwr=0.1),),
        )
    )
    m, r = EnergyPlusCompiler(energyplus).compile(b)
    assert {s["kind"] for s in r.data["shading"].values()} == {"reveal", "overhang", "balcony"}
    rows = [f for f in r.data["facades"] if f["facade_id"] == "main.r0.e0" and f["storey"] == 0]
    assert sum(f["window_area_m2"] for f in rows) / sum(
        f["gross_area_m2"] for f in rows
    ) == pytest.approx(0.1)


def test_residential_only(building):
    with pytest.raises(ValueError, match="residential"):
        building.updated(geometry=building.geometry.updated(zoning=ZoningSpec(mode="apartments")))


@pytest.mark.parametrize(
    "override,match",
    [
        (FacadeOverride(facade_id="missing", wwr=0.3), "unknown facade"),
        (FacadeOverride(facade_id="main.r0.e0", storey=3, wwr=0.3), "nonexistent storey"),
    ],
)
def test_unknown_facade_and_storey_overrides_fail_at_input_validation(building, override, match):
    with pytest.raises(ValueError, match=match):
        building.updated(facade=building.facade.updated(overrides=(override,)))


def test_apartment_layout(building, energyplus):
    b = residential_building(building)
    b = b.updated(
        envelope=b.envelope.updated(
            dwelling_partition=b.envelope.intermediate_floor,
            common_partition=b.envelope.intermediate_floor,
        ),
        geometry=b.geometry.updated(
            zoning=ZoningSpec(
                mode="apartments", apartments=ApartmentLayoutSpec(max_candidates=1000)
            )
        ),
    )
    m, r = EnergyPlusCompiler(energyplus).compile(b)
    assert r.data["layout"]["status"] == "generated"
    assert any(z.get("zone_kind") == "stairwell" for z in r.data["zones"].values())
    types = {t.name: t for t in b.geometry.zoning.apartments.types}
    for z in r.data["zones"].values():
        if z.get("zone_kind") == "dwelling":
            t = types[z["apartment_type"]]
            assert t.min_area_m2 - 1e-7 <= z["floor_area_m2"] <= t.max_area_m2 + 1e-7


@pytest.mark.parametrize("height,orientation", [(2.8, 0), (3, 0), (3, 45), (3, 90)])
def test_apartment_windows_loads_and_fallback(building, energyplus, height, orientation):
    b = residential_building(building)
    b = b.updated(
        facade=b.facade.updated(default_wwr=0.3, reveal_depth_m=0),
        envelope=b.envelope.updated(
            dwelling_partition=b.envelope.intermediate_floor,
            common_partition=b.envelope.intermediate_floor,
        ),
    )
    c = EnergyPlusCompiler(energyplus)
    b = b.updated(
        geometry=b.geometry.updated(
            orientation_deg=orientation,
            parts=(
                b.geometry.parts[0].updated(
                    storey_elevations_m=(0, height, 2 * height, 3 * height)
                ),
            ),
        )
    )
    before, _ = c.compile(b)
    apartment = b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode="apartments")))
    after, report = c.compile(apartment)
    assert report.data["layout"]["status"] == "generated"

    def points(model):
        return sorted(
            tuple(np.round(vertices(o).flatten(), 6))
            for o in model["FenestrationSurface:Detailed"].values()
        )

    assert points(before) == points(after)
    for kind, field in (
        ("People", "number_of_people"),
        ("ElectricEquipment", "design_level"),
        ("Lights", "lighting_level"),
        ("WaterUse:Equipment", "peak_flow_rate"),
    ):
        assert sum(o[field] for o in before[kind].values()) == pytest.approx(
            sum(o[field] for o in after[kind].values())
        )
    assert any(
        o["heating_setpoint_temperature_schedule_name"] == "common_heating_setpoint"
        for o in after["ThermostatSetpoint:DualSetpoint"].values()
    )
    assert viewer_data(after, report.data)["objects"]
    tiny = apartment.updated(
        geometry=apartment.geometry.updated(
            parts=(apartment.geometry.parts[0].updated(footprint=Footprint.rectangle(4, 4)),)
        )
    )
    with pytest.raises(ValueError):
        c.compile(tiny)
    tiny = tiny.updated(
        geometry=tiny.geometry.updated(zoning=tiny.geometry.zoning.updated(on_failure="per_storey"))
    )
    _, r = c.compile(tiny)
    assert r.data["layout"]["status"] == "fallback_per_storey"
    assert r.data["layout"]["parts"][0]["reason"]


def test_overhang_analytical_projection(building, energyplus):
    """At 45° solar altitude a horizontal projection shades its own depth downwards."""
    b = residential_building(building)
    b = b.updated(facade=b.facade.updated(reveal_depth_m=0, overhang=OverhangSpec(depth_m=0.6)))
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    metadata = report.data["shading"]
    name = next(n for n, s in metadata.items() if s["kind"] == "overhang")
    v = vertices(model["Shading:Building:Detailed"][name])
    # Export starts at the declared upper-left vertex. Measure physical depth
    # independently of the cyclic start index of this horizontal polygon.
    edge_lengths = np.linalg.norm(np.roll(v, -1, axis=0) - v, axis=1)
    projection = min(edge_lengths)
    assert projection == pytest.approx(0.6)
    assert projection / np.tan(np.radians(45)) == pytest.approx(0.6)


def test_optional_backend_failure(monkeypatch, building):
    import builtins

    from epsm_core.roofs import skeleton

    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "py_straight_skeleton":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ValueError, match=r"epsm_core\[geometry\]"):
        skeleton(building.geometry.parts[0].footprint.polygon)


@pytest.mark.parametrize("shape", ["mono_pitch", "gable", "hip"])
def test_analytic_roof_volumes_without_engine(shape):
    from shapely.geometry import Polygon

    from epsm_core.roofs import roof_faces

    if shape == "hip":
        pytest.importorskip("py_straight_skeleton")
    polygon = Footprint.rectangle(30, 20).polygon
    faces = roof_faces(polygon, RoofSpec(shape=shape), 9)
    projected = [Polygon([(x, y) for x, y, z in face]).area for face in faces]
    actual = sum(area * sum(z - 9 for x, y, z in face) / 3 for area, face in zip(projected, faces))
    expected = {
        "mono_pitch": 600 * 30 * np.tan(np.radians(10)) / 2,
        "gable": 600 * 10 * np.tan(np.radians(30)) / 2,
        "hip": (600 * 10 - 50 * 100 + 4 * 1000 / 3) * np.tan(np.radians(30)),
    }
    assert sum(projected) == pytest.approx(600)
    assert actual == pytest.approx(expected[shape])


def test_layout_coverage_and_access_without_engine():
    pytest.importorskip("py_straight_skeleton")
    from shapely import unary_union

    from epsm_core.apartments import infer_floorplate

    footprint = Footprint.rectangle(30, 20).polygon
    controls = ApartmentLayoutSpec()
    plan, reason = infer_floorplate(footprint, controls, [])
    assert reason is None
    polygons = [q for q, kind, typ in plan["parts"]]
    cover = unary_union(polygons)
    assert cover.symmetric_difference(footprint).area < 1e-7
    assert sum(p.area for p in polygons) == pytest.approx(cover.area)
    common = unary_union([q for q, kind, typ in plan["parts"] if kind != "dwelling"])
    for q, kind, typ in plan["parts"]:
        if kind == "dwelling":
            assert q.boundary.intersection(footprint.boundary).length >= controls.min_frontage_m
            assert q.boundary.intersection(common.boundary).length >= controls.min_access_m


@pytest.mark.parametrize(
    "shape,roof,orientation", [("l", "gable", 45), ("u", "hip", 0), ("u", "hip", 90)]
)
def test_concave_roof_shell_regressions(building, energyplus, shape, roof, orientation):
    from epsm_core import GeometrySpec

    pytest.importorskip("py_straight_skeleton")
    footprint = (
        Footprint.l_shape(30, 30, 15, 15) if shape == "l" else Footprint.u_shape(30, 30, 14, 20)
    ).scaled_to_area(600)
    b = residential_building(building)
    b = b.updated(
        geometry=GeometrySpec.from_footprint(
            footprint, storey_elevations_m=(0, 3, 6, 9), orientation_deg=orientation
        ).updated(roof=RoofSpec(shape=roof), zoning=ZoningSpec(mode="per_storey")),
        facade=b.facade.updated(reveal_depth_m=0),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["validation"]["surface_count"] > 0
    assert model["Zone"]["main_attic_3"]["volume"] > 0


@pytest.mark.parametrize("orientation", [0, 45, 90])
def test_u_shape_apartment_topology_regression(building, energyplus, orientation):
    from epsm_core import GeometrySpec
    from epsm_core.surface_checks import validate_surfaces

    pytest.importorskip("py_straight_skeleton")
    b = residential_building(building)
    b = b.updated(
        geometry=GeometrySpec.from_footprint(
            Footprint.u_shape(30, 30, 14, 20).scaled_to_area(600),
            storey_elevations_m=(0, 3, 6, 9),
            orientation_deg=orientation,
        ).updated(zoning=ZoningSpec(mode="apartments")),
        envelope=b.envelope.updated(
            dwelling_partition=b.envelope.intermediate_floor,
            common_partition=b.envelope.intermediate_floor,
        ),
        facade=b.facade.updated(default_wwr=0.3, reveal_depth_m=0),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["layout"]["status"] == "generated"
    assert report.data["zoning"]["effective_mode"] == "apartments"
    assert not report.data["zoning"]["substituted"]
    assert len(model["Zone"]) > 3
    assert validate_surfaces(model, report.data["zones"])["status"] == "passed"


def test_party_wall_layout_fallback_and_viewer_zone(building, energyplus):
    from epsm_core import PartyWall

    b = residential_building(building)
    b = b.updated(
        geometry=b.geometry.updated(
            zoning=ZoningSpec(mode="apartments", on_failure="per_storey"),
            party_walls=(
                PartyWall(
                    facade_id="main.r0.e0",
                    neighbor_id="reviewed",
                    neighbor_conditioning="heated",
                    contact_confirmed=True,
                    assumption_source="test fixture",
                ),
            ),
        ),
        envelope=b.envelope.updated(
            dwelling_partition=b.envelope.intermediate_floor,
            common_partition=b.envelope.intermediate_floor,
        ),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["layout"]["status"] == "fallback_per_storey"
    assert "Party-wall" in report.data["layout"]["parts"][0]["reason"]
    data = viewer_data(model, report.data)
    objects = {o["name"]: o for o in data["objects"]}
    openings = [o for o in objects.values() if o["kind"] == "opening"]
    assert openings
    for opening in openings:
        assert opening["zone"] == objects[opening["parent"]]["zone"]
        assert opening["zone"] in model["Zone"]


def test_layout_failure_reruns_all_disconnected_components_per_storey(building, energyplus):
    from shapely.affinity import translate

    from epsm_core import BuildingPart

    pytest.importorskip("py_straight_skeleton")
    b = residential_building(building)
    remote = translate(Footprint.rectangle(4, 4).polygon, 50, 0)
    b = b.updated(
        geometry=b.geometry.updated(
            zoning=ZoningSpec(mode="apartments", on_failure="per_storey"),
            parts=(
                b.geometry.parts[0].updated(storey_elevations_m=(0, 3, 6, 9)),
                BuildingPart(
                    identifier="remote",
                    footprint=Footprint(exterior=tuple(remote.exterior.coords)[:-1]),
                    storey_elevations_m=(0, 3, 6, 9),
                ),
            ),
        ),
        envelope=b.envelope.updated(
            dwelling_partition=b.envelope.intermediate_floor,
            common_partition=b.envelope.intermediate_floor,
        ),
        facade=b.facade.updated(default_wwr=0.3, reveal_depth_m=0),
    )
    model, report = EnergyPlusCompiler(energyplus).compile(b)
    assert report.data["layout"]["status"] == "fallback_per_storey"
    records = {p["part_id"]: p for p in report.data["layout"]["parts"]}
    assert records["main"]["status"] == "fallback_per_storey"
    assert records["remote"]["status"] == "fallback_per_storey"
    baseline, _ = EnergyPlusCompiler(energyplus).compile(
        b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode="per_storey")))
    )

    def openings(m):
        return sorted(
            tuple(np.round(vertices(o).flatten(), 6))
            for o in m["FenestrationSurface:Detailed"].values()
        )

    assert openings(model) == openings(baseline)
