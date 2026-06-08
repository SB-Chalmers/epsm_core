"""Demo 1 — Creating a building.

This walks through constructing the top-level :class:`~pbgenerator.building.Building`
aggregate: the single object that owns a building's identity, simulation
parameters, location/weather, geometry, optional PV, and (after a run) results.

No EnergyPlus run happens here — this demo is only about *building the building*.
See later demos for simulating and reading results.

Run it with::

    PYTHONPATH=src python demos/demo_01_creating_a_building.py
"""
from __future__ import annotations

from pbgenerator import Building, Location, WeatherSite, cmf_1960


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Footprint geometry
    # ------------------------------------------------------------------
    # A footprint is a list of [x, y] vertices in metres (EPSG:3006 / SWEREF99
    # TM for real Swedish buildings, but any metre-based CRS works).  Here we
    # use a simple 20 m x 12 m rectangle.
    footprint = [[0, 0], [20, 0], [20, 12], [0, 12]]

    # ------------------------------------------------------------------
    # 2. Simulation parameters
    # ------------------------------------------------------------------
    # `cmf_1960` is an archetype factory for a 1960s Swedish multi-family
    # building (concrete-frame "miljonprogram").  It returns a fully populated
    # BuildingParams; here: 4 storeys with balanced heat-recovery ventilation.
    params = cmf_1960(num_floors=4, ventilation_system="FTX")

    # ------------------------------------------------------------------
    # 3. Location + weather
    # ------------------------------------------------------------------
    # A WeatherSite points at an EPW file (plus optional station metadata).
    weather = WeatherSite(
        epw_path="epw/SWE_BL_Hano.Island.026280_TMYx.2004-2018.epw",
        station_name="Hano Island",
    )
    # `hypothetical_site` describes an arbitrary site for what-if studies (no
    # EPC record).  Real buildings would use
    # `Location.from_footprint_record(...)` instead.  Geometry lives on the
    # Building, not the Location.
    location = Location.hypothetical_site(city="Demoville", weather=weather)

    # ------------------------------------------------------------------
    # 4. The Building aggregate
    # ------------------------------------------------------------------
    building = Building(name="demo_house", params=params,
                        footprint_pts=footprint, location=location)

    # ------------------------------------------------------------------
    # 5. Inspect what we just created (no simulation needed)
    # ------------------------------------------------------------------
    print("Building:        ", building.name)
    print("City:            ", building.location.city)
    print("Hypothetical?    ", building.location.hypothetical)
    print("EPW:             ", building.location.epw_path)
    print("Ventilation:     ", building.params.ventilation_system)
    print("Storeys:         ", building.params.num_floors)
    print("Footprint area:  ", round(building.footprint_area_m2, 1), "m2")

    # Geometry is a generated artifact: build it on demand.  This populates the
    # Honeybee model and room geometry, and unlocks the heated-area property.
    building.build_model()
    print("Honeybee model:  ", type(building.honeybee_model).__name__)
    print("Rooms (zones):   ", len(building.rooms.all))
    print("Heated area:     ", round(building.heated_floor_area_m2, 1), "m2")

    print("\nBuilding created. Next: building.simulate(...) to run EnergyPlus.")


if __name__ == "__main__":
    main()
