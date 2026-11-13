# -*- coding: utf-8 -*-
"""
V4 离线蛋白语义软标签标注、训练集净化与高难短板样本挖掘（严格防泄露）

功能：
1. mine_hard_transposase_and_archaeal_windows：严格仅从 negative_splits.json 的 train 分片中
   提取全部古菌病毒（Sulfolobus / Acidianus / Fuselloviridae 等）多尺度切片，以及在
   prophage_masks 缓冲外孤立存在的细菌/质粒转座酶（IS/transposase）短岛窗口；
2. annotate_contigs_with_diamond：统一用 Pyrodigal(meta=True) 提取去重 contig 的 ORF，
   调用 WSL DIAMOND (或测试注入 hit_fetcher) 批检索本地 phage_refseq_prot.dmnd，
   并映射为每个训练窗口的软语义目标 [has_viral_hallmark, is_transposase_risk] 与净化掩蔽标签；
3. ensure_v4_orf_tokens：复用 Expert C 的 ORF Token 提取器，优先链接/复制已有缓存，
   仅对新增 V3/V4 分片多核增量提取 (N, 36, 30) 基因拓扑矩阵。
"""
import concurrent.futures
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ...utils.phage_dataset.cleaner import merge_intervals
from ..experts.expert_c_orf import extract_orf_tensors_for_part
from ..features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows
from ..inference.protein_gate import _classify_hit_title
from ..teachers.checkv_teacher import to_wsl_path
from .feature_dataset import iter_fasta, load_split_arrays

logger = logging.getLogger("phage_discovery.data.v4_semantic_prep")

ARCHAEAL_VIRUS_RE = re.compile(
    r"(?:sulfolobus|fusellovir|acidianus|bicaudavir|ampullavir|globulovir|guttavir|"
    r"lipothrixvir|rudivir|turrivir|halovirus|haloarchaeal|thermoprote|pyrobaculum|metallosph)",
    re.IGNORECASE,
)

TRANSPOSASE_SQL_RE = re.compile(
    r"(?:transposase|transposon|insertion\s+sequence|is\d+\s+family)",
    re.IGNORECASE,
)

INTEGRASE_SEM_RE = re.compile(
    r"\b(?:integrase|excisionase|recombinase|site[- ]specific\s+recombinase|resolvase)\b",
    re.IGNORECASE,
)

TAIL_LYSIS_SEM_RE = re.compile(
    r"\b(?:capsid|coat\s+protein|portal|terminase|terl|ters|tail|baseplate|"
    r"tape\s+measure|holin|endolysin|lysin|spanin|sheath|neck\s+protein|collar|lysis)\b",
    re.IGNORECASE,
)


def _extract_contig_orfs_raw(item: Tuple[str, str]) -> Tuple[str, List[Tuple[int, int, str]]]:
    """多核工作函数：提取单条 contig 上长度 >= 20 aa 的 Pyrodigal ORF 坐标与序列。"""
    import pyrodigal

    cid, seq = item
    out: List[Tuple[int, int, str]] = []
    if len(seq) < 200:
        return cid, out
    finder = pyrodigal.GeneFinder(meta=True, mask=True)
    genes = finder.find_genes(seq.upper().encode("ascii", errors="ignore"))
    for gene in genes:
        aa = gene.translate(include_stop=False)
        if len(aa) >= 20:
            s0 = max(0, gene.begin - 1)
            e0 = max(s0 + 1, gene.end)
            out.append((s0, e0, aa))
    return cid, out


