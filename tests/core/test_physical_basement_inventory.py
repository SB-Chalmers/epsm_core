"""Basements retain ground boundaries, installed interfaces and shared ownership."""

import pytest
from epsm_data.domain import ConstructionSet
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    BuildingPart,
    Footprint,
    GeometrySpec,
    PartyWall,
    Weather,
    ZoningSpec,
)


def model(**changes):
    return Building(
        preset="illustrative-reference",
        geometry=GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8),
            storeys=2,
            storey_height_m=3,
            basement_depth_m=2,
            basement_conditioned=True,
            **changes,
        ),
    )


@pytest.mark.parametrize("mode", ["whole_building", "per_storey"])
def test_conditioned_basement_keeps_ground_and_internal_ceiling(mode, synthetic_weather):
    building = model(zoning=ZoningSpec(mode=mode))
    assert building.readiness().ready
    bottom = next(e for e in building.elements if e.identifier == "main.basement_floor")
    ceiling = next(e for e in building.elements if e.identifier == "main.ground_floor")
    assert (bottom.area_m2, bottom.elevation_m, bottom.boundary) == (80, -2, "Ground")
    assert (ceiling.area_m2, ceiling.elevation_m, ceiling.boundary) == (80, 0, "Internal")
    assert sum(e.area_m2 for e in building.elements if e.role == Role.BASEMENT_WALL) == 72
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)
    assert all(item["physical_element_id"] for item in resolved.internal_mass)
    assert resolved.operations["load_reference_area_m2"] == 240
    assert sum(zone["volume_m3"] for zone in resolved.zones.values() if zone["conditioned"]) == 640


def test_explicit_basement_floor_recipe_is_not_relabelled_or_rejected(synthetic_weather):
    building = model()
    definitions = dict(building.construction_set.elements)
    ground = definitions[Role.GROUND_FLOOR]
    definitions[Role.BASEMENT_FLOOR] = ground.with_changes(
        application=Role.BASEMENT_FLOOR,
        components=tuple(
            c.with_changes(application=Role.BASEMENT_FLOOR) for c in ground.components
        ),
    )
    building.construction_set = ConstructionSet(elements=definitions)
    bottom = next(e for e in building.elements if e.identifier == "main.basement_floor")
    assert bottom.role == Role.BASEMENT_FLOOR
    assert building.readiness().ready
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)


@pytest.mark.parametrize("mode", ["whole_building", "per_storey"])
def test_attached_basements_count_one_installed_shared_wall(mode, synthetic_weather):
    building = model(zoning=ZoningSpec(mode=mode))
    wing = BuildingPart(
        identifier="wing",
        footprint=Footprint(exterior=((10, 0), (14, 0), (14, 8), (10, 8))),
        storey_elevations_m=(0, 3, 6),
    )
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing))
    walls = [e for e in building.elements if e.role == Role.BASEMENT_WALL]
    assert sum(e.area_m2 for e in walls if e.boundary == "Internal") == 16
    assert sum(e.area_m2 for e in walls if e.boundary == "Ground") == 88
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)
    assert all(item["physical_element_id"] for item in resolved.internal_mass)
    assert (
        sum(
            row.area_m2
            for row in building.quantities()
            if row.element_id in {e.identifier for e in walls if e.boundary == "Internal"}
        )
        > 0
    )


def test_reviewed_below_grade_contact_is_adiabatic_not_ground(synthetic_weather):
    building = model()
    building.geometry = building.geometry.updated(
        party_walls=(
            PartyWall(
                facade_id="main.r0.e0",
                neighbor_id="next",
                contact_confirmed=True,
                neighbor_conditioning="unknown",
                assumption_source="explicit below-grade contact",
                bottom_m=-2,
                top_m=4,
            ),
        )
    )
    assert building.readiness().ready
    basement = [e for e in building.elements if e.role == Role.BASEMENT_WALL]
    assert sum(e.area_m2 for e in basement if e.boundary == "Adiabatic") == 20
    assert sum(e.area_m2 for e in basement if e.boundary == "Ground") == 52
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    faces = [
        face
        for face in resolved.surfaces
        if face["cell_kind"] == "basement"
        and face["kind"] == "Wall"
        and face["boundary"] == "Adiabatic"
    ]
    assert sum(face["gross_area_m2"] for face in faces) == 20
    assert all(face["physical_element_id"] for face in faces)


def test_legacy_basement_interface_requires_explicit_geometry_regeneration():
    from epsm_core import BuildingSnapshot

    legacy = model().snapshot().to_dict()
    legacy["schema"] = "epsm.building/7"
    legacy.pop("zone_uses", None)
    legacy.pop("unconditioned_exchange", None)
    for element in legacy["elements"]:
        if element["identifier"] == "main.ground_floor":
            element["boundary"] = "Ground"
    snapshot = BuildingSnapshot.from_dict(legacy)
    restored = snapshot.to_building()
    assert restored.snapshot().sha256 == snapshot.sha256
    assert any("boundary" in issue for issue in restored.readiness().unsupported)
    restored.geometry = restored.geometry
    assert restored.readiness().ready
    assert restored.snapshot().sha256 != snapshot.sha256
    assert restored.snapshot().to_dict()["schema"] == "epsm.building/8"
    assert next(e for e in restored.elements if e.identifier == "main.ground_floor").boundary == "Internal"
    assert next(e for e in snapshot.to_building().elements
                if e.identifier == "main.ground_floor").boundary == "Ground"


def test_asymmetric_basement_floor_is_one_owner_with_reciprocal_layers(
    synthetic_weather, energyplus,
):
    from epsm_core import EnergyPlusCompiler

    building = model(zoning=ZoningSpec(mode="per_storey"))
    # The illustrative floor has distinct insulation and concrete layers, so a
    # direction error is observable rather than hidden by a symmetric recipe.
    weather = Weather.from_epw(synthetic_weather)
    resolved = building.resolve(weather)
    interface = [face for face in resolved.surfaces
                 if face["physical_element_id"] == "main.ground_floor"]
    assert len(interface) == 2
    assert {face["reverse"] for face in interface} == {False, True}
    assert interface[0]["construction"] == interface[1]["construction"]
    assert interface[0]["adjacent"] == interface[1]["name"]
    data, _ = EnergyPlusCompiler(energyplus).compile(building.to_spec(weather))
    names = [data["BuildingSurface:Detailed"][face["name"]]["construction_name"]
             for face in interface]
    layers = [list(data["Construction"][name].values()) for name in names]
    assert len(layers[0]) >= 2
    assert layers[0][0] != layers[0][-1]
    assert layers[0] == list(reversed(layers[1]))
