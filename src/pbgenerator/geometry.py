from __future__ import annotations

import math
from dataclasses import dataclass

from honeybee.room import Room
from honeybee.facetype import face_types
from honeybee.boundarycondition import Outdoors, Ground
from ladybug_geometry.geometry2d.pointvector import Point2D
from ladybug_geometry.geometry2d.polygon import Polygon2D
from ladybug_geometry.geometry3d.face import Face3D
from ladybug_geometry.geometry3d.pointvector import Point3D, Vector3D
from ladybug_geometry_polyskel.polysplit import perimeter_core_subpolygons

from .building_params import FacadeWWR


@dataclass
class BuildingRooms:
    """Container separating perimeter (conditioned) from core (unconditioned) rooms."""
    perimeter: list[Room]
    core: list[Room]

    @property
    def all(self) -> list[Room]:
        return self.perimeter + self.core

    @property
    def perimeter_floor_area(self) -> float:
        """Total floor area of perimeter rooms (Atemp proxy)."""
        return sum(r.floor_area for r in self.perimeter)

    @property
    def total_floor_area(self) -> float:
        return sum(r.floor_area for r in self.all)


def _translate_to_origin(pts: list[list[float]]) -> list[Point3D]:
    """Shift 2-D coordinates so the min-x / min-y sits at the origin.

    Accepts points in any projected CRS that uses metres (e.g. EPSG 3006).
    """
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x_min, y_min = min(xs), min(ys)
    return [Point3D(p[0] - x_min, p[1] - y_min, 0) for p in pts]


_CARDINAL_MAP = {
    "North": "north", "NorthEast": "north", "NorthWest": "north",
    "South": "south", "SouthEast": "south", "SouthWest": "south",
    "East": "east", "West": "west",
}


def _apply_wwr_by_cardinal(rooms: list[Room], wwr: FacadeWWR) -> None:
    """Add apertures to outdoor walls using per-cardinal-direction WWR."""
    ratios = {
        "north": max(0.01, min(0.95, wwr.north)),
        "east": max(0.01, min(0.95, wwr.east)),
        "south": max(0.01, min(0.95, wwr.south)),
        "west": max(0.01, min(0.95, wwr.west)),
    }
    for room in rooms:
        for face in room.faces:
            if face.type != face_types.wall:
                continue
            if not isinstance(face.boundary_condition, Outdoors):
                continue  # interior wall
            direction = _CARDINAL_MAP.get(face.cardinal_direction(), "north")
            face.apertures_by_ratio(ratios[direction])


