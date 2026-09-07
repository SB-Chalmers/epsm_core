"""Demo-only input factories and visual aids; modelling calls stay in notebooks."""

import json
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from epsm_core import BuildingSpec, Footprint, GeometrySpec
from epsm_core.inspection import geometry_scene
from epsm_core.viewer import viewer_data

ROOT = Path(__file__).resolve().parents[2]
WEATHER = Path(os.environ.get("EPSM_WEATHER_DIR", ROOT / "data/weather"))
STATIONS = {
    "Gothenburg": "SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw",
    "Malmo": "SWE_SN_Malmo.AP-Sturup.026360_TMYx.2004-2018.epw",
    "Kiruna": "SWE_NB_Kiruna.AP.020440_TMYx.2004-2018.epw",
}
plt.rcParams.update({"figure.figsize": (9, 4), "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 100})


def epw(city="Gothenburg"):
    path = WEATHER / STATIONS[city]
    if not path.is_file():
        raise FileNotFoundError(f"Provide {path.name} under EPSM_WEATHER_DIR (currently {WEATHER}). No weather is downloaded or fabricated.")
    return path


def engine():
    path = os.environ.get("ENERGYPLUS_EXE") or shutil.which("energyplus")
    local = Path("/Applications/OpenStudio-3.9.0/EnergyPlus/energyplus")
    if not path and local.exists():
        path = str(local)
    if not path:
        raise RuntimeError("Install EnergyPlus 24.2 and set ENERGYPLUS_EXE to its executable. Geometry notebooks need no engine.")
    return path


def workspace(name):
    directory = ROOT / "output/demo" / name / uuid4().hex[:12]
    directory.mkdir(parents=True)
    return directory


def building(city="Gothenburg", identifier="demo"):
    # Reuse the repository's documented, explicitly illustrative assumptions.
    import importlib.util
    source = importlib.util.spec_from_file_location("epsm_demo_building", ROOT / "examples/building.py")
    module = importlib.util.module_from_spec(source)
    source.loader.exec_module(module)
    return module.example_spec(epw(city)).updated(identifier=identifier)


def geometry(footprint=None, storeys=3, **options):
    return GeometrySpec.from_footprint(
        footprint if footprint is not None else Footprint.rectangle(30, 20),
        storeys=storeys, storey_height_m=3, **options,
    )


def table(value):
    if isinstance(value, dict):
        value = [{"field": key, "value": str(item)} for key, item in value.items()]
    frame = pd.DataFrame(value)
    display(frame)
    return frame


def plans(shapes, title="Metric footprint diversity", figsize=None):
    columns = min(3, len(shapes))
    rows = (len(shapes) + columns - 1) // columns
    fig, axes = plt.subplots(rows, columns, figsize=figsize or (4 * columns, 3.5 * rows), squeeze=False)
    for ax in axes.flat[len(shapes):]:
        ax.set_visible(False)
    for ax, (name, shape) in zip(axes.flat, shapes.items()):
        shape = shape.polygon if isinstance(shape, Footprint) else shape
        for polygon in getattr(shape, "geoms", [shape]):
            ax.fill(*polygon.exterior.xy, color="#75b5c5", alpha=.7)
            for hole in polygon.interiors:
                ax.fill(*hole.xy, color="white")
        ax.set(title=name, xlabel="x [m]", ylabel="y [m]", aspect="equal")
    fig.suptitle(title)
    fig.tight_layout()
    plt.show(); plt.close(fig)


def preview(value, title="Resolved geometry", interactive=True, figsize=(9, 5)):
    """Static resolved surface evidence plus an optional real embedded widget."""
    if isinstance(value, BuildingSpec):
        model, report = geometry_scene(value.geometry, facade=value.facade, context=value.context)
    else:
        model, report = geometry_scene(value)
    objects = viewer_data(model, report)["objects"]
    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(projection="3d")
    points = []
    for obj in objects:
        xyz = np.asarray(obj["vertices"])
        points.extend(xyz)
        color = "#4c9ed9" if obj["kind"] == "window" else "#79a795" if obj["kind"] == "context" else "#dfc9a4"
        ax.add_collection3d(Poly3DCollection([xyz], facecolor=color, edgecolor="#425568", linewidth=.3, alpha=.45))
    xyz = np.asarray(points)
    if len(xyz):
        low, high = xyz.min(axis=0), xyz.max(axis=0)
        ax.auto_scale_xyz([low[0], high[0]], [low[1], high[1]], [low[2], high[2]])
        ax.set_box_aspect(np.maximum(high-low, 1))
    ax.set(title=title, xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
    plt.show(); plt.close(fig)
    if interactive:
        widget = value.widget()
        # Display exactly once, including when preview() is the last expression.
        # Use value.widget() directly when a reusable widget handle is needed.
        display(widget)


def bars(values, ylabel, title, figsize=(9, 4)):
    series = pd.Series(values, dtype=float)
    fig, ax = plt.subplots(figsize=figsize)
    series.plot.bar(ax=ax, color="#247d92", rot=25)
    ax.set(ylabel=ylabel, title=title)
    plt.tight_layout()
    plt.show(); plt.close(fig)


def weather_frame(path):
    raw = pd.read_csv(path, skiprows=8, header=None)
    return pd.DataFrame({"month": raw[1], "day": raw[2], "hour": raw[3],
                         "temperature_c": raw[6], "relative_humidity_pct": raw[8],
                         "global_horizontal_wh_m2": raw[13]})


def result_frame(result):
    return pd.DataFrame({name: values for name, values in result.hourly.items()
                         if name.endswith("_kwh")}, index=pd.to_datetime(result.time_axis))


def result_plots(result):
    frame = result_frame(result)
    keys = ["space_heating_demand_kwh", "cooling_demand_kwh", "dhw_load_kwh"]
    bars({key: result.scalars[key] for key in keys}, "kWh/year", "Annual thermal demands")
    fig, ax = plt.subplots(figsize=(9, 4))
    frame[keys].resample("ME").sum().plot.bar(ax=ax, stacked=True, rot=45, title="Monthly thermal demand", ylabel="kWh/month")
    plt.tight_layout(); plt.show(); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4))
    frame[keys].iloc[:168].plot(ax=ax, title="First week: hourly interval energy", ylabel="kWh per hour interval")
    plt.tight_layout(); plt.show(); plt.close(fig)
    return frame


def corpus_sample(count=6):
    files = sorted((ROOT / "tests/fixtures/footprints").glob("*.json"))
    return [p for p in files if p.name != "manifest.json"][:count]


def flow(labels, title, figsize=(12, 4), converge=False):
    """Conceptual API composition, not a computed physical result."""
    fig, ax = plt.subplots(figsize=figsize, layout="constrained")
    ax.set(xlim=(-.6, len(labels)-.4), ylim=(-.75, .75), title=title)
    ax.axis("off")
    positions = [(i, 0) for i in range(len(labels))]
    edges = [(i-1, i) for i in range(1, len(labels))]
    if converge:
        positions = [(0, .35), (0, -.35), (1.5, 0), (3, 0)]
        edges = [(0, 2), (1, 2), (2, 3)]
    boxes = []
    for label, (x, y) in zip(labels, positions):
        boxes.append(ax.text(x, y, label, ha="center", va="center", fontsize=10,
                            bbox=dict(boxstyle="round,pad=.6", facecolor="#e4f1f2", edgecolor="#247d92")))
    for start, end in edges:
        ax.annotate("", xy=positions[end], xytext=positions[start],
                    arrowprops=dict(arrowstyle="->", color="#247d92", lw=2,
                                    patchA=boxes[start].get_bbox_patch(), patchB=boxes[end].get_bbox_patch(),
                                    shrinkA=8, shrinkB=8))
    plt.show()
    plt.close(fig)
