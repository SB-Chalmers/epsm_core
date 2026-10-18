# Reusing prepared geometry

`Building.to_spec()` resolves geometry once and uses that graph for physical
surface and internal-mass assignments. Materials and schedules remain inputs to
each conversion.

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

Cache lookups read installed Core source contents to invalidate edited developer
checkouts. Construction does no I/O. Cached resolution is therefore an explicit
preparation operation, while ordinary uncached resolution retains its no-I/O
contract. `clear()` releases entries and resets the hit/miss counters.
