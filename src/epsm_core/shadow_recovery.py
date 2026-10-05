# File: shadow_recovery.py
# Purpose: Audited, opt-in context approximation after pure shadow-capacity failures.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-10-05
# Date modified: 2026-10-05
# Changelog:
#   2026-10-05 - Add bounded context-only shadow retries with retained attempt evidence.

"""Context shading approximation; never a warning waiver or thermal geometry repair.

Notes
-----
A 1 m then 2 m tolerance can remove real facade projections. This policy is distinct
from centimetre-scale small-cap cleanup and is therefore explicitly opt-in. Every
retry starts from the original scene, retains all neighbours/heights/courtyards,
and undergoes the ordinary compiler, calendar, engine and SQL acceptance checks.
"""

import json
import shutil
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .failures import SHADOW_COMPLEXITY_LIMIT

POLICY = "context-shadow-simplification-1"
TOLERANCES_M = (1.0, 2.0)
MAX_EXCHANGED_AREA_FRACTION = 0.10


def simplify_shadow_context(spec, tolerance_m):
    """Build an audited shading candidate while retaining all thermal inputs.

    Parameters
    ----------
    spec : BuildingSpec
        Immutable source scene; each retry uses this original specification.
    tolerance_m : float
        Maximum permitted boundary Hausdorff displacement in metres.

    Returns
    -------
    tuple
        Candidate specification (or None when unchanged/unsafe) and audit record.

    Notes
    -----
    Simplify only outer context rings. Courtyards, elevations and target inputs
    remain exact. A footprint exceeding 10% exchanged area is retained unchanged.
    Original and proposed contacts are compared against the target and every
    neighbour; reject a scene with a changed contact or new overlap. The ordinary
    compiler subsequently proves prepared shell closure and emitted face validity.
    """
    target = unary_union([f.polygon for f in spec.geometry.footprints])
    sources = [f.polygon for b in spec.context.buildings for f in b.footprints]
    candidates, footprints, buildings = [], [], []
    audit = dict(
        policy=POLICY,
        tolerance_m=tolerance_m,
        maximum_exchanged_area_fraction=MAX_EXCHANGED_AREA_FRACTION,
        radius_m=spec.context.generation.get("radius_m"),
        footprints=footprints,
    )
    for building in spec.context.buildings:
        prepared = []
        for footprint in building.footprints:
            p = footprint.polygon
            # Preserve hole coordinates, rather than relying on topology preservation
            # alone: Shapely's simplifier can otherwise move courtyard boundaries.
            outer = p.simplify(tolerance_m, preserve_topology=True)
            q = Polygon(outer.exterior, [hole.coords for hole in p.interiors])
            # An unchanged courtyard can fall outside a simplified outer ring.
            # Do not run overlay operations on that invalid candidate polygon.
            valid = q.is_valid and not q.is_empty
            exchanged = p.symmetric_difference(q).area / p.area if valid else None
            displacement = p.boundary.hausdorff_distance(q.boundary) if valid else None
            allowed = (
                valid and exchanged <= MAX_EXCHANGED_AREA_FRACTION and displacement <= tolerance_m
            )
            if not allowed:
                q = p
            changed = not p.equals(q)
            footprints.append(
                dict(
                    identifier=building.identifier,
                    changed=changed,
                    disposition="simplified" if changed else "retained",
                    candidate_within_limits=allowed,
                    source_exterior=list(p.exterior.coords),
                    prepared_exterior=list(q.exterior.coords),
                    source_area_m2=p.area,
                    prepared_area_m2=q.area,
                    candidate_exchanged_area_fraction=exchanged,
                    candidate_boundary_displacement_m=displacement,
                    symmetric_difference_area_fraction=p.symmetric_difference(q).area / p.area,
                    boundary_displacement_m=p.boundary.hausdorff_distance(q.boundary),
                )
            )
            candidates.append(q)
            prepared.append(footprint.updated(exterior=tuple(q.exterior.coords)))
        buildings.append(building.updated(footprints=tuple(prepared)))
    if not any(f["changed"] for f in footprints):
        audit.update(disposition="skipped", reason="no footprint changed within limits")
        return None, audit

    def preserved(p, q, other_p, other_q):
        # Contact sets protect party-wall evidence and courtyard/nearby geometry;
        # area tests additionally prevent overlapping solids with disjoint rings.
        return q.intersection(other_q).area <= 1e-8 and p.boundary.intersection(
            other_p.boundary
        ).equals(q.boundary.intersection(other_q.boundary))

    for i, (p, q) in enumerate(zip(sources, candidates)):
        if not preserved(p, q, target, target) or any(
            not preserved(p, q, sources[j], candidates[j]) for j in range(i)
        ):
            audit.update(disposition="skipped", reason="contact changed or overlap introduced")
            return None, audit
    audit["disposition"] = "candidate"
    generation = dict(spec.context.generation, shadow_recovery=audit)
    context = spec.context.updated(buildings=tuple(buildings), generation=generation)
    return spec.updated(context=context), audit


