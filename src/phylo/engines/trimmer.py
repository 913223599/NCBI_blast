# -*- coding: utf-8 -*-
"""
AlignmentTrimmer - 多序列比对位点修剪器
支持：
1. 官方 WSL ClipKIT (`-m kpic` / `kpic-smart-gap` / `smart-gap`)；
2. 基于 NumPy 的向量化 KPIC 等效实现与缺口比例阈值过滤 (`gap`)；
3. 输出简约信息位点 (PI sites) 与修剪前后 gap 统计指标供第 8 步质检。
"""
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..core.fasta_io import read_fasta_records
from ..models.schemas import TrimModeType
from ..runtime.process_runner import ProcessRunner
from ..runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.trimmer")

_CLIPKIT_MODE_MAP: Dict[str, str] = {
    "kpic": "kpic",
    "kpic_smart_gap": "kpic-smart-gap",
    "smart_gap": "smart-gap",
}


def _compute_alignment_stats(fasta_path: Path) -> Tuple[int, int, int, float]:
    """返回 (n_seqs, n_cols, parsimony_informative_sites, mean_gap_ratio)。"""
    records = read_fasta_records(fasta_path)
    if not records:
        return 0, 0, 0, 0.0
    n_seqs = len(records)
    first_seq = records[0].seq
    n_cols = len(first_seq) if first_seq is not None else 0
    if n_cols == 0:
        return n_seqs, 0, 0, 0.0

    mat = np.frombuffer(
        b"".join(str(r.seq).upper().encode("ascii", errors="replace") for r in records),
        dtype=np.uint8,
    ).reshape(n_seqs, n_cols)
    gap_mask = (mat == ord("-")) | (mat == ord(".")) | (mat == ord("?")) | (mat == ord("X")) | (mat == ord("N"))
    mean_gap = float(((mat == ord("-")) | (mat == ord(".")) | (mat == ord("?"))).mean())

    pi_sites = 0
    for col_idx in range(n_cols):
        col = mat[~gap_mask[:, col_idx], col_idx]
        if col.size < 4:
            continue
        _, counts = np.unique(col, return_counts=True)
        if int((counts >= 2).sum()) >= 2:
            pi_sites += 1

    return n_seqs, n_cols, pi_sites, round(mean_gap, 4)


