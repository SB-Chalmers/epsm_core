# Physical Building authoring

`Building()` and `Building.empty()` create an unpopulated authoring draft. Select
`Building(preset="illustrative-reference")` to request the named illustrative
preset: a 20 × 12 m, three-storey building with 2.8 m storeys, 20% glazing,
explicit Data reference constructions/HVAC and the sourced Sveby residential
operation factory. The reference is illustrative, not calibrated building
evidence. Its embodied factors are unknown. The version-5 preset also names its
uncalibrated EnergyPlus Kiva soil and boundary assumptions in its provenance.
`from_footprint(...)` starts from geometry and accepts explicit `construction_set`,
`facade`, `hvac`, `operation`, `foundation`, `ground_temperature` and
`thermal_bridge_uplift_fraction`, `load_reference_area_m2` and
`load_reference_area_policy` arguments.

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

### Assigning resolved inputs together

`building.assign_inputs(...)` updates the draft atomically and returns an
`InputAssignmentReport`. Pass resolved `construction_set`, `operation`, `hvac`,
`thermal_bridge_uplift_fraction` and/or `facade_properties` inputs. Construction
roles without geometric targets are reported as unmatched; no physical elements
are created. Core does not select a catalogue entry or infer a calendar here.

`mode="replace"` replaces supplied roles and sections. Uncovered physical elements
keep their constructions and installed component IDs. `mode="fill_missing"`
fills individual unassigned elements and absent sections, preserving targeted
overrides and configured operation/HVAC. Every supplied value is validated even
when fill-missing would retain an existing choice. Invalid inputs leave the whole
Building unchanged. A completely retained assignment preserves snapshot identity.
Known operation/HVAC contradictions, including supply temperatures and FVP
topology/leakage/continuous-exhaust constraints, are checked against the effective
retained and supplied inputs. Calendar and complete geometry checks remain part
of simulation preparation and do not require invented weather or project dates.

```python
from epsm_core import Building, Footprint

reference = Building(preset="illustrative-reference")
building = Building.from_footprint(
    Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
    facade=reference.facade,  # caller explicitly selects opening geometry
)
report = building.assign_inputs(
    construction_set=reference.construction_set,
    operation=reference.operation,
    mode="fill_missing",
)
print(report.to_dict())
print(building.readiness())  # HVAC, ground, bridge and load-area choices remain
```

`facade_properties` accepts only `glazing` and `solar_shading_factor`. Geometry,
WWR, opening placement/layout, orientation and context stay unchanged. An absent
facade stays missing and properties are reported unmatched. Explicit glazing
properties update applicable actual `WindowElement` performance as well as facade
defaults, so the engine receives those values. Missing/layered window definitions
remain unchanged and are reported as unmatched physical targets. No whole-window
construction is fabricated; readiness still reports their missing/unsupported
representation.
When constructions and explicit glazing are supplied together, explicit glazing
properties take precedence for actual window performance. Construction-definition
sources and winning glazing-property sources remain separate in provenance.

Optional `provenance={"records": [...]}` accepts `SourceRecord` records for changed
inputs. Partial edits narrow broad construction/facade sources to retain evidence
for untouched fields. Incoming broad sources are attached only to changed paths.
The report contains applied, replaced, retained and unmatched paths; `readiness()`
reports simulation requirements. The operation and report rendering are offline.
Earlier snapshots, renovation stages and material flows stay unchanged. Material
authoring after renovation remains a history requirement rather than an invented
intervention. Single-field assignments and `assign_construction()` remain available.

Use `airflow_properties={...}` for explicit infiltration, ventilation or schedule
patches without replacing the installed HVAC delivery, equipment or topology.
Only known `AirflowSpec` fields are accepted, excluding `topology`; select a new
system through `hvac` when topology must change. `replace` patches supplied leaves
on the retained or same-call supplied system. Source records use paths such as
`hvac.airflow.envelope_infiltration_ach`; untouched delivery/equipment sources are
preserved. Same-call explicit leaf sources take precedence over broad template
sources. Without HVAC, the patch is unmatched and no system is inferred.
`fill_missing` retains every typed-system field, including zero, even when the
system is newly supplied in that call. A model default is not evidence of absence.

### Resolve a complete or incomplete HVAC template

`HVACSystem.resolve_template(template, previous=None)` consumes a loaded Data
`HVACTemplate` with no catalogue or resource reads. It returns immutable
`HVACTemplateResolution`: an optional complete `hvac`, explicit `requirements`,
read-only `values`, source references and notes. `to_dict()` returns a detached
export. Partial templates do not invent topology, leakage or product choices.

