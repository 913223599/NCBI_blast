import json

with open('results/pan_genomics/pan_20260908_122619_dd97e2/result.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

sample_names = data['sample_names']
ani_mat = data['ani_matrix']
af_mat = data.get('af_matrix', {})

cluster_sids = [
    'ANNO_8F7D6620', # 1.1_Anno
    'ANNO_143A2AF4', # 3
    'ANNO_70F218CB', # 1.2_Anno
    'ANNO_DDEF165E', # 1
    'ANNO_A172B78C', # K08
    'ANNO_5DEF0051', # 3133-3924
    'ANNO_9634DD82', # 3133-3923
    'ANNO_D5F97288', # 1.3_Anno
    'ANNO_6F990C54', # 1.4_Anno
]

print('=== ANI MATRIX ===')
cols = [sample_names[s] for s in cluster_sids]
print('%-12s' % 'Sample', ' '.join(['%10s' % c[:10] for c in cols]))
for s1 in cluster_sids:
    row = []
    for s2 in cluster_sids:
        val = ani_mat.get(s1, {}).get(s2)
        row.append('%10.2f' % val if val is not None else '%10s' % 'None')
    print('%-12s' % sample_names[s1][:12], ' '.join(row))

print('\n=== AF MATRIX (Alignment Fraction) ===')
print('%-12s' % 'Sample', ' '.join(['%10s' % c[:10] for c in cols]))
for s1 in cluster_sids:
    row = []
    for s2 in cluster_sids:
        val = af_mat.get(s1, {}).get(s2)
        row.append('%10.2f' % val if val is not None else '%10s' % 'None')
    print('%-12s' % sample_names[s1][:12], ' '.join(row))
