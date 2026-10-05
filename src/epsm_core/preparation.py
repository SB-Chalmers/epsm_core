# File: preparation.py
# Purpose: Conservative, auditable metric footprint preparation; no EPC or engine dependency.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
# License: MIT; see the project-root LICENSE for the full permission and warranty terms.
# Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
# Project PI: Alexander Hollberg
# Computational Sustainable Design Group
# Research Area of Sustainable Built Environments
# Chalmers University of Technology, Gothenburg
# Date created: 2026-09-06 (documentation-header creation; not original file creation)
# Date modified: 2026-10-05
# Changelog:
#   2026-10-05 - Audit exchanged outline area and component contacts; share metrics and lineage.
#   2026-09-06 - Document preparation interfaces, examples, constraints and processing rationale.

"""Conservative, auditable metric footprint preparation; no EPC or engine dependency.

Notes
-----
Preparation preserves original geometry as audit evidence while normalizing, repairing,
rounding and simplifying a metric footprint. Only accepted status indicates all checks
passed. Review reasons, geometric metrics and source-edge lineage travel with the
candidate geometry.

Examples
--------
Example::

    from epsm_core.preparation import prepare_geometry

    from shapely.geometry import box

    result = prepare_geometry(box(0, 0, 10, 8))
    assert result.status == "accepted"
"""

from dataclasses import asdict, dataclass, replace
from typing import Literal

import numpy as np
from shapely import STRtree, get_coordinates, make_valid, normalize, set_precision
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping
from shapely.geometry.polygon import orient


@dataclass(frozen=True)
class GeometryPolicy:
    """Versioned metric footprint-cleanup tolerances and protected boundaries.

    Attributes
    ----------
    version : str
        Dataset identity/version or stable item identity, as appropriate to the record.
        Default: ``'conservative-metric-2'``.
    precision_m : float
        Strictly positive coordinate grid in metres used during conservative preparation.
        Default: ``0.001``.
    simplification_m : float
        Nonnegative line-simplification distance in metres.  Default: ``0.05``.
    max_displacement_m : float
        Maximum bidirectional boundary displacement in metres.  Default: ``0.1``.
    max_area_fraction : float
        Maximum relative change in net area or total boundary length.  Default: ``0.005``.
    max_perimeter_fraction : float
        Maximum relative change in net area or total boundary length.  Default: ``0.01``.
    max_symmetric_difference_fraction : float
        Maximum removed plus added plan area divided by source area. Default: ``0.005``.
    protected_vertices : tuple[tuple[float, float], ...]
        Source boundary vertices whose containing rings must remain unsimplified.  Default:
        ``()``.
    edge_properties : tuple[tuple[str, str], ...]
        Explicit source-edge ID/property pairs whose run boundaries require protection.
        Default: ``()``.

    Notes
    -----
    Limits are finite and nonnegative; precision is strictly positive. Explicit edge
    properties protect their endpoint rings from simplification. These are conservative
    acceptance controls, not a CRS or height policy.

    Examples
    --------
    Example::

        from epsm_core.preparation import GeometryPolicy

        policy = GeometryPolicy()
    """

    version: str = "conservative-metric-2"
    precision_m: float = 0.001
    simplification_m: float = 0.05
    max_displacement_m: float = 0.1
    max_area_fraction: float = 0.005
    max_perimeter_fraction: float = 0.01
    # Source vertices bounding different facade properties or shared ownership.
    protected_vertices: tuple[tuple[float, float], ...] = ()
    edge_properties: tuple[tuple[str, str], ...] = ()
    max_symmetric_difference_fraction: float = 0.005

    def __post_init__(self):
        """Check finite, nonnegative cleanup limits and strictly positive precision.

        Returns
        -------
        None
            Validates the immutable policy at construction.

        Raises
        ------
        ValueError
            Rejected conditions: Preparation limits must be finite and nonnegative; precision
            positive.

        Notes
        -----
        Zero movement, simplification or fractional-change tolerances are allowed; a zero
        precision grid is not.

        Examples
        --------
        Example::

            from epsm_core.preparation import GeometryPolicy

            GeometryPolicy(precision_m=0.001).__post_init__()
        """

        # 1. Check finite, nonnegative cleanup limits and strictly positive precision.
        limits = (
            self.precision_m,
            self.simplification_m,
            self.max_displacement_m,
            self.max_area_fraction,
            self.max_perimeter_fraction,
            self.max_symmetric_difference_fraction,
        )
        if not all(np.isfinite(v) and v >= 0 for v in limits) or not self.precision_m:
            raise ValueError(
                "Preparation limits must be finite and nonnegative; precision positive"
            )


