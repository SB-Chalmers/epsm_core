"""Scaffold missing demo notebooks; preserve all existing notebook edits and outputs.

Existing notebooks are the editable source of truth. Shared helpers only provide
setup, illustrative input factories and presentation. Use enrich_demo_notebooks.py
to refresh its managed teaching cells without replacing user-authored content.
"""
from pathlib import Path
import hashlib
import json
import textwrap
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
CATALOG = []
SETUP = '''from pathlib import Path
import sys
ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / "src/epsm_core").is_dir())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import json
from dataclasses import asdict
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display
from epsm_core import *
from epsm_viewer import scene_widget, view_scene, write_scene
from demo.support.common import (building, geometry, epw, engine, workspace, table,
                                 plans, preview, bars, weather_frame, result_frame, result_plots)
from epsm_core.inspection import geometry_scene
OUT = workspace(Path.cwd().name)
'''

def nb(folder, name, title, purpose, steps, *, needs=(), lesson=""):
    rel = f"{folder}/{name}.ipynb"
    intro = f"# {title}\n\n{purpose}\n\n" + (
        "This is an executable lesson about representing building-stock diversity with EPSM Core. "
        "All dimensions are metric. The materials, use patterns and stock weights are explicit demonstration assumptions, "
        "not calibrated national statistics. Read each explanation before changing the code.\n\n"
        "**How to use:** select the **EPSM Core Demo** kernel and Run All from a fresh kernel. "
        "Each notebook is independent; generated files go under `output/demo/`. "
        "Setup instructions and the complete learning path are in [the demo guide](../README.md).\n\n"
    ) + "**Prerequisites:** installed epsm_viewer wheel with notebook extra; " + (", ".join(needs) if needs else "notebook environment; no EnergyPlus or weather required") + "."
    cells = [nbf.v4.new_markdown_cell(intro), nbf.v4.new_code_cell(SETUP)]
    for heading, explanation, code in steps:
        cells += [nbf.v4.new_markdown_cell(f"## {heading}\n\n{explanation}"), nbf.v4.new_code_cell(textwrap.dedent(code).strip())]
    cells.append(nbf.v4.new_markdown_cell("## Interpretation and next experiment\n\n" + lesson +
        "\n\nFor a stock study, retain the inputs, provenance and acceptance decisions with every result. "
        "A successful geometry preview does not establish simulation validity or predictive accuracy. "
        "Change one assumption at a time before combining measures, and report rejected or substituted cases alongside accepted cases."))
    notebook = nbf.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "EPSM Core Demo", "language": "python", "name": "epsm-core-demo"},
        "language_info": {"name": "python", "version": "3.12"},
        "epsm_demo": {"prerequisites": list(needs), "title": title},
    })
    for i, cell in enumerate(notebook.cells):
        cell.id = hashlib.sha256(f"{rel}:{i}".encode()).hexdigest()[:12]
    target = ROOT / "demo" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        nbf.write(notebook, target)
    saved = nbf.read(target, as_version=4).metadata.epsm_demo
    CATALOG.append({"path": rel, "title": saved.title, "prerequisites": list(saved.prerequisites)})

