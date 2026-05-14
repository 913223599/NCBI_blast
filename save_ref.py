"""从下载的 Markdown 中提取 FASTA 序列并保存"""
import re

src = r"C:\Users\Administrator\.gemini\antigravity\brain\1a9df026-bc60-4bc9-9b70-bbfb604b25d9\.system_generated\steps\449\content.md"
dst = r"f:\NCBI blast\test_data\ref_ralstonia_jumbo.fasta"

with open(src, "r", encoding="utf-8") as f:
    content = f.read()

# 找到 FASTA 头部行
idx = content.find(">PQ309151")
if idx == -1:
    print("ERROR: Could not find FASTA header")
    exit(1)

fasta_text = content[idx:]
# 清理可能的 Markdown 干扰
lines = []
for line in fasta_text.splitlines():
    line = line.strip()
    if not line:
        continue
    if line.startswith(">") or re.match(r'^[ACGTNRYSWKMBDHV]+$', line, re.IGNORECASE):
        lines.append(line)

with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

# 统计长度
total_bp = sum(len(l) for l in lines if not l.startswith(">"))
print(f"Saved reference: {len(lines)-1} sequence lines, {total_bp:,} bp total")
