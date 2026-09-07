import numpy as np

from epsm_core import (
    AddInsulation,
    BuildingBuilder,
    DistrictPlan,
    FVPSpec,
    InstallPV,
    PVSpec,
    apply_renovation,
)
from epsm_core.delivery import fvp_delivery


def test_builder_provenance(building):
    assumptions = building.model_dump(mode="json")
    assumptions.pop("provenance")
    b = BuildingBuilder(assumption_profile="test", assumptions=assumptions).build(
        identifier="known"
    )
    records = {r.field_path: r for r in b.provenance.records}
    assert records["identifier"].status == "measured"
    assert records["geometry.parts"].assumption_profile == "test"


def test_renovation_does_not_mutate(building):
    original = building.physical_hash()
    renovated = apply_renovation(
        building,
        AddInsulation(element="wall", layer=building.envelope.wall.layers[0]),
        effective_date="2026-01-01",
    )
    assert renovated.envelope.wall.u_value_w_m2k < building.envelope.wall.u_value_w_m2k
    assert building.physical_hash() == original
    assert renovated.renovations[0].before_sha256 == original
    solar = apply_renovation(
        building, InstallPV(pv=PVSpec(dc_capacity_kw=10)), effective_date="2026-01-01"
    )
    assert solar.physical_hash() != original


def test_fvp_conservation(building):
    b = building.updated(
        airflow=building.airflow.updated(topology="F", sensible_recovery_effectiveness=0),
        delivery={"fvp": FVPSpec(cop=3, capacity_kw=20)},
    )
    heating = np.full(8760, 15.0)
    dhw = np.full(8760, 5.0)
    output = fvp_delivery(b, heating, dhw, np.full(8760, 21.0))
    np.testing.assert_allclose(
        output["fvp_heat_kwh"], output["fvp_extracted_heat_kwh"] + output["fvp_electricity_kwh"]
    )
    np.testing.assert_allclose(heating + dhw, output["fvp_heat_kwh"] + output["backup_input_kwh"])
    assert (output["fvp_heat_kwh"] <= 20).all()


def test_district_context(building):
    from epsm_core import Footprint

    second = building.updated(
        identifier="second",
        geometry=building.geometry.updated(
            parts=(
                building.geometry.parts[0].updated(
                    footprint=Footprint(exterior=((50, 0), (80, 0), (80, 20), (50, 20)))
                ),
            )
        ),
    )
    resolved = list(DistrictPlan(buildings=(building, second)).resolved_buildings())
    assert len(resolved[0].context.buildings) == 1
    assert resolved[0].context.buildings[0].identifier == "second:main"
    assert resolved[0].geometry == building.geometry


def test_hash_physics(building, energyplus):
    from epsm_core import EnergyPlusCompiler

    compiler = EnergyPlusCompiler(energyplus)
    original = compiler.run_id(building)
    changes = [
        building.updated(airflow=building.airflow.updated(envelope_infiltration_ach=0.3)),
        building.updated(climate=building.climate.updated(weather_sha256="f" * 64)),
        building.updated(
            geometry=building.geometry.updated(
                parts=(
                    building.geometry.parts[0].updated(
                        storey_elevations_m=(0, 2.8, 5.6, 8.4, 11.2)
                    ),
                )
            )
        ),
        building.updated(envelope=building.envelope.updated(thermal_bridge_uplift_fraction=0.2)),
    ]
    assert all(compiler.run_id(b) != original for b in changes)