Every supplied airflow, delivery, renewables and equipment section is checked
independently before missing inputs are classified. An incomplete airflow cannot
mask invalid heating efficiency, contradictory delivery choices, malformed
equipment or known topology/flow contradictions. Unknown sections/fields are
rejected. A heat-pump carrier without a COP is an explicit requirement rather
than a made-up efficiency.

```python
from epsm_data import HVACTemplate
from epsm_core import HVACSystem

template = HVACTemplate("project:minimum-flow", {
    "airflow": {"mechanical_vent_l_s_m2": 0.35},
})
resolution = HVACSystem.resolve_template(template)
assert resolution.hvac is None
print(resolution.requirements)  # topology and envelope infiltration remain unknown
```

Explicit `previous` fills known system fields while retaining delivery/equipment
not supplied by the template. Heating/FVP definition fields merge within their
own section; schedules remain complete replacements. Equipment records merge by
identifier, and explicitly supplied product definitions create new installed
occurrence IDs unless the caller supplies an occurrence ID. Complete templates
retain the existing `HVACSystem.from_template` behaviour through the same
validation route. That factory raises when unresolved requirements remain; use
`resolve_template` for gradual authoring. Template resolution does not apply
building provenance; `assign_inputs` attaches the selected sources when committing.

The existing geometry-first basement adapter currently labels a basement bottom
`GROUND_FLOOR` when no construction set was supplied during geometry creation.
`assign_inputs` preserves that recorded role and reports a supplied
`BASEMENT_FLOOR` definition as unmatched. It does not relabel geometry or substitute
the ground-floor recipe for a basement-floor recipe. Review the physical roles
before application; correcting the geometry adapter is a separate change.

### Internal-gain partitions

`UseSpec.gain_partitions` selects how people, equipment and lighting gains are
split into EnergyPlus heat channels. Leaving it `None` preserves the historical
fallback and is reported as `legacy_default` in each zone's `gain_partitions`
diagnostic. The named illustrative preset selects `GainPartitionSpec(policy="epsm_legacy_v1")`
explicitly; this reports `selection="policy"` and records the choice as preset
provenance. That policy uses 30% radiant people heat with EnergyPlus determining
the sensible/latent split, caps equipment radiation at 30% of each hour's available
heat, and assigns 30% of lighting input to radiant heat. Equipment latent, lighting
visible and lighting return-air fractions are zero. Older snapshots with the field
absent or null retain the legacy fallback.

For a reviewed custom split, select `policy="explicit"` and provide the channel
fractions. `people_fraction_radiant` is a fraction of sensible people heat;
`people_sensible_heat_fraction=None` leaves that value to EnergyPlus's automatic
calculation. Equipment radiant and latent fractions apply to electrical heat, with
the remainder assigned to convection. Lighting radiant, visible and return-air
fractions leave the remainder convective. Fractions that exceed their heat budget
are rejected: equipment radiant plus latent, and the three lighting fractions, must
each sum to at most one. Explicit equipment budgets must also fit every hour of the
selected heat-fraction schedule; Core does not silently cap them. The legacy
equipment path retains its historical hourly radiant cap.

```python
from epsm_core import GainPartitionSpec

partitions = GainPartitionSpec(
    policy="explicit",
    people_fraction_radiant=0.25,
    people_sensible_heat_fraction=None,  # EnergyPlus auto-calculates it
    equipment_fraction_radiant=0.20,
    equipment_fraction_latent=0.10,
    lighting_fraction_radiant=0.30,
    lighting_fraction_visible=0.20,
    lighting_return_air_fraction=0.10,
)
building.operation = building.operation.with_changes(gain_partitions=partitions)
```

Gain partitions survive `UseSpec` JSON and Building snapshot/copy/renovation
roundtrips. `ProgramBlend` requires a common gain-partition policy; represent
components with different policies as separate zone uses instead of averaging the
channel fractions. The compiled per-zone report includes the effective policy,
selection (`legacy_default`, `policy` or `explicit`), supplied configuration and
channel budget at `report.data["zones"][zone]["gain_partitions"]`.

