
import asyncio
import os
import sys
from pathlib import Path
import json

# 设置路径
root_dir = Path("f:/NCBI blast").resolve()
sys.path.append(str(root_dir))

async def run_optimized_plan_b():
    from src.assembly.steps.phage_annotation import PhageAnnotationStep
    
    task_id = "AS_1776601910417"
    fasta_path = root_dir / "results" / "assembly" / task_id / "consensuscorrectionstep" / "polished_assembly.fasta"
    anno_dir = root_dir / "results" / "assembly" / task_id / "phageannotationstep"
    output_tsv = anno_dir / "Host_Prediction_Plan_B.tsv"
    
    # 强制将 Windows 路径转换为 WSL 路径
    def to_wsl(win_path):
        p = str(win_path).replace("\\", "/")
        if ":" in p:
            parts = p.split(":")
            return f"/mnt/{parts[0].lower()}{parts[1]}"
        return p

    wsl_fasta = to_wsl(fasta_path)
    wsl_db = to_wsl(root_dir / "database" / "Prophage.3281395sequence.fasta.gz.msh")
    wsl_tmp_raw = "/tmp/raw_mash_dist.txt"
    wsl_tmp_top = "/tmp/top_mash_hits.txt"

    print(f"[START] 启动优化版比对引擎 (方案 B)...")
    
    # 步骤 1: 直接在 Shell 里完成比对、排序、取前 100
    # mash dist 输出: [Ref] [Query] [Dist] [P-val] [Hashes]
    # 我们按第 3 列 (双精度距离) 进行数值型正序排列 (-k3 -n)
    # 注意引号：由于路径包含空格，必须在 bash -c 内部进行双重引号处理
    bash_cmd = f"mash dist -p 16 '{wsl_db}' '{wsl_fasta}' > {wsl_tmp_raw} && sort -k3 -n {wsl_tmp_raw} | head -n 100 > {wsl_tmp_top}"
    
    proc = await asyncio.create_subprocess_shell(
        f"wsl -d Ubuntu -u root -- bash -c '{bash_cmd}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    print("  [Step 1/3] 正在执行 328 万指纹全量碰撞并排序...")
    await proc.communicate()
    
    # 步骤 2: 读取前 100 名结果
    print("  [Step 2/3] 正在提取最优命中记录...")
    proc = await asyncio.create_subprocess_shell(
        f"wsl -d Ubuntu -u root -- cat {wsl_tmp_top}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    lines = stdout.decode().strip().split("\n")
    
    # 步骤 3: 元数据富化与保存
    print("  [Step 3/3] 正在对命中条目执行 NCBI 嗅探与元数据合并...")
    
    class MockRunner:
        async def run_command(self, cmd, on_output=None, **kwargs):
            full_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd])
            p = await asyncio.create_subprocess_shell(f"wsl -d Ubuntu -u root -- {full_cmd}", stdout=asyncio.subprocess.PIPE)
            while True:
                line = await p.stdout.readline()
                if not line: break
                if on_output: on_output(line.decode().strip())
            await p.wait()
            return p.returncode

    from src.assembly.steps.phage_annotation import PhageAnnotationStep
    class MockContext:
        def __init__(self): self.is_wsl = True; self.data = {}
        def get(self, k, d=None): return self.data.get(k, d)
        def update(self, k, v): self.data[k] = v

    step = PhageAnnotationStep(MockContext())
    step.runner = MockRunner()
    
    final_hits = []
    with open(output_tsv, "w", encoding="utf-8") as f_out:
        f_out.write("Rank\tAccession\tSimilarity\tDistance\tHost_Description\n")
        
        for i, line in enumerate(lines):
            if not line.strip(): continue
            cols = line.split("\t")
            if len(cols) < 3: continue
            
            ref_id = cols[0]
            dist = float(cols[2])
            sim = f"{(1.0 - dist) * 100:.2f}%"
            acc = ref_id.split("|")[0].split(".")[0]
            
            # 执行 NCBI 嗅探 (针对前 10 名)
            desc = "Unknown"
            if i < 15:
                # 修复 datasets 指令
                try:
                    desc_raw = await step._silent_ncbi_fetch(acc)
                    desc = desc_raw if desc_raw else "Unknown"
                except: desc = "Lookup Failed"
            
            f_out.write(f"{i+1}\t{acc}\t{sim}\t{dist}\t{desc}\n")
            if i < 10:
                print(f"  #{i+1}: [{sim}] {desc} ({acc})")
                
    print(f"\n[OK] 优化版方案 B 跑通！报告已存至: {output_tsv}")

if __name__ == "__main__":
    asyncio.run(run_optimized_plan_b())
