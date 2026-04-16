"""Sveby-based ProgramType definitions and blending for mixed-use buildings."""
from __future__ import annotations

from honeybee_energy.programtype import ProgramType
from honeybee_energy.load.people import People
from honeybee_energy.load.lighting import Lighting
from honeybee_energy.load.equipment import ElectricEquipment
from honeybee_energy.load.hotwater import ServiceHotWater

from .schedule import OCC_SCHED, LIGHT_SCHED, EQUIP_SCHED, ACTIVITY_SCHED


def _dhw_flow(kwh_m2: float) -> float:
    """Convert annual DHW target (kWh/m²/yr) to ServiceHotWater flow_per_area."""
    if kwh_m2 <= 0:
        return 0.0
    avg_watts = kwh_m2 * 1000.0 / 8760.0
    dhw = ServiceHotWater("_tmp", flow_per_area=0.001,
                          target_temperature=60,
                          sensible_fraction=0.0, latent_fraction=0.0)
    dhw.set_watts_per_area(avg_watts, water_mains_temperature=8)
    return dhw.flow_per_area


def sveby_apartment(
    occupant_density: float = 0.017,
    lighting_w_m2: float = 0.0,
    equipment_w_m2: float = 1.68,
    dhw_kwh_m2: float = 21.0,
) -> ProgramType:
    """Sveby Bostadshus 2.0 residential apartment program."""
    prog = ProgramType("SvebyApartment")
    prog.people = People(
        "SvebyApt_People", people_per_area=occupant_density,
        occupancy_schedule=OCC_SCHED(), activity_schedule=ACTIVITY_SCHED(),
        radiant_fraction=0.3,
    )
    prog.lighting = Lighting(
        "SvebyApt_Lights", watts_per_area=max(0.0, lighting_w_m2),
        schedule=LIGHT_SCHED(), return_air_fraction=0.0,
        radiant_fraction=0.4, visible_fraction=0.2,
    )
    prog.electric_equipment = ElectricEquipment(
        "SvebyApt_Equip", watts_per_area=max(0.0, equipment_w_m2),
        schedule=EQUIP_SCHED(), radiant_fraction=0.3,
    )
    flow = _dhw_flow(dhw_kwh_m2)
    if flow > 0:
        prog.service_hot_water = ServiceHotWater(
            "SvebyApt_DHW", flow_per_area=flow,
            target_temperature=60,
            sensible_fraction=0.0, latent_fraction=0.0,
        )
    return prog


def sveby_garage() -> ProgramType:
    """Heated garage: lighting only, no people / DHW / equipment."""
    prog = ProgramType("SvebyGarage")
    prog.lighting = Lighting(
        "SvebyGar_Lights", watts_per_area=1.0,
        schedule=LIGHT_SCHED(), return_air_fraction=0.0,
        radiant_fraction=0.4, visible_fraction=0.2,
    )
    return prog


def sveby_common() -> ProgramType:
    """Common areas (corridors, communal rooms): lighting only."""
    prog = ProgramType("SvebyCommon")
    prog.lighting = Lighting(
        "SvebyCom_Lights", watts_per_area=3.0,
        schedule=LIGHT_SCHED(), return_air_fraction=0.0,
        radiant_fraction=0.4, visible_fraction=0.2,
    )
    return prog


def sveby_basement() -> ProgramType:
    """Basement (storage, laundry, mechanical): minimal internal gains."""
    prog = ProgramType("SvebyBasement")
    prog.lighting = Lighting(
        "SvebyBsmt_Lights", watts_per_area=1.0,
        schedule=LIGHT_SCHED(), return_air_fraction=0.0,
        radiant_fraction=0.4, visible_fraction=0.2,
    )
    prog.electric_equipment = ElectricEquipment(
        "SvebyBsmt_Equip", watts_per_area=0.5,
        schedule=EQUIP_SCHED(), radiant_fraction=0.3,
    )
    return prog


def blend_building_program(
    identifier: str,
    *,
    residential_pct: int = 100,
    garage_pct: float = 0.0,
    occupant_density: float = 0.017,
    lighting_w_m2: float = 0.0,
    equipment_w_m2: float = 1.68,
    dhw_kwh_m2: float = 21.0,
) -> ProgramType:
    """Create a weighted-average ProgramType for a mixed-use building.

    Parameters
    ----------
    identifier : Honeybee identifier for the blended program.
    residential_pct : EgenAtempBostad from EPC (0–100).
    garage_pct : Heated-garage share of Atemp (0–100), from EgenAvarmgarage / EgenAtemp.
    occupant_density, lighting_w_m2, equipment_w_m2, dhw_kwh_m2 :
        Sveby load parameters for the residential portion.

    Returns
    -------
    A single ProgramType that is the area-weighted average of the apartment,
    garage, and common-area sub-programs.
    """
    res = max(0.0, min(100.0, float(residential_pct)))
    gar = max(0.0, min(100.0 - res, float(garage_pct)))
    com = 100.0 - res - gar

    # If fully residential, skip blending overhead
    if res >= 100.0:
        return sveby_apartment(occupant_density, lighting_w_m2,
                               equipment_w_m2, dhw_kwh_m2)

    programs = []
    weights = []

    if res > 0:
        programs.append(sveby_apartment(occupant_density, lighting_w_m2,
                                        equipment_w_m2, dhw_kwh_m2))
        weights.append(res / 100.0)
    if gar > 0:
        programs.append(sveby_garage())
        weights.append(gar / 100.0)
    if com > 0:
        programs.append(sveby_common())
        weights.append(com / 100.0)

    if len(programs) == 1:
        return programs[0]

    return ProgramType.average(identifier, programs, weights)
