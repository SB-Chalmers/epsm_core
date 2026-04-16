"""Extract envelope UA from E+ SQL and back-calculate U-value gap."""
import sqlite3
import os
import glob

# Find SQL
sql_path = None
for p in glob.glob("idf/**/eplusout.sql", recursive=True):
    sql_path = p
    break
if not sql_path:
    for p in glob.glob("results/**/eplusout.sql", recursive=True):
        sql_path = p
        break
print(f"SQL: {sql_path}")

con = sqlite3.connect(sql_path)
cur = con.cursor()

# --- Opaque surfaces ---
print("\n=== Opaque Exterior Surfaces ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "AND TableName = 'Opaque Exterior' "
    "AND ColumnName IN ('Construction','Gross Area','Net Area',"
    "'U-Factor with Film','U-Factor no Film') "
    "ORDER BY RowName, ColumnName"
)
opaque = {}
for row_name, col_name, value in cur.fetchall():
    opaque.setdefault(row_name, {})[col_name] = value

for name, cols in sorted(opaque.items()):
    print(f"  {name[:60]:60s} | constr={cols.get('Construction','?'):30s} "
          f"| gross={cols.get('Gross Area','?'):>8s} "
          f"| net={cols.get('Net Area','?'):>8s} "
          f"| U_film={cols.get('U-Factor with Film','?'):>6s} "
          f"| U_nofilm={cols.get('U-Factor no Film','?'):>6s}")

# --- Ground-contact surfaces ---
print("\n=== Ground Contact Surfaces ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "AND TableName = 'Opaque Exterior' "
    "AND RowName LIKE '%BASEMENT%' "
    "ORDER BY RowName, ColumnName"
)
for r in cur.fetchall():
    print(f"  {r[0]:60s} | {r[1]:20s} | {r[2]}")

# --- Also check underground walls table ---
print("\n=== Underground Surfaces ===")
cur.execute(
    "SELECT TableName FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "GROUP BY TableName"
)
tables = [r[0] for r in cur.fetchall()]
print(f"  Available tables: {tables}")

for tbl in tables:
    if 'underground' in tbl.lower() or 'ground' in tbl.lower():
        print(f"\n  --- {tbl} ---")
        cur.execute(
            "SELECT RowName, ColumnName, Value "
            "FROM TabularDataWithStrings "
            "WHERE ReportName = 'EnvelopeSummary' "
            f"AND TableName = '{tbl}' "
            "ORDER BY RowName, ColumnName"
        )
        for r in cur.fetchall():
            print(f"    {r[0]:60s} | {r[1]:20s} | {r[2]}")

# --- Fenestration ---
print("\n=== Exterior Fenestration ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "AND TableName = 'Exterior Fenestration' "
    "AND ColumnName IN ('Construction','Area of Multiplied Openings',"
    "'Glass Area','Glass U-Factor','SHGC') "
    "ORDER BY RowName, ColumnName"
)
fenest = {}
for row_name, col_name, value in cur.fetchall():
    fenest.setdefault(row_name, {})[col_name] = value

total_win_area = 0
total_win_ua = 0
for name, cols in sorted(fenest.items()):
    try:
        area = float(cols.get('Glass Area', '0') or '0')
        u = float(cols.get('Glass U-Factor', '0') or '0')
    except ValueError:
        continue
    total_win_area += area
    total_win_ua += area * u
    print(f"  {name[:60]:60s} | area={area:>7.1f} | U={u:.3f}")

print(f"\n  Total window: area={total_win_area:.1f} m2, UA={total_win_ua:.1f} W/K, "
      f"avg U={total_win_ua/total_win_area:.3f}" if total_win_area > 0 else "")

# --- Aggregate UA by element type ---
print("\n\n========== UA SUMMARY ==========")
# Parse opaque by construction type
wall_area = wall_ua = 0
roof_area = roof_ua = 0
floor_area = floor_ua = 0
bwall_area = bwall_ua = 0
bfloor_area = bfloor_ua = 0
other_area = other_ua = 0