def build_rooms(
    footprint_pts: list[list[float]],
    floor_height: float,
    num_floors: int,
    wwr: FacadeWWR,
    apartment_depth: float = 0.0,
    identifier: str = "Building",
    num_basement_floors: int = 0,
    basement_floor_height: float = 2.7,
    basement_depth_below_grade: float = 2.0,
    basement_wwr: float = 0.05,
) -> BuildingRooms:
    """Create Honeybee Rooms from a polygon footprint.

    Args:
        footprint_pts: List of [x, y] pairs describing the footprint polygon
            in a projected CRS (e.g. EPSG 3006).  Coordinates are translated
            so the polygon's bounding-box minimum sits at the world origin.
        floor_height: Storey height in metres.
        num_floors: Number of above-ground storeys.
        wwr: Per-cardinal-direction window-to-wall ratios.
        apartment_depth: Depth of each dwelling unit from the facade in metres.
            When > 0 a straight-skeleton split creates perimeter (dwelling)
            and core zones.  The depth is automatically clamped so it does not
            exceed what the polygon can support.
        identifier: Base identifier for the rooms.
        num_basement_floors: Number of heated basement floors below grade.
        basement_floor_height: Storey height of basement floors in metres.
        basement_depth_below_grade: How far the basement extends below grade [m].
            The above-grade strip = basement_floor_height - depth_below_grade.
        basement_wwr: WWR for the above-grade strip of basement walls.

    Returns:
        BuildingRooms with perimeter and core room lists.
    """
    local_pts = _translate_to_origin(footprint_pts)

    depth = solve_apartment_depth(footprint_pts, apartment_depth)

    if depth > 0:
        poly2d = Polygon2D([Point2D(pt.x, pt.y) for pt in local_pts])
        perim_polys, core_polys = perimeter_core_subpolygons(
            poly2d, distance=depth, tolerance=0.01,
        )
        n_perim = len(perim_polys)
        footprints = [
            Face3D([Point3D(pt.x, pt.y, 0) for pt in sp])
            for sp in perim_polys + core_polys
        ]
    else:
        n_perim = 1
        footprints = [Face3D(local_pts)]

    rooms = Room.rooms_from_footprint(
        footprints,
        floor_to_floor_height=floor_height,
        story_count=num_floors,
        unique_id=identifier,
    )

    # --- Basement rooms ---------------------------------------------------
    basement_rooms: list[Room] = []
    if num_basement_floors > 0:
        basement_rooms = _build_basement_rooms(
            local_pts=local_pts,
            basement_floor_height=basement_floor_height,
            num_basement_floors=num_basement_floors,
            depth_below_grade=basement_depth_below_grade,
            basement_wwr=basement_wwr,
            identifier=identifier,
        )

    all_rooms = list(rooms) + basement_rooms
    if len(all_rooms) > 1:
        Room.solve_adjacency(all_rooms, 0.01)

    # Rooms are created in the same order as footprints:
    # first n_perim footprints × num_floors = perimeter rooms,
    # remainder = core rooms.
    perim_per_floor = n_perim
    total_perim = perim_per_floor * num_floors
    perimeter_rooms = list(rooms[:total_perim]) + basement_rooms
    core_rooms = list(rooms[total_perim:])

    _apply_wwr_by_cardinal(list(rooms[:total_perim]), wwr)

    # Set ground BC on below-grade basement faces (after adjacency solving)
    for room in basement_rooms:
        _apply_basement_ground_bc(room, basement_depth_below_grade)

    return BuildingRooms(perimeter=perimeter_rooms, core=core_rooms)


def _build_basement_rooms(
    local_pts: list[Point3D],
    basement_floor_height: float,
    num_basement_floors: int,
    depth_below_grade: float,
    basement_wwr: float,
    identifier: str,
) -> list[Room]:
    """Create basement rooms positioned below z=0.

    The basement floor sits at z = -basement_floor_height and the ceiling
    at z = 0 (grade level).  The above-grade strip of each wall
    (basement_floor_height - depth_below_grade) gets small windows;
    below-grade walls and the floor slab get Ground BC (applied later).
    """
    footprint = [Face3D(local_pts)]
    rooms = Room.rooms_from_footprint(
        footprint,
        floor_to_floor_height=basement_floor_height,
        story_count=num_basement_floors,
        unique_id=f"{identifier}_Basement",
    )

    # Move rooms below grade so the top of the topmost basement is at z=0
    shift = Vector3D(0, 0, -basement_floor_height * num_basement_floors)
    for room in rooms:
        room.move(shift)

    # Add small windows to the above-grade strip of exterior walls.
    above_grade = basement_floor_height - depth_below_grade
    if above_grade > 0.1 and basement_wwr > 0:
        for room in rooms:
            # Only the topmost basement floor has walls above grade
            for face in room.faces:
                if face.type != face_types.wall:
                    continue
                if not isinstance(face.boundary_condition, Outdoors):
                    continue
                # Check if this wall has any portion above z=0
                max_z = max(v.z for v in face.vertices)
                if max_z <= 0.01:
                    continue  # fully below grade
                # The above-grade ratio of this wall
                wall_height = max(v.z for v in face.vertices) - min(v.z for v in face.vertices)
                if wall_height < 0.01:
                    continue
                above_ratio = min(1.0, above_grade / wall_height)
                effective_wwr = basement_wwr * above_ratio
                if effective_wwr > 0.005:
                    face.apertures_by_ratio(effective_wwr)

    return rooms


