import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from epsm_core.specs import *
from epsm_core.weather import climate_from_epw


@pytest.fixture
def energyplus():
    path = os.environ.get("ENERGYPLUS_EXE", "/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    if not Path(path).exists():
        pytest.skip("EnergyPlus 24.2 unavailable")
    return path


@pytest.fixture(scope="session")
def synthetic_weather(tmp_path_factory):
    """Complete non-leap EPW for software tests, separate from every run directory."""
    path = tmp_path_factory.mktemp("weather-inputs") / "synthetic-2023.epw"
    headers = [
        "LOCATION,Unit test,Test,SWE,SYNTHETIC,000000,57,12,1,20",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,Synthetic constant weather for software tests only",
        "COMMENTS 2,Not measured or representative weather",
        "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
    ]
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\n".join(headers) + "\n")
        for hour in range(8760):
            stamp = datetime(2023, 1, 1) + timedelta(hours=hour)
            row = ["0"] * 35
            row[:10] = [
                "2023", str(stamp.month), str(stamp.day), str(stamp.hour + 1), "60",
                "?", "10", "5", "70", "101325",
            ]
            row[12] = "300"  # Horizontal infrared radiation, Wh/m2.
            row[20:22] = ["180", "2"]  # Wind direction and speed.
            stream.write(",".join(row) + "\n")
    return path


@pytest.fixture
def building(synthetic_weather):
    epw = (
        Path(__file__).parents[2]
        / "data/weather/SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw"
    )
    if not epw.exists():
        epw = synthetic_weather
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
            parts=(
                BuildingPart(
                    identifier="main",
                    footprint=Footprint.rectangle(30, 20),
                    storey_elevations_m=(0, 2.8, 5.6, 8.4),
                ),
            )
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
            basement_ceiling=insulated,
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
