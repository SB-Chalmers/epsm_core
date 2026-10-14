"""Bounded Shapely-only MFH thermal layouts, with auditable simplified results.

These are schematic thermal zones, not architectural plans or evidence of Atemp.
The source envelope is retained. No straight-skeleton or optimisation dependency is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product
from time import perf_counter

import numpy as np
from shapely import set_precision, unary_union
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box

from epsm_core.preparation import prepare_geometry
from epsm_core.roofs import dominant_direction
from epsm_core.surface_checks import MIN_GENERATED_EDGE_M
from epsm_core.zoning import polygon_components, validate_partitions

GRID = 1e-8


@dataclass(frozen=True)
class MfhLayoutPolicy:
    """Metric prototype controls; fractions describe above-ground plan area only."""

    target_unconditioned_fraction: float = 0.078
    target_unit_area_m2: float = 67.5
    min_unit_area_m2: float = 25.0
    max_unit_area_m2: float = 120.0
    max_common_fraction: float = 0.20
    min_footprint_m2: float = 150.0
    min_core_area_m2: float = 12.0
    min_core_width_m: float = 2.0
    min_unit_width_m: float = 2.5
    width_retention: float = 0.95
    min_frontage_m: float = 1.2
    min_access_m: float = 0.9
    max_cores: int = 8
    max_candidates: int = 32
    max_split_evaluations: int = 256
    max_grid_cells: int = 40000
    max_units: int = 64
    grid_size_m: float | None = None

    def __post_init__(self):
        values = [v for v in vars(self).values() if v is not None]
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("MFH controls must be finite and positive")
        if not 0 < self.target_unconditioned_fraction <= self.max_common_fraction < 1:
            raise ValueError("MFH target must be positive and within the maximum common fraction")
        if not self.min_unit_area_m2 <= self.target_unit_area_m2 <= self.max_unit_area_m2:
            raise ValueError("MFH apartment area bounds must contain the target")
        if not 0 < self.width_retention <= 1:
            raise ValueError("MFH width retention must be in (0, 1]")
        if self.grid_size_m is not None and self.grid_size_m not in (0.5, 1.0, 2.0):
            raise ValueError("MFH grid size must be 0.5, 1, 2 m or None for adaptive")
        caps = dict(max_cores=8, max_candidates=32, max_split_evaluations=256,
                    max_grid_cells=40000, max_units=64)
        for key, cap in caps.items():
            value = getattr(self, key)
            if isinstance(value, bool) or int(value) != value or not 1 <= value <= cap:
                raise ValueError(f"{key} must be an integer from 1 to {cap}")


@dataclass
class MfhLayoutResult:
    """Complete apartments, simplified occupied regions, or explicit fallback."""

    footprint: Polygon
    method: str
    status: str = "fallback"
    common: tuple = ()
    occupied: tuple = ()
    reason: str | None = None
    metrics: dict = field(default_factory=dict)
    preparation: dict = field(default_factory=dict)

    def receipt(self, *, geometry=False):
        result = dict(method=self.method, status=self.status, reason=self.reason,
                      metrics=self.metrics, preparation=self.preparation)
        if geometry:
            result["geometry"] = dict(footprint=self.footprint.wkt,
                                      common=[p.wkt for p in self.common],
                                      occupied=[p.wkt for p in self.occupied])
        return result


def width_retention(polygon, width):
    """Morphological screen for substantial narrow appendages, not every pinch point."""
    if polygon.is_empty or polygon.area <= 0:
        return 0.0
    inset = polygon.buffer(-width / 2, join_style="mitre")
    if inset.is_empty:
        return 0.0
    return inset.buffer(width / 2, join_style="mitre").intersection(polygon).area / polygon.area


def _contact(a, b):
    # Boolean cuts can differ by a few nanometres while representing the same edge.
    return a.boundary.intersection(b.boundary.buffer(5e-8, cap_style="flat")).length


def _min_edge(p):
    return min(math.dist(a, b) for ring in (p.exterior, *p.interiors)
               for a, b in zip(ring.coords, list(ring.coords)[1:]))


def _normalise(p, regions):
    """Snap near-corner cut endpoints consistently without moving source vertices."""
    anchors = np.array([v for r in (p.exterior, *p.interiors) for v in list(r.coords)[:-1]])
    registry = {}

    def ring(coords):
        out = []
        for point in coords:
            point = tuple(point)
            if point not in registry:
                distances = np.linalg.norm(anchors - point, axis=1)
                i = int(np.argmin(distances))
                registry[point] = tuple(anchors[i]) if distances[i] < MIN_GENERATED_EDGE_M else point
            out.append(registry[point])
        return out

    return [Polygon(ring(q.exterior.coords), [ring(r.coords) for r in q.interiors]).simplify(0)
            for q in regions]


def _unit_metrics(q, p, common, policy):
    return dict(area_m2=q.area, frontage_m=_contact(q, p), access_m=_contact(q, common),
                width_retention=width_retention(q, policy.min_unit_width_m),
                min_edge_m=_min_edge(q), vertices=len(q.exterior.coords) - 1)


def _usable(q, p, common, policy, *, area=False):
    if q.geom_type != "Polygon" or q.is_empty or not q.is_valid or q.interiors:
        return False
    if area and not policy.min_unit_area_m2 - 1e-6 <= q.area <= policy.max_unit_area_m2 + 1e-6:
        return False
    return (_contact(q, p) >= policy.min_frontage_m - 1e-6
            and _contact(q, common) >= policy.min_access_m - 1e-6
            and width_retention(q, policy.min_unit_width_m) >= policy.width_retention - 1e-6)


def _candidate(p, common, units, method, policy, *, common_width=2.0, **metrics):
    common = polygon_components(unary_union(common))
    units = [q for g in units for q in polygon_components(g)]
    if not common or not units or len(units) > policy.max_units:
        return None, "empty_or_excessive_partition"
    if any(q.interiors or not q.is_valid for q in common):
        return None, "fragmented_or_holed_common_space"
    fraction = sum(q.area for q in common) / p.area
    if fraction > policy.max_common_fraction + 1e-7:
        return None, "excessive_common_area"
    if any(q.area < policy.min_core_area_m2 - 1e-6 for q in common):
        return None, "small_service_area"
    if any(width_retention(q, common_width) < policy.width_retention - 1e-6 for q in common):
        return None, "narrow_common_space"
    n = len(common)
    regions = _normalise(p, common + units)
    common, units = regions[:n], regions[n:]
    try:
        validate_partitions(p, regions)
    except ValueError:
        return None, "coverage_or_overlap_failure"
    if any(q.geom_type != "Polygon" or q.is_empty or q.interiors or not q.is_valid for q in regions):
        return None, "disconnected_or_holed_zone"
    if any(_min_edge(q) < MIN_GENERATED_EDGE_M for q in regions):
        return None, "subcentimetre_edge"
    c = unary_union(common)
    if any(not _usable(q, p, c, policy) for q in units):
        return None, "width_frontage_or_access_failure"
    # Simplified zones may be larger than apartments, but still need usable geometry.
    if any(q.area < policy.min_unit_area_m2 - 1e-6 for q in units):
        return None, "tiny_occupied_region"
    status = "complete" if all(q.area <= policy.max_unit_area_m2 + 1e-6 for q in units) else "simplified"
    measurements = [_unit_metrics(q, p, c, policy) for q in units]
    fraction = c.area / p.area
    return MfhLayoutResult(p, method, status, tuple(common), tuple(units),
        None if status == "complete" else "occupied_regions_exceed_apartment_area_band",
        dict(common_fraction=fraction, fraction_error=fraction-policy.target_unconditioned_fraction,
             common_area_m2=c.area, occupied_area_m2=sum(q.area for q in units),
             apartment_count=len(units) if status == "complete" else 0,
             occupied_zone_count=len(units), units=measurements,
             mean_size_error_m2=float(np.mean([abs(q.area-policy.target_unit_area_m2) for q in units])),
             internal_boundary_m=(sum(q.length for q in regions)-p.length)/2,
             boundary_vertices=sum(len(q.exterior.coords)-1 for q in regions), **metrics)), None


def _score(result):
    # Nanometre clipping differences must not select different unit counts after rotation.
    return (result.status != "complete", round(abs(result.metrics["fraction_error"]), 6),
            round(result.metrics["mean_size_error_m2"], 5), result.metrics["internal_boundary_m"])


def _area_cut(p, axis, target):
    a, b, c, d = p.bounds
    lo, hi = (a, c) if axis == 0 else (b, d)
    for _ in range(28):
        v = (lo + hi)/2
        clip = box(a-1, b-1, v, d+1) if axis == 0 else box(a-1, b-1, c+1, v)
        if p.intersection(clip).area < target:
            lo = v
        else:
            hi = v
    return (lo+hi)/2


def _bands(p, count, axis=0):
    a, b, c, d = p.bounds
    edges = [a if axis == 0 else b]
    edges += [_area_cut(p, axis, p.area*i/count) for i in range(1, count)]
    edges += [c if axis == 0 else d]
    return [p.intersection(box(x, b-1, y, d+1) if axis == 0 else box(a-1, x, c+1, y))
            for x, y in zip(edges, edges[1:])]


def _sectors(p, cx, cy, count, axis=0, mirror=False):
    a, b, c, d = p.bounds
    if count == 4:
        cuts = [box(a-1, b-1, cx, cy), box(cx, b-1, c+1, cy),
                box(a-1, cy, cx, d+1), box(cx, cy, c+1, d+1)]
    elif count == 2:
        cuts = ([box(a-1, b-1, cx, d+1), box(cx, b-1, c+1, d+1)] if axis == 0 else
                [box(a-1, b-1, c+1, cy), box(a-1, cy, c+1, d+1)])
    elif axis == 0:
        cuts = ([box(a-1, b-1, cx, d+1), box(cx, b-1, c+1, cy), box(cx, cy, c+1, d+1)]
                if not mirror else [box(cx, b-1, c+1, d+1), box(a-1, b-1, cx, cy), box(a-1, cy, cx, d+1)])
    else:
        cuts = ([box(a-1, b-1, c+1, cy), box(a-1, cy, cx, d+1), box(cx, cy, c+1, d+1)]
                if not mirror else [box(a-1, cy, c+1, d+1), box(a-1, b-1, cx, cy), box(cx, b-1, c+1, cy)])
    return [p.intersection(cut) for cut in cuts]


def _modules(p, policy):
    preferred = max(1, min(policy.max_cores, round(
        p.area*(1-policy.target_unconditioned_fraction)/(3*policy.target_unit_area_m2))))
    counts = sorted({max(1, min(policy.max_cores, preferred+i)) for i in (-1, 0, 1)},
                    key=lambda n: abs(n-preferred))
    configs = list(product((0, 1), counts, (3.0, 2.5), (0, 1)))
    best, reason, examined = None, "no_feasible_core_modules", 0
    for axis, count, width, placement in configs[:policy.max_candidates]:
        examined += 1
        modules = _bands(p, count, axis)
        if any(q.geom_type != "Polygon" or q.interiors for q in modules):
            reason = "disconnected_or_holed_module"
            continue
        common, units = [], []
        failed = False
        for q in modules:
            a, b, c, d = q.bounds
            target = max(policy.min_core_area_m2, q.area*policy.target_unconditioned_fraction)
            length = max(4.0, target/width)
            longer = 0 if c-a >= d-b else 1
            unit_count = max(2, min(4, round((q.area-target)/policy.target_unit_area_m2)))
            options = []
            for k in sorted((2, 3, 4), key=lambda k: abs((q.area-target)/k-policy.target_unit_area_m2)):
                for cut_axis, mirror in product((longer, 1-longer), (False, True) if k == 3 else (False,)):
                    cx, cy = (a+c)/2, (b+d)/2
                    core_axis = longer
                    if k == 3:
                        core_axis = 1-cut_axis
                        if cut_axis == 0:
                            pos = (c-a)/3+target/(6*(d-b))
                            cx = c-pos if mirror else a+pos
                        else:
                            pos = (d-b)/3+target/(6*(c-a))
                            cy = d-pos if mirror else b+pos
                    elif placement:
                        inset = q.buffer(-(policy.min_unit_width_m+width/2), join_style="mitre")
                        if inset.is_empty:
                            continue
                        cx, cy = inset.representative_point().coords[0]
                    w, h = (length, width) if core_axis == 0 else (width, length)
                    core = box(cx-w/2, cy-h/2, cx+w/2, cy+h/2)
                    if not q.covers(core) or q.boundary.distance(core) < policy.min_unit_width_m-1e-6:
                        continue
                    occupied = q.difference(core)
                    pieces = _sectors(occupied, cx, cy, k, cut_axis, mirror)
                    # Contacts are always measured against the actual outer footprint.
                    if all(_usable(v, p, core, policy) and v.area >= policy.min_unit_area_m2 for v in pieces):
                        cost = (any(v.area > policy.max_unit_area_m2 for v in pieces),
                                np.mean([abs(v.area-policy.target_unit_area_m2) for v in pieces]),
                                abs(k-unit_count), sum(v.length for v in pieces))
                        options.append((cost, core, pieces))
            if not options:
                failed = True
                reason = "module_core_or_access_capacity"
                break
            _, core, pieces = min(options, key=lambda item: item[0])
            common.append(core)
            units.extend(pieces)
        if failed:
            continue
        result, failure = _candidate(p, common, units, "modules", policy,
                                     candidates=examined, module_count=count)
        if result and (best is None or _score(result) < _score(best)):
            best = result
        reason = failure or reason
    if best:
        best.metrics["candidates"] = examined
    return best, reason


def _corridor(p, policy):
    best, reason, examined = None, "no_feasible_corridor", 0
    for axis in (0, 1):
        a, b, c, d = p.bounds
        cx, cy = (a+c)/2, (b+d)/2
        core = (box(cx-2, cy-1.5, cx+2, cy+1.5) if axis == 0 else
                box(cx-1.5, cy-2, cx+1.5, cy+2))
        if not p.covers(core):
            continue
        def service(width):
            bar = (box(a+2.5, cy-width/2, c-2.5, cy+width/2) if axis == 0 else
                   box(cx-width/2, b+2.5, cx+width/2, d-2.5))
            return unary_union([core, bar]).intersection(p)
        lo, hi = 1.5, 3.0
        for _ in range(20):
            mid = (lo+hi)/2
            if service(mid).area < policy.target_unconditioned_fraction*p.area:
                lo = mid
            else:
                hi = mid
        common = service((lo+hi)/2)
        if common.geom_type != "Polygon" or common.interiors:
            reason = "disconnected_corridor"
            continue
        occupied = p.difference(common)
        sides = _sectors(occupied, cx, cy, 2, 1-axis)
        base_counts = [max(1, round(s.area/policy.target_unit_area_m2)) for s in sides]
        for adjustment in product((-1, 0, 1), repeat=2):
            examined += 1
            counts = [max(1, n+i) for n, i in zip(base_counts, adjustment)]
            pieces = [u for s, n in zip(sides, counts) for u in _bands(s, n, axis)]
            result, failure = _candidate(p, [common], pieces, "corridor", policy,
                                         common_width=1.5, candidates=examined,
                                         corridor_width_m=(lo+hi)/2)
            if result and (best is None or _score(result) < _score(best)):
                best = result
            reason = failure or reason
    if best:
        best.metrics["candidates"] = examined
    return best, reason


def _offset(p, policy):
    from epsm_core.geometry import facade_edges
    from epsm_core.zoning import perimeter_core_partitions

    from ._mfh_offset import rectilinear_units

    lo, hi = 0.0, max(p.bounds[2]-p.bounds[0], p.bounds[3]-p.bounds[1])
    target = p.area*policy.target_unconditioned_fraction
    for _ in range(35):
        mid = (lo+hi)/2
        if p.buffer(-mid, join_style="mitre").area > target:
            lo = mid
        else:
            hi = mid
    depth = (lo+hi)/2
    if depth < policy.min_unit_width_m:
        return None, "shallow_habitable_band"
    try:
        regions = perimeter_core_partitions(p, list(facade_edges(p, "main")), depth)
    except ValueError as exc:
        return None, "offset_partition_failure: " + str(exc)
    cores = [r.polygon for r in regions if r.kind == "core"]
    if len(cores) != 1 or cores[0].interiors:
        return None, "fragmented_or_holed_core"
    core = cores[0]
    if abs(core.area-target) > target*.01:
        return None, "target_area_not_reproduced"
    if core.area < policy.min_core_area_m2 or width_retention(core, policy.min_core_width_m) < policy.width_retention:
        return None, "narrow_or_small_service_core"
    report, geometry = rectilinear_units(p, core, target=policy.target_unit_area_m2,
                                         minimum=policy.min_unit_area_m2, maximum=policy.max_unit_area_m2)
    if geometry:
        _, c, units = geometry
        ox, oy = report["aligned_origin_m"]
        angle = report["aligned_angle_deg"]
        def restore(q):
            return rotate(translate(q, ox, oy), angle, origin=(0, 0))
        return _candidate(p, [restore(c)], [restore(q) for q in units], "offset", policy,
                          candidates=report["attempts"], perimeter_depth_m=depth)
    cx, cy = core.centroid.coords[0]
    result, reason = _candidate(p, [core], _sectors(p.difference(core), cx, cy, 4),
                                "offset", policy, candidates=report["attempts"],
                                baseline_failure=report["reason"], perimeter_depth_m=depth)
    if result:
        # The legacy bay search did not find apartments; four sectors are the explicit fallback.
        result.status = "simplified"
        result.reason = report["reason"]
        result.metrics["apartment_count"] = 0
    return result, reason or report["reason"]


def _slicing(p, policy, seed):
    if seed is None:
        return None, "no_feasible_common_seed"
    common = unary_union(seed.common)
    first = polygon_components(p.difference(common))
    states = [first]
    best, examined = None, 0
    while states and examined < policy.max_split_evaluations:
        pending = []
        for units in states:
            result, _ = _candidate(p, seed.common, units, "slicing", policy,
                                   common_width=1.5, split_evaluations=examined)
            if result and (best is None or _score(result) < _score(best)):
                best = result
            q = max(units, key=lambda q: (bool(q.interiors), q.area))
            if len(units) >= policy.max_units or (not q.interiors and q.area < 2*policy.min_unit_area_m2):
                continue
            a, b, c, d = q.bounds
            for axis in (0, 1):
                cuts = [_area_cut(q, axis, q.area/2)]
                if q.area > policy.target_unit_area_m2 + policy.min_unit_area_m2:
                    cuts.append(_area_cut(q, axis, policy.target_unit_area_m2))
                if q.interiors:
                    cuts.extend(v.centroid.coords[0][axis] for v in seed.common)
                for cut in cuts:
                    if examined >= policy.max_split_evaluations:
                        break
                    examined += 1
                    left = q.intersection(box(a-1, b-1, cut, d+1) if axis == 0 else box(a-1, b-1, c+1, cut))
                    right = q.difference(left)
                    parts = polygon_components(left) + polygon_components(right)
                    if len(parts) != 2 or any(v.area < policy.min_unit_area_m2 for v in parts):
                        continue
                    if any(v.geom_type != "Polygon" or not v.is_valid
                           or _contact(v, p) < policy.min_frontage_m
                           or _contact(v, common) < policy.min_access_m
                           or width_retention(v, policy.min_unit_width_m) < policy.width_retention for v in parts):
                        continue
                    leaves = [v for v in units if v is not q] + parts
                    cost = (sum(bool(v.interiors) for v in leaves),
                            sum(max(0, v.area-policy.max_unit_area_m2) for v in leaves),
                            np.mean([abs(v.area-policy.target_unit_area_m2) for v in leaves]),
                            sum(v.length for v in leaves))
                    pending.append((cost, leaves))
        states = [v for _, v in sorted(pending, key=lambda v: v[0])[:4]]
    if best is None:
        return None, "bounded_slicing_search_exhausted"
    best.metrics["subdivision_found"] = True
    best.metrics["split_evaluations"] = examined
    return best, "bounded_slicing_search_exhausted"


def generate_mfh_layout(footprint, policy=None, *, method="auto", prepared=False):
    """Return one receipt and Shapely partition in the caller's original metric frame.

    ``prepared=True`` is for the Core adapter after its normal cleanup. Ordinary callers
    receive fresh conservative preparation. Courtyards remain an explicit v1 fallback.
    """
    policy = policy or MfhLayoutPolicy()
    if method not in ("auto", "modules", "corridor", "offset", "slicing", "grid"):
        raise ValueError("Unknown MFH layout method")
    start = perf_counter()
    preparation = {}
    if not prepared:
        prep = prepare_geometry(footprint)
        preparation = dict(status=prep.status, reasons=list(prep.reasons), metrics=prep.metrics)
        footprint = prep.cleaned_geometry
        if prep.status != "accepted":
            return MfhLayoutResult(footprint, method, reason="preparation_"+prep.status,
                                   preparation=preparation)
    def fallback(reason):
        return MfhLayoutResult(footprint, method, reason=reason, preparation=preparation,
                               metrics=dict(runtime_s=perf_counter()-start))
    if footprint.geom_type != "Polygon" or footprint.is_empty or not footprint.is_valid:
        return fallback("invalid_or_multiple_footprints")
    if footprint.area < policy.min_footprint_m2:
        return fallback("small_footprint")
    if footprint.interiors:
        return fallback("courtyard_requires_reviewed_layout")
    if len(footprint.exterior.coords) > 128:
        return fallback("outline_complexity_budget")
    if width_retention(footprint, 2*policy.min_unit_width_m+policy.min_core_width_m) < policy.width_retention:
        return fallback("insufficient_floorplate_width")
    origin = footprint.centroid.coords[0]
    local = translate(footprint, -origin[0], -origin[1])
    angle = dominant_direction(local)
    p = set_precision(rotate(local, -angle, origin=(0, 0)), GRID)
    if method == "offset":
        result, reason = _offset(p, policy)
    elif method == "modules":
        result, reason = _modules(p, policy)
    elif method == "corridor":
        result, reason = _corridor(p, policy)
    else:
        modules, mr = _modules(p, policy)
        corridor, cr = _corridor(p, policy)
        seeds = [v for v in (modules, corridor) if v]
        seed = min(seeds, key=_score) if seeds else None
        if method == "auto":
            # Promotion remains evidence-gated: the inexpensive vector methods only.
            result, reason = seed, mr + "; " + cr
        elif method == "slicing":
            result, reason = _slicing(p, policy, seed)
        else:
            from ._mfh_grid import grid_layout
            result, reason = grid_layout(p, policy, seed)
    if result is None:
        return fallback(reason)
    # Transform a shared coordinate pool once so reciprocal boundaries remain identical.
    registry = {}
    def restore(q):
        def ring(r):
            out = []
            for point in r.coords:
                point = tuple(point)
                if point not in registry:
                    radians = math.radians(angle)
                    x, y = point
                    registry[point] = (x*math.cos(radians)-y*math.sin(radians)+origin[0],
                                       x*math.sin(radians)+y*math.cos(radians)+origin[1])
                out.append(registry[point])
            return out
        return Polygon(ring(q.exterior), [ring(r) for r in q.interiors])
    result.common = tuple(restore(q) for q in result.common)
    result.occupied = tuple(restore(q) for q in result.occupied)
    result.footprint = footprint
    try:
        validate_partitions(footprint, [*result.common, *result.occupied])
    except ValueError:
        return fallback("source_frame_coverage_failure")
    result.preparation = preparation
    result.metrics.update(runtime_s=perf_counter()-start, alignment_deg=angle,
                          requested_method=method, target_fraction=policy.target_unconditioned_fraction)
    return result


def generate_mfh_layouts(footprints, policy=None, *, method="auto"):
    """Batch wrapper; input geometries are explicitly planar metres, no CRS inference."""
    return [generate_mfh_layout(p, policy, method=method) for p in footprints]
