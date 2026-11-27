# -*- coding: utf-8 -*-
"""
Phold AI 蛋白质三维结构感知与折叠增强引擎 (PholdEngine)
结合 ESMFold 深度学习空间折叠与 Foldseek 结构域比对，专司破解未知与假定蛋白 (hypothetical protein)
"""
import asyncio
import gc
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from Bio import SeqIO

from .base import BaseAnnotationEngine
from ..fuser import AnnotationFuser
from ..types import AnnotationRunRequest, FeatureItem

logger = logging.getLogger("analysis.annotation.engines.phold")


class PholdEngine(BaseAnnotationEngine):
    """Phold 3D 结构深度增强引擎"""

    def __init__(self):
        super().__init__(name="Phold AI")
        self.unavailable_reason: Optional[str] = None

    @staticmethod
    def _parse_gpu_probe_output(stdout: str) -> Dict[str, Any]:
        """解析 WSL Phold GPU 运行态探测输出的 JSON 载荷。"""
        text = (stdout or "").strip()
        if not text:
            return {"ok": False, "error": "empty probe output"}
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    data.setdefault("ok", True)
                    return data
            except Exception as _exc:
                logger.debug("phold_engine JSON 行解析跳过: %s", _exc)
                continue
        return {"ok": False, "error": text[:200]}

    @staticmethod
    def _format_gpu_probe_notice(probe: Dict[str, Any]) -> Tuple[str, str]:
        """将 WSL Phold GPU 运行态探测结果格式化为 (日志级别, 提示信息)。"""
        if not probe.get("ok"):
            err = probe.get("error") or "unknown error"
            return ("info", f"Phold AI GPU 运行态预检未完成，将按默认环境继续执行 ({err})")

        has_gpu = bool(probe.get("has_wsl_gpu"))
        kernel_ok = bool(probe.get("kernel_ok"))
        torch_ver = str(probe.get("torch_version") or "unknown")
        device_name = str(probe.get("device_name") or "CUDA GPU")
        py_bin = str(probe.get("python_bin") or "python3")

        if kernel_ok:
            return (
                "info",
                f"Phold AI 已启用 GPU 加速: {device_name} (torch {torch_ver}, python={py_bin})",
            )

        if has_gpu:
            detail = str(probe.get("error") or "CUDA 不可用或计算内核不兼容")
            return (
                "warning",
                "检测到 WSL GPU 设备 (/dev/dxg)，但 Phold 当前解释器无法执行 CUDA kernel "
                f"({py_bin}, torch={torch_ver}, reason={detail})。"
                "可能安装了 CPU 版 PyTorch、CUDA 架构不匹配 (如 RTX 50 系列需 cu128) 或存在 ~/.local 阴影包，"
                "请运行 scripts/fix_phold_gpu_wsl.ps1 或 scripts/setup_phold.sh 修复。",
            )

        return ("info", "当前 WSL 未检测到 GPU 透传，Phold AI 将使用 CPU 模式运行")

    async def _probe_wsl_gpu_runtime(self) -> Dict[str, Any]:
        """探测 WSL root 上下文中 phold 实际解释器的 GPU 与 CUDA kernel 可用性。"""
        from ....assembly.env.wsl_manager import WSLManager

        if not WSLManager.is_available():
            return {"ok": False, "error": "WSL unavailable"}

        distro = WSLManager.get_best_distro()
        py_one_liner = (
            "import json,os; "
            "r={'has_wsl_gpu':os.path.exists('/dev/dxg'),'python_bin':'','torch_version':'','torch_file':'','cuda_version':'','cuda_available':False,'kernel_ok':False,'device_name':'','error':''}; "
            "import sys; r['python_bin']=sys.executable; "
            "\ntry:\n"
            " import torch\n"
            " r['torch_version']=getattr(torch,'__version__','')\n"
            " r['torch_file']=getattr(torch,'__file__','')\n"
            " r['cuda_version']=str(getattr(getattr(torch,'version',None),'cuda','') or '')\n"
            " r['cuda_available']=bool(torch.cuda.is_available())\n"
            " if r['cuda_available']:\n"
            "  r['device_name']=torch.cuda.get_device_name(0)\n"
            "  _=(torch.zeros(1).cuda()+1).item()\n"
            "  r['kernel_ok']=True\n"
            "  torch.cuda.empty_cache()\n"
            "except Exception as e:\n"
            " r['error']=str(e)\n"
            "print(json.dumps(r,ensure_ascii=False))"
        )
        # 用单行 base64/heredoc 无引号风险方式执行，避免不同 shell 引号嵌套失效
        import base64

        encoded_py = base64.b64encode(py_one_liner.encode("utf-8")).decode("ascii")
        bash_script = (
            "PHOLD_BIN=$(command -v phold 2>/dev/null || true); "
            "PY_BIN=''; "
            "if [ -n \"$PHOLD_BIN\" ] && [ -r \"$PHOLD_BIN\" ]; then "
            "  SHEBANG=$(head -n 1 \"$PHOLD_BIN\" | sed -n 's/^#![[:space:]]*//p'); "
            "  case \"$SHEBANG\" in */env\\ *) PY_BIN=$(echo \"$SHEBANG\" | awk '{print $2}') ;; *) PY_BIN=$(echo \"$SHEBANG\" | awk '{print $1}') ;; esac; "
            "fi; "
            "[ -x \"$PY_BIN\" ] || PY_BIN=$(command -v python3 || true); "
            "if [ -z \"$PY_BIN\" ]; then echo '{\"ok\":false,\"error\":\"python3 not found\"}'; exit 0; fi; "
            f"OUT=$(echo '{encoded_py}' | base64 -d | \"$PY_BIN\" - 2>/dev/null || true); "
            "if [ -z \"$OUT\" ]; then echo '{\"ok\":false,\"error\":\"probe failed\"}'; else echo \"$OUT\"; fi"
        )
        try:
            res = await asyncio.to_thread(
                subprocess.run,
                ["wsl", "-d", distro, "-u", "root", "bash", "-lc", bash_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=15,
            )
            probe = self._parse_gpu_probe_output(res.stdout)
            if not probe.get("ok") and res.stderr:
                probe["error"] = (res.stderr.strip() or probe.get("error") or "")[:200]
            return probe
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def is_available(self) -> bool:
        from ....assembly.engine.runner import CommandRunner
        from ....assembly.env.wsl_manager import WSLManager
        from ....workbench.models.tool_config import ToolConfig

        db_dir = ToolConfig.get_db_dir("phold_db")
        if not (db_dir.exists() and any(db_dir.iterdir())):
            self.unavailable_reason = f"Phold 数据库未就绪: {db_dir}"
            logger.warning(self.unavailable_reason)
            return False

        if not WSLManager.is_available():
            self.unavailable_reason = "未检测到可用的 WSL 发行版，无法调用 phold（数据库文件已存在）"
            logger.warning(self.unavailable_reason)
            return False

        runner = CommandRunner(step_name="PholdCheck", logger=logger, is_wsl=True)
        available = (await runner.run_command(["which", "phold"], silence_errors=True)) == 0
        if not available:
            self.unavailable_reason = "WSL 中未安装 phold，请先运行 scripts/setup_phold.sh"
            logger.warning(self.unavailable_reason)
        return available

    def _cleanup_gpu_memory(self):
        """显存红线保护与垃圾回收"""
        try:
            import importlib
            torch = importlib.import_module("torch")
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception as _exc:
            logger.debug("PholdEngine 回收 GPU 显存缓存失败（已忽略）: %s", _exc)
        gc.collect()

    async def run(
        self,
        input_fasta: Path,
        work_dir: Path,
        req: AnnotationRunRequest,
        threads: int,
        prefix: str,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Tuple[List[FeatureItem], Dict[str, str]]:
        """基础运行接口"""
        return [], {}

    async def complement_from_gbk(
        self,
        features: List[FeatureItem],
        input_gbk: Path,
        work_dir: Path,
        threads: int,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> int:
        """
        以中间 GenBank 为输入调度 Phold 进行 3D 结构折叠与 Foldseek 补漏
        返回成功识别补全的未知蛋白数量
        """
        if not input_gbk.exists() or input_gbk.stat().st_size == 0:
            return 0

        unannotated_count = sum(1 for f in features if f.feature_type == "CDS" and AnnotationFuser.is_unannotated(f.product))
        if unannotated_count == 0:
            logger.info("所有蛋白均已有确切功能，跳过 Phold 3D 补漏")
            return 0

        from ....assembly.engine.runner import CommandRunner
        from ....assembly.env.wsl_manager import WSLManager
        from ....workbench.models.tool_config import ToolConfig

        runner = CommandRunner(step_name="Phold", logger=logger, is_wsl=True)
        out_dir = work_dir / "phold_out"
        out_dir.mkdir(parents=True, exist_ok=True)

        if on_progress:
            on_progress(70, f"正在调度 Phold AI 蛋白质三维结构折叠与空间感知增强 (针对 {unannotated_count} 个假定蛋白)...", None)

        # 显存红线保护：切换至 WSL Phold GPU 引擎前先清理本进程 GPU 缓存
        self._cleanup_gpu_memory()

        # 预检 WSL 内 phold 实际解释器的 GPU / CUDA kernel 可用性
        probe = await self._probe_wsl_gpu_runtime()
        probe_level, probe_msg = self._format_gpu_probe_notice(probe)
        if probe_level == "warning":
            logger.warning(probe_msg)
        else:
            logger.info(probe_msg)
        if on_progress:
            on_progress(72, probe_msg, probe_msg)

        # 建立项目根目录的无空格软链接（不再硬编码特定盘符，兼容项目迁移）
        WSLManager.ensure_project_link()

        # 将路径转换为 WSL 路径，并直接使用磁盘上真实的 Phold 数据库目录
        wsl_gbk = WSLManager.to_wsl_path(str(input_gbk))
        wsl_out = WSLManager.to_wsl_path(str(out_dir))
        wsl_db = WSLManager.to_wsl_path(str(ToolConfig.get_db_dir("phold_db")))

        cmd = [
            "bash", "-c",
            f"export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 && phold run -i \"{wsl_gbk}\" -o \"{wsl_out}\" -d \"{wsl_db}\" -t {threads} -f"
        ]

        current_phold_pct = 5
        def on_phold_output(line: str):
            nonlocal current_phold_pct
            if not on_progress or not line:
                return
            clean_l = line.strip()
            lower_l = clean_l.lower()
            if "using device:" in lower_l:
                if "cuda" in lower_l:
                    logger.info("Phold 运行设备确认: %s", clean_l)
                else:
                    logger.warning("Phold 运行设备回退: %s", clean_l)
                on_progress(max(current_phold_pct, 60), f"Phold AI 计算设备: {clean_l}", clean_l)
            elif "no available gpu was found" in lower_l or "prostt5 will be run with cpu only" in lower_l:
                logger.warning("Phold AI 回退至纯 CPU 执行: %s", clean_l)
                on_progress(max(current_phold_pct, 60), f"Phold AI 未检测到可用 CUDA，正使用 CPU 执行: {clean_l}", clean_l)
            elif "cuda out of memory" in lower_l or "outofmemoryerror" in lower_l:
                logger.error("Phold AI GPU 显存溢出: %s", clean_l)
                on_progress(current_phold_pct, f"Phold AI GPU 显存不足: {clean_l}", clean_l)
            elif "createdb" in clean_l or "Foldseek createdb" in clean_l:
                current_phold_pct = max(current_phold_pct, 25)
                on_progress(current_phold_pct, "Phold AI [1/4]: 正在构建蛋白质空间特征数据库 (Foldseek)...", clean_l)
            elif "easy-search" in clean_l or "structure match" in clean_l or "searching" in lower_l:
                current_phold_pct = max(current_phold_pct, 50)
                on_progress(current_phold_pct, "Phold AI [2/4]: 正在执行 Foldseek 三维构象空间比对...", clean_l)
            elif "predict" in clean_l or "ESM" in clean_l or "prostt5" in clean_l or "embedding" in lower_l:
                current_phold_pct = max(current_phold_pct, 75)
                on_progress(current_phold_pct, "Phold AI [3/4]: 正在执行深度学习 3D 结构折叠空间感知...", clean_l)
            elif "topfunction" in clean_l or "merge" in clean_l or "filter" in lower_l:
                current_phold_pct = max(current_phold_pct, 95)
                on_progress(current_phold_pct, "Phold AI [4/4]: 正在筛选最优结构预测并生成增强模型...", clean_l)
            else:
                on_progress(current_phold_pct, f"Phold AI 正在运行: {clean_l[:55]}...", clean_l)

        ret = await runner.run_command(cmd, cwd=work_dir, on_output=on_phold_output)
        
        # 强制显存垃圾清理
        self._cleanup_gpu_memory()

        phold_gbk = out_dir / "phold.gbk"
        if ret != 0 or not phold_gbk.exists() or phold_gbk.stat().st_size == 0:
            logger.warning("Phold 执行未能产出 phold.gbk，保留已有注释")
            return 0

        # 解析 Phold 增强产物
        phold_candidates: List[FeatureItem] = []
        with open(phold_gbk, "r", encoding="utf-8", errors="ignore") as f:
            for rec in SeqIO.parse(f, "genbank"):
                for feat in rec.features:
                    if feat.type in ["source", "gene"]:
                        continue
                    q = feat.qualifiers
                    lt = q.get("locus_tag", [""])[0]
                    prod = q.get("product", ["hypothetical protein"])[0]
                    trans = q.get("translation", [""])[0]
                    gene_name = q.get("gene", [None])[0]
                    phold_func = q.get("function", q.get("phold_annotation", q.get("note", [None])))[0]

                    f_start = int(feat.location.start) + 1
                    f_end = int(feat.location.end)
                    f_strand = "+" if feat.location.strand >= 0 else "-"

                    item = FeatureItem(
                        id=lt,
                        locus_tag=lt,
                        contig_id=rec.id,
                        feature_type=feat.type,
                        start=f_start,
                        end=f_end,
                        strand=f_strand,
                        length_bp=f_end - f_start + 1,
                        gene_name=gene_name,
                        product=prod,
                        translation=trans if trans else None,
                        notes=f"Phold Structure: {phold_func}" if phold_func else None
                    )
                    phold_candidates.append(item)

        # 流式互补
        features, updated_count = AnnotationFuser.merge_by_coordinates(
            base_features=features,
            incoming_features=phold_candidates,
            engine_name="Phold AI",
            overlap_threshold=0.8
        )

        if on_progress:
            on_progress(100, f"Phold AI 结构感知成功额外识别出 {updated_count} 个结构功能蛋白 (剩余 {unannotated_count - updated_count} 个未知)...", None)

        return updated_count