@dataclass(frozen=True)
class EdgeLineage:
    """Map one cleaned edge to matching source-edge identities.

    Attributes
    ----------
    facade_id : str
        Stable physical facade identifier from GeometrySpec.facades().  Required at
        construction.
    start : tuple[float, float]
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Required at construction.
    end : tuple[float, float]
        Directed metric boundary endpoints; _m fields retain source-frame coordinates.
        Required at construction.
    source_edges : tuple[str, ...]
        Source edge IDs matching the cleaned run.  Required at construction.
    changed : bool
        Whether no exactly equal source edge was found.  Required at construction.

    Notes
    -----
    changed means no exactly equal source edge was found. Multiple source edges may map to a
    simplified run; endpoints are cleaned metric coordinates.

    Examples
    --------
    Example::

        from epsm_core.preparation import EdgeLineage

        edge = EdgeLineage("p0.r0.e0", (0, 0), (1, 0), ("p0.r0.e0",), False)
    """

    facade_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    source_edges: tuple[str, ...]
    changed: bool


@dataclass(frozen=True)
class GeometryPreparationResult:
    """Auditable outcome of geometry normalization and bounded cleanup.

    Attributes
    ----------
    source_geometry : object
        Original geometry or cleanup candidate; acceptance is determined separately by
        status.  Required at construction.
    cleaned_geometry : object
        Original geometry or cleanup candidate; acceptance is determined separately by
        status.  Required at construction.
    policy : GeometryPolicy
        Explicit cleanup tolerances, protected vertices and lineage controls.  Required at
        construction.
    status : Literal['accepted', 'needs_review', 'rejected']
        Evidence or processing outcome classification for the record.  Required at
        construction.
    reasons : tuple[str, ...]
        Stable reason codes explaining review requirements or rejection.  Required at
        construction.
    stages : tuple[str, ...]
        Ordered preparation stages actually attempted.  Required at construction.
    metrics : dict
        Measured displacement, area, perimeter and topology evidence.  Required at
        construction.
    edge_lineage : tuple[EdgeLineage, ...]
        Cleaned-to-source boundary mappings supporting facade provenance.  Required at
        construction.

    Notes
    -----
    Only accepted means all checks passed. needs_review retains candidate geometry and
    reasons for caller review; rejected may contain unsupported or collapsed geometry. Never
    treat the cleaned shape alone as an acceptance signal.

    Examples
    --------
    Example::

        from epsm_core.preparation import prepare_geometry

        from shapely.geometry import box

        result = prepare_geometry(box(0, 0, 10, 8))
    """

    source_geometry: object
    cleaned_geometry: object
    policy: GeometryPolicy
    status: Literal["accepted", "needs_review", "rejected"]
    reasons: tuple[str, ...]
    stages: tuple[str, ...]
    metrics: dict
    edge_lineage: tuple[EdgeLineage, ...]

    def artifact(self, *, source_crs, target_crs, transformation):
        """Serialize source, cleaned geometry and lineage with caller-supplied CRS provenance.

        Parameters
        ----------
        source_crs : str
            Caller-supplied coordinate-system label for preparation provenance.
        target_crs : str
            Caller-supplied coordinate-system label for preparation provenance.
        transformation : str or dict
            Description of the actual coordinate transformation performed before preparation.

        Returns
        -------
        dict
            GeoJSON geometries, WKB, policy, metrics, stages and edge records.

        Notes
        -----
        No CRS or transformation is inferred. The caller must describe the actual preprocessing
        transform; geometries already use metric coordinates.

        Examples
        --------
        Supply a GeometryPreparationResult as ``result`` from prepare_geometry.

        Example::

            artifact = result.artifact(
                source_crs="local_metres",
                target_crs="local_metres",
                transformation="identity",
            )
        """
        # 1. Serialize source, cleaned geometry and lineage with caller-supplied CRS provenance.
        return dict(
            source_geometry=mapping(self.source_geometry),
            cleaned_geometry=mapping(self.cleaned_geometry),
            source_wkb_hex=self.source_geometry.wkb_hex,
            source_crs=source_crs,
            target_crs=target_crs,
            transformation=transformation,
            policy=asdict(self.policy),
            status=self.status,
            reasons=self.reasons,
            stages=self.stages,
            metrics=self.metrics,
            edge_lineage=[asdict(e) for e in self.edge_lineage],
        )


