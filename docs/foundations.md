# Foundation heat transfer and migration

New `EnvelopeSpec` objects use **Kiva** by default. The former constant 18°C
surface-temperature boundary is no longer implicit. This changes simulation
results and physical/run hashes; do not combine old and new results without
identifying their foundation method.

```python
from epsm_core import FoundationSpec, GroundTemperatureSpec

# Default for a new envelope; measured site properties can replace these values.
foundation = FoundationSpec(
    soil_conductivity_w_mk=1.73,
    soil_density_kg_m3=1842,
    soil_specific_heat_j_kgk=419,
    deep_ground_boundary="ZeroFlux",
    deep_ground_depth_m=40,
)
updated = envelope.updated(foundation=foundation, ground_temperature=None)

# Reproduce the historical, uncalibrated 18°C boundary explicitly.
legacy = envelope.updated(ground_temperature=GroundTemperatureSpec())

# Or supply a documented January–December profile.
legacy = envelope.updated(ground_temperature=GroundTemperatureSpec(
    monthly_temperatures_c=(4, 4, 5, 7, 10, 13, 15, 16, 14, 11, 8, 5),
    source="illustrative only; replace with justified contact temperatures",
))
```

Old serialized envelopes containing `ground_temperature` and no `foundation`
retain prescribed temperatures on load. New serialization stores the explicit
method. Supplying both Kiva and monthly contact temperatures is an error.
Switching an existing legacy envelope to Kiva requires clearing its profile as
shown above. No unsupported geometry silently falls back to the old method.

## Soil, perimeter and footing assumptions

The default soil values are EnergyPlus 24.2 defaults, **not measurements**.
The deep boundary is explicitly zero flux at 40 m rather than EnergyPlus's
automatic groundwater estimate. `GroundWater` with an explicit depth is available
when supported by evidence; the depth must lie below the slab bottom. The far
field defaults to 40 m. Mesh settings, hourly solver timestep and surface
absorptivities are pinned in the compilation report.

The exposed perimeter is the intersection of each ground-zone slab boundary
with the boundary of the resolved building-footprint union. Matching allows a
10 nm tolerance for rotated collinear edges without moving surface vertices. Internal thermal-zone
edges therefore contribute zero. `exposed_perimeter_fraction` (default 1) scales
this exterior perimeter for a documented aggregate exposure assumption; it does
not model neighbouring soil or spatially locate shared contacts. Courtyard
boundaries are not currently supported in a single Kiva floor.

Existing slab layers and below-grade basement-wall constructions are retained.
Kiva reads basement geometry from those surfaces. `wall_height_above_grade_m`
and `wall_depth_below_slab_m` default to zero. No additional footing block is
created by default, and EnergyPlus supplies its default foundation wall for slab
cases. To add a footing block, supply `footing_material`; `footing_width_m` and
`footing_depth_m` default to 0.3 m and become active only with that material.
`footing_wall` accepts an optional `ConstructionSpec` for a separately documented
below-slab wall. These extra footing inputs are separate from existing envelope
assemblies and are not inferred from energy residuals.

## Geometry and diagnostics

Slab, heated/unheated basement, concave simple footprints and supported zone
layouts use the same conditioned areas, zone volumes, loads and infiltration as
before. Redundant collinear vertices are removed with a 1 nm simplification tolerance,
retaining original coordinates and checking area conservation within 1e-6 m².
Compatible coplanar floor triangles are merged into a single downward
floor polygon per ground zone. Kiva floors retain normal, closure and volume
checks; their complete polygon is allowed to be concave. Other horizontal
receivers retain convex tessellation requirements.

A ground zone with holes, disconnected floor components, differing floor
constructions or elevations is rejected clearly. Explicit prescribed-temperature
mode remains available for these geometries. Foundation assumptions, assignments,
merged faces, settings and exposed lengths appear in `report.data["foundation"]`
and runner `diagnostics.json`. `ground_temperature` is null in Kiva reports.

The workflow's historical pilot explicitly retains its original temperature
boundary; diagnostic Kiva variants now select the Core specification. Source
hashes invalidate reuse across compiler changes. No cohort recalibration or
clustering is part of this migration.

Reference: [EnergyPlus 24.2 Kiva inputs](https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/group-advanced-surface-concepts.html#foundationkiva).

## Verification performed on 1 October 2026

- Core suite: **554 passed**, 9 skipped (including the opt-in smoke cases).
- Foundation suite with smoke enabled: **25 passed**, including seven annual
  EnergyPlus 24.2 cases: slab, heated basement, unheated basement, perimeter/core,
  apartments, rotated apartments and concave footprint. No foundation warnings.
- Workflow regression tests: **37 passed**; four existing Shapely warnings.
- A pinned real-building prototype comparison retained identical envelope
  materials, infiltration, ventilation and Kiva soil settings. Annual heating
  differed by only **0.0000021 kWh out of 342,870 kWh**, due to perimeter matching
  precision. Compiler provenance matches the final source for all seven smoke runs.

Receipts, models, engine diagnostics and comparisons are preserved under
`output/kiva-default-smoke-final-2026-10-01`,
`output/kiva-prototype-equivalence-final-2026-10-01`, and
`output/kiva-default-validation-2026-10-01.json`.
The cohort has not been rerun or recalibrated as part of this migration.
