# Learn EPSM Core through building-stock diversity

The 38 notebooks in these 11 folders explain how to describe, inspect and simulate diverse buildings with the current API. Start with one building, then choose the themes where your source data or modelling assumptions vary most. Both `03_` folders are intentional: constructions and operations are separate themes.

![The building modelling workflow](../docs/figures/workflow.svg)

Read the figure from top to bottom. `GeometrySpec` can be inspected before weather or energy inputs exist. A complete `BuildingSpec` then supplies envelope, climate and operations; compilation resolves engine objects, and a run produces validated thermal results. Each reference figure has one owning lesson; other lessons link to it. Original thematic diagrams explain component ownership, and computed plots provide example-specific evidence.

## Environment and inputs

The dedicated `.venv-demo` is separate from the older `.venv`. The current demo environment uses Python 3.12; the package requires Python 3.11 or newer. If setting up a fresh checkout, run from the repository root:

```sh
python3 -m venv .venv-demo
.venv-demo/bin/python -m pip install -r requirements.txt
.venv-demo/bin/python -m pip install '/path/to/epsm_viewer-<version>-py3-none-any.whl[notebook]'
.venv-demo/bin/python -m pip check
.venv-demo/bin/python -m ipykernel install --prefix .venv-demo --name epsm-core-demo --display-name 'EPSM Core Demo'
.venv-demo/bin/python -m jupyterlab
```

Choose **EPSM Core Demo** in JupyterLab. In VS Code, select `.venv-demo/bin/python` as the notebook kernel. Run a notebook from a fresh kernel, starting at its setup cell. The setup creates a unique output directory beneath `output/demo/`, so separately executed lessons do not share hidden state or overwrite one another's runs.

Replace the wheel path with the actual built `epsm_viewer` wheel. It is a separate
optional package, not part of Core's notebook extra or assumed available on a
package index. Interactive lessons and `preview(..., interactive=True)` require
it; a missing dependency raises an error. `preview(..., interactive=False)` uses
Core scene data and Matplotlib only. See [viewer migration](../docs/viewer-migration.md).

Geometry-only lessons need no EnergyPlus executable or EPW. Lessons tagged with weather use explicit local files; simulation lessons additionally require **EnergyPlus 24.2** and its adjacent schema. Set `ENERGYPLUS_EXE` to the executable and `EPSM_WEATHER_DIR` to your weather directory if needed. The demo helpers also recognize the existing repository weather folder and the documented local OpenStudio EnergyPlus location. No notebook downloads or fabricates weather.

The climate comparisons use these exact example files:

- `SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw`
- `SWE_SN_Malmo.AP-Sturup.026360_TMYx.2004-2018.epw`
- `SWE_NB_Kiruna.AP.020440_TMYx.2004-2018.epw`

## How to read the notebooks

Each lesson has an API explanation and reading notes. The facade lesson walks through complete BuildingSpec construction, validated nested updates, override precedence and resolved elevations. Read input tables before interpreting plots. Follow assertions as checks of specific contracts, such as preserved area or annual/hourly energy agreement; they do not prove calibration against measured buildings.

`building()` and `geometry()` are input factories in [the demo helpers](support/common.py), not universal package defaults. `table()`, `plans()`, `bars()` and `preview()` are presentation aids. The public package calls remain visible in the lesson cells. `preview()` displays a static figure and normally an embedded widget; use `epsm_viewer.scene_widget(value.scene())` directly when you want to manage the interactive handle yourself.

Static documentation screenshots explain controls and model representations. They are not live widgets or new simulation results. The context and zoning sensitivity figures come from a separate retained experiment; captions link to its assumptions and run data. Compare their interpretation method with the notebook experiment rather than expecting identical numerical values.

The examples deliberately exercise diversity without claiming national representativeness. Demonstration constructions, daily schedules, climate selections and population weights need independent justification before national extrapolation. `DistrictPlan` is a small-district helper, not national spatial ingestion or orchestration.

