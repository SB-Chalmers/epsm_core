import pandas as pd
df = pd.read_csv('results_cmf1960.csv')
df['atemp_ratio'] = df['Atemp_sim'] / df['Atemp_epc']
df['fp_area'] = df['Atemp_sim'] / df['Floors']
df['epc_fp'] = df['Atemp_epc'] / df['Floors']

under = df[df['atemp_ratio'] < 0.8]
ok = df[(df['atemp_ratio'] >= 0.8) & (df['atemp_ratio'] <= 1.2)]
over = df[df['atemp_ratio'] > 1.2]

print('=== CATEGORY SUMMARY ===')
for label, grp in [('Under (<0.8)', under), ('OK (0.8-1.2)', ok), ('Over (>1.2)', over)]:
    n = len(grp)
    if n > 0:
        avg_r = grp['EPC_ratio'].mean()
        med_r = grp['EPC_ratio'].median()
        print(f'{label:16s} {n:2d} buildings | EPC_ratio mean={avg_r:.2f}, median={med_r:.2f}')
    else:
        print(f'{label:16s}  0 buildings')

print()
print('=== OK Atemp buildings (0.8-1.2): EPC_ratio quality ===')
n_good = ((ok['EPC_ratio']>=0.85) & (ok['EPC_ratio']<=1.15)).sum()
print(f'  Within 0.85-1.15: {n_good} / {len(ok)}')
print(f'  EPC_ratio: {ok["EPC_ratio"].describe().to_string()}')

print()
print('=== Correlation matrix (all 35) ===')
for col in ['atemp_ratio', 'Floors', 'Apt_depth', 'Num_footprints']:
    print(f'  corr(EPC_ratio, {col:18s}) = {df["EPC_ratio"].corr(df[col]):+.2f}')

# What if we exclude buildings with big atemp mismatch?
print()
print('=== If we filter to Atemp within +/-20% ===')
filt = df[(df['atemp_ratio'] >= 0.8) & (df['atemp_ratio'] <= 1.2)]
print(f'  Remaining: {len(filt)} / {len(df)}')
print(f'  EPC_ratio: mean={filt["EPC_ratio"].mean():.2f}, median={filt["EPC_ratio"].median():.2f}')
n_match = ((filt['EPC_ratio']>=0.85) & (filt['EPC_ratio']<=1.15)).sum()
print(f'  Within 0.85-1.15: {n_match} / {len(filt)}')
