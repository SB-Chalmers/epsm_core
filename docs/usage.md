# Building, renovation and district examples

`examples/building.py` declares a complete building using caller-owned materials.
Its constants are demonstration assumptions, not Swedish archetype defaults.

```sh
python examples/building.py /path/to/weather.epw building.json
epsm-core run building.json output/example
```

Replace glazing while retaining the original building:

```python
from epsm_core import GlazingSpec, ReplaceGlazing, apply_renovation
renovated = apply_renovation(spec, ReplaceGlazing(glazing=GlazingSpec(
    u_value_w_m2k=1.1, solar_heat_gain_coefficient=0.5)))
```

Facade IDs such as `c0.r0.e0` identify component, ring and edge before rotation.
Interior rings use r1, r2, etc. `FacadeOverride(facade_id=..., wwr=...)` rotates with
the building. The compiler reports the resulting cardinal window areas.

Use `Footprint(exterior=..., holes=(ring,))` for courtyards, and several entries in
`GeometrySpec.footprints` for disconnected parts. Parts share floors, heights and
physics in this release. `basement_depth_m` creates a full basement;
`basement_conditioned` controls HVAC and inclusion in Atemp. `zoning="per_storey"`
creates individual floor zones. `Footprint.scaled_to_area()` preserves the shape
and rescales every ring. See architecture.md for Kiva tessellation assumptions.

```python
from epsm_core import DistrictPlan
results = DistrictPlan(buildings=(building_a, building_b)).run("output/district", workers=2)
```

District inputs must share a projected metric CRS and already contain geographic
orientations (`orientation_deg=0`). The external EPC adapter requires a source CRS
and returns a reconciliation report for observed versus geometric Atemp.

The optional `epsm_data.epsm_core_adapter` converts complete physical components
into core constructions. Supply explicit role mappings and outside-to-inside
component order. Composite layers become equivalent homogeneous thermal layers.

Failures retain `eplusout.err` and `process.log`, without a successful result marker.
Direct reruns require a fresh directory; epsm_workflows owns campaign retry/resume.