## Learning path

Start with the environment check and first building. Geometry lessons can then be explored independently. Constructions, schedules, weather and systems explain what must be attached to a full building; renovation and results lessons compare those inputs. Finish with the diversity matrix and capstone.

### 00_quickstart

- [Environment and learning map](00_quickstart/01_environment_and_learning_map.ipynb) — no engine or weather.
- [One building, from assumptions to results](00_quickstart/02_first_building_to_results.ipynb) — local EPW, EnergyPlus 24.2.

### 01_geometry

- [Footprint diversity and explicit preparation](01_geometry/01_footprint_diversity_and_preparation.ipynb) — no engine or weather.
- [Massing, storeys, basements and party walls](01_geometry/02_massing_storeys_basements_and_party_walls.ipynb) — no engine or weather.
- [Thermal zoning and preserved quantities](01_geometry/03_thermal_zoning.ipynb) — no engine or weather.
- [Roofs, attics and straight skeleton](01_geometry/04_roofs_and_straight_skeleton.ipynb) — no engine or weather.
- [Facades, windows and attached shading](01_geometry/05_facades_windows_and_shading.ipynb) — no engine or weather.
- [Experimental apartment layouts](01_geometry/06_experimental_apartment_layouts.ipynb) — local EPW.
- [Neighbourhood context and solar access](01_geometry/07_neighbourhood_context.ipynb) — no engine or weather.
- [Real-footprint corpus review and acceptance](01_geometry/08_real_footprint_corpus_review.ipynb) — no engine or weather.

### 02_weather

- [EPW metadata and the simulation calendar](02_weather/01_epw_metadata_and_calendar.ipynb) — local EPW.
- [Swedish climate diversity](02_weather/02_swedish_climate_diversity.ipynb) — local EPW.
- [Climate and ground-temperature sensitivity](02_weather/03_climate_and_ground_sensitivity.ipynb) — local EPW, EnergyPlus 24.2.

### 03_construction

- [Materials, layers and envelope roles](03_construction/01_materials_layers_and_envelopes.ipynb) — no engine or weather.
- [Glazing performance and thermal mass](03_construction/02_glazing_and_thermal_mass.ipynb) — local EPW, EnergyPlus 24.2.
- [Physical quantity takeoff](03_construction/03_physical_quantity_takeoff.ipynb) — local EPW.

### 03_schedule_and_occupancy

- [Daily schedules and annual calendars](03_schedule_and_occupancy/01_schedules_and_calendars.ipynb) — no engine or weather.
- [Occupancy, gains, setpoints and DHW](03_schedule_and_occupancy/02_occupancy_gains_setpoints_and_dhw.ipynb) — local EPW, EnergyPlus 24.2.
- [Dwelling and common-space operations](03_schedule_and_occupancy/03_dwelling_and_common_space_operations.ipynb) — local EPW, EnergyPlus 24.2.

### 04_systems

- [Airflow and sensible heat recovery](04_systems/01_airflow_and_heat_recovery.ipynb) — local EPW, EnergyPlus 24.2.
- [Delivery and exhaust-air heat pumps](04_systems/02_delivery_and_exhaust_air_heat_pumps.ipynb) — local EPW, EnergyPlus 24.2.
- [PVWatts generation from explicit PV inputs](04_systems/03_photovoltaics.ipynb) — local EPW, PySAM.

### 05_renovation

- [Individual renovation measures](05_renovation/01_individual_measures.ipynb) — local EPW.
- [Renovation packages across contrasting buildings](05_renovation/02_packages_and_building_diversity.ipynb) — local EPW, EnergyPlus 24.2.
- [Renovation provenance and quantity changes](05_renovation/03_provenance_and_quantity_changes.ipynb) — local EPW.
- [Why renovation savings are not additive](05_renovation/04_measure_interactions.ipynb) — local EPW, EnergyPlus 24.2.

