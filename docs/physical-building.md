# Physical Building authoring

`Building()` and `Building.empty()` create an unpopulated authoring draft. Select
`Building(preset="illustrative-reference")` to request the named illustrative
preset: a 20 × 12 m, three-storey building with 2.8 m storeys, 20% glazing,
explicit Data reference constructions/HVAC and the sourced Sveby residential
operation factory. The reference is illustrative, not calibrated building
evidence. Its embodied factors are unknown. The version-2 preset also names its
uncalibrated EnergyPlus Kiva soil and boundary assumptions in its provenance.
`from_footprint(...)` starts from geometry and accepts explicit `construction_set`,
`facade`, `hvac`, `operation`, `foundation` and `ground_temperature` arguments.

## Ownership and editing

Core uses the actual lightweight `epsm_data` Material, Layer, Component, Element
and ConstructionSet classes. No catalogue is loaded by importing either package.
Data owns the four sourced operational JSON records and generic-use assumptions;
Core retains numerical schedule and UseSpec factories for compatibility.

A Core `BuildingElement` is a physical instance with ID, area and construction.
A Data `Element` is its reusable construction definition. Thermal zones and
surface subdivisions are derived and do not own installed material quantities.

Building field assignments validate their own types. Missing data can be filled
incrementally; `readiness('geometry'|'quantities'|'energy'|'lca', engine=...)`
reports requirements. Construction assignment makes an independent graph copy.
Shared construction definitions are immutable; use `with_changes()` to derive new
definitions. `assign_construction(..., element_ids=(...))` edits selected instances.
Assigned operations remain `OperationProfile` objects, including after copying or
restoring a snapshot; `building.operation.with_changes(...)` validates replacements.
Domain representations show only loaded scalar metadata and collection counts,
stay on one line within 160 characters, and perform no calculation or I/O. Full
data remain available through the object's attributes and explicit inspection.
The building ConstructionSet provides role defaults; each physical element holds
its actual assignment, including targeted renovation overrides.
Geometry remains authoritative for thermal areas and locations. Manually edited
physical element metadata can be inspected and used for quantities, but energy
readiness rejects metadata that differs from the generated geometry. Change the
geometry or facade configuration to change thermal areas; construction-only
overrides remain supported. Explicit zero-window facade overrides are preserved
when assigning per-window thermal properties.

Ground heat transfer is authoring input too. A draft has no foundation method or
ground temperatures, and energy readiness reports the missing fields. Kiva requires
an explicit method, source, soil conductivity/density/heat capacity, wall heights,
exposed-perimeter fraction, deep-boundary choice/depth and far-field width. If a
footing material is supplied, footing depth and width must also be explicit. The
prescribed-temperature method requires an explicit method and twelve monthly values
with a source. Omitted FoundationSpec defaults remain useful as validated value
defaults, but do not count as authored inputs. The named illustrative preset supplies
the documented EnergyPlus 24.2 Kiva values explicitly; they are not site measurements.

```python
from epsm_core import Building, Footprint, FoundationSpec

building = Building.from_footprint(
    Footprint.rectangle(10, 8),
    storeys=2,
    storey_height_m=3,
    foundation=FoundationSpec(
        method="kiva",
        source="study-soil-report-v1",
        soil_conductivity_w_mk=1.6,
        soil_density_kg_m3=1800,
        soil_specific_heat_j_kgk=900,
        exposed_perimeter_fraction=0.75,
        wall_height_above_grade_m=0.2,
        wall_depth_below_slab_m=0.1,
        deep_ground_boundary="ZeroFlux",
        deep_ground_depth_m=30,
        far_field_width_m=25,
    ),
)
```

## Quantities and ordered interventions

`building.quantities()` returns an iterable MaterialInventory with `by_material()`
and `to_dict()`. Material leaves retain their source identity and installed
occurrence ID. Parallel shares use each material's fraction and thickness. Windows
provide known area, and explicit HVAC equipment provides counts; absent masses are
`None`. Element/component aggregate values are not additional inventory rows.

```python
from epsm_core import Building
from epsm_data import ConstructionOperation, RenovationMeasure, SystemOperation
from epsm_data import reference_hvac_template
from epsm_data.domain.enums import BuildingElement as Role

building = Building(preset="illustrative-reference")
wall = next(e for e in building.elements if e.role == Role.EXT_WALL)
replacement = RenovationMeasure(
    'wall.replace', 'envelope', 'Replace wall', 'Illustrative replacement', 'wall',
    operations=(ConstructionOperation('replace_element', Role.EXT_WALL,
                                       element=wall.construction),),
    target_element_ids=(wall.identifier,),
)
child = building.renovate(replacement)
next_child = child.renovate(SystemOperation('replace_hvac', reference_hvac_template()))
assert not building.stages
assert len(next_child.stages) == 2
```

