# -*- coding: utf-8 -*-
"""
ViridicAniCalculator - 科研标准噬菌体全基因组相似性 (VIRIDIC-wgANI / FastANI / skani) 计算引擎
严格依据 Moraru et al. (2020) VIRIDIC 公式计算双向非重叠覆盖碱基数与一致碱基数：
  intergenomic_similarity (wgANI%) = (ident_AB + ident_BA) / (len_A + len_B) * 100
  AF_A(%) = aligned_len_A / len_A * 100
  aligned_ANI(%) = (ident_AB + ident_BA) / (aligned_len_A + aligned_len_B) * 100
支持大规模矩阵分片落盘与 Checkpoint 断点保护，以及 ICTV 70%/95% 阈值判定和嵌合预警。
"""
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ...core.fasta_io import iter_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...models.schemas import AniEngineType, AniHitRecord, AniScreenResult, DeliveryScopeConfig
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_tool_registry
from .inphared_index import InpharedIndex, InpharedRecord, get_inphared_index

logger = logging.getLogger("phylo.viridic_ani")


@dataclass
class HspSegment:
    q_start: int
    q_end: int
    nident: int
    align_len: int


def compute_covered_bases_and_ident(length: int, hsps: Sequence[HspSegment]) -> Tuple[int, float]:
    """
    计算单向所有 HSP 在查询序列上的并集覆盖长度，以及按高一致度优先覆盖的匹配碱基数。
    避免重复比对区间导致 AF > 100% 或 wgANI 虚高。
    """
    if length <= 0 or not hsps:
        return 0, 0.0

    # 按一致度比例降序覆盖位点（对于 3kb~500kb 噬菌体基因组，float32/boolean 数组极快且零重叠误差）
    if length <= 2_000_000:
        best_pident = np.zeros(length, dtype=np.float32)
        covered = np.zeros(length, dtype=bool)
        for h in hsps:
            s = max(0, min(h.q_start, h.q_end) - 1)
            e = min(length, max(h.q_start, h.q_end))
            if e <= s:
                continue
            ratio = min(1.0, max(0.0, float(h.nident) / max(1, h.align_len)))
            covered[s:e] = True
            slice_view = best_pident[s:e]
            np.maximum(slice_view, ratio, out=slice_view)
        cov_bases = int(covered.sum())
        ident_bases = float(best_pident[covered].sum()) if cov_bases > 0 else 0.0
        return cov_bases, ident_bases

    # 超大基因组（> 2Mb）改用区间扫描线合并，防止大内存占用
    intervals = sorted(
        (max(0, min(h.q_start, h.q_end) - 1), min(length, max(h.q_start, h.q_end)), float(h.nident) / max(1, h.align_len))
        for h in hsps
    )
    merged_cov = 0
    weighted_ident = 0.0
    cur_s, cur_e, cur_r = -1, -1, 0.0
    for s, e, r in intervals:
        if e <= s:
            continue
        if cur_s < 0:
            cur_s, cur_e, cur_r = s, e, r
        elif s <= cur_e:
            if e > cur_e:
                cur_e = e
            cur_r = max(cur_r, r)
        else:
            span = cur_e - cur_s
            merged_cov += span
            weighted_ident += span * cur_r
            cur_s, cur_e, cur_r = s, e, r
    if cur_s >= 0:
        span = cur_e - cur_s
        merged_cov += span
        weighted_ident += span * cur_r
    return merged_cov, weighted_ident


def compute_viridic_pair_metrics(
    len_a: int,
    len_b: int,
    hsps_ab: Sequence[HspSegment],
    hsps_ba: Sequence[HspSegment],
) -> Tuple[float, float, float, float]:
    """
    计算两两噬菌体 (A, B) 的 VIRIDIC 指标：
    返回 (wg_ani_pct, aligned_ani_pct, af_a_pct, af_b_pct)。
    """
    cov_a, ident_ab = compute_covered_bases_and_ident(len_a, hsps_ab)
    cov_b, ident_ba = compute_covered_bases_and_ident(len_b, hsps_ba)

    total_len = max(1, len_a + len_b)
    wg_ani = ((ident_ab + ident_ba) / total_len) * 100.0
    af_a = (cov_a / max(1, len_a)) * 100.0
    af_b = (cov_b / max(1, len_b)) * 100.0
    total_cov = cov_a + cov_b
    aligned_ani = ((ident_ab + ident_ba) / total_cov) * 100.0 if total_cov > 0 else 0.0

    return (
        round(min(100.0, max(0.0, wg_ani)), 2),
        round(min(100.0, max(0.0, aligned_ani)), 2),
        round(min(100.0, max(0.0, af_a)), 2),
        round(min(100.0, max(0.0, af_b)), 2),
    )


