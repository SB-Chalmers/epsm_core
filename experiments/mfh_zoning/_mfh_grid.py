"""Bounded four-neighbour apartment growth; the mesh is never thermal geometry."""

from collections import deque
from heapq import heappop, heappush
from math import ceil, floor

import numpy as np
import shapely

from .mfh_layouts import _candidate, _contact, _score, _usable


def _mesh(p, common, h, limit):
    a, b, c, d = p.bounds
    nx, ny = ceil((c-a)/h), ceil((d-b)/h)
    if nx*ny > limit:
        return None, "grid_cell_budget"
    occupied = p.difference(common)
    rows, columns = np.indices((ny, nx))
    x, y = a+columns.ravel()*h, b+rows.ravel()*h
    boxes = shapely.box(x, y, x+h, y+h)
    clipped = shapely.intersection(boxes, occupied)
    areas = shapely.area(clipped)
    active = areas > 0
    # A clipped cell containing separate pieces cannot be represented by one ownership ID.
    ambiguous = active & ((shapely.get_type_id(clipped) != 3) | (shapely.get_num_interior_rings(clipped) > 0))
    if ambiguous.any():
        return None, "disconnected_or_holed_grid_cell"
    indices = np.flatnonzero(active)
    adjacency = [[] for _ in range(nx*ny)]
    for i in indices:
        row, col = divmod(int(i), nx)
        for j in ((i+1 if col+1 < nx else -1), (i+nx if row+1 < ny else -1)):
            if j < 0 or not active[j]:
                continue
            # Full cells use the implicit lattice; clipped cells need real shared frontage.
            if (areas[i] >= h*h-1e-9 and areas[j] >= h*h-1e-9) or (
                clipped[i].boundary.intersection(clipped[j].boundary).length > 1e-7
            ):
                adjacency[i].append(int(j))
                adjacency[j].append(int(i))
    exterior = np.zeros(nx*ny, bool)
    access = np.zeros(nx*ny, bool)
    boundaries = shapely.boundary(clipped[indices])
    exterior[indices] = shapely.length(shapely.intersection(boundaries, p.boundary.buffer(5e-8))) > 1e-7
    access[indices] = shapely.length(shapely.intersection(boundaries, common.boundary.buffer(5e-8))) > 1e-7
    return dict(boxes=boxes, clipped=clipped, areas=areas, active=active, indices=indices,
                adjacency=adjacency, exterior=exterior, access=access, nx=nx, ny=ny,
                centers=np.column_stack((x+h/2, y+h/2)), occupied=occupied, h=h), None


def _distances(mesh, free):
    n = len(free)
    distances = np.full(n, -1, int)
    parents = np.full(n, -1, int)
    seeds = np.flatnonzero(mesh["access"] & free)
    queue = deque(int(v) for v in seeds)
    distances[seeds] = 0
    while queue:
        i = queue.popleft()
        for j in mesh["adjacency"][i]:
            if free[j] and distances[j] < 0:
                distances[j] = distances[i]+1
                parents[j] = i
                queue.append(j)
    return distances, parents


