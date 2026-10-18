"""Shared contact has one physical owner and no outdoor heat-transfer area."""
import pytest
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import Building, BuildingPart, Footprint, PartyWall, Weather
from epsm_core.specs import GeometrySpec, ZoningSpec


def model():
    building = Building(preset="illustrative-reference")
    building.geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        zoning=ZoningSpec(mode="whole_building"),
    )
    return building


def party(**changes):
    return PartyWall(facade_id="main.r0.e0", neighbor_id="neighbor",
                     neighbor_conditioning="unknown", contact_confirmed=True,
                     assumption_source="geometric contact; assumed adiabatic", **changes)


def test_full_party_wall_is_opaque_adiabatic_physical_inventory(synthetic_weather):
    building = model()
    building.geometry = building.geometry.updated(party_walls=(party(),))
    shared = [e for e in building.elements if e.facade_id == "main.r0.e0"]
    assert not any(e.role == Role.WINDOW for e in shared)
    assert sum(e.area_m2 for e in shared) == pytest.approx(60)
    assert {e.boundary for e in shared} == {"Adiabatic"}
    assert building.readiness(engine="epsm_rc").ready
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    faces = {f["name"]: f for f in resolved.surfaces}
    assert not any(faces[o["parent"]]["boundary"] != "Outdoors" for o in resolved.openings)
    assert sum(f["gross_area_m2"] for f in faces.values()
               if f["boundary"] == "Adiabatic") == pytest.approx(60)
    assert all(f["physical_element_id"] for f in faces.values())


def test_partial_party_contact_keeps_outdoor_area_and_window_ownership(synthetic_weather):
    building = model()
    building.geometry = building.geometry.updated(party_walls=(
        party(start_m=2, end_m=8, bottom_m=0, top_m=4),
    ))
    shared = [e for e in building.elements if e.facade_id == "main.r0.e0"]
    assert sum(e.area_m2 for e in shared if e.boundary == "Adiabatic") == pytest.approx(24)
    assert sum(e.area_m2 for e in shared if e.boundary == "Outdoors") == pytest.approx(36)
    assert all(e.boundary == "Outdoors" for e in shared if e.role == Role.WINDOW)
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert sum(f["gross_area_m2"] for f in resolved.surfaces
               if f["boundary"] == "Adiabatic") == pytest.approx(24)
    for element in shared:
        if element.role == Role.WINDOW:
            actual = sum(o["area_m2"] for o in resolved.openings
                         if o["physical_element_id"] == element.identifier)
        else:
            actual = sum(f["net_area_m2"] for f in resolved.surfaces
                         if f["physical_element_id"] == element.identifier)
        assert actual == pytest.approx(element.area_m2)
    assert sum(row.area_m2 for row in building.quantities()
               if row.element_id in {e.identifier for e in shared}) > 0


def test_multiple_contacts_union_and_snapshot_roundtrip():
    building = model()
    original = building.snapshot().sha256
    building.geometry = building.geometry.updated(party_walls=(
        party(start_m=0, end_m=6, bottom_m=0, top_m=3),
        party(start_m=4, end_m=10, bottom_m=0, top_m=3),
    ))
    assert sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic") == pytest.approx(30)
    captured = building.snapshot()
    assert captured.sha256 != original
    assert captured.to_building().snapshot().sha256 == captured.sha256


def test_confirmed_contact_does_not_require_neighbor_heating_evidence(synthetic_weather):
    for status in ("heated", "unheated", "unknown"):
        building = model()
        building.geometry = building.geometry.updated(party_walls=(party().updated(neighbor_conditioning=status),))
        assert building.resolve(Weather.from_epw(synthetic_weather)).surfaces
    building.geometry = building.geometry.updated(party_walls=(party().updated(contact_confirmed=False),))
    assert not building.readiness(engine="epsm_rc").ready


