import os
import glob
path = "/root/.conda/envs/vibrant/share/vibrant-1.2.1/db/databases"
files = glob.glob(os.path.join(path, "Pfam*"))
for f in files:
    print(f"{f}: {os.path.getsize(f)} bytes")