ENGINE = ("local EPW", "EnergyPlus 24.2")
WEATHER = ("local EPW",)
nb('00_quickstart', '01_environment_and_learning_map', 'Environment and learning map',
   'Confirm which interpreter and optional backends are actually running before interpreting any simulation.', [
('Inspect the active environment', 'The notebook kernel can differ from your terminal Python. This table reports the current interpreter and installed versions rather than assuming the environment is correct.', '''
import importlib.metadata as metadata
import subprocess
from epsm_core.roofs import backend_versions
packages = ["epsm_core", "numpy", "shapely", "jupyterlab", "anywidget", "py-straight-skeleton", "nrel-pysam"]
table({"interpreter": sys.executable, **{p: metadata.version(p) for p in packages}})
assert backend_versions()["py_straight_skeleton"] == "0.1.0"
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
'''),
('Check external inputs explicitly', 'EnergyPlus is a separate executable. Missing weather or engine inputs are shown as unavailable here; later notebooks that require them will stop with a specific prerequisite error.', '''
rows = []
for name, check in [("EnergyPlus", engine), ("Gothenburg EPW", epw)]:
    try:
        value = check()
        rows.append({"input": name, "status": "available", "location": str(value)})
    except (RuntimeError, FileNotFoundError) as error:
        rows.append({"input": name, "status": "unavailable", "location": str(error)})
table(rows)
if rows[0]["status"] == "available":
    print(subprocess.run([engine(), "--version"], capture_output=True, text=True, check=True).stdout)
'''),
('Locate the learning path', 'The catalogue groups capabilities by modelling decision. Geometry and visual inspection can be learned before configuring the energy engine.', '''
catalog = json.loads((ROOT / "demo/catalogue.json").read_text())
frame = table(catalog)
bars(frame.path.str.split('/').str[0].value_counts().to_dict(), "notebooks", "Coverage by theme")
preview(geometry(Footprint.l_shape(30, 25, 12, 10)), "First embedded geometry")
''')], lesson='Start with the first building notebook, then visit the themes where your source data has the largest uncertainty.')
nb('00_quickstart', '02_first_building_to_results', 'One building, from assumptions to results',
   'Follow the full lifecycle and distinguish physical inputs, geometric inspection, compilation and accepted simulation output.', [
('Build an explicit specification', 'The factory uses the repository example: concrete and insulation layers, 20% WWR, ventilation with heat recovery and constant use schedules. These are illustrative values. Immutable updates validate every replacement.', '''
b = building()
table({"identifier": b.identifier, "floor_area_m2": b.geometry.conditioned_floor_area_m2,
       "wall_U_W_m2K": b.envelope.wall.u_value_w_m2k,
       "weather_sha256": b.climate.weather_sha256, "physical_hash": b.physical_hash()})
widget = preview(b)
assert b.geometry.conditioned_floor_area_m2 > 0
'''),
('Compile before running', 'Compilation produces EnergyPlus input and an audit report. Surface validation is necessary, but an accepted simulation still requires engine diagnostics.', '''
compiler = EnergyPlusCompiler(engine())
model, report = compiler.compile(b)
assert report.data["validation"]["surface_count"] > 0
table({"run_id": report.run_id, "zones": len(model["Zone"]), "objects": len(model)})
'''),
('Run and reconcile annual energy', 'The runner requires an empty run directory. Three charts separate annual totals, seasonal behaviour and an hourly example. Hourly kWh are interval energy, not instantaneous design loads.', '''
result = EnergyPlusRunner(engine()).run(b, OUT / "run")
assert isinstance(result, SimulationResult)
assert np.isclose(result.hourly["space_heating_demand_kwh"].sum(), result.scalars["space_heating_demand_kwh"])
frame = result_plots(result)
table(result.diagnostics)
''')], needs=ENGINE, lesson='This sequence is the unit of work a stock workflow repeats. Keep the exact weather identity and physical assumptions, not just the final EUI.')
nb('01_geometry','01_footprint_diversity_and_preparation','Footprint diversity and explicit preparation',
   'Preserve shape diversity instead of replacing the entire stock with rectangles. Inspect any cleanup before accepting it.', [
('Construct contrasting forms', 'Concavity, courtyard holes and disconnected components change exposed perimeter and solar access. Coordinates must already be in metres; source_crs is metadata and does not reproject them.', '''
from shapely.geometry import Polygon, MultiPolygon, box, shape
forms = {"rectangle": Footprint.rectangle(30,20), "L": Footprint.l_shape(30,30,15,15),
         "U": Footprint.u_shape(30,30,14,20), "courtyard": box(0,0,30,30).difference(box(10,10,20,20)),
         "disconnected": MultiPolygon([box(0,0,10,10), box(15,0,25,10)])}
plans(forms)
rows = []
for name, outline in forms.items():
    g = GeometrySpec.from_footprint(outline, storeys=2, storey_height_m=3)
    assert np.isclose(g.conditioned_floor_area_m2, 2*g.footprint_area_m2)
    rows.append({"form": name, "parts": len(g.parts), "area_m2": g.footprint_area_m2})
table(rows)
'''),
('Audit a real repository footprint', 'This deterministic corpus selection exercises a real outline; it does not establish a representative sample. The fixture retains source and cleaned geometries. Roof-edge proxies still need interpretation before becoming facade footprints.', '''
files = sorted((ROOT / "tests/fixtures/footprints").glob("0181-*.json"))
fixture = json.loads(files[0].read_text())
raw = shape(fixture["source_geometry"])
prepared = prepare_geometry(raw, GeometryPolicy())
assert isinstance(prepared, GeometryPreparationResult)
plans({"source": raw, "prepared": prepared.cleaned_geometry})
table({"fixture": files[0].name, "status": prepared.status, "reasons": prepared.reasons, **prepared.metrics})
artifact = prepared.artifact(source_crs="EPSG:3006", target_crs="EPSG:3006", transformation="none; already metric")
(OUT / "preparation.json").write_text(json.dumps(artifact, indent=2))
'''),
('Keep review decisions visible', 'A self-intersecting polygon is deliberately supplied to preparation, not directly accepted as a Footprint. Repair is evidence to review, not an automatic endorsement.', '''
bowtie = Polygon([(0,0),(10,10),(0,10),(10,0)])
review = prepare_geometry(bowtie)
assert review.status != "accepted"
table({"status": review.status, "reasons": review.reasons})
preview(geometry(forms["courtyard"]), "Courtyard preserved")
''')], lesson='Compare area, perimeter and topology before and after preparation. Quantify how many source records require review rather than hiding their loss from the stock sample.')
nb('01_geometry','02_massing_storeys_basements_and_party_walls','Massing, storeys, basements and party walls',
   'Represent vertical diversity and contact assumptions without inventing terrain, overlapping solids or partial basements.', [
('Describe unequal wings', 'Parts begin at common grade and may have different heights. Shared ownership seams and exposed upper walls have distinct physical meanings.', '''
from shapely.geometry import box
parts = (BuildingPart(identifier="low", footprint=Footprint(exterior=tuple(box(0,0,15,20).exterior.coords)), storey_elevations_m=(0,3,6)),
         BuildingPart(identifier="high", footprint=Footprint(exterior=tuple(box(15,0,30,20).exterior.coords)), storey_elevations_m=(0,3,6,9,12)))
g = GeometrySpec(parts=parts)
assert g.conditioned_floor_area_m2 == 1800
preview(g, "Unequal wings and exposure")
table([{"part": p.identifier, "floors": p.floors, "height_m": p.storey_elevations_m[-1]} for p in parts])
'''),
('Separate basement conditioning', 'The current basement spans the full footprint. Adding an unconditioned basement changes thermal boundaries; conditioning it also changes the area denominator.', '''
variants = {"none": g, "unconditioned": g.updated(basement_depth_m=2.5),
            "conditioned": g.updated(basement_depth_m=2.5, basement_conditioned=True)}
bars({k:v.conditioned_floor_area_m2 for k,v in variants.items()}, "m² conditioned", "Basement area accounting")
assert variants["conditioned"].conditioned_floor_area_m2 > g.conditioned_floor_area_m2
preview(variants["unconditioned"], "Full-footprint basement")
'''),
('Declare reviewed party-wall evidence', 'Touching a neighbour does not automatically imply a thermal party wall. Record contact, neighbour conditioning and the source of the assumption explicitly.', '''
simple = geometry()
facade = simple.facades()[0]
party = PartyWall(facade_id=facade.facade_id, neighbor_id="reviewed-neighbour", neighbor_conditioning="heated", contact_confirmed=True, assumption_source="demonstration reviewed contact")
attached = simple.updated(party_walls=(party,))
table(party.model_dump())
preview(attached, "Reviewed heated party wall")
''')], lesson='Height and basement assumptions affect both load and floor-area normalization. Keep contact evidence separate from geometric adjacency.')
nb('01_geometry','03_thermal_zoning','Thermal zoning and preserved quantities',
   'Compare detail levels while preserving the physical building. More zones increase workload and do not automatically improve a stock model.', [
('Resolve three zoning modes', 'Per-storey is the default. Perimeter/core uses exposed facade strips; its 4.5 m depth is an explicit modelling assumption.', '''
modes = ["whole_building", "per_storey", "perimeter_core"]
variants = {mode: geometry(zoning=ZoningSpec(mode=mode)) for mode in modes}
reports = {mode: geometry_scene(g)[1] for mode,g in variants.items()}
table([{"mode": mode, "zones": len(reports[mode]["zones"]), "floor_area_m2": g.conditioned_floor_area_m2, "volume_m3": g.conditioned_volume_m3} for mode,g in variants.items()])
assert len({g.conditioned_volume_m3 for g in variants.values()}) == 1
bars({mode: len(r["zones"]) for mode,r in reports.items()}, "thermal zones", "Detail creates workload")
'''),
('Inspect floor partitions', 'The chart uses actual emitted horizontal floor surfaces. Virtual zone boundaries must not be interpreted as new material walls.', '''
from shapely.geometry import Polygon
plans_by_mode = {}
for mode,g in variants.items():
    model, report = geometry_scene(g)
    floors = [Polygon([(v["vertex_x_coordinate"], v["vertex_y_coordinate"]) for v in s["vertices"]]) for s in model["BuildingSurface:Detailed"].values() if s["surface_type"] == "Floor" and all(abs(v["vertex_z_coordinate"]) < 1e-6 for v in s["vertices"])]
    fig, ax = plt.subplots()
    for i,p in enumerate(floors): ax.fill(*p.exterior.xy, alpha=.5, edgecolor="black")
    ax.set(title=mode, xlabel="x [m]", ylabel="y [m]", aspect="equal")
    plt.show()
preview(variants["perimeter_core"], "Perimeter/core surfaces")
'''),
('Expose the failure policy', 'Fallback is opt-in and applies to the whole building. Always inspect requested and effective modes before including a case in a comparison of detail levels.', '''
policy = ZoningSpec(mode="perimeter_core", depth_m=4.5, on_failure="per_storey")
_, report = geometry_scene(geometry(zoning=policy))
table(report["zoning"])
assert report["zoning"]["effective_mode"] == "perimeter_core"
''')], lesson='First establish invariant area, volume and prescribed loads. Use the results notebooks for matched energy comparisons; a zone-count chart alone says nothing about accuracy.')
nb('01_geometry','04_roofs_and_straight_skeleton','Roofs, attics and straight skeleton',
   'Exercise the installed straight-skeleton backend and distinguish roof shape from the occupied thermal boundary.', [
('Inspect roof shape diversity', 'Flat roofs may be compact or cold-attic. Pitched roofs resolve to cold attics above horizontal occupied ceilings; occupied pitched rooms and touching pitched-roof unions are outside this release.', '''
from epsm_core.roofs import roof_faces, skeleton, backend_versions
from shapely.geometry import Polygon
assert backend_versions()["py_straight_skeleton"] == "0.1.0"
roof_specs = {name: RoofSpec(shape=name) for name in ["flat","mono_pitch","gable","hip"]}
table([{**roof.model_dump(), "resolved_pitch": roof.pitch} for roof in roof_specs.values()])
heights = {}
for name,roof in roof_specs.items():
    g = geometry(roof=roof)
    preview(g, name, interactive=name=="hip")
    faces = roof_faces(g.parts[0].footprint.polygon, roof, 9)
    heights[name] = max(v[2] for face in faces for v in face)
bars(heights, "m above grade", "Actual roof maxima")
'''),
('Plot the skeleton and verify coverage', 'Hip facets follow skeleton nodes. Projected facet areas should cover the footprint without silently becoming a flat roof. This checks geometry, not a national success rate.', '''
outline = Footprint.u_shape(30,30,14,20).polygon
sk = skeleton(outline)
fig, ax = plt.subplots()
ax.plot(*outline.exterior.xy, color="black")
for a,bnode in sk.arc_iterator():
    ax.plot([a.position.x,bnode.position.x],[a.position.y,bnode.position.y], color="#c04d31")
ax.set(aspect="equal", title="U-shaped straight skeleton", xlabel="x [m]", ylabel="y [m]")
plt.show()
faces = roof_faces(outline, RoofSpec(shape="hip"), 9)
assert np.isclose(sum(Polygon([(x,y) for x,y,z in face]).area for face in faces), outline.area)
preview(geometry(Footprint.u_shape(30,30,14,20), roof=RoofSpec(shape="hip")), "Concave hip roof")
'''),
('Check missing-backend behaviour', 'A controlled import failure verifies the actionable installation error. This deliberately tests the failure path without uninstalling anything.', '''
from unittest.mock import patch
import builtins
original_import = builtins.__import__
def missing_backend(name, *args, **kwargs):
    if name == "py_straight_skeleton": raise ImportError("demo missing backend")
    return original_import(name, *args, **kwargs)
with patch("builtins.__import__", side_effect=missing_backend):
    try: skeleton(outline)
    except ValueError as error:
        assert "epsm_core[geometry]" in str(error)
        print(error)
    else: raise AssertionError("Missing backend should fail explicitly")
''')], lesson='Straight skeleton is implemented and exercised here. Retain failure counts for irregular stock footprints; do not substitute flat roofs without recording a separate modelling decision.')
nb('01_geometry','05_facades_windows_and_shading','Facades, windows and attached shading',
   'Resolve facade identities first, then vary opening patterns and shading independently of glazing properties.', [
('Select facades by orientation', 'Facade IDs are stable selections, while azimuths already account for building orientation. Overrides target an ID and optionally a storey.', '''
g = geometry(orientation_deg=25)
facades = g.facades()
table([asdict(f) for f in facades])
fid = facades[0].facade_id
base = FacadeSpec(default_wwr=.25, glazing=GlazingSpec(u_value_w_m2k=1.4, solar_heat_gain_coefficient=.55))
override = FacadeOverride(facade_id=fid, storey=0, wwr=.15)
custom = base.updated(overrides=(override,))
assert custom.wwr_for(fid,0) == .15
bars({f.facade_id:f.azimuth_deg for f in facades}, "degrees clockwise from north", "Facade orientation")
'''),
('Compare opening patterns', 'Scaled windows and repeated windows have different geometry even at the same requested WWR. Compare logical window and thermal pane counts; zoning may split a logical opening.', '''
counts = {}
for mode in ["scaled","wwr","dimensions"]:
    layout = WindowLayoutSpec(mode=mode, window_width_m=1.2, window_height_m=1.5, center_spacing_m=3.5, sill_height_ratio=.3) if mode=="dimensions" else WindowLayoutSpec(mode=mode, mid=WindowPattern(width_m=1.2, spacing_m=3.5))
    facade = custom.updated(layout=layout)
    scene, report = geometry_scene(g, facade=facade)
    counts[mode] = report["logical_window_count"]
    display(scene_widget(g.scene(facade=facade), height=450))
bars(counts, "logical windows", "Opening layout comparison")
'''),
('Add explicit shading geometry', 'Reveals model recess shading, not frame conduction. Open balconies and overhangs are shading surfaces; they are not enclosed thermal spaces.', '''
shaded = custom.updated(reveal_depth_m=.12, overhang=OverhangSpec(depth_m=.6), balconies=(BalconySpec(facade_id=fid, storeys=(1,), width_m=3, depth_m=1.2, side_screen_height_m=1),))
scene, report = geometry_scene(g, facade=shaded)
assert len(scene["Shading:Building:Detailed"]) > 0
table({"logical_windows": report["logical_window_count"], "thermal_panes": report["thermal_pane_count"], "shades": len(scene["Shading:Building:Detailed"])})
display(scene_widget(g.scene(facade=shaded)))
''')], lesson='At stock scale, separate uncertain WWR, glazing performance and shade geometry. Assigning more geometric detail is not evidence that the assumed inputs are better.')
nb('01_geometry','06_experimental_apartment_layouts','Experimental apartment layouts',
   'Inspect bounded residential layout generation, type mix, access and the explicit fallback policy.', [
('Request a residential layout', 'Apartment zoning needs residential use and physical dwelling/common partition constructions. Target shares are soft layout goals; they are not a reconstruction of observed floorplans.', '''
b = building()
types = (ApartmentType(name="small", min_area_m2=20, max_area_m2=65, target_share=.5), ApartmentType(name="large", min_area_m2=65, max_area_m2=120, target_share=.5))
controls = ApartmentLayoutSpec(types=types)
b = b.updated(facade=b.facade.updated(layout=WindowLayoutSpec(mode="wwr")), use=b.use.updated(occupancy_category="residential"), envelope=b.envelope.updated(dwelling_partition=b.envelope.intermediate_floor, common_partition=b.envelope.intermediate_floor), geometry=b.geometry.updated(zoning=ZoningSpec(mode="apartments", apartments=controls)))
table([t.model_dump() for t in controls.types])
preview(b, "Procedural apartment zones")
'''),
('Check floorplate coverage and access', 'The resolved report contains the actual layout and any approximation. Floorplate generation must cover the footprint; type targets must not be mistaken for hard area assignments.', '''
from epsm_core.apartments import infer_floorplate
from shapely import unary_union
outline = b.geometry.parts[0].footprint.polygon
plan, reason = infer_floorplate(outline, controls, [])
assert reason is None
cells = [p for p,kind,typ in plan["parts"]]
assert unary_union(cells).symmetric_difference(outline).area < 1e-6
plans({str(i)+" "+kind:p for i,(p,kind,typ) in enumerate(plan["parts"])}, "Generated floorplate cells")
bars({str(i)+" "+kind:p.area for i,(p,kind,typ) in enumerate(plan["parts"])}, "m²", "Actual cell areas")
'''),
('Read requested and effective modes', 'Use on_failure only when whole-building substitution is acceptable. The report is the source of truth for inclusion in an apartment-detail comparison.', '''
_, report = geometry_scene(b.geometry, facade=b.facade)
table(report["layout"])
assert report["zoning"]["effective_mode"] == "apartments"
fallback_policy = ZoningSpec(mode="apartments", on_failure="per_storey")
table(fallback_policy.model_dump())
''')], needs=WEATHER, lesson='Generated layouts are experimental. Track achieved mix, circulation area and substitution rates before using this level of detail across diverse residential buildings.')
nb('01_geometry','07_neighbourhood_context','Neighbourhood context and solar access',
   'Represent nearby shading with explicit geometry, then compare reproducible illustrative neighbourhoods.', [
('Provide a custom neighbour', 'Context objects shade the target but are not thermally coupled. A courtyard can contain a neighbour; positive-area overlap with target footprints is rejected.', '''
from shapely.geometry import box
g = geometry()
neighbour = ContextBuilding(identifier="north-neighbour", footprints=(Footprint(exterior=tuple(box(5,30,25,45).exterior.coords)),), height_m=18)
context = ContextSpec(buildings=(neighbour,))
table(neighbour.model_dump())
display(scene_widget(g.scene(context=context)))
'''),
('Generate seeded scenarios', 'The same seed makes the low-rise and high-rise horizontal geometry comparable. These presets change shading, not weather, wind or engine terrain.', '''
contexts = {name: synthetic_context(g, preset=name, seed=17) for name in ["rural","urban_lowrise_dense","urban_highrise_dense"]}
for name,c in contexts.items():
    display(scene_widget(g.scene(context=c), height=450))
table([{ "preset": name, **c.generation} for name,c in contexts.items()])
bars({name:len(c.buildings) for name,c in contexts.items()}, "neighbours", "Achieved context counts")
'''),
('Inspect target and context separately', 'Cutaway controls affect the target while retaining complete neighbour silhouettes. Keep the achieved context count and representation assumptions with your study.', '''
heights = {name:np.mean([n.height_m for n in c.buildings]) for name,c in contexts.items()}
bars(heights, "m", "Mean neighbour height")
assert [n.footprints for n in contexts["urban_lowrise_dense"].buildings] == [n.footprints for n in contexts["urban_highrise_dense"].buildings]
preview(g, "Target without context: static reference", interactive=False)
''')], lesson='Use matched target inputs to assess shading sensitivity. Do not interpret the labels rural or urban as complete environmental boundary conditions.')
nb('02_weather','01_epw_metadata_and_calendar','EPW metadata and the simulation calendar',
   'Bind a building to a specific weather file and inspect the hourly convention before interpreting seasonal energy.', [
('Construct the climate explicitly', 'The EPW file hash is part of input identity. The calendar year controls the simulation time axis and is distinct from the multi-year weather period in a TMY filename.', '''
from epsm_core.weather import file_sha256, hourly_axis, validate_epw_calendar
climate = climate_from_epw(epw(), calendar_year=2023)
assert isinstance(climate, ClimateSpec)
assert climate.weather_sha256 == file_sha256(epw())
table(climate.model_dump())
validate_epw_calendar(epw(), climate.calendar_year)
axis = hourly_axis(2023)
assert len(axis) == climate.hours_in_year == 8760
'''),
('Preview hourly weather', 'Read temperature and radiation fields to understand the forcing. EPW hour numbering is 1–24; use the validated package calendar for result alignment.', '''
w = weather_frame(epw())
table(w.head(12))
w.groupby("month")["temperature_c"].agg(["min","mean","max"]).plot(title="Monthly dry-bulb temperature", ylabel="°C")
plt.show()
plt.imshow(w.temperature_c.to_numpy().reshape(-1,24).T, aspect="auto", origin="lower", cmap="coolwarm")
plt.colorbar(label="°C"); plt.xlabel("day of weather year"); plt.ylabel("hour index"); plt.title("Temperature calendar"); plt.show()
'''),
('Check calendar length', 'A leap-year axis has 8784 intervals. Calendar compatibility is validated rather than silently repeating or dropping a weather day.', '''
assert len(hourly_axis(2024)) == 8784
bars({"2023":len(axis), "2024":len(hourly_axis(2024))}, "hour intervals", "Calendar lengths")
try:
    validate_epw_calendar(epw(), 2024)
except ValueError as error:
    print("Expected incompatibility for this non-leap TMY:", error)
''')], needs=WEATHER, lesson='Keep EPW identity, chosen calendar and result interval units together. A timestamp shift can invalidate coincident-peak comparisons even if annual totals agree.')
nb('02_weather','02_swedish_climate_diversity','Swedish climate diversity',
   'Compare three explicit stations as climate examples, without inferring national spatial coverage from three locations.', [
('Resolve station identities', 'Each path is explicit and checksum-verified. These TMY files are comparison inputs, not observations of a single common historical year.', '''
cities = ["Gothenburg","Malmo","Kiruna"]
climates = {city:climate_from_epw(epw(city)) for city in cities}
table([{"city":city, **c.model_dump()} for city,c in climates.items()])
fig,ax = plt.subplots()
for city,c in climates.items():
    ax.scatter(c.longitude_deg,c.latitude_deg); ax.annotate(city,(c.longitude_deg,c.latitude_deg))
ax.set(xlabel="longitude [degrees]",ylabel="latitude [degrees]",title="Example station locations (coordinate scatter)")
plt.show()
'''),
('Compare distributions and seasonality', 'Averages hide cold extremes and summer variation. Plot both the distribution and the monthly mean before choosing representative climate classes.', '''
weather = {city:weather_frame(epw(city)) for city in cities}
pd.DataFrame({city:w.temperature_c for city,w in weather.items()}).plot.box(ylabel="°C",title="Annual hourly dry-bulb distributions")
plt.show()
pd.DataFrame({city:w.groupby("month").temperature_c.mean() for city,w in weather.items()}).plot(ylabel="°C",title="Seasonal temperature differences")
plt.show()
'''),
('Compare solar forcing', 'Global horizontal irradiation is not facade irradiation or PV generation. Roof/facade orientation and shading must be considered separately.', '''
bars({city:w.global_horizontal_wh_m2.sum()/1000 for city,w in weather.items()}, "kWh/m²/year", "Global horizontal irradiation")
assert len({c.weather_sha256 for c in climates.values()}) == 3
''')], needs=WEATHER, lesson='A national workflow should select climate inputs from a documented spatial rule upstream. This notebook exercises explicit ClimateSpec diversity only.')
nb('02_weather','03_climate_and_ground_sensitivity','Climate and ground-temperature sensitivity',
   'Keep geometry and use fixed to isolate two environmental assumptions.', [
('Create matched climate cases', 'Only the weather changes between these annual runs. Small cases keep the experiment reviewable; they do not calibrate an entire climate region.', '''
base = building()
runner = EnergyPlusRunner(engine())
results = {}
for city in ["Gothenburg","Malmo","Kiruna"]:
    spec = base.updated(climate=climate_from_epw(epw(city)))
    results[city] = runner.run(spec, OUT / city)
bars({city:r.scalars["space_heating_demand_eui_kwh_m2"] for city,r in results.items()}, "kWh/m²/year", "Matched heating demand across climates")
'''),
('Disclose ground assumptions', 'The default monthly ground temperatures are an uncalibrated engine assumption. Supply an explicit source for an alternative; constant deep-ground temperatures are not outdoor air temperatures.', '''
ground = GroundTemperatureSpec(monthly_temperatures_c=(15.,)*12, source="illustrative constant 15C sensitivity")
changed = base.updated(envelope=base.envelope.updated(ground_temperature=ground))
ground_runner = EnergyPlusRunner(engine(), settings=CompilerSettings(hourly_outputs=(HourlyOutputRequest(name="Surface Inside Face Conduction Heat Transfer Energy"),)))
cold_ground = ground_runner.run(changed, OUT / "ground15")
pd.DataFrame({"default":base.envelope.ground_temperature.monthly_temperatures_c,"illustrative":ground.monthly_temperatures_c},index=range(1,13)).plot(ylabel="°C",xlabel="month",title="Ground boundary assumptions")
plt.show()
'''),
('Compare energy and retained evidence', 'Ground conduction has both directions over the year. The annual absolute-transfer metric should not be interpreted as net heat loss.', '''
bars({"default":results["Gothenburg"].scalars["space_heating_demand_kwh"], "15C ground":cold_ground.scalars["space_heating_demand_kwh"]}, "kWh/year", "Ground sensitivity in Gothenburg")
table({"default_source":base.envelope.ground_temperature.source,"alternative_source":ground.source,"absolute_ground_transfer_kwh":cold_ground.scalars["annual_absolute_ground_transfer_kwh"]})
assert changed.geometry == base.geometry
''')], needs=ENGINE, lesson='Sensitivity to an assumption is not evidence that either boundary condition is correct. Ground-data sourcing remains the responsibility of the caller.')
nb('03_construction','01_materials_layers_and_envelopes','Materials, layers and envelope roles',
   'Construct physical assemblies explicitly and distinguish the top-floor boundary from the external roof shell.', [
('Build and inspect material layers', 'Conductivity, density and heat capacity describe different physical effects. Layer order is explicit; the calculated nominal U-value includes the construction surface resistance.', '''
concrete = MaterialSpec(name="illustrative concrete",conductivity_w_mk=1.7,density_kg_m3=2300,specific_heat_j_kgk=880)
wool = MaterialSpec(name="illustrative mineral wool",conductivity_w_mk=.04,density_kg_m3=40,specific_heat_j_kgk=840)
wall = ConstructionSpec(layers=(LayerSpec(material=wool,thickness_m=.15),LayerSpec(material=concrete,thickness_m=.2)))
table([{"material":l.material.name,"thickness_m":l.thickness_m,"R_m2K_W":l.thickness_m/l.material.conductivity_w_mk} for l in wall.layers])
fig,ax = plt.subplots(); left=0
for layer in wall.layers:
    ax.barh([0],layer.thickness_m,left=left,label=layer.material.name); left+=layer.thickness_m
ax.set(xlabel="layer thickness [m]",title="Wall section: ordered layers",yticks=[]); ax.legend(); plt.show()
'''),
('Check resistance and thickness sensitivity', 'This is a steady-state assembly calculation, not an annual building simulation. Extra insulation reduces nominal U-value but does not specify thermal bridges automatically.', '''
resistance = wall.surface_resistance_m2k_w + sum(l.thickness_m/l.material.conductivity_w_mk for l in wall.layers)
assert np.isclose(wall.u_value_w_m2k,1/resistance)
bars({f"{d*100:.0f} cm":wall.updated(layers=(wall.layers[0].updated(thickness_m=d),wall.layers[1])).u_value_w_m2k for d in [.05,.1,.15,.25]}, "W/m²K", "Insulation thickness sensitivity")
'''),
('Assign physical boundary roles', 'Envelope roles let a cold attic use a top-floor ceiling construction independently from its weather shell. Basement walls and ceilings also have explicit assignments.', '''
slab = ConstructionSpec(layers=(wall.layers[1],))
envelope = EnvelopeSpec(wall=wall,top=wall,ground=wall,intermediate_floor=slab,weather_shell=slab,basement_wall=wall,basement_ceiling=wall)
table({role:value.u_value_w_m2k for role,value in envelope.__dict__.items() if isinstance(value,ConstructionSpec)})
''')], lesson='National archetypes can share explicit assemblies, but measured construction evidence and assumed defaults should remain distinguishable.')
nb('03_construction','02_glazing_and_thermal_mass','Glazing performance and thermal mass',
   'Separate solar transmission, heat loss and stored heat rather than reducing every envelope choice to a single U-value.', [
('Compare glazing specifications', 'U-value and solar heat gain coefficient can affect heating and cooling differently. Visible transmittance is retained independently.', '''
glazing = {"baseline":GlazingSpec(u_value_w_m2k=2.5,solar_heat_gain_coefficient=.7),"improved":GlazingSpec(u_value_w_m2k=1.1,solar_heat_gain_coefficient=.5)}
table([{ "name":name,**g.model_dump()} for name,g in glazing.items()])
bars({name:g.u_value_w_m2k for name,g in glazing.items()},"W/m²K","Glazing heat transmission")
'''),
('Quantify nominal areal heat capacity', 'Areal heat capacity is density × specific heat × thickness summed over layers. It is a useful physical quantity, not a substitute for dynamic simulation.', '''
b = building()
heavy = b.envelope.intermediate_floor
light_material = MaterialSpec(name="illustrative timber",conductivity_w_mk=.13,density_kg_m3=450,specific_heat_j_kgk=1600)
light = ConstructionSpec(layers=(LayerSpec(material=light_material,thickness_m=.12),))
assemblies = {"heavy":heavy,"light":light}
bars({name:sum(l.material.density_kg_m3*l.material.specific_heat_j_kgk*l.thickness_m for l in a.layers)/1000 for name,a in assemblies.items()},"kJ/m²K","Nominal areal heat capacity")
'''),
('Run a matched glazing comparison', 'Keep window area and use unchanged. Annual differences reflect both transmission and solar gains, so do not attribute the result to U-value alone.', '''
results = {name:EnergyPlusRunner(engine()).run(b.updated(facade=b.facade.updated(glazing=g)),OUT/name) for name,g in glazing.items()}
bars({name:r.scalars["space_heating_demand_kwh"] for name,r in results.items()},"kWh/year","Matched glazing cases")
assert b.facade.default_wwr == .2
''')], needs=ENGINE, lesson='Use independently sourced glazing and mass assumptions. Equal U-values do not imply equal dynamic response.')
nb('03_construction','03_physical_quantity_takeoff','Physical quantity takeoff',
   'Count actual materials and equipment without assigning mass to virtual thermal partitions or shading context.', [
('Inspect typed quantities', 'PhysicalQuantity records distinguish opaque layers, glazing and equipment. Null mass for glazing is deliberately different from a measured zero mass.', '''
b = building()
quantities = quantity_takeoff(b)
assert all(isinstance(q,PhysicalQuantity) for q in quantities)
frame = table([q.model_dump() for q in quantities])
bars(frame.groupby("role").mass_kg.sum(min_count=1).dropna().to_dict(),"kg","Nominal material mass by role")
'''),
('Check zoning invariance', 'Perimeter/core boundaries are virtual. They should not add construction quantities when the physical building remains unchanged.', '''
finer = b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode="perimeter_core")))
other = quantity_takeoff(finer)
mass = lambda items:sum(q.mass_kg or 0 for q in items)
assert np.isclose(mass(quantities),mass(other))
bars({"per-storey":mass(quantities),"perimeter/core":mass(other)},"kg","Physical mass is invariant to virtual zoning")
'''),
('Check context exclusion', 'Neighbours are shading inputs rather than part of the target inventory. This distinction prevents duplicated material totals in a stock study.', '''
shaded = b.updated(context=synthetic_context(b.geometry,preset="rural",seed=3))
assert quantity_takeoff(shaded) == quantities
preview(b,"Target whose materials are counted")
''')], needs=WEATHER, lesson='Keep physical quantities for downstream assessment. EPSM Core supplies quantities and references, not automatic costs or carbon factors.')
nb('03_schedule_and_occupancy','01_schedules_and_calendars','Daily schedules and annual calendars',
   'Understand the current 24-value schedule contract and its implications for representing diverse use patterns.', [
('Define a daily profile', 'ScheduleSpec accepts exactly 24 hourly values. The current compiler repeats this day; it has no separate weekday, weekend or holiday schedule input.', '''
from epsm_core.weather import hourly_axis
constant = ScheduleSpec.constant(21)
setback = ScheduleSpec(values=tuple(18 if h<6 or h>=22 else 21 for h in range(24)))
assert len(setback.values)==24
pd.DataFrame({"constant":constant.values,"night setback":setback.values}).plot(xlabel="hour index",ylabel="°C",title="Daily heating setpoint")
plt.show()
table({"values_per_day":len(setback.values),"hours_2023":len(hourly_axis(2023)),"hours_2024":len(hourly_axis(2024))})
'''),
('Preview repetition explicitly', 'The week shown below is a visualization of daily repetition, not a new weekly schedule feature. This limitation matters for schools and offices.', '''
week = np.tile(setback.values,7)
plt.plot(np.arange(168),week); plt.xlabel("hour of illustrative week"); plt.ylabel("°C"); plt.title("The same profile repeats daily"); plt.show()
annual = np.tile(setback.values,365).reshape(365,24)
plt.imshow(annual.T,aspect="auto",origin="lower",cmap="coolwarm"); plt.colorbar(label="°C"); plt.xlabel("day"); plt.ylabel("hour"); plt.title("Repeated daily schedule across 2023"); plt.show()
'''),
('Reject malformed daily inputs', 'Validation stops unsupported lengths before a model is compiled. Setpoint schedules use temperatures; fractional schedules receive additional checks through UseSpec.', '''
from pydantic import ValidationError
try: ScheduleSpec(values=(1.,)*23)
except ValidationError as error: print("Expected rejection:",error.errors()[0]["msg"])
else: raise AssertionError("23-hour schedule was accepted")
''')], lesson='Describe schedule diversity honestly within the current daily-profile API. Do not claim weekday/weekend fidelity from a repeated daily curve.')
nb('03_schedule_and_occupancy','02_occupancy_gains_setpoints_and_dhw','Occupancy, gains, setpoints and DHW',
   'Use explicit operational assumptions to represent contrasting buildings and isolate their effects.', [
('Build contrasting use profiles', 'Occupant density is per conditioned floor area. Fraction schedules modulate gains, while annual DHW intensity controls an energy total.', '''
b = building()
daytime = ScheduleSpec(values=tuple(1 if 8<=h<18 else .1 for h in range(24)))
residential = b.use.updated(occupancy_category="residential", lighting_gain_w_m2=2)
office = UseSpec(occupancy_category="non_residential",heating_setpoint=ScheduleSpec.constant(21),occupant_density_per_m2=.05,equipment_gain_w_m2=6,lighting_gain_w_m2=5,dhw_kwh_m2_year=5,occupancy_fraction=daytime,equipment_fraction=daytime,lighting_fraction=daytime)
uses={"residential":residential,"office-like":office}
table([{ "use":name,"people_per_m2":u.occupant_density_per_m2,"equipment_W_m2":u.equipment_gain_w_m2,"DHW_kWh_m2_year":u.dhw_kwh_m2_year} for name,u in uses.items()])
pd.DataFrame({name:u.occupancy_fraction.values for name,u in uses.items()}).plot(xlabel="hour",ylabel="fraction",title="Daily occupancy assumptions"); plt.show()
'''),
('Compare prescribed internal gains', 'The plotted people gains use activity per person and the supplied fraction. These are prescribed inputs, not measured occupancy.', '''
for name,u in uses.items():
    gains = np.array(u.occupancy_fraction.values)*u.occupant_density_per_m2*u.occupant_activity_w + np.array(u.equipment_fraction.values)*u.equipment_gain_w_m2 + np.array(u.lighting_fraction.values)*u.lighting_gain_w_m2
    plt.plot(gains,label=name)
plt.legend(); plt.xlabel("hour"); plt.ylabel("W/m² prescribed"); plt.title("People, equipment and lighting gains"); plt.show()
'''),
('Run matched operations', 'Changing use can change heating and DHW in opposite directions. Keep the geometry and weather identical to isolate operations.', '''
results={name:EnergyPlusRunner(engine()).run(b.updated(use=u),OUT/name) for name,u in uses.items()}
bars({name:r.scalars["space_heating_demand_kwh"] for name,r in results.items()},"kWh/year","Heating response to use")
for name,r in results.items():
    assert np.isclose(r.scalars["dhw_load_kwh"],uses[name].dhw_kwh_m2_year*b.geometry.conditioned_floor_area_m2,rtol=.01)
''')], needs=ENGINE, lesson='Use-specific assumptions can matter as much as construction detail. Keep their provenance and test them independently before assigning archetypes to a national stock.')
nb('03_schedule_and_occupancy','03_dwelling_and_common_space_operations','Dwelling and common-space operations',
   'Assign common-space operations explicitly when apartment zoning creates circulation and shared zones.', [
('Configure residential and common uses', 'Common-space assumptions are separate inputs. Apartment controls also govern whether residential loads are conserved across the generated layout.', '''
b=building()
b=b.updated(facade=b.facade.updated(layout=WindowLayoutSpec(mode="wwr")),use=b.use.updated(occupancy_category="residential"),envelope=b.envelope.updated(dwelling_partition=b.envelope.intermediate_floor,common_partition=b.envelope.intermediate_floor),geometry=b.geometry.updated(zoning=ZoningSpec(mode="apartments")))
common=b.use.updated(heating_setpoint=ScheduleSpec.constant(18),occupant_density_per_m2=0,equipment_gain_w_m2=0,lighting_gain_w_m2=1,dhw_kwh_m2_year=0)
b=b.updated(common_use=common,common_airflow=AirflowSpec(topology="F",envelope_infiltration_ach=.1,mechanical_vent_l_s_m2=.2))
table({"dwelling_setpoint_C":b.use.heating_setpoint.values[0],"common_setpoint_C":b.common_use.heating_setpoint.values[0],"conserve_residential_loads":b.geometry.zoning.apartments.conserve_residential_loads})
preview(b,"Dwelling and common-zone geometry")
'''),
('Compare daily control temperatures', 'A lower circulation temperature is an illustrative operation, not a universal rule for residential stocks.', '''
pd.DataFrame({"dwelling":b.use.heating_setpoint.values,"common":common.heating_setpoint.values}).plot(ylabel="°C",xlabel="hour",title="Zone-use setpoints"); plt.show()
bars({"dwelling":b.use.lighting_gain_w_m2,"common":common.lighting_gain_w_m2},"W/m²","Lighting assumptions")
'''),
('Inspect actual compiled assignments', 'Read the generated zones and layout report rather than assuming that target type shares uniquely determine the common-area fraction.', '''
model,report=EnergyPlusCompiler(engine()).compile(b)
table(report.data["layout"])
assert report.data["zoning"]["effective_mode"]=="apartments"
table(pd.DataFrame.from_dict(report.data["zones"],orient="index").reset_index())
''')], needs=ENGINE, lesson='Physical apartment partitions and different common-space operations change the modelling package. They are not equivalent to virtual perimeter/core zoning.')
nb('04_systems','01_airflow_and_heat_recovery','Airflow and sensible heat recovery',
   'Compare the supported S, F, FT and FTX topologies with explicit air exchange assumptions.', [
('Declare valid topology inputs', 'Infiltration, natural exchange and mechanical ventilation use different units and represent separate flows. Heat recovery is meaningful only for the compatible system topology.', '''
b=building()
flows={"S":AirflowSpec(topology="S",envelope_infiltration_ach=.2,natural_exchange_ach=.3),
       "F":AirflowSpec(topology="F",envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35),
       "FT":AirflowSpec(topology="FT",envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35),
       "FTX":AirflowSpec(topology="FTX",envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35,sensible_recovery_effectiveness=.7)}
table([f.model_dump() for f in flows.values()])
bars({name:f.sensible_recovery_effectiveness for name,f in flows.items()},"fraction","Sensible recovery assumptions")
'''),
('Run matched system cases', 'The natural system is not necessarily flow-equivalent to the mechanical systems. Treat the S comparison as an assumption package; F/FT/FTX keep the mechanical rate fixed.', '''
results={name:EnergyPlusRunner(engine()).run(b.updated(airflow=f),OUT/name) for name,f in flows.items()}
bars({name:r.scalars["space_heating_demand_kwh"] for name,r in results.items()},"kWh/year","Heating demand by airflow package")
'''),
('Inspect seasonal response', 'EnergyPlus thermal demand is not automatically purchased heating energy or fan electricity. Only report delivery signals the package actually supplies.', '''
pd.DataFrame({name:result_frame(r).space_heating_demand_kwh.resample("ME").sum() for name,r in results.items()}).plot(ylabel="kWh/month",title="Seasonal heating demand"); plt.show()
assert all(r.diagnostics["accepted"] for r in results.values())
''')], needs=ENGINE, lesson='Record assumed ventilation rates and recovery efficiency independently. A national stock needs evidence for both system prevalence and actual operation.')
nb('04_systems','02_delivery_and_exhaust_air_heat_pumps','Delivery and exhaust-air heat pumps',
   'Distinguish thermal demand from capacity-limited FVP delivery and backup energy.', [
('Configure compatible FVP delivery', 'The model uses an explicit COP, thermal capacity and exhaust-temperature threshold. This is the package delivery model, not a detailed refrigerant-cycle simulation.', '''
b=building()
b=b.updated(airflow=AirflowSpec(topology="F",envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35),delivery=DeliverySpec(fvp=FVPSpec(cop=3,capacity_kw=8,dhw_priority=True)))
table(b.delivery.fvp.model_dump())
bars({"capacity":b.delivery.fvp.capacity_kw},"kW thermal","FVP capacity assumption")
'''),
('Run and inspect delivery signals', 'The runner adds delivery arrays after thermal simulation. Exhaust availability and demand can both limit production; backup serves the remaining demand.', '''
result=EnergyPlusRunner(engine()).run(b,OUT/"fvp")
frame=result_frame(result)
keys=[k for k in frame if k.startswith("fvp_") or k.startswith("backup_")]
table({k:result.units[k] for k in keys})
frame[keys].iloc[:168].plot(ylabel="kWh per hour interval",title="FVP and backup: first week"); plt.show()
'''),
('Check the energy balance', 'Produced heat equals electricity plus extracted exhaust heat for the constant COP model. This check is independent of how much backup is needed.', '''
from epsm_core.delivery import fvp_delivery
check=fvp_delivery(b,[10.,2.],[1.,1.],[21.,21.])
assert np.allclose(check["fvp_heat_kwh"],check["fvp_electricity_kwh"]+check["fvp_extracted_heat_kwh"])
bars({k:float(frame[k].sum()) for k in keys},"kWh/year","Annual delivery components")
''')], needs=ENGINE, lesson='Do not subtract PV from thermal demand. Report delivered heat, FVP electricity, backup energy and PV generation with their own units and definitions.')
nb('04_systems','03_photovoltaics','PVWatts generation from explicit PV inputs',
   'Use the optional PySAM backend with the same checksum-verified weather as the building model.', [
('Define the PV system', 'DC nameplate capacity, tilt, azimuth and losses are explicit inputs. This example does not infer usable roof area or perform detailed neighbouring-building PV shading.', '''
pv=PVSpec(dc_capacity_kw=5,tilt_deg=30,azimuth_deg=180)
renewables=RenewablesSpec(pv_systems=(pv,))
climate=climate_from_epw(epw())
table(pv.model_dump())
assert renewables.pv_systems[0]==pv
'''),
('Run the real backend', 'PVWatts returns hourly AC generation in kWh. Reconcile it with the annual value before combining it with other result streams.', '''
generation=run_pvwatts(pv,climate)
hourly=np.asarray(generation["pv_hourly_kwh"])
assert len(hourly)==climate.hours_in_year
assert np.all(np.isfinite(hourly)) and np.all(hourly>=0)
table({k:v for k,v in generation.items() if k!="pv_hourly_kwh"})
plt.imshow(hourly.reshape(-1,24).T,aspect="auto",origin="lower",cmap="YlOrRd"); plt.colorbar(label="kWh per hour interval"); plt.xlabel("day"); plt.ylabel("hour"); plt.title("PV generation calendar"); plt.show()
'''),
('Compare orientation and seasonal generation', 'Keep capacity and climate fixed. A generation estimate is not self-consumption, avoided grid energy or economic payback.', '''
from epsm_core.weather import hourly_axis
series=pd.Series(hourly,index=pd.to_datetime(hourly_axis(climate.calendar_year)))
series.resample("ME").sum().plot.bar(ylabel="kWh/month",title="Seasonal PV generation"); plt.show()
outputs={str(az):float(np.sum(run_pvwatts(pv.updated(azimuth_deg=az),climate)["pv_hourly_kwh"])) for az in [90,180,270]}
bars(outputs,"kWh/year","Azimuth sensitivity [degrees]")
''')], needs=(*WEATHER,"PySAM"), lesson='Keep PV generation separate from building thermal demands. Roof suitability, self-consumption and economic assessment require additional caller-owned assumptions.')
nb('05_renovation','01_individual_measures','Individual renovation measures',
   'Apply every supported renovation operation and inspect its validated physical changes.', [
('Construct explicit measures', 'Insulation specifies element and layer; glazing and airflow replace their complete specifications. FVP requires compatible airflow. PV adds a generation system.', '''
b=building()
layer=b.envelope.wall.layers[0].updated(thickness_m=.1)
measures=[AddInsulation(element="wall",layer=layer),ReplaceGlazing(glazing=GlazingSpec(u_value_w_m2k=1.1,solar_heat_gain_coefficient=.5)),ChangeAirflow(airflow=AirflowSpec(topology="F",envelope_infiltration_ach=.15,mechanical_vent_l_s_m2=.35)),InstallFVP(fvp=FVPSpec(cop=3,capacity_kw=8)),InstallPV(pv=PVSpec(dc_capacity_kw=5))]
table([m.model_dump() for m in measures])
'''),
('Apply immutable transformations', 'Use a compatible exhaust-only baseline for the FVP demonstration. Each operation returns a new BuildingSpec and appends an audit record.', '''
variants={}
for measure in measures:
    source=b.updated(airflow=AirflowSpec(topology="F",envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35)) if isinstance(measure,InstallFVP) else b
    changed=apply_renovation(source,measure,effective_date="2026-01-01")
    assert changed.physical_hash()!=source.physical_hash()
    assert len(changed.renovations)==len(source.renovations)+1
    variants[measure.kind]=changed
assert len(b.renovations)==0
bars({name:len(v.renovations[-1].changes) for name,v in variants.items()},"quantity changes","Physical audit size")
'''),
('Preview quantities before simulation', 'A physical retrofit need not alter the visible shell: insulation changes material layers, while PV is represented as a generation system rather than automatically placed roof panels.', '''
bars({"baseline":b.envelope.wall.u_value_w_m2k,"insulated":variants["add_insulation"].envelope.wall.u_value_w_m2k},"W/m²K","Wall improvement")
preview(variants["replace_glazing"],"Geometry retained after glazing replacement")
''')], needs=WEATHER, lesson='Audit each operation before combining it with another. The physical hashes describe changed inputs, not a guarantee of energy savings.')
nb('05_renovation','02_packages_and_building_diversity','Renovation packages across contrasting buildings',
   'Compare matched baseline and package cases while keeping climate and use fixed within each pair.', [
('Build a two-measure package', 'The order is recorded explicitly. A combined result cannot be assumed to equal the sum of savings from independent measures.', '''
base=building()
forms={"compact":geometry(Footprint.rectangle(20,20),storeys=2),"elongated":geometry(Footprint.rectangle(40,10),storeys=2)}
packages={}
for name,g in forms.items():
    b=base.updated(identifier=name,geometry=g)
    first=apply_renovation(b,AddInsulation(element="wall",layer=b.envelope.wall.layers[0].updated(thickness_m=.1)),effective_date="2026-01-01")
    final=apply_renovation(first,ReplaceGlazing(glazing=GlazingSpec(u_value_w_m2k=1.1,solar_heat_gain_coefficient=.5)),effective_date="2026-01-02")
    packages[name]=(b,final)
plans({name:g.parts[0].footprint for name,g in forms.items()})
'''),
('Run baseline and package pairs', 'Use unique directories for each annual run. Differences between shapes show how exposure changes the response to the same retrofit assumptions.', '''
rows=[]
for name,pair in packages.items():
    for label,b in zip(["baseline","package"],pair):
        r=EnergyPlusRunner(engine()).run(b,OUT/f"{name}-{label}")
        rows.append({"form":name,"case":label,"heating_kwh":r.scalars["space_heating_demand_kwh"],"run_id":r.run_id})
frame=table(rows)
comparison=frame.pivot(index="form",columns="case",values="heating_kwh")
comparison.plot.bar(ylabel="kWh/year",title="Matched renovation comparisons"); plt.show()
'''),
('Interpret absolute and relative savings', 'Absolute savings and percentage savings answer different questions. These cases have equal floor area to make the shape comparison easier to interpret.', '''
savings=comparison.baseline-comparison.package
bars(savings.to_dict(),"kWh/year","Absolute heating savings")
table(pd.DataFrame({"absolute_kwh":savings,"relative_percent":100*savings/comparison.baseline}))
assert all(a.geometry.conditioned_floor_area_m2==800 for a,b in packages.values())
''')], needs=ENGINE, lesson='Extend the diversity matrix only after the matched pair logic is sound. These results cannot establish retrofit uptake, cost effectiveness or national savings without stock evidence.')
nb('05_renovation','03_provenance_and_quantity_changes','Renovation provenance and quantity changes',
   'Keep physical changes and external assessment references inspectable without importing an external catalogue.', [
('Record assumptions and references', 'SourceRecord captures input evidence. DatasetReference and AssessmentReference identify caller-owned data without fetching prices or emission factors.', '''
b=building()
source=SourceRecord(field_path="envelope.wall",status="assumed",source="illustrative assembly",confidence=.5,assumption_profile="demo")
provenance=ProvenanceSpec(records=(source,))
b=b.updated(provenance=provenance)
dataset=DatasetReference(dataset="illustrative-materials",version="demo-1",item_id="wool")
assessment=AssessmentReference(identifier="illustrative-A1-A3",lifecycle_stage="A1-A3",factor_source=dataset)
table(source.model_dump()); table(assessment.model_dump())
'''),
('Apply an audited change', 'Administrative provenance alone must not alter physical identity. A material change must alter it and retain typed before/after quantity records.', '''
assert b.physical_hash()==b.updated(provenance=ProvenanceSpec()).physical_hash()
changed=apply_renovation(b,AddInsulation(element="wall",layer=b.envelope.wall.layers[0].updated(thickness_m=.1)),effective_date="2026-01-01",dataset_references=(dataset,),assessment_references=(assessment,))
record=changed.renovations[-1]
assert isinstance(record,RenovationRecord)
assert all(isinstance(c,QuantityChange) for c in record.changes)
table([{ "action":c.action,"before_kg":c.before.mass_kg if c.before else None,"after_kg":c.after.mass_kg if c.after else None} for c in record.changes])
'''),
('Reconcile physical totals', 'Only physical quantities are computed here. Attaching a factor reference does not calculate carbon or cost.', '''
old=sum(q.mass_kg or 0 for q in quantity_takeoff(b)); new=sum(q.mass_kg or 0 for q in quantity_takeoff(changed))
assert new>old
bars({"before":old,"after":new},"kg","Material mass after insulation")
(OUT/"renovated.json").write_text(changed.model_dump_json(indent=2))
assert BuildingSpec.model_validate_json((OUT/"renovated.json").read_text())==changed
''')], needs=WEATHER, lesson='Provenance and physical identity serve different purposes. Retain both so a stock result can be traced to assumptions and reassessed with different external factors.')
nb('06_io','01_specifications_schema_and_roundtrips','Specifications, schema and JSON roundtrips',
   'Build a validated input, inspect its schema and preserve its physical identity across serialization.', [
('Separate assumptions and observations', 'BuildingBuilder merges caller-owned assumptions with explicit observations. It does not discover a dataset or contact a service.', '''
from pydantic import ValidationError
base=building()
assumptions=base.model_dump(exclude={"identifier","climate","provenance"})
builder=BuildingBuilder(assumption_profile="explicit-demo",assumptions=assumptions)
b=builder.build(identifier="io-demo",climate=climate_from_epw(epw()).model_dump())
table({"identifier":b.identifier,"hash":b.physical_hash(),"provenance_records":len(b.provenance.records)})
'''),
('Roundtrip JSON and inspect schema', 'Validation rejects unknown fields. Use updated for changes; a generic unvalidated model_copy update is not an equivalent operation.', '''
path=OUT/"building.json"; path.write_text(b.model_dump_json(indent=2))
loaded=BuildingSpec.model_validate_json(path.read_text())
assert loaded==b and loaded.physical_hash()==b.physical_hash()
schema=BuildingSpec.model_json_schema()
(OUT/"schema.json").write_text(json.dumps(schema,indent=2))
table([{ "field":key,"required":key in schema["required"]} for key in schema["properties"]])
try: b.updated(unknown_demo_field=True)
except ValidationError as error: print("Expected unknown field rejection:",error.errors()[0]["msg"])
else: raise AssertionError("Unknown field accepted")
'''),
('Exercise CLI schema and validation', 'The CLI accepts the same JSON specification. It provides a useful boundary for caller-owned batch tooling without adding orchestration to core.', '''
import subprocess
for args in [["schema"],["validate",str(path)]]:
    proc=subprocess.run([sys.executable,"-m","epsm_core.cli",*args],capture_output=True,text=True,check=True)
    print(proc.stdout[:500])
table([{ "artifact":p.name,"bytes":p.stat().st_size} for p in OUT.iterdir()])
preview(b,"Serialized building")
''')], needs=WEATHER, lesson='Archive immutable specifications alongside simulation results. A human-readable identifier alone is not enough to establish which inputs produced a result.')
nb('06_io','02_compilation_and_engine_exports','Compilation reports and engine exports',
   'Inspect epJSON, compilation settings and IDF export as explicit boundaries of the simulation pipeline.', [
('Compile with explicit settings', 'CompilerSettings adds keyed hourly outputs and participates in run identity. Physical simulation settings are fixed and validated.', '''
b=building()
settings=CompilerSettings(hourly_outputs=(HourlyOutputRequest(name="Site Outdoor Air Drybulb Temperature"),))
compiler=EnergyPlusCompiler(engine(),settings=settings)
model,report=compiler.compile(b)
assert isinstance(report,CompilationReport)
table({"run_id":report.run_id,"model_types":len(model),"zones":len(model["Zone"])})
bars({k:len(v) for k,v in model.items() if "Surface" in k},"objects","Compiled surface objects")
'''),
('Write inspectable engine artifacts', 'The compiler writes building.json, model.epJSON and compilation.json. Its report records actual generated quantities and validation evidence.', '''
written=compiler.write(b,OUT/"compiled")
assert written.run_id==report.run_id
assert compiler.run_id(b)==report.run_id
table([{ "artifact":p.name,"bytes":p.stat().st_size} for p in (OUT/"compiled").iterdir()])
from epsm_core import scene_data
from epsm_viewer import scene_widget
display(scene_widget(scene_data(model, report.data)))
'''),
('Exercise CLI compile and IDF export', 'IDF is an engine interchange artifact, not a replacement for the explicit BuildingSpec. Check the CLI output and retain the original spec and report.', '''
import subprocess
spec_path=OUT/"compiled/building.json"
for args in [["compile",str(spec_path),str(OUT/"cli-compiled")],["export-idf",str(spec_path),str(OUT/"idf")]]:
    proc=subprocess.run([sys.executable,"-m","epsm_core.cli","--energyplus",engine(),*args],capture_output=True,text=True,check=True)
    print(proc.stdout[:800])
''')], needs=ENGINE, lesson='Keep compiler, backend and engine identities with inputs. Compilation success proves model acceptance checks, not an annual simulation outcome.')
nb('06_io','03_execution_artifacts_and_failures','Execution artifacts and failure evidence',
   'Run an isolated simulation and inspect what remains when an execution cannot proceed.', [
('Run an explicit input', 'Run directories must be empty so old output cannot be mistaken for new evidence. The timeout is explicit and failed runs retain diagnostics.', '''
b=building(); runner=EnergyPlusRunner(engine())
result=runner.run(b,OUT/"accepted",timeout_seconds=1800)
table(result.artifacts)
frame=result_plots(result)
assert result.diagnostics["accepted"]
'''),
('Demonstrate an occupied-directory rejection', 'This is a deliberate failure of run isolation, not a fabricated EnergyPlus failure. The accepted artifacts remain available for inspection.', '''
try: runner.run(b,OUT/"accepted")
except (SimulationError,ValueError,FileExistsError) as error:
    print(type(error).__name__,str(error)[:1200])
else: raise AssertionError("Runner accepted a nonempty directory")
table([{ "artifact":p.name,"bytes":p.stat().st_size} for p in (OUT/"accepted").iterdir() if p.is_file()])
'''),
('Exercise the CLI run boundary', 'The same explicit spec can be passed to the CLI. This second small annual run verifies the external interface; it intentionally uses its own empty directory.', '''
import subprocess
path=OUT/"input.json"; path.write_text(b.model_dump_json())
proc=subprocess.run([sys.executable,"-m","epsm_core.cli","--energyplus",engine(),"run",str(path),str(OUT/"cli-run")],capture_output=True,text=True,check=True)
print(proc.stdout[:1200])
''')], needs=ENGINE, lesson='Report failures alongside accepted results. Core preserves evidence but does not implement stock-level retry, caching or resumability policy.')
nb('07_visualise','01_embedded_geometry_widget','Embedded 3D geometry widget',
   'Inspect resolved geometry directly inside JupyterLab and VS Code, including when the kernel runs on another machine.', [
('Display an engine-independent scene', 'The widget receives bundled JavaScript and scene data through the kernel. It does not depend on a browser reaching the kernel machine through localhost.', '''
from epsm_viewer import scene_widget
g=geometry(Footprint.u_shape(30,30,14,20),roof=RoofSpec(shape="hip"))
widget=scene_widget(g.scene(), height=600)
assert widget._repr_mimebundle_()[0]["application/vnd.jupyter.widget-view+json"]["model_id"]
display(widget)
preview(g,"Static reference for non-widget readers",interactive=False)
'''),
('Use inspection controls', 'Drag to orbit, scroll to zoom, choose a storey and enable cutaway. Select a surface using the dropdown or by clicking the geometry; the next cell reads the Python selection state.', '''
print("Selected surface (empty until you select one):",widget.selected_surface)
scene=g.scene()
assert widget.scene == scene
table({"objects":len(widget.scene["objects"]),"geometry_only":widget.scene["report"]["geometry_only"],"height_px":widget.height})
'''),
('Manage widget lifetime', 'Changing height updates the existing view. close releases the frontend when you are finished; do not close the visible widget immediately after displaying it.', '''
widget.height=650
probe=scene_widget(g.scene(), height=250)
probe.close()  # An undisplayed probe verifies explicit lifecycle use.
bars({kind:sum(o["kind"]==kind for o in widget.scene["objects"]) for kind in {o["kind"] for o in widget.scene["objects"]}},"objects","Scene inventory")
# When finished inspecting the visible widget, run: widget.close()
''')], lesson='A static notebook preview cannot execute WebGL. Rerun the display cell in a trusted live notebook to activate the embedded controls.')
nb('07_visualise','02_compiled_model_inspection','Inspect actual compiled surfaces',
   'Compare a geometry-only preview with compiled constructions and diagnostic evidence.', [
('Compile an explicit building', 'Compiled epJSON contains thermal constructions and load assignments unavailable to a geometry-only preview. Neither display mode runs EnergyPlus by itself.', '''
from epsm_core import scene_data
from epsm_viewer import scene_widget, view_scene, write_scene
b=building(); compiler=EnergyPlusCompiler(engine())
report=compiler.write(b,OUT/"compiled")
compiled_scene = scene_data(json.loads((OUT/"compiled/model.epJSON").read_text()), report.data)
widget=scene_widget(compiled_scene)
display(widget)
preview(b,"Static geometry reference",interactive=False)
'''),
('Inspect construction evidence', 'Select a wall in the widget to inspect source epJSON, nominal/applied U-values and layer metadata. This table previews the same report evidence.', '''
table(pd.DataFrame.from_dict(report.data["constructions"],orient="index").reset_index())
assert not widget.scene["report"].get("geometry_only",False)
bars({"zones":len(report.data["zones"]),"surfaces":len(report.data["surfaces"])},"count","Compiled inventory")
'''),
('Use the external viewer explicitly', 'The browser-server handle remains available for standalone work. It must remain open while a browser uses its URL; the context manager below is only a short HTTP smoke test.', '''
from urllib.request import urlopen
bundle=write_scene(compiled_scene, directory=OUT/"browser-bundle")
with view_scene(compiled_scene, directory=OUT/"served", launch_browser=False) as handle:
    assert urlopen(handle.url).status==200
    print("Standalone viewer served successfully")
table([{ "file":p.name,"bytes":p.stat().st_size} for p in bundle.iterdir()])
''')], needs=ENGINE, lesson='Use the compiled viewer for thermal evidence and the geometry widget for early shape review. Keep acceptance diagnostics separate from visual plausibility.')
nb('07_visualise','03_comparative_geometry_review','Independent comparative geometry review',
   'Compare multiple embedded scenes and preserve a readable static reference without changing physical model inputs.', [
('Display independent widgets', 'Each widget has its own controls and selection state. Changing one view must not change another or mutate the underlying immutable GeometrySpec.', '''
from ipywidgets import HBox,Layout
from epsm_viewer import scene_widget, view_scene
left=geometry(); right=left.updated(zoning=ZoningSpec(mode="perimeter_core"),roof=RoofSpec(shape="gable"))
w1=scene_widget(left.scene(), height=500); w2=scene_widget(right.scene(), height=500)
display(HBox([w1,w2],layout=Layout(width="100%")))
assert w1.model_id!=w2.model_id
preview(left,"Per-storey baseline",interactive=False)
preview(right,"Perimeter/core with cold attic",interactive=False)
'''),
('Read scene complexity', 'The comparison changes two controls for visual teaching. For energy attribution, change them separately using matched simulations.', '''
bars({"left":len(w1.scene["objects"]),"right":len(w2.scene["objects"])},"objects","Resolved scene size")
table({"left_selection":w1.selected_surface,"right_selection":w2.selected_surface})
assert left.zoning.mode=="per_storey"
'''),
('Separate scene generation from display', 'Core scene methods provide data; epsm_viewer owns standalone display. Notebook widgets are the inline interface; the following handles are closed promptly after HTTP checks.', '''
from urllib.request import urlopen
with view_scene(left.scene(), directory=OUT/"geometry", launch_browser=False) as handle:
    assert urlopen(handle.url).status==200
with view_scene(right.scene(), directory=OUT/"preview", launch_browser=False) as handle:
    assert urlopen(handle.url).status==200
''')], lesson='Keep preview complexity bounded when inspecting many buildings. A representative gallery is more useful than loading a whole national stock into one WebGL scene.')
nb('08_batch','01_district_context_and_parallel_runs','District context and bounded parallel runs',
   'Run a small district using existing APIs and inspect its conservative neighbour representation.', [
('Place buildings in one metric frame', 'District targets must share a coordinate system, have unique identifiers and use zero scene orientation. Other targets become shading extrusions; there is no inter-building thermal coupling.', '''
from shapely.geometry import box
base=building()
targets=[]
for i in range(3):
    fp=Footprint(exterior=tuple(box(i*50,0,i*50+20,15).exterior.coords))
    targets.append(base.updated(identifier=f"target-{i}",geometry=geometry(fp,storeys=i+1,source_crs="local_metres")))
plan=DistrictPlan(buildings=tuple(targets))
resolved=tuple(plan.resolved_buildings())
assert all(len(b.context.buildings)==2 for b in resolved)
table([{ "target":b.identifier,"neighbours":len(b.context.buildings),"floor_area_m2":b.geometry.conditioned_floor_area_m2} for b in resolved])
preview(resolved[1],"Middle target and shading neighbours")
'''),
('Run with two workers', 'The district helper uses bounded threads around independent engine processes. A failed worker propagates its exception; completed artifacts remain on disk.', '''
results=plan.run(OUT/"district",energyplus=engine(),workers=2)
assert set(results)=={b.identifier for b in targets}
bars({name:r.scalars["space_heating_demand_eui_kwh_m2"] for name,r in results.items()},"kWh/m²/year","District heating EUI")
'''),
('Aggregate aligned hourly demands', 'The peak of a sum is not generally the sum of each building peak. Align the validated time axes before aggregation.', '''
profiles=pd.DataFrame({name:result_frame(r).space_heating_demand_kwh for name,r in results.items()})
assert not profiles.isna().any().any()
profiles.iloc[:168].plot(ylabel="kWh per hour interval",title="Aligned district heating profiles"); plt.show()
table({"coincident_hourly_average_peak_kW":profiles.sum(axis=1).max(),"sum_of_individual_hourly_peaks_kW":profiles.max().sum()})
''')], needs=ENGINE, lesson='DistrictPlan includes every other target as context, so it is a small-district helper. National spatial partitioning and neighbour selection belong upstream.')
nb('08_batch','02_building_stock_diversity_matrix','A building-stock diversity matrix',
   'Capture diversity deliberately with existing inputs rather than claiming national representativeness from arbitrary sample size.', [
('Define explicit contrasting cases', 'This matrix covers form, height, insulation, use, climate and ventilation. Each dimension is a modelling choice; the rows are illustrative samples, not inferred building records.', '''
rows=[{"case":f"case-{i}","form":["rectangle","L","U"][i%3],"storeys":[1,2,4,6,3,8][i],"insulation_m":[.05,.1,.15,.2,.25,.1][i],"use":"residential" if i%2==0 else "non_residential","climate":["Gothenburg","Malmo","Kiruna"][i%3],"ventilation":"F" if i%2==0 else "FTX"} for i in range(6)]
frame=table(rows)
forms={"rectangle":Footprint.rectangle(30,20),"L":Footprint.l_shape(30,30,15,15),"U":Footprint.u_shape(30,30,14,20)}
plans(forms)
'''),
('Resolve validated specifications', 'The builder factory supplies explicit remaining assumptions. The resulting objects can be compiled independently; no new stock orchestration API is introduced.', '''
specs=[]
for row in rows:
    b=building(row["climate"],row["case"])
    wall=b.envelope.wall.updated(layers=(b.envelope.wall.layers[0].updated(thickness_m=row["insulation_m"]),*b.envelope.wall.layers[1:]))
    flow=AirflowSpec(topology=row["ventilation"],envelope_infiltration_ach=.2,mechanical_vent_l_s_m2=.35,sensible_recovery_effectiveness=.7 if row["ventilation"]=="FTX" else 0)
    specs.append(b.updated(geometry=geometry(forms[row["form"]],storeys=row["storeys"]),envelope=b.envelope.updated(wall=wall),use=b.use.updated(occupancy_category=row["use"]),airflow=flow))
assert len({s.physical_hash() for s in specs})==6
bars({s.identifier:s.geometry.conditioned_floor_area_m2 for s in specs},"m²","Sample floor-area diversity")
'''),
('Inspect what the matrix covers', 'Coverage of input categories is not coverage of their joint distribution. A larger factorial expansion may quickly become unaffordable and still omit observed stock structures.', '''
encoded=pd.get_dummies(frame.set_index("case")[["form","use","climate","ventilation"]],dtype=int)
fig,ax=plt.subplots(figsize=(10,4)); ax.imshow(encoded,aspect="auto",cmap="Blues",vmin=0,vmax=1)
ax.set_xticks(range(len(encoded.columns)),encoded.columns,rotation=70,ha="right"); ax.set_yticks(range(len(encoded)),encoded.index); ax.set_title("Explicit category coverage"); plt.tight_layout(); plt.show()
for spec in specs: (OUT/f"{spec.identifier}.json").write_text(spec.model_dump_json(indent=2))
''')], needs=WEATHER, lesson='Choose extra cases where important physical combinations are absent. Unsupported geometry and uncertain inputs should remain visible in the sampling report.')
nb('08_batch','03_diversity_capstone','Diversity capstone: six buildings and matched retrofits',
   'Run twelve small annual cases using current APIs, retain failures and aggregate only matched accepted pairs.', [
('Construct six physical cases', 'This pilot spans form, height, climate and wall insulation. The same wall-insulation measure is applied to each baseline; equal demonstration weights do not imply national population frequencies.', '''
from concurrent.futures import ThreadPoolExecutor
forms=[Footprint.rectangle(20,15),Footprint.l_shape(30,30,15,15),Footprint.u_shape(30,30,14,20)]
cases=[]
for i in range(6):
    b=building(["Gothenburg","Malmo","Kiruna"][i%3],f"sample-{i}")
    wall=b.envelope.wall.updated(layers=(b.envelope.wall.layers[0].updated(thickness_m=.05+.025*i),*b.envelope.wall.layers[1:]))
    b=b.updated(geometry=geometry(forms[i%3],storeys=1+i%4),envelope=b.envelope.updated(wall=wall))
    retrofit=apply_renovation(b,AddInsulation(element="wall",layer=wall.layers[0].updated(thickness_m=.1)),effective_date="2026-01-01")
    cases.extend([(f"{i}-baseline",b),(f"{i}-retrofit",retrofit)])
table([{ "case":name,"area_m2":b.geometry.conditioned_floor_area_m2,"wall_U_W_m2K":b.envelope.wall.u_value_w_m2k,"weather":Path(b.climate.epw_path).name} for name,b in cases])
plans({str(i):form for i,form in enumerate(forms)})
'''),
('Run with explicit acceptance accounting', 'This notebook owns only a small experiment loop. Exceptions are recorded with their case identity; accepted pairs are required before calculating savings. This is not a retry or resume service.', '''
runner=EnergyPlusRunner(engine())
def run_case(item):
    name,spec=item
    try:
        result=runner.run(spec,OUT/name)
        return {"case":name,"status":"accepted","heating_kwh":result.scalars["space_heating_demand_kwh"],"run_id":result.run_id,"area_m2":spec.geometry.conditioned_floor_area_m2}
    except Exception as error:
        return {"case":name,"status":"failed","error":str(error)}
with ThreadPoolExecutor(max_workers=2) as pool:
    records=list(pool.map(run_case,cases))
(OUT/"manifest.json").write_text(json.dumps(records,indent=2))
frame=table(records)
bars(frame.status.value_counts().to_dict(),"cases","Acceptance accounting")
assert len(frame)==12 and (frame.status=="accepted").all(), "Inspect retained failures before comparing this pilot"
'''),
('Compare matched pairs', 'Only accepted baseline/retrofit pairs belong in the savings comparison. The result demonstrates heterogeneous response, not a national total.', '''
frame["building"]=frame.case.str.split('-').str[0]; frame["scenario"]=frame.case.str.split('-').str[1]
pairs=frame.pivot(index="building",columns="scenario",values="heating_kwh")
pairs.plot.bar(ylabel="kWh/year",title="Six matched annual comparisons"); plt.show()
bars((pairs.baseline-pairs.retrofit).to_dict(),"kWh/year","Diversity of heating savings")
assert len(pairs)==6
''')], needs=ENGINE, lesson='A national application needs observed distributions, spatial input assignment and orchestration upstream. This capstone verifies the core unit of work across diverse inputs.')
nb('09_results','01_scalars_hourly_signals_and_units','Scalars, hourly signals and units',
   'Read SimulationResult as a structured evidence object and reconcile annual and hourly demand.', [
('Produce a real result', 'The runner retains raw requested signals as well as normalized demand arrays. Use the units mapping rather than inferring units from a plot label.', '''
b=building(); result=EnergyPlusRunner(engine()).run(b,OUT/"run")
assert isinstance(result,SimulationResult)
table(result.scalars)
table([{ "signal":key,"unit":unit} for key,unit in result.units.items()][:20])
'''),
('Reconcile and plot demand', 'Annual heating should equal the sum of hourly interval energy. EUI divides energy by the reported conditioned floor area, which changes when basement conditioning changes.', '''
frame=result_plots(result)
for key in ["space_heating_demand_kwh","cooling_demand_kwh","dhw_load_kwh"]:
    assert np.isclose(frame[key].sum(),result.scalars[key])
assert np.isclose(result.scalars["space_heating_demand_eui_kwh_m2"],frame.space_heating_demand_kwh.sum()/b.geometry.conditioned_floor_area_m2)
'''),
('Inspect duration and acceptance', 'Sorted hourly values show demand duration but discard timing. The maximum hourly kWh is numerically an average kW over that hour, not a subhourly design peak.', '''
plt.plot(np.sort(frame.space_heating_demand_kwh.to_numpy())[::-1]); plt.xlabel("hours ranked by demand"); plt.ylabel("hourly-average kW"); plt.title("Heating load-duration curve"); plt.show()
table(result.diagnostics)
assert result.diagnostics["accepted"]
''')], needs=ENGINE, lesson='Keep thermal demand, delivered energy and electricity generation distinct. Annual totals alone cannot describe coincident peaks or load-shape diversity.')
nb('09_results','02_comparisons_and_aggregation','Comparisons and illustrative stock aggregation',
   'Compare energy, intensity and coincident profiles using explicit demonstration weights.', [
('Run two contrasting sizes', 'Area normalization and population weighting answer different questions. Both buildings use the same climate and construction to isolate size and exposure.', '''
base=building(); specs={"small":base.updated(geometry=geometry(Footprint.rectangle(10,10),storeys=1)),"large":base.updated(geometry=geometry(Footprint.rectangle(30,20),storeys=4))}
results={name:EnergyPlusRunner(engine()).run(b,OUT/name) for name,b in specs.items()}
rows=[{"case":name,"area_m2":specs[name].geometry.conditioned_floor_area_m2,"heating_kwh":r.scalars["space_heating_demand_kwh"],"eui":r.scalars["space_heating_demand_eui_kwh_m2"]} for name,r in results.items()]
frame=table(rows).set_index("case")
frame.eui.plot.bar(ylabel="kWh/m²/year",title="Area-normalized heating"); plt.show()
'''),
('Aggregate with explicit illustrative counts', 'These weights are teaching values, not Swedish building counts. A weighted stock EUI divides total weighted energy by total weighted floor area, rather than averaging building EUIs.', '''
weights=pd.Series({"small":10,"large":2},name="illustrative_count")
energy=(frame.heating_kwh*weights).sum(); area=(frame.area_m2*weights).sum()
stock_eui=energy/area
assert np.isclose(stock_eui,np.average(frame.eui,weights=frame.area_m2*weights))
table({"weighted_energy_kwh":energy,"weighted_area_m2":area,"weighted_EUI_kwh_m2":stock_eui})
bars((frame.heating_kwh*weights).to_dict(),"illustrative stock kWh/year","Weighted contribution")
'''),
('Align profiles before calculating peaks', 'Use the validated time axis and reject mismatches. Summing individual peaks overstates a coincident peak unless they occur together.', '''
profiles=pd.DataFrame({name:result_frame(r).space_heating_demand_kwh for name,r in results.items()})
assert not profiles.isna().any().any()
total=profiles.mul(weights).sum(axis=1)
assert total.max()<=float((profiles.max()*weights).sum())+1e-6
total.iloc[:168].plot(ylabel="illustrative stock hourly-average kW",title="Weighted coincident heating profile"); plt.show()
''')], needs=ENGINE, lesson='National estimates require justified counts and representativeness. The aggregation mathematics is useful here; the demonstration weights carry no national inference.')
nb('09_results','03_quality_sensitivity_and_interpretation','Quality, sensitivity and interpretation',
   'Separate model acceptance from accuracy and inspect whether a requested detail level was actually used.', [
('Compare matched zoning modes', 'Both cases preserve geometry and operations. Any substitution invalidates a claim about the requested zoning mode unless reported separately.', '''
b=building(); results={}
for mode in ["per_storey","perimeter_core"]:
    spec=b.updated(geometry=b.geometry.updated(zoning=ZoningSpec(mode=mode,on_failure="error")))
    results[mode]=EnergyPlusRunner(engine()).run(spec,OUT/mode)
rows=[]
for mode,r in results.items():
    zoning=r.diagnostics["zoning"]
    assert zoning["effective_mode"]==mode and not zoning["substituted"]
    rows.append({"requested":mode,"effective":zoning["effective_mode"],"accepted":r.diagnostics["accepted"],"heating_kwh":r.scalars["space_heating_demand_kwh"],"cooling_kwh":r.scalars["cooling_demand_kwh"]})
frame=table(rows).set_index("requested")
frame[["heating_kwh","cooling_kwh"]].plot.bar(ylabel="kWh/year",title="Matched zoning comparison"); plt.show()
'''),
('Inspect absolute differences', 'Percentages become unstable near zero cooling demand. Show absolute differences and a clearly defined baseline before reporting percentages.', '''
delta=frame.loc["perimeter_core",["heating_kwh","cooling_kwh"]]-frame.loc["per_storey",["heating_kwh","cooling_kwh"]]
bars(delta.to_dict(),"kWh/year difference","Perimeter/core minus per-storey")
profiles={mode:result_frame(r).space_heating_demand_kwh for mode,r in results.items()}
pd.DataFrame(profiles).iloc[:168].plot(ylabel="kWh per hour interval",title="Hourly response comparison"); plt.show()
'''),
('Retain the interpretation evidence', 'An accepted model passes its declared checks; predictive accuracy requires independent observations. Preserve run IDs, climate identity and assumptions when sharing a comparison.', '''
evidence={"weather_sha256":b.climate.weather_sha256,"input_hash":b.physical_hash(),"runs":{name:r.run_id for name,r in results.items()},"interpretation":"Illustrative sensitivity only; no measured-energy calibration"}
(OUT/"comparison-evidence.json").write_text(json.dumps(evidence,indent=2))
table(evidence)
assert all(r.diagnostics["accepted"] for r in results.values())
''')], needs=ENGINE, lesson='Use sensitivity to prioritize uncertain inputs and modelling detail. It does not prove that one geometry or operations assumption is correct for an observed building.')

