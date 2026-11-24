# -*- coding: utf-8 -*-
"""
FastTreeEngine - 近似最大似然建树引擎 (支持 0~100 支持率标准化)
"""
import logging
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.fasttree")


def normalize_fasttree_support(newick: str) -> str:
    """将 FastTree 输出的 0~1 SH-like 节点支持率转换为 0~100 百分制，与 IQ-TREE/NJ 统一。"""
    def _repl(match: re.Match[str]) -> str:
        val = float(match.group(1))
        pct = round(val * 100) if val <= 1.0 else round(val)
        return f"){pct}{match.group(2)}"

    return re.sub(r"\)(0(?:\.\d+)?|1(?:\.0+)?)([:;])", _repl, newick)


class FastTreeEngine:
    """FastTree 包装器。"""

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def build(
        self,
        msa_fasta: Path,
        output_nwk: Path,
        mol_type: str = "dna",
        model: str = "gtr",
        threads: int = 0,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("FastTree 开始前任务已取消")

        desc = self.registry.get("fasttree")
        if not desc.available:
            raise ToolUnavailableError("fasttree", f"FastTree 不可用: {desc.notes}")

        safe_threads = get_safe_cpu_budget(threads)
        args: list[str] = ["-quiet"]
        m = model.lower().strip()
        if mol_type == "protein":
            if m.startswith("wag"):
                args.append("-wag")
            elif m.startswith("lg"):
                args.append("-lg")
        else:
            args.append("-nt")
            if m.startswith("gtr"):
                args.append("-gtr")

        raw_out = output_nwk.with_suffix(".fasttree.raw.nwk")
        if desc.runtime == "wsl":
            from src.assembly.env.wsl_manager import WSLManager

            cmd = [desc.path, *args, WSLManager.to_wsl_path(str(msa_fasta.resolve()))]
            res = self.runner.run_wsl(cmd, stdout_path=raw_out)
        else:
            cmd = [desc.path, *args, str(msa_fasta.resolve())]
            env_extra = {"OMP_NUM_THREADS": str(safe_threads)}
            res = self.runner.run_native(cmd, stdout_path=raw_out, env_extra=env_extra)

        if res.returncode != 0:
            raise PhyloError(f"FastTree 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])
        if not raw_out.is_file() or raw_out.stat().st_size == 0:
            raise PhyloError("FastTree 未生成有效的 Newick 输出。")

        nwk_text = raw_out.read_text(encoding="utf-8", errors="replace").strip()
        if not nwk_text.startswith("("):
            raise PhyloError("FastTree 输出格式无效", detail=nwk_text[:300])

        normalized = normalize_fasttree_support(nwk_text)
        output_nwk.parent.mkdir(parents=True, exist_ok=True)
        output_nwk.write_text(normalized + "\n", encoding="utf-8")
        return output_nwk
