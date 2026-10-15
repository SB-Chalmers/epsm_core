"""Incomplete templates remain inspectable while every supplied section is checked."""

import pytest
from epsm_data import HVACTemplate, reference_hvac_template

from epsm_core import Building, HVACSystem, HVACTemplateResolution


def test_partial_template_reports_missing_airflow_without_inventing_system():
    template = HVACTemplate("project:partial", {"airflow": {"mechanical_vent_l_s_m2": 0.35}},
                            source_references=("project:survey",))
    resolved = HVACSystem.resolve_template(template)
    assert isinstance(resolved, HVACTemplateResolution)
    assert resolved.hvac is None
    assert set(resolved.requirements) == {"airflow.topology", "airflow.envelope_infiltration_ach"}
    assert resolved.source_references == template.source_references
    with pytest.raises(TypeError):
        resolved.values["airflow"]["mechanical_vent_l_s_m2"] = 9
    exported = resolved.to_dict()
    exported["values"]["airflow"]["mechanical_vent_l_s_m2"] = 9
    assert resolved.values["airflow"]["mechanical_vent_l_s_m2"] == 0.35
    assert len(repr(resolved)) <= 160


@pytest.mark.parametrize("values", [
    {"delivery": {"heating": {"efficiency": -1}}},
    {"equipment": [{"identifier": "unit", "count": -1}]},
    {"unknown_section": {}},
    {"delivery": {"fvp": {}, "heating": {}}},
    {"delivery": {"heating": {"carrier": "fuel", "heat_pump_cop": {"values": [3] * 24}}}},
    {"delivery": {"heating": {"carrier": "heat_pump", "heat_pump_cop": {"values": [0] * 24}}}},
    {"airflow": {"topology": "S", "mechanical_vent_l_s_m2": 0.35}},
    {"airflow": {"topology": "FTX"}, "delivery": {"fvp": {"cop": 3}}},
    {"equipment": [{"identifier": "unit", "factor_refs": [["malformed"]]}]},
    {"airflow": {"infiltration_coefficients": (1, 0, 0)}},
])
def test_invalid_supplied_section_is_not_masked_by_missing_airflow(values):
    with pytest.raises(ValueError):
        HVACSystem.resolve_template(HVACTemplate("invalid", values))


def test_previous_system_supplies_known_fields_without_changing_original():
    previous = Building(preset="illustrative-reference").hvac
    before = previous.to_dict()
    template = HVACTemplate("project:leakage", {"airflow": {"envelope_infiltration_ach": 0.4}})
    result = HVACSystem.resolve_template(template, previous=previous)
    assert result.hvac.airflow.envelope_infiltration_ach == 0.4
    assert result.hvac.delivery == previous.delivery and result.hvac.equipment == previous.equipment
    assert previous.to_dict() == before
    assert not result.requirements
    assert HVACSystem.from_template(template, previous=previous).to_dict() == result.hvac.to_dict()


def test_reference_template_and_existing_complete_factory_remain_equivalent():
    template = reference_hvac_template()
    result = HVACSystem.resolve_template(template)
    first, second = result.hvac.to_dict(), HVACSystem.from_template(template).to_dict()
    for values in (first, second):
        for record in values["equipment"]:
            record.pop("occurrence_id")
    assert first == second
    assert not result.requirements


def test_missing_equipment_product_and_heatpump_cop_are_explicit_requirements():
    equipment = HVACSystem.resolve_template(HVACTemplate("partial-equipment", {
        "equipment": [{"identifier": "unit", "count": 2}],
    }))
    assert "equipment.0.product_id" in equipment.requirements
    heating = HVACSystem.resolve_template(HVACTemplate("partial-heating", {
        "delivery": {"heating": {"carrier": "heat_pump", "source": "project:selection"}},
    }))
    assert "delivery.heating.heat_pump_cop" in heating.requirements
    assert heating.hvac is None


def test_resolution_and_inspection_do_not_read_resources(monkeypatch):
    template = reference_hvac_template()

    def denied(*args, **kwargs):
        pytest.fail("Template resolution must use loaded portable values")

    monkeypatch.setattr("builtins.open", denied)
    monkeypatch.setattr("pathlib.Path.open", denied)
    result = HVACSystem.resolve_template(template)
    assert result.hvac is not None
    assert result.to_dict()["template_id"] == template.template_id
