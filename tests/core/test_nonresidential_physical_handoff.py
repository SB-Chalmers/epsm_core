"""Physical boundaries retain source roles and compiled room-side material order."""
import math

import pytest
from epsm_data import Catalogue
from epsm_data.domain import ConstructionSet
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import (
    Building,
    EnergyPlusCompiler,
    Footprint,
    GeometrySpec,
    RoofSpec,
    Weather,
    ZoningSpec,
)
from epsm_core.building_adapter import thermal_construction


def relabel(element, role):
    return element.with_changes(application=role, components=tuple(
        component.with_changes(application=role) for component in element.components))


def reference(roof=None, basement=False, zoning="per_storey"):
    return Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        roof=roof or RoofSpec(shape="flat"), basement_depth_m=2 if basement else 0,
        basement_conditioned=basement, zoning=ZoningSpec(mode=zoning)))


def material_totals(assembly):
    return (sum(x.thickness_m/x.material.conductivity_w_mk for x in assembly.layers),
            sum(x.thickness_m*x.material.density_kg_m3 for x in assembly.layers),
            sum(x.thickness_m*x.material.density_kg_m3*x.material.specific_heat_j_kgk
                for x in assembly.layers))


@pytest.mark.parametrize("role, films", [(Role.EXT_WALL, .17), (Role.INTERMEDIATE_FLOOR, .26)])
def test_physical_thermal_handoff_retains_domain_nominal_boundary_resistance(role, films):
    source = reference().construction_set.elements[role]
    assembly = thermal_construction(source)
    assert assembly.surface_resistance_m2k_w == pytest.approx(films)
    assert assembly.u_value_w_m2k == pytest.approx(source.u_value)


@pytest.mark.parametrize("route", ["constructor", "assignment"])
def test_compact_roof_role_alias_preserves_materials_and_ready_top(route, synthetic_weather):
    building = reference()
    definitions = dict(building.construction_set.elements)
    definitions.pop(Role.TOP_FLOOR)
    source = relabel(definitions[Role.EXT_WALL], Role.ROOF)
    definitions[Role.ROOF] = source
    incoming = ConstructionSet(elements=definitions)
    before = source.to_dict()
    if route == "constructor":
        building.construction_set = incoming
    else:
        report = building.assign_inputs(construction_set=incoming)
        assert "construction:ROOF" not in report.unmatched
    top = next(e for e in building.elements if e.identifier == "main.top")
    assert top.role == Role.TOP_FLOOR and top.boundary == "Outdoors"
    assert top.construction.application == Role.TOP_FLOOR
    assert source.to_dict() == before
    assert material_totals(thermal_construction(top.construction)) == pytest.approx(
        material_totals(thermal_construction(source)))
    # A later regeneration must retain the replacement instead of a stale
    # previously installed TOP_FLOOR from the reference construction set.
    building.construction_set = building.construction_set
    top = next(e for e in building.elements if e.identifier == "main.top")
    assert thermal_construction(top.construction) == thermal_construction(source)
    assert building.readiness(engine="energyplus").ready
    assert building.to_spec(Weather.from_epw(synthetic_weather)).envelope.top == thermal_construction(source)


def test_explicit_compact_top_beats_roof_alias_and_cold_attic_never_aliases():
    compact = reference()
    top = compact.construction_set.elements[Role.TOP_FLOOR]
    assert next(e for e in compact.elements if e.identifier == "main.top").construction == top
    attic = reference(RoofSpec(shape="gable", pitch_deg=30))
    definitions = dict(attic.construction_set.elements)
    del definitions[Role.TOP_FLOOR]
    attic.construction_set = ConstructionSet(elements=definitions)
    assert next(e for e in attic.elements if e.identifier == "main.top").construction is None
    assert "construction:main.top" in attic.readiness().missing
    assert all(e.construction is not None for e in attic.elements if e.role == Role.ROOF)


@pytest.mark.parametrize("basement", [False, True])
@pytest.mark.parametrize("route", ["constructor", "assignment"])
def test_explicit_soil_slab_precedes_suspended_ground_floor(basement, route, synthetic_weather):
    building = reference(basement=basement)
    definitions = dict(building.construction_set.elements)
    suspended = definitions[Role.GROUND_FLOOR]
    # A distinct assembly makes accidental ceiling/slab substitution observable.
    soil = relabel(definitions[Role.EXT_WALL], Role.BASEMENT_FLOOR)
    definitions[Role.BASEMENT_FLOOR] = soil
    incoming = ConstructionSet(elements=definitions)
    if route == "constructor":
        building.construction_set = incoming
    else:
        building.assign_inputs(construction_set=incoming)
    bottom_id = "main.basement_floor" if basement else "main.ground_floor"
    bottom = next(e for e in building.elements if e.identifier == bottom_id)
    assert bottom.role == Role.BASEMENT_FLOOR and bottom.boundary == "Ground"
    assert bottom.construction == soil
    spec = building.to_spec(Weather.from_epw(synthetic_weather))
    assert spec.envelope.ground == thermal_construction(soil)
    if basement:
        ceiling = next(e for e in building.elements if e.identifier == "main.ground_floor")
        assert ceiling.role == Role.GROUND_FLOOR and ceiling.boundary == "Internal"
        assert ceiling.construction == suspended
        assert spec.envelope.basement_ceiling == thermal_construction(suspended)


def test_fill_missing_retains_explicit_installed_soil_choice():
    building = reference()
    installed = next(e for e in building.elements if e.identifier == "main.ground_floor")
    definitions = dict(building.construction_set.elements)
    definitions[Role.BASEMENT_FLOOR] = relabel(definitions[Role.EXT_WALL], Role.BASEMENT_FLOOR)
    building.assign_inputs(construction_set=ConstructionSet(elements=definitions), mode="fill_missing")
    current = next(e for e in building.elements if e.identifier == "main.ground_floor")
    assert current.role == installed.role and current.construction == installed.construction
    assert building.readiness().ready


