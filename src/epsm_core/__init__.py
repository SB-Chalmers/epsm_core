# File: __init__.py
# Purpose: Building specifications and EnergyPlus simulation, without implicit data loading.
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
#   2026-09-06 - Document __init__ interfaces, examples, constraints and processing rationale.

"""Building specifications and EnergyPlus simulation, without implicit data loading.

Notes
-----
The package exposes explicit input specifications and compile/run helpers. Importing the
package does not read weather or launch EnergyPlus. Geometry inspection can operate
without thermal materials or engine installation.

Examples
--------
Example::

    from epsm_core import Footprint, GeometrySpec

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
    )
    assert geometry.conditioned_floor_area_m2 == 160
"""

from ._version import __version__ as __version__
from .builder import BuildingBuilder
from .compiler import CompilationReport, EnergyPlusCompiler
from .district import DistrictPlan
from .preparation import GeometryPolicy, GeometryPreparationResult, prepare_geometry
from .pv import run_pvwatts
from .quantities import quantity_takeoff
from .renovation import (
    AddInsulation,
    ChangeAirflow,
    InstallFVP,
    InstallPV,
    ReplaceGlazing,
    apply_renovation,
)
from .results import SimulationResult
from .runner import EnergyPlusRunner, SimulationError
from .specs import (
    AirflowSpec,
    ApartmentLayoutSpec,
    ApartmentType,
    AssessmentReference,
    BalconySpec,
    BuildingPart,
    BuildingSpec,
    ClimateSpec,
    ConstructionSpec,
    ContextBuilding,
    ContextSpec,
    DatasetReference,
    DeliverySpec,
    EnvelopeSpec,
    FacadeOverride,
    FacadeSpec,
    Footprint,
    FVPSpec,
    GeometrySpec,
    GlazingSpec,
    GroundTemperatureSpec,
    LayerSpec,
    MaterialSpec,
    OverhangSpec,
    PartyWall,
    PhysicalQuantity,
    ProvenanceSpec,
    PVSpec,
    QuantityChange,
    RenewablesSpec,
    RenovationRecord,
    RoofSpec,
    ScheduleSpec,
    SourceRecord,
    UseSpec,
    WindowLayoutSpec,
    WindowPattern,
    ZoningSpec,
)
from .weather import climate_from_epw

__all__ = [
    "synthetic_context",
    "preview_geometry",
    "CompilerSettings",
    "RoofSpec",
    "WindowLayoutSpec",
    "WindowPattern",
    "OverhangSpec",
    "BalconySpec",
    "ApartmentType",
    "ApartmentLayoutSpec",
    "GeometryPolicy",
    "GeometryPreparationResult",
    "prepare_geometry",
    "quantity_takeoff",
    "BuildingBuilder",
    "CompilationReport",
    "EnergyPlusCompiler",
    "EnergyPlusRunner",
    "SimulationError",
    "SimulationResult",
    "DistrictPlan",
    "AirflowSpec",
    "AssessmentReference",
    "DatasetReference",
    "PhysicalQuantity",
    "QuantityChange",
    "RenovationRecord",
    "BuildingSpec",
    "BuildingPart",
    "PartyWall",
    "ClimateSpec",
    "ConstructionSpec",
    "ContextBuilding",
    "ContextSpec",
    "DeliverySpec",
    "EnvelopeSpec",
    "FacadeOverride",
    "FacadeSpec",
    "Footprint",
    "FVPSpec",
    "GeometrySpec",
    "ZoningSpec",
    "GlazingSpec",
    "GroundTemperatureSpec",
    "LayerSpec",
    "MaterialSpec",
    "ProvenanceSpec",
    "PVSpec",
    "RenewablesSpec",
    "ScheduleSpec",
    "SourceRecord",
    "UseSpec",
    "climate_from_epw",
    "AddInsulation",
    "ChangeAirflow",
    "InstallFVP",
    "InstallPV",
    "ReplaceGlazing",
    "apply_renovation",
    "run_pvwatts",
]

from .context import synthetic_context
from .inspection import preview_geometry
from .settings import CompilerSettings
