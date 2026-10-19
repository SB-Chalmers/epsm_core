# API guide

There is one current immutable `BuildingSpec` and one generated JSON Schema. Inputs reject unknown fields, nonfinite values and invalid geometry. Use `.updated(...)` for a validated replacement; direct `model_copy(update=...)` does not validate changes.

The package version is `0.7.0`. Simulation identity combines input content, recursive compiler sources, compiler settings, engine/schema and geometry-backend identities. The [physical Building API](physical-building.md) adds gradual authoring and explicit snapshot schema `epsm.building/8`, including declared auxiliary-zone controls and attic outdoor exchange; the existing complete `BuildingSpec` remains the numerical migration contract.

## Responsibilities

| Interface | Responsibility |
| --- | --- |
| `BuildingSpec` | Geometry, facade, climate, envelope, use, airflow, context, delivery and provenance |
| `ResolvedBuildingInput` | Immutable, engine-independent physical view of resolved inputs |
| `GainPartitionSpec` | Explicit or legacy people, equipment and lighting heat-channel fractions |
| `GeometrySpec` | Parts, storeys, zoning, roof defaults, basement and coordinate metadata |
| `ZoningSpec` | Mode, perimeter depth, apartment controls and explicit failure policy |
| `RoofSpec` | Roof geometry and attic topology; optional per-part replacement |
| `FacadeSpec` | Default glazing, window layout, WWR, overrides and attached shading |
| `ContextSpec` | Explicit neighbouring buildings, generation metadata and bounded small-cap preparation (`simplify_small_caps=False` retains exact outlines) |
| `CompilerSettings` | Engine controls such as maximum shadow figures |
| `BuildingBuilder` | Bundled Sveby or caller-owned assumptions merged with known observations |
| `SvebyResidentialSpec` | Versioned residential normal-use values, mappings and completion-default disclosure |
| `EnergyPlusCompiler` / `EnergyPlusRunner` | Validated model output / isolated simulation |
| `preflight_energyplus` | Read-only EnergyPlus geometry readiness for a `BuildingSpec` |
| `resolve_building` | Resolve an existing complete `BuildingSpec` without engine or weather-file I/O |
| `quantity_takeoff` | Physical material/equipment quantities, excluding virtual zoning and context |

Definitions live in focused `epsm_core.specs` domain modules and are re-exported from `epsm_core`. Importing them does not load a registry or contact a service.

`building.resolve(weather)` adapts a fully authored physical Building to the same
read-only view. `resolve_building(spec)` is the advanced path for an existing
complete `BuildingSpec`; its climate metadata is already part of the spec, so
resolution does not require an EnergyPlus installation or read an EPW file. Both
paths return `ResolvedBuildingInput`, schema `epsm.resolved_building/1`. See the
[resolved-input guide](physical-building.md#resolved-input-view) for identity,
geometry, climate context, ownership and export semantics. The view exposes the
supplied climate metadata without reading its weather path.

## Operational standards

Data’s `select_operating_profile("multi_family", version="2.0")` selects the pinned residential definition; Core’s `resolve_operating_profile` converts loaded values. `BuildingBuilder()` has no profile by default; set `building_use="residential"` to select the current bundled profile. The standard supplies operational leaves only, so weather, fabric, leakage, ventilation topology and installed-system performance remain explicit inputs.

The explicit residential profile contains separately labelled completion defaults for occupant density and cooling availability. It also retains requirements the current compiler cannot emit, rather than silently changing them. See the [operational-standards contract](standards.md) for source mappings, Atemp handling, overrides, provenance and the compliance boundary.

`UseSpec.gain_partitions` accepts the exported `GainPartitionSpec`. `None` keeps
the legacy fallback and is identified as `legacy_default` in per-zone gain
diagnostics. Select `policy="epsm_legacy_v1"` to name that behavior explicitly or
`policy="explicit"` to supply custom fractions. Snapshot schema 6 serializes the
selection; older absent or null values preserve the legacy behavior. The
[gain-partition guide](physical-building.md#internal-gain-partitions) documents
the channel definitions and validation budgets.

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

`preflight_energyplus(spec)` checks Kiva floor unions using resolved zones and physical
construction overrides. It needs no EnergyPlus executable or weather-file read; the
compiler retains the same validation before applying Kiva objects.

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
uses one OpenMP thread. Clipping capacity failures remain strict by default. The explicit runner option
`recover_context_shadows=True` enables the separately audited
[context shadow recovery](shadow-recovery.md) policy.
The figure allowance is workspace capacity for the unchanged polygon-clipping calculation;
it was promoted from EnergyPlus's 15,000 default after exact dense-campaign cases exceeded
that default. Exhausting the larger allowance rejects that attempt; optional context recovery
requires a new model and a fully validated simulation.

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

## Ground heat transfer

New envelopes default to `FoundationSpec(method="kiva")`. Soil and footing assumptions remain configurable and reported. Explicit legacy `GroundTemperatureSpec` profiles retain prescribed-temperature behaviour. See [foundation settings and migration](foundations.md).

## Shared hourly gain inputs and raw evidence

`resolve_internal_gains(use, reference_area_m2=..., calendar_year=...)` returns an
immutable `InternalGainSeries` of hourly watts for explicit gain partitions.
Convective and radiant heat are separate from latent, lost and return-air heat.
Visible lighting energy enters the radiant channel. An engine-calculated people
split stays in `unresolved_people_w`; consumers must resolve or reject it.
This pure helper performs no weather or engine I/O.

`SourceRecord.evidence` optionally retains finite JSON source fields, selected
values and derivations. Older records need no new field. Geometry edits invalidate
provenance for geometry and its descendants; copies and snapshots retain evidence.

## Warning acceptance

The runner reviews bounded, known 24.2 psychrometric warnings only after full
output validation. See [warning acceptance](warning-acceptance.md) for scope,
limits, retained evidence and `review_psychrometric_warnings=False` strict opt-out.
