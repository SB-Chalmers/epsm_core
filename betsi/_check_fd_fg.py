"""Check FD and FG for FH construction year or ventilation system."""
import pandas as pd

# FD - building condition/damage
fd = pd.read_csv("betsi/FD.csv", sep=";", decimal=",", encoding="latin-1")
fd_fh = fd[fd["Byggnad"].str.startswith("FH", na=False)]
print("FD.csv columns:")
for c in fd.columns:
    print(f"  {c}")
print(f"\nFH rows: {len(fd_fh)}")

# Check for vent system in FG
print("\n" + "=" * 60)
fg = pd.read_csv("betsi/FG.csv", sep=";", decimal=",", encoding="latin-1")
fg_fh = fg[fg["Byggnad"].str.startswith("FH", na=False)]
print(f"FG.csv FH rows: {len(fg_fh)}")
print("FG.csv columns:")
for c in fg.columns:
    print(f"  {c}")

# Look for ventilation system columns
vent_cols = [c for c in fg.columns if any(x in c.lower() for x in ["vent", "luft", "ftx", "fvp", "själv", "frånluft"])]
print(f"\nVent-related columns in FG: {vent_cols}")

if vent_cols:
    for c in vent_cols:
        print(f"\n{c}:")
        print(fg_fh[c].value_counts().head(10))

# Check FE for vent system
print("\n" + "=" * 60)
fe = pd.read_csv("betsi/FE.csv", sep=";", decimal=",", encoding="latin-1")
fe_fh = fe[fe["Byggnad"].str.startswith("FH", na=False)]
print(f"FE.csv FH rows: {len(fe_fh)}")
vent_cols_fe = [c for c in fe.columns if any(x in c.lower() for x in ["vent", "luft", "ftx", "fvp", "själv", "frånluft", "tilluft"])]
print(f"\nVent-related columns in FE:")
for c in vent_cols_fe:
    vals = fe_fh[c].dropna()
    if len(vals) > 0:
        print(f"  {c}: n={len(vals)}")
        print(f"    {fe_fh[c].value_counts().head(5).to_dict()}")
