# -*- coding: utf-8 -*-
"""
ProteomeTreeEngine - 第 3 步备选路径：全基因组蛋白质组树（类 ViPTree 算法）
当目标为目/科级宏观定位或样本普遍缺少 TerL 时，调用多核 DIAMOND BLASTp 计算所有基因组的
双向共享蛋白得分矩阵，按 ViPTree 公式：
  S_G(A, B) = score(A, B) / sqrt(score(A, A) * score(B, B))
  D(A, B) = -ln(max(eps, S_G))
构建 BioNJ 全基因组蛋白质组系统发育补充树。
"""
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Tuple

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
            except Exception as _exc:
                logger.debug("ProteomeTreeEngine._log 忽略非致命异常: %s", _exc)

    @staticmethod
    def accumulate_blastp_tsv_streaming(
        tsv_path: Path,
        idx_map: Dict[str, int],
    ) -> np.ndarray:
        """
        流式聚合 DIAMOND BLASTp TSV 为基因组对总 bitscore 矩阵。
        DIAMOND 输出按 query 蛋白分组连续排列时只维护单个蛋白的临时字典（O(N) 内存防 OOM）；
        若输入行出现非连续乱序分组，则自动回退到全表精确累加一次。
        """
        n = len(idx_map)
        score_mat = np.zeros((n, n), dtype=np.float64)

        def _flush_protein(cur_q: Optional[str], cur_best: Dict[int, float]) -> None:
            if not cur_q or not cur_best:
                return
            q_genome = cur_q.rsplit("__P", 1)[0]
            q_idx = idx_map.get(q_genome)
            if q_idx is None:
                return
            for s_idx, bs in cur_best.items():
                score_mat[q_idx, s_idx] += bs

        cur_q: Optional[str] = None
        cur_best: Dict[int, float] = {}
        seen_prots: set[str] = set()
        fallback_needed = False

        with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
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

                if cur_q != q_prot:
                    if cur_q is not None:
                        _flush_protein(cur_q, cur_best)
                        seen_prots.add(cur_q)
                    if q_prot in seen_prots:
                        fallback_needed = True
                        break
                    cur_q = q_prot
                    cur_best = {}

                if bs > cur_best.get(s_idx, 0.0):
                    cur_best[s_idx] = bs

        if not fallback_needed:
            _flush_protein(cur_q, cur_best)
            return score_mat

        # 非连续乱序回退精确累加
        score_mat.fill(0.0)
        best_per_pair: Dict[Tuple[str, int], float] = {}
        with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
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

        for (q_prot, s_idx), bs in best_per_pair.items():
            q_genome = q_prot.rsplit("__P", 1)[0]
            q_idx = idx_map.get(q_genome)
            if q_idx is not None:
                score_mat[q_idx, s_idx] += bs
        return score_mat

    @staticmethod
    def compute_sg_distance_matrix(
        score_mat: np.ndarray,
        distance_mode: Literal["log_sg", "one_minus_sg"] = "log_sg",
    ) -> np.ndarray:
        """向量化计算 ViPTree S_G 相似性并转换为演化距离矩阵。"""
        mat = np.array(score_mat, dtype=np.float64, copy=False)
        diag = np.maximum(1e-6, np.diag(mat))
        sym = 0.5 * (mat + mat.T)
        denom = np.maximum(1e-12, np.sqrt(np.outer(diag, diag)))
        sg = np.clip(sym / denom, 1e-6, 1.0)
        if distance_mode == "one_minus_sg":
            dist = np.clip(1.0 - sg, 0.0, 1.0)
        else:
            dist = np.maximum(0.0, -np.log(sg))
        np.fill_diagonal(dist, 0.0)
        return np.asarray(dist, dtype=np.float64)

    def build_proteome_tree(
        self,
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        output_nwk: Path,
        dist_npy: Path,
        dist_csv: Path,
        threads: int = 0,
        tree_method: Literal["bionj", "upgma"] = "bionj",
        distance_mode: Literal["log_sg", "one_minus_sg"] = "log_sg",
        use_gpu: bool = True,
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

        # 检查断点矩阵缓存是否命中（相同样本集与 ORF 数量）
        fp_hasher = hashlib.sha256()
        for sid in labels:
            fp_hasher.update(f"{sid}:{orf_counts[sid]}\n".encode("utf-8"))
        proteome_fp = fp_hasher.hexdigest()

        score_ckpt_json = work_dir / "proteome_checkpoint.json"
        score_mat_npy = work_dir / "proteome_score_mat.npy"
        score_mat: Optional[np.ndarray] = None
        if score_ckpt_json.is_file() and score_mat_npy.is_file():
            try:
                ckpt_meta = json.loads(score_ckpt_json.read_text(encoding="utf-8"))
                if ckpt_meta.get("fingerprint") == proteome_fp:
                    loaded = np.load(str(score_mat_npy))
                    if loaded.shape == (n, n):
                        score_mat = np.asarray(loaded, dtype=np.float64)
                        self._log(f"[ProteomeTree] 命中全基因组得分矩阵断点缓存 ({n}x{n})，跳过重复 BLASTp")
            except Exception:
                score_mat = None

        if score_mat is None:
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
            is_large_scale = n >= 200
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
                "--threads",
                str(safe_threads),
                "--block-size",
                "2.0",
                "--max-target-seqs",
                str(min(2500, max(250, n))) if is_large_scale else str(max(200, n * 4)),
                "--quiet",
            ]
            if not is_large_scale:
                cmd.insert(-1, "--sensitive")

            mode_desc = "快速高通量模式" if is_large_scale else "--sensitive"
            self._log(
                f"[ProteomeTree] 运行全对全 DIAMOND BLASTp ({n} 株基因组, 线程={safe_threads}, {mode_desc})"
            )
            res = self.runner.run_wsl(cmd)
            if res.returncode != 0 or not tsv_out.is_file():
                raise PhyloError("DIAMOND BLASTp 失败", detail=res.stderr[-800:])

            score_mat = self.accumulate_blastp_tsv_streaming(tsv_out, idx_map)
            np.save(str(score_mat_npy), score_mat)
            score_ckpt_json.write_text(
                json.dumps({"fingerprint": proteome_fp, "n": n}, ensure_ascii=False),
                encoding="utf-8",
            )

        dist_mat = self.compute_sg_distance_matrix(score_mat, distance_mode=distance_mode)

        np.save(str(dist_npy), dist_mat)
        NJBioNJEngine.save_distance_csv(labels, dist_mat, dist_csv)
        nj = NJBioNJEngine(cancel_event=self.cancel_event, on_log=self.on_log)
        nj.build_from_matrix(labels, dist_mat, output_nwk, method=tree_method, use_gpu=use_gpu)

        report = MarkerExtractionReport(
            mode="proteome",
            total_genomes=n,
            extracted_count=sum(1 for v in orf_counts.values() if v > 0),
            missing_ids=[k for k, v in orf_counts.items() if v == 0],
            tool_used=f"prodigal-gv + DIAMOND BLASTp (ViPTree S_G) + {tree_method.upper()}",
            tool_version=diamond_desc.version,
            hits=hits_items,
        )
        return output_nwk, report