def classify_ictv_threshold(
    wg_ani: float,
    aligned_ani: float,
    af_query: float,
    af_ref: float,
    species_threshold: float = 95.0,
    genus_threshold: float = 70.0,
) -> Tuple[str, bool]:
    """
    基于 ICTV Caudoviricetes 标准阈值判定初步分类地位与嵌合警告。
    - >=95%: same_species
    - 70%~95%: same_genus_new_species (若在 65%~75% 模糊带标注 genus_boundary_ambiguous)
    - 65%~70%: genus_boundary_ambiguous
    - <65%: novel_genus_candidate
    """
    mosaic = min(af_query, af_ref) < 50.0 and aligned_ani >= 80.0
    if wg_ani >= species_threshold:
        return "same_species", mosaic
    if abs(wg_ani - genus_threshold) <= 5.0:
        return "genus_boundary_ambiguous", mosaic
    if wg_ani >= genus_threshold:
        return "same_genus_new_species", mosaic
    return "novel_genus_candidate", mosaic


class ViridicAniCalculator:
    """多核分片 VIRIDIC-wgANI / FastANI / skani 计算与 ICTV 解读引擎。"""

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

    def compute_matrix_from_fastas(
        self,
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        engine: AniEngineType = "viridic_blastn",
        threads: int = 0,
        batch_size: int = 16,
    ) -> Tuple[List[str], List[List[float]], List[List[float]], Dict[Tuple[str, str], Tuple[float, float, float, float]], str, str]:
        """
        计算任意 N 条完整噬菌体基因组的两两 wgANI 与 AF 矩阵。
        支持分片落盘 + Checkpoint 断点恢复。
        返回: (labels, wgani_matrix, af_matrix, pair_details, actual_engine_ver, cmd_preview)
        """
        labels = list(genome_fastas.keys())
        n = len(labels)
        if n == 0:
            return [], [], [], {}, "", ""

        work_dir.mkdir(parents=True, exist_ok=True)
        shards_dir = work_dir / "ani_shards"
        shards_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = work_dir / "ani_checkpoint.json"

        # 建立纯 ASCII 短 ID 映射供外部 blastn/skani/fastANI 安全使用，规避中文/特殊字符路径或 header 干扰
        sid_to_ascii: Dict[str, str] = {sid: f"G{idx + 1:05d}" for idx, sid in enumerate(labels)}
        ascii_to_sid: Dict[str, str] = {v: k for k, v in sid_to_ascii.items()}

        # 收集序列长度并写入合并 FASTA 供 blastn / skani 使用
        lengths: Dict[str, int] = {}
        combined_fasta = work_dir / "ani_combined_genomes.fasta"
        with open(combined_fasta, "w", encoding="utf-8", newline="\n") as out_fh:
            for sid in labels:
                fpath = genome_fastas[sid]
                total_len = 0
                seq_chunks: List[str] = []
                for rec in iter_fasta_records(fpath):
                    s = str(rec.seq).strip().upper()
                    total_len += len(s)
                    seq_chunks.append(s)
                lengths[sid] = total_len
                merged_seq = "".join(seq_chunks)
                out_fh.write(f">{sid_to_ascii[sid]}\n")
                for pos in range(0, len(merged_seq), 80):
                    out_fh.write(merged_seq[pos : pos + 80] + "\n")

        safe_threads = get_safe_cpu_budget(threads)

        # 如果选择 skani 且可用，走极速 skani triangle + af
        if engine == "skani" and self.registry.get("skani").available:
            return self._run_skani_matrix(
                labels, lengths, genome_fastas, work_dir, safe_threads
            )

        # 如果选择 fastani 且可用，且基因组数量适合，走官方 fastANI
        if engine == "fastani" and self.registry.get("fastani").available:
            return self._run_fastani_matrix(
                labels, lengths, genome_fastas, work_dir, safe_threads
            )

        # 默认主科学路线：VIRIDIC-BLASTn (分片建库查询 + 严格公式计算)
        blastn_desc = self.registry.get("blastn")
        if not blastn_desc.available:
            raise ToolUnavailableError("blastn", f"BLASTn 不可用: {blastn_desc.notes}")

        from src.assembly.env.wsl_manager import WSLManager

        blast_db = work_dir / "ani_blastdb" / "phages"
        blast_db.parent.mkdir(parents=True, exist_ok=True)

        # 调用 makeblastdb 构建库
        if blastn_desc.runtime == "wsl":
            makeblastdb_bin = str(PurePosixPath(blastn_desc.path).with_name("makeblastdb"))
            mk_cmd = [
                makeblastdb_bin,
                "-in",
                WSLManager.to_wsl_path(str(combined_fasta.resolve())),
                "-dbtype",
                "nucl",
                "-out",
                WSLManager.to_wsl_path(str(blast_db.resolve())),
            ]
            mk_res = self.runner.run_wsl(mk_cmd)
        else:
            makeblastdb_bin = str(Path(blastn_desc.path).with_name("makeblastdb"))
            mk_cmd = [
                makeblastdb_bin,
                "-in",
                str(combined_fasta.resolve()),
                "-dbtype",
                "nucl",
                "-out",
                str(blast_db.resolve()),
            ]
            mk_res = self.runner.run_native(mk_cmd)
        if mk_res.returncode != 0:
            raise PhyloError("makeblastdb 构建 ANI 参考库失败", detail=mk_res.stderr[-800:])

        # 读取已有分片 checkpoint
        completed_batches: set[int] = set()
        if ckpt_path.is_file():
            try:
                ckpt_data = json.loads(ckpt_path.read_text(encoding="utf-8"))
                completed_batches = set(ckpt_data.get("completed_batches", []))
            except Exception:
                completed_batches = set()

        # 按 batch_size 分片执行 blastn（支持断点续算与强杀取消）
        total_batches = (n + batch_size - 1) // batch_size
        cmd_preview = ""
        hsp_map: Dict[Tuple[str, str], List[HspSegment]] = {}

        for b_idx in range(total_batches):
            if self.cancel_event.is_set():
                raise PhyloCancelledError("VIRIDIC-wgANI 分片计算已取消")

            shard_tsv = shards_dir / f"blast_batch_{b_idx}.tsv"
            batch_ids = labels[b_idx * batch_size : (b_idx + 1) * batch_size]

            if b_idx not in completed_batches or not shard_tsv.is_file():
                query_slice_fa = shards_dir / f"query_batch_{b_idx}.fasta"
                batch_set = {sid_to_ascii[sid] for sid in batch_ids}
                with open(query_slice_fa, "w", encoding="utf-8", newline="\n") as qfh:
                    for rec in iter_fasta_records(combined_fasta):
                        if rec.id in batch_set:
                            qfh.write(f">{rec.id}\n{str(rec.seq)}\n")

                if blastn_desc.runtime == "wsl":
                    cmd = [
                        blastn_desc.path,
                        "-query",
                        WSLManager.to_wsl_path(str(query_slice_fa.resolve())),
                        "-db",
                        WSLManager.to_wsl_path(str(blast_db.resolve())),
                        "-word_size",
                        "7",
                        "-reward",
                        "2",
                        "-penalty",
                        "-3",
                        "-gapopen",
                        "5",
                        "-gapextend",
                        "2",
                        "-dust",
                        "no",
                        "-soft_masking",
                        "false",
                        "-evalue",
                        "1e-3",
                        "-num_threads",
                        str(safe_threads),
                        "-max_target_seqs",
                        str(max(500, n * 4)),
                        "-outfmt",
                        "6 qseqid sseqid qstart qend sstart send nident length",
                        "-out",
                        WSLManager.to_wsl_path(str(shard_tsv.resolve())),
                    ]
                    if not cmd_preview:
                        cmd_preview = " ".join(cmd)
                    res = self.runner.run_wsl(cmd)
                else:
                    cmd = [
                        blastn_desc.path,
                        "-query",
                        str(query_slice_fa.resolve()),
                        "-db",
                        str(blast_db.resolve()),
                        "-word_size",
                        "7",
                        "-reward",
                        "2",
                        "-penalty",
                        "-3",
                        "-gapopen",
                        "5",
                        "-gapextend",
                        "2",
                        "-dust",
                        "no",
                        "-soft_masking",
                        "false",
                        "-evalue",
                        "1e-3",
                        "-num_threads",
                        str(safe_threads),
                        "-max_target_seqs",
                        str(max(500, n * 4)),
                        "-outfmt",
                        "6 qseqid sseqid qstart qend sstart send nident length",
                        "-out",
                        str(shard_tsv.resolve()),
                    ]
                    if not cmd_preview:
                        cmd_preview = " ".join(cmd)
                    res = self.runner.run_native(cmd)

                if res.returncode != 0:
                    raise PhyloError(
                        f"BLASTn VIRIDIC 分片 {b_idx + 1}/{total_batches} 执行失败",
                        detail=res.stderr[-800:],
                    )
                completed_batches.add(b_idx)
                ckpt_path.write_text(
                    json.dumps({"completed_batches": sorted(completed_batches)}, ensure_ascii=False),
                    encoding="utf-8",
                )

            # 流式解析当前分片并即时归并 HSP
            if shard_tsv.is_file():
                with open(shard_tsv, "r", encoding="utf-8", errors="replace") as sfh:
                    for line in sfh:
                        parts = line.rstrip("\n").split("\t")
                        if len(parts) < 8:
                            continue
                        qid = ascii_to_sid.get(parts[0], parts[0])
                        sid = ascii_to_sid.get(parts[1], parts[1])
                        try:
                            qs, qe = int(parts[2]), int(parts[3])
                            nident, alen = int(parts[6]), int(parts[7])
                        except ValueError:
                            continue
                        hsp_map.setdefault((qid, sid), []).append(
                            HspSegment(q_start=qs, q_end=qe, nident=nident, align_len=alen)
                        )

        return self._assemble_matrix(
            labels, lengths, hsp_map, blastn_desc.version, cmd_preview
        )

    def _assemble_matrix(
        self,
        labels: List[str],
        lengths: Dict[str, int],
        hsp_map: Dict[Tuple[str, str], List[HspSegment]],
        ver: str,
        cmd_preview: str,
    ) -> Tuple[List[str], List[List[float]], List[List[float]], Dict[Tuple[str, str], Tuple[float, float, float, float]], str, str]:
        n = len(labels)
        wgani_mat = [[0.0] * n for _ in range(n)]
        af_mat = [[0.0] * n for _ in range(n)]
        pair_details: Dict[Tuple[str, str], Tuple[float, float, float, float]] = {}

        for i in range(n):
            wgani_mat[i][i] = 100.0
            af_mat[i][i] = 100.0
            pair_details[(labels[i], labels[i])] = (100.0, 100.0, 100.0, 100.0)
            for j in range(i + 1, n):
                a, b = labels[i], labels[j]
                wg, aln_ani, af_a, af_b = compute_viridic_pair_metrics(
                    lengths.get(a, 0),
                    lengths.get(b, 0),
                    hsp_map.get((a, b), ()),
                    hsp_map.get((b, a), ()),
                )
                wgani_mat[i][j] = wg
                wgani_mat[j][i] = wg
                af_mat[i][j] = af_a
                af_mat[j][i] = af_b
                pair_details[(a, b)] = (wg, aln_ani, af_a, af_b)
                pair_details[(b, a)] = (wg, aln_ani, af_b, af_a)

        return labels, wgani_mat, af_mat, pair_details, ver, cmd_preview

    def _run_skani_matrix(
        self,
        labels: List[str],
        lengths: Dict[str, int],
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        safe_threads: int,
    ) -> Tuple[List[str], List[List[float]], List[List[float]], Dict[Tuple[str, str], Tuple[float, float, float, float]], str, str]:
        from src.assembly.env.wsl_manager import WSLManager

        desc = self.registry.get("skani")
        list_file = work_dir / "skani_inputs.txt"
        out_tsv = work_dir / "skani_dist.tsv"
        path_to_id: Dict[str, str] = {}
        with open(list_file, "w", encoding="utf-8", newline="\n") as fh:
            for sid in labels:
                wsl_p = WSLManager.to_wsl_path(str(genome_fastas[sid].resolve()))
                fh.write(wsl_p + "\n")
                path_to_id[wsl_p] = sid
                path_to_id[Path(wsl_p).name] = sid

        cmd = [
            desc.path,
            "dist",
            "--ql",
            WSLManager.to_wsl_path(str(list_file.resolve())),
            "--rl",
            WSLManager.to_wsl_path(str(list_file.resolve())),
            "-t",
            str(safe_threads),
            "-s",
            "50",
            "-o",
            WSLManager.to_wsl_path(str(out_tsv.resolve())),
        ]
        res = self.runner.run_wsl(cmd)
        if res.returncode != 0:
            raise PhyloError("skani ANI 计算失败", detail=res.stderr[-800:])

        n = len(labels)
        idx_map = {sid: idx for idx, sid in enumerate(labels)}
        wgani_mat = [[0.0] * n for _ in range(n)]
        af_mat = [[0.0] * n for _ in range(n)]
        pair_details: Dict[Tuple[str, str], Tuple[float, float, float, float]] = {}
        for i in range(n):
            wgani_mat[i][i] = 100.0
            af_mat[i][i] = 100.0
            pair_details[(labels[i], labels[i])] = (100.0, 100.0, 100.0, 100.0)

        if out_tsv.is_file():
            with open(out_tsv, "r", encoding="utf-8", errors="replace") as fh:
                fh.readline()  # skip header
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 5:
                        continue
                    r_id = path_to_id.get(parts[0]) or path_to_id.get(Path(parts[0]).name)
                    q_id = path_to_id.get(parts[1]) or path_to_id.get(Path(parts[1]).name)
                    if not q_id or not r_id or q_id == r_id:
                        continue
                    try:
                        ani = float(parts[2])
                        af_r = float(parts[3])
                        af_q = float(parts[4])
                    except ValueError:
                        continue
                    la = max(1, lengths.get(q_id, 1))
                    lb = max(1, lengths.get(r_id, 1))
                    wg = round((ani * ((af_q / 100.0) * la + (af_r / 100.0) * lb)) / (la + lb), 2)
                    qi, ri = idx_map[q_id], idx_map[r_id]
                    wgani_mat[qi][ri] = wg
                    wgani_mat[ri][qi] = wg
                    af_mat[qi][ri] = round(af_q, 2)
                    af_mat[ri][qi] = round(af_r, 2)
                    pair_details[(q_id, r_id)] = (wg, round(ani, 2), round(af_q, 2), round(af_r, 2))
                    pair_details[(r_id, q_id)] = (wg, round(ani, 2), round(af_r, 2), round(af_q, 2))

        return labels, wgani_mat, af_mat, pair_details, desc.version, " ".join(cmd)

    def _run_fastani_matrix(
        self,
        labels: List[str],
        lengths: Dict[str, int],
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        safe_threads: int,
    ) -> Tuple[List[str], List[List[float]], List[List[float]], Dict[Tuple[str, str], Tuple[float, float, float, float]], str, str]:
        from src.assembly.env.wsl_manager import WSLManager

        desc = self.registry.get("fastani")
        list_file = work_dir / "fastani_inputs.txt"
        out_tsv = work_dir / "fastani_out.tsv"
        path_to_id: Dict[str, str] = {}
        with open(list_file, "w", encoding="utf-8", newline="\n") as fh:
            for sid in labels:
                wsl_p = WSLManager.to_wsl_path(str(genome_fastas[sid].resolve()))
                fh.write(wsl_p + "\n")
                path_to_id[wsl_p] = sid
                path_to_id[Path(wsl_p).name] = sid

        cmd = [
            desc.path,
            "--ql",
            WSLManager.to_wsl_path(str(list_file.resolve())),
            "--rl",
            WSLManager.to_wsl_path(str(list_file.resolve())),
            "-t",
            str(safe_threads),
            "--fragLen",
            "1000",
            "--minFraction",
            "0.1",
            "-o",
            WSLManager.to_wsl_path(str(out_tsv.resolve())),
        ]
        res = self.runner.run_wsl(cmd)
        if res.returncode != 0:
            raise PhyloError("FastANI 执行失败", detail=res.stderr[-800:])

        n = len(labels)
        raw_pairs: Dict[Tuple[str, str], Tuple[float, float]] = {}
        if out_tsv.is_file():
            with open(out_tsv, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 5:
                        continue
                    q_id = path_to_id.get(parts[0]) or path_to_id.get(Path(parts[0]).name)
                    r_id = path_to_id.get(parts[1]) or path_to_id.get(Path(parts[1]).name)
                    if not q_id or not r_id or q_id == r_id:
                        continue
                    try:
                        ani = float(parts[2])
                        mapped_frags = float(parts[3])
                        total_frags = max(1.0, float(parts[4]))
                        af_q = min(100.0, (mapped_frags / total_frags) * 100.0)
                    except ValueError:
                        continue
                    raw_pairs[(q_id, r_id)] = (ani, af_q)

        wgani_mat = [[0.0] * n for _ in range(n)]
        af_mat = [[0.0] * n for _ in range(n)]
        pair_details: Dict[Tuple[str, str], Tuple[float, float, float, float]] = {}
        for i in range(n):
            wgani_mat[i][i] = 100.0
            af_mat[i][i] = 100.0
            pair_details[(labels[i], labels[i])] = (100.0, 100.0, 100.0, 100.0)
            for j in range(i + 1, n):
                a, b = labels[i], labels[j]
                ani_ab, af_ab = raw_pairs.get((a, b), (0.0, 0.0))
                ani_ba, af_ba = raw_pairs.get((b, a), (ani_ab, af_ab))
                la, lb = max(1, lengths.get(a, 1)), max(1, lengths.get(b, 1))
                wg = round(
                    ((ani_ab * (af_ab / 100.0) * la) + (ani_ba * (af_ba / 100.0) * lb))
                    / (la + lb),
                    2,
                )
                aln_ani = round((ani_ab + ani_ba) / (2.0 if ani_ba > 0 else 1.0), 2)
                wgani_mat[i][j] = wgani_mat[j][i] = wg
                af_mat[i][j] = round(af_ab, 2)
                af_mat[j][i] = round(af_ba, 2)
                pair_details[(a, b)] = (wg, aln_ani, round(af_ab, 2), round(af_ba, 2))
                pair_details[(b, a)] = (wg, aln_ani, round(af_ba, 2), round(af_ab, 2))

        return labels, wgani_mat, af_mat, pair_details, desc.version, " ".join(cmd)

    def build_screen_result(
        self,
        query_ids: List[str],
        mash_hits_map: Dict[str, Tuple[float, float, Optional[InpharedRecord]]],
        matrix_labels: List[str],
        wgani_matrix: List[List[float]],
        af_matrix: List[List[float]],
        pair_details: Dict[Tuple[str, str], Tuple[float, float, float, float]],
        scope: DeliveryScopeConfig,
        engine_used: str,
        engine_version: str,
        command_preview: str,
    ) -> AniScreenResult:
        """汇总第 1 步预判结果、ICTV 阈值分级、模糊带警告与推荐外群。"""
        hits: List[AniHitRecord] = []

        # 读取全部相关元数据
        missing_accs = [lbl for lbl in matrix_labels if lbl not in query_ids and lbl not in mash_hits_map]
        extra_meta: Dict[str, InpharedRecord] = (
            self.index.get_by_accessions(missing_accs) if missing_accs and self.index.is_available() else {}
        )

        for lbl in matrix_labels:
            if lbl in query_ids:
                continue
            # 取对所有查询株的最大 wgANI
            best_tuple = (0.0, 0.0, 0.0, 0.0)
            for q in query_ids:
                cand = pair_details.get((q, lbl), (0.0, 0.0, 0.0, 0.0))
                if cand[0] >= best_tuple[0]:
                    best_tuple = cand
            wg_ani, aln_ani, af_q, af_r = best_tuple
            mash_d, mash_ani, meta = mash_hits_map.get(lbl, (None, None, extra_meta.get(lbl)))
            if wg_ani == 0.0 and mash_ani is not None:
                # 若尚未下载真实序列跑 BLASTn，保留 Mash 粗估仅作排序提示但标注 AF=0
                pass
            call, mosaic = classify_ictv_threshold(
                wg_ani,
                aln_ani,
                af_q,
                af_r,
                species_threshold=scope.ani_species_threshold,
                genus_threshold=scope.ani_genus_threshold,
            )
            hits.append(
                AniHitRecord(
                    accession=lbl,
                    description=meta.description if meta else lbl,
                    mash_distance=mash_d,
                    mash_ani=mash_ani,
                    wg_ani=wg_ani,
                    aligned_ani=aln_ani,
                    af_query=af_q,
                    af_ref=af_r,
                    genome_length=meta.genome_length if meta else 0,
                    gc_content=meta.gc_content if meta else 0.0,
                    host=meta.host if meta else "",
                    genus=meta.genus if meta else "",
                    subfamily=meta.subfamily if meta else "",
                    family=meta.family if meta else "",
                    order=meta.order_name if meta else "",
                    class_name=meta.class_name if meta else "",
                    realm=meta.realm if meta else "",
                    classification_call=call,  # type: ignore[arg-type]
                    mosaic_warning=mosaic,
                )
            )

        hits.sort(key=lambda h: (h.wg_ani, h.mash_ani or 0.0), reverse=True)

        candidate_genera: List[str] = []
        candidate_families: List[str] = []
        candidate_orders: List[str] = []
        host_hint = ""
        for h in hits[:15]:
            if h.genus and h.genus not in candidate_genera:
                candidate_genera.append(h.genus)
            if h.family and h.family not in candidate_families:
                candidate_families.append(h.family)
            if h.order and h.order not in candidate_orders:
                candidate_orders.append(h.order)
            if not host_hint and h.host:
                host_hint = h.host

        top_hit = hits[0] if hits else None
        warnings: List[str] = []
        ambiguous_zone = False
        if not top_hit:
            summary_call = "未在 INPHARED 参考库中命中显著相似基因组，疑似极远缘或全新高阶分类单元。"
            warnings.append("Mash 与 wgANI 均未发现近邻，建议补充本地参考基因组或采用全基因组蛋白质组树进行科/目级定位。")
        else:
            top_wg = top_hit.wg_ani
            if top_wg >= scope.ani_species_threshold:
                summary_call = (
                    f"最高 wgANI = {top_wg:.2f}% (对应 {top_hit.accession}"
                    + (f", 属 {top_hit.genus}" if top_hit.genus else "")
                    + ") >= 95% 种阈值：初步提示为已知种（或高度近缘株）。"
                )
            elif abs(top_wg - scope.ani_genus_threshold) <= 5.0:
                ambiguous_zone = True
                summary_call = (
                    f"最高 wgANI = {top_wg:.2f}% (对应 {top_hit.accession}"
                    + (f", 属 {top_hit.genus}" if top_hit.genus else "")
                    + ") 处于 65%-75% 属界模糊带：不可单凭数值武断定属，建议纳入邻近多属参考并重点核对 TerL 拓扑与外群。"
                )
                warnings.append("wgANI 落在 65%-75% 模糊带，已自动扩展参考集覆盖邻近属。")
            elif top_wg >= scope.ani_genus_threshold:
                summary_call = (
                    f"最高 wgANI = {top_wg:.2f}% (对应 {top_hit.accession}"
                    + (f", 属 {top_hit.genus}" if top_hit.genus else "")
                    + ") 处于 70%-95% 区间：初步提示同属候选新种（仍需核对比对覆盖度 AF 与系统发育自洽性）。"
                )
            else:
                summary_call = (
                    f"最高 wgANI = {top_wg:.2f}% (< 70% 属阈值"
                    + (f", 最近为 {top_hit.genus or top_hit.accession}" if top_hit else "")
                    + ")：初步提示候选新属，需结合 TerL 系统发育分支与外群进一步确认。"
                )

            if any(h.mosaic_warning for h in hits[:5]):
                warnings.append(
                    "检测到高局部一致度但覆盖度偏低 (AF < 50% & aligned ANI >= 80%) 的近邻，提示可能存在基因组嵌合（mosaicism），请谨慎解读 wgANI 数值。"
                )

        # 推荐外群（遵循 scope.outgroup_count 可调数量）
        outgroup_recs = (
            self.index.find_outgroup_candidates(
                target_genera=candidate_genera[: max(1, scope.max_target_genera)],
                target_families=candidate_families[:2],
                target_orders=candidate_orders[:2],
                host_hint=host_hint,
                exclude_accessions=[h.accession for h in hits[:15]],
                limit=scope.outgroup_count,
            )
            if scope.outgroup_count > 0
            else []
        )

        return AniScreenResult(
            query_ids=query_ids,
            engine_used=engine_used,
            engine_version=engine_version,
            command_preview=command_preview,
            top_hits=hits,
            matrix_labels=matrix_labels,
            wgani_matrix=wgani_matrix,
            af_matrix=af_matrix,
            candidate_genera=candidate_genera,
            candidate_families=candidate_families,
            summary_call=summary_call,
            ambiguous_zone=ambiguous_zone,
            warnings=warnings,
            recommended_outgroup_accessions=[r.accession for r in outgroup_recs],
        )
