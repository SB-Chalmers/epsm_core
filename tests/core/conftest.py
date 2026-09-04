from pathlib import Path
import os

import pytest

from epsm_core.specs import *
from epsm_core.weather import climate_from_epw


@pytest.fixture
def energyplus():
    path = os.environ.get("ENERGYPLUS_EXE", "/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    if not Path(path).exists():
        pytest.skip("EnergyPlus 24.2 unavailable")
    return path


@pytest.fixture
def building(tmp_path):
    epw = (
        Path(__file__).parents[2] / "epw/SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw"
    )
    if not epw.exists():
        epw=tmp_path/"unit-test-weather.epw"
        epw.write_text("LOCATION,Unit test,Test,SWE,TEST,000000,57,12,1,20\n")
    concrete = MaterialSpec(
        name="concrete", conductivity_w_mk=1.7, density_kg_m3=2300, specific_heat_j_kgk=880
    )
    wool = MaterialSpec(
        name="mineral wool", conductivity_w_mk=0.04, density_kg_m3=40, specific_heat_j_kgk=840
    )
    slab = ConstructionSpec(layers=(LayerSpec(material=concrete, thickness_m=0.2),))
    insulated = ConstructionSpec(layers=(LayerSpec(material=wool, thickness_m=0.15), *slab.layers))
    return BuildingSpec(
        identifier="test",
        geometry=GeometrySpec(
            footprints=(Footprint.rectangle(30, 20),), floors=3, floor_height_m=2.8
        ),
        facade=FacadeSpec(
            default_wwr=0.2, glazing=GlazingSpec(u_value_w_m2k=1.8, solar_heat_gain_coefficient=0.6)
        ),
        climate=climate_from_epw(epw),
        envelope=EnvelopeSpec(
            wall=insulated,
            top=insulated,
            ground=insulated,
            intermediate_floor=slab,
            weather_shell=slab,
            basement_wall=insulated,
            roof_topology="compact",
        ),
        airflow=AirflowSpec(
            topology="FTX",
            envelope_infiltration_ach=0.2,
            mechanical_vent_l_s_m2=0.35,
            sensible_recovery_effectiveness=0.7,
        ),
        use=UseSpec(
            heating_setpoint=ScheduleSpec.constant(21),
            occupant_density_per_m2=0.017,
            equipment_gain_w_m2=1.68,
            dhw_kwh_m2_year=21,
        ),
    )