def _apply_basement_ground_bc(room: Room, depth_below_grade: float) -> None:
    """Set Ground boundary condition on below-grade faces of a basement room.

    - Floor faces (horizontal, facing down): always Ground.
    - Wall faces: Ground if their top is at or below grade (z <= 0).
      Walls with portions above grade keep Outdoors BC (they may have windows).
    """
    for face in room.faces:
        if isinstance(face.boundary_condition, Outdoors):
            if face.type == face_types.floor:
                # Basement slab is always ground-contact
                face.boundary_condition = Ground()
            elif face.type == face_types.wall:
                # If the wall top is at or below grade, set to Ground
                max_z = max(v.z for v in face.vertices)
                if max_z <= 0.01:
                    face.boundary_condition = Ground()


def solve_apartment_depth(
    footprint_pts: list[list[float]],
    target_depth: float,
) -> float:
    """Return apartment depth clamped to what the footprint can support.

    Computes the approximate inradius of the polygon (minimum perpendicular
    distance from the centroid to any edge) and caps the depth so the
    straight-skeleton split always produces a valid core.

    Returns 0 if the footprint is too narrow for a meaningful split (< 1 m).
    """
    if target_depth <= 0:
        return 0.0

    xs = [p[0] for p in footprint_pts]
    ys = [p[1] for p in footprint_pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    n = len(footprint_pts)
    min_dist = float("inf")
    for i in range(n):
        x1, y1 = footprint_pts[i]
        x2, y2 = footprint_pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        edge_len = math.hypot(dx, dy)
        if edge_len < 1e-6:
            continue
        dist = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / edge_len
        min_dist = min(min_dist, dist)

    safe = max(0.0, min_dist - 0.5)
    depth = min(target_depth, safe)
    return depth if depth >= 1.0 else 0.0


def _perimeter_area_at_depth(poly2d: Polygon2D, depth: float) -> float | None:
    """Return total perimeter sub-polygon area for a given depth.

    Returns None if the straight-skeleton split fails (e.g. depth too large).
    """
    try:
        perim_polys, _ = perimeter_core_subpolygons(poly2d, distance=depth, tolerance=0.01)
        return sum(p.area for p in perim_polys)
    except Exception:
        return None


def _max_viable_depth(poly2d: Polygon2D, ceiling: float = 20.0) -> float:
    """Find the largest depth that produces a valid perimeter/core split.

    Starts from *ceiling* and halves until the skeleton split succeeds and
    produces a non-trivial core (area < gross).  Returns 0 if nothing works.
    """
    gross = poly2d.area
    d = min(ceiling, math.sqrt(gross) / 2)  # sensible starting upper bound
    for _ in range(15):
        area = _perimeter_area_at_depth(poly2d, d)
        if area is not None and area < gross * 0.999:
            return d
        d *= 0.7
        if d < 0.5:
            break
    return 0.0


def solve_depth_for_atemp(
    footprint_pts: list[list[float]],
    target_atemp: float,
    total_floors: int,
    max_depth: float = 20.0,
) -> float:
    """Find the apartment depth that makes perimeter_floor_area ≈ target_atemp.

    Uses bisection on the depth parameter.  The perimeter area is monotonically
    increasing with depth (up to the point where the core vanishes), so
    bisection is reliable.

    Returns 0 if the full footprint area × floors is already smaller than
    target_atemp (depth can't help — footprint is too small).
    """
    if total_floors <= 0 or target_atemp <= 0:
        return 0.0

    local_pts = _translate_to_origin(footprint_pts)
    poly2d = Polygon2D([Point2D(pt.x, pt.y) for pt in local_pts])
    gross_area = poly2d.area

    target_per_floor = target_atemp / total_floors

    # If footprint is already smaller than target, no depth can help
    if gross_area <= target_per_floor:
        return 0.0

    # Find maximum viable depth via probing (works for concave polygons)
    viable_max = _max_viable_depth(poly2d, max_depth)
    if viable_max < 1.0:
        return 0.0

    # Check if even max depth undershoots (perimeter area at max < target)
    area_at_max = _perimeter_area_at_depth(poly2d, viable_max)
    if area_at_max is not None and area_at_max <= target_per_floor:
        return round(viable_max, 1)

    # Bisect: find depth where perimeter_area = target_per_floor
    lo, hi = 0.5, viable_max
    for _ in range(30):
        mid = (lo + hi) / 2.0
        area = _perimeter_area_at_depth(poly2d, mid)
        if area is None or area < target_per_floor:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.05:
            break

    return round((lo + hi) / 2.0, 1)
