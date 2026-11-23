# -*- coding: utf-8 -*-
"""
MashScreener - 基于本地 INPHARED 全库 Mash 索引 (37,563+ 噬菌体) 的快速初筛器
"""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry
from .inphared_index import InpharedIndex, InpharedRecord, get_inphared_index

logger = logging.getLogger("phylo.mash_screener")


@dataclass
class MashHit:
    query_id: str
    ref_accession: str
    distance: float
    pvalue: float
    shared_hashes: int
    total_hashes: int
    meta: Optional[InpharedRecord] = None

    @property
    def mash_ani(self) -> float:
        return round(max(0.0, (1.0 - self.distance) * 100.0), 2)


class MashScreener:
    """用官方 Mash 对查询噬菌体基因组秒扫 INPHARED 参考数据库。"""

    def __init__(
        self,
        index: Optional[InpharedIndex] = None,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.index = index or get_inphared_index()
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
            except Exception:
                pass

    def screen_against_inphared(
        self,
        query_fasta: Path,
        work_dir: Path,
        top_k: int = 40,
        threads: int = 0,
    ) -> Tuple[List[MashHit], str]:
        """
        对 query_fasta 执行 `mash dist` 初筛，返回 (按最佳相似度排序的命中列表, 实际命令预览)。
        """
        if self.cancel_event.is_set():
            raise PhyloCancelledError("INPHARED Mash 初筛前任务已取消")

        msh_path = self.index.msh_path
        if not msh_path.is_file():
            raise PhyloError(f"未找到 INPHARED Mash 索引文件: {msh_path}")

        desc = self.registry.get("mash")
        if not desc.available:
            raise ToolUnavailableError("mash", f"Mash 不可用: {desc.notes}")

        safe_threads = get_safe_cpu_budget(threads)
        work_dir.mkdir(parents=True, exist_ok=True)
        raw_out = work_dir / "inphared_mash_dist.tsv"

        self._log(
            f"[ANI-Screen] 使用 Mash ({desc.runtime}) 扫描 INPHARED 全库 ({msh_path.name}), 线程={safe_threads}"
        )

        if desc.runtime == "wsl":
            from src.assembly.env.wsl_manager import WSLManager

            cmd = [
                desc.path,
                "dist",
                "-p",
                str(safe_threads),
                "-i",
                "-d",
                "0.45",
                WSLManager.to_wsl_path(str(msh_path.resolve())),
                WSLManager.to_wsl_path(str(query_fasta.resolve())),
            ]
            cmd_preview = " ".join(cmd)
            res = self.runner.run_wsl(cmd, stdout_path=raw_out)
        else:
            cmd = [
                desc.path,
                "dist",
                "-p",
                str(safe_threads),
                "-i",
                "-d",
                "0.45",
                str(msh_path.resolve()),
                str(query_fasta.resolve()),
            ]
            cmd_preview = " ".join(cmd)
            res = self.runner.run_native(cmd, stdout_path=raw_out)

        if res.returncode != 0:
            raise PhyloError(
                f"INPHARED Mash 扫描失败 (exit={res.returncode})",
                detail=res.stderr[-1000:],
            )

        hits = self._parse_mash_tsv(raw_out, top_k=top_k)
        # 若严格阈值 -d 0.45 未命中任何结果（例如高度新颖的未知科噬菌体），放宽至全扫描兜底捞出最近远缘邻株
        if not hits:
            self._log("[ANI-Screen] -d 0.45 未命中近邻，自动放宽距离阈值重新检索远缘参考株...")
            relaxed_cmd = [tok for tok in cmd if tok not in ("-d", "0.45")]
            cmd_preview = " ".join(relaxed_cmd)
            res = (
                self.runner.run_wsl(relaxed_cmd, stdout_path=raw_out)
                if desc.runtime == "wsl"
                else self.runner.run_native(relaxed_cmd, stdout_path=raw_out)
            )
            if res.returncode == 0:
                hits = self._parse_mash_tsv(raw_out, top_k=top_k)

        if hits and self.index.is_available():
            meta_map = self.index.get_by_accessions(h.ref_accession for h in hits)
            for h in hits:
                h.meta = meta_map.get(h.ref_accession)

        self._log(f"[ANI-Screen] INPHARED 初筛完成，命中 {len(hits)} 条候选参考基因组。")
        return hits, cmd_preview

    @staticmethod
    def _parse_mash_tsv(tsv_path: Path, top_k: int = 40) -> List[MashHit]:
        if not tsv_path.is_file():
            return []
        by_ref: Dict[str, MashHit] = {}
        with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                ref_id = parts[0].strip()
                query_id = parts[1].strip()
                try:
                    dist = float(parts[2])
                    pval = float(parts[3])
                    shared_raw, total_raw = parts[4].split("/")
                    shared = int(shared_raw)
                    total = int(total_raw)
                except (ValueError, IndexError):
                    continue
                if shared <= 0:
                    continue
                hit = MashHit(
                    query_id=query_id,
                    ref_accession=ref_id,
                    distance=dist,
                    pvalue=pval,
                    shared_hashes=shared,
                    total_hashes=total,
                )
                prev = by_ref.get(ref_id)
                if prev is None or (hit.distance < prev.distance) or (
                    hit.distance == prev.distance and hit.shared_hashes > prev.shared_hashes
                ):
                    by_ref[ref_id] = hit

        ranked = sorted(by_ref.values(), key=lambda h: (h.distance, -h.shared_hashes))
        return ranked[:top_k]
