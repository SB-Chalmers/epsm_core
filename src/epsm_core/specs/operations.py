# File: specs/operations.py
# Purpose: Explicit zone operation and unconditioned air-exchange inputs.
# SPDX-License-Identifier: MIT
# Date created: 2026-10-03
"""Zone assignments preserve physical geometry and carry a declared input source.

Sveby school inputs distinguish classrooms, kitchens, sport and service spaces
(2016 version 1.0, Tables 2.1-2.3). Geometry does not establish those uses. Callers
must assign a named resolved zone or an existing geometry zone kind explicitly.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .base import Nonnegative, Positive, Spec
from .physics import AirflowSpec, UseSpec
from .schedules import ScheduleSpec


class ZoneUseSpec(Spec):
    """Override use/airflow by exact zone name or geometry zone kind.

    Exact names take precedence over kind assignments; duplicate selectors and
    selectors without matches are errors. ``reference_area_m2`` optionally gives
    a zone-specific load basis (e.g. verified Atemp), without resizing geometry.
    """

    zone_name: Annotated[str, Field(min_length=1)] | None = None
    zone_kind: Annotated[str, Field(min_length=1)] | None = None
    use: UseSpec | None = None
    airflow: AirflowSpec | None = None
    reference_area_m2: Positive | None = None
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]

    @model_validator(mode="after")
    def selector(self):
        """Require exactly one selector and an operational override."""
        if (self.zone_name is None) == (self.zone_kind is None):
            raise ValueError("Choose exactly one zone_name or zone_kind")
        if self.use is None and self.airflow is None:
            raise ValueError("Zone assignment requires use or airflow")
        if self.reference_area_m2 is not None and self.zone_name is None:
            raise ValueError("Zone-specific reference area requires an exact zone_name")
        return self


class UnconditionedExchangeSpec(Spec):
    """Declared outdoor exchange for an unconditioned attic or basement.

    This is an outdoor exchange scenario, not calibrated conditioned-envelope
    infiltration. See EPSM Data release.apply_attic_ventilation for the legacy
    adapter replaced by this native compiler input. No default rate is inferred.
    """

    zone_kind: Annotated[str, Field(pattern="^(attic|basement)$")]
    outdoor_air_ach: Nonnegative
    fraction: ScheduleSpec = ScheduleSpec.constant(1)
    source: Annotated[str, Field(min_length=1, pattern=r"\S")]

    @model_validator(mode="after")
    def bounds(self):
        """Check fraction bounds independently of its calendar form."""
        if any(not 0 <= v <= 1 for v in self.fraction.all_values):
            raise ValueError("Unconditioned exchange fraction must lie in [0,1]")
        return self