def test_same_domain_attached_parts_have_one_shared_inventory_owner(synthetic_weather):
    building = model()
    wing = BuildingPart(identifier="wing", footprint=Footprint(
        exterior=((10, 0), (14, 0), (14, 8), (10, 8))), storey_elevations_m=(0, 3, 6))
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing))
    internal = [e for e in building.elements if e.boundary == "Internal" and e.role.is_ext_wall]
    assert sum(e.area_m2 for e in internal) == pytest.approx(48)
    assert building.readiness(engine="epsm_rc").ready
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert sum(m["area_m2"] for m in resolved.internal_mass
               if m["physical_element_id"] in {e.identifier for e in internal}) == pytest.approx(48)
    assert all(e.boundary == "Outdoors" for e in building.elements if e.role == Role.WINDOW)


def test_public_contact_detection_uses_partial_collinear_overlap_and_height():
    from epsm_core import PartyWallNeighbor

    geometry = model().geometry
    neighbor = PartyWallNeighbor(identifier="next", footprint=Footprint(
        exterior=((2, -5), (8, -5), (8, 0), (2, 0))), top_m=4)
    updated = geometry.with_party_wall_contacts((neighbor,), assumption_source="test geometry")
    assert not geometry.party_walls
    assert len(updated.party_walls) == 1
    wall = updated.party_walls[0]
    assert wall.facade_id == "main.r0.e0"
    assert (wall.start_m, wall.end_m, wall.bottom_m, wall.top_m) == pytest.approx((2, 8, 0, 4))
    separated = neighbor.updated(footprint=Footprint(
        exterior=((2, -5.2), (8, -5.2), (8, -0.2), (2, -0.2))))
    assert not geometry.with_party_wall_contacts((separated,), assumption_source="test").party_walls


def test_invalid_contact_extents_fail():
    with pytest.raises(ValueError, match="end_m"):
        party(start_m=8, end_m=2)
    with pytest.raises(ValueError, match="top_m"):
        party(bottom_m=4, top_m=2)


@pytest.mark.parametrize("mode", ("whole_building", "per_storey"))
def test_unequal_attached_parts_keep_shared_wall_once_and_outdoor_remnant(mode, synthetic_weather):
    building = model()
    wing = BuildingPart(identifier="wing", footprint=Footprint(
        exterior=((10, 2), (14, 2), (14, 8), (10, 8))), storey_elevations_m=(0, 2.5, 5))
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing),
                                                   zoning=ZoningSpec(mode=mode))
    internal = [e for e in building.elements if e.boundary == "Internal" and e.role.is_ext_wall]
    assert sum(e.area_m2 for e in internal) == pytest.approx(30)
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    owners = {e.identifier for e in building.elements}
    assert all(f["physical_element_id"] in owners for f in resolved.surfaces)
    assert all(m["physical_element_id"] in owners for m in resolved.internal_mass)
    # The shorter wing leaves the target wall above it outdoors.
    target = [f for f in resolved.surfaces if f["facade_id"] == "main.r0.e1"]
    assert sum(f["gross_area_m2"] for f in target if f["boundary"] == "Outdoors") == pytest.approx(18)


def test_contact_detection_rejects_point_touch_overlap_and_nonparallel_nearness():
    from epsm_core import PartyWallNeighbor

    geometry = model().geometry
    shapes = (
        ((10, -2), (12, -2), (12, 0), (10, 0)),  # point touch
        ((2, -2), (8, -2), (8, 1), (2, 1)),  # footprint overlap
        ((2, -2), (8, -2), (8, -.01), (2, -.1)),  # not parallel
    )
    for coordinates in shapes:
        neighbor = PartyWallNeighbor(identifier="next", footprint=Footprint(exterior=coordinates), top_m=4)
        assert not geometry.with_party_wall_contacts((neighbor,), tolerance_m=.1,
                                                     assumption_source="test").party_walls


