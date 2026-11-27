# -*- coding: utf-8 -*-
"""
IQTreeEngine - IQ-TREE 2/3 最大似然推断引擎
严格透传模型、安全 CPU 线程数与 UFBoot 参数。
"""
import logging
import re
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ...core.fasta_io import read_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.iqtree")

UFBOOT_MIN_REPLICATES = 1000
PROTEIN_FAST_MSET = "LG,WAG,JTT,Q.pfam,VT"
PROTEIN_FAST_CMAX = 4

MODEL_ALIAS_DNA = {
    "auto": "MFP",
    "mfp": "MFP",
    "jc": "JC",
    "jc69": "JC",
    "k2p": "K2P",
    "hky": "HKY+G",
    "gtr": "GTR+G",
    "gtr+g": "GTR+G",
    "p-distance": "JC",
}

MODEL_ALIAS_PROT = {
    "auto": "MFP",
    "mfp": "MFP",
    "mfp_full": "MFP_FULL",
    "jtt": "JTT+G",
    "jtt+g": "JTT+G",
    "lg": "LG+G",
    "lg+g": "LG+G",
    "wag": "WAG+G",
    "wag+g": "WAG+G",
    "poisson": "Poisson",
}


class IQTreeEngine:
    """IQ-TREE 2/3 最大似然构建引擎。"""

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.last_best_model: Optional[str] = None
        self.last_best_model_bic: Optional[float] = None
        self.last_log_likelihood: Optional[float] = None
        self.last_pi_sites: Optional[int] = None
        self.last_command: str = ""
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception as _exc:
                logger.debug("IQTreeEngine 日志回调执行失败: %s", _exc)

    @staticmethod
    def resolve_model(model: str, mol_type: str) -> str:
        key = (model or "auto").strip().lower()
        table = MODEL_ALIAS_PROT if mol_type == "protein" else MODEL_ALIAS_DNA
        return table.get(key, model.strip() or "MFP")

    @staticmethod
    def resolve_model_flags(model: str, mol_type: str) -> Tuple[str, List[str], Optional[str]]:
        """解析模型名称及 ModelFinder 收窄参数；蛋白 MFP 默认聚焦核心通用模型集以大幅提速。"""
        key = (model or "auto").strip().lower()
        if mol_type == "protein":
            if key in ("auto", "mfp"):
                return (
                    "MFP",
                    ["-mset", PROTEIN_FAST_MSET, "-cmax", str(PROTEIN_FAST_CMAX)],
                    f"核心蛋白快速集 {PROTEIN_FAST_MSET}, cmax={PROTEIN_FAST_CMAX}",
                )
            if key == "mfp_full":
                return ("MFP", [], "全量 ModelFinder 蛋白模型")
        return (IQTreeEngine.resolve_model(model, mol_type), [], None)

    def build(
        self,
        msa_fasta: Path,
        output_nwk: Path,
        work_dir: Path,
        mol_type: str = "dna",
        model: str = "MFP",
        bootstrap: int = 1000,
        threads: int = 0,
        bnni: bool = True,
        alrt: int = 1000,
        seed: int = 42,
        outgroup: Optional[str] = None,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("IQ-TREE 开始前任务已取消")

        desc = self.registry.get("iqtree")
        if not desc.available:
            raise ToolUnavailableError("iqtree", f"IQ-TREE 不可用: {desc.notes}")

        records = read_fasta_records(msa_fasta)
        n_seqs = len(records)
        safe_threads = get_safe_cpu_budget(threads)
        resolved_model, model_flags, model_note = self.resolve_model_flags(model, mol_type)

        actual_bootstrap = bootstrap
        actual_alrt = alrt
        if n_seqs < 4:
            if actual_bootstrap > 0 or actual_alrt > 0:
                self._log("[IQ-TREE] 序列数量不足 4 条，UFBoot 与 SH-aLRT 自动关闭。")
            actual_bootstrap = 0
            actual_alrt = 0
        elif 0 < actual_bootstrap < UFBOOT_MIN_REPLICATES:
            self._log(
                f"[IQ-TREE] UFBoot 算法要求至少 {UFBOOT_MIN_REPLICATES} 次采样，已由 {actual_bootstrap} 自动提升至 {UFBOOT_MIN_REPLICATES}。"
            )
            actual_bootstrap = UFBOOT_MIN_REPLICATES

        iq_dir = work_dir / "iqtree_run"
        iq_dir.mkdir(parents=True, exist_ok=True)
        prefix = iq_dir / "phylo"
        self.last_best_model = None
        self.last_best_model_bic = None
        self.last_log_likelihood = None
        self.last_pi_sites = None
        self.last_command = ""

        ver_text = (desc.version or "").lower()
        is_v1 = bool(re.search(r"version\s+1\.", ver_text))
        thread_flag = "-nt" if is_v1 else "-T"
        seqtype_flag = "AA" if mol_type == "protein" else "DNA"

        note_suffix = f" ({model_note})" if model_note else ""
        self._log(
            f"[IQ-TREE] 启动推断 ({desc.runtime}), 模型={resolved_model}{note_suffix}, UFBoot={actual_bootstrap}, SH-aLRT={actual_alrt}, 线程={safe_threads}"
        )

        extra_flags: List[str] = list(model_flags)
        if actual_bootstrap >= UFBOOT_MIN_REPLICATES:
            extra_flags.extend(["-B", str(actual_bootstrap)])
            if bnni:
                extra_flags.append("-bnni")
        if actual_alrt > 0:
            extra_flags.extend(["-alrt", str(actual_alrt)])
        if seed is not None and seed >= 0:
            extra_flags.extend(["--seed", str(seed)])
        if outgroup:
            extra_flags.extend(["-o", outgroup])

        if desc.runtime == "wsl":
            from src.assembly.env.wsl_manager import WSLManager

            cmd = [
                desc.path,
                "-s",
                WSLManager.to_wsl_path(str(msa_fasta.resolve())),
                "-st",
                seqtype_flag,
                "-m",
                resolved_model,
                "-pre",
                WSLManager.to_wsl_path(str(prefix.resolve())),
                thread_flag,
                str(safe_threads),
                "-redo",
                *extra_flags,
            ]
            self.last_command = " ".join(cmd)
            res = self.runner.run_wsl(cmd, stream_stdout_to_log=True)
        else:
            cmd = [
                desc.path,
                "-s",
                str(msa_fasta.resolve()),
                "-st",
                seqtype_flag,
                "-m",
                resolved_model,
                "-pre",
                str(prefix.resolve()),
                thread_flag,
                str(safe_threads),
                "-redo",
                *extra_flags,
            ]
            self.last_command = " ".join(cmd)
            res = self.runner.run_native(cmd, stream_stdout_to_log=True)

        if res.returncode != 0:
            raise PhyloError(f"IQ-TREE 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])

        iqtree_report = Path(f"{prefix}.iqtree")
        if iqtree_report.is_file():
            rep_text = iqtree_report.read_text(encoding="utf-8", errors="replace")
            m_best = re.search(
                r"(?:Best-fit model(?:\s+according to [A-Z]+)?|Model of substitution):\s*([^\s]+)",
                rep_text,
            )
            if m_best:
                self.last_best_model = m_best.group(1).strip()
            m_bic = re.search(
                r"Bayesian information criterion \(BIC\) score:\s*([0-9.+\-eE]+)",
                rep_text,
            )
            if m_bic:
                try:
                    self.last_best_model_bic = round(float(m_bic.group(1)), 2)
                except ValueError:
                    pass
            if self.last_best_model:
                bic_note = f" (BIC={self.last_best_model_bic})" if self.last_best_model_bic is not None else ""
                self._log(f"[IQ-TREE] 最佳替换模型: {self.last_best_model}{bic_note}")
            m_ll = re.search(
                r"Log-likelihood of the tree:\s*([0-9.+\-eE]+)",
                rep_text,
            )
            if m_ll:
                try:
                    self.last_log_likelihood = round(float(m_ll.group(1)), 2)
                except ValueError:
                    pass
            m_pi = re.search(r"Number of parsimony-informative sites:\s*(\d+)", rep_text)
            if m_pi:
                self.last_pi_sites = int(m_pi.group(1))

        treefile = Path(f"{prefix}.treefile")
        if not treefile.is_file() or treefile.stat().st_size == 0:
            raise PhyloError(f"IQ-TREE 未生成结果文件: {treefile}")

        nwk_text = treefile.read_text(encoding="utf-8", errors="replace").strip()
        output_nwk.parent.mkdir(parents=True, exist_ok=True)
        output_nwk.write_text(nwk_text + "\n", encoding="utf-8")
        return output_nwk
