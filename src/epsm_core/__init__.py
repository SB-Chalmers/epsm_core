# File: __init__.py
# Purpose: Building specifications, bundled operational standards and EnergyPlus simulation.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-03
# Changelog:
#   2026-10-03 - Add documented calendar, operational and archetype-application support.
#   2026-09-15 - Export the bundled Sveby residential standard API.
#   2026-09-11 - Export the typed HourlyOutputRequest API.
#   2026-09-06 - Document __init__ interfaces, examples, constraints and processing rationale.

"""Building specifications, operational standards and EnergyPlus simulation.

Notes
-----
The package exposes explicit input specifications, a lazily loaded bundled Sveby
residential profile and compile/run helpers. Importing the package does not read the
profile or weather and does not launch EnergyPlus. Geometry inspection can operate
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
from .building import (
    AuthoringLink,
    Building,
    BuildingElement,
    BuildingSnapshot,
    Equipment,
    HVACSystem,
    OperationProfile,
    Readiness,
    RenovationStage,
)
from .building_adapter import run_building, thermal_construction
from .compiler import CompilationReport, EnergyPlusCompiler
from .dhw import DHWProfileSpec, load_dhw_profile
from .district import DistrictPlan
from .generic_programme import GenericOtherProgramme, load_generic_other_v1
from .inventory import MaterialFlows, MaterialInventory, MaterialQuantity
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
    FootprintCleanupSpec,
    FoundationSpec,
    FVPSpec,
    GeometrySpec,
    GlazingSpec,
    GroundTemperatureSpec,
    HeatingDeliverySpec,
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
    SchedulePeriod,
    ScheduleSpec,
    SourceRecord,
    UnconditionedExchangeSpec,
    UseSpec,
    WindowLayoutSpec,
    WindowPattern,
    ZoneUseSpec,
    ZoningSpec,
)
from .standards import SvebyResidentialSpec, load_sveby_residential_v2, load_sveby_spec
from .weather import Weather, climate_from_epw

__all__ = [
    "AuthoringLink", "Building", "BuildingElement", "BuildingSnapshot", "HVACSystem", "OperationProfile",
    "Readiness", "RenovationStage", "MaterialFlows", "MaterialInventory", "MaterialQuantity",
    "Weather",
    "Equipment",
    "run_building", "thermal_construction",
    "DHWProfileSpec",
    "load_dhw_profile",
    "GenericOtherProgramme",
    "load_generic_other_v1",
    "SvebyNonResidentialSpec", "load_sveby_office_v1", "load_sveby_school_v1",
    "FootprintCleanupSpec",
    "synthetic_context",
    "preview_geometry",
    "CompilerSettings",
    "HourlyOutputRequest",
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
    "SvebyResidentialSpec",
    "load_sveby_residential_v2",
    "load_sveby_spec",
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
    "HeatingDeliverySpec",
    "EnvelopeSpec",
    "FacadeOverride",
    "FacadeSpec",
    "Footprint",
    "FVPSpec",
    "GeometrySpec",
    "ZoningSpec",
    "GlazingSpec",
    "FoundationSpec",
    "GroundTemperatureSpec",
    "LayerSpec",
    "MaterialSpec",
    "ProvenanceSpec",
    "PVSpec",
    "RenewablesSpec",
    "ScheduleSpec",
    "SchedulePeriod",
    "SourceRecord",
    "UseSpec",
    "ProgramBlend",
    "ProgramComponent",
    "ZoneUseSpec",
    "UnconditionedExchangeSpec",
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
from .nonresidential import SvebyNonResidentialSpec, load_sveby_office_v1, load_sveby_school_v1

# Explicit area-weighted mixed-use operation (no implicit spatial allocation).
from .programs import ProgramBlend as ProgramBlend
from .programs import ProgramComponent as ProgramComponent
from .settings import CompilerSettings, HourlyOutputRequest