def run_batch_diamond_blastp(
    orf_records: Sequence[Tuple[str, str]],
    dmnd_db: Path,
    *,
    evalue: float = 1e-5,
    min_qcov: float = 35.0,
    threads: Optional[int] = None,
) -> Dict[str, Tuple[float, str]]:
    """通过 WSL DIAMOND blastp 对全量去重训练 ORF 执行多线程蛋白语义检索。"""
    if not orf_records:
        return {}
    db_path = Path(dmnd_db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"DIAMOND 数据库不存在: {db_path}")

    cpu_cnt = os.cpu_count() or 4
    n_threads = threads if threads is not None else max(1, cpu_cnt - 2)
    best_hits: Dict[str, Tuple[float, str]] = {}

    with tempfile.TemporaryDirectory(prefix="phage_v4_dmnd_") as tmpdir:
        tmp_root = Path(tmpdir)
        faa_path = tmp_root / "train_orfs.faa"
        out_path = tmp_root / "dmnd_hits.tsv"
        with open(faa_path, "w", encoding="utf-8") as fh:
            for qid, aa in orf_records:
                fh.write(f">{qid}\n{aa}\n")

        cmd = [
            "wsl",
            "diamond",
            "blastp",
            "-d",
            to_wsl_path(db_path),
            "-q",
            to_wsl_path(faa_path),
            "-o",
            to_wsl_path(out_path),
            "--outfmt",
            "6",
            "qseqid",
            "bitscore",
            "stitle",
            "-e",
            str(evalue),
            "--query-cover",
            str(min_qcov),
            "-k",
            "3",
            "--threads",
            str(n_threads),
            "--sensitive",
            "--quiet",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"WSL diamond blastp 失败 (exit={proc.returncode}): {proc.stderr.strip()}")

        if out_path.exists():
            with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.rstrip("\r\n").split("\t", 2)
                    if len(parts) < 3:
                        continue
                    qid = parts[0].strip()
                    try:
                        bitscore = float(parts[1])
                    except ValueError:
                        continue
                    stitle = parts[2].strip()
                    prev = best_hits.get(qid)
                    if prev is None or bitscore > prev[0]:
                        best_hits[qid] = (bitscore, stitle)
    return best_hits


