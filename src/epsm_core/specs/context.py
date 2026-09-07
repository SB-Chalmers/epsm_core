# File: specs/context.py
# Purpose: Context input specifications.
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
#   2026-09-06 - Document context interfaces, examples, constraints and processing rationale.

"""Context input specifications.

Notes
-----
Context records describe shading-only neighbours with explicit metric footprints and
elevations. Collection validation enforces unique IDs; target-relative and neighbour-
relative overlap checks are performed by the context resolution workflow.

Examples
--------
Example::

    from epsm_core.specs.context import ContextSpec

    context = ContextSpec()
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .base import Positive, Spec
from .geometry import Footprint


class ContextBuilding(Spec):
    """Opaque shading-only neighbour with metric footprint and elevation.

    Attributes
    ----------
    identifier : str
        Stable identifier within the owning collection. Minimum length 1. Required at
        construction.
    footprints : tuple[Footprint, ...]
        Metric footprint records retained separately for each physical component. Minimum
        length 1. Required at construction.
    height_m : Positive
        Height or height bound in metres; context height is measured above its base
        elevation. Strictly positive when supplied. Required at construction.
    base_elevation_m : float
        Context-building bottom elevation in the common metric datum.  Default: ``0``.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Requires a nonempty ID, at least one footprint and positive height above
    base_elevation_m. It carries no thermal construction, conditioned zone or occupancy.

    Examples
    --------
    Example::

        from epsm_core.specs.context import ContextBuilding
        from epsm_core.specs.geometry import Footprint

        neighbour = ContextBuilding(
            identifier="next", footprints=(Footprint.rectangle(5, 5),), height_m=9
        )
    """

    identifier: Annotated[str, Field(min_length=1)]
    footprints: Annotated[tuple[Footprint, ...], Field(min_length=1)]
    height_m: Positive
    base_elevation_m: float = 0


class ContextSpec(Spec):
    """Explicit neighbouring buildings and inspectable generation metadata.

    Attributes
    ----------
    buildings : tuple[ContextBuilding, ...]
        Explicit target or context buildings, according to the owning specification.
        Default: ``()``.
    generation : dict
        Inspectable scenario-generation metadata; not an instruction to generate implicit
        geometry.  Default: a fresh dict per instance.

    Raises
    ------
    pydantic.ValidationError
        If fields, finite-value requirements or the model relationships described below are
        invalid.

    Notes
    -----
    Building IDs must be unique. Geometry overlap is checked against the target by
    validate_context. generation records scenario provenance and does not create buildings
    implicitly.

    Examples
    --------
    Example::

        from epsm_core.specs.context import ContextSpec

        context = ContextSpec()
    """

    buildings: tuple[ContextBuilding, ...] = ()

    generation: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_buildings(self):
        """Require unique neighbour building identifiers.

        Returns
        -------
        Self
            Validated context.

        Raises
        ------
        ValueError
            Rejected conditions: Context building identifiers must be unique.

        Notes
        -----
        This checks identity only. Geometric overlap against other neighbours and the target is
        checked by validate_context.

        Examples
        --------
        Example::

            from epsm_core.specs.context import ContextSpec

            context = ContextSpec()
            assert context.unique_buildings() is context
        """

        ids = [b.identifier for b in self.buildings]
        if len(ids) != len(set(ids)):
            raise ValueError("Context building identifiers must be unique")
        return self
