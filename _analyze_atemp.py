import pandas as pd
df = pd.read_csv('results_cmf1960.csv')
df['atemp_ratio'] = df['Atemp_sim'] / df['Atemp_epc']
df['atemp_diff_pct'] = (df['atemp_ratio'] - 1) * 100

cols = ['Fastighet','Husnr','Atemp_epc','Atemp_sim','atemp_ratio','atemp_diff_pct','Floors','Num_footprints','Apt_depth','EPC_ratio']

print("=== Atemp mismatch (sim/epc), sorted ===")
print(df[cols].sort_values('atemp_ratio').to_string(index=False, float_format='%.1f'))

print()
print("Summary:")
print(f"  Mean atemp ratio:  {df['atemp_ratio'].mean():.2f}")
print(f"  Median:            {df['atemp_ratio'].median():.2f}")
within_20 = ((df['atemp_ratio']>=0.8) & (df['atemp_ratio']<=1.2)).sum()
within_10 = ((df['atemp_ratio']>=0.9) & (df['atemp_ratio']<=1.1)).sum()
print(f"  Within +/-20%:     {within_20} / {len(df)}")
print(f"  Within +/-10%:     {within_10} / {len(df)}")
corr = df['atemp_ratio'].corr(df['EPC_ratio'])
print(f"  Corr(atemp_ratio, EPC_ratio): {corr:.2f}")

# How is sim Atemp computed?  footprint_area * floors
# So mismatch = wrong footprint area OR wrong floor count
df['fp_area'] = df['Atemp_sim'] / df['Floors']
df['epc_fp'] = df['Atemp_epc'] / df['Floors']
df['fp_ratio'] = df['fp_area'] / df['epc_fp']
print()
print("=== Implied footprint area (sim vs epc/floors) ===")
print(df[['Fastighet','Husnr','fp_area','epc_fp','fp_ratio','Floors']].sort_values('fp_ratio').to_string(index=False, float_format='%.0f'))
