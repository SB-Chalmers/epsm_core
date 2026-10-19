"""Physical snapshots retain declared basement controls and attic exchange."""

import pytest

from epsm_core import Building, ScheduleSpec, UnconditionedExchangeSpec, ZoneUseSpec


def test_auxiliary_operation_inputs_are_detached_and_survive_snapshot():
    reference = Building(preset="illustrative-reference")
    uses = [ZoneUseSpec(zone_kind="basement", use=reference.operation.updated(
        heating_setpoint=ScheduleSpec.constant(18)), source="declared basement control")]
    exchanges = [UnconditionedExchangeSpec(zone_kind="attic", outdoor_air_ach=.5,
        source="declared ventilation assumption")]
    building = Building(preset="illustrative-reference", zone_uses=uses,
        unconditioned_exchange=exchanges)
    snapshot = building.snapshot()
    uses.clear()
    exchanges.clear()
    assert len(building.zone_uses) == len(building.unconditioned_exchange) == 1
    restored = snapshot.to_building()
    assert restored.zone_uses == building.zone_uses
    assert restored.unconditioned_exchange == building.unconditioned_exchange
    restored.unconditioned_exchange = ()
    assert restored.snapshot().sha256 != snapshot.sha256
    assert snapshot.to_building().unconditioned_exchange == building.unconditioned_exchange
    assert building.to_dict()["schema"] == "epsm.building/8"


def test_old_snapshot_identity_is_retained_until_auxiliary_operation_changes():
    original = Building(preset="illustrative-reference").to_dict()
    original["schema"] = "epsm.building/7"
    original.pop("zone_uses", None)
    original.pop("unconditioned_exchange", None)
    restored = Building.from_dict(original)
    assert restored.to_dict() == original
    restored.unconditioned_exchange = (UnconditionedExchangeSpec(
        zone_kind="attic", outdoor_air_ach=0, source="explicit sealed attic"),)
    assert restored.to_dict()["schema"] == "epsm.building/8"


def test_auxiliary_input_validation_rejects_duplicate_selectors():
    exchange = UnconditionedExchangeSpec(zone_kind="attic", outdoor_air_ach=.5,
        source="declared assumption")
    with pytest.raises(ValueError, match="Duplicate"):
        Building(unconditioned_exchange=(exchange, exchange))


def test_auxiliary_controls_reach_core_spec_and_resolved_domains(synthetic_weather):
    from epsm_core import Footprint, GeometrySpec, RoofSpec, Weather

    building = Building(preset="illustrative-reference", geometry=GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=3, storey_height_m=3,
        basement_depth_m=2.5, basement_conditioned=True, roof=RoofSpec(shape="gable")))
    building.zone_uses = (ZoneUseSpec(zone_kind="basement", use=building.operation.updated(
        heating_setpoint=ScheduleSpec.constant(18), occupant_density_per_m2=0),
        source="declared basement programme"),)
    building.unconditioned_exchange = (UnconditionedExchangeSpec(zone_kind="attic", outdoor_air_ach=.5,
        source="declared attic programme"),)
    weather = Weather.from_epw(synthetic_weather)
    spec = building.to_spec(weather)
    assert spec.zone_uses == building.zone_uses
    assert spec.unconditioned_exchange == building.unconditioned_exchange
    resolved = building.snapshot().resolve(weather)
    basement = [zone for zone in resolved.zones.values()
                if zone["physical_zone_kind"] == "basement"]
    assert basement
    assert all(set(zone["operation"]["heating_setpoint"]["values"]) == {18.} for zone in basement)
    assert all(zone["operation"]["occupant_density_per_m2"] == 0 for zone in basement)
    assert sum(zone["load_reference_area_m2"] for zone in resolved.zones.values() if zone["conditioned"]) == 320


def test_historical_snapshot_restores_stored_inventory_before_geometry_regeneration(monkeypatch):
    from epsm_core import BuildingSnapshot, physical_geometry

    data = Building(preset="illustrative-reference").to_dict()
    data["schema"] = "epsm.building/7"
    original = BuildingSnapshot.from_dict(data)

    def forbidden(*args, **kwargs):
        pytest.fail("Restoring a stored physical inventory must not regenerate thermal geometry")

    monkeypatch.setattr(physical_geometry, "physical_elements", forbidden)
    restored = Building.from_dict(data)
    assert restored.snapshot().sha256 == original.sha256
    assert [element.to_dict() for element in restored.elements] == data["elements"]
    with pytest.raises(pytest.fail.Exception):
        restored.geometry = restored.geometry.updated(orientation_deg=15)


def test_footprint_authoring_routes_operation_overrides_to_building():
    from epsm_core import Footprint

    reference = Building(preset="illustrative-reference")
    use = ZoneUseSpec(zone_kind="basement", use=reference.operation.updated(
        heating_setpoint=ScheduleSpec.constant(18)), source="declared basement control")
    exchange = UnconditionedExchangeSpec(zone_kind="attic", outdoor_air_ach=.5,
        source="declared attic exchange")
    building = Building.from_footprint(Footprint.rectangle(10, 8), storeys=2,
        storey_height_m=3, zone_uses=(use,), unconditioned_exchange=(exchange,))
    assert building.zone_uses[0].model_dump() == use.model_dump()
    assert building.unconditioned_exchange == (exchange,)
