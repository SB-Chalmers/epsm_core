# File: vertex_order.py
# Purpose: Deterministic cyclic vertex ordering without geometric mutation.
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
#   2026-09-11 - Document cyclic-only serialization and vertex-preservation assertions.

"""Canonical EnergyPlus vertex order without changing geometry or face normals."""

import numpy as np

from .surface_checks import properties


def upper_left_vertices(points):
    """Rotate an outward CCW ring to the upper-left corner as viewed outside.

    Match the EnergyPlus export convention used by Honeybee: world Z is up
    for walls/slopes; world Y is up for horizontal faces (within 0.01 m).
    Only cyclic rotation is allowed; winding, coordinates and area are preserved.
    """
    v = np.asarray(points, dtype=float)
    _, normal, _ = properties(v)
    if np.ptp(v[:, 2]) <= 0.01:
        xy = v[:, :2].copy()
        xy[:, 0] *= 1 if normal[2] >= 0 else -1
    else:
        up = np.array([0.0, 0.0, 1.0]) - normal[2] * normal
        up /= np.linalg.norm(up)
        right = np.cross(up, normal)
        delta = v - v.mean(axis=0)
        xy = np.column_stack((delta @ right, delta @ up))
    corner = np.array([xy[:, 0].min(), xy[:, 1].max()])
    distances = np.sum((xy - corner) ** 2, axis=1)
    # A geometric tie uses coordinates, independent of the incoming start index.
    near = np.flatnonzero(np.isclose(distances, distances.min(), rtol=1e-12, atol=1e-12))
    start = min(near, key=lambda i: tuple(v[i]))
    return np.roll(v, -int(start), axis=0)


def serialize_vertices(points):
    """Serialize a physical ring by cyclic start rotation only, with an assertion.

    Horizontal faces use world Y as local up and normal-dependent world X as
    local right. Coordinates are never quantized or reconstructed here.
    """
    original = np.asarray(points, dtype=float)
    ordered = upper_left_vertices(original)
    if not any(np.array_equal(ordered, np.roll(original, i, axis=0)) for i in range(len(original))):
        raise ValueError("Serializer changed physical vertices or winding")
    return tuple(tuple(float(value) for value in point) for point in ordered)
