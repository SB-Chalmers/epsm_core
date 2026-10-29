"""Catalogue renovation candidates applied through Building.renovate with geometric quantities."""

import json
import math

import pytest
from epsm_data import Catalogue, RenovationCatalogue
from epsm_data.domain.enums import BuildingElement as Role

from epsm_core import Building, BuildingSnapshot, Footprint, GeometrySpec
from epsm_core.measures import apply_candidates, resolve_candidate, ventilation_drivers


@pytest.fixture(scope="module")
def library():
    return Catalogue.load()


@pytest.fixture(scope="module")
def renovations(library):
    return RenovationCatalogue.load(library)


def building(library, *, ventilation="S"):
    result = Building(
        preset="illustrative-reference",
        construction_set=library.get("mf_se02", state="existing").construction_set,
        geometry=GeometrySpec.from_footprint(Footprint.rectangle(30, 12), storeys=4,
                                             storey_height_m=2.8, basement_depth_m=2.4,
                                             basement_conditioned=True))
    result.hvac = result.hvac.with_changes(airflow=result.hvac.airflow.model_dump() | {
        "topology": ventilation, "mechanical_vent_l_s_m2": 0.0 if ventilation == "S" else 0.35,
        "natural_exchange_ach": 0.5 if ventilation == "S" else 0.0,
        "sensible_recovery_effectiveness": 0.0})
    return result


def test_insulation_adds_layers_and_keeps_existing_occurrences(library, renovations):
    base = building(library)
    candidate = renovations.get("insulate_wall.stone_wool_200")
    child = apply_candidates(base, candidate)
    walls = [e for e in base.elements if e.role == Role.EXT_WALL and e.boundary == "Outdoors"]
    stage = child.stages[0]
    flows = stage.material_flows
    assert not flows.removed
    assert {q.element_id for q in flows.installed} == {e.identifier for e in walls}
    renovated = {e.identifier: e for e in child.elements}
    for wall in walls:
        assert renovated[wall.identifier].component_ids[1:] == wall.component_ids
    drivers = dict(stage.quantities[0].drivers)
    assert drivers["element_area_m2"] == pytest.approx(sum(e.area_m2 for e in walls))


def test_basement_floor_targets_only_the_ground_slab(library, renovations):
    base = building(library)
    child = apply_candidates(base, renovations.get("insulate_basement.floor_eps_45_screed_50"))
    floors = [e for e in base.elements if e.role == Role.GROUND_FLOOR]
    assert {e.boundary for e in floors} == {"Ground", "Internal"}
    assert child.stages[0].quantities[0].measure_type == "insulate_basement"
    assert dict(child.stages[0].quantities[0].drivers)["element_area_m2"] == pytest.approx(360)
    assert {q.element_id for q in child.stages[0].material_flows.installed} == {
        e.identifier for e in floors if e.boundary == "Ground"}


def test_window_replacement_removes_units_but_upgrade_retains_them(library, renovations):
    base = building(library)
    replaced = apply_candidates(base, renovations.get("replace_window.u_0_90")).stages[0]
    upgraded = apply_candidates(
        base, renovations.get("upgrade_window.insulating_glass_inner_sash"))
    windows = [e for e in base.elements if e.role == Role.WINDOW]
    area = sum(e.area_m2 for e in windows)
    assert len(replaced.material_flows.removed) == len(windows)
    flows = upgraded.stages[0].material_flows
    assert not flows.removed
    assert [q.kind for q in flows.installed] == ["installation"]
    glazing = upgraded.installations[0]
    assert glazing.quantity == pytest.approx(0.75 * area)
    assert glazing.mass_kg == pytest.approx(20 * 0.75 * area)
    assert {e.construction.u_value for e in upgraded.elements if e.role == Role.WINDOW} == {1.3}
    assert dict(upgraded.stages[0].quantities[0].drivers)["window_count"] == pytest.approx(area / 1.08)