@pytest.mark.parametrize("basement", [False, True])
def test_partial_window_replacement_retains_explicit_soil_role_and_occurrences(basement):
    building = reference(basement=basement)
    definitions = dict(building.construction_set.elements)
    definitions[Role.BASEMENT_FLOOR] = relabel(definitions[Role.EXT_WALL], Role.BASEMENT_FLOOR)
    building.construction_set = ConstructionSet(elements=definitions)
    bottom_id = "main.basement_floor" if basement else "main.ground_floor"
    before = next(e for e in building.elements if e.identifier == bottom_id)
    window = definitions[Role.WINDOW].with_changes(u_value=.9)
    building.assign_inputs(construction_set=ConstructionSet(elements={Role.WINDOW: window}))
    after = next(e for e in building.elements if e.identifier == bottom_id)
    assert after == before
    assert building.readiness().ready


def test_ground_floor_only_replacement_updates_basement_ceiling_without_demoting_soil():
    building = reference(basement=True)
    definitions = dict(building.construction_set.elements)
    definitions[Role.BASEMENT_FLOOR] = relabel(definitions[Role.EXT_WALL], Role.BASEMENT_FLOOR)
    building.construction_set = ConstructionSet(elements=definitions)
    before = next(e for e in building.elements if e.identifier == "main.basement_floor")
    ceiling = relabel(definitions[Role.TOP_FLOOR], Role.GROUND_FLOOR)
    building.assign_inputs(construction_set=ConstructionSet(elements={Role.GROUND_FLOOR: ceiling}))
    assert next(e for e in building.elements if e.identifier == "main.basement_floor") == before
    assert next(e for e in building.elements if e.identifier == "main.ground_floor").construction == ceiling


def test_explicit_ground_floor_soil_replacement_at_grade_remains_possible():
    building = reference()
    definitions = dict(building.construction_set.elements)
    definitions[Role.BASEMENT_FLOOR] = relabel(definitions[Role.EXT_WALL], Role.BASEMENT_FLOOR)
    building.construction_set = ConstructionSet(elements=definitions)
    soil = definitions[Role.GROUND_FLOOR]
    building.assign_inputs(construction_set=ConstructionSet(elements={Role.GROUND_FLOOR: soil}))
    selected = next(e for e in building.elements if e.identifier == "main.ground_floor")
    assert selected.role == Role.GROUND_FLOOR and selected.construction == soil
    building.construction_set = building.construction_set
    selected = next(e for e in building.elements if e.identifier == "main.ground_floor")
    assert selected.role == Role.GROUND_FLOOR and selected.construction == soil
    assert building.readiness().ready


@pytest.mark.parametrize("category,era", [("office", 1), ("office", 2), ("school", 1), ("school", 2)])
def test_authored_nonresidential_floor_finish_faces_upper_room(category, era, synthetic_weather, energyplus):
    catalogue = Catalogue.load()
    aid = f"{category}_se{era:02}"
    archetype = catalogue.get(aid)
    metadata = catalogue.nominal_metadata(aid)
    roof = (RoofSpec(shape="gable", pitch_deg=30) if metadata["roof_topology"] == "cold_attic"
            else RoofSpec(shape="flat"))
    building = reference(roof)
    building.assign_inputs(construction_set=archetype.construction_set)
    assert building.readiness(engine="energyplus").ready
    weather = Weather.from_epw(synthetic_weather)
    spec = building.to_spec(weather)
    if era == 1:
        soil = next(e for e in building.elements if e.identifier == "main.ground_floor")
        assert soil.role == Role.BASEMENT_FLOOR
        assert len(spec.envelope.ground.layers) == 1
        assert spec.envelope.ground.layers[0].thickness_m == pytest.approx(.1)
        assert spec.envelope.ground == thermal_construction(soil.construction)
    floor = next(e for e in building.elements if e.role == Role.INTERMEDIATE_FLOOR)
    assembly = thermal_construction(floor.construction)
    assert assembly.layers[-1].thickness_m == pytest.approx(.0025)
    assert assembly.layers[0].thickness_m == pytest.approx(.015 if era == 1 else .025)
    assert material_totals(spec.envelope.intermediate_floor) == pytest.approx(material_totals(assembly))
    model, _ = EnergyPlusCompiler(energyplus).compile(spec)
    resolved = building.resolve(weather)
    faces = [face for face in resolved.surfaces if face["physical_element_id"] == floor.identifier]
    assert {face["kind"] for face in faces} == {"Floor", "Ceiling"}
    room_side_depths = {}
    for face in faces:
        compiled = model["BuildingSurface:Detailed"][face["name"]]
        layers = list(model["Construction"][compiled["construction_name"]].values())
        room_side_depths[face["kind"]] = model["Material"][layers[-1]]["thickness"]
    assert room_side_depths["Floor"] == pytest.approx(.0025)
    assert room_side_depths["Ceiling"] == pytest.approx(.015 if era == 1 else .025)
    assert math.isclose(sum(q.mass_kg for q in building.quantities()
                            if q.element_id == floor.identifier),
                        floor.area_m2*material_totals(assembly)[1], rel_tol=1e-10)


def test_custom_outside_inside_intermediate_stack_is_not_globally_reversed(synthetic_weather):
    building = reference()
    source = building.construction_set.elements[Role.INTERMEDIATE_FLOOR]
    assembly = thermal_construction(source)
    spec = building.to_spec(Weather.from_epw(synthetic_weather))
    assert spec.envelope.intermediate_floor.layers == assembly.layers