def polygons(geometry):
    """Extract immediate Polygon or MultiPolygon members for conservative cleanup.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry in metric plan coordinates; supported component handling is
        described in Notes.

    Returns
    -------
    list of Polygon
        Polygon members, or an empty list for unsupported geometry.

    Notes
    -----
    GeometryCollections are deliberately not flattened here; repair that creates mixed
    nonpolygonal features is rejected by the preparation workflow.

    Examples
    --------
    Example::

        from epsm_core.preparation import polygons

        from shapely.geometry import box

        assert len(polygons(box(0, 0, 2, 2))) == 1
    """

    # 1. Extract immediate Polygon or MultiPolygon members for conservative cleanup.
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def canonical_polygon(polygon):
    """Normalize winding, ring origins and hole order without moving coordinates.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.

    Returns
    -------
    Polygon
        Canonical polygon with counterclockwise exterior.

    Notes
    -----
    Each ring starts at its lexicographically smallest vertex. Hole sorting and winding
    normalization stabilize facade identities.

    Examples
    --------
    Example::

        from epsm_core.preparation import canonical_polygon

        from shapely.geometry import box

        p = canonical_polygon(box(0, 0, 2, 2))
        assert tuple(p.exterior.coords[0]) == (0.0, 0.0)
    """
    # 1. Normalize winding, ring origins and hole order without moving coordinates.
    p = orient(normalize(polygon), sign=1)

    def ring(r):
        """Rotate an unclosed coordinate sequence to its smallest vertex.

        Parameters
        ----------
        r : LinearRing
            Shapely ring whose repeated closing point is handled by the helper.

        Returns
        -------
        list of tuple
            Canonically started ring coordinates.

        Notes
        -----
        The enclosing orient call supplies winding. Remove the duplicated closing vertex before
        choosing the start.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            ring(p.exterior)
        """

        points = list(r.coords)[:-1]
        start = min(range(len(points)), key=points.__getitem__)
        return points[start:] + points[:start]

    return Polygon(ring(p.exterior), sorted((ring(r) for r in p.interiors)))


def canonical_geometry(geometry):
    """Canonicalize and sort polygon components by binary geometry representation.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry in metric plan coordinates; supported component handling is
        described in Notes.

    Returns
    -------
    Polygon or MultiPolygon
        Stable geometry with unchanged coordinates.

    Notes
    -----
    A single part is returned as Polygon. Unsupported inputs become an empty MultiPolygon
    through polygons; validate input before relying on this helper.

    Examples
    --------
    Example::

        from epsm_core.preparation import canonical_geometry

        from shapely.geometry import box

        assert canonical_geometry(box(0, 0, 2, 2)).area == 4
    """

    parts = sorted((canonical_polygon(p) for p in polygons(geometry)), key=lambda p: p.wkb)
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def edges(geometry):
    """Yield each directed ring edge with preparation-local lineage identity.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry in metric plan coordinates; supported component handling is
        described in Notes.

    Yields
    ------
    tuple
        Edge ID and two-point LineString.

    Notes
    -----
    IDs use pN.rN.eN component/ring/edge indices. These IDs describe the current geometry
    ordering, so source and cleaned identities need explicit lineage mapping.

    Examples
    --------
    Example::

        from epsm_core.preparation import edges

        from shapely.geometry import box

        assert len(list(edges(box(0, 0, 2, 2)))) == 4
    """

    # 1. Yield each directed ring edge with preparation-local lineage identity.
    for pi, p in enumerate(polygons(geometry)):
        for ri, r in enumerate((p.exterior, *p.interiors)):
            coords = list(r.coords)
            for ei, (a, b) in enumerate(zip(coords, coords[1:])):
                yield f"p{pi}.r{ri}.e{ei}", LineString([a, b])


