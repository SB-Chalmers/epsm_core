"""Reference-flow conservation and native ideal heating boundary verification.

References: TABULA CommonCalculationMethod eq.(7), pp.12–13; EnergyPlus 24.2
I/O Reference ZoneInfiltration:DesignFlowRate / ZoneHVAC:IdealLoadsAirSystem.
"""
import numpy as np
import pytest

from epsm_core import EnergyPlusCompiler, EnergyPlusRunner, ProgramBlend, ScheduleSpec
from epsm_core.compiler import AIRFLOW_DIAGNOSTIC_VARIABLES


def area_flow(building, topology="F", recovery=0):
    """TABULA 0.4 ACH on reference area * 2.5 m, not geometry volume."""
    return building.airflow.updated(
        topology=topology, envelope_infiltration_ach=0,
        envelope_infiltration_l_s_m2=.4 * 2.5 / 3.6,
        sensible_recovery_effectiveness=recovery,
        mechanical_vent_l_s_m2=0 if topology == "S" else building.airflow.mechanical_vent_l_s_m2,
    )


def test_reference_area_flow_and_component_budget(building, energyplus):
    spec = building.updated(load_reference_area_m2=1000, airflow=area_flow(building))
    model, report = EnergyPlusCompiler(energyplus).compile(spec)
    objects = model["ZoneInfiltration:DesignFlowRate"]
    assert all(x["design_flow_rate_calculation_method"] == "Flow/Zone" for x in objects.values())
    assert all("air_changes_per_hour" not in x for x in objects.values())
    assert sum(x["design_flow_rate"] for x in objects.values()) == pytest.approx(.4 * 2.5 * 1000 / 3600)
    assert sum(x["outdoor_air_flow_per_zone"] for x in model["DesignSpecification:OutdoorAir"].values()) == pytest.approx(.35)
    zones = [z for z in report.data["zones"].values() if z["conditioned"]]
    assert sum(z["mean_outdoor_air_m3_s"] for z in zones) == pytest.approx(.35 + 1000 / 3600)
    assert all(z["airflow_accounting"]["ventilation_model"] == "ideal_loads_exhaust_thermal_equivalent" for z in zones)
    requested = {x["variable_name"] for x in model["Output:Variable"].values()}
    assert set(AIRFLOW_DIAGNOSTIC_VARIABLES) <= requested


def test_duplicate_infiltration_bases_are_rejected(building):
    with pytest.raises(ValueError, match="requires envelope_infiltration_ach=0"):
        building.airflow.updated(envelope_infiltration_l_s_m2=.2)
    with pytest.raises(ValueError):
        area_flow(building).updated(envelope_infiltration_l_s_m2=-.1)


def test_area_flow_does_not_change_with_geometry_volume(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    spec = building.updated(load_reference_area_m2=1000, airflow=area_flow(building))
    part = spec.geometry.parts[0]
    taller = spec.updated(geometry=spec.geometry.updated(parts=(part.updated(
        storey_elevations_m=(0, 4, 8, 12)),)))
    totals = []
    for s in (spec, taller):
        model, _ = compiler.compile(s)
        totals.append(sum(x["design_flow_rate"] for x in model["ZoneInfiltration:DesignFlowRate"].values()))
    assert totals[0] == pytest.approx(totals[1])
    assert compiler.run_id(spec) != compiler.run_id(taller)


def test_natural_flow_diagnostics_are_requested_only_when_present(building, energyplus):
    compiler = EnergyPlusCompiler(energyplus)
    natural = building.updated(airflow=area_flow(building, "S").updated(
        mechanical_vent_l_s_m2=0, natural_exchange_ach=.3))
    for spec, expected in ((building, False), (natural, True)):
        model, _ = compiler.compile(spec)
        requests = {x["variable_name"] for x in model["Output:Variable"].values()}
        assert ("Zone Ventilation Standard Density Volume Flow Rate" in requests) == expected


def test_blending_preserves_area_flow_and_rejects_mixed_bases():
    from test_program_blending import mixture

    blend = mixture()
    components = tuple(c.updated(airflow=c.airflow.updated(
        envelope_infiltration_ach=0, envelope_infiltration_l_s_m2=rate,
        infiltration_fraction=ScheduleSpec.constant(fraction)))
        for c, rate, fraction in zip(blend.components, [.1, .4], [1, .5]))
    _, airflow = ProgramBlend(source=blend.source, components=components).resolve(calendar_year=2024)
    assert airflow.envelope_infiltration_l_s_m2 == pytest.approx(.16)
    assert airflow.envelope_infiltration_l_s_m2 * airflow.infiltration_fraction.hourly(2024)[0] == pytest.approx(.12)
    with pytest.raises(ValueError, match="reference bases"):
        ProgramBlend(source=blend.source, components=(components[0], blend.components[1])).resolve(calendar_year=2024)


@pytest.mark.energyplus
def test_native_reference_flow_equivalence_and_heating_components(building, energyplus, tmp_path):
    """Two equivalent flow bases must deliver equal heat; recovery reduces demand."""
    spec = building.updated(load_reference_area_m2=1000, airflow=area_flow(building))
    ach = (.4 * 2.5 * 1000 / spec.geometry.conditioned_volume_m3)
    equivalent = spec.updated(airflow=spec.airflow.updated(
        envelope_infiltration_l_s_m2=None, envelope_infiltration_ach=ach))
    runner = EnergyPlusRunner(energyplus)
    outputs = [runner.run(s, tmp_path / name) for s, name in (
        (spec, "reference-area"), (equivalent, "equivalent-ach"),
        (spec.updated(airflow=area_flow(building, "FTX", .7)), "balanced-recovery"))]
    assert outputs[0].scalars["space_heating_demand_kwh"] == pytest.approx(
        outputs[1].scalars["space_heating_demand_kwh"], rel=1e-7)
    assert outputs[2].scalars["space_heating_demand_kwh"] < outputs[0].scalars["space_heating_demand_kwh"]
    for output in outputs:
        def signal(name):
            return np.sum([v for k, v in output.hourly.items() if k.split("::", 1)[0].upper() == name.upper()], axis=0)
        coil = signal("Zone Ideal Loads Supply Air Sensible Heating Energy")
        zone = signal("Zone Ideal Loads Zone Sensible Heating Energy")
        cooling = signal("Zone Ideal Loads Zone Sensible Cooling Energy")
        outside = signal("Zone Ideal Loads Outdoor Air Sensible Heating Energy")
        recovery = signal("Zone Ideal Loads Heat Recovery Sensible Heating Energy")
        mask = (coil > 1) & (cooling < 1e-6)
        assert mask.sum() > 100
        # PurchasedAirManager.cc v24.2, lines2535–2542 /2590–2596 /2826–2829:
        # coil uses mixed-air enthalpy; OA uses zone humidity cp; recovery uses
        # inlet humidity cp. Sensible-only component sums are approximate, not
        # an exact thermodynamic identity when those humidity ratios differ.
        # A 0.5% bound still detects duplicate/missing ventilation heating.
        np.testing.assert_allclose((coil + recovery)[mask], (zone + outside)[mask], rtol=.005, atol=.05)
        assert sum(coil) / 3.6e6 == pytest.approx(output.scalars["space_heating_demand_kwh"], rel=1e-7)