Ground heat transfer is authoring input too. A draft has no foundation method or
ground temperatures, and energy readiness reports the missing fields. Kiva requires
an explicit method, source, soil conductivity/density/heat capacity, wall heights,
exposed-perimeter fraction, deep-boundary choice/depth and far-field width. If a
footing material is supplied, footing depth and width must also be explicit. The
prescribed-temperature method requires an explicit method and twelve monthly values
with a source. Omitted FoundationSpec defaults remain useful as validated value
defaults, but do not count as authored inputs. The named illustrative preset supplies
the documented EnergyPlus 24.2 Kiva values explicitly; they are not site measurements.

Thermal-bridge uplift is another required energy input. A draft leaves
`thermal_bridge_uplift_fraction` unset. Supply a finite nonnegative fraction; for
example, `0.1` means a ten percent U-value increase for supported envelope roles.
The compiler represents it by changing equivalent conductivities while retaining
layer thickness, density and specific heat, so physical material quantities and
layer heat capacity stay unchanged. The named illustrative preset explicitly supplies
zero and records that assumption in its provenance.

Loads and area-based airflow need one load-reference area choice. Set a finite
positive `load_reference_area_m2`, or select
`load_reference_area_policy="conditioned_floor_area"` to derive it from the current
geometry. The policy follows later geometry edits. A chosen area scales per-area
people, equipment, lighting, DHW and area-based airflow inputs; it does not change
the physical floor area, envelope, volume or material quantities. The illustrative
preset uses the conditioned-floor-area policy. Supplying an explicit area overrides
that preset assumption and removes its stale provenance record. If you set an
explicit policy yourself, clear it before assigning an area.

## Resolved input view

`building.resolve(weather)` returns an immutable `ResolvedBuildingInput` view of a
fully authored physical Building. Resolution requires energy readiness, so it does
not fill missing operation, construction, foundation, thermal-bridge or area inputs.
The input may be an already-loaded `Weather` or `ClimateSpec`; resolving it does not
initialize EnergyPlus or read another weather file. This exported view has its own
schema, `epsm.resolved_building/1`; it does not change the `epsm.building/8`
snapshot format.

```python
resolved = building.resolve(weather)
print(resolved.source_id, resolved.source_snapshot_id)
for surface in resolved.surfaces:
    print(surface["gross_area_m2"], surface["opening_area_m2"], surface["net_area_m2"])

export = resolved.to_dict()  # writable detached data for downstream tools
```

The view reports per-surface gross, opening and net areas, and openings identify
both each thermal pane and its logical physical opening. Physical ownership,
thermal-zone assignments, operation references and boundary relationships remain
attached to the resolved records. Internal mass is represented once as its physical
record, not duplicated for the two thermal faces used by the engine.

Geometry coordinates use `local_metric_after_scene_rotation`, matching the existing
geometry pipeline. The origin is the source geometry's minimum XY before rotation;
`orientation_deg` records the clockwise angle already applied to the local polygons.
Consumers must not apply a second scene rotation. Construction records are nominal
authoring constructions. They do not include thermal-bridge conductance equivalents
or engine material substitutions.

The source fields distinguish `source_kind` (`building_snapshot` or
`building_spec`), `source_id`, `source_snapshot_id` and `source_spec_hash`. For
physical Buildings, `source_id` and `source_snapshot_id` retain the exact snapshot
SHA-256; `source_spec_hash` identifies the resolved spec, including its supplied
climate context. For an existing spec, `source_spec_hash` identifies that spec and
`source_snapshot_id` is `None`. Spec-only resolution retains construction roles and
assignments, but leaves physical owner IDs absent when no authoring inventory exists.

```python
from epsm_core import resolve_building

spec_view = resolve_building(spec)  # spec is an existing complete BuildingSpec
print(spec_view.source_kind, spec_view.source_spec_hash)
```

The view's `climate` mapping retains the supplied calendar, site, weather identity
and path as context; resolution does not read the file at that path. The nested maps
are read-only and sequence data use tuples. Use `.to_dict()` for a detached mutable
export; changing that export cannot alter the Building or the resolved view. A
physical Building's snapshot identity remains the exact authoring snapshot hash
(weather is not part of that snapshot), while `source_spec_hash` includes the
resolved spec and supplied climate context. This also preserves identity for a
restored complete schema-5 snapshot. For an existing complete `BuildingSpec`,
`resolve_building(spec)` provides the same engine-independent view without weather
file I/O because the climate metadata is already present. This is a resolved-input
API; it does not imply migration of RC or other consumers.

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
preset revision and provenance, resolved construction values, occurrence identities,
authored ground fields, optional thermal-bridge input and load-reference choice. New
snapshots use `epsm.building/8`; `.sha256` identifies the stored
state. `.to_dict()` returns a detached copy; `.to_building()` returns an editable
independent building. Runtime results and evaluation settings are excluded.
Version-1 through version-7 snapshots remain readable and retain their original hash
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

