import json
import glob, os

# Let's inspect the fasta files or the sample lengths
with open('results/pan_genomics/pan_20260908_122619_dd97e2/result.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Where are the assemblies or fastas?
# Let's check project files
for root, dirs, files in os.walk('.'):
    for fn in files:
        if fn.endswith('.fasta') or fn.endswith('.fna') or fn.endswith('.gbk'):
            if '1.3' in fn or '1.4' in fn:
                p = os.path.join(root, fn)
                print(p, os.path.getsize(p))
