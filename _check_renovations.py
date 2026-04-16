"""Check renovation status for all batch buildings, compare good vs bad matches."""
import duckdb
import pandas as pd

df = pd.read_csv("results_cmf1960.csv")
con = duckdb.connect("epc_sweden.duckdb", read_only=True)

# Key renovation columns (building envelope + ventilation)
renov_cols = [
    "AtgUtfordaIsolTak",      # roof insulation
    "AtgUtfordaIsolVagg",     # wall insulation
    "AtgUtfordaIsolMark",     # ground insulation
    "AtgUtfordaByteFonster",  # window replacement
    "AtgUtfordaKompFonster",  # supplementary glazing
    "AtgUtfordaTatFonster",   # window sealing
    "AtgUtfordaByteVent",     # ventilation replacement
    "AtgUtfordaAterVent",     # ventilation heat recovery
    "AtgUtfordaNyVentil",     # new ventilation
    "AtgUtfordaAnnanBygg",    # other building measures
    "AtgUtfordaUtfortAr",     # year of renovation
]

select = ", ".join(renov_cols)
fids = df["FormularId"].tolist()
placeholders = ",".join(str(f) for f in fids)

rows = con.execute(f"""
    SELECT FormularId, {select}
    FROM epc WHERE FormularId IN ({placeholders})
""").fetchdf().drop_duplicates(subset="FormularId")
con.close()

merged = df.merge(rows, on="FormularId", how="left")
merged["atemp_ratio"] = merged["Atemp_sim"] / merged["Atemp_epc"]

# Classify
merged["group"] = "poor"
merged.loc[(merged["EPC_ratio"] >= 0.85) & (merged["EPC_ratio"] <= 1.15), "group"] = "good"
merged.loc[merged["EPC_ratio"] > 1.15, "group"] = "over"

display_cols = ["Fastighet", "Husnr", "EP_epc", "EP_sim", "EPC_ratio", "Ventilation",
                "atemp_ratio"] + renov_cols

print("=== GOOD MATCHES (0.85-1.15) ===")
good = merged[merged["group"] == "good"].sort_values("EPC_ratio")
print(good[display_cols].to_string(index=False))

print()
print("=== POOR MATCHES (<0.85) ===")
poor = merged[merged["group"] == "poor"].sort_values("EPC_ratio")
print(poor[display_cols].to_string(index=False))

print()
print("=== OVER-PREDICTIONS (>1.15) ===")
over = merged[merged["group"] == "over"].sort_values("EPC_ratio", ascending=False)
print(over[display_cols].to_string(index=False))

# Summary: renovation rates by group
print()
print("=== Renovation rates by group ===")
bool_cols = [c for c in renov_cols if c != "AtgUtfordaUtfortAr"]
for grp_name, grp in merged.groupby("group"):
    n = len(grp)
    print(f"\n{grp_name} ({n} buildings):")
    for col in bool_cols:
        yes_count = (grp[col].fillna("").str.strip().str.lower() == "ja").sum()
        if yes_count > 0:
            print(f"  {col:30s}: {yes_count}/{n} ({yes_count/n*100:.0f}%)")