def topology(geometry):
    """Summarize component count, hole count and pairwise component contacts.

    Parameters
    ----------
    geometry : BaseGeometry
        Shapely geometry in metric plan coordinates; supported component handling is
        described in Notes.

    Returns
    -------
    tuple
        Number of polygons, holes and contacts; contacts are None for invalid parts.

    Notes
    -----
    Only contact counts are retained, not a full connectivity graph. This summary is one
    safeguard alongside area and displacement checks.

    Examples
    --------
    Example::

        from epsm_core.preparation import topology

        from shapely.geometry import box

        assert topology(box(0, 0, 2, 2)) == (1, 0, 0)
    """

    # 1. Summarize component count, hole count and pairwise component contacts.
    parts = polygons(geometry)
    if any(not p.is_valid for p in parts):
        return (len(parts), sum(len(p.interiors) for p in parts), None)
    contacts = []
    tree = STRtree(parts)
    for i, p in enumerate(parts):
        for j in tree.query(p, predicate="intersects"):
            if i < j:
                contacts.append((i, int(j), p.intersection(parts[j]).geom_type))
    return (len(parts), sum(len(p.interiors) for p in parts), len(contacts))


def geometry_change_metrics(source, cleaned):
    """Measure metric outline changes without assuming energy equivalence.

    Symmetric difference counts removed AND added area, preventing cancellation in
    net area. It is unavailable for invalid inputs, which must remain review cases.
    Boundary displacement uses densified Hausdorff distance; acceptance must also
    check continuous boundary containment. All lengths include courtyard rings.
    """
    from shapely import hausdorff_distance

    valid = source.is_valid and cleaned.is_valid and source.area > 0
    return dict(
        boundary_displacement_m=float(
            hausdorff_distance(source.boundary, cleaned.boundary, densify=0.1)
        ),
        area_change_fraction=abs(cleaned.area - source.area) / source.area if source.area else None,
        symmetric_difference_fraction=(
            source.symmetric_difference(cleaned).area / source.area if valid else None
        ),
        perimeter_change_fraction=abs(cleaned.length - source.length) / source.length,
        source_area_m2=source.area,
        cleaned_area_m2=cleaned.area,
        source_perimeter_m=source.length,
        cleaned_perimeter_m=cleaned.length,
    )


def geometry_edge_lineage(source, cleaned, radius):
    """Map prepared edges to source runs within a metric search radius.

    IDs are local to each geometry; they are evidence for manual remapping, never
    permission to apply old facade properties to new edge indices automatically.
    """
    original_edges = list(edges(source))
    tree = STRtree([e for _, e in original_edges])
    lineage = []
    for fid, edge in edges(cleaned):
        matches = []
        for i in tree.query(edge.buffer(radius)):
            old_id, old = original_edges[i]
            # Require positive projected overlap, avoiding adjacent end-only edges.
            a, b = [edge.project(Point(p)) for p in old.coords]
            if abs(a - b) > 1e-9 and old.difference(edge.buffer(radius)).length <= 1e-9:
                matches.append(old_id)
        exact = any(edge.equals(original_edges[i][1]) for i in tree.query(edge))
        lineage.append(
            EdgeLineage(
                fid,
                tuple(edge.coords[0]),
                tuple(edge.coords[-1]),
                tuple(sorted(matches)),
                not exact,
            )
        )
    return tuple(lineage)


def component_contacts_preserved(source, cleaned, tolerance_m):
    """Audit contact partners and contact geometry after component reordering.

    Match components by greatest plan overlap, requiring a unique correspondence.
    Contact counts alone cannot detect a contact switching to another component.
    Invalid inputs return None: repaired geometry always requires review separately.
    ``tolerance_m`` bounds precision rounding of shared boundaries, not simplification.
    """
    if not source.is_valid or not cleaned.is_valid:
        return None
    before, after = polygons(source), polygons(cleaned)
    if len(before) != len(after):
        return False
    order = [max(range(len(after)), key=lambda j: a.intersection(after[j]).area) for a in before]
    if len(set(order)) != len(before):
        return False
    for i, a in enumerate(before):
        for j in range(i + 1, len(before)):
            old, new = a.intersection(before[j]), after[order[i]].intersection(after[order[j]])
            if old.is_empty != new.is_empty:
                return False
            if not old.is_empty:
                if old.geom_type != new.geom_type:
                    return False
                if tolerance_m == 0:
                    if not old.equals(new):
                        return False
                elif not (
                    old.covered_by(new.buffer(tolerance_m, quad_segs=32))
                    and new.covered_by(old.buffer(tolerance_m, quad_segs=32))
                ):
                    return False
    return True


