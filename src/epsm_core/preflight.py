# File: preflight.py
# Purpose: Inspect EnergyPlus ground geometry before engine setup.
# SPDX-License-Identifier: MIT
# License: MIT; see the project-root LICENSE.
# Date created: 2026-10-14

# File: preflight.py
# Purpose: Read-only simulation readiness checks that avoid engine and weather I/O.
# SPDX-License-Identifier: MIT

"""Read-only simulation readiness checks that do not initialize an engine."""

from __future__ import annotations

from epsm_core._logging import operation as logged_operation

from .building import Readiness
from .failures import CompilationError
from .foundations import check_kiva_floor_geometry
from .specs import BuildingSpec


def _surface_record(face, construction):
    return dict(
        zone_name=face.zone,
        construction_name=construction,
        vertices=[dict(
            vertex_x_coordinate=x, vertex_y_coordinate=y, vertex_z_coordinate=z
        ) for x, y, z in face.vertices],
    )


@logged_operation("simulation.preflight")
def preflight_energyplus(spec: BuildingSpec) -> Readiness:
    """Inspect selected ground geometry without weather or engine I/O.

    Parameters
    ----------
    spec : BuildingSpec
        Validated numerical input with its selected ground method and assignments.

    Returns
    -------
    Readiness
        Unsupported Kiva conditions naming the affected zone. Prescribed ground
        treatment has no Kiva floor restriction.

    Notes
    -----
    Uses the same floor union and validation as the compiler. It does not read
    the EPW, inspect an installation, create output or change the input. This
    checks ground geometry, rather than every simulation prerequisite.

    Examples
    --------
    With an already validated ``spec``::

        readiness = preflight_energyplus(spec)
        readiness.require()
    """
    from .pipeline import resolve_geometry

    envelope = spec.envelope
    foundation = envelope.foundation
    if foundation is None or foundation.method != "kiva":
        return Readiness()
    try:
        resolved = resolve_geometry(spec, panelize=True)
        graph = resolved.graph
        surfaces_by_name = {face.name: face for face in graph.surfaces}
        unknown = set(spec.surface_constructions) - surfaces_by_name.keys()
        if unknown:
            return Readiness(unsupported=(f"Unknown surface construction targets: {sorted(unknown)}",))
        override_labels = {
            name: f"physical_override_{index}"
            for index, name in enumerate(sorted(spec.surface_constructions))
        }
        by_zone = {}
        for face in graph.surfaces:
            if face.boundary != "Ground" or face.kind != "Floor":
                continue
            construction = override_labels.get(face.name, face.construction)
            if face.name in override_labels and face.construction.endswith("_reverse"):
                construction += "_reverse"
            record = _surface_record(face, construction)
            by_zone.setdefault(face.zone, []).append((face.name, record))
        check_kiva_floor_geometry(by_zone, envelope)
    except (CompilationError, ValueError) as error:
        return Readiness(unsupported=(str(error),))
    return Readiness()


def _preflight_building_kiva(building):
    """Check Building-owned geometry and physical floor assignments without a spec/climate."""
    from .pipeline import resolve_geometry

    foundation = building.foundation
    if foundation is None or foundation.method != "kiva":
        return Readiness()
    try:
        resolved = resolve_geometry(building, panelize=True)
        from .building_adapter import (
            _envelope_for_building,
            _surface_constructions_for_building,
        )

        envelope = _envelope_for_building(building)
        overrides = _surface_constructions_for_building(
            building, building.geometry, building.facade, envelope, resolved=resolved)
        override_labels = {
            name: f"physical_override_{index}"
            for index, name in enumerate(sorted(overrides))
        }
        by_zone = {}
        for face in resolved.graph.surfaces:
            if face.boundary != "Ground" or face.kind != "Floor":
                continue
            construction = override_labels.get(face.name, face.construction)
            if face.name in override_labels and face.construction.endswith("_reverse"):
                construction += "_reverse"
            record = _surface_record(face, construction)
            by_zone.setdefault(face.zone, []).append((face.name, record))
        check_kiva_floor_geometry(by_zone, envelope)
    except (CompilationError, ValueError) as error:
        return Readiness(unsupported=(str(error),))
    return Readiness()
