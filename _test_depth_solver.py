from src.pbgenerator.epc_io import load_footprints, load_epc_metadata
from src.pbgenerator.geometry import solve_depth_for_atemp, build_rooms, solve_apartment_depth
from src.pbgenerator.building_params import FacadeWWR

# Test with Laxen 1 h1: fp=1323 m², 4+1=5 floors, EPC Atemp=4784
fps = load_footprints(formular_id=755729, limit=10)
fp = [f for f in fps if "Flerfamiljshus" in f.andamal][0]
epc_atemp = 4784
total_floors = 5

print(f"Footprint area: {fp.footprint_area:.0f} m2")
print(f"Gross estimate: {fp.footprint_area * total_floors:.0f} m2")
print(f"EPC Atemp: {epc_atemp}")
print()

# Old approach: fixed 5m depth
d_old = solve_apartment_depth(fp.footprint_pts, 5.0)
bldg_old = build_rooms(fp.footprint_pts, 2.7, 4, FacadeWWR(0,0,0,0),
                        apartment_depth=5.0, num_basement_floors=1)
print(f"Old (depth=5.0, solved={d_old:.1f}): perim_atemp={bldg_old.perimeter_floor_area:.0f}")

# New approach: solve depth for EPC Atemp
d_new = solve_depth_for_atemp(fp.footprint_pts, epc_atemp, total_floors)
bldg_new = build_rooms(fp.footprint_pts, 2.7, 4, FacadeWWR(0,0,0,0),
                        apartment_depth=d_new, num_basement_floors=1)
print(f"New (solved depth={d_new:.1f}): perim_atemp={bldg_new.perimeter_floor_area:.0f}")

# Also test Karpen 1: fp too small (333 vs needs 602)
print()
fps2 = load_footprints(formular_id=755764, limit=10)
fp2 = [f for f in fps2 if "Flerfamiljshus" in f.andamal][0]
print(f"Karpen 1: fp_area={fp2.footprint_area:.0f}, 8 floors, EPC=4818")
d2 = solve_depth_for_atemp(fp2.footprint_pts, 4818, 8)
print(f"  Solved depth={d2:.1f} (0 = footprint too small, use full)")
