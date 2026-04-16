"""Compare Fjallvagen 28 vs median 1960s MFH in Uddevalla."""
import duckdb

con = duckdb.connect("epc_sweden.duckdb", read_only=True)
KAT = "Flerbostadshus"
KOMMUN = 85  # Uddevalla

# Fjallvagen 28 stats
fjall = con.execute(
    "SELECT FormularId, EgenNybyggAr, EgenAtemp, EgiEnergiPrestanda, EgiEnergiklass,"
    " EgenByggnadsKat, EgenByggnadsTyp,"
    " VentTypF, VentTypFT, VentTypFTX, VentTypSjalvdrag, VentTypFmed"
    " FROM epc WHERE FormularId = 1033661"
).fetchone()
print("=== AGIR 17 (Fjallvagen 28) ===")
print(f"  Year: {fjall[1]}, Atemp: {fjall[2]}, EP: {fjall[3]}, Class: {fjall[4]}")
print(f"  Kat: {fjall[5]}, Typ: {fjall[6]}")
print(f"  Vent: F={fjall[7]}, FT={fjall[8]}, FTX={fjall[9]}, Sjalvdrag={fjall[10]}, Fmed={fjall[11]}")

# 1950-1975 MFH in Uddevalla - distribution
print(f"\n=== 1950-1975 MFH in Uddevalla ===")
stats = con.execute(f"""
    SELECT COUNT(*), ROUND(AVG(EgiEnergiPrestanda),1), ROUND(MEDIAN(EgiEnergiPrestanda),1),
        ROUND(STDDEV(EgiEnergiPrestanda),1),
        ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.25),1),
        ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.75),1),
        MIN(EgiEnergiPrestanda), MAX(EgiEnergiPrestanda),
        ROUND(AVG(EgenAtemp),0), ROUND(MEDIAN(EgenAtemp),0)
    FROM epc WHERE IdKommunkod = {KOMMUN}
        AND EgenNybyggAr BETWEEN 1950 AND 1975
        AND EgenByggnadsKat = '{KAT}'
        AND EgiEnergiPrestanda > 0 AND EgenAtemp > 0
""").fetchone()
print(f"  n={stats[0]}")
print(f"  EP: mean={stats[1]}, median={stats[2]}, std={stats[3]}")
print(f"  EP: Q25={stats[4]}, Q75={stats[5]}, min={stats[6]}, max={stats[7]}")
print(f"  Atemp: mean={stats[8]}, median={stats[9]}")

# Percentile rank
pct = con.execute(f"""
    SELECT ROUND(100.0 * SUM(CASE WHEN EgiEnergiPrestanda <= 110 THEN 1 ELSE 0 END)
           / COUNT(*), 1)
    FROM epc WHERE IdKommunkod = {KOMMUN}
        AND EgenNybyggAr BETWEEN 1950 AND 1975
        AND EgenByggnadsKat = '{KAT}'
        AND EgiEnergiPrestanda > 0
""").fetchone()
print(f"\n  AGIR 17 EP=110: percentile rank = {pct[0]}%")

# By ventilation type
print(f"\n=== By ventilation type ===")
vent = con.execute(f"""
    SELECT CASE
        WHEN VentTypFTX = 'Ja' THEN 'FTX'
        WHEN VentTypFmed = 'Ja' THEN 'FVP'
        WHEN VentTypFT = 'Ja' THEN 'FT'
        WHEN VentTypF = 'Ja' THEN 'F'
        WHEN VentTypSjalvdrag = 'Ja' THEN 'S'
        ELSE 'Other' END as vent,
        COUNT(*), ROUND(MEDIAN(EgiEnergiPrestanda),1), ROUND(AVG(EgiEnergiPrestanda),1)
    FROM epc WHERE IdKommunkod = {KOMMUN}
        AND EgenNybyggAr BETWEEN 1950 AND 1975
        AND EgenByggnadsKat = '{KAT}'
        AND EgiEnergiPrestanda > 0
    GROUP BY vent ORDER BY COUNT(*) DESC
""").fetchall()
for v in vent:
    marker = " <-- AGIR 17" if v[0] == 'S' else ""
    print(f"  {v[0]:5s}: n={v[1]:4d}, median EP={v[2]:6.1f}, mean EP={v[3]:6.1f}{marker}")

# All självdrag buildings sorted by EP
print(f"\n=== 1950-75 Självdrag MFH in Uddevalla (sample, sorted by EP) ===")
sd = con.execute(f"""
    SELECT FormularId, EgenNybyggAr, EgenAtemp, EgiEnergiPrestanda, EgiEnergiklass
    FROM epc WHERE IdKommunkod = {KOMMUN}
        AND EgenNybyggAr BETWEEN 1950 AND 1975
        AND EgenByggnadsKat = '{KAT}'
        AND VentTypSjalvdrag = 'Ja'
        AND EgiEnergiPrestanda > 0
    ORDER BY EgiEnergiPrestanda
""").fetchall()
for i, b in enumerate(sd):
    marker = " <-- AGIR 17" if b[0] == 1033661 else ""
    print(f"  {b[0]:>10d} | year={b[1]} | Atemp={b[2]:>5d} | EP={b[3]:>3d} | {b[4]}{marker}")
    if i > 40 and not marker:
        print(f"  ... ({len(sd) - i - 1} more)")
        break

# Nationwide comparison
print(f"\n=== NATIONWIDE 1950-75 MFH with Sjalvdrag ===")
nat = con.execute("""
    SELECT COUNT(*), ROUND(MEDIAN(EgiEnergiPrestanda),1),
        ROUND(AVG(EgiEnergiPrestanda),1),
        ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.25),1),
        ROUND(QUANTILE_CONT(EgiEnergiPrestanda, 0.75),1)
    FROM epc WHERE EgenNybyggAr BETWEEN 1950 AND 1975
        AND EgenByggnadsKat = 'Flerbostadshus'
        AND VentTypSjalvdrag = 'Ja'
        AND EgiEnergiPrestanda > 0
""").fetchone()
print(f"  n={nat[0]}, median={nat[1]}, mean={nat[2]}, Q25={nat[3]}, Q75={nat[4]}")

con.close()
