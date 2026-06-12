"""Demo 6 — AMY vs TMY comparison.

Runs the same reference building for each weather file:
  * TMY       — SWE_VG_Goteborg.025130_TMYx.epw  (typical meteorological year)
  * AMY 2021  — gothenburg_2021.epw               (actual year 2021, SMHI)
  * AMY 2023  — gothenburg_2023.epw               (actual year 2023, SMHI)

Prints a summary table and writes three PNGs to ``demos/output/``:

* ``amy_vs_tmy_monthly_heating.png``   — monthly heating load (grouped bars)
* ``amy_vs_tmy_monthly_cooling.png``   — monthly cooling load
* ``amy_vs_tmy_monthly_temp.png``      — monthly mean zone air temperature

Run it with::

    PYTHONPATH=src python demos/demo_06_amy_vs_tmy.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pbgenerator import Building, Location, WeatherSite, cmf_1960

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ------------------------------------------------------------------
# Runs: (label, epw_path, bar_colour)
# ------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNS = [
    ("TMY",      _REPO_ROOT / "epw" / "SWE_VG_Goteborg.025130_TMYx.epw",  "#2980b9"),
    ("AMY 2021", Path("/Users/ssanjay/GitHub/smhi2epw/gothenburg_2021.epw"), "#e67e22"),
    ("AMY 2023", Path("/Users/ssanjay/GitHub/smhi2epw/gothenburg_2023.epw"), "#27ae60"),
]


# ------------------------------------------------------------------
# Helper: build and simulate
# ------------------------------------------------------------------
def run_building(epw_path: Path, label: str) -> Building:
    footprint = [[0, 0], [20, 0], [20, 12], [0, 12]]
    params = cmf_1960(num_floors=4, ventilation_system="FTX")
    weather = WeatherSite(epw_path=str(epw_path), station_name=label)
    location = Location.hypothetical_site(city="Gothenburg", weather=weather)
    safe_label = label.replace(" ", "_")
    building = Building(name=f"demo_{safe_label}", params=params, location=location,
                        footprint_pts=footprint)
    work = Path(tempfile.mkdtemp(prefix=f"pbg_{label}_"))
    print(f"Running EnergyPlus [{label}] ...")
    building.simulate(idf_dir=work / "idf", output_dir=work / "out")
    print(f"  Done — {work}")
    return building


# ------------------------------------------------------------------
# Plots
# ------------------------------------------------------------------
def _monthly_kwh(results, signal_name: str) -> list[float]:
    sig = getattr(results, signal_name, None)
    if sig is None:
        return [0.0] * 12
    return [v / 3.6e6 for v in sig.monthly.values]


def _monthly_temp(results) -> list[float]:
    return list(results.air_temperature.monthly.values)


_NEGLIGIBLE_KWH = 1.0  # suppress plot if all runs total less than this


def plot_monthly_energy(
    runs: list[tuple[str, Building, str]],
    signal: str,
    ylabel: str,
    title: str,
    out_path: Path,
) -> Path | None:
    all_vals = [_monthly_kwh(b.results, signal) for _, b, _ in runs]
    # Skip if all values are numerical noise (total < threshold across all runs).
    if sum(v for row in all_vals for v in row) < _NEGLIGIBLE_KWH:
        print(f"  (skipped {out_path.name} — all values negligible)")
        return None

    n = len(runs)
    w = 0.8 / n
    x = np.arange(12)
    fig, ax = plt.subplots(figsize=(11, 4))
    for i, ((label, building, colour), vals) in enumerate(zip(runs, all_vals)):
        offset = (i - (n - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=label, color=colour, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(_MONTHS)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_monthly_temperature(
    runs: list[tuple[str, Building, str]],
    out_path: Path,
) -> Path:
    markers = ["o", "s", "^", "D"]
    x = np.arange(12)
    fig, ax = plt.subplots(figsize=(11, 4))
    for i, (label, building, colour) in enumerate(runs):
        vals = _monthly_temp(building.results)
        ax.plot(x, vals, f"{markers[i % len(markers)]}-",
                label=label, color=colour, linewidth=2)
    ax.set_xticks(x)
    ax.set_xticklabels(_MONTHS)
    ax.set_ylabel("Mean zone air temperature [°C]")
    ax.set_title("Monthly mean zone air temperature — TMY vs AMY")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# Summary table
# ------------------------------------------------------------------
def print_summary(runs: list[tuple[str, Building, str]]) -> None:
    def kwh(val):
        return round(val.value, 1) if val is not None else "N/A"

    def pct_diff(base, v):
        if not isinstance(base, float) or base == 0:
            return "—"
        return f"{(v - base) / base * 100:+.1f}%"

    def get_metrics(b: Building):
        r = b.results
        return [
            kwh(r.heating),
            kwh(r.cooling),
            kwh(r.site_energy),
            round(r.site_eui.value, 1) if r.site_eui else "N/A",
            round(r.air_temperature.annual.value, 2),
        ]

    metric_names = [
        "Annual heating [kWh]",
        "Annual cooling [kWh]",
        "Site energy [kWh]",
        "Site EUI [kWh/m²]",
        "Mean zone temp [°C]",
    ]

    all_metrics = [(label, get_metrics(b)) for label, b, _ in runs]
    base_metrics = all_metrics[0][1]  # TMY is the baseline

    col_name = 28
    col_val = 14
    labels = [label for label, _, _ in runs]
    header = f"{'Metric':<{col_name}}" + "".join(f"{lbl:>{col_val}}" for lbl in labels)
    delta_labels = [f"Δ vs {labels[0]}" for _ in labels[1:]]
    header += "".join(f"{dl:>{col_val}}" for dl in delta_labels)
    sep = "-" * (col_name + col_val * (len(runs) + len(runs) - 1))

    print("\n== Weather Comparison Summary ==")
    print(sep)
    print(header)
    print(sep)
    for i, name in enumerate(metric_names):
        vals = [m[i] for _, m in all_metrics]
        row = f"{name:<{col_name}}" + "".join(f"{str(v):>{col_val}}" for v in vals)
        deltas = [pct_diff(base_metrics[i] if isinstance(base_metrics[i], float) else 0, v)
                  for v in vals[1:]]
        row += "".join(f"{d:>{col_val}}" for d in deltas)
        print(row)
    print(sep)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> None:
    buildings = [(label, run_building(epw, label), colour)
                 for label, epw, colour in _RUNS]

    print_summary(buildings)

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    paths = [
        plot_monthly_energy(
            buildings,
            signal="heating_load",
            ylabel="Heating load [kWh]",
            title="Monthly heating load — TMY vs AMY",
            out_path=out_dir / "amy_vs_tmy_monthly_heating.png",
        ),
        plot_monthly_energy(
            buildings,
            signal="cooling_load",
            ylabel="Cooling load [kWh]",
            title="Monthly cooling load — TMY vs AMY",
            out_path=out_dir / "amy_vs_tmy_monthly_cooling.png",
        ),
        plot_monthly_temperature(
            buildings,
            out_path=out_dir / "amy_vs_tmy_monthly_temp.png",
        ),
    ]

    print("\nFigures written:")
    for p in paths:
        if p is not None:
            print("  ", p)


if __name__ == "__main__":
    main()
