# Applying building operation to matrix fabric

Added 3 October 2026. The fabric library belongs to EPSM Data; operational
calendars and energy simulation belong to Core. The implementation references
are also recorded in the script headers/docstrings and packaged source resources.

## Source versions and interpretation

| Profile | Published source | Implemented interpretation |
|---|---|---|
| Residential | Sveby Brukarindata bostader 2.0, bundled resource | Supplying `calendar_year` to `use_spec` or `BuildingBuilder` uses monthly household heat and DHW timing, with annual totals conserved. Omitting it preserves the legacy daily profile. |
| Office | [Brukarindata kontor 1.0, 2012](https://www.sveby.org/wp-content/uploads/2012/10/Sveby_Brukarindata_kontor_version_1.0.pdf) | Revised chapter 5: 1.3 L/s/m² Atemp, active weekdays 07–19. Table 2.2 still states 1.5; the discrepancy is explicit. Table 10.1: 225 days, 9 h/day, 70% presence, 20 m²/person, 108 W/person. |
| Primary/secondary school | [Brukarindata undervisningsbyggnader 1.0, 2016](https://www.sveby.org/wp-content/uploads/2016/05/Sveby-Brukarindata-undervisning-1.0-160525.pdf) | Table 2.2 room functions; 220 operating days. Classrooms and associated areas: 22 °C, 3 L/s/m², 5+5 W/m² for 10 h/day, .067 people/m² for 6 h/day at 80 W/person. |

Office 2.0 was a consultation draft when reviewed; it is not used. Office 50
kWh/m²/year business electrical input is represented by one equivalent equipment
load with 70% zone heat. A lighting/equipment split is not asserted. Off-hour
equipment fraction .2 is an EPSM scenario, not a source-prescribed fraction.
School service/storage has 18 °C, .35 L/s/m² and zero people/equipment/lighting.
Kitchen/dining and sport/showers have base/boost ventilation 2/4 L/s/m², five
hours each. School 07–17 operation and 09–15 occupancy are documented clock
placement assumptions. Heating remains enabled over closures; cooling is disabled
unless explicitly enabled with a suitable building-specific setpoint.

No national holidays or school vacations are generated. Provide actual dates and
their source; `normal_use=True` checks source day counts and weekdays. Raw actual
operation can use `normal_use=False`, and must match the target's normalization.
The non-residential builder defaults use the normal-use profiles. Use an explicit
custom assumption profile for actual-use calendars. Preschool/university, dynamic
blinds, full HVAC, fan heat and Sveby's postprocessing airing adjustment remain
separate. In particular, school airing 4 kWh/m² is never converted into leakage.

## Calendar and zone inputs

```python
from epsm_core import AirflowSpec, UseSpec, load_sveby_school_v1

# active_dates and calendar_source come from reviewed project observations.
profile = load_sveby_school_v1()
inputs = profile.building_assumptions(
    calendar_year=2023, active_dates=active_dates,
    calendar_source=calendar_source, zone_role="classrooms",
)
use = UseSpec.model_validate(inputs["use"])
airflow = AirflowSpec(
    topology="FTX", envelope_infiltration_ach=measured_leakage_scenario_ach,
    sensible_recovery_effectiveness=reviewed_recovery, **inputs["airflow"],
)
spec = spec.updated(use=use, airflow=airflow, load_reference_area_m2=verified_atemp)
```

The shading factor in `inputs['facade']` must be applied explicitly if using this
partial profile outside `BuildingBuilder`. Recovery and leakage are required
building inputs, not inferred from a use category.

`ScheduleSpec` retains required 24-hour `values`. Optional `weekday_values` gives
seven profiles Monday first. `SchedulePeriod` overrides inclusive dates with a
source and cannot overlap another period. `ScheduleSpec.annual` gives exactly
8760/8784 hour-start intervals with a matching `calendar_year`. All schedules use
EPW local standard time, without DST. Dated schedules from a different climate
year fail before compilation. Compiled schedules resolve real weekdays and dates
before emitting `Schedule:Compact`; EnergyPlus holiday flags cannot substitute
another day type.

`AirflowSpec.mechanical_vent_fraction` schedules outdoor mechanical flow;
`heating_availability` and `cooling_availability` control conditioning separately.
Natural exchange and envelope infiltration remain independent inputs. Setting
ventilation to zero does not disable heating during weekends or vacations.

`ZoneUseSpec` assigns `use` and/or `airflow` by exact compiled `zone_name` or
`zone_kind`. Inspect the compilation report first. Physical kinds include `main`,
`basement` and `attic`; apartment kinds include dwelling/common/stairwell.
Exact names take precedence over kinds; no matches and duplicate selectors fail.
School room functions must be mapped from a documented building programme to
appropriate thermal zones. Geometry subdivisions are not evidence of classroom
or kitchen location, and a whole-building classroom profile is only a declared
approximation when those functions are unknown.

`load_reference_area_m2` scales people, electrical loads, DHW and mechanical
flow using Atemp while preserving geometry, surface heat transfer and physical
air volume. Exact zone assignments may specify `reference_area_m2`; allocations
must sum to the building's declared reference area. The report retains both
physical and load areas. Do not rescale a footprint to fit EPC Atemp. Existing
workflow cases that already rescaled densities must not apply that rescaling again.

`UnconditionedExchangeSpec` schedules declared outdoor ACH on unconditioned
attic/basement zones. It does not change conditioned-envelope leakage or override
their computed temperatures. There is no assumed default exchange rate.

## Energy accounting and validation

`DeliverySpec(heating=HeatingDeliverySpec(...))` converts validated hourly ideal
space heat using declared carrier, efficiency, an explicit heat-pump COP schedule
where applicable, and net distribution losses. Net losses exclude heat already
recovered into simulated zones. Their annual total uses the compiled load
reference area and is distributed using a normalized `loss_fraction` schedule.
SFP optionally reports scheduled ventilation fan electricity separately. It does
not feed fan heat back into the thermal simulation. FVP and this accounting model
are mutually exclusive; the existing FVP model requires uniform continuous exhaust.

Results include `space_heating_carrier_input_kwh`, `net_distribution_loss_kwh`,
optional `ventilation_fan_electricity_kwh`, monthly thermal totals and
`space_heating_eui_on_load_reference_area_kwh_m2`. Geometric demand EUI remains
available. DHW, business electricity and cooling are not included in delivered
space heat. This accounting requires independently evidenced parameters and
does not establish a building-level accuracy threshold.

Tests cover source energy integrals, closures, leap years, native zone assignments,
load areas, carrier conservation and annual EnergyPlus office/school execution.
Synthetic test calendars and buildings are integration evidence, not EPC validation.

### Generated eave resolution (2026-10-03)

Skewed registry footprints can produce sub-centimetre heights at almost parallel
eaves in analytic gable/mono-pitch models. `roof_faces` resolves generated heights
below the existing `MIN_GENERATED_EDGE_M` (0.01001 m) to the eave base, using the
same node heights for roof triangles and attic walls. It preserves source x/y,
ridge/pitch choice and projected coverage; triangulation retains those heights.
This bounded roof-model approximation is declared in graph approximations.
The EnergyPlus 24.2 minimum-edge acceptance threshold remains unchanged. Genuine
short footprint edges still fail. Shared vertex tuples retain pool identity through
cyclic ring cleaning. Four existing SE.02 diagnostic geometries now compile.
