import sys
from pathlib import Path
from Bio import SeqIO
sys.path.append('src/backend')
from utils.assembly_gbk_fixer import GBKAnnotationBackfiller

# 目标任务产物
gbk_path = Path("results/assembly/AS_1776518668936/phageannotationstep/pharokka_res/PHAGE.gbk")
if not gbk_path.exists():
    print("没有找到文件，脚本退出。")
    sys.exit(0)

# 我们人为模拟一次 BLAST 执行完的命中结果（挑选任意一个存在于文件中的 unknown ID）
records = list(SeqIO.parse(gbk_path, "genbank"))
target_id = None
for r in records:
    for f in r.features:
        if f.type == "CDS" and "unknown" in f.qualifiers.get("product", [""])[0].lower():
            target_id = f.qualifiers.get("locus_tag", [f.qualifiers.get("ID", [""])[0]])[0]
            break
    if target_id: break

if target_id:
    print(f"正在测试回填机制...")
    print(f"找到目标未知序列 ID: {target_id}")
    
    mock_hits = {
        target_id: {
            "product": "[自动测试] 跨库深度鉴定产物 (ex. Tail fiber protein)",
            "evalue": "1.3e-50"
        }
    }
    
    fixer = GBKAnnotationBackfiller(gbk_path)
    new_path = fixer.apply_blast_hits(mock_hits)
    print(f"成功写入新的强化版 GBK 文件: {new_path}")
    
    # 重新读取验证
    updated = list(SeqIO.parse(new_path, "genbank"))
    for r in updated:
        for f in r.features:
            if f.type == "CDS":
                cid = f.qualifiers.get("locus_tag", [f.qualifiers.get("ID", [""])[0]])[0]
                if cid == target_id:
                    print(f"验证命中: {cid}")
                    print(f"当前 Product: {f.qualifiers.get('product', [''])[0]}")
                    print(f"附加记录 (Note): {f.qualifiers.get('note', [''])[0]}")
