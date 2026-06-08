"""Demo 3 — Plotting results.

Runs a building (as in Demo 2) and turns the retained time series into figures.
All data is pulled through the keyless accessors, so no string keys appear; the
explicit units on every series are used directly as axis labels.

Produces three PNGs in ``demos/output/``:

* ``monthly_heating.png``    — monthly heating load (bar chart)
* ``zone_temps_week.png``    — hourly zone air temperatures for a winter week
* ``monthly_gains.png``      — monthly internal/solar gains (stacked area)

Run it with::

    PYTHONPATH=src python demos/demo_03_plotting_results.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: write files, no interactive window
import matplotlib.pyplot as plt

from pbgenerator import Building, Location, WeatherSite, cmf_1960

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def run_building() -> Building:
    footprint = [[0, 0], [20, 0], [20, 12], [0, 12]]
    params = cmf_1960(num_floors=4, ventilation_system="FTX")
    weather = WeatherSite(
        epw_path="epw/SWE_BL_Hano.Island.026280_TMYx.2004-2018.epw",
        station_name="Hano Island",
    )
    location = Location.hypothetical_site(city="Demoville", weather=weather)
    building = Building(name="demo_house", params=params,
                       footprint_pts=footprint, location=location)

    work = Path(tempfile.mkdtemp(prefix="pbg_demo3_"))
    print("Running EnergyPlus ...")
    building.simulate(idf_dir=work / "idf", output_dir=work / "out")
    print("Done.")
    return building


def plot_monthly_heating(building: Building, out_dir: Path) -> Path:
    """Monthly heating load as a bar chart (energy summed per month)."""
    series = building.results.heating_load.monthly  # TimeSeries of 12 values
    # Convert J -> kWh for a readable axis.
    kwh = [v / 3.6e6 for v in series.values]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(_MONTHS, kwh, color="#c0392b")
    ax.set_ylabel("Heating load [kWh]")
    ax.set_title("Monthly heating load")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    path = out_dir / "monthly_heating.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_zone_temps_week(building: Building, out_dir: Path) -> Path:
    """Hourly zone air temperatures for one cold week (mid-January)."""
    start, end = 24 * 7, 24 * 14  # hours for the 2nd week of the year

    fig, ax = plt.subplots(figsize=(10, 4))
    for zone in building.results.zones:
        ts = zone.air_temperature.hourly
        ax.plot(range(start, end), ts.values[start:end],
                label=f"Floor {zone.floor}", linewidth=1.2)

    ax.set_xlabel("Hour of year")
    ax.set_ylabel(f"Air temperature [{ts.unit}]")
    ax.set_title("Zone air temperature — winter week")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    path = out_dir / "zone_temps_week.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_monthly_gains(building: Building, out_dir: Path) -> Path:
    """Monthly internal + solar gains as a stacked area chart (kWh)."""
    res = building.results

    def monthly_kwh(signal):
        if signal is None or signal.monthly is None:
            return [0.0] * 12
        return [v / 3.6e6 for v in signal.monthly.values]

    gains = {
        "Solar": monthly_kwh(res.solar_gains),
        "Equipment": monthly_kwh(res.equipment),
        "Lighting": monthly_kwh(res.lighting),
        "Occupants": monthly_kwh(res.occupancy_heat),
    }

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.stackplot(_MONTHS, *gains.values(), labels=list(gains), alpha=0.85)
    ax.set_ylabel("Heat gains [kWh]")
    ax.set_title("Monthly internal & solar gains")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    path = out_dir / "monthly_gains.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    building = run_building()

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    print("\nWriting figures:")
    for path in (
        plot_monthly_heating(building, out_dir),
        plot_zone_temps_week(building, out_dir),
        plot_monthly_gains(building, out_dir),
    ):
        print("  ", path)


if __name__ == "__main__":
    main()
