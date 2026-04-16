from src.pbgenerator.epc_io import load_footprints
import math

fps = load_footprints(formular_id=755729, limit=10)
fp = [f for f in fps if "Flerfamiljshus" in f.andamal][0]
pts = fp.footprint_pts

xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
print(f"BBox: {max(xs)-min(xs):.1f} x {max(ys)-min(ys):.1f} m")
print(f"Area: {fp.footprint_area:.0f} m2")
print(f"Num vertices: {len(pts)}")

cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
n = len(pts)
min_dist = float("inf")
for i in range(n):
    x1, y1 = pts[i]
    x2, y2 = pts[(i+1) % n]
    dx, dy = x2 - x1, y2 - y1
    el = math.hypot(dx, dy)
    if el < 1e-6:
        continue
    dist = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / el
    if dist < min_dist:
        min_dist = dist
print(f"Min centroid-to-edge: {min_dist:.1f} m")
print(f"Safe depth: {max(0, min_dist - 0.5):.1f} m")
print()

for i in range(n):
    x1, y1 = pts[i]
    x2, y2 = pts[(i+1) % n]
    el = math.hypot(x2 - x1, y2 - y1)
    print(f"  edge {i}: {el:.1f} m")
