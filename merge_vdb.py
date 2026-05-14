import os
import glob
import sys

db_dir = "/root/.conda/envs/vibrant/share/vibrant-1.2.1/db/databases"
# 使用更通用的匹配符 VOG*.hmm 以捕获所有 24,982 个文件
vog_files = glob.glob(os.path.join(db_dir, "VOG*.hmm"))

if not vog_files:
    print("No VOG files found.")
    sys.exit(1)

out_file = os.path.join(db_dir, "VOGDB94_phage.HMM")
print(f"Detected {len(vog_files)} VOG files.")
print(f"Merging into {out_file}...")

# 排序以确保合并顺序稳定（虽然 HMM 顺序通常不影响功能，但更严谨）
vog_files.sort()

with open(out_file, "wb") as out_f:
    for f in vog_files:
        with open(f, "rb") as in_f:
            out_f.write(in_f.read())
            
print(f"Successfully merged {len(vog_files)} VOG files.")
