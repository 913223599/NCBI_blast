# -*- coding: utf-8 -*-
"""
ProteomeTreeEngine - 第 3 步备选路径：全基因组蛋白质组树（类 ViPTree 算法）
当目标为目/科级宏观定位或样本普遍缺少 TerL 时，调用多核 DIAMOND BLASTp 计算所有基因组的
双向共享蛋白得分矩阵，按 ViPTree 公式：
  S_G(A, B) = score(A, B) / sqrt(score(A, A) * score(B, B))
  D(A, B) = -ln(max(eps, S_G))
构建 BioNJ 全基因组蛋白质组系统发育补充树。
"""
import logging
import math
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ...core.fasta_io import iter_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...models.schemas import MarkerExtractionReport, MarkerHitItem
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry
from ..tree.nj import NJBioNJEngine
from .terl_extractor import TerlExtractor

logger = logging.getLogger("phylo.proteome_tree")


class ProteomeTreeEngine:
    """基于全基因组共享蛋白相似性 (ViPTree-like) 的备选宏观构树引擎。"""

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
        self.terl_helper = TerlExtractor(cancel_event=self.cancel_event, on_log=self.on_log)

    def terminate_active(self) -> None:
        self.runner.terminate_active()
        self.terl_helper.terminate_active()

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def build_proteome_tree(
        self,
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        output_nwk: Path,
        dist_npy: Path,
        dist_csv: Path,
        threads: int = 0,
    ) -> Tuple[Path, MarkerExtractionReport]:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("蛋白质组树构建已取消")

        diamond_desc = self.registry.get("diamond")
        if not diamond_desc.available:
            raise ToolUnavailableError("diamond", f"DIAMOND 不可用: {diamond_desc.notes}")

        work_dir.mkdir(parents=True, exist_ok=True)
        orf_paths = self.terl_helper.predict_orfs_batch(genome_fastas, threads=threads)

        labels = list(genome_fastas.keys())
        idx_map = {sid: idx for idx, sid in enumerate(labels)}
        n = len(labels)

        combined_faa = work_dir / "proteome_all_orfs.faa"
        orf_counts: Dict[str, int] = {sid: 0 for sid in labels}
        hits_items: List[MarkerHitItem] = []

        with open(combined_faa, "w", encoding="utf-8", newline="\n") as out_fh:
            for sid in labels:
                cnt = 0
                for idx, rec in enumerate(iter_fasta_records(orf_paths[sid]), start=1):
                    aa = str(rec.seq).replace("*", "").strip()
                    if len(aa) < 30:
                        continue
                    cnt += 1
                    out_fh.write(f">{sid}__P{idx}\n{aa}\n")
                orf_counts[sid] = cnt
                hits_items.append(
                    MarkerHitItem(
                        sample_id=sid,
                        protein_id=f"{cnt} ORFs",
                        aa_length=cnt,
                        status="extracted" if cnt > 0 else "missing",
                        notes=f"共预测 {cnt} 个蛋白用于全基因组蛋白质组相似性矩阵计算",
                    )
                )

        from src.assembly.env.wsl_manager import WSLManager

        db_prefix = work_dir / "proteome_dmnd"
        mk_res = self.runner.run_wsl(
            [
                diamond_desc.path,
                "makedb",
                "--in",
                WSLManager.to_wsl_path(str(combined_faa.resolve())),
                "-d",
                WSLManager.to_wsl_path(str(db_prefix.resolve())),
                "--quiet",
            ]
        )
        if mk_res.returncode != 0:
            raise PhyloError("DIAMOND makedb 失败", detail=mk_res.stderr[-600:])

        safe_threads = get_safe_cpu_budget(threads)
        tsv_out = work_dir / "proteome_blastp.tsv"
        cmd = [
            diamond_desc.path,
            "blastp",
            "-q",
            WSLManager.to_wsl_path(str(combined_faa.resolve())),
            "-d",
            WSLManager.to_wsl_path(str(db_prefix.resolve())),
            "-o",
            WSLManager.to_wsl_path(str(tsv_out.resolve())),
            "--outfmt",
            "6",
            "qseqid",
            "sseqid",
            "bitscore",
            "-e",
            "1e-5",
            "--sensitive",
            "--threads",
            str(safe_threads),
            "--max-target-seqs",
            str(max(200, n * 4)),
            "--quiet",
        ]
        self._log(f"[ProteomeTree] 运行全对全 DIAMOND BLASTp ({n} 株基因组, 线程={safe_threads})")
        res = self.runner.run_wsl(cmd)
        if res.returncode != 0 or not tsv_out.is_file():
            raise PhyloError("DIAMOND BLASTp 失败", detail=res.stderr[-800:])

        # 对每个 (q_protein, target_genome) 取最高 bitscore 再对基因组对求和
        best_per_pair: Dict[Tuple[str, int], float] = {}
        with open(tsv_out, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3 or "__P" not in parts[0] or "__P" not in parts[1]:
                    continue
                q_prot = parts[0]
                s_genome = parts[1].rsplit("__P", 1)[0]
                s_idx = idx_map.get(s_genome)
                if s_idx is None:
                    continue
                try:
                    bs = float(parts[2])
                except ValueError:
                    continue
                key = (q_prot, s_idx)
                if bs > best_per_pair.get(key, 0.0):
                    best_per_pair[key] = bs

        score_mat = np.zeros((n, n), dtype=np.float64)
        for (q_prot, s_idx), bs in best_per_pair.items():
            q_genome = q_prot.rsplit("__P", 1)[0]
            q_idx = idx_map.get(q_genome)
            if q_idx is not None:
                score_mat[q_idx, s_idx] += bs

        dist_mat = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                s_ii = max(1e-6, float(score_mat[i, i]))
                s_jj = max(1e-6, float(score_mat[j, j]))
                s_ij = 0.5 * (float(score_mat[i, j]) + float(score_mat[j, i]))
                sg = min(1.0, max(1e-6, s_ij / math.sqrt(s_ii * s_jj)))
                d = max(0.0, -math.log(sg))
                dist_mat[i, j] = dist_mat[j, i] = d

        np.save(str(dist_npy), dist_mat)
        NJBioNJEngine.save_distance_csv(labels, dist_mat, dist_csv)
        nj = NJBioNJEngine(cancel_event=self.cancel_event, on_log=self.on_log)
        nj.build_from_distance_matrix(labels, dist_mat, output_nwk, method="bionj")

        report = MarkerExtractionReport(
            mode="proteome",
            total_genomes=n,
            extracted_count=sum(1 for v in orf_counts.values() if v > 0),
            missing_ids=[k for k, v in orf_counts.items() if v == 0],
            tool_used="prodigal-gv + DIAMOND BLASTp (ViPTree S_G) + BioNJ",
            tool_version=diamond_desc.version,
            hits=hits_items,
        )
        return output_nwk, report
