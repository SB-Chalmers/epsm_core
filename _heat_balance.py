"""Extract zone heating energy breakdown from EnergyPlus SQL output."""
import sqlite3

db = sqlite3.connect("idf/eplusout.sql")
cur = db.cursor()

ATEMP = 5078.0

# 1. Sensible heat gain summary - building total
print("=" * 70)
print("ANNUAL SENSIBLE HEAT BALANCE — Total Building")
print("=" * 70)
cur.execute("""
    SELECT ColumnName, Value
    FROM TabularDataWithStrings
    WHERE ReportName = 'SensibleHeatGainSummary'
      AND TableName = 'Annual Building Sensible Heat Gain Components'
      AND RowName = 'Total Facility'
""")
for col, val in cur.fetchall():
    try:
        gj = float(val)
        kwh = gj / 3.6 * 1000
        kwh_m2 = kwh / ATEMP
        if abs(gj) > 0.01:
            print(f"  {col:45s}: {gj:10.2f} GJ  = {kwh:10.0f} kWh  ({kwh_m2:6.1f} kWh/m2)")
    except ValueError:
        pass

# 2. Per-zone breakdown
print()
print("=" * 70)
print("PER-ZONE HEAT GAIN COMPONENTS")
print("=" * 70)

cur.execute("""
    SELECT DISTINCT RowName
    FROM TabularDataWithStrings
    WHERE ReportName = 'SensibleHeatGainSummary'
      AND TableName = 'Annual Building Sensible Heat Gain Components'
      AND RowName != 'Total Facility'
    ORDER BY RowName
""")
zones = [r[0] for r in cur.fetchall()]

cur.execute("""
    SELECT DISTINCT ColumnName
    FROM TabularDataWithStrings
    WHERE ReportName = 'SensibleHeatGainSummary'
      AND TableName = 'Annual Building Sensible Heat Gain Components'
""")
cols = [r[0] for r in cur.fetchall()]

# Sum conditioned vs unconditioned (Floor5 = attic)
cond_totals = {}
uncond_totals = {}
for zone in zones:
    is_attic = "floor5" in zone.lower()
    is_basement = "basement" in zone.lower()
    label = "ATTIC" if is_attic else ("BASEMENT" if is_basement else "COND")
    target = uncond_totals if is_attic else cond_totals

    for col in cols:
        cur.execute("""
            SELECT Value FROM TabularDataWithStrings
            WHERE ReportName = 'SensibleHeatGainSummary'
              AND TableName = 'Annual Building Sensible Heat Gain Components'
              AND RowName = ? AND ColumnName = ?
        """, (zone, col))
        row = cur.fetchone()
        if row:
            try:
                v = float(row[0])
                target[col] = target.get(col, 0.0) + v
            except ValueError:
                pass

print(f"\n{'Component':45s} {'Cond GJ':>10s} {'kWh/m2':>10s}")
print("-" * 67)
for col in cols:
    c = cond_totals.get(col, 0.0)
    kwh_m2 = c / 3.6 * 1000 / ATEMP
    if abs(c) > 0.01:
        print(f"  {col:43s} {c:10.2f} {kwh_m2:10.1f}")

# 3. Envelope summary — actual U-values used
print()
print("=" * 70)
print("ENVELOPE SUMMARY — Opaque Exterior")
print("=" * 70)
cur.execute("""
    SELECT RowName, ColumnName, Value
    FROM TabularDataWithStrings
    WHERE ReportName = 'EnvelopeSummary'
      AND TableName = 'Opaque Exterior'
    ORDER BY RowName, ColumnName
""")
surfaces = {}
for row_name, col_name, value in cur.fetchall():
    if row_name not in surfaces:
        surfaces[row_name] = {}
    surfaces[row_name][col_name] = value

# Print summary grouped by construction
from collections import defaultdict
by_construction = defaultdict(lambda: {"count": 0, "area": 0.0, "u": 0.0})
for sname, props in surfaces.items():
    cons = props.get("Construction", "?")
    area = float(props.get("Net Area [m2]", 0) or props.get("Gross Area [m2]", 0))
    u = float(props.get("U-Factor with Film [W/m2-K]", 0) or 0)
    by_construction[cons]["count"] += 1
    by_construction[cons]["area"] += area
    if u > 0:
        by_construction[cons]["u"] = u  # same for all surfaces with same construction

print(f"{'Construction':45s} {'Count':>6s} {'Area m2':>10s} {'U (film)':>10s}")
print("-" * 73)
for cons, data in sorted(by_construction.items()):
    print(f"  {cons:43s} {data['count']:6d} {data['area']:10.1f} {data['u']:10.3f}")

# 4. Fenestration
print()
print("=" * 70)
print("ENVELOPE SUMMARY — Exterior Fenestration")
print("=" * 70)
cur.execute("""
    SELECT RowName, ColumnName, Value
    FROM TabularDataWithStrings
    WHERE ReportName = 'EnvelopeSummary'
      AND TableName = 'Exterior Fenestration'
    ORDER BY RowName, ColumnName
""")
win_surfaces = {}
for row_name, col_name, value in cur.fetchall():
    if row_name not in win_surfaces:
        win_surfaces[row_name] = {}
    win_surfaces[row_name][col_name] = value

total_win_area = 0
win_u_values = []
for sname, props in win_surfaces.items():
    area = float(props.get("Area of Multiplied Openings [m2]", 0) or props.get("Glass Area [m2]", 0))
    u = float(props.get("Glass U-Factor [W/m2-K]", 0) or 0)
    total_win_area += area
    if u > 0:
        win_u_values.append((area, u))

if win_u_values:
    avg_u = sum(a * u for a, u in win_u_values) / sum(a for a, _ in win_u_values)
    print(f"  Total window area: {total_win_area:.1f} m2")
    print(f"  Area-weighted U:   {avg_u:.3f} W/m2K")
    print(f"  Window count:      {len(win_surfaces)}")

# 5. Outdoor air summary
print()
print("=" * 70)
print("OUTDOOR AIR SUMMARY")
print("=" * 70)
cur.execute("""
    SELECT RowName, ColumnName, Value
    FROM TabularDataWithStrings
    WHERE ReportName = 'OutdoorAirSummary'
    ORDER BY TableName, RowName, ColumnName
""")
for row in cur.fetchall():
    print(f"  {row[0]:50s} | {row[1]:30s} | {row[2]}")

db.close()
