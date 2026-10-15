"""Resolved geometry, provenance, and immutable compiler-input contract."""

import math
from pathlib import Path

import pytest

from epsm_core import (
    Building,
    BuildingPart,
    BalconySpec,
    EnergyPlusCompiler,
    FacadeOverride,
    Footprint,
    OverhangSpec,
    Weather,
    WindowLayoutSpec,
    ZoneUseSpec,
    ZoningSpec,
    resolve_building,
)


def test_spec_resolution_is_deterministic_and_does_not_read_weather_files(
        building, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Resolving an existing BuildingSpec must not access weather files")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr("epsm_core.weather.file_sha256", forbidden)

    first = resolve_building(building)
    second = resolve_building(building)
    assert first.to_dict() == second.to_dict()
    assert first.data["schema"] == "epsm.resolved_building/1"
    assert first.source_kind == "building_spec"
    # A BuildingSpec source is identified by its stable physical hash; its
    # human-readable identifier remains available in the exported data.
    assert first.source_id == building.physical_hash()
    assert first.data["identifier"] == building.identifier
    assert first.source_snapshot_id is None
    assert first.source_spec_hash == building.physical_hash()


def test_resolved_input_is_recursively_immutable_but_export_is_detached(building):
    resolved = resolve_building(building)
    assert isinstance(resolved.surfaces, tuple)
    assert isinstance(resolved.openings, tuple)
    assert isinstance(resolved.internal_mass, tuple)
    with pytest.raises(TypeError):
        resolved.data["identifier"] = "changed"
    with pytest.raises(TypeError):
        resolved.surfaces[0]["name"] = "changed"
    with pytest.raises(TypeError):
        resolved.surfaces[0]["vertices"][0][0] = -1
    zone_name = next(iter(resolved.zones))
    with pytest.raises(TypeError):
        resolved.zones[zone_name]["floor_area_m2"] = -1
    with pytest.raises(TypeError):
        resolved.operations["use"]["equipment_gain_w_m2"] = 999

    exported = resolved.to_dict()
    exported["schema"] = "mutated"
    exported["geometry"]["origin_m"][0] = 999
    assert resolved.data["schema"] == "epsm.resolved_building/1"
    assert resolved.to_dict()["geometry"]["origin_m"][0] != 999


def test_resolved_input_is_detached_from_mutable_source_maps(building):
    target = next(face["name"] for face in resolve_building(building).surfaces if face["kind"] == "Wall")
    spec = building.updated(surface_constructions={target: building.envelope.wall})
    resolved = resolve_building(spec)
    before = resolved.to_dict()

    # Frozen specs can still contain mutable dictionaries; the resolved view
    # must remain a detached snapshot if callers mutate those dictionaries.
    spec.surface_constructions[target] = building.envelope.top
    spec.surface_constructions["added.later"] = building.envelope.ground
    assert resolved.to_dict() == before


@pytest.mark.parametrize(
    "footprint,expected_area",
    [
        (Footprint.rectangle(30, 20), 600),
        (Footprint(exterior=((0, 0), (12, 0), (12, 4), (5, 4), (5, 10), (0, 10))), 78),
        (Footprint(exterior=((0, 0), (12, 0), (12, 10), (0, 10)),
                   holes=(((4, 3), (8, 3), (8, 7), (4, 7)),)), 104),
    ],
    ids=("rectangle", "concave", "courtyard"),
)
def test_resolved_geometry_preserves_area_volume_origin_and_orientation(
        building, footprint, expected_area):
    part = building.geometry.parts[0].updated(footprint=footprint)
    geometry = building.geometry.updated(parts=(part,), orientation_deg=31)
    resolved = resolve_building(building.updated(geometry=geometry))

    assert sum(zone["floor_area_m2"] for zone in resolved.zones.values()) == pytest.approx(
        expected_area * 3
    )
    assert sum(zone["volume_m3"] for zone in resolved.zones.values()) == pytest.approx(
        expected_area * 8.4
    )
    assert resolved.geometry["origin_m"] == pytest.approx((0, 0))
    assert resolved.geometry["orientation_deg"] == pytest.approx(31)
    # The exported footprint is translated to the common origin and then rotated
    # clockwise into the scene frame, matching the resolved geometry graph.
    local_ring = resolved.geometry["local_footprints"][0]["coordinates"][0]
    assert resolved.geometry["coordinate_frame"] == "local_metric_after_scene_rotation"
    # GeoJSON stores closed rings.
    local_ring = local_ring[:-1]
    origin_x, origin_y = resolved.geometry["origin_m"]
    radians = math.radians(31)
    expected_ring = tuple(
        ((x - origin_x) * math.cos(radians) + (y - origin_y) * math.sin(radians),
         -(x - origin_x) * math.sin(radians) + (y - origin_y) * math.cos(radians))
        for x, y in footprint.exterior
    )
    assert all(any(tuple(point) == pytest.approx(expected) for point in local_ring)
               for expected in expected_ring)


def test_resolved_multipart_geometry_uses_one_local_origin(building):
    main = building.geometry.parts[0].updated(
        footprint=Footprint(exterior=((10, 5), (18, 5), (18, 11), (10, 11)))
    )
    annex = BuildingPart(
        identifier="annex",
        footprint=Footprint(exterior=((40, 15), (46, 15), (46, 21), (40, 21))),
        storey_elevations_m=(0, 3, 6),
    )
    geometry = building.geometry.updated(parts=(main, annex), orientation_deg=45)
    resolved = resolve_building(building.updated(geometry=geometry))
    assert resolved.geometry["origin_m"] == pytest.approx((10, 5))
    assert resolved.geometry["orientation_deg"] == pytest.approx(45)
    assert len(resolved.geometry["local_footprints"]) == 2
    assert sum(zone["floor_area_m2"] for zone in resolved.zones.values()) == pytest.approx(
        48 * 3 + 36 * 2
    )
    assert sum(zone["volume_m3"] for zone in resolved.zones.values()) == pytest.approx(
        48 * 8.4 + 36 * 6
    )


def test_resolved_metrics_match_compiler_and_surface_areas(building, energyplus):
    spec = building.updated(facade=building.facade.updated(reveal_depth_m=0.2))
    resolved = resolve_building(spec)
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    compiled = report.data

    assert set(resolved.zones) == set(compiled["zones"])
    for name, zone in resolved.zones.items():
        source = compiled["zones"][name]
        assert zone["floor_area_m2"] == pytest.approx(source["floor_area_m2"])
        assert zone["volume_m3"] == pytest.approx(source["volume_m3"])
        assert zone["operation"]["equipment_gain_w_m2"] == pytest.approx(
            spec.use.equipment_gain_w_m2
        )

    source_surfaces = compiled["surfaces"]
    assert {face["name"] for face in resolved.surfaces} == set(source_surfaces)
    for face in resolved.surfaces:
        source = source_surfaces[face["name"]]
        assert face["gross_area_m2"] == pytest.approx(source["area_m2"])
        assert face["net_area_m2"] == pytest.approx(
            face["gross_area_m2"] - face["opening_area_m2"]
        )
    assert {item["name"] for item in resolved.shading} == set(compiled["shading"])


def test_resolved_panelized_shading_keeps_opening_and_physical_area_ownership(
        building, synthetic_weather):
    from collections import defaultdict

    b = Building(preset="illustrative-reference")
    b.geometry = b.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    b.operation = b.operation.updated(occupancy_category="residential")
    b.facade = b.facade.updated(
            layout=WindowLayoutSpec(mode="wwr"),
            reveal_depth_m=0.2,
            overhang=OverhangSpec(depth_m=0.6),
            balconies=(BalconySpec(
                facade_id="main.r0.e0", storeys=(1, 2), start_m=2,
                width_m=4, depth_m=1.5, side_screen_height_m=1,
            ),),
            overrides=(FacadeOverride(facade_id="main.r0.e0", storey=0, wwr=0.1),),
        )
    resolved = b.resolve(Weather.from_epw(synthetic_weather))
    assert resolved.data["panelize"] is True
    assert {item["kind"] for item in resolved.shading} == {"reveal", "overhang", "balcony"}

    physical = {item["identifier"]: item for item in resolved.physical_elements}
    opening_area_by_owner = defaultdict(float)
    for opening in resolved.openings:
        opening_area_by_owner[opening["physical_element_id"]] += opening["area_m2"]
    assert opening_area_by_owner
    assert set(opening_area_by_owner) <= physical.keys()
    for owner_id, area in opening_area_by_owner.items():
        assert physical[owner_id]["area_m2"] == pytest.approx(area)
    assert resolved.logical_window_count == len({opening["logical_window"]
                                                 for opening in resolved.openings})
    assert len(resolved.openings) >= resolved.logical_window_count


def test_zone_operation_override_and_reference_area_are_preserved(building):
    names = sorted(resolve_building(building).zones)
    selected = names[0]
    reference_area = 300
    use = building.use.updated(equipment_gain_w_m2=7)
    spec = building.updated(
        load_reference_area_m2=900,
        zone_uses=(
            # The exact selector carries the same share as the default scaled areas here.
            ZoneUseSpec(
                zone_name=selected,
                use=use,
                reference_area_m2=reference_area,
                source="synthetic resolved-input test",
            ),
        ),
    )
    resolved = resolve_building(spec)
    zone = resolved.zones[selected]
    assert resolved.to_dict()["zones"][selected]["operation"] == use.model_dump(mode="json")
    assert zone["operation_sources"] == ("synthetic resolved-input test",)
    assert zone["load_reference_area_m2"] == pytest.approx(reference_area)
    assert zone["load_reference_area_basis"] == "zone_override"


def test_physical_snapshot_identity_and_wall_window_mass_ownership(synthetic_weather):
    from epsm_data.domain.enums import BuildingElement as Role

    weather = Weather.from_epw(synthetic_weather)
    building = Building(preset="illustrative-reference")
    building.geometry = building.geometry.updated(
        zoning=ZoningSpec(mode="whole_building")
    )
    before = building.snapshot().sha256
    resolved = building.resolve(weather)
    from_snapshot = building.snapshot().resolve(weather)

    assert building.snapshot().sha256 == before
    assert resolved.to_dict() == from_snapshot.to_dict()
    assert resolved.source_kind == "building_snapshot"
    assert resolved.source_snapshot_id == before
    assert resolved.source_id == before
    physical = {item["identifier"] for item in resolved.physical_elements}
    assert physical == {element.identifier for element in building.elements}

    wall_ids = {element.identifier for element in building.elements if element.role == Role.EXT_WALL}
    window_ids = {element.identifier for element in building.elements if element.role == Role.WINDOW}
    slab_ids = {element.identifier for element in building.elements
                if element.role == Role.INTERMEDIATE_FLOOR}
    assert wall_ids & {face["physical_element_id"] for face in resolved.surfaces}
    assert window_ids & {opening["physical_element_id"] for opening in resolved.openings}
    assert slab_ids & {item["physical_element_id"] for item in resolved.internal_mass}

    inventory_ids = {row.element_id for row in building.quantities()}
    # Operational systems can be quantity rows without being physical envelope
    # elements. Every architectural inventory item must still resolve to an owner.
    assert {item.identifier for item in building.elements} <= inventory_ids
    assert inventory_ids - physical == {"equipment.heating", "equipment.ventilation"}


def test_unknown_physical_assignment_targets_are_not_silently_dropped(building):
    with pytest.raises(ValueError, match="Unknown surface construction targets"):
        resolve_building(building.updated(surface_constructions={"missing": building.envelope.wall}))
    with pytest.raises(ValueError, match="Unknown physical internal-mass construction targets"):
        resolve_building(building.updated(internal_mass_constructions={"missing": building.envelope.intermediate_floor}))


def test_reciprocal_faces_keep_nominal_owner_and_reverse_role(building):
    resolved = resolve_building(building)
    faces = {face["name"]: face for face in resolved.surfaces}
    reversed_faces = [face for face in faces.values() if face["reverse"]]
    assert reversed_faces
    for face in reversed_faces:
        assert face["construction_role"].endswith("_reverse")
        assert face["boundary"] == "Surface"
        counterpart = faces[face["adjacent"]]
        assert counterpart["adjacent"] == face["name"]
        assert counterpart["construction"] == face["construction"]


def test_complete_legacy_snapshot_keeps_original_identity_during_resolution(synthetic_weather):
    from epsm_core import BuildingSnapshot
    data = Building(preset="illustrative-reference").to_dict()
    data["schema"] = "epsm.building/5"
    data["preset_revision"] = "4"
    data["operation"].pop("gain_partitions")
    for record in data["provenance"]["records"]:
        if record["assumption_profile"] == "illustrative-reference@5":
            record["assumption_profile"] = record["source"] = "illustrative-reference@4"
    snapshot = BuildingSnapshot.from_dict(data)
    restored = snapshot.to_building()
    resolved = restored.resolve(Weather.from_epw(synthetic_weather))
    assert restored.snapshot().sha256 == snapshot.sha256
    assert resolved.source_snapshot_id == snapshot.sha256
    assert resolved.operations["use"]["gain_partitions"] is None


def test_targeted_wall_and_mass_nominal_constructions_keep_physical_ownership(synthetic_weather):
    from dataclasses import replace
    from epsm_data.domain.enums import BuildingElement as Role

    building = Building(preset="illustrative-reference")
    building.geometry = building.geometry.updated(zoning=ZoningSpec(mode="whole_building"))
    targets = [next(element for element in building.elements if element.role == role)
               for role in (Role.EXT_WALL, Role.INTERMEDIATE_FLOOR)]
    expected = {}
    for target in targets:
        component = target.construction.components[0]
        slot = component.layers[0]
        layer = replace(slot.layer, thickness=slot.layer.thickness * 2,
                        materials=tuple(replace(share, thickness=share.thickness * 2)
                                        for share in slot.layer.materials))
        changed = replace(target.construction, components=(
            replace(component, layers=(replace(slot, layer=layer), *component.layers[1:])),
            *target.construction.components[1:]))
        building.assign_construction(changed, element_ids=(target.identifier,))
        expected[target.identifier] = layer.thickness
    identity = building.snapshot().sha256
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    for target, thickness in expected.items():
        records = [item for item in (*resolved.surfaces, *resolved.internal_mass)
                   if item["physical_element_id"] == target]
        assert records
        assert all(item["construction"]["layers"][0]["thickness_m"] == thickness for item in records)
    assert building.snapshot().sha256 == identity
    assert sum(item["area_m2"] for item in resolved.internal_mass) == pytest.approx(
        sum(element.area_m2 for element in building.elements if element.role == Role.INTERMEDIATE_FLOOR))
