"""Demo 7 — Natural ventilation: effect of window opening on zone temperatures.

Runs the same 1960s building with four scenarios:
  * Baseline  — no natural ventilation
  * 24 °C     — windows open when indoor > 24 °C  (standard)
  * 22 °C     — windows open when indoor > 22 °C  (aggressive)
  * 20 °C     — windows open when indoor > 20 °C  (very aggressive)

Uses the AMY 2023 Gothenburg file (warmer than TMY — makes the effect visible).

Writes four PNGs to ``demos/output/``:

* ``natvent_monthly_zone_temp.png``   — monthly mean zone temp + outdoor, all scenarios
* ``natvent_summer_hourly.png``       — hourly zone + outdoor temp, hottest 2-week window
* ``natvent_monthly_heating.png``     — monthly heating load — winter penalty of open windows
* ``natvent_overheating_hours.png``   — hours above 25 / 27 °C per month, all scenarios

Run it with::

    PYTHONPATH=src python demos/demo_07_natural_ventilation.py
"""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pbgenerator import Building, Location, WeatherSite, cmf_1960

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EPW = Path("/Users/ssanjay/GitHub/smhi2epw/gothenburg_2023.epw")

# ------------------------------------------------------------------
# Scenarios: (display label, nat_vent_t_open_c, min_outdoor_t, line colour)
#
# min_outdoor_t must be warm enough that windows don’t open during the
# heating season (indoor always ≥ t_heating = 21 °C by the setpoint).
# Rule of thumb: min_outdoor ≈ trigger − 4 °C keeps opening confined
# to days when the outdoor air is genuinely helpful for cooling.
# ------------------------------------------------------------------
_SCENARIOS: list[tuple[str, float | None, float, str]] = [
    ("Baseline (closed)",  None,  18.0,  "#555555"),
    ("Open > 24 °C",       24.0,  20.0,  "#2980b9"),
    ("Open > 22 °C",       22.0,  18.0,  "#e67e22"),
    ("Open > 20 °C",       20.0,  16.0,  "#27ae60"),
]


# ------------------------------------------------------------------
# Run building
# ------------------------------------------------------------------
def run_scenario(label: str, nat_vent_t: float | None, min_outdoor_t: float) -> Building:
    params = cmf_1960(num_floors=4, ventilation_system="FTX")
    if nat_vent_t is not None:
        params = dataclasses.replace(
            params,
            nat_vent_t_open_c=nat_vent_t,
            nat_vent_min_outdoor_t_c=min_outdoor_t,
        )

    weather = WeatherSite(epw_path=str(_EPW), station_name=label)
    location = Location.hypothetical_site(city="Gothenburg", weather=weather)
    safe = (label.replace(" ", "_").replace(">", "gt")
                 .replace("(", "").replace(")", "")
                 .replace("°", "deg").replace(",", ""))
    building = Building(
        name=f"natvent_{safe}",
        params=params,
        location=location,
        footprint_pts=[[0, 0], [20, 0], [20, 12], [0, 12]],
    )
    work = Path(tempfile.mkdtemp(prefix=f"pbg_nv_{safe}_"))
    print(f"  Running [{label}] ...")
    building.simulate(idf_dir=work / "idf", output_dir=work / "out")
    return building


# ------------------------------------------------------------------
# Helper: find hottest 2-week window by outdoor temperature
# ------------------------------------------------------------------
def _hottest_window(outdoor_hourly: tuple, weeks: int = 2) -> tuple[int, int]:
    vals = outdoor_hourly
    n = weeks * 7 * 24
    best, best_start = -999.0, 0
    for start in range(0, len(vals) - n, 24):
        mean = sum(vals[start:start + n]) / n
        if mean > best:
            best, best_start = mean, start
    return best_start, best_start + n


