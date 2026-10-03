# Footprint preparation and perimeter zoning

New GeometrySpec inputs enable `FootprintCleanupSpec()` by default: topology-preserving simplification at 0.01 m with a maximum 0.001 relative area change. Source rings stay in `geometry.parts`; `geometry.footprints`, heated-area properties, geometry preview, quantities and compilation use the prepared rings. Invalid source polygons are rejected rather than repaired automatically.

```python
from epsm_core import FootprintCleanupSpec

# Reproduce source rings explicitly.
geometry = geometry.updated(footprint_cleanup=FootprintCleanupSpec(enabled=False))
# Stronger preparation must be requested explicitly.
geometry = geometry.updated(footprint_cleanup=FootprintCleanupSpec(
    tolerance_m=0.1, max_area_change_fraction=0.01))
```

The pass removes duplicates and collinear vertices, preserves hole counts and shared part contacts, and checks bidirectional boundary displacement and area change. Changes to explicitly referenced façade IDs are rejected; disable cleanup or supply separately prepared geometry and reviewed references. No area scaling to external observations occurs.

Compilation reports include cleanup version, settings, source hash, original/prepared vertex counts, areas, perimeters and displacement. The settings and implementation version are included in the physical specification hash. Default-enabled cleanup changes hashes even when the outline remains geometrically identical. Existing saved specifications acquire this default when loaded; choose disabled mode to retain their original rings. Keep the old compiler version to reproduce historical generated geometry exactly.

Perimeter/core zoning remains optional; per-storey remains the default. Perimeter geometry is placed on one 1e-8 m scene grid before subdivision. Generated intersections within 0.010001 m of source corners are aligned coherently across all partitions. This may make a tiny local change in thermal partition depth; coverage and overlap checks enforce the physical floor outline. The grid and alignment bound are recorded in the zoning report. Redundant generated surface vertices are removed before serialization, preserving normals and shared boundaries. Boundary identities and clipped-window containment use a 1e-7 m numerical tolerance; real gaps, overlaps, nonplanarity and short edges still fail validation.

Basements remain whole-floor zones and attics retain their roof-based subdivision. Their contacts with partitioned residential floors use reciprocal shared surface geometry. Kiva exposed perimeter is computed from the physical exterior, excluding internal zone boundaries.
