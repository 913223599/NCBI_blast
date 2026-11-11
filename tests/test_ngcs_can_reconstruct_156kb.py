# -*- coding: utf-8 -*-
r"""
验证：NGCS 生成的序列素材是否具备完整拼接出 156kb 闭环噬菌体基因组的全部物理信息？
"""
import os
import sys
import subprocess
import pytest

# ===== 前置依赖守卫 =====
# 该测试依赖外部 NGCS 项目模块 (E:\NGCS) 与 E:\NGCS_Work 素材数据。
# 当前环境未提供这些外部数据时，跳过本模块，避免 pytest 收集阶段崩溃。
if not os.path.isdir(r"E:\NGCS") or not os.path.isfile(r"E:\NGCS_Work\tasks\bench_test_postproc\assembly.fasta"):
    pytest.skip(
        "外部 NGCS 数据缺失 (E:\\NGCS / E:\\NGCS_Work\\tasks\\bench_test_postproc\\assembly.fasta)，跳过 156kb 重构验证",
        allow_module_level=True,
    )

if r"E:\NGCS" not in sys.path:
    sys.path.insert(0, r"E:\NGCS")

from ngcs.utils.edlib_compat import edlib
from ngcs.spectral.backbone import reverse_complement

# 1. 加载最初未被过度误删的 7 个 contig 产物 (来自 bench_test_postproc)
bench_fa = r"E:\NGCS_Work\tasks\bench_test_postproc\assembly.fasta"
flye_fa = r"E:\NGCS_Work\tasks\bench_test\flye_out\assembly.fasta"

contigs = {}
with open(bench_fa, "r", encoding="utf-8") as f:
    cid = ""
    for line in f:
        if line.startswith(">"):
            cid = line.strip()[1:].split()[0]
            contigs[cid] = []
        else:
            contigs[cid].append(line.strip())
contigs = {k: "".join(v) for k, v in contigs.items()}

print("=== NGCS 原始生成的素材盘点 ===")
for k, v in contigs.items():
    print(f"  {k}: length = {len(v):,} bp")

# 检查 Flye 156,274 bp 上的各区间与 NGCS 素材的对应情况
# Flye [0 - 17,295] (17.3 kb) -> contig_1 [138,104 - 155,401]
# Flye [17,295 - 32,018] (14.7 kb) -> ngcs_contig_6 [0 - 14,723]
# Flye [32,018 - 68,270] (36.3 kb) -> contig_2 [0 - 36,255] (反向互补)
# Flye [47,813 - 156,274] (108.5 kb) -> contig_1 [30,173 - 138,104]

# 测试：用 NGCS 自己的 sequence blocks 进行端到端重构
block1 = contigs["ngcs_contig_1"][30173:155401] # 125,228 bp (来自 NGCS contig_1)
block2 = contigs["ngcs_contig_6"][:14723]         # 14,723 bp  (来自 NGCS contig_6)
block3 = reverse_complement(contigs["ngcs_contig_2"][:36255]) # 36,255 bp (来自 NGCS contig_2)

print(f"\nNGCS 素材块:")
print(f"  Block 1 (from ngcs_contig_1): {len(block1):,} bp")
print(f"  Block 2 (from ngcs_contig_6): {len(block2):,} bp")
print(f"  Block 3 (from ngcs_contig_2): {len(block3):,} bp")

# 检查 Block 1 与 Block 2 的衔接 (Block 1 尾部 vs Block 2 头部)
aln_1_2 = edlib.align(block2[:200], block1[-2000:], mode="HW", task="locations", k=10)
print(f"\nBlock 1 -> Block 2 衔接检测: editDistance = {aln_1_2['editDistance']}, locations = {aln_1_2.get('locations')}")

# 检查 Block 2 与 Block 3 的衔接
aln_2_3 = edlib.align(block3[:200], block2[-2000:], mode="HW", task="locations", k=10)
print(f"Block 2 -> Block 3 衔接检测: editDistance = {aln_2_3['editDistance']}, locations = {aln_2_3.get('locations')}")

# 检查 Block 3 与 Block 1 的首尾成环闭合
aln_3_1 = edlib.align(block1[:200], block3[-2000:], mode="HW", task="locations", k=10)
print(f"Block 3 -> Block 1 环化衔接检测: editDistance = {aln_3_1['editDistance']}, locations = {aln_3_1.get('locations')}")

# 把这三个来自 NGCS 原生组装的块缝合起来
# 注意：Block 3 与 Block 1 之间存在我们前面发现的 20,458 bp 共享重叠
# 缝合完整的 156kb 序列
fused_ngcs = block1 + block2 + block3[20458:] # 排除重叠部分
print(f"\nNGCS 缝合后总长度: {len(fused_ngcs):,} bp")

# 写入文件并用 minimap2 全长比对 Flye 156,274 bp
out_fused = r"C:\Users\Administrator\.gemini\antigravity-ide\brain\439da690-8114-4b95-8668-c7b78b6009d9\scratch\ngcs_assembled_156kb.fasta"
with open(out_fused, "w", encoding="utf-8") as f:
    f.write(f">ngcs_complete_156kb length={len(fused_ngcs)} circular=True\n{fused_ngcs}\n")

paf_res = r"C:\Users\Administrator\.gemini\antigravity-ide\brain\439da690-8114-4b95-8668-c7b78b6009d9\scratch\ngcs_156kb_vs_flye.paf"
cmd = f'wsl minimap2 -c /mnt/e/NGCS_Work/tasks/bench_test/flye_out/assembly.fasta /mnt/c/Users/Administrator/.gemini/antigravity-ide/brain/439da690-8114-4b95-8668-c7b78b6009d9/scratch/ngcs_assembled_156kb.fasta > "{paf_res}"'
subprocess.run(cmd, shell=True, check=True)

with open(paf_res, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"\n=== NGCS 重构 156kb 与 Flye 156,274 bp 端到端全基因组共线性比对 ({len(lines)} hits) ===")
for l in lines:
    p = l.strip().split("\t")
    qname, qlen, qstart, qend, strand, tname, tlen, tstart, tend, nmatch, alen, mapq = p[:12]
    ident = int(nmatch) / int(alen) * 100
    print(f"NGCS 156kb [{int(qstart):,}-{int(qend):,}/{int(qlen):,}] -> Flye [{int(tstart):,}-{int(tend):,}/{int(tlen):,}] strand={strand} identity={ident:.2f}% mapq={mapq}")

