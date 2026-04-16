import pandas as pd
df = pd.read_csv('results_cmf1960.csv')
print(f'Buildings: {len(df)}')
print()
print('EPC_ratio stats:')
print(df['EPC_ratio'].describe().to_string())
print()
df['atemp_ratio'] = df['Atemp_sim'] / df['Atemp_epc']
print('Atemp ratio (sim/epc):')
print(df['atemp_ratio'].describe().to_string())
print()
print('Ventilation:')
print(df['Ventilation'].value_counts().to_string())
print(f'Apt_depth=0: {(df["Apt_depth"]==0).sum()}')
print()
cols = ['Fastighet','Husnr','EP_epc','EP_sim','EPC_ratio','Atemp_epc','Atemp_sim','Apt_depth','Ventilation']
print('=== Under-predictions (ratio < 0.65) ===')
print(df[df['EPC_ratio']<0.65].sort_values('EPC_ratio')[cols].to_string(index=False))
print()
print('=== Over-predictions (ratio > 1.0) ===')
print(df[df['EPC_ratio']>1.0].sort_values('EPC_ratio',ascending=False)[cols].to_string(index=False))
print()
good = df[(df['EPC_ratio']>=0.85) & (df['EPC_ratio']<=1.15)]
pct = len(good)/len(df)*100
print(f'=== Good matches (0.85-1.15): {len(good)} / {len(df)} ({pct:.0f}%) ===')
print(good[cols].to_string(index=False))
