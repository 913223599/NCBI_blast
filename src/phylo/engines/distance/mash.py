# -*- coding: utf-8 -*-
"""
MashDistanceEngine - Track A 全基因组 MinHash 演化距离引擎
适用于长基因组 / 噬菌体 / 宏基因组片段的秒级无对齐距离矩阵计算。
"""
import csv
import json
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ...core.fasta_io import iter_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.mash")


class MashDistanceEngine:
    """调用 WSL/本地 Mash 计算全基因组距离矩阵，并分片落盘。"""

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
                logger.debug("MashDistanceEngine._log 忽略非致命异常: %s", _exc)

    def _to_wsl(self, path: Path) -> str:
        from src.assembly.env.wsl_manager import WSLManager

        return WSLManager.to_wsl_path(str(path.resolve()))

    def compute_distance_matrix(
        self,
        sanitized_fasta: Path,
        work_dir: Path,
        kmer: int = 21,
        sketch_size: int = 1000,
        threads: int = 0,
    ) -> Tuple[List[str], np.ndarray]:
        """
        将合并 FASTA 按单条序列分片，使用 mash sketch + mash dist 生成对称距离矩阵。
        返回 (short_id_list, float64_matrix)。
        """
        if self.cancel_event.is_set():
            raise PhyloCancelledError("Mash 阶段开始前任务已取消")

        desc = self.registry.get("mash")
        if not desc.available:
            raise ToolUnavailableError("mash", f"未找到可用的 Mash 工具: {desc.notes}")

        safe_threads = get_safe_cpu_budget(threads)
        ids: List[str] = [(rec.id or "").strip() for rec in iter_fasta_records(sanitized_fasta)]
        n_seqs = len(ids)
        if n_seqs < 3:
            raise PhyloError("Mash 至少需要 3 条有效序列。")

        sketch_prefix = work_dir / "mash_all"
        sketch_msh = work_dir / "mash_all.msh"
        dist_tsv = work_dir / "mash_dist.tsv"

        if desc.runtime == "wsl":
            self._log(f"[Mash] Sketch 建库 (k={kmer}, s={sketch_size}, threads={safe_threads})...")
            res_sketch = self.runner.run_wsl(
                [
                    desc.path,
                    "sketch",
                    "-i",
                    "-k",
                    str(kmer),
                    "-s",
                    str(sketch_size),
                    "-p",
                    str(safe_threads),
                    self._to_wsl(sanitized_fasta),
                    "-o",
                    self._to_wsl(sketch_prefix),
                ]
            )
            if res_sketch.returncode != 0:
                raise PhyloError("Mash sketch 执行失败", detail=res_sketch.stderr[-1000:])

            self._log(f"[Mash] 并行计算成对全基因组距离 (threads={safe_threads})...")
            res_dist = self.runner.run_wsl(
                [
                    desc.path,
                    "dist",
                    "-p",
                    str(safe_threads),
                    self._to_wsl(sketch_msh),
                    self._to_wsl(sketch_msh),
                ],
                stdout_path=dist_tsv,
            )
            if res_dist.returncode != 0:
                raise PhyloError("Mash dist 执行失败", detail=res_dist.stderr[-1000:])
        else:
            res_sketch = self.runner.run_native(
                [
                    desc.path,
                    "sketch",
                    "-i",
                    "-k",
                    str(kmer),
                    "-s",
                    str(sketch_size),
                    "-p",
                    str(safe_threads),
                    str(sanitized_fasta.resolve()),
                    "-o",
                    str(sketch_prefix.resolve()),
                ]
            )
            if res_sketch.returncode != 0:
                raise PhyloError("Mash sketch 执行失败", detail=res_sketch.stderr[-1000:])
            res_dist = self.runner.run_native(
                [desc.path, "dist", "-p", str(safe_threads), str(sketch_msh.resolve()), str(sketch_msh.resolve())],
                stdout_path=dist_tsv,
            )
            if res_dist.returncode != 0:
                raise PhyloError("Mash dist 执行失败", detail=res_dist.stderr[-1000:])

        idx_by_id: Dict[str, int] = {sid: i for i, sid in enumerate(ids)}
        matrix = np.ones((n_seqs, n_seqs), dtype=np.float64)
        np.fill_diagonal(matrix, 0.0)

        with open(dist_tsv, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 3:
                    continue
                q_id = parts[0].strip().split()[0]
                r_id = parts[1].strip().split()[0]
                qi = idx_by_id.get(q_id)
                ri = idx_by_id.get(r_id)
                if qi is None or ri is None or qi == ri:
                    continue
                try:
                    val = float(parts[2])
                except ValueError:
                    val = 1.0
                if not np.isfinite(val):
                    val = 1.0
                val = max(0.0, min(1.0, val))
                matrix[qi, ri] = val
                matrix[ri, qi] = val

        # 确保对称性
        matrix = 0.5 * (matrix + matrix.T)
        np.fill_diagonal(matrix, 0.0)

        return ids, matrix

    @staticmethod
    def save_matrix_artifacts(
        ids: List[str],
        matrix: np.ndarray,
        id_map: Dict[str, str],
        npy_path: Path,
        csv_path: Path,
        ids_json_path: Path,
    ) -> None:
        """持久化二进制距离矩阵与人类可读 CSV（包含原始序列名）。"""
        npy_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(npy_path), matrix)
        ids_json_path.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")

        display_ids = [id_map.get(sid, sid) for sid in ids]
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ID", *display_ids])
            for row_idx, name in enumerate(display_ids):
                writer.writerow([name, *[f"{float(v):.6f}" for v in matrix[row_idx]]])
