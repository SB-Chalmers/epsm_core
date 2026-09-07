"""Draw supported roof/facade geometry from the current EPSM resolver.

Run: python docs/figures/plot_roof_facade.py --preview-dir output/validation
Requires epsm_core[geometry] and Matplotlib; no EnergyPlus, weather or result files.
Roof panels share a scale. Facade detail panels deliberately use different scales.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, Polygon
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from epsm_core import (
    BalconySpec,
    FacadeOverride,
    FacadeSpec,
    Footprint,
    GeometrySpec,
    GlazingSpec,
    OverhangSpec,
    RoofSpec,
    WindowLayoutSpec,
)
from epsm_core.inspection import geometry_scene

HERE = Path(__file__).resolve().parent
INK = "#172B3A"
MUTED = "#455463"
WALL = "#DEE5E8"
WINDOW = "#64B5D6"
BLUE = "#0072B2"
SHADE = "#E4AD58"
SHADE_EDGE = "#99631A"
CEILING = "#118579"


def vertices(surface):
    return np.array(
        [
            [v["vertex_x_coordinate"], v["vertex_y_coordinate"], v["vertex_z_coordinate"]]
            for v in surface["vertices"]
        ]
    )


def roof_panel(ax, shape, title):
    roof = RoofSpec(shape=shape, topology="cold_attic", attic_height_m=1.5)
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(12, 8), storeys=1, storey_height_m=3, roof=roof
    )
    scene, _ = geometry_scene(geometry)
    maximum = 0.0
    for surface in scene["BuildingSurface:Detailed"].values():
        v = vertices(surface)
        maximum = max(maximum, float(v[:, 2].max()))
        if surface["outside_boundary_condition"] != "Outdoors":
            continue
        attic = surface["construction_name"] == "weather_shell"
        polygon = Poly3DCollection(
            [v],
            facecolor=SHADE if attic else WALL,
            edgecolor=SHADE_EDGE if attic else "#AAB6BD",
            linewidth=0.65,
            alpha=0.80 if attic else 0.60,
        )
        ax.add_collection3d(polygon)
    # The actual occupied top boundary is shared with the unconditioned attic.
    ceilings = [
        vertices(s)
        for s in scene["BuildingSurface:Detailed"].values()
        if s["surface_type"] == "Ceiling" and s["construction_name"] == "top"
    ]
    assert ceilings, "Resolver must expose the horizontal occupied ceiling"
    for v in ceilings:
        assert np.allclose(v[:, 2], 3)
        loop = np.vstack([v, v[0]])
        ax.plot(*loop.T, color=CEILING, linewidth=1.3, linestyle="--", zorder=100)
    ax.set(xlim=(-0.5, 12.5), ylim=(-0.5, 8.5), zlim=(0, 6.0))
    ax.set_box_aspect((13, 9, 6))
    ax.set_proj_type("ortho")
    ax.view_init(elev=25, azim=-53)
    ax.set_axis_off()
    ax.set_title(title, fontsize=13, fontweight="bold", pad=0)
    assumption = "1.50 m attic" if shape == "flat" else f"{roof.pitch:g}° slope"
    ax.text2D(
        0.5,
        -0.035,
        f"{assumption} · top at {maximum:.2f} m",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )


def facade_scene(kind):
    geometry = GeometrySpec.from_footprint(Footprint.rectangle(8, 4), storeys=2, storey_height_m=3)
    edge = next(
        edge
        for edge in geometry.facades()
        if np.isclose(edge.start_m[1], 0) and np.isclose(edge.end_m[1], 0)
    )
    mode = "scaled" if kind == "scaled" else "wwr"
    facade = FacadeSpec(
        default_wwr=0,
        glazing=GlazingSpec(u_value_w_m2k=1.5, solar_heat_gain_coefficient=0.6),
        layout=WindowLayoutSpec(mode=mode),
        overrides=(FacadeOverride(facade_id=edge.facade_id, storey=1, wwr=0.3),),
    )
    if kind == "reveal":
        facade = facade.updated(reveal_depth_m=0.2)
    elif kind == "overhang":
        facade = facade.updated(overhang=OverhangSpec(depth_m=0.6))
    elif kind == "balcony":
        facade = facade.updated(
            balconies=(
                BalconySpec(
                    facade_id=edge.facade_id,
                    storeys=(1,),
                    start_m=0.1,
                    width_m=2.2,
                    depth_m=1.2,
                    front_screen_height_m=0.9,
                ),
            )
        )
    scene, report = geometry_scene(geometry, facade=facade)
    surfaces = scene["BuildingSurface:Detailed"]
    walls = [
        vertices(s)
        for name, s in surfaces.items()
        if report["surfaces"][name]["facade_id"] == edge.facade_id
        and report["surfaces"][name]["storey"] == 1
        and s["surface_type"] == "Wall"
    ]
    windows = [vertices(s) for s in scene["FenestrationSurface:Detailed"].values()]
    shades = [vertices(s) for s in scene["Shading:Building:Detailed"].values()]
    assert windows and all(np.allclose(v[:, 1], 0) for v in windows)
    # Only the specified upper facade receives glazing in this illustration.
    for v in windows:
        assert min(v[:, 2]) >= 3 and max(v[:, 2]) <= 6
    return walls, sorted(windows, key=lambda v: v[:, 0].mean()), shades


def project(v):
    """A fixed oblique projection of resolved coordinates, including outward depth."""
    return np.column_stack([v[:, 0] - 0.55 * v[:, 1], v[:, 2] + 0.32 * v[:, 1]])


def facade_panel(ax, kind, title, caption):
    walls, windows, shades = facade_scene(kind)
    if kind in ("reveal", "overhang"):
        focus = windows[0]
        lo, hi = focus[:, 0].min(), focus[:, 0].max()
        shades = [s for s in shades if lo - 0.5 <= s[:, 0].mean() <= hi + 0.5]
        windows = [focus]
        ax.set(xlim=(lo - 0.35, hi + 0.75), ylim=(3.5, 6.1))
    elif kind == "balcony":
        ax.set(xlim=(-0.2, 3.15), ylim=(2.3, 6.15))
    else:
        ax.set(xlim=(-0.25, 8.25), ylim=(2.55, 6.2))
    for v in walls:
        ax.add_patch(Polygon(project(v), facecolor=WALL, edgecolor="#AAB6BD", linewidth=0.8))
    for v in windows:
        ax.add_patch(Polygon(project(v), facecolor=WINDOW, edgecolor=BLUE, linewidth=1.0))
    for v in shades:
        ax.add_patch(
            Polygon(
                project(v),
                facecolor=SHADE,
                edgecolor=SHADE_EDGE,
                alpha=0.90,
                linewidth=0.85,
            )
        )
    ax.set_aspect("equal")
    ax.set_axis_off()
    left, _, width, _ = ax.get_position().bounds
    ax.figure.text(left + width / 2, 0.345, title, fontsize=12, fontweight="bold", ha="center")
    if kind in ("scaled", "repeated"):
        ax.annotate("", (8, 2.75), (0, 2.75), arrowprops={"arrowstyle": "|-|", "color": MUTED})
        ax.text(4, 2.56, "8 m", ha="center", va="top", fontsize=10, color=MUTED)
    ax.figure.text(
        left + width / 2,
        0.085,
        caption,
        ha="center",
        va="top",
        fontsize=10.5,
        color=MUTED,
        linespacing=1.35,
    )


def make_figure(preview_dir=None):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "text.color": INK,
            "svg.fonttype": "none",
            "svg.hashsalt": "epsm-roof-facade",
            "savefig.facecolor": "white",
        }
    )
    fig = plt.figure(figsize=(16, 9.2))
    fig.text(0.045, 0.96, "Roof and facade geometry", fontsize=23, fontweight="bold")
    fig.text(
        0.045,
        0.918,
        "Resolved EPSM surfaces · geometry assumptions can be selected independently",
        fontsize=12,
        color=MUTED,
    )
    fig.text(0.045, 0.86, "ROOFS", fontsize=10.5, fontweight="bold", color=MUTED)
    fig.text(0.12, 0.86, "12 × 8 m footprint · occupied ceiling at 3 m", fontsize=11, color=MUTED)
    for i, (shape, title) in enumerate(
        (
            ("flat", "Flat cold attic"),
            ("mono_pitch", "Mono-pitch"),
            ("gable", "Gable"),
            ("hip", "Hip"),
        )
    ):
        ax = fig.add_axes([0.03 + i * 0.245, 0.565, 0.235, 0.26], projection="3d")
        roof_panel(ax, shape, title)
    fig.legend(
        handles=[
            Patch(facecolor=WALL, edgecolor="#AAB6BD", label="Occupied enclosure"),
            Patch(facecolor=SHADE, edgecolor=SHADE_EDGE, label="Cold-attic shell"),
            plt.Line2D([], [], color=CEILING, linestyle="--", label="Horizontal occupied ceiling"),
        ],
        loc="center",
        bbox_to_anchor=(0.50, 0.50),
        ncol=3,
        frameon=False,
        fontsize=10.5,
    )
    fig.text(
        0.5,
        0.464,
        "All four examples have unconditioned attics. A compact flat roof omits the attic volume.",
        ha="center",
        fontsize=11,
        color=MUTED,
    )
    fig.add_artist(plt.Line2D([0.045, 0.96], [0.425, 0.425], color="#D3DBE0", linewidth=1))
    fig.text(0.045, 0.382, "FACADES", fontsize=10.5, fontweight="bold", color=MUTED)
    fig.text(
        0.125,
        0.382,
        "8 × 3 m upper-storey facade · 30% window-to-wall ratio",
        fontsize=11,
        color=MUTED,
    )
    panels = (
        ("scaled", "Scaled opening", "One logical opening\nFull facade"),
        ("repeated", "Repeated windows", "WWR-based layout\nFull facade"),
        ("reveal", "Reveal fins", "0.20 m outward fins\nWindow detail"),
        ("overhang", "Window overhang", "0.60 m projection\nWindow detail"),
        ("balcony", "Open balcony", "1.20 m deck; 0.90 m screen\nBalcony detail"),
    )
    for i, (kind, title, caption) in enumerate(panels):
        ax = fig.add_axes([0.04 + i * 0.193, 0.125, 0.174, 0.20])
        facade_panel(ax, kind, title, caption)
    fig.text(
        0.5,
        0.019,
        "Blue glazing stays in the wall plane. Amber fins/decks/screens are shading surfaces. Detail views use different scales.",
        ha="center",
        fontsize=11,
        color=MUTED,
    )
    fig.savefig(HERE / "roof-and-facade.svg", metadata={"Date": None})
    if preview_dir:
        preview_dir = Path(preview_dir)
        preview_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview_dir / "roof-and-facade.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-dir", type=Path)
    make_figure(parser.parse_args().preview_dir)
