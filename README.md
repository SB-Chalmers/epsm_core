# epsm_core

A pre-1.0 building-energy modelling library for automated urban building energy modelling. The development version is **0.1.0.dev0**; content hashes distinguish simulation inputs and implementations.

Start with a metric footprint and storeys, choose procedural facade and zoning assumptions, add neighbouring buildings, and inspect the geometry before simulation. EPSM preserves concave outlines, courtyards and disconnected parts. Per-storey zoning is the default; perimeter/core zoning is available explicitly. Generated apartment layouts are experimental.

![Workflow from known footprint and storeys through geometry inspection to a complete building specification and simulation.](docs/figures/workflow.svg)

Geometry inspection is the first checkpoint; constructions, weather and operations complete the input before simulation. The [38 notebook lessons](demo/README.md) explain each API step with code, plots and guided documentation figures, from one building to diverse stock samples.

Residential operations are batteries-included: `BuildingBuilder()` uses the bundled, version-pinned Sveby 2.0 normal-use profile when no explicit assumption profile is supplied. Physical fabric, weather, leakage and installed systems remain explicit. See [bundled operational standards](docs/standards.md) for the exact values, non-Sveby completion defaults and compliance limitations.

```python
from epsm_core import Footprint, GeometrySpec, ZoningSpec, synthetic_context

geometry = GeometrySpec.from_footprint(
    Footprint.rectangle(30, 20), storeys=3, storey_height_m=3,
    zoning=ZoningSpec(mode="perimeter_core", depth_m=4.5),
)
context = synthetic_context(geometry, preset="urban_lowrise_dense", seed=0)
with geometry.view("output/preview", context=context) as preview:
    print(preview.url)
    input("Press Enter to stop the preview. ")
```

Geometry inspection needs no EnergyPlus installation or weather. Simulation uses a validated immutable `BuildingSpec`, a local EPW, and EnergyPlus 24.2. Python 3.11 or later is required.

```sh
python -m pip install -e '.[dev,geometry]'
python examples/building.py data/weather/SWE_VG_Gothenburg-Landvetter.AP.025260_TMYx.2004-2018.epw output/building.json
epsm-core validate output/building.json
epsm-core --energyplus /path/to/energyplus run output/building.json output/run
```

Read [usage](docs/usage.md), [bundled operational standards](docs/standards.md), the [geometry feature contract](docs/geometry.md), [API guide](docs/api.md), and [architecture and physics](docs/architecture.md).

The package owns building inputs, geometry, compilation, execution and results. `epsm_data` supplies physical catalogues; `epsm_workflows` owns ingestion, studies, storage and batch policy. Importing core does not discover datasets or use the network.

Maintain source in `src/`, tests in `tests/`, and executable examples in `examples/`. External inputs belong in ignored `data/`; generated artifacts belong in ignored `output/`. Historical evidence is kept separately in `ARCHIVE/`. Current tests and examples do not depend on archived studies.

## Ground heat transfer

New envelopes default to `FoundationSpec(method="kiva")`. Soil and footing assumptions remain configurable and reported. Explicit legacy `GroundTemperatureSpec` profiles retain prescribed-temperature behaviour. See [foundation settings and migration](docs/foundations.md).

Versioned Sveby office and primary/secondary-school profiles, explicit calendars,
zone operation, Atemp load areas and space-heat delivery accounting are documented
in [building archetype operation](docs/archetype-operation.md). Source references
and completion assumptions also live in the implementing scripts and resources.