def _simplify(polygon, policy):
    # If a property boundary is present, keep this ring exactly. This conservative
    # choice avoids inventing a facade merge across an override or shared edge.
    """Simplify boundary lines while preserving rings containing protected vertices.

    Parameters
    ----------
    polygon : Polygon
        Planar Shapely polygon in metres, with courtyard interiors retained where supported.
    policy : GeometryPolicy
        Explicit cleanup tolerances, protected vertices and lineage controls.

    Returns
    -------
    Polygon
        Candidate geometry requiring subsequent validity checks.

    Notes
    -----
    Protected coordinates are rounded onto the policy grid before membership checks. Line
    simplification can still create invalid polygon topology, so callers must validate the
    result.

    Examples
    --------
    Example::

        from epsm_core.specs.geometry import Footprint
        from epsm_core.preparation import GeometryPolicy
        from epsm_core.specs.geometry import GeometrySpec
        from epsm_core.preparation import _simplify

        geometry = GeometrySpec.from_footprint(
            Footprint.rectangle(10, 8), storeys=2, storey_height_m=3
        )
        polygon = geometry.footprints[0].polygon
        candidate = _simplify(polygon, GeometryPolicy())
    """

    # 1. Simplify boundary lines while preserving rings containing protected vertices.
    protected = {
        tuple(round(x / policy.precision_m) * policy.precision_m for x in p)
        for p in policy.protected_vertices
    }

    def ring(r):
        """Keep a protected ring intact or simplify its boundary line.

        Parameters
        ----------
        r : LinearRing
            Shapely ring whose repeated closing point is handled by the helper.

        Returns
        -------
        list of tuple
            Ring coordinates for rebuilding a Polygon.

        Notes
        -----
        A single protected vertex retains the entire ring to avoid merging across an explicit
        facade-property boundary.

        Examples
        --------
        Within the enclosing operation, after its captured state has been initialized::

            ring(polygon.exterior)
        """

        if protected.intersection(tuple(p) for p in r.coords):
            return list(r.coords)
        return list(LineString(r.coords).simplify(policy.simplification_m).coords)

    return Polygon(ring(polygon.exterior), [ring(r) for r in polygon.interiors])


