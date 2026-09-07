# File: district.py
# Purpose: Independent target-building runs sharing a geographic shading context.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document district interfaces, examples, constraints and processing rationale.

"""Independent target-building runs sharing a geographic shading context.

Notes
-----
Each target runs independently while other district parts become conservative opaque
shading extrusions. Footprints must already share one georeferenced metric frame with
zero scene orientation. There is no inter-building thermal coupling.

Examples
--------
Example::

    from epsm_core.district import DistrictPlan

    plan = DistrictPlan(buildings=())
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .geometry import local_polygons
from .roofs import roof_faces
from .runner import EnergyPlusRunner
from .specs import BuildingSpec, ContextBuilding, ContextSpec, Spec


class DistrictPlan(Spec):
    """Collection of independent targets sharing geographic shading context.

    Attributes
    ----------
    buildings : tuple[BuildingSpec, ...]
        Explicit target or context buildings, according to the owning specification.
        Required at construction.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Before execution, targets must share one metric CRS, have unique IDs and use zero
    orientation. Other targets become conservative shading extrusions, not coupled thermal
    models.

    Examples
    --------
    Example::

        from epsm_core.district import DistrictPlan

        plan = DistrictPlan(buildings=())
    """

    buildings: tuple[BuildingSpec, ...]

    @staticmethod
    def _context_parts(building):
        """Yield conservative shading extrusions for every physical neighbour part.

        Parameters
        ----------
        building : BuildingSpec
            Validated building input; geometry-only helpers also accept an object exposing the
            fields they consume.

        Yields
        ------
        ContextBuilding
            One context record per building part.

        Notes
        -----
        Uses the actual maximum pitched-roof elevation, or flat attic top, as extrusion height.
        It preserves original footprints and does not model neighbour heat exchange.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            from epsm_core.district import DistrictPlan

            neighbours = tuple(DistrictPlan._context_parts(building))
        """
        # 1. Yield conservative shading extrusions for every physical neighbour part.
        polygons, _ = local_polygons(building.geometry)
        for part, polygon in zip(building.geometry.parts, polygons):
            roof = building.geometry.roof_for(part)
            top = part.storey_elevations_m[-1]
            if roof.shape != "flat":
                top = max(
                    v[2]
                    for face in roof_faces(polygon, roof, top, building.geometry.orientation_deg)
                    for v in face
                )
            elif roof.topology == "cold_attic":
                top += roof.attic_height_m
            yield ContextBuilding(
                identifier=building.identifier + ":" + part.identifier,
                footprints=(part.footprint,),
                height_m=top,
            )

    def resolved_buildings(self):
        """Attach every other district building as shading context to each target.

        Yields
        ------
        BuildingSpec
            Target building with appended neighbour context.

        Raises
        ------
        ValueError
            Rejected conditions: District building identifiers must be unique; District geometry
            must share a single metric coordinate system; District footprints must already be
            georeferenced; use orientation_deg=0.

        Notes
        -----
        Requires unique building IDs, one shared metric CRS and orientation_deg=0. Resolve roof
        maxima once, then validate each target's combined context on immutable replacement.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            from epsm_core.district import DistrictPlan

            targets = tuple(DistrictPlan(buildings=(building,)).resolved_buildings())
        """

        # 1. Attach every other district building as shading context to each target.
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
        # Roof generation can be expensive; resolve each neighbour once per plan.
        neighbours = {b.identifier: tuple(self._context_parts(b)) for b in self.buildings}
        for target in self.buildings:
            context = tuple(
                part
                for b in self.buildings
                if b.identifier != target.identifier
                for part in neighbours[b.identifier]
            )
            yield target.updated(
                context=ContextSpec(
                    buildings=(*target.context.buildings, *context),
                    generation={
                        **target.context.generation,
                        "district_building_count": len(context),
                        "achieved_building_count": len(target.context.buildings) + len(context),
                        "district_representation": "Conservative flat extrusion to each neighbour's actual roof maximum",
                    },
                )
            )

    def run(self, directory, *, energyplus=None, workers=1):
        """Run independent target simulations in a bounded thread pool.

        Parameters
        ----------
        directory : str or Path or None
            Local artifact directory; consult Notes for creation, overwrite and default-path
            behavior.
        energyplus : str or Path or None
            EnergyPlus 24.2 executable; None uses ENERGYPLUS_EXE then PATH. Default: ``None``.
        workers : int
            Maximum thread-pool worker count for independent building runs. Default: ``1``.

        Returns
        -------
        dict
            Building identifiers mapped to SimulationResult objects.

        Notes
        -----
        Creates run-ID subdirectories beneath directory. Requires EnergyPlus 24.2 and valid
        EPWs. Worker exceptions propagate; completed or failed artifacts remain on disk.

        Examples
        --------
        Supply a validated BuildingSpec as ``building``.

        Example::

            from epsm_core.district import DistrictPlan

            results = DistrictPlan(buildings=(building,)).run("output/district", workers=1)
        """

        # 1. Run independent target simulations in a bounded thread pool.
        runner = EnergyPlusRunner(energyplus)

        def run_one(building):
            """Run one context-resolved building under its compiler-derived identity.

            Parameters
            ----------
            building : BuildingSpec
                Validated building input; geometry-only helpers also accept an object exposing the
                fields they consume.

            Returns
            -------
            tuple
                Building identifier and validated SimulationResult.

            Notes
            -----
            Uses the enclosing runner and output directory; the run directory must be empty.

            Examples
            --------
            Within the enclosing operation, after its captured state has been initialized::

                run_one(building)
            """

            run_id = runner.compiler.run_id(building)
            return building.identifier, runner.run(building, Path(directory) / run_id)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(pool.map(run_one, self.resolved_buildings()))
