"""Find construction year for FH buildings in BETSI data."""
import pandas as pd
import glob
import os

betsi_dir = "betsi"

# List all CSV files
csvs = sorted(glob.glob(os.path.join(betsi_dir, "*.csv")))
print("All BETSI CSV files:")
for f in csvs:
    print(f"  {os.path.basename(f)}")

print("\n" + "=" * 60)
print("Scanning ALL files for year/age/period columns with FH data")
print("=" * 60)

for f in csvs:
    try:
        df = pd.read_csv(f, sep=";", decimal=",", encoding="latin-1", nrows=5)
        year_cols = []
        for c in df.columns:
            cl = c.lower()
            if any(x in cl for x in ["år", "year", "ald", "period", "uppf", "byggnads"]):
                year_cols.append(c)
        if year_cols:
            # Read full file for these columns
            df_full = pd.read_csv(f, sep=";", decimal=",", encoding="latin-1")
            if "Byggnad" in df_full.columns:
                fh = df_full[df_full["Byggnad"].str.startswith("FH", na=False)]
                if len(fh) > 0:
                    print(f"\n{os.path.basename(f)} (FH rows: {len(fh)}):")
                    for c in year_cols:
                        vals = fh[c].dropna()
                        if len(vals) > 0:
                            print(f"  {c}: n={len(vals)}")
                            vc = fh[c].value_counts().head(8)
                            for v, cnt in vc.items():
                                print(f"    {v}: {cnt}")
    except Exception as e:
        pass

# Also check Uppräkningstal files for FH
print("\n" + "=" * 60)
print("Uppräkningstal files")
print("=" * 60)
ut_files = glob.glob(os.path.join(betsi_dir, "Uppr*kningstal*.csv"))
for f in ut_files:
    df = pd.read_csv(f, sep=";", decimal=",", encoding="latin-1")
    btypes = df["Byggnad"].str[:2].value_counts() if "Byggnad" in df.columns else "no Byggnad col"
    print(f"\n{os.path.basename(f)}:")
    print(f"  Building types: {dict(btypes) if isinstance(btypes, pd.Series) else btypes}")
    print(f"  Columns: {df.columns.tolist()[:15]}")