`readiness(engine="energyplus")` also checks Kiva's resolved ground-floor unions
without opening weather files or initializing EnergyPlus. `preflight_energyplus(spec)`
provides the same check for a complete `BuildingSpec`. It rejects per-zone floor
holes, disconnected pieces, overlaps, non-coplanar floors and mixed constructions;
prescribed monthly ground temperatures remain available for geometry Kiva cannot
represent. The compiler repeats these checks as a final defensive guard.

`run_building(building, weather=weather, directory=...)` captures a snapshot and
checks EnergyPlus readiness before reading weather, then compiles and executes the
existing EnergyPlus implementation. `building.to_spec(weather)` exposes the
engine-independent migration bridge. Targeted opaque changes
reach thermal faces/internal slabs through bounded construction overrides; nominal
physical inventory continues to use the original Data materials. Parallel thermal
layers are reduced only within the engine adapter.

## Current adapter limits

The generated physical inventory supports flat compact parts, flat and pitched
cold attics, storeys, windows, full-footprint basements, reviewed party walls and
attached conditioned parts. Cold-attic ceilings, sloped roof shells and gable
walls have separate physical owners and constructions. Basement interfaces stay
internal and shared basement walls retain one installed owner. See
[roof and basement inputs](roofs-and-basements.md) for examples and the exact
construction and control handoff.

Touching pitched parts, pitched-attic party contacts above the eave, attached
unconditioned parts, generated apartment partitions and outlines changed by
automatic cleanup retain explicit ownership limitations. Readiness reports these
gaps; the pre-existing complete geometry/numerical APIs remain available. Thermal
reduction currently requires equal parallel path depths and at most ten emitted
layers per assembly. RC additionally validates its supported thermal domains,
buffer reduction, schedules and shading assumptions before calculation.
Layered window recipes remain available for material inventory; the current
thermal bridge requires whole-window U-value, SHGC and visible transmittance
through `WindowElement`, and readiness reports layered windows as unsupported.
Unknown nonthermal products and detailed window/equipment material composition
remain explicit inventory gaps; they are never invented from U-values or counts.

## Development installation

This release requires `epsm_data >= 0.6.0`.
Install Data first, then Core (`pip install -e ../epsm_data -e '.[dev,geometry]'`).
CI tests both a recorded Data commit and its current `dev` branch. Configure the
`EPSM_DATA_DEPLOY_KEY` Actions secret containing a read-only SSH deploy key scoped
to that private repository; CI
fails explicitly before testing if the secret is absent. Use the supported EPSM compatibility manifest to select an exact tested
combination; private wheels require configured dependency access.

## Consumer migration after explicit presets

Core now leaves `Building()` and `BuildingBuilder()` unconfigured. Callers that
intend the illustrative model must select
`Building(preset="illustrative-reference")`; callers that intend residential
Sveby assumptions must select `BuildingBuilder(building_use="residential")`.
RC, LCA and Workflows examples and tests using the former no-argument defaults
need that explicit selection when upgrading Core. Those consumer changes and
installed cross-package checks are separate from this Core change; they have
not been claimed as passing here.


## Shared walls and exposure

Physical elements expose a `boundary`: `Outdoors`, `Ground`, `Adiabatic` or
`Internal`. Partial party-wall contacts create separate opaque elements for the
outdoor remainder and adiabatic contact; only outdoor areas generate windows.
Same-building attached conditioned parts have one installed shared-wall owner,
retained as internal thermal mass. Constructions and material quantities remain
physical even when their boundary has no outdoor heat transfer.

Snapshot format 7 adds that explicit boundary. Formats 1–6 remain readable and
an untouched restored snapshot keeps its original bytes and identity. Missing
legacy boundaries are inferred from their role. Editing geometry regenerates
boundary-aware inventory. Format 8 additionally retains authored `zone_uses` and
`unconditioned_exchange` inputs. Reviewed basement contacts and supported
cold-attic shells now have physical owners; attached unconditioned parts,
apartments, touching pitched parts and pitched-attic contacts above the eave
retain their stated limitations. See [contact assumptions](party-walls.md).
