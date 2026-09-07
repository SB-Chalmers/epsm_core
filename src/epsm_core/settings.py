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
# Date modified: 2026-09-06
# Changelog:
#   2026-09-06 - Document settings interfaces, examples, constraints and processing rationale.

"""Engine controls, separate from the physical building description.

Notes
-----
Engine controls are deliberately separate from the physical building specification. They
affect compiler run identity. The shadow-overlap limit bounds engine complexity and is
validated independently of facade geometry.

Examples
--------
Example::

    from epsm_core.settings import CompilerSettings

    settings = CompilerSettings(shadow_max_figures=10000000)
"""

from typing import Annotated

from pydantic import Field

from .specs.base import Spec


class CompilerSettings(Spec):
    """Engine execution controls kept separate from physical building inputs.

    Attributes
    ----------
    shadow_max_figures : int
        Maximum EnergyPlus polygon shadow-overlap figure count; higher limits can increase
        runtime/memory. At least 15000. At most 20000000. Default: ``10000000``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    shadow_max_figures is bounded from 15,000 to 20,000,000 and contributes to run identity.
    Raising it permits more polygon shadow intersections but can increase simulation time
    and memory.

    Examples
    --------
    Example::

        from epsm_core.settings import CompilerSettings

        settings = CompilerSettings(shadow_max_figures=10000000)
    """

    shadow_max_figures: Annotated[int, Field(ge=15000, le=20000000)] = 10000000