def test_explicit_gap_tolerance_is_recorded_contact_assumption():
    from epsm_core import PartyWallNeighbor

    geometry = model().geometry
    neighbor = PartyWallNeighbor(identifier="next", footprint=Footprint(
        exterior=((2, -5), (8, -5), (8, -.05), (2, -.05))), top_m=4)
    assert not geometry.with_party_wall_contacts((neighbor,), assumption_source="exact").party_walls
    updated = geometry.with_party_wall_contacts((neighbor,), tolerance_m=.1,
                                                assumption_source="0.1 m gap sensitivity")
    assert len(updated.party_walls) == 1
    assert updated.party_walls[0].assumption_source == "0.1 m gap sensitivity"


def test_schema_six_snapshot_preserves_original_identity_until_geometry_edit():
    from epsm_core import BuildingSnapshot

    encoded = model().snapshot().to_dict()
    encoded["schema"] = "epsm.building/6"
    for element in encoded["elements"]:
        element.pop("boundary")
    original = BuildingSnapshot.from_dict(encoded)
    restored = original.to_building()
    assert restored.snapshot().sha256 == original.sha256
    assert restored.readiness(engine="epsm_rc").ready
    restored.geometry = restored.geometry.updated(party_walls=(party(),))
    assert restored.snapshot().to_dict()["schema"] == "epsm.building/7"
    assert restored.snapshot().sha256 != original.sha256


def test_contact_changes_geometry_cache_identity(synthetic_weather):
    from epsm_core.pipeline import GeometryCache

    building = model()
    weather = Weather.from_epw(synthetic_weather)
    cache = GeometryCache()
    first = building.resolve(weather, geometry_cache=cache)
    assert cache.misses == 1
    building.geometry = building.geometry.updated(party_walls=(party(),))
    second = building.resolve(weather, geometry_cache=cache)
    assert cache.misses == 2
    assert first.source_snapshot_id != second.source_snapshot_id
    assert not any(f["boundary"] == "Adiabatic" for f in first.surfaces)
    assert any(f["boundary"] == "Adiabatic" for f in second.surfaces)


@pytest.mark.parametrize("mode", ("whole_building", "per_storey"))
def test_shared_parts_compile_nominal_inventory_without_duplicate_wall(mode, synthetic_weather, energyplus):
    from epsm_core import EnergyPlusCompiler, quantity_takeoff

    building = model()
    wing = BuildingPart(identifier="wing", footprint=Footprint(
        exterior=((10, 0), (14, 0), (14, 8), (10, 8))), storey_elevations_m=(0, 3, 6))
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing),
                                                   zoning=ZoningSpec(mode=mode))
    spec = building.to_spec(Weather.from_epw(synthetic_weather))
    model_data, report = EnergyPlusCompiler(energyplus).compile(spec)
    assert model_data["BuildingSurface:Detailed"]
    assert quantity_takeoff(spec)
    if mode == "whole_building":
        from epsm_core.diagnostics import compiler_warning_conditions
        assert "space_area_equals_base_plus_physical_slabs" in compiler_warning_conditions(
            spec, model_data, report)


def test_partial_contact_energyplus_surfaces_are_adiabatic_and_window_free(synthetic_weather, energyplus):
    from epsm_core import EnergyPlusCompiler

    building = model()
    building.geometry = building.geometry.updated(party_walls=(party(start_m=2, end_m=8, top_m=4),))
    data, _ = EnergyPlusCompiler(energyplus).compile(building.to_spec(Weather.from_epw(synthetic_weather)))
    surfaces = data["BuildingSurface:Detailed"]
    shared = {name for name, surface in surfaces.items()
              if surface["outside_boundary_condition"] == "Adiabatic"}
    assert shared
    assert all(surfaces[name]["sun_exposure"] == "NoSun" and
               surfaces[name]["wind_exposure"] == "NoWind" for name in shared)
    assert not any(opening["building_surface_name"] in shared
                   for opening in data["FenestrationSurface:Detailed"].values())