def _build_hard_v4_records(
    neg_dir: Path,
    splits_json: Path,
    max_transposase_loci: int = 900,
    flank_buffer_bp: int = 15000,
    seed: int = 42,
) -> List[Tuple[str, str]]:
    """
    严格仅从 negative_splits.json 中 split=='train' 的负样本库截取：
    1. 全部古菌病毒全序列（连带多尺度短片段切分）；
    2. 远离 prophage_masks 的纯细菌/质粒 IS/转座酶短岛（含 5kb 及 800bp 局部窗口）。
    """
    rng = np.random.default_rng(seed)
    neg_root = Path(neg_dir).resolve()
    splits: Dict[str, str] = json.loads(Path(splits_json).read_text(encoding="utf-8"))
    train_accs = {acc for acc, sp in splits.items() if sp == "train"}
    non_train_accs = {acc for acc, sp in splits.items() if sp != "train"}
    if not train_accs:
        raise ValueError(f"negative_splits.json 中未找到 train 分片: {splits_json}")

    db_path = neg_root / "index" / "negative_index.sqlite"
    records: List[Tuple[str, str]] = []

    with closing(sqlite3.connect(db_path)) as conn:
        genomes = conn.execute(
            "SELECT accession, negative_category, organism, length_bp, fasta_relpath FROM genomes WHERE is_valid_negative=1"
        ).fetchall()

        mask_map: Dict[str, List[Tuple[int, int]]] = {}
        for acc, s_pos, e_pos in conn.execute("SELECT accession, start_pos, end_pos FROM prophage_masks").fetchall():
            if acc in non_train_accs:
                continue
            mask_map.setdefault(acc, []).append((int(s_pos), int(e_pos)))

        for acc in list(mask_map.keys()):
            mask_map[acc] = merge_intervals(mask_map[acc], flank_bp=flank_buffer_bp)

        archaeal_entries = []
        host_fasta_map: Dict[str, Path] = {}
        for acc, cat, org, lbp, relp in genomes:
            if acc not in train_accs:
                continue
            fa_p = neg_root / relp if relp else neg_root / "fasta" / f"{acc}.fasta"
            if not fa_p.exists():
                continue
            if cat == "non_phage_virus" and ARCHAEAL_VIRUS_RE.search(org or ""):
                archaeal_entries.append((acc, fa_p))
            elif cat in ("bacterial_chromosome", "plasmid"):
                host_fasta_map[acc] = fa_p

        # 1. 全量古菌病毒 + 3000bp / 800bp 短片采样（零泄露）
        for acc, fa_p in archaeal_entries:
            seqs = [s for _, s in iter_fasta(fa_p)]
            if not seqs:
                continue
            full_seq = "".join(seqs).upper()
            if len(full_seq) >= 1000:
                records.append((f"HARDV4_ARCH_{acc}_FULL", full_seq))
                for k_idx in range(min(8, max(2, len(full_seq) // 5000))):
                    slen = int(rng.choice([800, 1000, 3000]))
                    if len(full_seq) > slen:
                        st = int(rng.integers(0, len(full_seq) - slen))
                        records.append((f"HARDV4_ARCH_{acc}_S{slen}_{k_idx}", full_seq[st:st + slen]))

        # 2. 孤立转座酶短岛：避开 prophage_masks 与相邻噬菌体，仅采纯细菌/质粒 IS 位点
        cand_loci: List[Tuple[str, int, int]] = []
        cds_rows = conn.execute(
            "SELECT accession, start_pos, end_pos, product FROM cds_features"
        ).fetchall()
        for acc, s_pos, e_pos, prod in cds_rows:
            if acc not in host_fasta_map or not prod:
                continue
            if not TRANSPOSASE_SQL_RE.search(prod):
                continue
            s0 = max(0, int(s_pos) - 1)
            e0 = int(e_pos)
            blocked = any(not (e0 <= ms or s0 >= me) for ms, me in mask_map.get(acc, []))
            if not blocked:
                cand_loci.append((acc, s0, e0))

        rng.shuffle(cand_loci)
        chosen_by_acc: Dict[str, List[Tuple[int, int]]] = {}
        kept_cnt = 0
        for acc, s0, e0 in cand_loci:
            if kept_cnt >= max_transposase_loci:
                break
            prev_list = chosen_by_acc.setdefault(acc, [])
            if any(abs((s0 + e0) // 2 - (ps + pe) // 2) < 6000 for ps, pe in prev_list):
                continue
            prev_list.append((s0, e0))
            kept_cnt += 1

        for acc, loci in chosen_by_acc.items():
            fa_p = host_fasta_map[acc]
            full_seq = "".join(s for _, s in iter_fasta(fa_p)).upper()
            n_seq = len(full_seq)
            for li, (s0, e0) in enumerate(loci):
                mid = (s0 + e0) // 2
                w5_s = max(0, min(n_seq - 5000, mid - 2500))
                w5_e = min(n_seq, w5_s + 5000)
                if w5_e - w5_s >= 3000:
                    records.append((f"HARDV4_IS_{acc}_{li}_5K", full_seq[w5_s:w5_e]))
                if li % 3 == 0 and n_seq >= 900:
                    slen = int(rng.choice([800, 1000]))
                    w1_s = max(0, min(n_seq - slen, mid - slen // 2))
                    records.append((f"HARDV4_IS_{acc}_{li}_S{slen}", full_seq[w1_s:w1_s + slen]))

    # 最后严防死守：任何一条产出 ID 都禁止包含非 train accession
    for rec_id, _ in records:
        for acc in non_train_accs:
            if acc in rec_id:
                raise RuntimeError(f"防泄露自检失败: 发现非 train 序列 {acc} 混入 {rec_id}")

    logger.info(f"构建 hard_v4 序列片段: 共 {len(records)} 条 (全部严格来自 v1 train 负样本)")
    return records


def _extract_hard_v4_worker(args: Tuple[str, str]) -> Dict[str, Any]:
    cid, seq = args
    wsize = 5000 if len(seq) >= 5000 else len(seq)
    step = 2500 if "_FULL" in cid else wsize
    res = extract_contig_windows(cid, seq, win_size=wsize, step_size=step, truth_regions=None)
    n = len(res["starts"])
    res["labels"] = np.zeros(n, dtype=np.int8)
    res["overlap"] = np.zeros(n, dtype=np.float32)
    res["sub_mask"] = np.zeros((n, SUB_BINS), dtype=np.float32)
    return res


def mine_hard_transposase_and_archaeal_windows(
    neg_dir: Path,
    splits_json: Path,
    out_fasta: Path,
    out_npz: Path,
    *,
    max_transposase_loci: int = 900,
    workers: Optional[int] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """生成并提取 V4 专项难负样本分片 (train_hard_v4.npz + ext_hard_v4.fna)。"""
    records = _build_hard_v4_records(
        neg_dir=neg_dir, splits_json=splits_json, max_transposase_loci=max_transposase_loci, seed=seed,
    )
    out_fasta = Path(out_fasta).resolve()
    out_npz = Path(out_npz).resolve()
    out_fasta.parent.mkdir(parents=True, exist_ok=True)
    out_npz.parent.mkdir(parents=True, exist_ok=True)

    tmp_fa = out_fasta.with_name(f".{out_fasta.stem}.tmp.fna")
    with open(tmp_fa, "w", encoding="utf-8") as fh:
        for cid, seq in records:
            fh.write(f">{cid}\n{seq}\n")
    tmp_fa.replace(out_fasta)

    cpu_cnt = os.cpu_count() or 4
    n_workers = workers if workers is not None else max(1, cpu_cnt - 2)
    feats_l, lbl_l, ov_l, sub_l, cid_l, st_l, ed_l = [], [], [], [], [], [], []

    def _collect(item: Dict[str, Any]):
        if len(item["starts"]) == 0:
            return
        feats_l.append(item["features"])
        lbl_l.append(item["labels"])
        ov_l.append(item["overlap"])
        sub_l.append(item["sub_mask"])
        cid_str = str(item["contig_id"])
        cid_l.append(np.full(len(item["starts"]), cid_str, dtype=f"<U{max(1, len(cid_str))}"))
        st_l.append(item["starts"])
        ed_l.append(item["ends"])

    if n_workers > 1 and len(records) > 4:
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            for item in ex.map(_extract_hard_v4_worker, records, chunksize=8):
                _collect(item)
    else:
        for rec in records:
            _collect(_extract_hard_v4_worker(rec))

    if not feats_l:
        raise RuntimeError("hard_v4 未提取出任何有效窗口特征")

    total_rows = int(sum(len(x) for x in lbl_l))
    tmp_npz = out_npz.with_name(f".{out_npz.stem}.tmp.npz")
    np.savez_compressed(
        tmp_npz,
        feature_names=np.asarray(FEATURE_NAMES),
        features=np.concatenate(feats_l).astype(np.float32),
        labels=np.concatenate(lbl_l).astype(np.int8),
        overlap=np.concatenate(ov_l).astype(np.float32),
        sub_mask=np.concatenate(sub_l).astype(np.float32),
        contig_ids=np.concatenate(cid_l),
        starts=np.concatenate(st_l).astype(np.int64),
        ends=np.concatenate(ed_l).astype(np.int64),
        source=np.full(total_rows, 3, dtype=np.int8),
    )
    tmp_npz.replace(out_npz)
    logger.info(f"hard_v4 特征提取完成: {out_npz} ({total_rows} 行全负样本)")
    return {"fasta_path": str(out_fasta), "npz_path": str(out_npz), "records": len(records), "rows": total_rows}


def annotate_train_semantics_with_diamond(
    part_specs: Sequence[Tuple[str, Path, Path]],
    dmnd_db: Optional[Path] = None,
    *,
    clean_negative_parts: Sequence[str] = ("chimeras", "hard_neg", "mined", "ext_mined", "hard_v4"),
    workers: Optional[int] = None,
    hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    为每个训练集分片离线生成蛋白语义辅助监督目标 (`train_{part}_semantic.npz`)，
    并清洗阴性分片中隐含漏掩蔽真实前噬菌体的矛盾标签（标记 clean_labels=-1）。
    part_specs: [(part_name, npz_path, fasta_path), ...]
    """
    unique_contigs: Dict[str, str] = {}
    part_arrays: Dict[str, Dict[str, np.ndarray]] = {}
    part_npz_paths: Dict[str, Path] = {}

    for pname, npz_p, fa_p in part_specs:
        npz_path = Path(npz_p).resolve()
        fa_path = Path(fa_p).resolve()
        if not npz_path.exists() or not fa_path.exists():
            continue
        with np.load(npz_path, allow_pickle=True) as data:
            arrs = {k: data[k] for k in data.files}
        needed_cids = {str(c) for c in arrs["contig_ids"]}
        for cid, seq in iter_fasta(fa_path):
            if cid in needed_cids and cid not in unique_contigs:
                unique_contigs[cid] = seq
        part_arrays[pname] = arrs
        part_npz_paths[pname] = npz_path

    cpu_cnt = os.cpu_count() or 4
    n_workers = workers if workers is not None else max(1, cpu_cnt - 2)
    contig_orfs: Dict[str, List[Tuple[int, int, str]]] = {}
    items = list(unique_contigs.items())
    if n_workers > 1 and len(items) > 4:
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            for cid, orfs in ex.map(_extract_contig_orfs_raw, items, chunksize=8):
                contig_orfs[cid] = orfs
    else:
        for it in items:
            cid, orfs = _extract_contig_orfs_raw(it)
            contig_orfs[cid] = orfs

    orf_records: List[Tuple[str, str]] = []
    for cid, orfs in contig_orfs.items():
        for oi, (_, _, aa) in enumerate(orfs):
            orf_records.append((f"{cid}__orf{oi}", aa))

    if hit_fetcher is not None:
        best_hits = hit_fetcher(orf_records)
    elif dmnd_db is not None:
        best_hits = run_batch_diamond_blastp(orf_records, dmnd_db=dmnd_db, threads=n_workers)
    else:
        best_hits = {}

    contig_orf_cls: Dict[str, List[Tuple[int, int, str, str]]] = {}
    for cid, orfs in contig_orfs.items():
        lst = []
        for oi, (s0, e0, _) in enumerate(orfs):
            hit = best_hits.get(f"{cid}__orf{oi}")
            title = hit[1] if hit is not None else ""
            cls = _classify_hit_title(title) if hit is not None else "no_hit"
            lst.append((s0, e0, cls, title))
        lst.sort(key=lambda t: t[0])
        contig_orf_cls[cid] = lst

    clean_neg_set = set(clean_negative_parts)
    summary: Dict[str, Dict[str, Any]] = {}

    for pname, arrs in part_arrays.items():
        cids = arrs["contig_ids"]
        starts = arrs["starts"]
        ends = arrs["ends"]
        labels = arrs["labels"].astype(np.int8)
        n = len(labels)

        # 4维语义软目标: [sem_phage_hallmark, sem_integrase, sem_transp, sem_tail_lysis]
        sem_targets = np.zeros((n, 4), dtype=np.float32)
        sem_valid_mask = np.ones(n, dtype=np.float32)
        hallmark_cnts = np.zeros(n, dtype=np.int16)
        transp_cnts = np.zeros(n, dtype=np.int16)
        clean_labels = labels.copy()
        cleaned_neg_cnt = 0

        for idx in range(n):
            cid = str(cids[idx])
            ws = int(starts[idx])
            we = int(ends[idx])
            h_cnt = 0
            t_cnt = 0
            int_cnt = 0
            tl_cnt = 0
            other_phage_cnt = 0
            for gs, ge, cls, title in contig_orf_cls.get(cid, ()):
                if ge <= ws:
                    continue
                if gs >= we:
                    break
                mid = (gs + ge) // 2
                if ws <= mid < we:
                    if cls == "hallmark":
                        h_cnt += 1
                    elif cls == "transposase":
                        t_cnt += 1
                    elif cls == "non_amg_phage":
                        other_phage_cnt += 1
                    if title and INTEGRASE_SEM_RE.search(title):
                        int_cnt += 1
                    if title and TAIL_LYSIS_SEM_RE.search(title):
                        tl_cnt += 1

            hallmark_cnts[idx] = h_cnt
            transp_cnts[idx] = t_cnt
            sem_targets[idx, 0] = min(1.0, 0.65 if h_cnt == 1 else (1.0 if h_cnt >= 2 else 0.0))
            sem_targets[idx, 1] = 1.0 if int_cnt >= 1 else 0.0
            if t_cnt >= 1 and h_cnt == 0 and other_phage_cnt == 0:
                sem_targets[idx, 2] = 1.0
            elif t_cnt >= 2 and h_cnt == 0:
                sem_targets[idx, 2] = 0.5
            if tl_cnt >= 2 or other_phage_cnt >= 2:
                sem_targets[idx, 3] = 1.0
            elif tl_cnt == 1 or other_phage_cnt == 1:
                sem_targets[idx, 3] = 0.6

            # 仅清洗细菌/嵌合/挖掘库中标签为 0 但实际富含核心噬菌体基因的矛盾负样本（不动古菌/非噬菌体病毒）
            is_arch_or_npv = cid.startswith("HARDV4_ARCH_")
            if pname in clean_neg_set and not is_arch_or_npv and labels[idx] == 0:
                if h_cnt >= 2 or (h_cnt >= 1 and other_phage_cnt >= 2):
                    clean_labels[idx] = -1
                    cleaned_neg_cnt += 1

        npz_p = part_npz_paths[pname]
        sem_path = npz_p.with_name(f"train_{pname}_semantic.npz")
        tmp_sem = sem_path.with_name(f".{sem_path.stem}.tmp.npz")
        np.savez_compressed(
            tmp_sem,
            sem_targets=sem_targets,
            sem_valid_mask=sem_valid_mask,
            hallmark_counts=hallmark_cnts,
            transposase_counts=transp_cnts,
            clean_labels=clean_labels,
        )
        tmp_sem.replace(sem_path)

        summary[pname] = {
            "rows": n,
            "hallmark_pos_windows": int(np.sum(hallmark_cnts > 0)),
            "integrase_windows": int(np.sum(sem_targets[:, 1] > 0.5)),
            "transposase_risk_windows": int(np.sum(sem_targets[:, 2] > 0.5)),
            "tail_lysis_windows": int(np.sum(sem_targets[:, 3] > 0.5)),
            "cleaned_contradictory_negatives": cleaned_neg_cnt,
            "semantic_npz": str(sem_path),
        }
        logger.info(f"语义标注完成 train_{pname}: {summary[pname]}")

    return summary


def ensure_v4_orf_tokens(
    feat_dir: Path,
    part_fastas: Sequence[Tuple[str, Path]],
    *,
    legacy_cache_dirs: Sequence[Path] = (),
    workers: Optional[int] = None,
) -> Dict[str, str]:
    """
    确保 feat_dir 下各分片均拥有与 train_{part}.npz 严格等长的 ORF Token 缓存
    (train_{part}_orf_tokens_v2.npz)。行数完全一致时可直接复用旧缓存。
    """
    root = Path(feat_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    out_paths: Dict[str, str] = {}

    for pname, fa_p in part_fastas:
        npz_p = root / f"train_{pname}.npz"
        if not npz_p.exists() or not Path(fa_p).exists():
            continue
        arrs = load_split_arrays(root, "train", parts=(pname,))
        target_rows = len(arrs["labels"])
        dst_cache = root / f"train_{pname}_orf_tokens_v2.npz"

        reused = False
        if dst_cache.exists():
            with np.load(dst_cache) as d:
                if len(d["counts"]) == target_rows:
                    reused = True

        if not reused:
            for leg in legacy_cache_dirs:
                cand = Path(leg) / f"train_{pname}_orf_tokens_v2.npz"
                if cand.exists():
                    with np.load(cand) as d:
                        if len(d["counts"]) == target_rows:
                            shutil.copy2(cand, dst_cache)
                            reused = True
                            break

        if not reused:
            tokens, counts = extract_orf_tensors_for_part(Path(fa_p), arrs, workers=workers)
            tmp = dst_cache.with_name(f".{dst_cache.stem}.tmp.npz")
            np.savez_compressed(tmp, tokens=tokens, counts=counts)
            tmp.replace(dst_cache)

        out_paths[pname] = str(dst_cache)
    return out_paths
