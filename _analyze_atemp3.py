"""Check what fraction of floor area is core (excluded from Atemp) vs perimeter."""
import pandas as pd
df = pd.read_csv('results_cmf1960.csv')

# Atemp_sim = perimeter_floor_area across all footprints
# We can compute gross = fp_area * floors to see the core exclusion
# But we need to look at the sim logs for that. Let's just compare
# Atemp_sim to the actual expected: footprint_area × total_floors

# Total_floors includes basement. The CSV has Floors (above-ground only)
# but Atemp_sim includes basement. So the implied footprint area:
# fp_area = Atemp_sim / (Floors + basement?)  -- but we don't know basement from CSV

# Let's instead just check a simple: does footprint_area * floors match EPC?
# fp_area_needed = Atemp_epc / floors
# If fp_area_from_geometry > fp_area_needed → over-predicting Atemp
# If fp_area_from_geometry < fp_area_needed → under-predicting Atemp

# Actually the sim includes basement floors.  Let's check how many have basement.
from src.pbgenerator.epc_io import load_footprints, load_epc_metadata
import duckdb

con = duckdb.connect('epc_sweden.duckdb', read_only=True)

for _, row in df.iterrows():
    fid = int(row['FormularId'])
    epc = load_epc_metadata(fid)
    all_fps = load_footprints(formular_id=fid, limit=50)
    flerfamilj = [f for f in all_fps if "Flerfamiljshus" in f.andamal]
    seen = set()
    unique = []
    for fp in (flerfamilj if flerfamilj else all_fps):
        if fp.objektidentitet not in seen:
            seen.add(fp.objektidentitet)
            unique.append(fp)

    total_fp = sum(fp.footprint_area for fp in unique)
    floors = epc['num_floors']
    bsmt = epc['num_basement_floors']
    total_floors = floors + bsmt
    gross_est = total_fp * total_floors
    epc_atemp = epc['atemp']
    ratio = gross_est / epc_atemp if epc_atemp else 0

    print(f"{row['Fastighet']:15s} h{row['Husnr']:2d}  "
          f"fp={total_fp:6.0f}  fl={floors}+{bsmt}={total_floors}  "
          f"gross_est={gross_est:7.0f}  epc={epc_atemp:5d}  "
          f"ratio={ratio:.2f}  sim_atemp={row['Atemp_sim']:7.1f}  "
          f"sim/epc={row['Atemp_sim']/epc_atemp:.2f}")

con.close()