def test_ventilation_quantities_follow_geometry_and_existing_system(library, renovations):
    candidate = renovations.get("upgrade_ventilation.ftx_080")
    layout = candidate.payload.layout
    base = building(library)
    drivers = ventilation_drivers(base, layout, "S")
    floor = 30 * 12 * 5  # four storeys over a conditioned basement
    assert drivers["floor_area_m2"] == pytest.approx(floor)
    assert drivers["airflow_l_s"] == pytest.approx(0.35 * floor)
    assert drivers["ahu_count"] == math.ceil(0.35 * floor / 300)
    risers = math.ceil(360 / 120)
    network = risers * (4 * 2.8 + 2.4) + 5 * 360 * 0.08  # risers reach the basement
    terminals = math.ceil(floor / 15) + math.ceil(floor / 25)
    assert drivers["duct_length_m"] == pytest.approx(2 * network + terminals * 4.0)
    exhaust_only = ventilation_drivers(base, layout, "F")
    assert exhaust_only["exhaust_terminal_count"] == 0
    assert exhaust_only["duct_length_m"] == pytest.approx(network + math.ceil(floor / 15) * 4.0)
    assert ventilation_drivers(base, layout, "FTX")["duct_length_m"] == 0

    child = apply_candidates(base, candidate)
    assert child.hvac.airflow.topology == "FTX"
    assert child.hvac.airflow.sensible_recovery_effectiveness == 0.8
    assert child.hvac.airflow.mechanical_vent_l_s_m2 == 0.35
    duct = next(i for i in child.installations if i.product_id.startswith("duct"))
    assert duct.quantity == pytest.approx(drivers["duct_length_m"])
    assert duct.mass_kg == pytest.approx(2.6 * duct.quantity)


def test_installations_and_quantities_survive_snapshots_and_lineage(library, renovations):
    base = building(library)
    child = apply_candidates(base, renovations.get("upgrade_ventilation.ftx_080"),
                             renovations.get("insulate_roof.attic_loose_stone_wool_300"))
    snapshot = child.snapshot()
    assert snapshot.to_dict()["schema"] == "epsm.building/9"
    assert base.snapshot().to_dict()["schema"] == "epsm.building/8"
    restored = Building.from_snapshot(BuildingSnapshot.from_dict(snapshot.to_dict()))
    assert restored.installations == child.installations
    restored.restore_lineage(child.lineage_to_dict())
    assert restored.stages[0].quantities == child.stages[0].quantities
    assert len(restored.stages[0].material_flows.installed) == len(
        child.stages[0].material_flows.installed)


def test_one_stage_cannot_renovate_an_element_twice(library, renovations):
    base = building(library)
    with pytest.raises(ValueError, match="already in this stage"):
        apply_candidates(base, renovations.get("replace_window.u_0_90"),
                         renovations.get("upgrade_window.insulating_glass_inner_sash"))
    from dataclasses import replace

    ftx = renovations.get("upgrade_ventilation.ftx_080")
    only_f = replace(ftx, payload=replace(ftx.payload, from_ventilation=("F",)))
    with pytest.raises(ValueError, match="cannot replace S"):
        resolve_candidate(base, only_f)


def test_hosts_bring_scaled_sealing_and_sealing_never_stands_alone(library, renovations, caplog):
    base = building(library)
    windows = renovations.get("replace_window.u_0_90")
    walls = renovations.get("insulate_wall.stone_wool_200")
    sealing = renovations.get("seal_envelope.renovated_joints")
    outdoor = {e.identifier: e.area_m2 for e in base.elements if e.boundary == "Outdoors"}
    before = base.hvac.airflow.envelope_infiltration_ach

    with caplog.at_level("WARNING", logger="epsm_core.measures"):
        child = apply_candidates(base, windows, walls)
    stage = child.stages[0]
    assert stage.measure_ids == (windows.candidate_id, walls.candidate_id, sealing.candidate_id)
    renovated = sum(a for i, a in outdoor.items()
                    if i in {e.identifier for e in base.elements
                             if e.role in {Role.WINDOW, Role.EXT_WALL}})
    share = renovated / sum(outdoor.values())
    effects = dict(stage.quantities[-1].effects)
    assert effects["envelope_share"] == pytest.approx(share)
    assert child.hvac.airflow.envelope_infiltration_ach == pytest.approx(
        before * (1 - sealing.payload.nominal_reduction * share))
    assert any(getattr(r, "epsm_event", "") == "renovation.sealing.default_applied"
               for r in caplog.records)
    assert len(stage.material_flows.installed) == len(
        apply_candidates(base, windows, walls, companions=False).stages[0].material_flows.installed)

    assert apply_candidates(base, windows, companions=False).hvac.airflow.envelope_infiltration_ach == before
    with pytest.raises(ValueError, match="cannot be applied by itself"):
        apply_candidates(base, sealing)
    with pytest.raises(ValueError, match="cannot be applied by itself"):
        resolve_candidate(base, sealing)
    with pytest.raises(ValueError, match="cannot be applied by itself"):
        apply_candidates(base, renovations.get("insulate_roof.attic_loose_stone_wool_300"), sealing)


