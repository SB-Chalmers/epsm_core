# Area-weighted mixed programmes

`ProgramBlend` converts explicit heated-area fractions and sourced operational
programmes into native `UseSpec`/`AirflowSpec`, or a `ZoneUseSpec` override. The
concept follows [Honeybee ProgramType.average](https://www.ladybug.tools/honeybee-energy/docs/honeybee_energy.programtype.html).
It uses EPSM's own validated specs and compiler, without a Honeybee dependency.

```python
from epsm_core import ProgramBlend, ProgramComponent

# residential_use/office_use and their airflow specs are explicit source-backed
# inputs (for example the Sveby loaders); no programme is inferred from geometry.
blend = ProgramBlend(
    source="Existing EPC heated-area shares; shared-height effective-zone assumption",
    components=(
        ProgramComponent(name="residential", area_fraction=0.8,
                         use=residential_use, airflow=residential_airflow,
                         source="Sveby residential profile; existing EPC 80% residential"),
        ProgramComponent(name="office", area_fraction=0.2,
                         use=office_use, airflow=office_airflow,
                         source="Sveby office profile; existing EPC 20% office"),
    ),
)
use, airflow = blend.resolve(calendar_year=building.climate.calendar_year)
building = building.updated(use=use, airflow=airflow)
# Alternatively retain the other zones' programmes:
assignment = blend.zone_assignment(calendar_year=building.climate.calendar_year,
                                   zone_name="existing_exact_zone_name")
```

Area fractions must be finite, positive and sum to one; zero-share programmes
should be omitted. Use *heated/load-reference-area* fractions, not footprint or
unheated total area. GIS purpose order supplies no fraction. Missing, unrepresented
or contradictory EPC shares must be reviewed, not silently normalised. Share counts
alone cannot locate an office on a particular storey.

`load_generic_other_v1()` supplies a labelled screening fallback when the caller
cannot identify a non-residential use. Its `use_spec()` assumes 21 C heating,
weekday 08:00–18:00 occupancy at 0.03 people/m2, 5 W/m2 each of equipment and
lighting, and 5 kWh/m2/year of DHW. It exposes a 0.7 L/s/m2 ventilation design
flow and a matching weekday fraction schedule for the caller's `AirflowSpec`.
These are EPSM completion assumptions, not published Sveby values or claims about
restaurants, healthcare, hotels, or other specific uses. The caller must record
the profile ID and original programme name in provenance. `ProgramBlend` itself
continues to require complete fractions; any minimum-share rule and reassignment
of omitted area belong to the data adapter and must be documented there.

Design loads are area-weighted. Their schedules are **load-weighted**, so every
hour preserves people, occupant activity heat, equipment electricity and zone heat,
lighting and mechanical outdoor-air flow. DHW uses each component's independently
normalised annual profile before combining its annual demand. Dated closures and
weekday profiles expand to explicit 8760/8784 local-standard-time vectors for the
simulation year. Invalid years and zero-activity positive DHW are rejected.

`UseSpec.occupant_activity_schedule` is optional W/person; when absent, the original
constant activity remains. `equipment_heat_fraction_schedule` is an optional hourly
heat fraction. The compiler splits electrical equipment into additive radiant,
convective and lost objects, preserving electricity and total zone heat. The legacy
30% input-radiant share is retained where total heat permits; it is capped at total
heat when that heat fraction falls below 30%. Each emitted object's fractions remain
physical. All schedules carry the blend source. Keep the serialised `ProgramBlend`
alongside the applied building to retain each component's full provenance.

Identical controls are required by default. For differing thermostats, explicitly
supply `control_use=...` to `resolve`/`zone_assignment` and document this choice in
`blend.source`; only its heating/cooling setpoints and cooling-enabled flag are used.
No weighted temperature is silently assumed. Supply limits and plant availability
must agree. Different ventilation topology, recovery efficiency or leakage weather
coefficients require **separate zone assignments**. ACH averaging assumes the same
zone height/area-to-volume basis; different-height spaces should remain separate.

This is an effective-zone approximation. It conserves programme inputs; it cannot
conserve the separately controlled zones' nonlinear thermal demands, establish
party walls, reconstruct missing occupancy calendars or guarantee empirical heating
error below 20%/10%. Spatially resolved mixed-use buildings should use separate
`ZoneUseSpec` assignments with documented zone-specific reference areas. Heating
systems and FVP restrictions remain validated by `BuildingSpec`.

Verification includes normal/leap-year conservation, closures, zero loads, nested
blends, rejected system/control conflicts, native epJSON schema compilation and an
annual EnergyPlus run checking equipment electricity, DHW and severe errors.
