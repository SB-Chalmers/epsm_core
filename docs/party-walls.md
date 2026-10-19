# Shared-wall assumptions

Core 0.6.0 separates installed wall material from its thermal exposure. A
confirmed geometric contact with another building is assumed **adiabatic** for
this single-building model. The neighbouring building's heating status may be
unknown. Core does not infer or solve a neighbouring indoor temperature.

Only the contacting area becomes adiabatic. Horizontal contact distances are
measured along the directed facade returned by `geometry.facades()`, and
vertical distances are elevations in the same grade-relative metre frame as
the storeys. The outdoor remainder retains its construction and window rules.
Windows are generated only on resolved outdoor wall regions; the physical
inventory and thermal compiler use the same outdoor-region placement calculation.
Installed logical window area is independent of computational zoning. At a
computational parent split, EnergyPlus panes retain the existing small edge
clearance needed to lie strictly inside their parent surfaces. Consequently the
emitted panes may have slightly less area than their installed logical owner;
facade reports record `opening_suppression_reason` when that clearance applies.
Resolved opening areas and physical element areas remain separately inspectable.
The study's whole-building route has no perimeter/core pane splits.

```python
from epsm_core import Building, Footprint, GeometrySpec, PartyWallNeighbor

building = Building(preset="illustrative-reference")
building.geometry = GeometrySpec.from_footprint(
    Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
)
neighbor = PartyWallNeighbor(
    identifier="next",
    footprint=Footprint(exterior=((2, -5), (8, -5), (8, 0), (2, 0))),
    top_m=4,
)
building.geometry = building.geometry.with_party_wall_contacts(
    (neighbor,), assumption_source="supplied wall outlines and eave heights; adiabatic assumption",
)
assert sum(e.area_m2 for e in building.elements if e.boundary == "Adiabatic") == 24
```

The runnable [example](../examples/shared_walls.py) also checks window exposure
and snapshot round trips. Detection is a pure operation: it does not retrieve
neighbours, interpret register heights or change its inputs. Callers must supply
wall outlines and heights in the target's metric coordinate frame, with their
source identity and any assumptions. A roof-edge proxy is not verified wall
contact. Missing heights must remain missing or be explicitly supplied and
labelled as a sensitivity assumption.

Exact opposing collinear edges are required by default. `tolerance_m` can be
explicitly set from 0 to 0.1 metres for a parallel-gap sensitivity. Detection
never replaces a complete facade because a building is nearby. Point contact,
nonparallel edges and overlapping footprints do not establish a shared wall.
Multiple contact rectangles may overlap; their union is counted once.
Existing manually supplied contacts remain present in the returned geometry.

For manual assignment, `PartyWall` accepts `start_m`, `end_m`, `bottom_m` and
`top_m`. Omitted horizontal end and vertical bounds mean the facade's full
above-ground extent. `contact_confirmed=True` and a nonempty
`assumption_source` are required to resolve the wall. The legacy
`neighbor_conditioning` evidence field remains readable and does not determine
this boundary assumption.

Every physical element exposes `boundary`: `Outdoors`, `Ground`, `Adiabatic`
or `Internal`. A partial contact produces ordinary outdoor `.wall` and separate
`.adiabatic_wall` elements, both retaining the wall construction. Their areas
plus outdoor windows conserve the gross facade area. Material ownership is not
shared between separately simulated buildings; each model contains its supplied
wall construction. A single Building with attached conditioned parts owns each
internal shared wall once. The wall remains internal thermal mass, including
both radiating sides in EnergyPlus, while reciprocal computational faces do not
duplicate its material inventory.

The physical authoring adapter supports flat compact attached parts, explicit
basement interfaces and detached cold-attic roof shells. Touching pitched roofs,
attached unconditioned parts, apartment partitions and above-eave pitched attic
contacts retain the limitations described in [roof and basement support](roofs-and-basements.md).
Existing legacy `BuildingSpec` geometry routes retain their separately documented
capabilities.

Physical snapshot format `epsm.building/7` adds the boundary field. Formats
1–6 remain readable; missing boundaries are inferred by physical role, and an
untouched restored snapshot retains its original identity. Editing geometry
regenerates exposure and emits current format 8, which also retains declared
auxiliary-zone operations. An old snapshot with contradictory
party-wall/window quantities fails readiness until that explicit geometry edit;
restoration does not silently rewrite old evidence. Geometry/cache identities
include contact extents, and implementation fingerprints invalidate old graphs.

This fixes physical bookkeeping and heat-transfer boundaries. It does not
establish that an inferred contact or a catalogue wall construction describes
a particular real building accurately.
