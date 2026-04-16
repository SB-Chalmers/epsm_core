"""Quick analysis of batch results."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(open("results_cmf1960.csv")))

ratios = [float(r["EPC_ratio"]) for r in rows]
heating = [float(r["Heating_kwh_m2"]) for r in rows]

print(f"N = {len(rows)} buildings")
print(f"EPC_ratio: min={min(ratios):.2f}  max={max(ratios):.2f}  "
      f"mean={sum(ratios)/len(ratios):.2f}  median={sorted(ratios)[len(ratios)//2]:.2f}")
print(f"Heating:   min={min(heating):.1f}  max={max(heating):.1f}  "
      f"mean={sum(heating)/len(heating):.1f}  median={sorted(heating)[len(heating)//2]:.1f} kWh/m2")
print()

# By ventilation system
by_vent = defaultdict(list)
for r in rows:
    by_vent[r["Ventilation"]].append(r)
for v in sorted(by_vent):
    rr = by_vent[v]
    h = [float(r["Heating_kwh_m2"]) for r in rr]
    rat = [float(r["EPC_ratio"]) for r in rr]
    ep = [float(r["EP_epc"]) for r in rr]
    print(f"  {v} (n={len(rr)}):  heating_mean={sum(h)/len(h):.1f}  "
          f"ratio_mean={sum(rat)/len(rat):.2f}  EP_epc_mean={sum(ep)/len(ep):.0f}")

print()
print("--- Atemp mismatches (sim/epc ratio > 30% off) ---")
for r in rows:
    sim_a = float(r["Atemp_sim"])
    epc_a = float(r["Atemp_epc"])
    ratio_a = sim_a / epc_a if epc_a else 0
    if abs(ratio_a - 1.0) > 0.3:
        print(f"  {r['Fastighet']} h{r['Husnr']}: sim={sim_a:.0f} epc={epc_a:.0f} "
              f"ratio={ratio_a:.2f}  depth={r['Apt_depth']}")

print()
print("--- Wall U-value check ---")
# Calculate wall U-value from the construction layers
layers = [
    ("eternit_board",    0.090, 0.500),
    ("brick_mortar_eff", 0.125, 0.860),
    ("mw_stud_eff",      0.190, 0.039),
    ("asphalt_board",    0.012, 0.230),
    ("plaster_board",    0.026, 0.160),
]
r_tot = 0.13 + 0.04  # Rsi + Rso
for name, thick, cond in layers:
    r = thick / cond
    r_tot += r
    print(f"  {name}: R={r:.3f}")
print(f"  Total R = {r_tot:.3f}  =>  U = {1/r_tot:.3f} W/m²K")
print(f"  (TABULA CMF_1960 reference wall U ~ 0.69 W/m²K)")

# Roof
print()
roof_layers = [
    ("metal_sheet",       0.003, 45.25),
    ("wood_battens",      0.046, 0.120),
    ("roofing_felt",      0.005, 0.160),
    ("wooden_panel",      0.030, 0.120),
    ("mineral_wool_roof", 0.150, 0.049),
    ("cardboard",         0.005, 0.110),
    ("concrete_ceiling",  0.140, 2.309),
]
r_roof = 0.13 + 0.04
for name, thick, cond in roof_layers:
    r_roof += thick / cond
print(f"  Roof: R={r_roof:.3f}  =>  U={1/r_roof:.3f} W/m²K")
print(f"  (TABULA CMF_1960 reference roof U ~ 0.42 W/m²K)")

# Floor
floor_layers = [
    ("leca",           0.150, 0.160),
    ("concrete_slab",  0.150, 2.309),
    ("woodfiber_board",0.013, 0.070),
    ("linoleum",       0.010, 0.160),
]
r_floor = 0.13 + 0.04
for name, thick, cond in floor_layers:
    r_floor += thick / cond
print(f"  Floor: R={r_floor:.3f}  =>  U={1/r_floor:.3f} W/m²K")
print(f"  Window: U=2.22 W/m²K  (TABULA ref ~ 2.7)")
