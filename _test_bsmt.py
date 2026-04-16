"""Quick check: basement exposed_area after adjacency + ground BC."""
from honeybee.room import Room
from honeybee.facetype import face_types
from honeybee.boundarycondition import Ground, Outdoors
from ladybug_geometry.geometry3d.pointvector import Point3D, Vector3D
from ladybug_geometry.geometry3d.face import Face3D

pts = [Point3D(0, 0, 0), Point3D(10, 0, 0), Point3D(10, 10, 0), Point3D(0, 10, 0)]
fp = [Face3D(pts)]

rooms_above = Room.rooms_from_footprint(fp, floor_to_floor_height=3, story_count=1, unique_id="above")
rooms_below = Room.rooms_from_footprint(fp, floor_to_floor_height=3, story_count=1, unique_id="below")
rooms_below[0].move(Vector3D(0, 0, -3))

Room.solve_adjacency(rooms_above + rooms_below, 0.01)

bsmt = rooms_below[0]
for face in bsmt.faces:
    if isinstance(face.boundary_condition, Outdoors):
        if face.type == face_types.floor:
            face.boundary_condition = Ground()
        elif face.type == face_types.wall:
            face.boundary_condition = Ground()

print(f"Basement exposed_area = {bsmt.exposed_area:.1f}")
print(f"Basement volume = {bsmt.volume:.1f}")
print(f"Basement floor_area = {bsmt.floor_area:.1f}")
for face in bsmt.faces:
    print(f"  {face.type}: {face.area:.1f}  BC={face.boundary_condition}")
