"""Map which BETSI files contain FH data and what info they have."""
import pandas as pd
import glob, os

betsi_dir = "betsi"
csvs = sorted(glob.glob(os.path.join(betsi_dir, "*.csv")))

print("BETSI file coverage for FH (Flerbostadshus):")
print("=" * 70)

for f in csvs:
    try:
        df = pd.read_csv(f, sep=";", decimal=",", encoding="latin-1")
        if "Byggnad" not in df.columns:
            continue
        fh = df[df["Byggnad"].str.startswith("FH", na=False)]
        sh = df[df["Byggnad"].str.startswith("SH", na=False)]
        fn = os.path.basename(f)
        if len(fh) > 0:
            print(f"  {fn:45s} FH={len(fh):4d}  SH={len(sh):4d}  cols={len(df.columns)}")
        else:
            print(f"  {fn:45s} FH=   0  SH={len(sh):4d}  (SH only)")
    except Exception as e:
        print(f"  {os.path.basename(f):45s} ERROR: {e}")

# Now for files with FH data, check for ventilation system type
# FF.csv is SH only. Where is FH ventilation system?
# Maybe in FB_Klimat or FB_OVRIGT?
print("\n" + "=" * 70)
print("Looking for ventilation system data in FH-containing files...")
print("=" * 70)

for f in csvs:
    try:
        df = pd.read_csv(f, sep=";", decimal=",", encoding="latin-1")
        if "Byggnad" not in df.columns:
            continue
        fh = df[df["Byggnad"].str.startswith("FH", na=False)]
        if len(fh) == 0:
            continue
        vent_cols = [c for c in df.columns if any(x in c.lower() for x in 
            ["ventil", "ftx", "fvp", "självdrag", "frånluft", "tilluft", "fsystem"])]
        if vent_cols:
            fn = os.path.basename(f)
            print(f"\n{fn} (FH={len(fh)}):")
            for c in vent_cols:
                vals = fh[c].dropna()
                if len(vals) > 0:
                    print(f"  {c}: n={len(vals)}")
                    print(f"    {fh[c].value_counts().head(6).to_dict()}")
    except Exception:
        pass

# Check FB_Klimat for anything useful
print("\n" + "=" * 70)
print("FB_Klimat.csv for FH - all columns:")
print("=" * 70)
fbk = pd.read_csv("betsi/FB_Klimat.csv", sep=";", decimal=",", encoding="latin-1")
fbk_fh = fbk[fbk["Byggnad"].str.startswith("FH", na=False)]
print(f"FH rows: {len(fbk_fh)}")
for c in fbk.columns:
    vals = fbk_fh[c].dropna()
    if len(vals) > 0:
        print(f"  {c}: n={len(vals)}, sample={vals.head(3).tolist()}")