def _pure_shadow_failure(error, directory):
    """Require isolated capacity exhaustion, never a mixed fatal/geometry failure."""
    if getattr(error, "code", None) != SHADOW_COMPLEXITY_LIMIT:
        return False
    path = directory / "diagnostics.json"
    if not path.is_file():
        return False
    d = json.loads(path.read_text())
    rejected = [m for m in d.get("messages", []) if not m.get("approved", False)]
    return (
        bool(rejected)
        and all(m["category"] == "shadow_overlap_limit" for m in rejected)
        and not any(
            d.get(k, 0)
            for k in (
                "process_returncode",
                "fatal_count",
                "severe_count",
                "invalid_view_factor_count",
            )
        )
    )


def _promote_attempt(attempt, directory, manifest, output=None):
    """Expose the selected attempt at normal paths while retaining every original."""
    selected = next(r for r in manifest["attempts"] if r.get("directory") == str(attempt))
    manifest.update(
        selected_attempt=attempt.name,
        selected_accepted=output is not None,
        approximation_used=selected["geometry"] is not None,
        sensitivity_review_required=selected["geometry"] is not None,
    )
    # Never copy a completion marker until the root diagnostics and recovery
    # receipt describe the selected run. Failed attempts have no result marker.
    for source in attempt.iterdir():
        if source.name == "result.json":
            continue
        destination = directory / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
    (directory / "shadow-recovery.json").write_text(json.dumps(manifest, indent=2))
    path = directory / "diagnostics.json"
    if path.exists():
        diagnostics = json.loads(path.read_text())
        diagnostics["shadow_recovery"] = manifest
        path.write_text(json.dumps(diagnostics, indent=2))
    if output is not None:
        output.diagnostics["shadow_recovery"] = manifest
        # SimulationResult is frozen, but its artifact dictionary is mutable.
        # All promoted artifacts must point to the model/results actually selected.
        for name, value in list(output.artifacts.items()):
            try:
                relative = Path(value).relative_to(attempt)
            except ValueError:
                continue
            output.artifacts[name] = str(directory / relative)
        receipt = json.loads((attempt / "result.json").read_text())
        receipt["diagnostics"] = output.diagnostics
        (directory / "result.json").write_text(json.dumps(receipt, indent=2))


def run_with_context_shadow_recovery(run_once, spec, directory, **options):
    """Run the original scene, then at most two independently validated candidates.

    Parameters
    ----------
    run_once : callable
        Ordinary single-attempt runner, including complete acceptance validation.
    spec : BuildingSpec
        Source model; target, weather, systems and context heights remain fixed.
    directory : str or Path
        Empty root directory; every attempt remains in shadow-recovery/ subfolders.
    **options : dict
        Ordinary runner options. The timeout applies independently to each attempt.

    Returns
    -------
    SimulationResult
        First successful validated output, with approximation provenance attached.

    Notes
    -----
    Unrelated failures terminate immediately. Unchanged/unsafe candidates do not
    launch EnergyPlus. Exhausted capacity remains rejected and no success marker
    is created. Promoted root files belong to the selected attempt, never a mixture
    of original inputs and recovered outputs. Full attempt receipts are retained.
    """
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f"Run directory must be empty: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(
        policy=POLICY,
        enabled=True,
        attempts=[],
        approximation_used=False,
        sensitivity_review_required=False,
    )
    attempts = [("original", spec, None)]
    last_error = last_directory = None
    for name in ("original", "context-1m", "context-2m"):
        if name != "original":
            tolerance = TOLERANCES_M[0 if name == "context-1m" else 1]
            candidate, audit = simplify_shadow_context(spec, tolerance)
            if candidate is None:
                manifest["attempts"].append(dict(name=name, **audit))
                continue
            attempts.append((name, candidate, audit))
        _, candidate, audit = attempts[-1]
        attempt = directory / "shadow-recovery" / name
        record = dict(name=name, directory=str(attempt), geometry=audit)
        manifest["attempts"].append(record)
        try:
            output = run_once(candidate, attempt, **options)
        except Exception as error:
            record.update(
                accepted=False, failure_code=getattr(error, "code", None), failure_detail=str(error)
            )
            last_error, last_directory = error, attempt
            if _pure_shadow_failure(error, attempt):
                continue
            _promote_attempt(attempt, directory, manifest)
            raise
        record.update(accepted=True, run_id=output.run_id)
        manifest.update(
            selected_attempt=name,
            approximation_used=audit is not None,
            sensitivity_review_required=audit is not None,
        )
        _promote_attempt(attempt, directory, manifest, output)
        return output
    _promote_attempt(last_directory, directory, manifest)
    raise last_error