def test_attic_basement_ceiling_and_interior_targets(library, renovations):
    from epsm_core.specs.geometry import RoofSpec

    unheated = Building(
        preset="illustrative-reference",
        construction_set=library.get("mf_se02", state="existing").construction_set,
        geometry=GeometrySpec.from_footprint(Footprint.rectangle(30, 12), storeys=4,
                                             storey_height_m=2.8, basement_depth_m=2.4,
                                             basement_conditioned=False))
    ceiling = apply_candidates(unheated, renovations.get("insulate_basement.ceiling_stone_wool_100"))
    assert {q.element_id for q in ceiling.stages[0].material_flows.installed} == {"main.ground_floor"}
    with pytest.raises(ValueError, match="unheated basement"):
        apply_candidates(building(library), renovations.get("insulate_basement.ceiling_stone_wool_100"))
    interior = apply_candidates(unheated, renovations.get("insulate_wall.interior_wood_fibre_70"))
    wall = next(e for e in interior.elements if e.role == Role.EXT_WALL and e.boundary == "Outdoors")
    assert wall.construction.components[-1].name.startswith("Interior wood-fibre")
    attic = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(30, 12), storeys=4, storey_height_m=2.8,
        roof=RoofSpec(shape="gable", pitch_deg=27, topology="cold_attic")))
    top = next(e for e in attic.elements if e.role == Role.TOP_FLOOR)
    measure = resolve_candidate(attic, renovations.get("insulate_roof.attic_cellulose_300"))
    assert top.boundary == "Internal" and measure.target_element_ids == (top.identifier,)


def test_pv_is_sized_from_the_roof_and_dhw_use_is_reduced(library, renovations):
    from epsm_core.measures import pv_drivers
    from epsm_core.specs.geometry import RoofSpec

    pv = renovations.get("install_pv.roof_south_15")
    flat = building(library)
    drivers = pv_drivers(flat, pv.payload)
    assert drivers["pv_area_m2"] == pytest.approx(0.8 * 360)
    assert drivers["pv_capacity_kwp"] == pytest.approx(0.8 * 360 * 0.13)
    child = apply_candidates(flat, pv)
    array = child.hvac.renewables.pv_systems[-1]
    assert (array.tilt_deg, array.azimuth_deg, array.system_losses_pct) == (15, 180, 12)
    assert array.dc_capacity_kw == pytest.approx(drivers["pv_capacity_kwp"])
    module = next(i for i in child.installations if i.product_id == "pv.module_mono_si")
    assert module.quantity == pytest.approx(drivers["pv_capacity_kwp"] * 4.785)
    gable = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(30, 12), storeys=4, storey_height_m=2.8,
        roof=RoofSpec(shape="gable", pitch_deg=27, topology="cold_attic")))
    roof = sum(e.area_m2 for e in gable.elements if e.role == Role.ROOF)
    assert pv_drivers(gable, pv.payload)["pv_area_m2"] == pytest.approx(0.3 * roof)

    dhw = renovations.get("reduce_dhw.low_flow_fittings")
    reduced = apply_candidates(flat, dhw)
    assert reduced.operation.dhw_kwh_m2_year == pytest.approx(
        flat.operation.dhw_kwh_m2_year * (1 - dhw.payload.fraction))
    fittings = reduced.installations[0]
    assert fittings.quantity == pytest.approx(flat.effective_load_reference_area_m2)
    refs = dict(fittings.factor_refs)
    assert refs["carbon_reference_id"] == "epsm-derived:dhw.low_flow_fitting_set"
    assert json.loads(refs["carbon_reference"])["modules"]["A1A3"] == 0.2


def test_every_payload_type_has_a_resolver_and_every_operation_an_applier(library, renovations):
    from epsm_data import PAYLOADS

    from epsm_core.measures import RESOLVERS
    from epsm_core.renovation_apply import APPLIERS, ResolvedMeasure

    assert set(RESOLVERS) == set(PAYLOADS.values())
    with pytest.raises(TypeError, match="Cannot renovate"):
        building(library).renovate(object())
    with pytest.raises(TypeError, match="No applier"):
        ResolvedMeasure("x", (object(),))
    assert len(APPLIERS) == 5
