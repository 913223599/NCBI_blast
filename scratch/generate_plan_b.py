
import asyncio
import os
import sys
from pathlib import Path
import json

# 设置项目根目录到 sys.path
root_dir = Path("f:/NCBI blast").resolve()
sys.path.append(str(root_dir))

class MockRunner:
    async def run_command(self, cmd, on_output=None, **kwargs):
        import subprocess
        full_cmd = " ".join([f'"{c}"' if " " in c else c for c in cmd])
        proc = await asyncio.create_subprocess_shell(
            f"wsl -d Ubuntu -u root -- {full_cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        while True:
            line = await proc.stdout.readline()
            if not line: break
            msg = line.decode(errors='ignore').strip()
            if on_output: on_output(msg)
        await proc.wait()
        return proc.returncode

class RealMockContext:
    def __init__(self):
        self.project_root = root_dir
        self.is_wsl = True
        self.data = {}
        self.base_dir = root_dir / "results" / "assembly" / "AS_1776601910417"
    def update(self, key, value): self.data[key] = value
    def get(self, key, default=None): return self.data.get(key, default)

async def run_plan_b():
    from src.assembly.steps.phage_annotation import PhageAnnotationStep
    
    fasta_path = Path("f:/NCBI blast/results/assembly/AS_1776601910417/consensuscorrectionstep/polished_assembly.fasta")
    output_tsv = Path("f:/NCBI blast/results/assembly/AS_1776601910417/phageannotationstep/Host_Prediction_Plan_B.tsv")
    
    mock_ctx = RealMockContext()
    step = PhageAnnotationStep(mock_ctx)
    step.runner = MockRunner()
    
    print(f"正在对 328 万库执行深度碰撞 (方案 B)...")
    results = await step._deep_host_prediction(fasta_path, threads=16)
    
    # 转换为 TSV 格式保存
    with open(output_tsv, "w", encoding="utf-8") as f:
        f.write("Rank\tAccession\tSimilarity\tDistance\tDatabase\tHost_Description\n")
        hits = results.get("top_hits", [])
        if not hits:
            print("警告: 未发现显著命中。")
        for i, hit in enumerate(hits):
            f.write(f"{i+1}\t{hit['accession']}\t{hit['similarity']}\t{hit['distance']}\t{hit['db_source']}\t{hit['description']}\n")
    
    print(f"成功导出方案 B 结果至: {output_tsv}")
    print("\n前 10 名核心证据:")
    for h in hits[:10]:
        print(f"[{h['similarity']}] {h['description']} ({h['accession']})")

if __name__ == "__main__":
    asyncio.run(run_plan_b())
