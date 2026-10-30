"""Physical cold-attic inventory agrees with the actual thermal shell."""

import math

import pytest
from epsm_data.domain import ConstructionSet
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    BuildingPart,
    Footprint,
    GeometrySpec,
    PartyWall,
    RoofSpec,
    Weather,
    ZoningSpec,
)


def model(roof, **geometry_changes):
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8),
        storeys=2,
        storey_height_m=3,
        roof=roof,
        **geometry_changes,
    )
    return Building(preset="illustrative-reference", geometry=geometry)


@pytest.mark.parametrize("shape", ["flat", "gable", "mono_pitch", "hip"])
def test_cold_attic_has_actual_shell_and_separate_ceiling(shape, synthetic_weather):
    if shape == "hip":
        pytest.importorskip("py_straight_skeleton")
    roof = RoofSpec(
        shape=shape,
        topology="cold_attic",
        **(
            {"pitch_deg": 30, "direction_deg": 90}
            if shape in {"gable", "mono_pitch"}
            else {"pitch_deg": 30}
            if shape == "hip"
            else {}
        ),
    )
    building = model(roof)
    assert building.readiness(engine="energyplus").ready
    shell = [e for e in building.elements if e.role == Role.ROOF]
    expected = 80 if shape == "flat" else 80 / math.cos(math.radians(30))
    assert sum(e.area_m2 for e in shell) == pytest.approx(expected)
    ceiling = next(e for e in building.elements if e.identifier == "main.top")
    assert ceiling.area_m2 == 80 and ceiling.boundary == "Internal"
    gables = [e for e in building.elements if e.role == Role.EXT_WALL and e.storey == 2]
    expected_gables = {
        "flat": 54,
        "gable": 32 * math.tan(math.radians(30)),
        "mono_pitch": 180 * math.tan(math.radians(30)),
        "hip": 0,
    }
    assert sum(e.area_m2 for e in gables) == pytest.approx(expected_gables[shape])
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)
    assert all(
        face["physical_element_id"] in {e.identifier for e in gables}
        for face in resolved.surfaces
        if face["cell_kind"] == "attic" and face["kind"] == "Wall"
    )
    assert not any(opening["metadata"]["storey"] == 2 for opening in resolved.openings)
    snapshot = building.snapshot()
    assert snapshot.to_building().snapshot().sha256 == snapshot.sha256


def test_missing_shell_construction_remains_missing():
    building = model(RoofSpec(shape="gable"))
    elements = dict(building.construction_set.elements)
    del elements[Role.ROOF]
    building.construction_set = ConstructionSet(elements=elements)
    assert "construction:main.roof" in building.readiness().missing
    assert not building.readiness("quantities").ready


def test_shell_gable_and_ceiling_keep_distinct_physical_recipes(synthetic_weather):
    building = model(RoofSpec(shape="gable", pitch_deg=30, direction_deg=90))
    roof = next(e for e in building.elements if e.role == Role.ROOF)
    component = roof.construction.components[0]
    slot = component.layers[0]
    thin_layer = slot.layer.with_changes(
        thickness=0.03,
        materials=tuple(share.with_changes(thickness=0.03) for share in slot.layer.materials),
    )
    changed = roof.construction.with_changes(
        components=(
            component.with_changes(
                layers=(slot.with_changes(layer=thin_layer), *component.layers[1:])
            ),
        )
    )
    original = building.snapshot()
    building.assign_construction(changed, element_ids=(roof.identifier,))
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    attic = [face for face in resolved.surfaces if face["cell_kind"] == "attic"]
    assert {
        face["construction"]["layers"][0]["thickness_m"] for face in attic if face["kind"] == "Roof"
    } == {0.03}
    assert {
        face["construction"]["layers"][0]["thickness_m"] for face in attic if face["kind"] == "Wall"
    } == {0.15}
    assert {
        face["construction"]["layers"][0]["thickness_m"]
        for face in attic
        if face["kind"] == "Floor"
    } == {0.25}
    assert (
        next(e for e in original.to_building().elements if e.role == Role.ROOF).construction
        != changed
    )


def test_roof_materials_and_areas_do_not_depend_on_virtual_zones():
    building = model(RoofSpec(shape="gable", pitch_deg=30, direction_deg=90))
    baseline = [(e.identifier, e.area_m2, e.role, e.boundary) for e in building.elements]
    quantities = building.quantities().by_material()
    for mode in ("whole_building", "per_storey", "perimeter_core"):
        building.geometry = building.geometry.updated(zoning=ZoningSpec(mode=mode))
        assert [
            (e.identifier, e.area_m2, e.role, e.boundary) for e in building.elements
        ] == baseline
        assert building.quantities().by_material() == quantities