def prepare_geometry(raw_geometry, policy=GeometryPolicy()):
    """Prepare metric footprints with bounded displacement and explicit review evidence.

    Parameters
    ----------
    raw_geometry : Polygon or MultiPolygon
        Unprepared source geometry already expressed in finite two-dimensional metres.
    policy : GeometryPolicy
        Explicit cleanup tolerances, protected vertices and lineage controls. Default:
        ``GeometryPolicy()``.

    Returns
    -------
    GeometryPreparationResult
        Accepted, needs_review or rejected geometry with metrics and lineage.

    Raises
    ------
    ValueError
        Rejected conditions: Facade properties require unique known source-edge IDs.

    Notes
    -----
    Never infers heights, CRS or EPC-area scaling. Validity repair always requires review.
    Simplification seeks a fixed point within 20 iterations; acceptance also requires
    topology, area, perimeter, boundary containment and mapped-edge checks.

    Examples
    --------
    Example::

        from epsm_core.preparation import prepare_geometry

        from shapely.geometry import box

        result = prepare_geometry(box(0, 0, 10, 8))
        assert result.status == "accepted"
    """
    # 1. Prepare metric footprints with bounded displacement and explicit review evidence.
    reasons, stages = [], ["exact_normalization"]
    if (
        not polygons(raw_geometry)
        or raw_geometry.is_empty
        or not np.isfinite(get_coordinates(raw_geometry)).all()
        or raw_geometry.has_z
    ):
        return GeometryPreparationResult(
            raw_geometry,
            raw_geometry,
            policy,
            "rejected",
            ("requires_finite_nonempty_2d_polygonal_geometry",),
            (),
            {},
            (),
        )
    # 2. Preserve the original geometry as immutable audit evidence for every later check.
    source = raw_geometry
    if policy.edge_properties:
        properties = dict(policy.edge_properties)
        source_edges = dict(edges(source))
        if len(properties) != len(policy.edge_properties) or set(properties) - source_edges.keys():
            raise ValueError("Facade properties require unique known source-edge IDs")
        protected = set(policy.protected_vertices)
        # Preserve boundaries of every explicit property run, including override/default transitions.
        for edge_id in properties:
            protected.update(tuple(p) for p in source_edges[edge_id].coords)
        policy = replace(policy, protected_vertices=tuple(sorted(protected)))
    # 3. Normalize identity before repair; any repair remains a reviewable event.
    cleaned = canonical_geometry(source)
    if not cleaned.is_valid:
        cleaned = make_valid(cleaned)
        stages.append("validity_repair")
        reasons.append("validity_repair_requires_review")
        if not polygons(cleaned) or cleaned.is_empty:
            return GeometryPreparationResult(
                source,
                cleaned,
                policy,
                "rejected",
                ("repair_has_nonpolygonal_or_collapsed_features",),
                tuple(stages),
                {},
                (),
            )
    # Keep an explicit stage for rounding; GEOS pointwise never hides collapsed rings.
    # 4. Round visibly without letting topology-preserving precision hide collapsed rings.
    rounded = set_precision(cleaned, policy.precision_m, mode="pointwise")
    stages.append("coordinate_precision")
    if not rounded.is_valid or rounded.is_empty:
        reasons.append("precision_collapsed_or_invalid_features")
    else:
        cleaned = canonical_geometry(rounded)
    # 5. Simplify protected rings conservatively and seek a stable repeated-cleanup result.
    candidate = canonical_geometry(MultiPolygon([_simplify(p, policy) for p in polygons(cleaned)]))
    stages.append("simplification")
    if candidate.is_valid and not candidate.is_empty:
        # Reach a fixed point so accepted output is idempotent under this policy.
        for _ in range(20):
            next_candidate = canonical_geometry(
                MultiPolygon([_simplify(p, policy) for p in polygons(candidate)])
            )
            if next_candidate.wkb == candidate.wkb:
                break
            if not next_candidate.is_valid or next_candidate.is_empty:
                reasons.append("simplification_collapsed_or_invalid_features")
                break
            candidate = next_candidate
        else:
            reasons.append("simplification_not_stable")
        cleaned = candidate
    else:
        reasons.append("simplification_collapsed_or_invalid_features")
    # 6. Check continuous boundary containment as well as sampled displacement.
    if not source.boundary.equals(cleaned.boundary):
        # Continuous buffer containment guards the displacement limit between the
        # sampled Hausdorff points as well. Polygonal buffers are conservative.
        if not source.boundary.covered_by(
            cleaned.boundary.buffer(policy.max_displacement_m, quad_segs=32)
        ) or not cleaned.boundary.covered_by(
            source.boundary.buffer(policy.max_displacement_m, quad_segs=32)
        ):
            reasons.append("boundary_displacement_m_exceeded")
    # 7. Compare topology and physical metrics before deciding whether review is required.
    before, after = topology(source), topology(cleaned)
    if before != after:
        reasons.append("topology_changed")
    metrics = geometry_change_metrics(source, cleaned)
    metrics.update(source_topology=before, cleaned_topology=after)
    contacts = component_contacts_preserved(source, cleaned, policy.precision_m * 2**0.5)
    metrics["component_contacts_preserved"] = contacts
    if contacts is False:
        reasons.append("component_contacts_changed")
    for key, limit in (
        ("boundary_displacement_m", policy.max_displacement_m),
        ("area_change_fraction", policy.max_area_fraction),
        ("perimeter_change_fraction", policy.max_perimeter_fraction),
        ("symmetric_difference_fraction", policy.max_symmetric_difference_fraction),
    ):
        if (metrics[key] is None and source.is_valid) or (
            metrics[key] is not None and metrics[key] > limit + 1e-12
        ):
            reasons.append(key + "_exceeded")
    # 8. Map cleaned runs to source edges using positive overlap, not endpoint contact.
    lineage = geometry_edge_lineage(source, cleaned, policy.max_displacement_m + policy.precision_m)
    if any(not edge.source_edges for edge in lineage):
        reasons.append("unmapped_edge")
    # 9. Return geometry together with acceptance evidence; shape alone is insufficient.
    return GeometryPreparationResult(
        source,
        cleaned,
        policy,
        "needs_review" if reasons else "accepted",
        tuple(sorted(set(reasons))),
        tuple(stages),
        metrics,
        tuple(lineage),
    )
