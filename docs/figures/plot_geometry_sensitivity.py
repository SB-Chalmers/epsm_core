"""Rebuild the two documentation figures from the adjacent retained data.

Run: python docs/figures/plot_geometry_sensitivity.py
Requires Matplotlib. No simulator, external results directory or network is used.
Optional --preview-dir writes PNG copies for visual review outside the docs tree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, StrMethodFormatter

HERE = Path(__file__).resolve().parent
CLIMATES = ("gothenburg", "malmo", "kiruna")
STYLES = {
    "gothenburg": ("Gothenburg", "#0072B2", "o"),
    "malmo": ("Malmö–Sturup", "#D55E00", "s"),
    "kiruna": ("Kiruna", "#7753A6", "^"),
}
METRICS = (
    ("heating_kwh", "Annual heating", "%", True),
    ("cooling_kwh", "Annual cooling", "kWh/year", False),
    ("solar_kwh", "Transmitted solar", "%", True),
    ("peak_heating_kw", "Hourly heating peak", "kW", False),
    ("peak_cooling_kw", "Hourly cooling peak", "kW", False),
)


def configure():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.labelsize": 11,
            "axes.titlesize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 11,
            "axes.edgecolor": "#C7CED5",
            "axes.labelcolor": "#455463",
            "text.color": "#172B3A",
            "xtick.color": "#455463",
            "ytick.color": "#172B3A",
            "svg.fonttype": "none",
            "svg.hashsalt": "epsm-geometry-sensitivity",
            "savefig.facecolor": "white",
        }
    )


def make_figure(data, kind, preview_dir=None):
    rows = data["cases"]
    baseline = {
        (r["climate"], r["shape"]): r
        for r in rows
        if r["zoning"] == "per_storey" and r["context"] == "none"
    }
    if kind == "context":
        categories = ("rural", "urban_lowrise_dense", "urban_highrise_dense")
        labels = ("Rural", "Low-rise dense", "High-rise dense")
        candidates = {
            (r["climate"], r["context"]): r
            for r in rows
            if r["shape"] == "rectangle" and r["context"] in categories
        }
        title = "Surroundings: solar gains, annual demand and peaks"
        subtitle = "Change from the same rectangle with no surroundings · per-storey zoning"
        note = (
            "8 rural / 25 urban neighbours\n"
            "100 m radius · seed 0\n\n"
            "Cooling is shown in kWh:\n"
            "Kiruna's reference is zero.\n\n"
            "Peaks are hourly averages.\n"
            "Each panel has its own scale."
        )
    else:
        categories = ("rectangle", "courtyard", "wings")
        labels = ("Rectangle", "Courtyard", "Unequal wings")
        candidates = {
            (r["climate"], r["shape"]): r for r in rows if r["zoning"] == "perimeter_core"
        }
        title = "Perimeter/core zoning: annual demand and peaks"
        subtitle = "Change from per-storey zoning · 4.5 m perimeter depth · no surroundings"
        note = (
            "Rectangle / courtyard: 600 m²\n"
            "Unequal wings: 600 + 240 m²\n\n"
            "Cooling is shown in kWh:\n"
            "two Kiruna references are zero.\n\n"
            "Peaks are hourly averages.\n"
            "Each panel has its own scale."
        )
    fig, axes = plt.subplots(2, 3, figsize=(11.2, 7.2))
    fig.subplots_adjust(left=0.15, right=0.98, top=0.81, bottom=0.20, hspace=0.73, wspace=0.40)
    fig.text(0.05, 0.956, title, fontsize=19, fontweight="bold", va="top")
    fig.text(0.05, 0.895, subtitle, fontsize=11.5, color="#455463")
    for index, (metric, heading, unit, relative) in enumerate(METRICS):
        ax = axes.flat[index]
        values = []
        for climate_index, climate in enumerate(CLIMATES):
            label, color, marker = STYLES[climate]
            for category_index, category in enumerate(categories):
                row = candidates[climate, category]
                ref = baseline[climate, row["shape"]]
                before, after = ref[metric], row[metric]
                # Cooling uses absolute differences everywhere; a zero reference
                # never produces an invented percentage or is dropped from view.
                delta = 100 * (after / before - 1) if relative else after - before
                values.append(delta)
                y = category_index + (climate_index - 1) * 0.19
                ax.plot([0, delta], [y, y], color=color, alpha=0.5, linewidth=1.6)
                ax.scatter(
                    delta,
                    y,
                    s=44,
                    color=color,
                    marker=marker,
                    edgecolors="white",
                    linewidths=0.7,
                    zorder=4,
                )
        minimum, maximum = min(0, min(values)), max(0, max(values))
        span = maximum - minimum or 1
        ax.set_xlim(minimum - span * 0.12, maximum + span * 0.12)
        ax.set_ylim(2.5, -0.5)
        ax.set_yticks(range(3), labels if index % 3 == 0 else ("", "", ""))
        ax.tick_params(axis="y", length=0, pad=9)
        ax.tick_params(axis="x", length=3, color="#A9B4BF")
        ax.xaxis.set_major_locator(MaxNLocator(nbins=4, min_n_ticks=3))
        ax.xaxis.set_major_formatter(StrMethodFormatter("{x:g}"))
        ax.grid(axis="x", color="#E7EBEF", linewidth=0.8)
        ax.axvline(0, color="#85919D", linewidth=1.05, zorder=2)
        for side in ("top", "left", "right"):
            ax.spines[side].set_visible(False)
        ax.set_title(f"{chr(65 + index)}  {heading}", loc="left", pad=12, fontweight="bold")
        ax.set_xlabel(f"Change ({unit})", labelpad=7)
    notes = axes[1, 2]
    notes.axis("off")
    notes.text(0, 1.05, "Reading the figure", fontsize=12, fontweight="bold", va="top")
    notes.text(0, 0.80, note, fontsize=10, color="#455463", va="top", linespacing=1.25)
    handles = [
        Line2D([], [], color=color, marker=marker, linestyle="none", markersize=7, label=label)
        for label, color, marker in STYLES.values()
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.044, 0.095),
        ncol=3,
        frameon=False,
        handletextpad=0.4,
        columnspacing=2.4,
        fontsize=11,
    )
    fig.text(
        0.05,
        0.078,
        "30% scaled openings · compact flat roofs · 21°C heating / 26°C cooling",
        fontsize=10,
        color="#455463",
    )
    building_note = (
        "30 × 20 m rectangle · three 3 m storeys"
        if kind == "context"
        else "Three 3 m storeys (wing: two)"
    )
    fig.text(
        0.05,
        0.048,
        f"{building_note} · TMYx 2004–2018 · EnergyPlus 24.2",
        fontsize=10,
        color="#455463",
    )
    fig.text(
        0.05,
        0.018,
        "Controlled model sensitivity; these results do not establish accuracy against real buildings.",
        fontsize=9,
        color="#647482",
    )
    name = f"{kind}-sensitivity"
    fig.savefig(HERE / f"{name}.svg", metadata={"Date": None})
    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview_dir / f"{name}.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    data = json.loads((HERE / "geometry-sensitivity-data.json").read_text())
    configure()
    for kind in ("context", "zoning"):
        make_figure(data, kind, args.preview_dir)


if __name__ == "__main__":
    main()