def _stroke(mesh, path, free, width):
    # At coarse resolution the reserved width rounds UP, never below the width screen.
    cells = ceil(width/mesh["h"])
    offsets = range(-(cells//2), cells-cells//2)
    nx, ny = mesh["nx"], mesh["ny"]
    selected = set()
    for k, i in enumerate(path):
        row, col = divmod(i, nx)
        other = path[min(k+1, len(path)-1)] if k+1 < len(path) else path[max(0, k-1)]
        dr, dc = divmod(other, nx)
        for delta in offsets:
            r, c = (row+delta, col) if row == dr else (row, col+delta)
            if 0 <= r < ny and 0 <= c < nx:
                j = r*nx+c
                if mesh["active"][j]:
                    if not free[j]:
                        return None
                    selected.add(j)
    # Keep only the connected patch attached to this path; other cells remain unassigned.
    connected, queue = {path[0]}, deque([path[0]])
    while queue:
        i = queue.popleft()
        for j in mesh["adjacency"][i]:
            if j in selected and j not in connected:
                connected.add(j)
                queue.append(j)
    return sorted(connected)


def _start(p, common, mesh, count, phase, policy):
    labels = np.full(len(mesh["active"]), -1, int)
    base_distances, _ = _distances(mesh, mesh["active"])
    facade = np.flatnonzero(mesh["exterior"] & (base_distances >= 0))
    if not len(facade):
        return None, "no_seedable_frontage"
    anchors = [p.exterior.interpolate((k+phase)*p.exterior.length/count)
               for k in range(count)]
    anchor_cells = [int(facade[np.argmin(np.linalg.norm(
        mesh["centers"][facade]-np.array(point.coords[0]), axis=1))]) for point in anchors]
    ordered = sorted(zip(anchor_cells, anchors), key=lambda v: (base_distances[v[0]], v[0]))
    patches = []
    for label, (_, anchor) in enumerate(ordered):
        free = mesh["active"] & (labels < 0)
        distances, parents = _distances(mesh, free)
        available = np.flatnonzero(mesh["exterior"] & free & (distances >= 0))
        if not len(available):
            return None, "seed_paths_block_frontage"
        # Reserve connections before growth. No routing optimiser or random restarts.
        cell = int(available[np.argmin(np.linalg.norm(
            mesh["centers"][available]-np.array(anchor.coords[0]), axis=1))])
        path = [cell]
        while parents[path[-1]] >= 0:
            path.append(int(parents[path[-1]]))
        patch = _stroke(mesh, path, free, policy.min_unit_width_m)
        if not patch:
            return None, "seed_path_conflict"
        geometry = shapely.union_all(mesh["boxes"][patch]).intersection(mesh["occupied"])
        # A reserved path can have clipped end cells and stair-step turns. Test its
        # connections now; the complete grown polygon gets the full width screen.
        if (geometry.geom_type != "Polygon" or not geometry.is_valid or geometry.interiors
                or _contact(geometry, p) < policy.min_frontage_m
                or _contact(geometry, common) < policy.min_access_m
                or geometry.area > policy.max_unit_area_m2):
            return None, "seed_width_frontage_or_access"
        labels[patch] = label
        patches.append(patch)
    # Every occupied component must have a seed; otherwise connected growth cannot fill it.
    reached, queue = set(i for patch in patches for i in patch), deque(i for patch in patches for i in patch)
    while queue:
        for j in mesh["adjacency"][queue.popleft()]:
            if j not in reached:
                reached.add(j)
                queue.append(j)
    if len(reached) != len(mesh["indices"]):
        return None, "unseeded_occupied_component"
    return (labels, patches), None


def _grow(mesh, start):
    labels, patches = start
    count = len(patches)
    centers = [np.mean(mesh["centers"][patch], axis=0) for patch in patches]
    areas = [sum(mesh["areas"][patch]) for patch in patches]
    target = sum(mesh["areas"])/count
    frontiers = [[] for _ in patches]

    def push(label, cell):
        shared = sum(labels[n] == label for n in mesh["adjacency"][cell])
        distance = float(np.linalg.norm(mesh["centers"][cell]-centers[label]))
        heappush(frontiers[label], (-shared, distance, cell))

    for label, patch in enumerate(patches):
        for i in patch:
            for j in mesh["adjacency"][i]:
                if labels[j] < 0:
                    push(label, j)
    turns = [(areas[label]/target, label) for label in range(count)]
    import heapq
    heapq.heapify(turns)
    while turns:
        _, label = heappop(turns)
        frontier = frontiers[label]
        while frontier and labels[frontier[0][2]] >= 0:
            heappop(frontier)
        if not frontier:
            continue
        _, _, cell = heappop(frontier)
        labels[cell] = label
        areas[label] += mesh["areas"][cell]
        for neighbor in mesh["adjacency"][cell]:
            if labels[neighbor] < 0:
                push(label, neighbor)
        heappush(turns, (areas[label]/target, label))
    if (labels[mesh["indices"]] < 0).any():
        return None
    return [shapely.union_all(mesh["boxes"][labels == label]).intersection(mesh["occupied"])
            for label in range(count)]


def _repair(units, p, common, policy):
    """One fragment absorption pass, preserving all positive area and source connectivity."""
    from epsm_core.zoning import polygon_components
    fixed, fragments = [], []
    for unit in units:
        pieces = sorted(polygon_components(unit), key=lambda q: q.area, reverse=True)
        if not pieces:
            return None
        fixed.append(pieces[0])
        fragments.extend(pieces[1:])
    for fragment in fragments:
        neighbours = sorted(range(len(fixed)), key=lambda i:
                            fixed[i].boundary.intersection(fragment.boundary).length, reverse=True)
        for i in neighbours:
            merged = fixed[i].union(fragment)
            if _usable(merged, p, common, policy, area=True):
                fixed[i] = merged
                break
        else:
            return None
    return fixed


def grid_layout(p, policy, seed):
    if seed is None:
        return None, "no_feasible_common_seed"
    common = shapely.union_all(seed.common)
    area = p.area-common.area
    minimum, maximum = ceil(area/policy.max_unit_area_m2), min(policy.max_units, floor(area/policy.min_unit_area_m2))
    if minimum > maximum:
        return None, "apartment_count_capacity"
    preferred = max(minimum, min(maximum, round(area/policy.target_unit_area_m2)))
    counts = sorted({max(minimum, min(maximum, preferred+i)) for i in (0, -1, 1)},
                    key=lambda n: abs(n-preferred))
    sizes = (policy.grid_size_m,) if policy.grid_size_m is not None else (2.0, 1.0, 0.5)
    attempts, history, reason = 0, [], "no_valid_grid_growth"
    best = None
    for h in sizes:
        mesh, failure = _mesh(p, common, h, policy.max_grid_cells)
        if mesh is None:
            reason = failure
            history.append(dict(grid_size_m=h, reason=failure, starts=0))
            continue
        used = 0
        for count in counts:
            for phase in (0, 1/3, 2/3):
                attempts += 1
                used += 1
                start, failure = _start(p, common, mesh, count, phase, policy)
                if start is None:
                    reason = failure
                    continue
                units = _grow(mesh, start)
                if units is None:
                    reason = "unfilled_grid_component"
                    continue
                units = _repair(units, p, common, policy)
                if units is None:
                    reason = "unrepairable_grid_fragment"
                    continue
                result, failure = _candidate(p, seed.common, units, "grid", policy,
                                             common_width=1.5, grid_size_m=h,
                                             grid_cells=len(mesh["active"]), growth_starts=attempts,
                                             subdivision_found=True)
                reason = failure or reason
                if result and (best is None or _score(result) < _score(best)):
                    best = result
                if result and result.status == "complete":
                    history.append(dict(grid_size_m=h, reason="complete", starts=used))
                    result.metrics["resolution_history"] = history
                    return result, None
        history.append(dict(grid_size_m=h, reason=reason, starts=used))
    if best is None:
        return None, reason
    best.metrics.update(growth_starts=attempts, resolution_history=history)
    return best, reason