# ------------------------------------------------------------------
# Plot 1: monthly mean zone temperature
# ------------------------------------------------------------------
def plot_monthly_zone_temp(
    runs: list[tuple[str, Building, str]],
    out_path: Path,
) -> Path:
    markers = ["o", "s", "^", "D"]
    x = np.arange(12)

    fig, ax = plt.subplots(figsize=(11, 4))

    # outdoor temperature from baseline (same EPW for all)
    outdoor = runs[0][1].results.outdoor_air_temperature
    if outdoor is not None:
        out_vals = list(outdoor.monthly.values)
        ax.plot(x, out_vals, "k--", linewidth=1.2, label="Outdoor (EPW)", alpha=0.6)

    for i, (label, building, colour) in enumerate(runs):
        vals = list(building.results.air_temperature.monthly.values)
        ax.plot(x, vals, f"{markers[i % 4]}-",
                label=label, color=colour, linewidth=2)

    ax.set_xticks(x)
    ax.set_xticklabels(_MONTHS)
    ax.set_ylabel("Mean zone air temperature [°C]")
    ax.set_title("Monthly mean zone temperature — natural ventilation scenarios (AMY 2023)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# Plot 2: hourly zone temp during hottest 2-week window
# ------------------------------------------------------------------
def plot_summer_hourly(
    runs: list[tuple[str, Building, str]],
    out_path: Path,
) -> Path:
    baseline_outdoor = runs[0][1].results.outdoor_air_temperature
    outdoor_h = baseline_outdoor.hourly.values if baseline_outdoor else None

    start, end = _hottest_window(outdoor_h or
                                  runs[0][1].results.air_temperature.hourly.values)
    hours = np.arange(start, end)

    # x-axis as day-of-year labels
    day_ticks = list(range(start, end, 24))
    day_labels = [f"Day {h // 24 + 1}" for h in day_ticks]

    fig, ax = plt.subplots(figsize=(13, 5))

    if outdoor_h is not None:
        ax.fill_between(hours, outdoor_h[start:end], alpha=0.12,
                        color="black", label="Outdoor (EPW)")
        ax.plot(hours, outdoor_h[start:end], "k--", linewidth=1, alpha=0.5)

    for label, building, colour in runs:
        zone_h = building.results.air_temperature.hourly.values
        ax.plot(hours, zone_h[start:end], linewidth=1.5, label=label, color=colour)

    # Comfort thresholds
    ax.axhline(25, color="#e74c3c", linestyle=":", linewidth=1, alpha=0.8, label="25 °C threshold")
    ax.axhline(27, color="#c0392b", linestyle=":", linewidth=1, alpha=0.8, label="27 °C threshold")

    ax.set_xticks(day_ticks)
    ax.set_xticklabels(day_labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Zone air temperature [°C]")
    ax.set_title(
        f"Hourly zone temperature — hottest 2-week period "
        f"(hours {start}–{end}, day {start // 24 + 1}–{end // 24})"
    )
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# Plot 3: monthly heating load (winter penalty)
# ------------------------------------------------------------------
def plot_monthly_heating(
    runs: list[tuple[str, Building, str]],
    out_path: Path,
) -> Path:
    n = len(runs)
    w = 0.8 / n
    x = np.arange(12)

    fig, ax = plt.subplots(figsize=(11, 4))
    for i, (label, building, colour) in enumerate(runs):
        vals = [v / 3.6e6 for v in building.results.heating_load.monthly.values]
        offset = (i - (n - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=label, color=colour, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(_MONTHS)
    ax.set_ylabel("Heating load [kWh]")
    ax.set_title("Monthly heating load — trade-off of window opening (AMY 2023)")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# Plot 4: overheating hours per month
# ------------------------------------------------------------------
def plot_overheating_hours(
    runs: list[tuple[str, Building, str]],
    out_path: Path,
    thresholds: tuple[float, float] = (25.0, 27.0),
) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), sharey=False)

    for ax, thresh in zip(axes, thresholds):
        n = len(runs)
        w = 0.8 / n
        x = np.arange(12)

        for i, (label, building, colour) in enumerate(runs):
            hourly = np.array(building.results.air_temperature.hourly.values)
            # Count hours above threshold per calendar month (assume non-leap year)
            month_ends = np.cumsum([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
            month_starts = np.concatenate([[0], month_ends[:-1]])
            counts = [
                int(np.sum(hourly[s * 24: e * 24] > thresh))
                for s, e in zip(month_starts, month_ends)
            ]
            offset = (i - (n - 1) / 2) * w
            ax.bar(x + offset, counts, w, label=label, color=colour, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(_MONTHS)
        ax.set_ylabel("Hours above threshold")
        ax.set_title(f"Hours with zone temp > {thresh:.0f} °C")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Overheating hours — effect of natural ventilation (AMY 2023)", y=1.01)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# Summary table
# ------------------------------------------------------------------
def print_summary(runs: list[tuple[str, Building, str]]) -> None:
    def fmt(v):
        return f"{v:>10.1f}"

    baseline_heating = runs[0][1].results.heating.value

    # Find hottest 2 weeks for overheating count
    outdoor_h = runs[0][1].results.outdoor_air_temperature.hourly.values
    start, end = _hottest_window(outdoor_h)

    print("\n== Natural Ventilation Summary (AMY 2023) ==")
    header = f"{'Scenario':<22} {'Heating [kWh]':>16} {'Δ Heating':>12} "
    header += f"{'Peak zone [°C]':>16} {'Hrs > 25°C':>12} {'Hrs > 27°C':>12}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    for label, building, _ in runs:
        r = building.results
        hourly = np.array(r.air_temperature.hourly.values)
        peak = round(float(np.max(hourly[start:end])), 1)
        hrs25 = int(np.sum(hourly > 25.0))
        hrs27 = int(np.sum(hourly > 27.0))
        heating = r.heating.value
        delta = f"{(heating - baseline_heating) / baseline_heating * 100:+.1f}%"
        print(f"{label:<22} {heating:>16.0f} {delta:>12} {peak:>16} {hrs25:>12} {hrs27:>12}")

    print("-" * len(header))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> None:
    print("Building scenarios:")
    runs = [
        (label, run_scenario(label, t, min_out), colour)
        for label, t, min_out, colour in _SCENARIOS
    ]

    print_summary(runs)

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    paths = [
        plot_monthly_zone_temp(runs, out_dir / "natvent_monthly_zone_temp.png"),
        plot_summer_hourly(runs, out_dir / "natvent_summer_hourly.png"),
        plot_monthly_heating(runs, out_dir / "natvent_monthly_heating.png"),
        plot_overheating_hours(runs, out_dir / "natvent_overheating_hours.png"),
    ]

    print("\nFigures written:")
    for p in paths:
        print("  ", p)


if __name__ == "__main__":
    main()
