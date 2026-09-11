# File: settings.py
# Purpose: Engine controls, separate from the physical building description.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-09-11
# Changelog:
#   2026-09-11 - Replace niche engine controls with normalized typed hourly output requests.
#   2026-09-06 - Document settings interfaces, examples, constraints and processing rationale.

"""Engine controls, separate from the physical building description.

Notes
-----
Normalized output additions are separate from the physical building specification and
contribute to run identity. Simulation settings are fixed for annual Ideal Loads UBEM.

Examples
--------
Example::

    from epsm_core.settings import CompilerSettings

    settings = CompilerSettings()
"""

from pydantic import field_validator

from .specs.base import Spec


class HourlyOutputRequest(Spec):
    """Additional hourly EnergyPlus variable; use a specific key for surface outputs."""

    name: str
    key: str = "*"

    @field_validator("name", "key")
    @classmethod
    def normalize(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Output name and key must be nonempty")
        return value.upper()


class CompilerSettings(Spec):
    """Additional outputs for the fixed annual Ideal Loads UBEM configuration."""

    hourly_outputs: tuple[HourlyOutputRequest, ...] = ()

    @field_validator("hourly_outputs")
    @classmethod
    def normalize(cls, requests):
        return tuple(sorted(set(requests), key=lambda request: (request.name, request.key)))
