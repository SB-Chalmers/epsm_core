# Airflow and ideal heating accounting

Core models thermal demand using EnergyPlus 24.2 Ideal Loads. F is an equivalent
thermal representation of exhaust replacement air; pressure coupling between fan,
wind and stack is not simulated. FT/FTX use balanced thermal equivalents. S uses
separate natural exchange. Ideal heating supply flow includes recirculation and
must not be interpreted as outdoor ventilation.

## Reference-area infiltration

TABULA equation (7), printed pp.12–13 / Table 4 uses an additional infiltration
surcharge on A_C_ref ×2.5 m. This is a calculation reference, not measured clear
height or n50. Convert to L/(s m²) as source_ACH ×2.5/3.6. In Core:

```python
AirflowSpec(topology="F", envelope_infiltration_ach=0,
            envelope_infiltration_l_s_m2=0.4 * 2.5 / 3.6,
            mechanical_vent_l_s_m2=0.35)
```

Supply/document BuildingSpec.load_reference_area_m2 (and any zone-specific area
assignments) using the source area convention. Core does not assume TABULA area
equals Atemp. Infiltration is emitted as Flow/Zone, avoiding EnergyPlus geometric
floor-area substitution. It shares the explicit area accounting already used for
mechanical ventilation. A nonzero ACH together with area-based infiltration is
rejected. Existing ACH inputs retain their Core-volume interpretation and emitted
objects. Mixed programmes conserve the area-based hourly flow; mixing reference
bases requires separate zone assignments.

## Heating boundary and diagnostics

Supply Air Total Heating Energy is the ideal heating-coil demand, including
outdoor-air conditioning after recovery. Do not add outdoor-air heating or
infiltration heat loss again. They are explanatory components, not extra demand.
Humidity controls remain disabled; air-to-air recovery is restricted to FTX and
does not recover infiltration. Exhaust heat pumps remain downstream delivery
models. Heating/cooling availability is independent of ventilation schedules;
prescribed ventilation uses explicit DCV None and NoEconomizer.

Hourly outputs expose supply/zone sensible heating, zone sensible cooling,
outdoor-air heating, recovered heat, supply/outdoor-air standard-density flow,
and infiltration standard-density flow and sensible heat loss. S zones additionally
request natural-ventilation flow and sensible heat loss when those objects exist. Standard-density
flows are not instantaneous design-volume flows at outside-air density. Component
OA/recovery energies are conditional on Ideal Loads operating mode; don't force
an all-hours identity from annual heating-only positive parts when simultaneous
zone cooling occurs. Native tests verify heating-only component accounting,
reference-area/ACH equivalence, and recovery reducing demand.

The compilation report records a nominal design/schedule component budget,
reference basis, thermal-equivalent topology, and unresolved pressure coupling.
Weather-response coefficients are excluded from that nominal mean. No actual
airtightness or building accuracy is inferred from these diagnostics.

Sources:
- https://episcope.eu/fileadmin/tabula/public/docs/report/TABULA_CommonCalculationMethod.pdf
- https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/group-airflow.html
- https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/group-zone-forced-air-units.html
- https://bigladdersoftware.com/epx/docs/24-2/engineering-reference/ideal-loads-air-system.html

Review 2026-10-04: retained Ideal Loads; corrected reference-flow input and
accounting observability; no invented leakage measurements or exhaust-pressure
network. Previously fitted ACH multipliers must be reassessed against this area
convention. No national building accuracy result is claimed.

Native sensible-component reconciliation uses a 0.5% tolerance because the engine
uses different humidity-dependent heat capacities for coil, zone/OA and recovery
components; those sensible-only sums are not an exact enthalpy identity. Checked
against PurchasedAirManager.cc v24.2 lines2535–2542,2590–2596,2826–2829:
https://github.com/NREL/EnergyPlus/blob/v24.2.0/src/EnergyPlus/PurchasedAirManager.cc
The equivalent-flow heating-demand comparison remains at relative1e-7.

Validation: 636 Core tests passed,9 skipped (107.36s). Native cases verify
reference-area/ACH heating equivalence, FTX reduction and sensible-component
accounting. A separate native S case verifies three natural-flow signals and
strict runner acceptance; artifacts are retained in epsm_workflows/output/
core-airflow-fix-2026-10-04. Ruff and git diff --check pass. These are engine/
accounting checks, not new measured-building accuracy validation.
