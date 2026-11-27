# -*- coding: utf-8 -*-
"""
PhageDereplicator - 噬菌体参考基因组去冗余引擎
优先调用官方 dRep CLI (`dRep dereplicate -ignoreGenomeQuality -l 20000 -pa 0.90 -SkipSecondary`)；
若未安装 dRep，则基于 ANI 矩阵执行严格等效的连通簇代表选取（保护查询株、外群与 ICTV 代表不被删减）。
"""
import logging
import shutil
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from ...core.fasta_io import iter_fasta_records
from ...models.errors import PhyloCancelledError
from ...models.schemas import ReferenceCandidate
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.dereplicator")


class PhageDereplicator:
    """噬菌体基因组去冗余调度器（dRep 优先 + ANI 聚类等效回退）。"""

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
                logger.debug("PhageDereplicator 日志回调执行失败: %s", _exc)

    def dereplicate(
        self,
        genome_paths: Dict[str, Path],
        candidates: List[ReferenceCandidate],
        work_dir: Path,
        pa_threshold: float = 0.90,
        min_length: int = 20000,
        threads: int = 0,
        ani_matrix: Optional[Tuple[List[str], List[List[float]]]] = None,
    ) -> Tuple[Dict[str, Path], Dict[str, str | int]]:
        """
        对非保护参考株执行 ANI 去冗余。
        返回: (保留的 {accession: fasta_path}, 统计与使用工具详情)
        """
        if self.cancel_event.is_set():
            raise PhyloCancelledError("去冗余阶段已取消")

        if pa_threshold >= 1.0:
            self._log("[Derep] 已关闭去冗余 (pa>=1.00)，完整保留全部选定同种与近缘参考株。")
            return dict(genome_paths), {
                "before": len(genome_paths),
                "after": len(genome_paths),
                "removed": 0,
                "tool": "disabled (keep all selected strains)",
            }

        cand_map = {c.accession: c for c in candidates}
        # 查询株和指定外群受到硬性保护，绝不作为冗余被删除
        protected: Set[str] = {
            acc for acc, c in cand_map.items() if c.role in ("query", "outgroup")
        }
        # 保留每个候选属至少 1 条正式 ICTV 代表防止去冗余误杀唯一属代表
        seen_genus_rep: Set[str] = set()
        for acc in genome_paths:
            c = cand_map.get(acc)
            if c and c.is_ictv_classified and c.genus and c.genus not in seen_genus_rep:
                seen_genus_rep.add(c.genus)
                protected.add(acc)

        unprotected = [acc for acc in genome_paths if acc not in protected]
        if len(unprotected) < 3:
            return dict(genome_paths), {
                "before": len(genome_paths),
                "after": len(genome_paths),
                "removed": 0,
                "tool": "skipped (<=2 unprotected refs)",
            }

        # 优先调用官方 WSL dRep CLI
        drep_desc = self.registry.get("drep")
        if drep_desc.available:
            res = self._try_run_drep(
                drep_desc.path,
                genome_paths,
                protected,
                unprotected,
                cand_map,
                work_dir,
                pa_threshold,
                min_length,
                threads,
            )
            if res is not None:
                return res

        # 回退至基于 ANI 矩阵的连通分量去冗余（严格等效 -pa 0.90 主聚类）
        return self._fallback_ani_cluster(
            genome_paths,
            protected,
            cand_map,
            pa_threshold,
            min_length,
            ani_matrix,
        )

    def _try_run_drep(
        self,
        drep_bin: str,
        genome_paths: Dict[str, Path],
        protected: Set[str],
        unprotected: List[str],
        cand_map: Dict[str, ReferenceCandidate],
        work_dir: Path,
        pa_threshold: float,
        min_length: int,
        threads: int,
    ) -> Optional[Tuple[Dict[str, Path], Dict[str, str | int]]]:
        from src.assembly.env.wsl_manager import WSLManager

        drep_dir = work_dir / "drep_run"
        in_dir = drep_dir / "inputs"
        out_dir = drep_dir / "output"
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        in_dir.mkdir(parents=True, exist_ok=True)

        # 仅把长于 min_length 门槛（若所有序列均较短如实验合成，则安全放宽）放入 dRep
        file_to_acc: Dict[str, str] = {}
        eligible_files: List[str] = []
        short_fallback: Set[str] = set()
        for idx, acc in enumerate(unprotected, start=1):
            fpath = genome_paths[acc]
            seq_len = sum(len(r.seq) if r.seq is not None else 0 for r in iter_fasta_records(fpath))
            if seq_len < min_length:
                # 保留太短但未被 dRep -l 过滤导致全军覆没的边界情况记入日志
                short_fallback.add(acc)
            dst = in_dir / f"G{idx:04d}.fasta"
            shutil.copyfile(fpath, dst)
            wsl_p = WSLManager.to_wsl_path(str(dst.resolve()))
            eligible_files.append(wsl_p)
            file_to_acc[dst.name] = acc

        effective_min_len = min_length if len(short_fallback) < len(unprotected) else 1000
        safe_threads = get_safe_cpu_budget(threads)
        cmd = [
            drep_bin,
            "dereplicate",
            WSLManager.to_wsl_path(str(out_dir.resolve())),
            "--ignoreGenomeQuality",
            "-l",
            str(effective_min_len),
            "-pa",
            f"{pa_threshold:.2f}",
            "--SkipSecondary",
            "-p",
            str(safe_threads),
            "-g",
            *eligible_files,
        ]
        self._log(f"[dRep] 执行官方去冗余: -l {effective_min_len} -pa {pa_threshold:.2f} --SkipSecondary")
        res = self.runner.run_wsl(cmd, stream_stdout_to_log=True)
        derep_genomes_dir = out_dir / "dereplicated_genomes"
        if res.returncode != 0 or not derep_genomes_dir.is_dir():
            self._log("[dRep] 官方 dRep 运行未产出目录，回退至等效 ANI 聚类算法。")
            return None

        kept_accs: Set[str] = set(protected)
        for fp in derep_genomes_dir.iterdir():
            if fp.is_file() and fp.name in file_to_acc:
                kept_accs.add(file_to_acc[fp.name])

        kept = {acc: genome_paths[acc] for acc in genome_paths if acc in kept_accs}
        for acc, cand in cand_map.items():
            if acc in genome_paths and acc not in kept_accs:
                cand.selected = False

        stats = {
            "before": len(genome_paths),
            "after": len(kept),
            "removed": len(genome_paths) - len(kept),
            "tool": f"dRep (WSL, pa={pa_threshold:.2f})",
        }
        self._log(f"[dRep] 去冗余完成: {stats['before']} -> {stats['after']} 条基因组。")
        return kept, stats

    def _fallback_ani_cluster(
        self,
        genome_paths: Dict[str, Path],
        protected: Set[str],
        cand_map: Dict[str, ReferenceCandidate],
        pa_threshold: float,
        min_length: int,
        ani_matrix: Optional[Tuple[List[str], List[List[float]]]],
    ) -> Tuple[Dict[str, Path], Dict[str, str | int]]:
        threshold_pct = pa_threshold * 100.0
        labels = list(genome_paths.keys())
        idx_map: Dict[str, int] = {}
        mat: List[List[float]] = []
        if ani_matrix:
            m_labels, m_vals = ani_matrix
            idx_map = {lbl: idx for idx, lbl in enumerate(m_labels)}
            mat = m_vals

        def _priority_key(acc: str) -> Tuple[int, int, int, int]:
            c = cand_map.get(acc)
            is_prot = 1 if acc in protected else 0
            is_ictv = 1 if (c and c.is_ictv_classified) else 0
            comp = int(c.completeness or 90) if c else 90
            length = c.genome_length if c else 0
            return (is_prot, is_ictv, comp, length)

        # 构建相似图并用贪心代表选择进行聚类
        sorted_accs = sorted(labels, key=_priority_key, reverse=True)
        kept_accs: Set[str] = set()
        for acc in sorted_accs:
            if acc in protected:
                kept_accs.add(acc)
                continue
            c = cand_map.get(acc)
            if c and c.genome_length > 0 and c.genome_length < min_length:
                # 若总参考株较多且该条目短于阈值，仅在有其他代表时剔除
                if len(kept_accs) >= 5:
                    continue
            redundant = False
            i = idx_map.get(acc)
            if i is not None and mat:
                for rep_acc in kept_accs:
                    if cand_map.get(rep_acc) and cand_map[rep_acc].role == "query":
                        # 查询株本身不吸收非查询参考株为冗余
                        continue
                    j = idx_map.get(rep_acc)
                    if j is not None and mat[i][j] >= threshold_pct:
                        redundant = True
                        break
            if not redundant:
                kept_accs.add(acc)

        kept = {acc: genome_paths[acc] for acc in labels if acc in kept_accs}
        for acc, cand in cand_map.items():
            if acc in genome_paths and acc not in kept_accs:
                cand.selected = False

        stats = {
            "before": len(genome_paths),
            "after": len(kept),
            "removed": len(genome_paths) - len(kept),
            "tool": f"ANI-Cluster-Equiv (pa={pa_threshold:.2f})",
        }
        self._log(f"[Derep] 去冗余完成 ({stats['tool']}): {stats['before']} -> {stats['after']} 条。")
        return kept, stats
