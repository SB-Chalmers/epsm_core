"""Demo 4 — Plot *all* results.

A fuller tour of what the retained time series can show, all pulled through the
keyless accessors (``building.results.<signal>`` / ``...zones[i].<signal>``).

Figures written to ``demos/output/``:

* ``energy_signature.png``      — building heating demand vs. outdoor temperature
* ``zone_temps_year.png``       — hourly indoor temps (all zones) + outdoor temp
* ``monthly_energy_balance.png``— monthly heating vs. internal & solar gains
* ``all_signals_monthly.png``   — a small-multiple grid: every available signal

Run it with::

    PYTHONPATH=src python demos/demo_04_plot_all_results.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pbgenerator import Building, Location, WeatherSite, cmf_1960

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_J_TO_KWH = 1.0 / 3.6e6


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

    work = Path(tempfile.mkdtemp(prefix="pbg_demo4_"))
    print("Running EnergyPlus ...")
    building.simulate(idf_dir=work / "idf", output_dir=work / "out")
    print("Done.")
    return building


def _kwh_hourly(signal) -> list[float]:
    """Hourly series converted to kWh (energy variables are reported in J)."""
    return [v * _J_TO_KWH for v in signal.hourly.values]


def _kwh_monthly(signal) -> list[float]:
    if signal is None or signal.monthly is None:
        return [0.0] * 12
    return [v * _J_TO_KWH for v in signal.monthly.values]


def plot_energy_signature(building: Building, out_dir: Path) -> Path:
    """Classic energy signature: hourly heating demand vs. outdoor temperature."""
    res = building.results
    t_out = res.outdoor_air_temperature.hourly.values
    q_heat = _kwh_hourly(res.heating_load)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(t_out, q_heat, s=4, alpha=0.15, color="#c0392b", edgecolors="none")
    ax.set_xlabel("Outdoor air temperature [\u00b0C]")
    ax.set_ylabel("Heating demand [kWh/h]")
    ax.set_title("Energy signature \u2014 heating vs. outdoor temperature")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    path = out_dir / "energy_signature.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_zone_temps_year(building: Building, out_dir: Path) -> Path:
    """Hourly indoor temperatures for every zone, with outdoor temp for context."""
    res = building.results

    fig, ax = plt.subplots(figsize=(11, 4.5))
    for zone in res.zones:
        ts = zone.air_temperature.hourly
        ax.plot(ts.values, linewidth=0.5, alpha=0.8, label=f"Floor {zone.floor}")
    ax.plot(res.outdoor_air_temperature.hourly.values,
            linewidth=0.5, alpha=0.6, color="0.4", label="Outdoor")

    ax.set_xlabel("Hour of year")
    ax.set_ylabel("Temperature [\u00b0C]")
    ax.set_title("Indoor zone temperatures vs. outdoor (full year)")
    ax.legend(loc="lower center", ncol=5, fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    path = out_dir / "zone_temps_year.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_monthly_energy_balance(building: Building, out_dir: Path) -> Path:
    """Monthly heating demand (bars) against internal + solar gains (stacked)."""
    res = building.results
    gains = {
        "Solar": _kwh_monthly(res.solar_gains),
        "Equipment": _kwh_monthly(res.equipment),
        "Lighting": _kwh_monthly(res.lighting),
        "Occupants": _kwh_monthly(res.occupancy_heat),
    }
    heating = _kwh_monthly(res.heating_load)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.stackplot(_MONTHS, *gains.values(), labels=list(gains), alpha=0.8)
    ax.plot(_MONTHS, heating, "o-", color="#c0392b", linewidth=2, label="Heating demand")
    ax.set_ylabel("Energy [kWh]")
    ax.set_title("Monthly energy balance")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    path = out_dir / "monthly_energy_balance.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_all_signals_monthly(building: Building, out_dir: Path) -> Path:
    """Small-multiple grid: monthly profile of every available signal."""
    res = building.results
    names = res.available()

    cols = 3
    rows = (len(names) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 2.6 * rows))
    axes = axes.flatten()

    for ax, name in zip(axes, names):
        sig = getattr(res, name)
        monthly = sig.monthly
        if monthly is None:
            ax.set_visible(False)
            continue
        is_temp = sig.unit == "degC"
        values = monthly.values if is_temp else [v * _J_TO_KWH for v in monthly.values]
        ax.bar(_MONTHS, values, color="#2980b9" if is_temp else "#27ae60")
        ax.set_title(name, fontsize=9)
        ax.set_ylabel("\u00b0C" if is_temp else "kWh", fontsize=8)
        ax.tick_params(axis="x", labelsize=6, rotation=90)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(axis="y", alpha=0.3)

    for ax in axes[len(names):]:
        ax.set_visible(False)

    fig.suptitle("All available signals \u2014 monthly", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    path = out_dir / "all_signals_monthly.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    building = run_building()
    print("Available signals:", building.results.available())

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    print("\nWriting figures:")
    for path in (
        plot_energy_signature(building, out_dir),
        plot_zone_temps_year(building, out_dir),
        plot_monthly_energy_balance(building, out_dir),
        plot_all_signals_monthly(building, out_dir),
    ):
        print("  ", path)


if __name__ == "__main__":
    main()
