"""Check FE.csv for FH ventilation system type and construction year."""
import pandas as pd

fe = pd.read_csv("betsi/FE.csv", sep=";", decimal=",", encoding="latin-1")
fe_fh = fe[fe["Byggnad"].str.startswith("FH", na=False)]
print(f"FE.csv total rows: {len(fe)}, FH rows: {len(fe_fh)}")

# Print ALL vent-related columns
print("\nVentilation-related columns in FE.csv:")
for c in fe.columns:
    cl = c.lower()
    if any(x in cl for x in ["vent", "luft", "ftx", "fvp", "själv", "frånluft", "tilluft", "ff3", "fe2"]):
        vals = fe_fh[c].dropna()
        if len(vals) > 0:
            print(f"  {c}: n={len(vals)}")
            vc = fe_fh[c].value_counts().head(6)
            for v, cnt in vc.items():
                print(f"    {v}: {cnt}")

# Look for construction year in FE
print("\n" + "=" * 60)
print("FE columns with year/construction/age info:")
for c in fe.columns:
    cl = c.lower()
    if any(x in cl for x in ["år", "year", "ald", "period", "uppf"]):
        vals = fe_fh[c].dropna()
        if len(vals) > 5:
            print(f"  {c}: n={len(vals)}")
            # Check if looks like years (1900-2100)
            num = pd.to_numeric(vals, errors="coerce").dropna()
            if len(num) > 0:
                yrs = num[(num > 1900) & (num < 2100)]
                if len(yrs) > 0:
                    print(f"    year-like values: min={yrs.min():.0f}, max={yrs.max():.0f}, n={len(yrs)}")

# Check FE columns for building type / construction
print("\n" + "=" * 60)
print("All FE2x columns (building/construction):")
for c in fe.columns:
    if c.startswith("FE2"):
        vals = fe_fh[c].dropna()
        if len(vals) > 0:
            print(f"  {c}: n={len(vals)}")
            print(f"    {fe_fh[c].value_counts().head(5).to_dict()}")

# Check FF.csv for any FH rows we might have missed
ff = pd.read_csv("betsi/FF.csv", sep=";", decimal=",", encoding="latin-1")
ff_fh = ff[ff["Byggnad"].str.startswith("FH", na=False)]
print(f"\nFF.csv FH rows: {len(ff_fh)} (out of {len(ff)})")

# Conclusion: FH building IDs
print(f"\n{'=' * 60}")
print("FH building ID range:")
ids = fe_fh["Byggnad"].str.extract(r"FH(\d+)")[0].astype(int)
print(f"  min={ids.min()}, max={ids.max()}, n={len(ids)}")
