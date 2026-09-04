"""Explicit demonstration assumptions; takes an EPW and writes a BuildingSpec JSON."""

import argparse
from pathlib import Path

from epsm_core import (
    AirflowSpec,
    BuildingBuilder,
    ConstructionSpec,
    EnvelopeSpec,
    FacadeSpec,
    Footprint,
    GeometrySpec,
    GlazingSpec,
    LayerSpec,
    MaterialSpec,
    ScheduleSpec,
    UseSpec,
    climate_from_epw,
)


def example_spec(epw):
    concrete = MaterialSpec(
        name="demonstration concrete",
        conductivity_w_mk=1.7,
        density_kg_m3=2300,
        specific_heat_j_kgk=880,
    )
    insulation = MaterialSpec(
        name="demonstration insulation",
        conductivity_w_mk=0.04,
        density_kg_m3=40,
        specific_heat_j_kgk=840,
    )
    slab = ConstructionSpec(layers=(LayerSpec(material=concrete, thickness_m=0.2),))
    insulated = slab.updated(
        layers=(LayerSpec(material=insulation, thickness_m=0.15), *slab.layers)
    )
    envelope = EnvelopeSpec(
        wall=insulated,
        top=insulated,
        ground=insulated,
        intermediate_floor=slab,
        weather_shell=slab,
        basement_wall=insulated,
        roof_topology="compact",
    )
    assumptions = dict(
        geometry=GeometrySpec(
            footprints=(Footprint.rectangle(30, 20),), floors=3, floor_height_m=2.8
        ).model_dump(),
        envelope=envelope.model_dump(),
        facade=FacadeSpec(
            default_wwr=0.2, glazing=GlazingSpec(u_value_w_m2k=1.8, solar_heat_gain_coefficient=0.6)
        ).model_dump(),
        airflow=AirflowSpec(
            topology="FTX",
            envelope_infiltration_ach=0.2,
            mechanical_vent_l_s_m2=0.35,
            sensible_recovery_effectiveness=0.7,
        ).model_dump(),
        use=UseSpec(
            heating_setpoint=ScheduleSpec.constant(21),
            occupant_density_per_m2=0.017,
            equipment_gain_w_m2=1.68,
            dhw_kwh_m2_year=21,
        ).model_dump(),
    )
    return BuildingBuilder(assumption_profile="demonstration_only", assumptions=assumptions).build(
        identifier="example", climate=climate_from_epw(epw).model_dump()
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("epw")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(example_spec(args.epw).model_dump_json(indent=2))
