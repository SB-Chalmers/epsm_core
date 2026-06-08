"""Demo 2 — Create and run a building.

Builds the :class:`~pbgenerator.building.Building` aggregate (as in Demo 1),
runs a full EnergyPlus simulation, and reads the retained results back off the
same object — annual metrics with units, EUIs, and hourly/monthly time series
accessed without ever typing a string key.

This runs EnergyPlus, so it takes a few seconds and needs the EnergyPlus binary
on PATH (provided by honeybee-energy).

Run it with::

    PYTHONPATH=src python demos/demo_02_create_and_run.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from pbgenerator import Building, Location, WeatherSite, cmf_1960


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Create the building (see Demo 1 for the step-by-step breakdown)
    # ------------------------------------------------------------------
    footprint = [[0, 0], [20, 0], [20, 12], [0, 12]]
    params = cmf_1960(num_floors=4, ventilation_system="FTX")
    weather = WeatherSite(
        epw_path="epw/SWE_BL_Hano.Island.026280_TMYx.2004-2018.epw",
        station_name="Hano Island",
    )
    location = Location.hypothetical_site(footprint, city="Demoville", weather=weather)
    building = Building(name="demo_house", params=params, location=location)

    # ------------------------------------------------------------------
    # 2. Run EnergyPlus
    # ------------------------------------------------------------------
    # `simulate` builds the geometry, writes the IDF, runs EnergyPlus, parses
    # the SQL output, and stores everything on `building.results`.  The work
    # dirs are scratch here; point them anywhere you like to keep the IDF/SQL.
    work = Path(tempfile.mkdtemp(prefix="pbg_demo2_"))
    print("Running EnergyPlus ...")
    results = building.simulate(idf_dir=work / "idf", output_dir=work / "out")
    print("Done.\n")

    # ------------------------------------------------------------------
    # 3. Headline annual metrics (each carries its unit)
    # ------------------------------------------------------------------
    print("== Annual metrics ==")
    print("  Heating:   ", results.heating)
    print("  Cooling:   ", results.cooling)
    print("  Site:      ", results.site_energy)
    print("  Site EUI:  ", results.site_eui)
    print("  Atemp:     ", results.atemp_m2, "m2")

    # ------------------------------------------------------------------
    # 4. Keyless, friendly time-series access
    # ------------------------------------------------------------------
    print("\n== Building signals (no string keys) ==")
    print("  Available:        ", results.available())
    print("  Mean air temp:    ", round(results.air_temperature.annual.value, 2),
          results.air_temperature.annual.unit)
    print("  Heating load/yr:  ", results.heating_load.annual)
    if results.lighting is not None:
        print("  Lighting hourly:  ", len(results.lighting.hourly), "values")
    else:
        print("  Lighting hourly:   (not requested)")

    # Monthly aggregation is derived on demand (energy summed, temps averaged).
    monthly_temp = results.air_temperature.monthly
    print("  Monthly mean temp:",
          [round(v, 1) for v in monthly_temp.values])

    # ------------------------------------------------------------------
    # 5. Navigate floors and zones
    # ------------------------------------------------------------------
    print("\n== Per-floor heating load ==")
    for floor in results.floors:
        load = floor.heating_load.annual if floor.heating_load else None
        print(f"  Floor {floor.number}: {load}")

    print("\n== Zone air temperatures ==")
    for zone in results.zones:
        ts = zone.air_temperature.hourly
        print(f"  {zone.name}: mean {ts.mean:.2f} {ts.unit}, "
              f"min {ts.minimum:.1f}, max {ts.maximum:.1f}")

    # ------------------------------------------------------------------
    # 6. Raw artifacts are kept for traceability
    # ------------------------------------------------------------------
    print("\n== Artifacts ==")
    for kind, path in results.artifacts.items():
        print(f"  {kind}: {path}")


if __name__ == "__main__":
    main()
