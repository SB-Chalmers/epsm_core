"""Analyze BETSI measured ventilation/infiltration data."""
import pandas as pd
import glob

# Load data
lk = pd.read_csv("betsi/LUFTKVALITET.csv", sep=";", decimal=",", encoding="latin-1")
fa = pd.read_csv("betsi/FA.csv", sep=";", decimal=",", encoding="latin-1")

# Uppräkningstal has age bands (only for SH but lets us map building IDs)
ut_fname = glob.glob("betsi/Uppr*kningstal.csv")
ut_fname = [f for f in ut_fname if "TVOC" not in f][0]
ut = pd.read_csv(ut_fname, sep=";", decimal=",", encoding="latin-1")

# Derive building type from ID prefix
lk["btype"] = lk["Byggnad"].str[:2]

# Measured total ventilation ACH for LGH1
col1 = [c for c in lk.columns if "specifikt" in c.lower() and "medel" in c.lower() and "LGH 1" in c][0]
lk[col1] = pd.to_numeric(lk[col1], errors="coerce")

# ---- OVERALL STATS ----
valid = lk[lk[col1].notna()]
print("=" * 60)
print("BETSI LUFTKVALITET - Measured TOTAL ventilation rates")
print("(includes mechanical ventilation + infiltration)")
print("=" * 60)

print(f"\nAll buildings: n={len(valid)}")
print(f"  Mean={valid[col1].mean():.2f}  Median={valid[col1].median():.2f}")

for bt in sorted(valid["btype"].dropna().unique()):
    sub = valid[valid["btype"] == bt]
    label = {"FH": "Flerbostadshus", "SH": "Småhus"}.get(bt, bt)
    print(f"  {bt} {label} (n={len(sub)}): mean={sub[col1].mean():.2f}  median={sub[col1].median():.2f}  std={sub[col1].std():.2f}")

# ---- FH (flerbostadshus) DETAIL ----
fh = valid[valid["btype"] == "FH"].copy()
print(f"\n{'=' * 60}")
print(f"FLERBOSTADSHUS (FH) - measured total ventilation")
print(f"{'=' * 60}")
print(f"n={len(fh)}")
print(f"Mean:   {fh[col1].mean():.2f} ACH")
print(f"Median: {fh[col1].median():.2f} ACH")
print(f"P10:    {fh[col1].quantile(0.10):.2f}")
print(f"P25:    {fh[col1].quantile(0.25):.2f}")
print(f"P75:    {fh[col1].quantile(0.75):.2f}")
print(f"P90:    {fh[col1].quantile(0.90):.2f}")

# ---- SH by age band ----
# Merge SH measurements with Uppräkningstal age bands
sh = valid[valid["btype"] == "SH"].copy()
sh_ut = sh.merge(ut[["Byggnad", "ald"]], on="Byggnad", how="left")
print(f"\n{'=' * 60}")
print(f"SMÅHUS by age band (from Uppräkningstal)")
print(f"{'=' * 60}")
for age in sorted(sh_ut["ald"].dropna().unique()):
    sub = sh_ut[sh_ut["ald"] == age]
    print(f"  {age} (n={len(sub)}): mean={sub[col1].mean():.2f}  median={sub[col1].median():.2f}  std={sub[col1].std():.2f}")

# ---- FH by ventilation type from FA data ----
# FA doesn't have vent type or construction year for FH.
# Let me try to get vent info from the FH.csv file (apartment-level)
fh_apt = pd.read_csv("betsi/FH.csv", sep=";", decimal=",", encoding="latin-1")
# Check for ventilation-related columns
vent_cols_fh = [c for c in fh_apt.columns if any(x in c.lower() for x in ["luft", "vent", "don", "kanal", "frånluft"])]
print(f"\n{'=' * 60}")
print(f"FH.csv ventilation-related columns:")
print(f"{'=' * 60}")
for c in vent_cols_fh:
    print(f"  {c}")

# The key column: FH13 Luft till lägenheten
col_luft = "FH13 Luft till lägenheten"
if col_luft in fh_apt.columns:
    print(f"\n{col_luft}:")
    print(fh_apt[col_luft].value_counts())

# ---- Distribution histogram ----
print(f"\n{'=' * 60}")
print(f"FH ACH distribution (histogram)")
print(f"{'=' * 60}")
bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.5, 3.0]
fh["bin"] = pd.cut(fh[col1], bins=bins)
print(fh["bin"].value_counts().sort_index())

