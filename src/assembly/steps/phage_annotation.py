
import os
import shutil
from pathlib import Path
from ..core.base import BaseAssemblyStep

class PhageAnnotationStep(BaseAssemblyStep):
    """
    噬菌体专项注释步骤 (基于 Pharokka + Phold AI)
    集成 HMM 敏感比对与 AI 结构功能预测
    """
    async def execute(self) -> bool:
        self.status = "running"
        
        # 🔗 0. 初始化项目环境
        win_project_root = self.context.get("project_dir", os.getcwd())
        fasta = self.context.get("assembly_fasta")
        if not fasta:
             self.status = "failed"
             return False

        # 🔗 1. 环境自愈 (强制建立无空格路径映射)
        # 动态获取当前盘符，避免硬编码 /mnt/f
        win_path_obj = Path(win_project_root).resolve()
        drive_letter = win_path_obj.drive.replace(":", "").lower()
        
        # 建立基于当前盘符的临时工作根目录
        safe_root = f"/mnt/{drive_letter}/.ncbi_blast_wsl_tmp"
        
        # 获取标准 /mnt 源路径
        rel_project_path = str(win_path_obj.relative_to(win_path_obj.anchor)).replace("\\", "/")
        mnt_project_root = f"/mnt/{drive_letter}/{rel_project_path}"
        
        # 建立 symlink 以避开 Windows 路径中的空格问题
        await self.runner.run_command(["bash", "-c", f"ln -sfT '{mnt_project_root}' {safe_root}"])
        
        # 探测并建立数据库链接 (使用动态路径)
        pharokka_db_default = "/opt/pharokka_db"
        if (await self.runner.run_command(["test", "-d", pharokka_db_default])) != 0:
            if self.on_progress: self.on_progress(2, "初始化 Pharokka 数据库链接...")
            setup_script_wsl = f"{mnt_project_root}/scripts/setup_pharokka.sh"
            await self.runner.run_command(["bash", setup_script_wsl])

        # 🔗 2. 路径映射与性能计算
        # 使用动态计算的 safe_root 替换原始路径中的空格部分
        safe_fasta = str(fasta).replace(win_project_root, safe_root).replace("\\", "/")
        win_working_dir = str(self.get_working_dir())
        safe_working_dir = win_working_dir.replace(win_project_root, safe_root).replace("\\", "/")
        
        out_dir = Path(safe_working_dir) / "pharokka_res"
        phold_dir = Path(safe_working_dir) / "phold_res"

        try:
            core_out = []
            await self.runner.run_command(["nproc"], on_output=lambda x: core_out.append(x.strip()))
            # 🚀 调优：提升线程占用率到 90%
            threads = max(1, int(int(core_out[0]) * 0.9)) if core_out else 8
        except:
            threads = 8

        # 🔗 3. 执行 Pharokka (带超细粒度进度反馈)
        if self.on_progress: self.on_progress(10, "启动 Pharokka 深度注释流程...")
        
        def pharokka_handler(line: str):
            msg = line.strip()
            if "Phanotate" in msg: self.on_progress(15, "正在进行基因预测 (Phanotate)...")
            elif "Running MMseqs2" in msg and "PHROGs" in msg: self.on_progress(25, "检索核心蛋白库 (PHROGs)...")
            elif "CARD" in msg: self.on_progress(40, "检索耐药基因库 (CARD)...")
            elif "HMMER" in msg: self.on_progress(45, "HMM 深度比对 (敏感模式)...")
            elif "tRNAscan-SE" in msg: self.on_progress(50, "正在扫描 tRNA 基因...")
            elif "Dnaapler" in msg: self.on_progress(58, "正在校想起始位点 (Dnaapler)...")

        pharokka_cmd = [
            "pharokka.py", "-i", safe_fasta, "-o", out_dir.as_posix(),
            "-d", "/opt/pharokka_db", "-t", str(threads), "-p", "PHAGE",
            "--dnaapler", "--sensitivity", "8", "-f"
        ]
        await self.runner.run_command(pharokka_cmd, cwd=safe_working_dir, on_output=pharokka_handler)

        # 🔗 4. 执行 Phold AI 结构预测 (带 GPU 状态反馈)
        if self.on_progress: self.on_progress(60, "Pharokka 完成，进入 AI 结构增强模式...")
        
        def phold_handler(line: str):
            msg = line.strip()
            if "cuda" in msg.lower(): self.on_progress(62, "AI 显卡驱动已激活 (CUDA 加速)...")
            elif "Predicting 3Di" in msg: self.on_progress(75, "AI 神经网络正在推理构象...")
            elif "foldseek search" in msg: self.on_progress(85, "全球构象库比对搜索中...")

        gbk_file = out_dir / "PHAGE.gbk"
        phold_cmd = [
            "phold", "run", "-i", gbk_file.as_posix(), "-o", phold_dir.as_posix(),
            "-d", "/opt/phold_db", "-t", str(threads), "-f"
        ]
        ret_phold = await self.runner.run_command(phold_cmd, cwd=safe_working_dir, on_output=phold_handler)

        # 🔗 5. 产物确认与状态标记 (在 Windows 层面验证)
        win_out_dir = Path(win_working_dir) / "pharokka_res"
        win_phold_dir = Path(win_working_dir) / "phold_res"
        
        # 优先使用 Phold 的增强产物，如失败则退而求其次使用 Pharokka 的原始产物
        win_final_gbk = win_phold_dir / "phold.gbk" if ret_phold == 0 else win_out_dir / "PHAGE.gbk"
        
        if win_final_gbk.exists():
            # 将产物路径存入上下文，供后续可视化或报告步骤使用 (使用 Windows 路径)
            self.context.update("annotation_dir", win_final_gbk.parent)
            self.context.update("gbk_file", win_final_gbk)
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "深度注释任务圆满成功")
            return True

        self.status = "failed"
        return False

    def _parse_summary(self, path: Path) -> dict:
        """解析 Pharokka 摘要文件"""
        res = {"total_cds": 0, "functional_assigned": 0}
        try:
            with open(path, "r", encoding='utf-8') as f:
                for line in f:
                    if "Total CDS" in line:
                        res["total_cds"] = int(line.split(":")[-1].strip())
                    elif "Assigned function" in line:
                        res["functional_assigned"] = int(line.split(":")[-1].strip())
        except Exception:
            pass
        return res
