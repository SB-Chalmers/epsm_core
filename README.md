# epsm_core

Explicit building specifications and direct EnergyPlus 24.2 epJSON simulation for urban building energy modelling. Python 3.11+, with Pydantic, Shapely, NumPy and JSON Schema validation. PVWatts V8 is an optional PySAM stage.

```sh
python -m pip install -e '.[dev,pv]'
export ENERGYPLUS_EXE=/path/to/EnergyPlus/energyplus
epsm-core validate building.json
epsm-core compile building.json output/model
epsm-core run building.json output/run
epsm-core export-idf building.json output/debug
pytest
```

EnergyPlus 24.2 and its adjacent `Energy+.schema.epJSON` are required to compile or run. EPW files are supplied locally and checksummed. Importing the package does not load material registries or contact a network. `epsm-core schema` prints the sole persisted building schema.

```python
from epsm_core import BuildingSpec, EnergyPlusRunner
spec = BuildingSpec.model_validate_json(open("building.json").read())
result = EnergyPlusRunner().run(spec, "output/run")
print(result.scalars["space_heating_demand_eui_kwh_m2"])
```

`BuildingSpec` combines geometry, facade, climate, envelope, airflow, use, context, delivery, renewables and provenance. Inputs are frozen and validated. Use `spec.updated(...)` for a validated replacement. `BuildingBuilder` combines caller-owned assumption profiles with known observations. `apply_renovation` returns a new spec and a recorded physical change.

Supported geometry includes concave polygons, courtyards and disconnected components. Choose whole-building or per-storey zoning. Kiva handles slabs and full basements; cold attics are unconditioned zones with insulation on the top-floor ceiling. `DistrictPlan` runs buildings independently with neighbors as shading context.

Standard targets are space-heating demand, DHW load, and their combined ideal thermal load. Cooling, FVP delivery and PV generation have distinct outputs. Runs retain hourly signals with EnergyPlus names and units, and require zero severe/fatal errors, 8760 valid hours and annual/hourly agreement within 0.1%.

Read [architecture and physics](docs/architecture.md), [usage examples](docs/usage.md), and [implementation status](docs/implementation-status.md). The material/archetype adapter belongs to `EPSM_data`; EPC ingestion, the 10,000-run study, storage and ML belong to the sibling `epsm_workflows` repository.

The old `pbgenerator` API has been removed. Existing v1 datasets remain scientific comparison data.
