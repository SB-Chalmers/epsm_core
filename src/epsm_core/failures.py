# File: failures.py
# Purpose: Stable failure categories for compilation and simulation validation.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-11 (documentation-header creation; not original file creation)
# Date modified: 2026-09-11
# Changelog:
#   2026-09-11 - Document failure categories and machine-readable validation exceptions.

"""Stable failure categories; a simulation failure does not imply bad geometry."""

GEOMETRY_INVARIANT_FAILURE = "GEOMETRY_INVARIANT_FAILURE"
ENERGYPLUS_SCHEMA_FAILURE = "ENERGYPLUS_SCHEMA_FAILURE"
SHADOW_COMPLEXITY_LIMIT = "SHADOW_COMPLEXITY_LIMIT"
ENERGYPLUS_NUMERICAL_FAILURE = "ENERGYPLUS_NUMERICAL_FAILURE"
WARNING_POLICY_REJECTION = "WARNING_POLICY_REJECTION"
MISSING_EXPECTED_OUTPUT = "MISSING_EXPECTED_OUTPUT"
EXTERNAL_ENVIRONMENT_FAILURE = "EXTERNAL_ENVIRONMENT_FAILURE"


class ValidationFailure(ValueError):
    """Rejected input or output with a machine-readable failure code."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


class CompilationError(ValidationFailure):
    """Compiler geometry or schema failure."""


class ResultValidationError(ValidationFailure):
    """Simulation output or initialized geometry failure."""


def engine_failure_code(diagnostics):
    categories = {m["category"] for m in diagnostics.get("messages", []) if not m["approved"]}
    if "shadow_overlap_limit" in categories:
        return SHADOW_COMPLEXITY_LIMIT
    if "missing_output" in categories:
        return MISSING_EXPECTED_OUTPUT
    if categories & {
        "invalid_geometry",
        "geometry_repair",
        "geometry_mismatch",
        "discarded_surface",
    }:
        return GEOMETRY_INVARIANT_FAILURE
    if (
        diagnostics.get("process_returncode")
        or diagnostics.get("severe_count")
        or diagnostics.get("fatal_count")
        or "convergence_failure" in categories
    ):
        return ENERGYPLUS_NUMERICAL_FAILURE
    if diagnostics.get("messages"):
        return WARNING_POLICY_REJECTION
    return ENERGYPLUS_NUMERICAL_FAILURE
