# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
"""Pure geometric contact detection and facade-plane contact extents.

Contact is a geometric observation. Treating it as adiabatic is an explicit
single-building modelling assumption and does not assert a neighbour temperature.
"""
from __future__ import annotations

import math

from .geometry import facade_edges
from .specs.geometry import PartyWall, PartyWallNeighbor


def detect_contacts(geometry, neighbors, *, tolerance_m, assumption_source):
    if not math.isfinite(tolerance_m) or not 0 <= tolerance_m <= 0.1:
        raise ValueError("tolerance_m must be between 0 and 0.1 m")
    if not assumption_source.strip():
        raise ValueError("Contact detection requires an assumption_source")
    contacts = []
    for neighbor in sorted(neighbors, key=lambda item: item.identifier):
        if not isinstance(neighbor, PartyWallNeighbor):
            raise TypeError("neighbors must contain PartyWallNeighbor objects")
        polygon = neighbor.footprint.polygon
        # Overlap with any target part is unresolved geometric/identity evidence.
        if any(part.footprint.polygon.intersection(polygon).area > 1e-8 for part in geometry.parts):
            continue
        for part in geometry.parts:
            bottom = max(part.storey_elevations_m[0], neighbor.bottom_m)
            top = min(part.storey_elevations_m[-1], neighbor.top_m)
            if top - bottom <= 1e-7:
                continue
            for fid, a, b in facade_edges(part.footprint.polygon, part.identifier):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = math.hypot(dx, dy)
                ux, uy = dx / length, dy / length
                for _, c, d in facade_edges(polygon, neighbor.identifier):
                    vx, vy = d[0] - c[0], d[1] - c[1]
                    other_length = math.hypot(vx, vy)
                    if (ux * vx + uy * vy >= 0 or
                            abs(ux * vy - uy * vx) > 1e-8 * other_length):
                        continue
                    gap = abs(ux * (c[1] - a[1]) - uy * (c[0] - a[0]))
                    if gap > tolerance_m + 1e-8:
                        continue
                    lo, hi = sorted(((p[0] - a[0]) * ux + (p[1] - a[1]) * uy
                                     for p in (c, d)))
                    start, end = max(0.0, lo), min(length, hi)
                    if end - start <= 1e-7:
                        continue
                    contacts.append(PartyWall(
                        facade_id=fid, neighbor_id=neighbor.identifier,
                        neighbor_conditioning="unknown", contact_confirmed=True,
                        assumption_source=assumption_source, start_m=start, end_m=end,
                        bottom_m=bottom, top_m=top,
                    ))
    return tuple(contacts)


def contact_bounds(wall, line, bottom, top):
    """Clip optional legacy whole-facade bounds to one extrusion's extent."""
    length = line.length
    if wall.start_m >= length or (wall.end_m is not None and wall.end_m > length + 1e-7):
        raise ValueError(f"Party wall {wall.facade_id} exceeds facade length")
    return (wall.start_m, length if wall.end_m is None else wall.end_m,
            bottom if wall.bottom_m is None else wall.bottom_m,
            top if wall.top_m is None else wall.top_m)