for name, cols in opaque.items():
    constr = cols.get('Construction', '').upper()
    try:
        net = float(cols.get('Net Area', cols.get('Gross Area', '0')))
        u = float(cols.get('U-Factor with Film', '0'))
    except ValueError:
        continue
    ua = net * u
    
    name_up = name.upper()
    if 'BASEMENT' in constr or 'UNDERGROUND' in constr:
        if 'WALL' in constr or 'WALL' in name_up:
            bwall_area += net; bwall_ua += ua
        elif 'FLOOR' in constr or 'FLOOR' in name_up:
            bfloor_area += net; bfloor_ua += ua
        else:
            other_area += net; other_ua += ua
    elif 'WALL' in constr or 'EXT_WALL' in constr:
        wall_area += net; wall_ua += ua
    elif 'ROOF' in constr or 'TOP' in constr:
        roof_area += net; roof_ua += ua
    elif 'FLOOR' in constr or 'GROUND' in constr or 'SLAB' in constr:
        floor_area += net; floor_ua += ua
    else:
        other_area += net; other_ua += ua

def print_element(label, area, ua):
    u_avg = ua / area if area > 0 else 0
    print(f"  {label:25s}: area={area:>8.1f} m2, UA={ua:>8.1f} W/K, U_avg={u_avg:.3f} W/m2K")
    return ua

total_ua = 0
total_ua += print_element("Ext walls (above grade)", wall_area, wall_ua)
total_ua += print_element("Roof", roof_area, roof_ua)
total_ua += print_element("Ground floor/slab", floor_area, floor_ua)
total_ua += print_element("Basement walls", bwall_area, bwall_ua)
total_ua += print_element("Basement floor", bfloor_area, bfloor_ua)
total_ua += print_element("Windows", total_win_area, total_win_ua)
total_ua += print_element("Other", other_area, other_ua)
print(f"  {'TOTAL':25s}: UA={total_ua:.1f} W/K")

# --- Back-calculate required UA ---
print("\n\n========== GAP ANALYSIS ==========")
sim_atemp = 5078.0
heating_gap_kwh_m2 = 36.1  # 110 - 73.9
heating_gap_kwh = heating_gap_kwh_m2 * sim_atemp
print(f"Heating gap: {heating_gap_kwh_m2:.1f} kWh/m2 = {heating_gap_kwh:.0f} kWh total")

# UA_additional = gap_kWh * 1000 / (HDD * 24) ... but simpler:
# gap_W_avg = gap_kWh * 1000 / 8760
gap_w_avg = heating_gap_kwh * 1000 / 8760
# avg indoor-outdoor dT during heating season ~15K (22.3 - ~7 outdoor mean)
avg_dt = 15.0
ua_deficit = gap_w_avg / avg_dt
print(f"Average extra power needed: {gap_w_avg:.0f} W")
print(f"Assuming avg dT={avg_dt:.0f}K during heating season")
print(f"UA deficit: {ua_deficit:.0f} W/K")
print(f"Current total UA: {total_ua:.0f} W/K")
print(f"Required total UA: {total_ua + ua_deficit:.0f} W/K (+{ua_deficit/total_ua*100:.0f}%)")

# What if spread proportionally across all elements?
print(f"\nIf gap spread proportionally (+{ua_deficit/total_ua*100:.0f}% each):")
factor = (total_ua + ua_deficit) / total_ua
for label, area, ua in [
    ("Ext walls", wall_area, wall_ua),
    ("Roof", roof_area, roof_ua),
    ("Ground floor", floor_area, floor_ua),
    ("Bsmt walls", bwall_area, bwall_ua),
    ("Bsmt floor", bfloor_area, bfloor_ua),
    ("Windows", total_win_area, total_win_ua),
]:
    if area > 0:
        u_now = ua / area
        u_needed = u_now * factor
        print(f"  {label:15s}: U now={u_now:.3f} -> needed={u_needed:.3f} W/m2K")

con.close()