@pytest.mark.parametrize(
    "footprint,shape",
    [
        (Footprint.l_shape(30, 30, 15, 15), "gable"),
        (
            Footprint(
                exterior=((0, 0), (30, 0), (30, 30), (0, 30)),
                holes=(((10, 10), (10, 20), (20, 20), (20, 10)),),
            ),
            "hip",
        ),
    ],
)
def test_concave_and_courtyard_shells_keep_physical_owners(footprint, shape, synthetic_weather):
    if shape == "hip":
        pytest.importorskip("py_straight_skeleton")
    building = Building(
        preset="illustrative-reference",
        geometry=GeometrySpec.from_footprint(
            footprint,
            storeys=3,
            storey_height_m=3,
            roof=RoofSpec(shape=shape, direction_deg=90 if shape == "gable" else None),
        ),
    )
    assert building.readiness().ready
    roof = next(e for e in building.elements if e.role == Role.ROOF)
    assert roof.area_m2 == pytest.approx(footprint.area_m2 / math.cos(math.radians(30)))
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(f["physical_element_id"] for f in resolved.surfaces)
    assert sum(
        f["gross_area_m2"]
        for f in resolved.surfaces
        if f["kind"] == "Roof" and f["cell_kind"] == "attic"
    ) == pytest.approx(roof.area_m2)


def test_separated_parts_can_have_different_roof_topologies(synthetic_weather):
    building = model(RoofSpec())
    wing = BuildingPart(
        identifier="wing",
        footprint=Footprint(exterior=((20, 0), (30, 0), (30, 8), (20, 8))),
        storey_elevations_m=(0, 3, 6),
        roof=RoofSpec(shape="gable"),
    )
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing))
    assert next(e for e in building.elements if e.identifier == "main.top").boundary == "Outdoors"
    assert next(e for e in building.elements if e.identifier == "wing.top").boundary == "Internal"
    assert {e.part_id for e in building.elements if e.role == Role.ROOF} == {"wing"}
    assert all(
        face["physical_element_id"]
        for face in building.resolve(Weather.from_epw(synthetic_weather)).surfaces
    )


def test_attached_flat_attics_keep_one_shared_attic_wall(synthetic_weather):
    building = model(RoofSpec(topology="cold_attic"), zoning=ZoningSpec(mode="whole_building"))
    wing = BuildingPart(
        identifier="wing",
        footprint=Footprint(exterior=((10, 0), (14, 0), (14, 8), (10, 8))),
        storey_elevations_m=(0, 3, 6),
    )
    building.geometry = building.geometry.updated(parts=(*building.geometry.parts, wing))
    shared = [e for e in building.elements if e.boundary == "Internal" and e.storey == 2]
    assert len(shared) == 1
    assert shared[0].identifier.endswith(".attic_internal_wall")
    assert shared[0].elevation_m == 6 and shared[0].area_m2 == 12
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)
    assert all(item["physical_element_id"] for item in resolved.internal_mass)


def test_pitched_attic_contacts_above_eave_are_explicitly_unsupported():
    building = model(RoofSpec(shape="gable"))
    building.geometry = building.geometry.updated(
        party_walls=(
            PartyWall(
                facade_id="main.r0.e1",
                neighbor_id="taller",
                contact_confirmed=True,
                neighbor_conditioning="unknown",
                assumption_source="synthetic taller neighbor",
                bottom_m=0,
                top_m=8,
            ),
        )
    )
    assert any("above the eave" in issue for issue in building.readiness().unsupported)


def test_legacy_unsupported_roof_draft_remains_inspectable_without_regeneration():
    from epsm_core import BuildingSnapshot

    building = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.l_shape(30, 30, 15, 15), storeys=3, storey_height_m=3))
    legacy = building.snapshot().to_dict()
    legacy["schema"] = "epsm.building/7"
    legacy.pop("zone_uses", None)
    legacy.pop("unconditioned_exchange", None)
    legacy["geometry"]["roof"] = RoofSpec(shape="gable").model_dump(mode="json")
    # Core 0.6 retained this draft's planar inventory but explicitly rejected
    # all pitched roofs. Its default ridge also fails strict roof coverage.
    snapshot = BuildingSnapshot.from_dict(legacy)
    restored = snapshot.to_building()
    assert restored.snapshot().sha256 == snapshot.sha256
    assert not any(e.role == Role.ROOF for e in restored.elements)
    assert any("coverage" in issue for issue in restored.readiness().unsupported)
    assert restored.snapshot().sha256 == snapshot.sha256


def test_pitched_roof_preserves_main_shared_wall_and_no_windows(synthetic_weather):
    building = model(RoofSpec(shape="gable"))
    building.geometry = building.geometry.updated(
        party_walls=(
            PartyWall(
                facade_id="main.r0.e1",
                neighbor_id="next",
                contact_confirmed=True,
                neighbor_conditioning="unknown",
                assumption_source="synthetic eave contact",
                bottom_m=0,
                top_m=6,
            ),
        )
    )
    assert building.readiness().ready
    assert sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic") == pytest.approx(
        48
    )
    assert not any(e.facade_id == "main.r0.e1" and e.role == Role.WINDOW for e in building.elements)
    resolved = building.resolve(Weather.from_epw(synthetic_weather))
    assert all(face["physical_element_id"] for face in resolved.surfaces)


@pytest.mark.energyplus
@pytest.mark.parametrize("shape", ["gable", "hip"])
def test_physical_pitched_roof_runs_real_energyplus(shape, synthetic_weather, energyplus, tmp_path):
    if shape == "hip":
        pytest.importorskip("py_straight_skeleton")
    from epsm_core import run_building

    building = model(RoofSpec(shape=shape))
    result = run_building(
        building,
        weather=Weather.from_epw(synthetic_weather),
        energyplus=energyplus,
        directory=tmp_path / shape,
    )
    assert result.diagnostics["accepted"]
    assert result.diagnostics["building_snapshot_id"] == building.snapshot().sha256
