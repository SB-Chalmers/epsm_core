# Reusing prepared geometry

`Building.to_spec()` and `Building.snapshot().resolve(weather)` each resolve
geometry once and use that graph for physical surface and internal-mass
assignments. Materials and schedules remain inputs to each conversion.

For repeated conversions or compilation, explicitly retain a bounded cache:

```python
from epsm_core import EnergyPlusCompiler
from epsm_core.pipeline import GeometryCache

cache = GeometryCache(max_entries=16)
spec = building.to_spec(weather, geometry_cache=cache)
resolved = building.resolve(weather, geometry_cache=cache)
compiler = EnergyPlusCompiler(energyplus, geometry_cache=cache)
model, report = compiler.compile(spec)
cache.clear()
```

Here `building` is a complete physical Building, `weather` is explicit Weather,
and `energyplus` names an installed EnergyPlus 24.2 executable. The cache is an
advanced optional argument; ordinary calls need no cache management.

The key retains geometry, window placement, facade shading and panelization.
Glazing, opaque materials and operating schedules are rebound on each conversion.
Cached working graphs are deep copies: compilation cannot change another run's
geometry. LRU eviction limits the number of retained graphs. One sequential caller
owns each cache; do not share it between workers.

The first cached lookup reads installed Core source contents once per process.
Restart the Python process after editing source code. Construction does no I/O;
later lookups do not check source files or directory metadata. `clear()` releases
geometry entries and resets the hit/miss counters. It does not refresh the
implementation identity. Ordinary uncached resolution retains its no-I/O contract.

Engine adapters that need the physical Building, validated specification and
read-only geometry view can obtain them in one preparation:

```python
from epsm_core.resolved import resolve_snapshot_inputs
from epsm_core.specs.schedules import hourly_schedule_scope

snapshot = building.snapshot()
with hourly_schedule_scope():
    inputs = resolve_snapshot_inputs(snapshot, weather, engine="epsm_rc")
    spec = inputs.spec
    resolved = inputs.resolved
    physical = inputs.building
    heating_setpoints = spec.use.heating_setpoint.hourly(weather.calendar_year)
```

This advanced handoff checks readiness, validates the specification and resolves
geometry once. `spec` and `physical` are caller-owned working objects; their maps
may be mutable. `resolved` stays immutable, and none of these values can change
the source snapshot or another call's inputs. Snapshot and resolved export
formats are unchanged. EnergyPlus's ten-layer construction limit applies to its
readiness, preflight and compilation; it does not restrict physical RC inputs.

The schedule scope shares immutable hourly tuples for equal schedule contents
and years across validation, calculation and energy accounting in that call.
Nested scopes reuse the outer scope. Values are released when the outer scope
ends, including after errors, and independent calls retain no schedule cache.

Adapters that capture EPW bytes for their run can pass decoded text in a
`StringIO` to `validate_epw_calendar(stream, year)`. The validator consumes the
stream without opening a file or closing the caller's stream. Path-based calls
keep their existing behavior.

Reduced thermal domains can call
`epsm_core.heating_delivery.heating_delivery_for_domain(spec, demand_kwh,
reference_area_m2=area, airflow=flow)` with their validated `AirflowSpec`.
It uses the existing carrier, net-loss and fan accounting without constructing
a compiler report or converting the airflow to a dictionary and back. The
original `heating_delivery` operation retains report-based zone accounting for
EnergyPlus results.
