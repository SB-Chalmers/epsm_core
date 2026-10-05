"""Reproduce documented cleanup illustrations; requires the notebook extra.

Run from the repository root: python examples/preparation_safeguards.py
Outputs PNG, SVG and numerical evidence under docs/figures/preparation/.
These are geometric examples, not energy-simulation validation.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon, box, shape

from epsm_core import GeometryPolicy, prepare_geometry
from epsm_core.preparation import component_contacts_preserved, polygons

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/figures/preparation"


def cancelling_outline():
    return Polygon([(0, 0), (0.25, -0.02), (0.5, 0), (0.75, 0.02), (1, 0), (1, 1), (0, 1)])


def draw(ax, source, cleaned):
    origin = source.bounds[:2]
    for geometry, color, style, marker in (
        (source, "#24578a", "-", "o"),
        (cleaned, "#d16621", "--", "x"),
    ):
        for p in polygons(translate(geometry, -origin[0], -origin[1])):
            for ring in (p.exterior, *p.interiors):
                x, y = ring.xy
                ax.plot(
                    x,
                    y,
                    color=color,
                    linestyle=style,
                    marker=marker,
                    markersize=3,
                    linewidth=1.6,
                    zorder=3 if style == "--" else 2,
                )
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.15)
    ax.set_xlabel("Local x (m)")
    ax.set_ylabel("Local y (m)")
    ax.margins(0.12)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    noisy = Polygon([(0, 0), (5, 0.001), (10, 0), (10, 8), (0, 8)])
    courtyard = Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20)], [[(5, 5), (5, 15), (15, 15), (15, 5)]]
    )
    real_file = next((ROOT / "tests/fixtures/footprints").glob("2584-9a0fd2bb*.json"))
    real = shape(json.loads(real_file.read_text())["source_geometry"])
    cases = [
        ("Safe removal of survey noise", noisy, GeometryPolicy()),
        ("Equal net area hides outline changes", cancelling_outline(), GeometryPolicy()),
        ("Courtyard retained", courtyard, GeometryPolicy()),
        (
            "Facade property boundary protected",
            noisy,
            GeometryPolicy(edge_properties=(("p0.r0.e0", "wwr=.2"), ("p0.r0.e1", "wwr=.5"))),
        ),
        ("Real corpus case: now requires review", real, GeometryPolicy()),
    ]
    fig, axs = plt.subplots(2, 3, figsize=(15, 10), layout="constrained")
    evidence = {}
    for ax, (title, source, policy) in zip(axs.flat, cases):
        result = prepare_geometry(source, policy)
        draw(ax, source, result.cleaned_geometry)
        if title in ("Safe removal of survey noise", "Facade property boundary protected"):
            detail = ax.inset_axes([0.52, 0.12, 0.43, 0.28])
            draw(detail, source, result.cleaned_geometry)
            detail.set_aspect("auto")
            detail.set_xlim(4, 6)
            detail.set_ylim(-0.0005, 0.0015)
            detail.set_xlabel("")
            detail.set_ylabel("")
            detail.tick_params(labelsize=6)
            detail.set_title("Boundary detail (m); y magnified", fontsize=7)
        metrics = result.metrics
        ax.set_title(title, fontsize=11, fontweight="bold", pad=12)
        note = (
            f"{result.status.replace('_', ' ').upper()}\n"
            f"Net area: {metrics['area_change_fraction']:.4%}  |  "
            f"Exchanged outline: {metrics['symmetric_difference_fraction']:.3%}\n"
            f"Perimeter: {metrics['perimeter_change_fraction']:.3%}  |  "
            f"Displacement: {metrics['boundary_displacement_m']:.4f} m"
        )
        ax.text(0.5, -0.25, note, transform=ax.transAxes, ha="center", fontsize=8.5)
        evidence[title] = dict(
            status=result.status,
            reasons=result.reasons,
            metrics=metrics,
            policy=result.artifact(
                source_crs="metric example", target_crs="metric example", transformation="none"
            )["policy"],
        )
    old = MultiPolygon([box(0, 0, 1, 1), box(1, 1, 2, 2), box(2.1, 2, 3.1, 3)])
    new = MultiPolygon([box(0, 0, 1, 1), box(1.1, 1, 2.1, 2), box(2.1, 2, 3.1, 3)])
    ax = axs.flat[-1]
    draw(ax, old, new)
    ax.set_title("Same contact count; different neighbours", fontsize=11, fontweight="bold", pad=12)
    for x, y, label in ((0.5, 0.5, "A"), (1.55, 1.5, "B"), (2.6, 2.5, "C")):
        ax.text(x, y, label, ha="center", va="center", fontweight="bold")
    ax.text(
        0.5,
        -0.25,
        "CONTACT AUDIT FAILS\nA–B contact becomes B–C contact\n"
        "Count remains one; partner and position change",
        transform=ax.transAxes,
        ha="center",
        fontsize=8.5,
    )
    evidence["contact_switch"] = dict(
        contacts_preserved=component_contacts_preserved(old, new, 0.001),
        description="Synthetic audit comparison, not a simplifier output",
    )
    fig.suptitle("EPSM Core: conservative footprint preparation safeguards", fontsize=16)
    fig.legend(
        handles=[
            Line2D([], [], color="#24578a", marker="o", label="Source"),
            Line2D([], [], color="#d16621", linestyle="--", marker="x", label="Candidate"),
        ],
        loc="outside lower center",
        ncol=2,
        frameon=False,
    )
    fig.savefig(OUT / "safeguards.png", dpi=180)
    svg_path = OUT / "safeguards.svg"
    fig.savefig(svg_path)
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n")
    plt.close(fig)
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
