"""Independent target-building runs sharing a geographic shading context."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .runner import EnergyPlusRunner
from .specs import BuildingSpec, ContextBuilding, ContextSpec, Spec


class DistrictPlan(Spec):
    buildings: tuple[BuildingSpec, ...]

    def resolved_buildings(self):
        ids = [b.identifier for b in self.buildings]
        if len(set(ids)) != len(ids):
            raise ValueError("District building identifiers must be unique")
        crs = {b.geometry.source_crs for b in self.buildings}
        if len(crs) != 1:
            raise ValueError("District geometry must share a single metric coordinate system")
        if any(b.geometry.orientation_deg for b in self.buildings):
            raise ValueError(
                "District footprints must already be georeferenced; use orientation_deg=0"
            )
        for target in self.buildings:
            context = tuple(
                ContextBuilding(
                    identifier=b.identifier,
                    footprints=b.geometry.footprints,
                    height_m=b.geometry.floors * b.geometry.floor_height_m
                    + (
                        b.geometry.attic_height_m if b.envelope.roof_topology == "cold_attic" else 0
                    ),
                )
                for b in self.buildings
                if b.identifier != target.identifier
            )
            yield target.updated(
                context=ContextSpec(buildings=(*target.context.buildings, *context))
            )

    def run(self, directory, *, energyplus=None, workers=1):
        runner = EnergyPlusRunner(energyplus)

        def run_one(building):
            run_id = runner.compiler.run_id(building)
            return building.identifier, runner.run(building, Path(directory) / run_id)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(pool.map(run_one, self.resolved_buildings()))
