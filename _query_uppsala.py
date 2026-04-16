"""Query Uppsala MFH buildings stratified by ventilation type."""
import duckdb
import pandas as pd

con = duckdb.connect('epc_sweden.duckdb', read_only=True)

query = """
SELECT
    FormularId,
    IdFastBet,
    IdHusnr,
    IdAdr,
    EgenNybyggAr,
    EgenAtemp,
    EgiEnergiPrestanda AS EP,
    EgiEnergiklass AS Eklass,
    EgenByggnadsKat AS Kategori,
    EgenAntalPlan AS Vplan,
    EgenAntalBolgh AS Lgh,
    EgiFastighet AS FastEl_kWh,
    VentTypFTX,
    VentTypF,
    VentTypSjalvdrag,
    VentTypFT,
    CASE
        WHEN VentTypFTX = 'Ja' THEN 'FTX'
        WHEN VentTypFT  = 'Ja' THEN 'FT'
        WHEN VentTypF   = 'Ja' THEN 'F'
        WHEN VentTypSjalvdrag = 'Ja' THEN 'S'
        ELSE 'Other'
    END AS vent_type
FROM epc
WHERE IdKommun = 'Uppsala'
  AND EgenByggnadsKat = 'Flerbostadshus'
  AND EgenNybyggAr BETWEEN 1960 AND 1970
  AND EgenAtemp > 500
  AND EgiEnergiPrestanda > 0
  AND Godkand IS NOT NULL
  AND EgenAntalPlan >= 2
"""

df = con.execute(query).fetchdf()
con.close()

# Deduplicate: one random building per fastighet per vent_type
df = df.sample(frac=1, random_state=42)
df = df.drop_duplicates(subset=['vent_type', 'IdFastBet'], keep='first')

# Sample 10 per vent type
sampled = []
for vt in ['S', 'F', 'FT', 'FTX']:
    grp = df[df['vent_type'] == vt]
    n = min(10, len(grp))
    sampled.append(grp.head(n))
    print(f"  {vt}: {len(grp)} unique fastigheter available, sampled {n}")

df = pd.concat(sampled, ignore_index=True)

print(f"\nSampled {len(df)} buildings:")
for vt, g in df.groupby('vent_type'):
    print(f"  {vt}: {len(g)}, mean EP={g['EP'].mean():.0f}")

# Build output CSV matching uddevalahem_epc_list.csv format
out = pd.DataFrame({
    'FormularId': df['FormularId'],
    'Fastighet': df['IdFastBet'],
    'Husnr': df['IdHusnr'],
    'Adress': df['IdAdr'],
    'Byggar': df['EgenNybyggAr'],
    'Atemp': df['EgenAtemp'],
    'EP': df['EP'],
    'Eklass': df['Eklass'],
    'Kategori': df['Kategori'],
    'Archetype': 'CMF_1960',
    'Godkand': '',  # we don't have this easily
    'Vplan': df['Vplan'],
    'Lgh': df['Lgh'],
    'FJV_kWh': '',
    'FastEl_kWh': df['FastEl_kWh'],
    'FTX': df['VentTypFTX'],
    'F': df['VentTypF'],
    'Sjalvdrag': df['VentTypSjalvdrag'],
})

out.to_csv('uppsala_cmf1960_stratified.csv', index=False)
print(f"\nWrote {len(out)} rows to uppsala_cmf1960_stratified.csv")
print()
print(out[['Fastighet', 'Adress', 'Byggar', 'Atemp', 'EP', 'FTX', 'F', 'Sjalvdrag']].to_string())
