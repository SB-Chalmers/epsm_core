# File: specs/base.py
# Purpose: Shared immutable validation primitives and explicit numerical units.
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
#   2026-09-06 - Document base interfaces, examples, constraints and processing rationale.

"""Shared immutable validation primitives and explicit numerical units.

Notes
-----
Shared aliases encode positive, nonnegative and fractional scalars plus metric
coordinate tuples. Spec forbids extra fields and nonfinite values and provides validated
immutable replacement. Nested dictionaries are not recursively frozen.

Examples
--------
Example::

    from epsm_core.specs.base import Spec

    spec = Spec()
    assert spec.model_dump() == {}
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

Positive = Annotated[float, Field(gt=0)]
Nonnegative = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Point = tuple[float, float]
Ring = tuple[Point, ...]


class Spec(BaseModel):
    """Base for explicit, validated and immutable input specifications.

    Notes
    -----
    Extra fields and nonfinite numbers are rejected. Frozen models prevent field
    reassignment, but nested dictionaries are not deeply immutable. Use updated for
    validated changes.

    Examples
    --------
    Example::

        from epsm_core.specs.base import Spec

        spec = Spec()
        assert spec.model_dump() == {}
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def updated(self, **changes) -> Self:
        """Create a validated replacement with selected field changes.

        Parameters
        ----------
        **changes : dict
            Field replacements validated against the complete specification.

        Returns
        -------
        Self
            New instance of the same specification class.

        Notes
        -----
        Unlike model_copy(update=...), this reconstructs the complete model and runs validators.
        The original model remains unchanged; nested mutable contents are not recursively frozen
        by Pydantic.

        Examples
        --------
        Example::

            from epsm_core.specs import PVSpec

            pv = PVSpec(dc_capacity_kw=5)
            assert pv.updated(dc_capacity_kw=6).dc_capacity_kw == 6
            assert pv.dc_capacity_kw == 5
        """
        return type(self).model_validate({**self.model_dump(), **changes})
