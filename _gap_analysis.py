"""One-off gap analysis: what explains sim vs EPC gap beyond U-values?"""

epc_normalaar = 110.0
sim_delivered = 73.9
gap = epc_normalaar - sim_delivered
print(f"Total gap: {gap:.1f} kWh/m2")
print()

# 1. Ground temperature: E+ default 18C vs real Swedish ~6C annual mean
u_floor_slab = 1.08   # CMF_1960_2_BASEMENT_FLOOR_TB
floor_area = 1015.5   # m2 footprint
sim_atemp = 5078.0
indoor = 22.3

dt_default = indoor - 18.0   # 4.3 K  (what E+ simulates)
dt_real = indoor - 6.0       # 16.3 K (real annual mean ground temp Sweden)

# Additional ground floor loss beyond what sim already captures
extra_floor = u_floor_slab * floor_area * (dt_real - dt_default) * 8760 / 1000
extra_floor_m2 = extra_floor / sim_atemp
print(f"1a. Ground temp (floor slab):")
print(f"    U={u_floor_slab}, A={floor_area}, extra dT={dt_real-dt_default:.0f}K")
print(f"    -> +{extra_floor_m2:.1f} kWh/m2")

# Basement walls below grade ~325 m2, U~4.4
u_bsmt_wall = 4.39   # CMF_1960_2_BASEMENT_WALL_TB
bsmt_wall_area = 325.0
extra_bwall = u_bsmt_wall * bsmt_wall_area * (dt_real - dt_default) * 8760 / 1000
extra_bwall_m2 = extra_bwall / sim_atemp
print(f"1b. Ground temp (basement walls):")
print(f"    U={u_bsmt_wall}, A~{bsmt_wall_area}")
print(f"    -> +{extra_bwall_m2:.1f} kWh/m2")

total_ground = extra_floor_m2 + extra_bwall_m2
print(f"    TOTAL ground temp error: +{total_ground:.1f} kWh/m2")
print()

# 2. Distribution losses (pipes from DH substation to radiators)
epc_heating_raw = 67.3
dist_pct = 0.05
dist_loss = dist_pct * epc_heating_raw
print(f"2. Distribution losses (~5%): +{dist_loss:.1f} kWh/m2")
print()

# 3. Weather file mismatch
# TMYx 2011-2025 may be warmer than SMHI normal period used for EPC correction
# Hard to quantify without checking degree-days of both
print("3. TMY vs SMHI normal period: uncertain (likely 0-5 kWh/m2)")
print()

# Summary
explained = total_ground + dist_loss
remaining = gap - explained
print("=== Gap accounting ===")
print(f"Total gap:             {gap:.1f} kWh/m2")
print(f"Ground temp error:    +{total_ground:.1f} kWh/m2  << MAJOR")
print(f"Distribution loss:    +{dist_loss:.1f} kWh/m2")
print(f"Explained so far:    +{explained:.1f} kWh/m2")
print(f"Remaining for U-vals: {remaining:.1f} kWh/m2")
