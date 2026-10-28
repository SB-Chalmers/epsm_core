"""TABULA's absolute thermal-bridge surcharge, carried by the walls and thermal top."""

import json

import pytest
from pydantic import ValidationError

from epsm_core import Building, BuildingSnapshot, EnergyPlusCompiler, Weather
from epsm_core.bridges import BRIDGED_ROLES, thermal_bridge_uplifts
from epsm_core.quantities import quantity_takeoff


def surcharged(delta_u=0.1):
    building = Building(preset="illustrative-reference")
    building.assign_inputs(thermal_bridge_delta_u_w_m2k=delta_u)
    return building


def test_unset_surcharge_leaves_existing_identities_unchanged(synthetic_weather):
    building = Building(preset="illustrative-reference")
    assert "thermal_bridge_delta_u_w_m2k" not in building.snapshot().to_dict()
    spec = building.to_spec(Weather.from_epw(synthetic_weather))
    assert "thermal_bridge_delta_u_w_m2k" not in spec.physical_dict()["envelope"]


def test_surcharge_replaces_the_uplift_fraction_and_survives_a_snapshot():
    building = surcharged(0.1)
    assert building.thermal_bridge_delta_u_w_m2k == 0.1
    assert building.thermal_bridge_uplift_fraction is None
    assert "thermal_bridge_uplift_fraction" not in building.readiness().missing
    restored = BuildingSnapshot.from_dict(json.loads(json.dumps(building.snapshot().to_dict()))).to_building()
    assert restored.thermal_bridge_delta_u_w_m2k == 0.1
    restored.assign_inputs(thermal_bridge_uplift_fraction=0.05)
    assert restored.thermal_bridge_delta_u_w_m2k is None
    with pytest.raises(ValueError, match="one thermal-bridge representation"):
        restored.assign_inputs(thermal_bridge_uplift_fraction=0.05, thermal_bridge_delta_u_w_m2k=0.1)


def test_spec_rejects_two_bridge_representations(synthetic_weather):
    spec = surcharged().to_spec(Weather.from_epw(synthetic_weather))
    with pytest.raises(ValidationError, match="one thermal-bridge representation"):
        type(spec.envelope).model_validate({**spec.envelope.model_dump(), "thermal_bridge_uplift_fraction": 0.1})


def test_wall_and_top_carry_the_whole_envelope_surcharge(synthetic_weather):
    spec = surcharged(0.1).to_spec(Weather.from_epw(synthetic_weather))
    uplifts = thermal_bridge_uplifts(spec)
    assert set(uplifts) == set(BRIDGED_ROLES)
    assert uplifts["wall"] == uplifts["top"] > 0
    assert all(uplifts[role] == 0 for role in ("ground", "basement_wall", "basement_ceiling"))
    # Independent areas from the nominal takeoff: envelope opaque faces and panes, once each.
    areas = {}
    for item in quantity_takeoff(spec):
        envelope_face = item.role in BRIDGED_ROLES and not item.element_id.endswith(".internal_wall")
        if item.area_m2 and (item.kind == "glazing" or (item.kind == "opaque_layer" and envelope_face)):
            areas[item.element_id, item.role] = item.area_m2
    envelope_area = sum(areas.values())
    carried = sum(area * getattr(spec.envelope, role).u_value_w_m2k * uplifts[role]
                  for (_, role), area in areas.items() if role in ("wall", "top"))
    assert carried == pytest.approx(0.1 * envelope_area)


def test_compiler_applies_the_surcharge_to_wall_and_top_only(energyplus, synthetic_weather):
    spec = surcharged(0.1).to_spec(Weather.from_epw(synthetic_weather))
    uplift = thermal_bridge_uplifts(spec)["wall"]
    _, report = EnergyPlusCompiler(energyplus).compile(spec)
    constructions = report.data["constructions"]
    for role in ("wall", "top"):
        item = constructions[role]
        assert item["applied_u_w_m2k"] == pytest.approx(item["nominal_u_w_m2k"] * (1 + uplift))
    ground = constructions["ground"]
    assert ground["applied_u_w_m2k"] == pytest.approx(ground["nominal_u_w_m2k"])