nb('01_geometry','08_real_footprint_corpus_review','Real-footprint corpus review and acceptance',
   'Review a small deterministic cross-municipality sample and make geometry acceptance part of the diversity report.', [
('Select a documented corpus sample', 'Select the first two fixture files per municipality in sorted order. This makes the sample reproducible but not statistically representative. The source fixture describes whether the outline is a roof-edge proxy.', '''
from shapely.geometry import shape
from shapely.affinity import translate
sample=[]
for municipality in ["0181","1480","2584"]:
    for path in sorted((ROOT/"tests/fixtures/footprints").glob(municipality+"-*.json"))[:2]:
        payload=json.loads(path.read_text())
        sample.append((path,payload))
table([{ "fixture":p.name,"municipality":d["municipality"],"stratum":d["selection_stratum"],"outline":d["insamlingslage"]} for p,d in sample])
'''),
('Review preparation without hiding failures', 'Run preparation on the source metric polygons. Display each shape in its own local plotting frame, preserving dimensions. Only accepted preparations are used for extrusion.', '''
rows=[]; gallery={}; accepted=[]
for path,data in sample:
    raw=shape(data["source_geometry"])
    result=prepare_geometry(raw,GeometryPolicy())
    rows.append({"fixture":path.name,"status":result.status,"area_m2":raw.area,"reasons":str(result.reasons)})
    x,y,_,_=raw.bounds
    gallery[path.stem[:13]]=translate(raw,xoff=-x,yoff=-y)
    if result.status=="accepted":
        accepted.append(GeometrySpec.from_footprint(result.cleaned_geometry,storeys=3,storey_height_m=3,source_crs="EPSG:3006",height_status="assumed",outline_kind="roof_edge_proxy",outline_reviewed=False))
plans(gallery,"Six real metric outlines, individually translated for plotting")
frame=table(rows)
bars(frame.status.value_counts().to_dict(),"source records","Preparation decisions")
assert len(rows)==6
'''),
('Inspect one accepted shape', 'The three storeys are an explicit teaching assumption. An accepted planar outline does not validate height, facade offset or energy inputs.', '''
assert accepted, "No accepted sample; inspect preparation decisions"
g=accepted[0]
preview(g,"Real outline, assumed height")
assert len(g.footprints)==len(g.parts)
reference=Footprint.l_shape(30,30,15,15).scaled_to_area(600)
assert np.isclose(reference.area_m2,600)
table({"synthetic_reference_area_m2":reference.area_m2,"synthetic_reference_perimeter_m":reference.perimeter_m,"real_conditioned_volume_m3":g.conditioned_volume_m3})
''')], lesson='Preserve source IDs and rejection counts. Scaling synthetic forms to a common area is useful for controlled sensitivity; do not silently rescale measured footprint geometry.')
nb('05_renovation','04_measure_interactions','Why renovation savings are not additive',
   'Run a four-case experiment to distinguish independent measure savings from a combined package response.', [
('Define a matched factorial experiment', 'All cases share weather, geometry and use. Insulation and glazing are applied individually and then together with dated audit records.', '''
b=building()
insulation=AddInsulation(element="wall",layer=b.envelope.wall.layers[0].updated(thickness_m=.1))
glazing=ReplaceGlazing(glazing=GlazingSpec(u_value_w_m2k=1.1,solar_heat_gain_coefficient=.5))
a=apply_renovation(b,insulation,effective_date="2026-01-01")
g=apply_renovation(b,glazing,effective_date="2026-01-01")
ab=apply_renovation(a,glazing,effective_date="2026-01-02")
cases={"baseline":b,"insulation":a,"glazing":g,"combined":ab}
table([{ "case":name,"wall_U_W_m2K":s.envelope.wall.u_value_w_m2k,"glazing_U_W_m2K":s.facade.glazing.u_value_w_m2k} for name,s in cases.items()])
'''),
('Run the four real cases', 'The model resolves interactions through its thermal calculation. No assumption of additivity is made before running.', '''
results={name:EnergyPlusRunner(engine()).run(spec,OUT/name) for name,spec in cases.items()}
heating=pd.Series({name:r.scalars["space_heating_demand_kwh"] for name,r in results.items()})
bars(heating.to_dict(),"kWh/year","Four-case heating comparison")
'''),
('Quantify the interaction', 'Compare the actual combined saving with the sum of individual savings. A small interaction in this one case is not a guarantee for other climates, controls or envelopes.', '''
individual=(heating.baseline-heating.insulation)+(heating.baseline-heating.glazing)
combined=heating.baseline-heating.combined
bars({"sum of individual savings":individual,"actual combined saving":combined},"kWh/year","Savings additivity check")
table({"interaction_kwh":combined-individual,"definition":"combined saving minus sum of individual savings"})
assert len(ab.renovations)==2 and len(b.renovations)==0
''')], needs=ENGINE, lesson='Use matched factorial comparisons for a few important assumptions before extrapolating package effects across a stock.')

(ROOT/'demo/catalogue.json').write_text(json.dumps(CATALOG,indent=2)+'\n')
assert len(CATALOG)==38, len(CATALOG)
print(f"Catalogue contains {len(CATALOG)} notebooks; existing notebooks preserved")