def test_computational_partitions_never_add_physical_shared_wall_material():
    building = model()
    building.facade = building.facade.updated(default_wwr=0)
    areas = []
    for mode in ("whole_building", "per_storey", "perimeter_core"):
        geometry = GeometrySpec.from_footprint(Footprint.rectangle(30, 20), storeys=2,
            storey_height_m=3, zoning=ZoningSpec(mode=mode), party_walls=(party(start_m=2, end_m=7, top_m=4),))
        building.geometry = geometry
        assert not any(e.boundary == "Internal" and e.role.is_ext_wall for e in building.elements)
        areas.append(sum(e.area_m2 for e in building.elements if e.role.is_ext_wall))
    assert areas == pytest.approx([600, 600, 600])


def test_blank_building_still_records_contact_before_facade_assignment():
    building = Building.empty()
    building.geometry = GeometrySpec.from_footprint(Footprint.rectangle(10, 8), storeys=2,
        storey_height_m=3, party_walls=(party(start_m=2, end_m=8, top_m=4),))
    assert sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic") == pytest.approx(24)
    assert "facade (explicit opening/opaque-area information)" in building.readiness().missing


def test_partial_external_contact_can_share_facade_id_with_internal_part_contact(synthetic_weather):
    building = model()
    wing = BuildingPart(identifier="wing", footprint=Footprint(
        exterior=((10, 4), (14, 4), (14, 8), (10, 8))), storey_elevations_m=(0, 3, 6))
    wall = party(start_m=0, end_m=4, top_m=6).updated(facade_id="main.r0.e1")
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing), party_walls=(wall,))
    assert sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic") == pytest.approx(24)
    assert building.resolve(Weather.from_epw(synthetic_weather)).surfaces


def test_partial_contact_suppresses_only_fully_covered_perimeter_strip():
    from epsm_core.geometry import local_polygons
    from epsm_core.zoning import exposed_facades

    geometry = model().geometry.updated(party_walls=(party(start_m=2, end_m=8, top_m=4),))
    polygons, _ = local_polygons(geometry)
    for bottom, top, expected in ((0, 3, 4), (3, 6, 10)):
        edges = exposed_facades(geometry.parts[0], polygons[0], geometry.parts, polygons,
            bottom, top, party_walls=geometry.party_walls)
        assert sum(((b[0]-a[0])**2 + (b[1]-a[1])**2)**.5
                   for fid, a, b in edges if fid == "main.r0.e0") == pytest.approx(expected)


def test_contact_height_cuts_leave_other_facades_glazing_unchanged():
    building = model()
    before = {e.identifier: e.area_m2 for e in building.elements if e.role == Role.WINDOW
              and e.facade_id != "main.r0.e0"}
    building.geometry = building.geometry.updated(party_walls=(party(start_m=2, end_m=8, top_m=4),))
    after = {e.identifier: e.area_m2 for e in building.elements if e.role == Role.WINDOW
             and e.facade_id != "main.r0.e0"}
    assert before == pytest.approx(after)



def test_perimeter_window_clearance_is_bounded_reported_and_outdoors(synthetic_weather):
    building = model()
    building.geometry = GeometrySpec.from_footprint(Footprint.rectangle(30, 20), storeys=2,
        storey_height_m=3, zoning=ZoningSpec(mode="perimeter_core"),
        party_walls=(party(start_m=2, end_m=7, top_m=4),))
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    installed = sum(e.area_m2 for e in building.elements if e.role == Role.WINDOW)
    emitted = sum(opening["area_m2"] for opening in resolved.openings)
    assert 0 <= installed - emitted < installed * .001
    faces = {face["name"]: face for face in resolved.surfaces}
    assert all(faces[opening["parent"]]["boundary"] == "Outdoors" for opening in resolved.openings)
    if installed - emitted > 1e-8:
        assert any("clearance" in (face["opening_suppression_reason"] or "")
                   for face in resolved.data["facades"])