### 06_io

- [Specifications, schema and JSON roundtrips](06_io/01_specifications_schema_and_roundtrips.ipynb) — local EPW.
- [Compilation reports and engine exports](06_io/02_compilation_and_engine_exports.ipynb) — local EPW, EnergyPlus 24.2.
- [Execution artifacts and failure evidence](06_io/03_execution_artifacts_and_failures.ipynb) — local EPW, EnergyPlus 24.2.

### 07_visualise

- [Embedded 3D geometry widget](07_visualise/01_embedded_geometry_widget.ipynb) — no engine or weather.
- [Inspect actual compiled surfaces](07_visualise/02_compiled_model_inspection.ipynb) — local EPW, EnergyPlus 24.2.
- [Independent comparative geometry review](07_visualise/03_comparative_geometry_review.ipynb) — no engine or weather.

### 08_batch

- [District context and bounded parallel runs](08_batch/01_district_context_and_parallel_runs.ipynb) — local EPW, EnergyPlus 24.2.
- [A building-stock diversity matrix](08_batch/02_building_stock_diversity_matrix.ipynb) — local EPW.
- [Diversity capstone: six buildings and matched retrofits](08_batch/03_diversity_capstone.ipynb) — local EPW, EnergyPlus 24.2.

### 09_results

- [Scalars, hourly signals and units](09_results/01_scalars_hourly_signals_and_units.ipynb) — local EPW, EnergyPlus 24.2.
- [Comparisons and illustrative stock aggregation](09_results/02_comparisons_and_aggregation.ipynb) — local EPW, EnergyPlus 24.2.
- [Quality, sensitivity and interpretation](09_results/03_quality_sensitivity_and_interpretation.ipynb) — local EPW, EnergyPlus 24.2.

## Editing and figure sources

Edit the notebooks directly; their code comments, additional cells and saved outputs are retained. `scripts/build_demo_notebooks.py` now scaffolds missing notebooks only and does not replace existing notebooks. `scripts/enrich_demo_notebooks.py` updates only its tagged teaching cells; other Markdown, code, comments and outputs remain editable. It includes a few explicit corrections to misleading older comments about demo defaults and geometry-policy units.

The figure files remain in `docs/figures/` and are linked relatively, so keep the repository structure when opening notebooks. Every inserted figure has a source link, a descriptive caption and instructions for reading it. See the [usage guide](../docs/usage.md), [geometry contract](../docs/geometry.md) and [architecture](../docs/architecture.md) for the underlying explanations and figure-generation instructions.

The review adds explanations without rerunning or replacing your saved simulation outputs. For an explicit fresh-kernel execution of a selected lesson, run from the repository root:

```sh
.venv-demo/bin/python scripts/execute_demo_notebooks.py '01_geometry/01_footprint_diversity_and_preparation.ipynb'
```

Running the executor with no pattern executes the full catalogue and writes its own status report under `output/demo/`. Prerequisite-dependent cells need the real configured inputs; absence of an error in a saved notebook is not proof that its current code has been executed.

## Figure conventions and maintenance

Every chart creates a fresh, explicitly sized figure and closes it after display. Standard charts use 9 × 4 inches, annotated plans 10 × 6, and four-panel comparisons 12 × 8. Footprint galleries wrap at three columns. `plans`, `preview`, `bars` and `flow` accept `figsize` for lesson-specific layouts. `preview()` displays once and returns no widget handle; use `epsm_viewer.scene_widget(b.scene())` to retain a handle.

Notebooks are the editable source of truth. `scripts/build_demo_notebooks.py` only scaffolds missing notebooks. `scripts/enrich_demo_notebooks.py` refreshes tagged explanation cells, links to reference figures outside their owning lesson, and preserves the custom facade lesson. Execute all lessons with `.venv-demo/bin/python scripts/execute_demo_notebooks.py`; inspect `output/demo/execution-report.json` for actual outcomes.
