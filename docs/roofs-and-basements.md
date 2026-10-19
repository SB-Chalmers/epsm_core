# Physical roofs and basements

Core owns physical geometry, installed constructions and the corresponding
EnergyPlus inputs. RC reduces that same resolved building under its explicitly
selected policy. Neither package infers renovation history, occupied roof rooms,
basement conditioning or attic ventilation from a roof outline.

Run the small [physical authoring notebook](../examples/roofs_and_basements.ipynb)
to inspect these inputs without weather or an engine.

## Cold-attic roofs

`RoofSpec(shape="gable"|"hip"|"mono_pitch")` uses a cold attic above a horizontal
occupied ceiling. A flat roof can also select `topology="cold_attic"`. The existing
roof generator retains projected coverage, courtyard holes, actual sloped area,
attic volume, closed shells and strict generated-edge checks. It never replaces
failed pitched geometry with a flat roof.

```python
from epsm_core import Building, Footprint, GeometrySpec, RoofSpec
from epsm_core.specs import UnconditionedExchangeSpec

geometry = GeometrySpec.from_footprint(
    Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
    roof=RoofSpec(shape="gable", pitch_deg=30, direction_deg=90),
)
building = Building(
    preset="illustrative-reference", geometry=geometry,
    unconditioned_exchange=(UnconditionedExchangeSpec(
        zone_kind="attic", outdoor_air_ach=0.5,
        source="illustrative declared outdoor exchange; not measured evidence",
    ),),
)
assert building.readiness("quantities").ready
```

The illustrative preset and 0.5 air changes per hour are selected software-example
inputs. They are not a recommendation for Swedish apartment buildings. An empty
exchange tuple does not assert that the attic is sealed; the authoring state
records that no exchange was supplied. Core passes a supplied rate, schedule and
source into the same `BuildingSpec.unconditioned_exchange` used by EnergyPlus and
the RC handoff. RC may reject missing or unsupported buffer inputs.

Each part retains separate installed elements:

| Element | Physical role and area | Boundary |
| --- | --- | --- |
| `part.top` | `TOP_FLOOR`, horizontal occupied ceiling | Internal |
| `part.roof` | `ROOF`, actual sloped shell area | Outdoors |
| `facade.attic_wall` | `EXT_WALL`, actual gable/attic wall area | Outdoors |

The corresponding thermal faces identify these owners and use their assigned
constructions. Main-storey windows stay on outdoor main walls; no attic glazing
is invented. Virtual zoning and roof triangulation do not add installed material.
The `ROOF` definition is required explicitly. Core does not substitute the
`TOP_FLOOR` recipe when a roof-shell assignment is missing.

The caller must establish whether a catalogue construction describes the ceiling,
the weather shell or both. Assigning insulated `TOP_FLOOR` and insulated `ROOF`
recipes models both; the software cannot establish that this is the actual
building. A legacy specification using its weather-shell recipe on gable walls
can preserve that exact choice through targeted physical assignments. Such a
choice remains an assumption and must retain its source.

Touching pitched parts still require an explicit intersecting-roof ownership
model. Explicit party contacts above a pitched part's eave remain unsupported
because replacing its gable shell does not yet clip those contacts. Ordinary
main-wall contacts up to the eave remain adiabatic and window-free. Hip roofs
require the pinned optional `geometry` dependency.

## Full-footprint basements

`GeometrySpec.basement_depth_m` creates the full-footprint lower volume;
`basement_conditioned` states whether it is conditioned. These controls remain
explicit inputs. Physical inventory retains the basement bottom and perimeter
walls against ground, and the main floor at grade as an internal installed
interface. Attached same-building basement walls have one internal material
owner. A reviewed below-grade party contact can be adiabatic; its negative
elevation bounds must be supplied explicitly.

The basement bottom uses an explicitly supplied `BASEMENT_FLOOR` definition when
present at generation, retaining the released `GROUND_FLOOR` fallback otherwise.
Geometry-first assignment preserves this recorded role rather than silently
relabeling it. The floor at grade uses its actual `GROUND_FLOOR` assignment.
When migrating a legacy specification, preserve its basement/main interface
recipe explicitly, including a legacy `intermediate_floor` recipe if that was
the chosen construction. Do not infer a new insulated floor from its name.

`Building.zone_uses` retains explicitly authored zone controls such as a basement
heating setpoint distinct from the occupied storeys. Copy, snapshot, renovation
and `to_spec(weather)` preserve those assignments. An RC policy must validate and
model supported distinct controls; the bridge does not erase them to obtain a
single conditioned domain. Unconditioned basements remain a separate modelling
case and are not made conditioned to pass readiness.

Snapshot format 8 records these controls and exchange inputs. Formats 1–7 remain
readable; an untouched restored snapshot retains its original identity. A legacy
unsupported roof snapshot retains its original inventory until the user
explicitly regenerates geometry, reviews the new shell targets and assigns the
missing constructions. Input completeness and accepted geometry do not establish
accuracy against EPC measurements.

Old basement snapshots likewise retain their original `Ground` metadata on the
floor at grade. Their unchanged identity is preserved, but current energy
readiness rejects that obsolete boundary instead of silently changing it.
Explicitly reassign `building.geometry = building.geometry`, review the resulting
internal interface and construction, and capture a new snapshot before rerunning.
The old snapshot remains unchanged and can still be inspected as historical
inventory; it does not acquire the newly supported geometry semantics.
