# Bundled operational standards

EPSM Core ships a version-pinned copy of the operational inputs from Sveby *Brukarindata bostäder* 2.0, published 11 November 2024. The source profile is package data rather than a network lookup, so the inputs used by a run do not change when the external website changes.

The official source is [Sveby Brukarindata bostäder 2.0](https://www.sveby.org/wp-content/uploads/2024/11/Sveby-brukarindata-bostadshus-2.0-241111.pdf). Data owns the machine-readable resource at `epsm_data/datasets/standards/sveby_residential_v2.json`, identified as `sveby.residential.v2.0.2024-11-11`. Core's existing loader reads that record and supplies numerical schedule and UseSpec factories.

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

The full apartment-size occupancy table and the official monthly DHW and household-electricity values remain in the JSON resource even where the current Core schema cannot emit them.

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

## Default use

The unversioned loader selects the current bundled standard:

```python
from epsm_core import load_sveby_spec

sveby = load_sveby_spec()
use = sveby.use_spec()
```

Use the versioned loader when a workflow must remain stable even after a future Core release changes its current standard:

```python
from epsm_core import load_sveby_residential_v2

sveby = load_sveby_residential_v2()
```

`BuildingBuilder(building_use="residential")` selects the unversioned loader; `BuildingBuilder()` supplies no profile. Known physical inputs can be dictionaries or typed Core specifications:

```python
from epsm_core import BuildingBuilder

building = BuildingBuilder(building_use="residential").build(
    identifier="example",
    geometry=geometry,
    climate=climate,
    envelope=envelope,
    facade=facade,
    airflow=airflow,
)
```

The resulting building gets the selected profile's `use`, `common_use`, solar multiplier and minimum mechanical outdoor-air flow. Weather, fabric, topology, leakage and recovery remain required. Explicit leaves in the supplied objects override profile leaves; Pydantic schema defaults that the caller did not explicitly set do not.

For a reviewed occupant density or active cooling system, create a caller-visible profile mapping and retain the same versioned provenance identity:

```python
from epsm_core import BuildingBuilder, load_sveby_residential_v2

sveby = load_sveby_residential_v2()
assumptions = sveby.building_assumptions(
    occupant_density_per_m2=0.021,
    cooling_enabled=True,
    fixed_solar_shading_calculated=True,
)
builder = BuildingBuilder(
    assumption_profile=sveby.profile_id,
    assumptions=assumptions,
)
```

## Type-specific DHW for EPC comparisons

Use `load_dhw_profile` to explicitly select historical BEN normal-use DHW
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
from epsm_core import load_dhw_profile, load_sveby_spec

profile = load_dhw_profile(
    "multi_family", purpose="epc_normal_use", version="1"
)
use = profile.apply_to(load_sveby_spec().use_spec(calendar_year=2024))
assert use.dhw_kwh_m2_year == 25
```

`apply_to` returns a validated replacement. It changes only the annual DHW rate,
retaining the original DHW timing, occupancy, gains and setpoints. The compiler
normalizes the retained schedule to the selected annual total, including leap
years. Set `BuildingSpec.load_reference_area_m2` to the compatible EPC Atemp;
geometric conditioned area is the fallback when no reference area is supplied.
Mixed programmes need a profile for each component and explicit area shares,
using the existing `ProgramBlend` or zone-use APIs.

The profile retains its source URI, source locator, area basis and type-specific
`profile_id`. `profile.source_record()` returns an **assumed** provenance record
for `use.dhw_kwh_m2_year`. When updating an existing building, replace the old
record for that field rather than keeping contradictory provenance:

```python
provenance = building.provenance.updated(
    records=tuple(
        record for record in building.provenance.records
        if record.field_path != "use.dhw_kwh_m2_year"
    ) + (profile.source_record(),)
)
building = building.updated(
    use=profile.apply_to(building.use),
    load_reference_area_m2=epc_atemp_m2,
    provenance=provenance,
)
```

`BuildingBuilder(building_use="residential")` and `load_sveby_spec()` supply 21 kWh/m²/year
from the published residential profile. The Sveby school operational profile
continues to supply 10; requesting `school` with `purpose="epc_normal_use"`
explicitly selects the separate BEN comparison assumption of 2. For observed
annual DHW, use the existing validated override
`use.updated(dhw_kwh_m2_year=observed_kwh / epc_atemp_m2)` and retain the actual
measurement or allocation basis in the caller's evidence.

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

- Daily schedules repeat throughout the year. The official monthly DHW and household-electricity profiles are stored but not emitted.
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
2. Add a versioned loader and its validation expectations.
3. Decide explicitly whether `load_sveby_spec()` should advance to the new version.
4. Document changed mappings and migration consequences.
5. Add tests for source values, model mappings, provenance and installed-package inclusion.
