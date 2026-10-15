# File: specs/__init__.py
# Purpose: The current building input schema, organized by domain.
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
#   2026-09-06 - Document __init__ interfaces, examples, constraints and processing rationale.

"""The current building input schema, organized by domain.

Notes
-----
This module re-exports the canonical validated input models. Numeric values carry
explicit units and defaults; cross-system relationships are checked on BuildingSpec.
Instantiating records does not implicitly fetch datasets, weather or assessment factors.

Examples
--------
Example::

    from epsm_core.specs import Footprint, ScheduleSpec

    assert Footprint.rectangle(10, 8).area_m2 == 80
    assert len(ScheduleSpec.constant(21).values) == 24
"""

from .base import Fraction as Fraction
from .base import Nonnegative as Nonnegative
from .base import Point as Point
from .base import Positive as Positive
from .base import Ring as Ring
from .base import Spec as Spec
from .building import BuildingSpec as BuildingSpec
from .context import ContextBuilding as ContextBuilding
from .context import ContextSpec as ContextSpec
from .facade import BalconySpec as BalconySpec
from .facade import FacadeOverride as FacadeOverride
from .facade import FacadeSpec as FacadeSpec
from .facade import GlazingSpec as GlazingSpec
from .facade import OverhangSpec as OverhangSpec
from .facade import WindowLayoutSpec as WindowLayoutSpec
from .facade import WindowPattern as WindowPattern
from .geometry import ApartmentLayoutSpec as ApartmentLayoutSpec
from .geometry import ApartmentType as ApartmentType
from .geometry import BuildingPart as BuildingPart
from .geometry import Footprint as Footprint
from .geometry import FootprintCleanupSpec as FootprintCleanupSpec
from .geometry import GeometrySpec as GeometrySpec
from .geometry import PartyWall as PartyWall
from .geometry import RoofSpec as RoofSpec
from .geometry import ZoningSpec as ZoningSpec
from .operations import UnconditionedExchangeSpec as UnconditionedExchangeSpec
from .operations import ZoneUseSpec as ZoneUseSpec
from .physics import AirflowSpec as AirflowSpec
from .physics import ClimateSpec as ClimateSpec
from .physics import ConstructionSpec as ConstructionSpec
from .physics import DeliverySpec as DeliverySpec
from .physics import EnvelopeSpec as EnvelopeSpec
from .physics import FoundationSpec as FoundationSpec
from .physics import FVPSpec as FVPSpec
from .physics import GainPartitionSpec as GainPartitionSpec
from .physics import GroundTemperatureSpec as GroundTemperatureSpec
from .physics import HeatingDeliverySpec as HeatingDeliverySpec
from .physics import LayerSpec as LayerSpec
from .physics import MaterialSpec as MaterialSpec
from .physics import PVSpec as PVSpec
from .physics import RenewablesSpec as RenewablesSpec
from .physics import ScheduleSpec as ScheduleSpec
from .physics import UseSpec as UseSpec
from .provenance import AssessmentReference as AssessmentReference
from .provenance import DatasetReference as DatasetReference
from .provenance import PhysicalQuantity as PhysicalQuantity
from .provenance import ProvenanceSpec as ProvenanceSpec
from .provenance import QuantityChange as QuantityChange
from .provenance import RenovationRecord as RenovationRecord
from .provenance import SourceRecord as SourceRecord
from .schedules import SchedulePeriod as SchedulePeriod