class AlignmentTrimmer:
    """支持 ClipKIT KPIC 与 gap 比例修剪的多序列比对修剪器。"""

    @staticmethod
    def trim(
        input_msa: Path,
        output_msa: Path,
        max_gap_ratio: float = 0.5,
        min_keep_cols: int = 20,
    ) -> Tuple[Path, Dict[str, int]]:
        """经典按最大缺口比例过滤低信息量对齐列（向后兼容接口）。"""
        records = read_fasta_records(input_msa)
        if not records:
            raise ValueError(f"MSA 文件为空: {input_msa}")

        lengths = {len(r.seq) if r.seq is not None else 0 for r in records}
        if len(lengths) != 1:
            raise ValueError(f"输入文件未对齐（序列长度不一致）: {input_msa}")

        n_seqs = len(records)
        first_seq = records[0].seq
        n_cols = len(first_seq) if first_seq is not None else 0

        mat = np.frombuffer(
            b"".join(str(r.seq).upper().encode("ascii", errors="replace") for r in records),
            dtype=np.uint8,
        ).reshape(n_seqs, n_cols)

        gap_mask = (mat == ord("-")) | (mat == ord(".")) | (mat == ord("?"))
        gap_ratio = gap_mask.mean(axis=0)
        keep_mask = gap_ratio <= float(max_gap_ratio)
        kept_cols = int(keep_mask.sum())

        if kept_cols < min_keep_cols:
            logger.warning(
                f"修剪阈值 {max_gap_ratio} 后仅剩 {kept_cols} 列 (< {min_keep_cols})，"
                f"已安全保留全部 {n_cols} 列。"
            )
            trimmed_mat = mat
            kept_cols = n_cols
        else:
            trimmed_mat = mat[:, keep_mask]

        output_msa.parent.mkdir(parents=True, exist_ok=True)
        with open(output_msa, "w", encoding="utf-8", newline="\n") as fh:
            for idx, rec in enumerate(records):
                seq_str = trimmed_mat[idx].tobytes().decode("ascii", errors="replace")
                fh.write(f">{rec.id}\n")
                for pos in range(0, len(seq_str), 80):
                    fh.write(seq_str[pos : pos + 80] + "\n")

        stats = {
            "original_cols": n_cols,
            "kept_cols": kept_cols,
            "removed_cols": n_cols - kept_cols,
        }
        return output_msa, stats

    @classmethod
    def trim_with_mode(
        cls,
        input_msa: Path,
        output_msa: Path,
        mode: TrimModeType = "kpic",
        max_gap_ratio: float = 0.5,
        min_keep_cols: int = 20,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Path, Dict[str, object]]:
        """
        根据科研修剪模式执行修剪：
        - kpic / kpic_smart_gap / smart_gap: 优先调用官方 WSL ClipKIT CLI；若不可用则回退 NumPy KPIC。
        - gap: 使用最大缺口比例过滤。
        """
        _, orig_cols, orig_pi, gap_before = _compute_alignment_stats(input_msa)
        output_msa.parent.mkdir(parents=True, exist_ok=True)

        if mode in _CLIPKIT_MODE_MAP:
            clipkit_mode = _CLIPKIT_MODE_MAP[mode]
            reg = get_tool_registry()
            desc = reg.get("clipkit")
            if desc.available:
                from src.assembly.env.wsl_manager import WSLManager

                runner = ProcessRunner(
                    cancel_event=cancel_event,
                    on_log=on_log,
                    wsl_distro=reg.wsl_distro or "Ubuntu",
                )
                cmd = [
                    desc.path,
                    WSLManager.to_wsl_path(str(input_msa.resolve())),
                    "-m",
                    clipkit_mode,
                    "-o",
                    WSLManager.to_wsl_path(str(output_msa.resolve())),
                ]
                res = runner.run_wsl(cmd)
                if res.returncode == 0 and output_msa.is_file() and output_msa.stat().st_size > 0:
                    _, kept_cols, kept_pi, gap_after = _compute_alignment_stats(output_msa)
                    if kept_cols >= min_keep_cols:
                        return output_msa, {
                            "mode": mode,
                            "tool": f"ClipKIT {desc.version} (-m {clipkit_mode})".strip(),
                            "original_cols": orig_cols,
                            "kept_cols": kept_cols,
                            "removed_cols": orig_cols - kept_cols,
                            "parsimony_informative_sites": kept_pi,
                            "mean_gap_before": gap_before,
                            "mean_gap_after": gap_after,
                        }
                    logger.warning(
                        f"ClipKIT (-m {clipkit_mode}) 修剪后仅剩 {kept_cols} 列 (< {min_keep_cols})，安全退回 KPIC 宽松保留。"
                    )

            # NumPy 等效 KPIC 实现（保留恒定位点与简约信息位点，过滤全 gap / 过度稀疏单态噪点列）
            kept_path, kept_cols = cls._numpy_kpic_trim(
                input_msa, output_msa, smart_gap=("smart_gap" in mode), min_keep_cols=min_keep_cols
            )
            _, _, kept_pi, gap_after = _compute_alignment_stats(kept_path)
            return kept_path, {
                "mode": mode,
                "tool": f"KPIC-NumPy-Equiv ({clipkit_mode})",
                "original_cols": orig_cols,
                "kept_cols": kept_cols,
                "removed_cols": orig_cols - kept_cols,
                "parsimony_informative_sites": kept_pi,
                "mean_gap_before": gap_before,
                "mean_gap_after": gap_after,
            }

        # 默认 gap 比例过滤
        out_path, basic_stats = cls.trim(
            input_msa=input_msa,
            output_msa=output_msa,
            max_gap_ratio=max_gap_ratio,
            min_keep_cols=min_keep_cols,
        )
        _, _, kept_pi, gap_after = _compute_alignment_stats(out_path)
        return out_path, {
            **basic_stats,
            "mode": "gap",
            "tool": f"GapThreshold (<= {max_gap_ratio})",
            "parsimony_informative_sites": kept_pi,
            "mean_gap_before": gap_before,
            "mean_gap_after": gap_after,
        }

    @staticmethod
    def _numpy_kpic_trim(
        input_msa: Path,
        output_msa: Path,
        smart_gap: bool = False,
        min_keep_cols: int = 20,
    ) -> Tuple[Path, int]:
        records = read_fasta_records(input_msa)
        n_seqs = len(records)
        first_seq = records[0].seq
        n_cols = len(first_seq) if first_seq is not None else 0
        mat = np.frombuffer(
            b"".join(str(r.seq).upper().encode("ascii", errors="replace") for r in records),
            dtype=np.uint8,
        ).reshape(n_seqs, n_cols)

        gap_chars = (mat == ord("-")) | (mat == ord(".")) | (mat == ord("?"))
        ambig = gap_chars | (mat == ord("X")) | (mat == ord("N"))
        gap_ratios = gap_chars.mean(axis=0)
        gap_limit = 0.9 if not smart_gap else float(max(0.5, np.percentile(gap_ratios, 90)))

        keep_indices: List[int] = []
        for col_idx in range(n_cols):
            if gap_ratios[col_idx] > gap_limit:
                continue
            valid = mat[~ambig[:, col_idx], col_idx]
            if valid.size == 0:
                continue
            _, counts = np.unique(valid, return_counts=True)
            is_constant = counts.size == 1 and valid.size >= max(2, int(n_seqs * 0.5))
            is_pi = int((counts >= 2).sum()) >= 2
            if is_constant or is_pi:
                keep_indices.append(col_idx)

        if len(keep_indices) < min_keep_cols:
            trimmed_mat = mat
            kept_cols = n_cols
        else:
            trimmed_mat = mat[:, keep_indices]
            kept_cols = len(keep_indices)

        with open(output_msa, "w", encoding="utf-8", newline="\n") as fh:
            for idx, rec in enumerate(records):
                seq_str = trimmed_mat[idx].tobytes().decode("ascii", errors="replace")
                fh.write(f">{rec.id}\n")
                for pos in range(0, len(seq_str), 80):
                    fh.write(seq_str[pos : pos + 80] + "\n")

        return output_msa, kept_cols
