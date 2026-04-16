"""Compare Fjallvagen 28 vs median 1960s MFH in Uddevalla."""
import duckdb

con = duckdb.connect("epc_sweden.duckdb", read_only=True)

# Get Uddevalla kommun code
r = con.execute("SELECT DISTINCT IdKommunkod, IdKommun FROM epc WHERE IdKommun LIKE '%devall%'").fetchall()
print("Uddevalla:", r)
kommun_code = r[0][0]

# Fjallvagen 28 stats
fjall = con.execute(
    "SELECT FormularId, EgenNybyggAr, EgenAtemp, EgiEnergiPrestanda, EgiEnergiklass,"
    "EgenByggnadsTyp, VentTypF, VentTypFT, VentTypFTX, VentTypSjalvdrag, VentTypFmed "
    "FROM epc WHERE FormularId = 1033661"
).fetchone()
print(f"\n=== AGIR 17 (Fjallvagen 28) ===")
print(f"  Year: {fjall[1]}, Atemp: {fjall[2]}, EP: {fjall[3]}, Class: {fjall[4]}")
print(f"  Type: {fjall[5]}")
print(f"  Vent: F={fjall[6]}, FT={fjall[7]}, FTX={fjall[8]}, Sjalvdrag={fjall[9]}, Fmed={fjall[10]}")

# 1960s MFH in Uddevalla - distribution
print(f"\n=== 1950-1975 MFH in Uddevalla (kommun={kommun_code}) ===")
stats = con.execute(
    f"SELECT COUNT(*), ROUND(AVG(EgiEnergiPrestanda),1), ROUND(MEDIAN(EgiEnergiPrestanda),1),"
    f"ROUND(STDDEV(EgiEnergiPrestanda),1),"
    f"ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.25),1),"
    f"ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.75),1),"
    f"MIN(EgiEnergiPrestanda), MAX(EgiEnergiPrestanda),"
    f"ROUND(AVG(EgenAtemp),0), ROUND(MEDIAN(EgenAtemp),0) "
    f"FROM epc WHERE IdKommunkod = {kommun_code}"
    f" AND EgenNybyggAr BETWEEN 1950 AND 1975"
    f" AND EgenByggnadsTyp = 'Flerbostadshus'"
    f" AND EgiEnergiPrestanda > 0 AND EgenAtemp > 0"
).fetchone()
print(f"  n={stats[0]}")
print(f"  EP: mean={stats[1]}, median={stats[2]}, std={stats[3]}")
print(f"  EP: Q25={stats[4]}, Q75={stats[5]}, min={stats[6]}, max={stats[7]}")
print(f"  Atemp: mean={stats[8]}, median={stats[9]}")

# Percentile rank of Fjallvagen
pct = con.execute(
    f"SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE EgiEnergiPrestanda <= 110)"
    f" / COUNT(*), 1) "
    f"FROM epc WHERE IdKommunkod = {kommun_code}"
    f" AND EgenNybyggAr BETWEEN 1950 AND 1975"
    f" AND EgenByggnadsTyp = 'Flerbostadshus'"
    f" AND EgiEnergiPrestanda > 0"
).fetchone()
print(f"\n  AGIR 17 EP=110: percentile rank = {pct[0]}%")

# By ventilation type
print(f"\n=== By ventilation type ===")
vent = con.execute(
    f"SELECT CASE"
    f" WHEN VentTypFTX = 'Ja' THEN 'FTX'"
    f" WHEN VentTypFmed = 'Ja' THEN 'FVP'"
    f" WHEN VentTypFT = 'Ja' THEN 'FT'"
    f" WHEN VentTypF = 'Ja' THEN 'F'"
    f" WHEN VentTypSjalvdrag = 'Ja' THEN 'S'"
    f" ELSE 'Other' END as vent,"
    f" COUNT(*), ROUND(MEDIAN(EgiEnergiPrestanda),1), ROUND(AVG(EgiEnergiPrestanda),1)"
    f" FROM epc WHERE IdKommunkod = {kommun_code}"
    f" AND EgenNybyggAr BETWEEN 1950 AND 1975"
    f" AND EgenByggnadsTyp = 'Flerbostadshus'"
    f" AND EgiEnergiPrestanda > 0"
    f" GROUP BY vent ORDER BY COUNT(*) DESC"
).fetchall()
for v in vent:
    marker = " <-- same type" if v[0] == 'FVP' else ""
    print(f"  {v[0]:5s}: n={v[1]:3d}, median EP={v[2]:6.1f}, mean EP={v[3]:6.1f}{marker}")

# All FVP buildings individually
print(f"\n=== All 1950-75 FVP MFH in Uddevalla ===")
fvp = con.execute(
    f"SELECT FormularId, EgenNybyggAr, EgenAtemp, EgiEnergiPrestanda, EgiEnergiklass"
    f" FROM epc WHERE IdKommunkod = {kommun_code}"
    f" AND EgenNybyggAr BETWEEN 1950 AND 1975"
    f" AND EgenByggnadsTyp = 'Flerbostadshus'"
    f" AND VentTypSjalvdrag = 'Ja'"
    f" AND EgiEnergiPrestanda > 0"
    f" ORDER BY EgiEnergiPrestanda"
).fetchall()
for b in fvp:
    marker = " <-- AGIR 17" if b[0] == 1033661 else ""
    print(f"  {b[0]:>10d} | year={b[1]} | Atemp={b[2]:>5d} | EP={b[3]:>3d} | {b[4]}{marker}")

# Also nationwide comparison
print(f"\n=== NATIONWIDE 1950-75 MFH with FVP ===")
nat = con.execute(
    "SELECT COUNT(*), ROUND(MEDIAN(EgiEnergiPrestanda),1),"
    "ROUND(AVG(EgiEnergiPrestanda),1),"
    "ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.25),1),"
    "ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.75),1)"
    " FROM epc WHERE EgenNybyggAr BETWEEN 1950 AND 1975"
    " AND EgenByggnadsKat = 'Flerbostadshus'"
    " AND VentTypFmed = 'Ja'"
    " AND EgiEnergiPrestanda > 0"
).fetchone()
print(f"  n={nat[0]}, median={nat[1]}, mean={nat[2]}, Q25={nat[3]}, Q75={nat[4]}")

con.close()
