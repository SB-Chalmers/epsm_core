"""Check ground temperature and basement infiltration issues."""
import sqlite3

ATEMP = 5078.0
con = sqlite3.connect("idf/eplusout.sql")

# 1. Ground-contact surfaces
rows = con.execute("""
    SELECT s.SurfaceName, s.ClassName, s.GrossArea, c.Name as Construction
    FROM Surfaces s
    LEFT JOIN Constructions c ON s.ConstructionIndex = c.ConstructionIndex
    WHERE s.ExtBoundCond = -1
    ORDER BY s.ClassName
""").fetchall()

print("=== Ground-contact surfaces ===")
total_ground_area = 0
for name, cls, area, cons in rows[:5]:
    print(f"  {cls:6s} area={area:.1f} m2  {cons}")
    total_ground_area += area
for name, cls, area, cons in rows[5:]:
    total_ground_area += area
print(f"  ... {len(rows)} surfaces, total {total_ground_area:.0f} m2")

# 2. Ground temperature impact
print("\n=== Ground temperature impact ===")
dT_wrong = 22.3 - 18.0   # E+ default 18C
dT_right = 22.3 - 7.5    # realistic for Uddevalla
print(f"  Default 18C -> dT = {dT_wrong:.1f} K")
print(f"  Realistic 7.5C -> dT = {dT_right:.1f} K")
print(f"  Loss multiplier: {dT_right / dT_wrong:.1f}x")

# Rough U: basement wall ~0.5, floor ~0.24, weighted avg ~0.3
U_avg = 0.30
current_loss_W = U_avg * total_ground_area * dT_wrong
correct_loss_W = U_avg * total_ground_area * dT_right
extra_W = correct_loss_W - current_loss_W
# Use heating degree hours for more accuracy
# Uddevalla: ~85000 Kh indoors = 22.3C
heating_hrs = 6000  # hours/yr where heating is needed
extra_kWh = extra_W * heating_hrs / 1000
print(f"  Extra ground loss: ~{extra_kWh:.0f} kWh/yr = {extra_kWh / ATEMP:.1f} kWh/m2")

# 3. Basement infiltration
print("\n=== Basement infiltration (currently 0) ===")
bsmt_vol = 2741.9
target_ach = 0.15  # conservative for basement
flow = target_ach * bsmt_vol / 3600
# rough annual infiltration loss: flow * rho * cp * DDH
# DDH for 22.3C base, ~85000 Kh for Uddevalla
rho_cp = 1.2 * 1005  # J/m3K
DDH = 85000  # degree-hours
inf_loss_kWh = flow * rho_cp * DDH / 1e6 * 3.6  # MJ -> kWh
print(f"  If ACH={target_ach}: flow={flow:.3f} m3/s")
print(f"  Annual loss: ~{inf_loss_kWh:.0f} kWh = {inf_loss_kWh / ATEMP:.1f} kWh/m2")

# 4. Basement internal gains (currently same as residential floors)
print("\n=== Basement internal gains (over-counted) ===")
bsmt_floor = 1015.5
equip_gain = 1.68 * bsmt_floor * 8760 / 1000  # kWh/yr
people_gain = 0.017 * 80 * bsmt_floor * (14/24) * 8760 / 1000  # 14h/day
# In reality, basement has ~10% of residential gains
real_frac = 0.10
excess_equip = equip_gain * (1.0 - real_frac)
excess_people = people_gain * (1.0 - real_frac)
print(f"  Equipment gain: {equip_gain:.0f} kWh/yr (full), realistic ~{equip_gain * real_frac:.0f}")
print(f"  People gain: {people_gain:.0f} kWh/yr (full), realistic ~{people_gain * real_frac:.0f}")
print(f"  Excess free heat: {(excess_equip + excess_people):.0f} kWh = {(excess_equip + excess_people) / ATEMP:.1f} kWh/m2")

# 5. Total gap analysis
print("\n=== GAP ANALYSIS ===")
sim_delivered = 83.6
epc_norm = 110.0
epc_raw = 93.2
print(f"  Current sim: {sim_delivered:.1f} kWh/m2")
print(f"  EPC norm:    {epc_norm:.0f} kWh/m2  (gap = {epc_norm - sim_delivered:.1f})")
print(f"  EPC raw:     {epc_raw:.1f} kWh/m2  (gap = {epc_raw - sim_delivered:.1f})")
ground_fix = extra_kWh / ATEMP
inf_fix = inf_loss_kWh / ATEMP
gains_fix = (excess_equip + excess_people) / ATEMP
total_fix = ground_fix + inf_fix + gains_fix
print(f"\n  Fixes:")
print(f"    Ground temp 18->7.5C:    +{ground_fix:.1f} kWh/m2")
print(f"    Basement infiltration:   +{inf_fix:.1f} kWh/m2")
print(f"    Reduce basement gains:   +{gains_fix:.1f} kWh/m2")
print(f"    TOTAL correction:        +{total_fix:.1f} kWh/m2")
print(f"    Corrected sim:           {sim_delivered + total_fix:.1f} kWh/m2")

con.close()
