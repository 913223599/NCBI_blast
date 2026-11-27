# -*- coding: utf-8 -*-
"""
MultiSequenceAligner - 统一多序列比对适配器 (MAFFT / MUSCLE / ClustalO)
严格使用安全 CPU 线程预算，禁止任何失败后的静默造假填充。
"""
import logging
import shutil
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ...core.fasta_io import read_fasta_records
from ...models.errors import InvalidInputError, PhyloCancelledError, PhyloError, ToolUnavailableError
from ...models.schemas import MsaStrategyType, MsaToolType
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.msa")


class MultiSequenceAligner:
    """统一的多序列比对调度器。"""

    LONG_SEQ_GUARD_BP = 15_000
    ITERATIVE_MAX_SEQS = 200

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

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception as _exc:
                logger.debug("MultiSequenceAligner 日志回调执行失败: %s", _exc)

    def _to_wsl(self, path: Path) -> str:
        from src.assembly.env.wsl_manager import WSLManager

        return WSLManager.to_wsl_path(str(path.resolve()))

    def align(
        self,
        input_fasta: Path,
        output_fasta: Path,
        tool: MsaToolType = "mafft",
        strategy: MsaStrategyType = "auto",
        threads: int = 0,
        max_seq_len: int = 0,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("MSA 阶段开始前任务已取消")

        if tool == "none":
            records = read_fasta_records(input_fasta)
            lengths = {len(r.seq) if r.seq is not None else 0 for r in records}
            if len(lengths) != 1:
                raise InvalidInputError(
                    "您选择了 [无需比对]，但输入序列长度不一致，无法直接建树，请选择 MAFFT/MUSCLE 比对或切换全基因组 Mash 模式。"
                )
            output_fasta.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input_fasta, output_fasta)
            return output_fasta

        desc = self.registry.get(tool)
        if not desc.available:
            raise ToolUnavailableError(tool, f"MSA 工具 [{tool}] 未就绪: {desc.notes}")

        safe_threads = get_safe_cpu_budget(threads)
        output_fasta.parent.mkdir(parents=True, exist_ok=True)

        if tool == "mafft":
            return self._run_mafft(desc.runtime, desc.path, input_fasta, output_fasta, strategy, safe_threads, max_seq_len)
        if tool == "muscle":
            return self._run_muscle(desc.runtime, desc.path, input_fasta, output_fasta, safe_threads)
        if tool == "clustalo":
            return self._run_clustalo(desc.runtime, desc.path, input_fasta, output_fasta, safe_threads)

        raise InvalidInputError(f"不支持的 MSA 工具: {tool}")

    @classmethod
    def resolve_mafft_args(
        cls,
        strategy: MsaStrategyType,
        threads: int,
        seq_count: int = 0,
        max_seq_len: int = 0,
    ) -> Tuple[MsaStrategyType, List[str], Optional[str]]:
        """解析 MAFFT 策略保护与全阶段多线程参数（含 --threadtb/--threadit）。"""
        effective_strategy: MsaStrategyType = strategy
        note: Optional[str] = None
        if max_seq_len >= cls.LONG_SEQ_GUARD_BP and strategy != "fast":
            effective_strategy = "fast"
            note = f"[MAFFT] 检测到超长序列 ({max_seq_len} bp)，策略自动降级为 fast (--retree 1) 以避免阻塞。"
        elif seq_count > cls.ITERATIVE_MAX_SEQS and strategy in ("accurate", "linsi", "einsi"):
            effective_strategy = "auto"
            note = (
                f"[MAFFT] 序列数较多 ({seq_count} 条 > {cls.ITERATIVE_MAX_SEQS})，"
                f"为避免 {strategy} 迭代耗时激增，策略自动降级为 auto (--auto)。"
            )

        if effective_strategy == "fast":
            flags = ["--retree", "1", "--maxiterate", "0"]
        elif effective_strategy in ("accurate", "linsi"):
            flags = ["--localpair", "--maxiterate", "1000"]
        elif effective_strategy == "einsi":
            flags = ["--genafpair", "--maxiterate", "1000"]
        else:
            flags = ["--auto"]

        t_str = str(max(1, threads))
        flags.extend(["--thread", t_str, "--threadtb", t_str, "--threadit", t_str])
        return effective_strategy, flags, note

    def _run_mafft(
        self,
        runtime: str,
        tool_path: str,
        input_fasta: Path,
        output_fasta: Path,
        strategy: MsaStrategyType,
        threads: int,
        max_seq_len: int,
    ) -> Path:
        seq_count = 0
        with open(input_fasta, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith(">"):
                    seq_count += 1

        effective_strategy, flags, note = self.resolve_mafft_args(
            strategy=strategy,
            threads=threads,
            seq_count=seq_count,
            max_seq_len=max_seq_len,
        )
        if note:
            self._log(note)

        self._log(f"[MAFFT] 开始执行 ({runtime}), 策略={effective_strategy}, 序列={seq_count}, 线程={threads}")
        in_arg = self._to_wsl(input_fasta) if runtime == "wsl" else str(input_fasta.resolve())
        run_fn = self.runner.run_wsl if runtime == "wsl" else self.runner.run_native

        cmd = [tool_path, *flags, in_arg]
        res = run_fn(cmd, stdout_path=output_fasta)
        if res.returncode != 0 and any(tok in res.stderr.lower() for tok in ("threadtb", "threadit", "unknown option")):
            compat_flags = [
                arg for idx, arg in enumerate(flags)
                if arg not in ("--threadtb", "--threadit")
                and (idx == 0 or flags[idx - 1] not in ("--threadtb", "--threadit"))
            ]
            res = run_fn([tool_path, *compat_flags, in_arg], stdout_path=output_fasta)

        if res.returncode != 0:
            raise PhyloError(f"MAFFT 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])
        self._verify_msa_output(output_fasta, "MAFFT")
        return output_fasta

    def _run_muscle(
        self,
        runtime: str,
        tool_path: str,
        input_fasta: Path,
        output_fasta: Path,
        threads: int,
    ) -> Path:
        self._log(f"[MUSCLE] 开始执行 ({runtime}), 线程={threads}")
        is_v5 = "muscle 5" in (self.registry.get("muscle").version or "").lower() or runtime == "native"
        if runtime == "wsl":
            in_arg = self._to_wsl(input_fasta)
            out_arg = self._to_wsl(output_fasta)
            cmd = [tool_path, "-align", in_arg, "-output", out_arg, "-threads", str(threads)]
            res = self.runner.run_wsl(cmd)
            if res.returncode != 0 and ("invalid" in res.stderr.lower() or "unrecognized" in res.stderr.lower()):
                # 兼容 MUSCLE v3 参数 (-in / -out)
                cmd_v3 = [tool_path, "-in", in_arg, "-out", out_arg]
                res = self.runner.run_wsl(cmd_v3)
        else:
            cmd = [tool_path, "-align", str(input_fasta.resolve()), "-output", str(output_fasta.resolve())]
            if is_v5:
                cmd.extend(["-threads", str(threads)])
            res = self.runner.run_native(cmd)
            if res.returncode != 0 and ("invalid" in res.stderr.lower() or "unrecognized" in res.stderr.lower()):
                cmd_v3 = [tool_path, "-in", str(input_fasta.resolve()), "-out", str(output_fasta.resolve())]
                res = self.runner.run_native(cmd_v3)

        if res.returncode != 0:
            raise PhyloError(f"MUSCLE 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])
        self._verify_msa_output(output_fasta, "MUSCLE")
        return output_fasta

    def _run_clustalo(
        self,
        runtime: str,
        tool_path: str,
        input_fasta: Path,
        output_fasta: Path,
        threads: int,
    ) -> Path:
        self._log(f"[ClustalO] 开始执行 ({runtime}), 线程={threads}")
        if runtime == "wsl":
            cmd = [
                tool_path,
                "-i",
                self._to_wsl(input_fasta),
                "-o",
                self._to_wsl(output_fasta),
                f"--threads={threads}",
                "--force",
            ]
            res = self.runner.run_wsl(cmd)
        else:
            cmd = [
                tool_path,
                "-i",
                str(input_fasta.resolve()),
                "-o",
                str(output_fasta.resolve()),
                f"--threads={threads}",
                "--force",
            ]
            res = self.runner.run_native(cmd)

        if res.returncode != 0:
            raise PhyloError(f"ClustalO 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])
        self._verify_msa_output(output_fasta, "ClustalO")
        return output_fasta

    @staticmethod
    def _verify_msa_output(output_fasta: Path, engine_name: str) -> None:
        if not output_fasta.is_file() or output_fasta.stat().st_size == 0:
            raise PhyloError(f"{engine_name} 未生成有效的比对结果文件。")
        records = read_fasta_records(output_fasta)
        if len(records) < 3:
            raise PhyloError(f"{engine_name} 输出序列不足 3 条。")
        lengths = {len(r.seq) if r.seq is not None else 0 for r in records}
        if len(lengths) != 1:
            raise PhyloError(f"{engine_name} 输出序列长度未对齐，请检查输入数据。")
