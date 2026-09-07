"""Draw documentation plans from EPSM's actual resolved thermal floor surfaces.

Run from the repository root:
    python docs/figures/geometry_partitions.py
    python docs/figures/geometry_partitions.py --preview-dir output/validation/figures

Requires an installed epsm_core checkout and Matplotlib. No weather, EnergyPlus,
archive or pre-existing output data is used. SVGs are regenerated beside this file.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as PlotPath
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely import unary_union
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from epsm_core import BuildingPart, FacadeSpec, Footprint, GeometrySpec, GlazingSpec, ZoningSpec
from epsm_core.pipeline import resolve_geometry
from epsm_core.surface_checks import validate_surfaces

HERE = Path(__file__).resolve().parent
INK = "#172B3A"
MUTED = "#455463"
PERIMETER = "#B8D8EB"
CORE = "#F4D5AA"
BASELINE = "#E1E7EC"
BOUNDARY = "#587181"


def configure():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": INK,
            "axes.labelcolor": MUTED,
            "svg.fonttype": "none",
            "svg.hashsalt": "epsm-resolved-geometry-plans",
            "savefig.facecolor": "white",
        }
    )


def buildings():
    """Explicit illustrative inputs; dimensions are metres and heights are known."""
    rectangle = GeometrySpec.from_footprint(
        Footprint.rectangle(40, 30), storey_elevations_m=(0, 3, 6, 9)
    )
    courtyard = GeometrySpec.from_footprint(
        Footprint(
            exterior=((0, 0), (40, 0), (40, 30), (0, 30)),
            holes=(((14, 10), (26, 10), (26, 20), (14, 20)),),
        ),
        storey_elevations_m=(0, 3, 6, 9),
    )
    wings = GeometrySpec(
        parts=(
            BuildingPart(
                identifier="lower",
                footprint=Footprint.rectangle(20, 30),
                storey_elevations_m=(0, 3, 6),
                height_status="measured",
            ),
            BuildingPart(
                identifier="taller",
                footprint=Footprint(exterior=((20, 0), (40, 0), (40, 30), (20, 30))),
                storey_elevations_m=(0, 3, 6, 9, 12),
                height_status="measured",
            ),
        )
    )
    return rectangle, courtyard, wings


def resolved(geometry, mode):
    spec = SimpleNamespace(
        geometry=geometry.updated(zoning=ZoningSpec(mode=mode)),
        facade=FacadeSpec(
            default_wwr=0,
            glazing=GlazingSpec(u_value_w_m2k=1.8, solar_heat_gain_coefficient=0.6),
        ),
    )
    result = resolve_geometry(spec)
    # Validate the same closed, reciprocal mesh that is used by the compiler.
    validate_surfaces(
        {
            "BuildingSurface:Detailed": {
                f.name: dict(
                    zone_name=f.zone,
                    construction_name=f.construction,
                    outside_boundary_condition=f.boundary,
                    outside_boundary_condition_object=f.adjacent,
                    vertices=[
                        dict(vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z)
                        for x, y, z in f.vertices
                    ],
                )
                for f in result.graph.surfaces
            }
        },
        result.graph.zones,
    )
    return result


def polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for child in geometry.geoms for p in polygons(child)]


def patch(polygon, **style):
    polygon = orient(polygon, sign=1)
    vertices, codes = [], []
    for ring in (polygon.exterior, *polygon.interiors):
        coordinates = list(ring.coords)
        vertices.extend(coordinates)
        codes.extend(
            [PlotPath.MOVETO] + [PlotPath.LINETO] * (len(coordinates) - 2) + [PlotPath.CLOSEPOLY]
        )
    return PathPatch(PlotPath(vertices, codes), **style)


def floor_zones(result, elevation):
    pieces = defaultdict(list)
    for face in result.graph.surfaces:
        if face.kind == "Floor" and all(abs(z - elevation) < 1e-7 for _, _, z in face.vertices):
            pieces[face.zone].append(Polygon([(x, y) for x, y, _ in face.vertices]))
    return {name: unary_union(patches) for name, patches in pieces.items()}


def line_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type in ("LineString", "LinearRing"):
        return [geometry]
    return [line for child in geometry.geoms for line in line_parts(child)]


def plan(ax, result, elevation=0, *, detail=False, annotate_core=False):
    zones = floor_zones(result, elevation)
    cover = unary_union(list(zones.values()))
    for name, shape in zones.items():
        kind = result.graph.zones[name].get("zone_kind", "per_storey")
        color = {"perimeter": PERIMETER, "core": CORE}.get(kind, BASELINE)
        for polygon in polygons(shape):
            ax.add_patch(patch(polygon, facecolor=color, edgecolor="none", zorder=1))
        if annotate_core and kind == "core":
            label = shape.representative_point()
            ax.text(label.x, label.y, "Core", ha="center", va="center", fontsize=10, zorder=5)
    internal = unary_union([p.boundary for p in zones.values()]).difference(cover.boundary)
    for line in line_parts(internal):
        x, y = line.xy
        ax.plot(x, y, color=BOUNDARY, lw=0.9, linestyle=(0, (3, 2.5)), zorder=3)
    for polygon in polygons(cover):
        ax.add_patch(patch(polygon, facecolor="none", edgecolor=INK, lw=1.6, zorder=4))
    ax.set(xlim=(-2, 42), ylim=(-2, 32), aspect="equal")
    ax.axis("off")
    if detail:
        ax.text(
            0.98,
            1.065,
            f"{len(zones)} zones shown" if len(zones) != 1 else "1 zone shown",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            color=MUTED,
            fontsize=9,
        )
    return zones


def save(fig, stem, preview_dir):
    fig.savefig(
        HERE / f"{stem}.svg",
        metadata={
            "Date": None,
            "Title": "EPSM resolved geometry: " + stem,
            "Description": (
                "Drawn from epsm_core.pipeline.resolve_geometry. Plan regions are unions of "
                "actual emitted Floor surfaces grouped by thermal zone. The perimeter depth "
                "is the illustrative default of 4.5 metres. Regenerate with geometry_partitions.py."
            ),
        },
    )
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview_dir / f"{stem}.png", dpi=150)
    plt.close(fig)


def zoning_comparison(models, preview_dir):
    fig, axes = plt.subplots(2, 3, figsize=(12.4, 8.6))
    fig.subplots_adjust(left=0.055, right=0.965, top=0.77, bottom=0.17, wspace=0.18, hspace=0.42)
    fig.text(0.055, 0.95, "The same envelope, different thermal zones", fontsize=21, weight="bold")
    fig.text(
        0.055,
        0.91,
        "Resolved ground-floor surfaces · same scale in every panel · dimensions in metres",
        fontsize=11,
        color=MUTED,
    )
    titles = ("Rectangle", "Courtyard", "Unequal-height wings")
    subtitles = (
        "40 × 30 m · three storeys",
        "40 × 30 m · 12 × 10 m courtyard",
        "20 × 30 m each · 6 m / 12 m high",
    )
    for column, (g, title, subtitle) in enumerate(zip(models, titles, subtitles)):
        ax = axes[0, column]
        x = ax.get_position().x0
        fig.text(x, 0.85, title, fontsize=14, weight="bold")
        fig.text(x, 0.823, subtitle, fontsize=9.5, color=MUTED)
        for row, mode in enumerate(("per_storey", "perimeter_core")):
            ax = axes[row, column]
            data = resolved(g, mode)
            plan(ax, data, detail=True, annotate_core=(row == 1 and column == 0))
            ax.text(
                0,
                1.065,
                "PER STOREY" if row == 0 else "PERIMETER / CORE",
                transform=ax.transAxes,
                va="bottom",
                fontsize=9,
                weight="bold",
                color=MUTED,
            )
            if column == 1:
                ax.text(
                    20, 15, "Open\ncourtyard", ha="center", va="center", color=MUTED, fontsize=9
                )
    # The depth dimension spans the actual left facade and resolved core boundary.
    rectangle_zones = floor_zones(resolved(models[0], "perimeter_core"), 0)
    core = next(p for name, p in rectangle_zones.items() if "core" in name)
    depth = core.bounds[0]
    assert abs(depth - 4.5) < 1e-7
    ax = axes[1, 0]
    ax.annotate(
        "", xy=(depth, 15), xytext=(0, 15), arrowprops=dict(arrowstyle="|-|", lw=1, color=INK)
    )
    ax.text(depth / 2, 17.1, f"{depth:g} m", ha="center", fontsize=9)
    axes[1, 0].text(0, -6.2, "Depth is an explicit modelling assumption.", color=MUTED, fontsize=9)
    axes[1, 1].text(
        0, -6.2, "Both outer and courtyard facades contribute.", color=MUTED, fontsize=9
    )
    axes[1, 2].annotate(
        "No band along\nthe shared seam",
        xy=(20, 15),
        xytext=(20, 15),
        ha="center",
        va="center",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.35", facecolor=CORE, edgecolor="none"),
    )
    axes[1, 2].text(
        0, -6.2, "Only exposed facades create perimeter strips.", color=MUTED, fontsize=9
    )
    fig.legend(
        handles=[
            Patch(facecolor=BASELINE, label="Per-storey zone"),
            Patch(facecolor=PERIMETER, label="Perimeter zone"),
            Patch(facecolor=CORE, label="Core zone"),
            Line2D(
                [0], [0], color=BOUNDARY, lw=1, linestyle=(0, (3, 2.5)), label="Virtual boundary"
            ),
        ],
        loc="lower left",
        bbox_to_anchor=(0.05, 0.057),
        ncol=4,
        frameon=False,
        columnspacing=2.4,
        handlelength=2.0,
        fontsize=10,
    )
    fig.text(
        0.055,
        0.034,
        "Virtual boundaries divide thermal space without adding material mass. Plans come from the compiler's shared geometry pipeline.",
        fontsize=9,
        color=MUTED,
    )
    save(fig, "geometry-zoning", preview_dir)


def height_exposure(geometry, preview_dir):
    fig = plt.figure(figsize=(12.4, 5.0))
    grid = fig.add_gridspec(1, 3, left=0.035, right=0.965, top=0.77, bottom=0.24, wspace=0.13)
    massing = fig.add_subplot(grid[0, 0], projection="3d")
    lower, upper = fig.add_subplot(grid[0, 1]), fig.add_subplot(grid[0, 2])
    fig.text(0.055, 0.92, "Exposure changes with height", fontsize=21, weight="bold")
    fig.text(
        0.055,
        0.865,
        "The taller wing gains a perimeter band above the lower wing's roof.",
        color=MUTED,
        fontsize=11,
    )
    envelope = resolved(geometry, "per_storey")
    for part_id, color in (("lower", "#C7D7E3"), ("taller", "#7AAFCF")):
        faces = [
            f.vertices
            for f in envelope.graph.surfaces
            if f.part_id == part_id and f.boundary == "Outdoors" and f.kind in ("Wall", "Roof")
        ]
        massing.add_collection3d(
            Poly3DCollection(faces, facecolor=color, edgecolor=INK, linewidth=0.5)
        )
    massing.set(xlim=(0, 40), ylim=(0, 30), zlim=(0, 16))
    massing.set_box_aspect((40, 30, 19))
    massing.view_init(elev=25, azim=-63)
    massing.axis("off")
    massing.text(7, 9, 8.5, "6 m", color=INK, fontsize=11)
    # A screen-space label remains visible above the 3-D collection's depth sort.
    massing.text2D(0.64, 0.64, "12 m", transform=massing.transAxes, color=INK, fontsize=11, zorder=100)
    massing.text2D(
        0.05,
        1.04,
        "Resolved exterior surfaces",
        transform=massing.transAxes,
        fontsize=11,
        weight="bold",
    )
    data = resolved(geometry, "perimeter_core")
    plan(lower, data, 0)
    plan(upper, data, 6)
    lower.text(
        0,
        1.04,
        "Floor at 0 m · 8 thermal zones",
        transform=lower.transAxes,
        fontsize=11,
        weight="bold",
    )
    upper.text(
        0,
        1.04,
        "Floor at 6 m · 5 thermal zones",
        transform=upper.transAxes,
        fontsize=11,
        weight="bold",
    )
    assert len(floor_zones(data, 0)) == 8
    assert len(floor_zones(data, 6)) == 5
    # The lower roof provides spatial context but contributes no upper-storey floor.
    lower_roof = next(
        f for f in envelope.graph.surfaces if f.part_id == "lower" and f.kind == "Roof"
    )
    roof_polygon = Polygon([(x, y) for x, y, _ in lower_roof.vertices])
    upper.add_patch(patch(roof_polygon, facecolor="#F3F5F7", edgecolor="#A5B3BD", lw=0.8, zorder=0))
    upper.text(10, 15, "Lower\nwing roof", ha="center", va="center", color=MUTED, fontsize=9)
    upper.annotate(
        "New exposed facade",
        xy=(20, 15),
        xytext=(22, -7.3),
        ha="center",
        fontsize=9,
        color=MUTED,
        arrowprops=dict(
            arrowstyle="->", color=MUTED, lw=1, connectionstyle="angle,angleA=90,angleB=0,rad=4"
        ),
    )
    lower.annotate(
        "Shared seam · no perimeter band",
        xy=(20, 15),
        xytext=(20, -7.3),
        ha="center",
        fontsize=9,
        color=MUTED,
        arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
    )
    fig.text(
        0.055,
        0.12,
        "Zones follow original storeys. If a facade is exposed during part of a storey, its perimeter region spans that whole storey.",
        fontsize=10,
        color=MUTED,
    )
    fig.text(
        0.055,
        0.077,
        "Actual wall surfaces retain the neighbour's exact height. These plans use the illustrative 4.5 m depth and compact flat roofs.",
        fontsize=9.5,
        color=MUTED,
    )
    fig.legend(
        handles=[
            Patch(facecolor=PERIMETER, label="Perimeter zone"),
            Patch(facecolor=CORE, label="Core zone"),
            Line2D(
                [0], [0], color=BOUNDARY, lw=1, linestyle=(0, (3, 2.5)), label="Virtual boundary"
            ),
        ],
        loc="lower left",
        bbox_to_anchor=(0.05, 0.008),
        ncol=3,
        frameon=False,
        fontsize=9,
        columnspacing=2.5,
    )
    save(fig, "geometry-height-exposure", preview_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    configure()
    models = buildings()
    zoning_comparison(models, args.preview_dir)
    height_exposure(models[2], args.preview_dir)


if __name__ == "__main__":
    main()
