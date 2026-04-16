"""Find the top-floor ceiling (vindsbjalklag) construction."""
import sqlite3, glob

sql = glob.glob("idf/**/eplusout.sql", recursive=True)[0]
con = sqlite3.connect(sql)
cur = con.cursor()

# 1. Find all constructions used
print("=== All constructions in model ===")
cur.execute(
    "SELECT DISTINCT Value FROM TabularDataWithStrings "
    "WHERE ColumnName = 'Construction' ORDER BY Value"
)
for r in cur.fetchall():
    print(f"  {r[0]}")

# 2. Find surfaces referencing TOP_FLOOR
print("\n=== Surfaces with TOP_FLOOR construction ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE Value LIKE '%TOP_FLOOR%' "
    "ORDER BY RowName"
)
for r in cur.fetchall():
    print(f"  {r[0][:60]:60s} | {r[1]:20s} | {r[2]}")

# 3. Interior surfaces of floor 4 (ceiling = top floor ceiling)
print("\n=== Floor 4 interior surfaces ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "AND RowName LIKE '%FLOOR4%' "
    "AND ColumnName IN ('Construction','Gross Area','U-Factor with Film') "
    "ORDER BY RowName, ColumnName"
)
data = {}
for name, col, val in cur.fetchall():
    data.setdefault(name, {})[col] = val
for name, cols in sorted(data.items()):
    c = cols.get('Construction', '?')
    a = cols.get('Gross Area', '?')
    u = cols.get('U-Factor with Film', '?')
    if 'TOP' in c or 'INTERIOR' in c or 'INTER' in c.upper():
        print(f"  {name[:60]:60s} | {c:30s} | A={a:>8s} | U={u}")

# 4. Floor 5 (cold attic) floor surface = the vindsbjalklag from above
print("\n=== Floor 5 (attic) floor surface ===")
cur.execute(
    "SELECT RowName, ColumnName, Value "
    "FROM TabularDataWithStrings "
    "WHERE ReportName = 'EnvelopeSummary' "
    "AND RowName LIKE '%FLOOR5%' "
    "AND ColumnName IN ('Construction','Gross Area','U-Factor with Film') "
    "ORDER BY RowName, ColumnName"
)
data2 = {}
for name, col, val in cur.fetchall():
    data2.setdefault(name, {})[col] = val
for name, cols in sorted(data2.items()):
    c = cols.get('Construction', '?')
    a = cols.get('Gross Area', '?')
    u = cols.get('U-Factor with Film', '?')
    print(f"  {name[:60]:60s} | {c:30s} | A={a:>8s} | U={u}")

# 5. Check the IDF for construction layers of TOP_FLOOR 
print("\n=== Checking IDF for TOP_FLOOR construction ===")
idf_path = glob.glob("idf/**/in.idf", recursive=True)[0]
with open(idf_path) as f:
    text = f.read()

import re
# Find the construction definition
for m in re.finditer(r'(?i)(Construction,\s*\n\s*CMF_1960_2_TOP_FLOOR.*?)(?=\n\n|\nConstruction,)', text, re.DOTALL):
    print(m.group(0))

con.close()
