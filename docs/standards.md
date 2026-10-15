# Bundled operational standards

EPSM Data owns the version-pinned operating definitions from Sveby *Brukarindata bostäder* 2.0, published 11 November 2024. Core resolves their schedules and physical inputs. The source profile is package data rather than a network lookup, so the inputs used by a run do not change when the external website changes.

The official source is [Sveby Brukarindata bostäder 2.0](https://www.sveby.org/wp-content/uploads/2024/11/Sveby-brukarindata-bostadshus-2.0-241111.pdf). Data owns the machine-readable resource at `epsm_data/datasets/standards/sveby_residential_v2.json`, identified as `sveby.residential.v2.0.2024-11-11`. Core converts the selected record through numerical schedule and UseSpec factories.

## Scope and terminology

The profile describes standardised **normal residential use** for energy calculation. It does not define a building's geometry, constructions, leakage, ventilation topology, heat-recovery efficiency, heating system or weather. It is not a peak-load sizing profile.

Sveby expresses area-normalised inputs per Atemp. EPSM Core applies area densities to its conditioned floor area. A caller claiming formal Sveby or regulatory compliance must verify that those area definitions agree for the model, or supply a documented conversion. Loading the profile alone does not establish regulatory compliance.

“Sveby value” and “EPSM completion default” are distinct:

- A Sveby value is copied from the versioned source document.
- A completion default fills a Core-required field for batteries-included operation when Sveby does not provide a universal value.
- A building observation supplied by the caller overrides either kind and is recorded as measured by `BuildingBuilder`.

## Values and Core mappings

| Source concept | Stored value | Current Core mapping |
| --- | ---: | --- |
| Heating setpoint | 21 °C | Constant `UseSpec.heating_setpoint` |
| Non-heating/cooling-season setpoint | 25 °C | Constant `UseSpec.cooling_setpoint` |
| Presence | 17:00–07:00, 14 h/day | Repeated 24-hour occupancy schedule |
| Person heat | 80 W/person total | `UseSpec.occupant_activity_w`; channel split selected by `UseSpec.gain_partitions` |
| Household electricity | 21 kWh/(m² Atemp year) | Retained as source metadata |
| Household electricity available as heat | 70%; 14.7 kWh/(m² year), 1.68 W/m² | `UseSpec.equipment_gain_w_m2`; radiant/latent/convective split selected by `UseSpec.gain_partitions` |
| DHW | 21 kWh/(m² Atemp year) | `UseSpec.dhw_kwh_m2_year` |
| DHW available as internal heat | 0% | Water use is not assigned as a zone gain |
| Minimum outdoor air | 0.35 L/(s m²) | Partial `AirflowSpec.mechanical_vent_l_s_m2` default |
| Solar shading without a detailed calculation | 0.50 total | `FacadeSpec.solar_shading_factor` |
| Occupant behaviour when fixed shading is calculated | 0.71 | Optional facade multiplier |
| Stair, storage and plant-room heating | 18 °C | `common_use.heating_setpoint` |
| Refuse-room heating | 10 °C | Stored; needs a distinct zone-use assignment |
| Kitchen boost | 30 min/day | Stored; not emitted without a building-specific boost flow |
| Window-airing addition | 4 kWh/(m² Atemp year) | Stored for result normalisation, not emitted as infiltration |

The full apartment-size occupancy table and official monthly values remain in the Data resource. Supplying a residential calendar year resolves the supported monthly energy schedules; apartment-specific population remains an explicit input.

Sveby specifies total person heat and useful household electricity, not universal
EnergyPlus radiant, latent and convective fractions. Core keeps those concerns
separate: the named illustrative Building preset explicitly selects
`GainPartitionSpec(policy="epsm_legacy_v1")`; a missing or null policy on an older
snapshot retains the legacy fallback and appears as `selection="legacy_default"`
in the per-zone gain diagnostic. A caller can provide reviewed channel fractions
with `policy="explicit"`. These are modelling inputs rather than additional Sveby
values. See the [physical Building gain-partition API](physical-building.md#internal-gain-partitions)
for the legacy values, field meanings, budget checks, diagnostic and serialization
behavior.

## Resolve Data definitions

Select source definitions in Data and use Core's single conversion route for
standard and authored profiles. Conversion of a loaded profile reads no files and
does not select another catalogue record:

```python
from epsm_data import select_operating_profile
from epsm_core import resolve_operating_profile

profile = select_operating_profile("multi_family")
resolved = resolve_operating_profile(profile, calendar={"calendar_year": 2024})
operation = resolved.operation
print(resolved.requirements)
assumptions = resolved.to_dict()["assumptions"]
```

`ResolvedOperatingProfile.assumptions` preserves Core's `use`, `common_use`,
`airflow` and `facade` section names. Its nested data are read-only;
`to_dict()` returns a writable detached export. `operation` is the validated
`OperationProfile` when use inputs are complete. `requirements` describes missing
inputs in this partial conversion, not the readiness of an existing Building.
The caller must combine them with its chosen physical inputs. Profile sources,
assumption `source_records` and notes remain inspectable, including generic
screening labels and explicit BEN source locators.

Residential `calendar={"calendar_year": year}` conserves monthly DHW and useful
household-electricity timing in ordinary and leap years. Omitting the year retains
the existing repeated daily route. Office and school require caller-supplied
`calendar_year`, `active_dates` and a nonempty `calendar_source`, with optional
`normal_use=False` for an explicitly documented actual-use calendar. Missing
calendar returns `operation=None` and a `calendar` requirement. A supplied invalid
calendar raises an error. No holiday list or clock dates are invented.

For clean authoring, construct `OperatingProfile("project-id", {
"building_assumptions": {"use": {...}, "airflow": {...}, "facade": {...}}
})` using portable plain values. Core validates each supplied physical value;
valid incomplete sections expose missing field paths and remain inspectable.
Custom schedules are supplied explicitly, without a second calendar-expansion
convention. Unknown sections and invalid values raise errors even when other
fields are missing. The same operation type is returned for standard and custom
definitions.

BEN normal-use DHW remains an explicit partial choice:

```python
from epsm_data import select_dhw_profile

ben = select_dhw_profile("multi_family", purpose="epc_normal_use")
dhw = resolve_operating_profile(ben, previous=operation)
assert dhw.operation.dhw_kwh_m2_year == 25
assert dhw.operation.dhw_fraction == operation.dhw_fraction
```

Without `previous`, BEN returns only the sourced annual DHW field and missing-use
requirements; it never creates occupancy, temperatures or timing. Explicit
`previous` also supports authored partial-use overlays. Full standard profiles
resolve their own use independently. Source coefficients retain their Atemp basis;
minimum airflow never supplies an installed ventilation topology, and no reference
area is inferred. Weather and geometry remain outside this conversion.

## Selection and advanced physical conversion

Select definitions in Data and resolve their physical inputs in Core:

```python
from epsm_data import select_operating_profile
from epsm_core import BuildingBuilder, SvebyResidentialSpec, resolve_operating_profile

definition = select_operating_profile("multi_family", version="2.0")
resolved = resolve_operating_profile(definition, calendar={"calendar_year": 2024})
use = resolved.operation
```

`BuildingBuilder(building_use="residential")` uses this same route;
`BuildingBuilder()` selects no profile. Office and school require a caller-supplied
year, active dates and calendar source. Known physical leaves override selected
assumptions; typed schema defaults the caller did not set do not override them.

```python
building = BuildingBuilder(building_use="residential").build(
    identifier="example", geometry=geometry, climate=climate,
    envelope=envelope, facade=facade, airflow=airflow,
)
```

The builder supplies use, common-space operation, shading and minimum mechanical
outdoor air. Weather, fabric, topology, leakage, recovery and reference area remain
explicit requirements. For reviewed overrides, preserve the selected source ID:

```python
resolved = resolve_operating_profile(
    definition, occupant_density_per_m2=0.021,
    cooling_enabled=True, fixed_solar_shading_calculated=True,
)
builder = BuildingBuilder(
    assumption_profile=resolved.profile_id,
    assumptions=resolved.to_dict()["assumptions"],
)
```

Advanced physical converters remain public. `SvebyResidentialSpec` accepts loaded
values and retains common-space, compiler coverage and detailed assumption inspection:

```python
sveby = SvebyResidentialSpec(definition.to_dict()["values"])
```

`SvebyNonResidentialSpec`, `DHWProfileSpec` and `GenericOtherProgramme` retain their
separate physical/calendar/accounting capabilities. Conversion of an already
loaded definition through `resolve_operating_profile` performs no resource lookup.

## Type-specific DHW for EPC comparisons

Use Data’s `select_dhw_profile` to explicitly select historical BEN normal-use DHW
assumptions for EPC comparisons. Version `"1"` stores the coefficients from
BEN BFS 2016:12 with BFS 2017:6 amendments in package data; it does not follow
changes to regulations or retrieve sources at runtime.

| Building type | Annual useful DHW, kWh/(m² Atemp year) |
| --- | ---: |
| `single_family` | 20 |
| `multi_family` | 25 |
| `office`, `school`, `non_residential` | 2 |

The source is [BEN, Chapter 2 Tables 2:1–2:7 and Chapter 3](https://www.boverket.se/Resources/constitutiontextstore/BEN/xml/Konsoliderad_BEN_BFS_2016_12.pdf).
These are normal-use coefficients before production efficiency is applied.
Purchased energy requires a separate efficiency or DHW COP assumption. VVC
losses, storage losses and installation-specific savings are not included.
Select the appropriate reporting basis in the workflow; loading a profile does
not establish actual consumption or regulatory compliance.

```python
from epsm_data import select_dhw_profile, select_operating_profile
from epsm_core import resolve_operating_profile

previous = resolve_operating_profile(
    select_operating_profile("multi_family"), calendar={"calendar_year": 2024},
).operation
profile = select_dhw_profile("multi_family", purpose="epc_normal_use", version="1")
overlay = resolve_operating_profile(profile, previous=previous)
use = overlay.operation
assert use.dhw_kwh_m2_year == 25
```

The partial BEN definition changes the annual DHW rate and retains the explicitly
supplied previous timing, occupancy, gains and setpoints. Without `previous`, the
result keeps only that supplied rate and lists missing fields. The compiler
normalizes retained timing to the annual total, including leap years. Supply
compatible EPC Atemp as `BuildingSpec.load_reference_area_m2`. Mixed programmes
need independent component profiles and explicit area shares through `ProgramBlend`
or zone-use APIs.

The definition retains source URI, locator, area basis and type-specific identity.
`overlay.source_records` identifies the annual rate as assumed evidence. An existing
BuildingSpec must retain that record with the changed physical use:

```python
provenance = building.provenance.updated(
    records=tuple(record for record in building.provenance.records
                  if record.field_path != "use.dhw_kwh_m2_year") + overlay.source_records,
)
building = building.updated(
    use=overlay.operation, load_reference_area_m2=epc_atemp_m2, provenance=provenance,
)
```

`DHWProfileSpec` remains available for explicit physical accounting and
`apply_to`/`source_record` operations on loaded fields. The canonical route above
preserves those source and timing semantics. Residential Sveby still supplies 21
kWh/m²/year and school Sveby 10; BEN `school` explicitly supplies the separate
comparison coefficient 2. For observed annual DHW, use
`use.updated(dhw_kwh_m2_year=observed_kwh / epc_atemp_m2)` and retain the measurement
or allocation basis.

## Completion defaults

Sveby specifies occupants by apartment size, not one universal person-per-area value. The residential profile path therefore retains the previous EPSM demonstration density of `0.017 person/m²` as an explicitly labelled completion assumption. Replace it by calculating the building population from the stored apartment-size table and dividing by the verified Atemp.

The residential profile also keeps cooling disabled because the standard setpoint does not prove that a cooling system exists. The 25 °C schedule remains present and becomes active when the caller supplies `cooling_enabled=True`.

Inspect completion assumptions programmatically:

```python
assert sveby.completion_default_fields == (
    "cooling_enabled",
    "occupant_density_per_m2",
)
```

Inspect compiler coverage separately:

```python
for field in sveby.unsupported_fields:
    print(field, sveby.data["unsupported_in_epsm_core"][field])
```

## Known limitations and compliance boundary

The current Core application is a transparent thermal subset of the stored standard:

- Without an explicit residential calendar year, daily schedules repeat. Supplying a calendar year conserves the stored monthly DHW and household-electricity totals on the actual calendar.
- `equipment_gain_w_m2=1.68` represents useful internal heat, not the complete 21 kWh/m² household-electricity end use. Do not treat the simulated equipment meter as total household electricity.
- Apartment compilation conserves the whole-building gain but may concentrate it in dwelling zones rather than distributing it over every Atemp zone as Sveby describes.
- Kitchen boost duration is known, but flow is installation-specific and constant `AirflowSpec` has no boost schedule.
- The window-airing value is a post-simulation heating-energy addition involving geographic and delivery-system factors. It must not be disguised as constant infiltration.
- The default `0.35 L/(s m²)` is compatible with F, FT and FTX topologies. Natural `S` ventilation requires an explicit topology-appropriate conversion and must override the mechanical-flow leaf.
- The 0.50 shading factor is for cases without a detailed fixed-shading calculation. Where Core geometry/context represents fixed shading, request the 0.71 occupant-behaviour factor instead to avoid double counting.
- Refuse rooms cannot receive their separate 10 °C setpoint until the model supplies a distinct zone-use assignment.

Consequently, “loaded from the Sveby profile” means the run has traceable standardised operational inputs. It does not by itself mean every Sveby adjustment has been applied or that a regulatory submission is compliant.

## Provenance and replacement

Every missing leaf merged by a selected profile is recorded as `status="assumed"`, with the versioned profile ID as both source and `assumption_profile`. Explicit caller leaves are recorded as measured with the caller's `source` label. The builder replaces caller-supplied provenance to prevent stale records from surviving a merge.

The resource validates its schema, identity, version and central reviewed values on load. Corruption or an unreviewed edit fails before a `UseSpec` is produced. Tests cover the values, schedule duration, explicit residential profile selection, typed-input merging and caller-owned profile compatibility. The JSON path is included in wheel package data and is checked during release verification.

When updating the standard:

1. Add a new versioned JSON resource rather than rewriting the historical file.
2. Extend Data’s public version selection and source validation.
3. Review the selected current version independently from explicit version pins.
4. Document changed mappings and migration consequences.
5. Add tests for source values, model mappings, provenance and installed-package inclusion.

## Migrating removed Core selectors

Definition selection now belongs to Data. Core retains physical converters,
schedule builders, common-space handling and calculation APIs.

| Previous Core selector | Public replacement |
| --- | --- |
| `load_sveby_spec()` | `select_operating_profile("multi_family")`, then `resolve_operating_profile` |
| `load_sveby_residential_v2()` | `select_operating_profile("multi_family", version="2.0")`, then resolve |
| `load_sveby_office_v1()` | `select_operating_profile("office", version="1.0")`, then resolve with project calendar |
| `load_sveby_school_v1()` | `select_operating_profile("school", version="1.0")`, then resolve with project calendar |
| `load_dhw_profile(...)` | `select_dhw_profile(...)`, then resolve with explicit `previous` use for an overlay |
| `load_generic_other_v1()` | `load_operating_profile("generic_other")`, then resolve; retain the labelled fallback identity |

Import selection functions from `epsm_data` and the resolver from `epsm_core`.
Existing saved Core formats and physical class constructors remain supported.

These selectors require Data 0.5.0 or newer. Core remains version 0.3.0 during
development; version numbers alone do not identify the coordinated archetype
APIs. Install the exact Data/Core development revisions recorded by the consuming
EPSM project's compatibility manifest and installed acceptance receipt.