All measures in one call form a transaction: failure leaves the source unchanged.
The returned child preserves the subclass and starts with empty application result
history. Like-for-like replacement installs new occurrences and removes old ones.
Unchanged occurrences remain retained. Stages have IDs/order, before/after snapshots
and material flows, without dates; assessment settings own elapsed time and horizon.
Catalogue prerequisites must appear in an earlier stage or earlier in the same
bundle. Duplicate bundle IDs and incompatible measures anywhere in the selected
path are rejected before application; recorded incompatibilities survive reload.
Direct authoring assignments describe state; use renovation operations when a
physical intervention must appear in lifecycle flows.

## Snapshots, lineage and execution

`snapshot()` stores canonical immutable JSON, including the explicitly selected
preset revision and provenance, resolved construction values, occurrence identities
and only the authored ground fields. New snapshots use `epsm.building/3`; `.sha256` identifies the stored
state. `.to_dict()` returns a detached copy; `.to_building()` returns an editable
independent building. Runtime results and evaluation settings are excluded.
Version-1 and version-2 snapshots remain readable and retain their original hash
while their restored state is unchanged. Missing ground inputs stay missing when an
older snapshot is restored. Editing a restored legacy building writes the new
snapshot format without resolving the preset again. Ordered history is separately
saved/restored with `lineage_to_dict()` and `restore_lineage()`.

Authoring edits remain possible after a renovation. `building.authoring_links`
retains before/after snapshots for edits between stages and for the current draft,
without adding renovation stages or rewriting the original material flows. A
schedule or naming edit has no material-history requirement. An edit to installed
identities or quantities appears in `building.material_history_requirements`;
assessment must report these unresolved changes as incomplete. Resolve physical
interventions with `renovate()` from the last established state, or revise the
baseline and derive the alternatives again. Both links and requirements are
included in lineage serialization and checked on restoration.

Weather is explicit: `Weather.from_epw(path)` captures the content fingerprint and
calendar. A single full-year AMY `DATA PERIODS` header with explicit dates selects
that year, including leap years. Undated or composite TMY periods use 2023;
`calendar_year=...` explicitly selects another calendar. Source row years alone
do not identify an AMY. The legacy `climate_from_epw()` retains its explicit 2023
default for existing callers.

Keep weather reconstruction evidence with the calculation. For example, after
generating weather with `smhi2epw` (a separate installation requiring provider
access), import its receipt explicitly:

```python
from epsm_core import Weather
from smhi2epw import EPWConfig, compile_epw

generated = compile_epw(EPWConfig(
    year=2024, output_path="gothenburg.epw", station_id=71420,
    provenance_path="gothenburg.epw.json",
))
weather = Weather.from_epw(
    generated.output_path, provenance_path="gothenburg.epw.json",
)
weather.validate()
print(weather.provenance["result"]["report"])
```

The receipt must identify the same EPW SHA-256. Its full source and quality
metadata are copied into `Weather`, survive `to_dict()`/`from_dict()`, and remain
independent of later edits to the receipt or returned dictionaries. Generic
metadata can be supplied as `provenance={...}`. Core does not fetch weather or
discover sidecars automatically. A complete calendar and preserved quality
report do not establish local weather accuracy.

`run_building(building, weather=weather, directory=...)` validates weather,
captures a snapshot, compiles and executes the existing EnergyPlus implementation.
`building.to_spec(weather)` exposes the migration bridge. Targeted opaque changes
reach thermal faces/internal slabs through bounded construction overrides; nominal
physical inventory continues to use the original Data materials. Parallel thermal
layers are reduced only within the engine adapter.

## Current adapter limits

The new automatically generated physical inventory supports detached flat compact
footprint columns, storeys, windows and basements. Attached parts, party walls,
pitched roofs, generated apartment partitions, and outlines changed by automatic
cleanup require further physical-ownership adapters. Readiness reports these gaps;
the pre-existing complete geometry/numerical APIs remain available. Thermal
reduction currently requires equal parallel path depths and at most ten emitted
layers per assembly. RC has additional single-conditioned-domain/shading limits.
Layered window recipes remain available for material inventory; the current
thermal bridge requires whole-window U-value, SHGC and visible transmittance
through `WindowElement`, and readiness reports layered windows as unsupported.
Unknown nonthermal products and detailed window/equipment material composition
remain explicit inventory gaps; they are never invented from U-values or counts.

## Development installation

This release requires `epsm_data >= 0.4.0`.
Install Data first, then Core (`pip install -e ../epsm_data -e '.[dev,geometry]'`).
The development CI checks out Data's `codex/harmonisation` branch. Configure the
`EPSM_DATA_DEPLOY_KEY` Actions secret containing a read-only SSH deploy key scoped
to that private repository; CI
fails explicitly before testing if the secret is absent. Switch to
the published dependency when the coordinated release is available.

## Consumer migration after explicit presets

Core now leaves `Building()` and `BuildingBuilder()` unconfigured. Callers that
intend the illustrative model must select
`Building(preset="illustrative-reference")`; callers that intend residential
Sveby assumptions must select `BuildingBuilder(building_use="residential")`.
RC, LCA and Workflows examples and tests using the former no-argument defaults
need that explicit selection when upgrading Core. Those consumer changes and
installed cross-package checks are separate from this Core change; they have
not been claimed as passing here.
