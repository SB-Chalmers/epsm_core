# API guide

There is one current immutable `BuildingSpec` and one generated JSON Schema. Inputs reject unknown fields, nonfinite values and invalid geometry. Use `.updated(...)` for a validated replacement; direct `model_copy(update=...)` does not validate changes.

The development package version is `0.1.0.dev0`. Simulation identity combines input content, recursive compiler sources, compiler settings, engine/schema and geometry-backend identities. Routine implementation changes do not require package-version bumps. The provisional numeric building-schema field has been removed; old experimental payloads must be regenerated against the current API.

## Responsibilities

| Interface | Responsibility |
| --- | --- |
| `BuildingSpec` | Geometry, facade, climate, envelope, use, airflow, context, delivery and provenance |
| `GeometrySpec` | Parts, storeys, zoning, roof defaults, basement and coordinate metadata |
| `ZoningSpec` | Mode, perimeter depth, apartment controls and explicit failure policy |
| `RoofSpec` | Roof geometry and attic topology; optional per-part replacement |
| `FacadeSpec` | Default glazing, window layout, WWR, overrides and attached shading |
| `ContextSpec` | Explicit resolved neighbouring buildings and generation metadata |
| `CompilerSettings` | Engine controls such as maximum shadow figures |
| `BuildingBuilder` | Caller-owned assumptions merged with known observations |
| `EnergyPlusCompiler` / `EnergyPlusRunner` | Validated model output / isolated simulation |
| `quantity_takeoff` | Physical material/equipment quantities, excluding virtual zoning and context |

Definitions live in focused `epsm_core.specs` domain modules and are re-exported from `epsm_core`. Importing them does not load a registry or contact a service.

## Geometry and facade selection

```python
from epsm_core import Footprint, GeometrySpec, ZoningSpec

geometry = GeometrySpec.from_footprint(
    Footprint.rectangle(30, 20),
    storeys=3, storey_height_m=3,
    height_status="measured",
    zoning=ZoningSpec(mode="perimeter_core", depth_m=4.5),
)
south = [f for f in geometry.facades() if 135 <= f.azimuth_deg < 225]
```

Supply either `storey_elevations_m` or the `storeys`/`storey_height_m` pair. Use explicit `BuildingPart` objects for unequal-height wings. Directions from the catalog already account for scene orientation; resolve selections to IDs instead of introducing another override-precedence mechanism.

```python
from epsm_core import FacadeOverride, WindowLayoutSpec

# building is an existing BuildingSpec.
# building = building.updated(facade=building.facade.updated(
#     layout=WindowLayoutSpec(mode="wwr"),
#     overrides=(FacadeOverride(facade_id=south[0].facade_id, wwr=0.3),),
# ))
```

## Context and compilation

```python
from epsm_core import synthetic_context, CompilerSettings, HourlyOutputRequest, EnergyPlusRunner

context = synthetic_context(geometry, preset="urban_lowrise_dense", seed=17)
settings = CompilerSettings(hourly_outputs=(
    HourlyOutputRequest(name="Site Outdoor Air Drybulb Temperature"),
))
# building = building.updated(context=context)
# result = EnergyPlusRunner(energyplus="/path/to/energyplus", settings=settings).run(
#     building, "output/run"
# )
```

A run directory must be empty. Failures retain diagnostics and model artifacts. `result.scalars` contains thermal demand and runtime/geometry counts; `result.hourly` retains requested signals with units and the validated calendar. `result.diagnostics["zoning"]` exposes procedural substitution.

`HourlyOutputRequest(name, key="*")` adds hourly variables. Names and keys are trimmed,
normalized to uppercase, deduplicated and sorted for deterministic run identity. Use
specific keys for surface variables to limit SQL size. Missing requested outputs fail
result validation. Core outputs always include hourly supply-air heating/cooling energy,
DHW energy, zone mean temperature and enclosure transmitted solar, plus monthly and
RunPeriod energy/solar totals. Hourly energy also supplies hourly-average load peaks.
Supply-air thermal demand and zone-total energy retain distinct meanings.

Production uses SQLite `Simple`, with no AllSummary, variable dictionary or automatic
preview. Surface conduction is validation-only; the ground-transfer scalar is available
only when complete conduction evidence was explicitly requested. Use explicit viewer
APIs for inspection. Campaign sampling, storage and validation outputs belong in orchestration.

`geometry.view(..., facade=..., context=...)` and `building.view(...)` use the geometry-only viewer. Their returned handle is a context manager; closing it stops the local server. Inspection scene artifacts are not EnergyPlus simulation inputs. Compile explicitly when engine preflight is required.

```python
# Uses the geometry and resolved context created above; no weather or engine required.
with geometry.view("output/preview", context=context) as viewer:
    print(viewer.url)
    input("Press Enter to stop the preview. ")
```

See the [viewer screenshot and controls](usage.md#start-with-geometry), [resolved zoning plans](geometry.md#roofs-and-thermal-zoning) and [context gallery](geometry.md#surrounding-buildings). Context surfaces report `building_id`, `footprint_index` and `surface_type` so selecting a roof cap identifies the neighbour it belongs to. Viewer cutaways change only the display.

CLI operations are `schema`, `validate`, `compile`, `run`, `view` and `export-idf`.
`--energyplus` selects the executable. `view` displays an existing compiled epJSON;
Python geometry inspection also works before a complete building specification exists.


### Annual UBEM fidelity and migration

The core supports Ideal Loads with hourly schedules. Detailed HVAC and fast controls
need separate validation. The production timestep remains **six per hour**: four
failed the agreed 0.1°C maximum hourly-average temperature-difference criterion.
CTF, FullExterior, PolygonClipping/SutherlandHodgman, Periodic/20 days,
SimpleSkyDiffuseModeling, 1,000,000 figures and minimum/maximum warmup days 1/25 are explicit.
Convergence tolerances remain 0.04 loads and 0.4°C temperature. Each simulation process
uses one OpenMP thread. Clipping capacity failures never trigger geometry changes or retries.
The figure allowance is workspace capacity for the unchanged polygon-clipping calculation;
it was promoted from EnergyPlus's 15,000 default after exact dense-campaign cases exceeded
that default. Exhausting the larger allowance remains a strict failure.

This is an intentional pre-1.0 API break. Removed controls are `shadow_max_figures`,
`reporting_profile`, `diagnostic_policy`, `shadow_geometry_recovery`, the CLI
`--shadow-max-figures` flag, and runner `create_preview`. Weather-specific warning
policies belong upstream. Severe errors, geometry repairs, shadow limits and unapproved
warnings always fail. See `benchmarks/optimization.py` for isolated private experiments.

Weather preflight verifies the complete hourly calendar and required temperature,
humidity, pressure, solar and wind fields, and rejects missing-value sentinels.
Limits follow the pinned [EnergyPlus 24.2 EPW data dictionary](https://bigladdersoftware.com/epx/docs/24-2/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html).
Site coordinates must match the EPW header. No climate-specific substitution is applied.

Run identity binds the actual serialized model to the compiler, engine, schema,
weather and normalized inputs. `compiler.run_id(spec)` therefore compiles and validates
the specification; use `report.run_id` when a compilation report already exists.
