# Architecture and physical assumptions

`epsm_core` accepts one immutable `BuildingSpec`, compiles it directly to EnergyPlus
24.2 epJSON, runs an isolated process, and reads validated scalar and hourly results.
The compiler has no database, archetype, Honeybee, Ladybug or network dependency.
`epsm_workflows` owns study orchestration/storage/analysis. `epsm_data` owns material
and renovation catalogues and its optional adapter imports core when called.

## Geometry and UBEM

One run simulates one target building. A target may have multiple disconnected
polygon components; each has its own thermal zone in whole-building mode. The
per-storey option creates a zone at every level in each component. Whole-building
zones explicitly carry full Atemp and volume; intermediate slabs appear as two-sided
internal mass. The EnergyPlus floor/space area warning is expected for this simplified
zoning mode and is retained in diagnostics.

Coordinates are in metres. The compiler translates target/context by the same source
origin. Clockwise orientation rotates only the target; context retains its geographic
position. Facade IDs `cN.rN.eN` refer to component/ring/edge before rotation. WWR follows
those IDs. Courtyard walls are exterior, and courtyard area is excluded from Atemp.
Horizontal surfaces containing holes are tessellated with constrained Delaunay
triangulation, checked for area conservation. World coordinates and outward normals
are emitted explicitly.

DistrictPlan requires georeferenced, already-oriented footprints in one shared metric
CRS. It adds other target footprints as shading and runs each building independently.
There is no inter-building airflow, heat transfer, district plant coupling or urban
weather feedback. Overlapping components are rejected rather than silently repaired.

## Kiva

The only ground model is EnergyPlus Foundation:Kiva. Slab-on-grade and a single uniform
full-depth basement per component are supported, including unconditioned basements.
No exposed-ground EPW temperature is assigned below the building. Soil defaults are
explicit serialized inputs and are not claimed to represent a particular Swedish site.

EnergyPlus 24.2 requires distinct foundation objects for tessellated floor patches.
Courtyard models therefore use multiple Kiva instances within a component. Artificial
tessellation edges are marked unexposed; courtyard and outer edges are exposed.
The compilation report records this area/perimeter approximation. Annual simulation
acceptance proves object compatibility, not agreement with a full 3D soil solver.
Simple concave footprints retain a single floor polygon and segment-specific perimeter.
Both otherwise unused numeric perimeter fields are explicitly supplied to work around
EnergyPlus 24.2 epJSON extensible-field counting; its resulting ignored-field warnings
are retained. See the [EnergyPlus Kiva reference](https://bigladdersoftware.com/epx/docs/24-2/input-output-reference/group-advanced-surface-concepts.html#foundationkiva).

## Constructions and roof boundary

Layers are ordered outside to inside. Surface film resistance is a nominal U-value
reporting convention; EnergyPlus computes film coefficients dynamically. Target-U
helpers solve a selected layer thickness and reject infeasible targets. Thermal-bridge
uplift scales layer conductivity while preserving thickness and heat capacity, giving
the requested nominal-U uplift under the stated film convention. It is an equivalent
conductance approximation, not explicit 2D junction modelling.

Compact roofs carry insulation directly. Cold attics use an unconditioned zone with
no HVAC/gains; insulation is in the top-floor ceiling and its reversed adjacent floor.
The exterior weather shell is stored separately. No assumption of attic ventilation
is made; the current attic is a sealed unconditioned buffer.

## Loads, ventilation, delivery and PV

S represents prescribed operating self-draught exchange, not wind/stack pressure
modelling. F/FT/FTX mechanical flow uses Ideal Loads outdoor air, with sensible/latent
recovery on FTX. Envelope leakage is a separate constant operating ACH term. F and FT
can have identical ideal demand. Effective outdoor-air ACH reports physical air volume,
without reducing the flow by heat-recovery effectiveness. Fan consumption is not
calculated in these ideal-demand models.

Supply temperatures are Ideal Loads limits; thermostat schedules describe room/return
conditions. Cooling, humidification and dehumidification are disabled by default.
Daily schedule profiles repeat over the 8760-hour non-leap calendar in standard time.
Occupant gains use explicit activity and fractional schedules. DHW uses prescribed
55 C hot water, 10 C cold water and an annual thermal load normalized to the schedule.

`space_heating_demand_kwh` is ideal supply-air heating, including outdoor-air treatment.
`dhw_load_kwh` is water heating. `ideal_thermal_load_kwh` is their sum; cooling is a
separate output. These quantities are not purchased/site energy.

FVP is a downstream hourly delivery estimate for F ventilation. The sensible exhaust
availability bounds evaporator extraction using explicit exhaust minimum temperature,
flow, rated capacity and constant COP; priority determines DHW versus space allocation.
It does not model latent extraction, frosting, part-load COP or a plant loop. Its heat,
electricity, extraction and backup input are reported separately with a conservation
test. PVWatts uses the optional PySAM V8 backend and the same EPW; output AC power is
integrated over each one-hour interval. No self-consumption or net-site-energy value
is inferred from thermal demand.

## Validation and artifacts

Schema validation precedes execution. EnergyPlus input processing is the native
preflight; no template expansion or intermediate IDF is used. Every run retains
building JSON, epJSON, compilation report, SQL, process log and `.err` diagnostics.
Nonzero exit, severe/fatal errors, missing targets, nonfinite/negative energy,
incomplete hours and annual/hourly disagreement prevent successful completion.
Warnings are counted and preserved. The campaign layer separately owns resume and
atomic Parquet/catalogue transactions.
