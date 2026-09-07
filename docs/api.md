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
from epsm_core import synthetic_context, CompilerSettings, EnergyPlusRunner

context = synthetic_context(geometry, preset="urban_lowrise_dense", seed=17)
settings = CompilerSettings(shadow_max_figures=10_000_000)
# building = building.updated(context=context)
# result = EnergyPlusRunner(energyplus="/path/to/energyplus", settings=settings).run(
#     building, "output/run"
# )
```

A run directory must be empty. Failures retain diagnostics and model artifacts. `result.scalars` contains thermal demand and runtime/geometry counts; `result.hourly` retains requested signals with units and the validated calendar. `result.diagnostics["zoning"]` exposes procedural substitution.

`geometry.view(..., facade=..., context=...)` and `building.view(...)` use the geometry-only viewer. Their returned handle is a context manager; closing it stops the local server. Inspection scene artifacts are not EnergyPlus simulation inputs. Compile explicitly when engine preflight is required.

```python
# Uses the geometry and resolved context created above; no weather or engine required.
with geometry.view("output/preview", context=context) as viewer:
    print(viewer.url)
    input("Press Enter to stop the preview. ")
```

See the [viewer screenshot and controls](usage.md#start-with-geometry), [resolved zoning plans](geometry.md#roofs-and-thermal-zoning) and [context gallery](geometry.md#surrounding-buildings). Context surfaces report `building_id`, `footprint_index` and `surface_type` so selecting a roof cap identifies the neighbour it belongs to. Viewer cutaways change only the display.

CLI operations are `schema`, `validate`, `compile`, `run`, `view` and `export-idf`. The global `--shadow-max-figures` flag configures compilation, and `--energyplus` selects the executable. `view` displays an existing compiled epJSON; Python geometry inspection also works before a complete building specification exists.
