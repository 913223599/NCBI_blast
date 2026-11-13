# -*- coding: utf-8 -*-
"""
噬菌体训练集预处理引擎（多核并行分片特征提取 + GPU 加速聚类去冗余 + 无泄露数据集划分）

设计要点：
1. 分片落盘与 Checkpoint 断点保护：按批次并行解析 GBK/FASTA，即时将 ORF 拓扑序列与 5kb 滑窗特征分片落盘；
2. 多核并行（保留 2 个 CPU 核心）：高效计算反向互补规范化 4-mer 频谱（136 维）、基因密度、同向链连续度及功能类别标记；
3. GPU 加速聚类（严格控制 Batch Size 与 torch.cuda.empty_cache()）：基于 4-mer 特征向量与长度一致性做相似度聚类，
   按 Cluster 级别进行 Train/Val/Test (8:1:1) 分层切分，彻底防止同源序列数据泄露。
"""
import argparse
import concurrent.futures
import csv
import json
import logging
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from Bio import SeqIO

logger = logging.getLogger("utils.phage_dataset.preprocessor")

# 预构建 256 -> 136 维规范化反向互补 4-mer 查找表
def _build_canonical_4mer_lut() -> Tuple[np.ndarray, List[str]]:
    bases = "ACGT"
    comp_map = {0: 3, 1: 2, 2: 1, 3: 0}
    canon_to_idx: Dict[int, int] = {}
    lut = np.full(256, -1, dtype=np.int16)
    names: List[str] = []

    for code in range(256):
        b0 = (code >> 6) & 3
        b1 = (code >> 4) & 3
        b2 = (code >> 2) & 3
        b3 = code & 3
        rc = (comp_map[b3] << 6) | (comp_map[b2] << 4) | (comp_map[b1] << 2) | comp_map[b0]
        canon = min(code, rc)
        if canon not in canon_to_idx:
            canon_to_idx[canon] = len(names)
            names.append(bases[(canon >> 6) & 3] + bases[(canon >> 4) & 3] + bases[(canon >> 2) & 3] + bases[canon & 3])
        lut[code] = canon_to_idx[canon]
    return lut, names


_CANON_4MER_LUT, CANONICAL_4MER_NAMES = _build_canonical_4mer_lut()
_BASE_TO_INT = np.full(256, -1, dtype=np.int16)
_BASE_TO_INT[ord("A")] = 0
_BASE_TO_INT[ord("a")] = 0
_BASE_TO_INT[ord("C")] = 1
_BASE_TO_INT[ord("c")] = 1
_BASE_TO_INT[ord("G")] = 2
_BASE_TO_INT[ord("g")] = 2
_BASE_TO_INT[ord("T")] = 3
_BASE_TO_INT[ord("t")] = 3

# 8 类噬菌体核心功能类别 ID 映射（供 ORF 序列模型使用）
FUNC_CATEGORIES: List[Tuple[int, str, re.Pattern]] = [
    (1, "capsid", re.compile(r"\b(?:major\s+capsid|capsid|coat\s+protein|scaffold)\b", re.IGNORECASE)),
    (2, "tail", re.compile(r"\b(?:tail\s+fiber|tail\s+fibre|tailspike|tape\s+measure|baseplate|tail\s+sheath|tail\s+protein)\b", re.IGNORECASE)),
    (3, "terminase_portal", re.compile(r"\b(?:terminase|terl|ters|portal|head[- ]tail|connector|packaging)\b", re.IGNORECASE)),
    (4, "lysin_holin", re.compile(r"\b(?:endolysin|lysin|holin|muramidase|spanin|lysis)\b", re.IGNORECASE)),
    (5, "integrase_recombinase", re.compile(r"\b(?:integrase|excisionase|recombinase|resolvase|transposase|repressor)\b", re.IGNORECASE)),
    (6, "replication", re.compile(r"\b(?:polymerase|helicase|primase|replicase|replication|single[- ]stranded|exonuclease|endonuclease)\b", re.IGNORECASE)),
    (7, "hypothetical", re.compile(r"\b(?:hypothetical|uncharacterized|unknown\s+function|duf\d+)\b", re.IGNORECASE)),
]


def _classify_product_func_id(product: str) -> int:
    for fid, _, pat in FUNC_CATEGORIES:
        if pat.search(product):
            return fid
    return 8  # other_annotated


def compute_canonical_4mer_freq(seq_str: str) -> np.ndarray:
    """向量化计算 136 维反向互补规范化 4-mer 频率向量（自动跳过含 N/简并碱基的 4-mer）。"""
    arr = np.frombuffer(seq_str.encode("ascii", errors="replace"), dtype=np.uint8)
    mapped = _BASE_TO_INT[arr]
    n = len(mapped)
    if n < 4:
        return np.zeros(136, dtype=np.float32)

    b0 = mapped[:-3]
    b1 = mapped[1:-2]
    b2 = mapped[2:-1]
    b3 = mapped[3:]
    valid = (b0 >= 0) & (b1 >= 0) & (b2 >= 0) & (b3 >= 0)
    if not np.any(valid):
        return np.zeros(136, dtype=np.float32)

    codes = (b0[valid] << 6) | (b1[valid] << 4) | (b2[valid] << 2) | b3[valid]
    canon_idx = _CANON_4MER_LUT[codes]
    counts = np.bincount(canon_idx, minlength=136).astype(np.float32)
    total = float(counts.sum())
    if total > 0:
        counts /= total
    return counts


def _extract_single_genome_features(args: Tuple[str, str, str, str, int, int, int]) -> Optional[Dict[str, Any]]:
    """
    解析单株样本 GBK 并提取：
    - 全长 136 维 4-mer 特征 + 基因结构统计；
    - 有序 ORF 拓扑特征序列；
    - 滑窗切片（默认 5kb / 步长 2.5kb）特征。
    """
    acc, gbk_path_str, tax_group, host, has_int, win_size, win_step = args
    gbk_path = Path(gbk_path_str)
    if not gbk_path.exists():
        return None

    try:
        with open(gbk_path, "r", encoding="utf-8") as fh:
            rec = SeqIO.read(fh, "genbank")
    except Exception:
        return None

    seq_str = str(rec.seq).upper()
    seq_len = len(seq_str)
    if seq_len == 0:
        return None

    kmer_vec = compute_canonical_4mer_freq(seq_str)
    gc_percent = round(((seq_str.count("G") + seq_str.count("C")) / seq_len) * 100.0, 2)

    # 提取有序 CDS / ORF 特征
    raw_cds: List[Tuple[int, int, int, int, str]] = []
    for feat in rec.features:
        if feat.type != "CDS" or not feat.location:
            continue
        start = int(feat.location.start)
        end = int(feat.location.end)
        strand = int(feat.location.strand or 1)
        product = str((feat.qualifiers.get("product") or ["hypothetical protein"])[0])
        func_id = _classify_product_func_id(product)
        raw_cds.append((start, end, strand, func_id, product))

    raw_cds.sort(key=lambda x: (x[0], x[1]))

    orf_seq: List[List[Any]] = []
    covered = 0
    last_end = 0
    strand_switches = 0
    cur_run = 0
    max_run = 0
    prev_strand = 0
    func_counts = Counter()

    for idx, (s, e, st, fid, _) in enumerate(raw_cds):
        cds_len = max(1, e - s)
        sub_seq = seq_str[max(0, s):min(seq_len, e)]
        cds_gc = round(((sub_seq.count("G") + sub_seq.count("C")) / len(sub_seq)), 4) if sub_seq else 0.0
        gap = s - raw_cds[idx - 1][1] if idx > 0 else s
        orf_seq.append([s, e, st, cds_len, cds_gc, fid, gap])

        func_counts[fid] += 1
        if s > last_end:
            covered += max(0, e - s)
            last_end = e
        elif e > last_end:
            covered += e - last_end
            last_end = e

        if prev_strand != 0 and st != prev_strand:
            strand_switches += 1
            cur_run = 1
        else:
            cur_run += 1
        max_run = max(max_run, cur_run)
        prev_strand = st

    cds_cnt = len(raw_cds)
    coding_density = round(min(1.0, covered / seq_len), 4)
    cds_per_kb = round((cds_cnt * 1000.0) / seq_len, 4)
    mean_cds_len = round(sum(e - s for s, e, _, _, _ in raw_cds) / cds_cnt, 1) if cds_cnt > 0 else 0.0
    switch_rate = round(strand_switches / max(1, cds_cnt - 1), 4) if cds_cnt > 1 else 0.0

    # 生成滑窗特征切片（用于窗口分类/粗定位训练）
    windows: List[Dict[str, Any]] = []
    if seq_len <= win_size:
        win_starts = [0]
    else:
        win_starts = list(range(0, seq_len - win_size + 1, win_step))
        if win_starts[-1] + win_size < seq_len:
            win_starts.append(seq_len - win_size)

    for w_idx, ws in enumerate(win_starts):
        we = min(seq_len, ws + win_size)
        w_seq = seq_str[ws:we]
        w_len = max(1, len(w_seq))
        w_gc = round(((w_seq.count("G") + w_seq.count("C")) / w_len) * 100.0, 2)
        overlap_cds = [c for c in raw_cds if c[1] > ws and c[0] < we]
        w_cds_cnt = len(overlap_cds)
        plus_cnt = sum(1 for c in overlap_cds if c[2] > 0)
        w_strand_bias = round(abs(2 * plus_cnt - w_cds_cnt) / w_cds_cnt, 3) if w_cds_cnt > 0 else 0.0
        w_markers = sum(1 for c in overlap_cds if c[3] in (1, 2, 3, 4, 5))
        windows.append({
            "acc": acc,
            "win_id": w_idx,
            "start": ws,
            "end": we,
            "len": w_len,
            "gc": w_gc,
            "cds_cnt": w_cds_cnt,
            "strand_bias": w_strand_bias,
            "marker_cds": w_markers,
        })

    return {
        "accession": acc,
        "tax_group": tax_group,
        "host": host,
        "has_integrase": has_int,
        "length_bp": seq_len,
        "gc_percent": gc_percent,
        "cds_count": cds_cnt,
        "cds_per_kb": cds_per_kb,
        "coding_density": coding_density,
        "mean_cds_len_bp": mean_cds_len,
        "strand_switch_rate": switch_rate,
        "max_same_strand_run": max_run,
        "func_capsid_cnt": func_counts.get(1, 0),
        "func_tail_cnt": func_counts.get(2, 0),
        "func_term_cnt": func_counts.get(3, 0),
        "func_lysin_cnt": func_counts.get(4, 0),
        "func_int_cnt": func_counts.get(5, 0),
        "func_rep_cnt": func_counts.get(6, 0),
        "func_hypo_cnt": func_counts.get(7, 0),
        "window_count": len(windows),
        "kmer4": kmer_vec.tolist(),
        "orf_seq": orf_seq,
        "windows": windows,
    }


def _cluster_genomes_gpu_or_cpu(
    accessions: List[str],
    lengths: List[int],
    kmer_matrix: np.ndarray,
    sim_threshold: float = 0.994,
    min_len_ratio: float = 0.85,
) -> Tuple[List[str], str]:
    """
    利用 PyTorch CUDA（不可用时降级 CPU）执行 Greedy Centroid 中心聚类去冗余（类似 CD-HIT 策略），
    避免单连锁传递合并效应；严格控制 GPU 内存并在结束前清理显存（torch.cuda.empty_cache()）。
    """
    n = len(accessions)
    if n == 0:
        return [], "none"

    # 按序列长度降序排列作为贪心代表中心顺序
    order = sorted(range(n), key=lambda idx: (-lengths[idx], accessions[idx]))
    inv_order = [0] * n
    for pos, orig_idx in enumerate(order):
        inv_order[orig_idx] = pos

    kmer_ord = kmer_matrix[order].astype(np.float32)
    len_ord = np.asarray([lengths[i] for i in order], dtype=np.float32)
    cluster_ids_ord = [""] * n
    device_used = "cpu_numpy"
    next_cid = 1

    try:
        import torch

        if torch.cuda.is_available():
            device = torch.device("cuda")
            device_used = f"cuda:{torch.cuda.get_device_name(0)}"
            x_norm = torch.nn.functional.normalize(torch.from_numpy(kmer_ord), p=2, dim=1).to(device)
            len_t = torch.from_numpy(len_ord).to(device)
            assigned = torch.zeros(n, dtype=torch.bool, device=device)

            with torch.no_grad():
                for i in range(n):
                    if bool(assigned[i].item()):
                        continue
                    sims = torch.matmul(x_norm[i], x_norm.T)
                    len_ratio = torch.minimum(len_t[i], len_t) / torch.maximum(len_t[i], len_t)
                    members = (~assigned) & (sims >= sim_threshold) & (len_ratio >= min_len_ratio)
                    members[i] = True
                    assigned |= members
                    cid = f"CLU_{next_cid:05d}"
                    next_cid += 1
                    for m_pos in torch.where(members)[0].cpu().tolist():
                        cluster_ids_ord[m_pos] = cid
                    del sims, len_ratio, members

            del x_norm, len_t, assigned
            torch.cuda.empty_cache()
        else:
            raise RuntimeError("CUDA not available")
    except Exception:
        norms = np.linalg.norm(kmer_ord, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        x_norm = (kmer_ord / norms).astype(np.float32)
        assigned_np = np.zeros(n, dtype=bool)
        for i in range(n):
            if assigned_np[i]:
                continue
            sims = x_norm[i] @ x_norm.T
            len_ratio = np.minimum(len_ord[i], len_ord) / np.maximum(len_ord[i], len_ord)
            members = (~assigned_np) & (sims >= sim_threshold) & (len_ratio >= min_len_ratio)
            members[i] = True
            assigned_np |= members
            cid = f"CLU_{next_cid:05d}"
            next_cid += 1
            for m_pos in np.where(members)[0].tolist():
                cluster_ids_ord[m_pos] = cid

    return [cluster_ids_ord[inv_order[orig_i]] for orig_i in range(n)], device_used


def _assign_cluster_splits(
    records: List[Dict[str, Any]],
    train_ratio: float = 0.80,
    val_ratio: float = 0.10,
) -> Dict[str, str]:
    """
    按簇级（Cluster-level）做分层均衡切分，保障同类簇绝不跨 Train/Val/Test 泄露，
    同时维持不同分类群与温和/裂解比例均衡。
    """
    clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in records:
        clusters[rec["cluster_id"]].append(rec)

    # 按分类群分组，每组内部按簇大小降序后以贪心误差最小原则分配到 train/val/test
    strata: Dict[str, List[Tuple[str, List[Dict[str, Any]]]]] = defaultdict(list)
    for cid, members in clusters.items():
        rep = members[0]
        key = f"{rep['tax_group']}_{rep['has_integrase']}"
        strata[key].append((cid, members))

    cluster_to_split: Dict[str, str] = {}
    total_counts = {"train": 0, "val": 0, "test": 0}
    target_ratios = {"train": train_ratio, "val": val_ratio, "test": max(0.01, 1.0 - train_ratio - val_ratio)}

    for key in sorted(strata.keys()):
        group_clusters = sorted(strata[key], key=lambda item: (-len(item[1]), item[0]))
        grp_counts = {"train": 0, "val": 0, "test": 0}

        for cid, members in group_clusters:
            sz = len(members)
            grp_total = sum(grp_counts.values()) + sz
            best_split = "train"
            best_score = float("inf")
            for sp in ("train", "val", "test"):
                # 同时衡量本分层配额偏差与全局配额偏差
                cur_grp_ratio = (grp_counts[sp] + sz) / max(1, grp_total)
                g_all = sum(total_counts.values()) + sz
                cur_all_ratio = (total_counts[sp] + sz) / max(1, g_all)
                score = abs(cur_grp_ratio - target_ratios[sp]) * 2.0 + abs(cur_all_ratio - target_ratios[sp])
                if score < best_score:
                    best_score = score
                    best_split = sp

            cluster_to_split[cid] = best_split
            grp_counts[best_split] += sz
            total_counts[best_split] += sz

    return cluster_to_split


def preprocess_phage_dataset(
    data_dir: Path,
    *,
    shard_size: int = 250,
    window_size: int = 5000,
    window_step: int = 2500,
    sim_threshold: float = 0.994,
    min_len_ratio: float = 0.85,
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    执行正样本数据集训练前预处理：
    1. 读取已校验通过的噬菌体清单；
    2. 分片多核提取特征（4-mer、基因拓扑、ORF 序列、5kb 滑窗）并断点落盘；
    3. GPU/CPU 加速相似度聚类并生成 Cluster-aware 无泄露 8:1:1 数据集切分。
    """
    root = Path(data_dir).resolve()
    prep_dir = root / "preprocessed"
    shards_dir = prep_dir / "shards"
    splits_dir = prep_dir / "splits"
    shards_dir.mkdir(parents=True, exist_ok=True)
    splits_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path = root / "index" / "phage_index.sqlite"
    if sqlite_path.exists():
        with closing(sqlite3.connect(sqlite_path)) as conn:
            rows = conn.execute(
                "SELECT accession, gbk_relpath, phage_tax_group, host, has_integrase "
                "FROM genomes WHERE status IN ('passed', 'warning') AND is_phage = 1 "
                "ORDER BY accession"
            ).fetchall()
        tasks = [
            (acc, str(root / gbk_rel), tax_grp or "Caudoviricetes", host or "", int(has_int or 0), window_size, window_step)
            for acc, gbk_rel, tax_grp, host, has_int in rows
        ]
    else:
        gbk_files = sorted((root / "gbk").glob("*.gbk"))
        tasks = [
            (p.stem, str(p), "Caudoviricetes", "", 0, window_size, window_step)
            for p in gbk_files
        ]

    if not tasks:
        raise RuntimeError(f"未找到可预处理的噬菌体记录: {root}")

    ckpt_path = prep_dir / "preprocess_checkpoint.json"
    completed_shards = {}
    if ckpt_path.exists():
        try:
            completed_shards = json.loads(ckpt_path.read_text(encoding="utf-8")).get("completed_shards", {})
        except Exception:
            completed_shards = {}

    cpu_cnt = os.cpu_count() or 4
    safe_workers = max_workers if max_workers is not None else max(1, min(cpu_cnt - 2, 16))
    logger.info(f"启动正样本训练集预处理: 共 {len(tasks)} 株, 分片大小={shard_size}, 并发进程={safe_workers}")

    summary_records: List[Dict[str, Any]] = []
    total_windows = 0
    total_orfs = 0

    for shard_idx, start in enumerate(range(0, len(tasks), shard_size)):
        shard_key = f"shard_{shard_idx:04d}"
        meta_shard_path = shards_dir / f"meta_{shard_key}.jsonl"
        orf_shard_path = shards_dir / f"orf_{shard_key}.jsonl"
        win_shard_path = shards_dir / f"win_{shard_key}.jsonl"
        batch_tasks = tasks[start:start + shard_size]

        if (
            shard_key in completed_shards
            and meta_shard_path.exists()
            and orf_shard_path.exists()
            and win_shard_path.exists()
        ):
            with open(meta_shard_path, "r", encoding="utf-8") as mf:
                for ln in mf:
                    if ln.strip():
                        rec = json.loads(ln)
                        total_windows += rec["window_count"]
                        total_orfs += rec["cds_count"]
                        summary_records.append(rec)
            continue

        if safe_workers == 1 or len(batch_tasks) < 8:
            batch_results = [_extract_single_genome_features(t) for t in batch_tasks]
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=safe_workers) as pool:
                batch_results = list(pool.map(_extract_single_genome_features, batch_tasks, chunksize=8))

        tmp_meta = meta_shard_path.with_name(f".{meta_shard_path.name}.tmp")
        tmp_orf = orf_shard_path.with_name(f".{orf_shard_path.name}.tmp")
        tmp_win = win_shard_path.with_name(f".{win_shard_path.name}.tmp")

        shard_cnt = 0
        with (
            open(tmp_meta, "w", encoding="utf-8") as mf,
            open(tmp_orf, "w", encoding="utf-8") as of,
            open(tmp_win, "w", encoding="utf-8") as wf,
        ):
            for item in batch_results:
                if not item:
                    continue
                shard_cnt += 1
                orf_seq = item.pop("orf_seq")
                windows = item.pop("windows")
                total_windows += len(windows)
                total_orfs += len(orf_seq)

                mf.write(json.dumps(item, ensure_ascii=False) + "\n")
                of.write(json.dumps({"accession": item["accession"], "orfs": orf_seq}, ensure_ascii=False) + "\n")
                for w in windows:
                    wf.write(json.dumps(w, ensure_ascii=False) + "\n")

                summary_records.append(item)

        tmp_meta.replace(meta_shard_path)
        tmp_orf.replace(orf_shard_path)
        tmp_win.replace(win_shard_path)

        completed_shards[shard_key] = {"count": shard_cnt, "saved_at": datetime.now().isoformat(timespec="seconds")}
        tmp_ckpt = ckpt_path.with_name(f".{ckpt_path.name}.tmp")
        tmp_ckpt.write_text(json.dumps({"completed_shards": completed_shards}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_ckpt.replace(ckpt_path)
        logger.info(f"预处理分片 {shard_key} 已落盘: 累计完成 {len(summary_records)}/{len(tasks)} 株")

    # 2. GPU 加速聚类去冗余
    summary_records.sort(key=lambda x: x["accession"])
    accessions = [r["accession"] for r in summary_records]
    lengths = [r["length_bp"] for r in summary_records]
    kmer_matrix = np.array([r["kmer4"] for r in summary_records], dtype=np.float32)

    cluster_ids, compute_device = _cluster_genomes_gpu_or_cpu(
        accessions,
        lengths,
        kmer_matrix,
        sim_threshold=sim_threshold,
        min_len_ratio=min_len_ratio,
    )
    for rec, cid in zip(summary_records, cluster_ids):
        rec["cluster_id"] = cid

    # 3. 按簇切分 Train / Val / Test
    cluster_to_split = _assign_cluster_splits(summary_records)
    for rec in summary_records:
        rec["split"] = cluster_to_split[rec["cluster_id"]]

    # 落盘 genome_features.tsv、clusters.tsv 与 splits/*.tsv
    feat_headers = [
        "accession", "cluster_id", "split", "tax_group", "host", "has_integrase",
        "length_bp", "gc_percent", "cds_count", "cds_per_kb", "coding_density",
        "mean_cds_len_bp", "strand_switch_rate", "max_same_strand_run",
        "func_capsid_cnt", "func_tail_cnt", "func_term_cnt", "func_lysin_cnt",
        "func_int_cnt", "func_rep_cnt", "func_hypo_cnt", "window_count",
    ]
    feat_tsv = prep_dir / "genome_features.tsv"
    tmp_ft = feat_tsv.with_name(f".{feat_tsv.name}.tmp")
    split_rows: Dict[str, List[list]] = {"train": [], "val": [], "test": []}
    with open(tmp_ft, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(feat_headers)
        for rec in summary_records:
            row = [rec[h] for h in feat_headers]
            w.writerow(row)
            split_rows[rec["split"]].append(row)
    tmp_ft.replace(feat_tsv)

    for sp_name, rows in split_rows.items():
        sp_path = splits_dir / f"{sp_name}.tsv"
        tmp_sp = sp_path.with_name(f".{sp_path.name}.tmp")
        with open(tmp_sp, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(feat_headers)
            w.writerows(rows)
        tmp_sp.replace(sp_path)

    cluster_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in summary_records:
        cluster_groups[rec["cluster_id"]].append(rec)

    clusters_tsv = prep_dir / "clusters.tsv"
    tmp_cl = clusters_tsv.with_name(f".{clusters_tsv.name}.tmp")
    with open(tmp_cl, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["cluster_id", "split", "size", "representative_acc", "tax_group", "members"])
        for cid in sorted(cluster_groups.keys()):
            members = cluster_groups[cid]
            w.writerow([
                cid,
                members[0]["split"],
                len(members),
                members[0]["accession"],
                members[0]["tax_group"],
                ",".join(m["accession"] for m in members),
            ])
    tmp_cl.replace(clusters_tsv)

    split_counter = Counter(r["split"] for r in summary_records)
    cluster_sizes = [len(m) for m in cluster_groups.values()]
    manifest: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_dir": str(root),
        "compute_device": compute_device,
        "parameters": {
            "shard_size": shard_size,
            "window_size": window_size,
            "window_step": window_step,
            "sim_threshold": sim_threshold,
            "min_len_ratio": min_len_ratio,
        },
        "summary": {
            "total_genomes": len(summary_records),
            "total_clusters": len(cluster_groups),
            "singleton_clusters": sum(1 for s in cluster_sizes if s == 1),
            "max_cluster_size": max(cluster_sizes) if cluster_sizes else 0,
            "total_orfs_extracted": total_orfs,
            "total_windows_extracted": total_windows,
            "mean_cds_per_kb": round(float(np.mean([r["cds_per_kb"] for r in summary_records])), 3),
            "mean_coding_density": round(float(np.mean([r["coding_density"] for r in summary_records])), 4),
            "split_distribution": dict(split_counter),
        },
        "artifacts": {
            "genome_features_tsv": str(feat_tsv),
            "clusters_tsv": str(clusters_tsv),
            "train_split": str(splits_dir / "train.tsv"),
            "val_split": str(splits_dir / "val.tsv"),
            "test_split": str(splits_dir / "test.tsv"),
            "shards_dir": str(shards_dir),
        },
    }

    manifest_path = prep_dir / "preprocess_manifest.json"
    tmp_mf = manifest_path.with_name(f".{manifest_path.name}.tmp")
    tmp_mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_mf.replace(manifest_path)

    return manifest


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="噬菌体训练集多核+GPU预处理工具")
    parser.add_argument("--data-dir", required=True, help="噬菌体正样本数据根目录")
    parser.add_argument("--shard-size", type=int, default=250, help="分片落盘大小（默认 250）")
    parser.add_argument("--window-size", type=int, default=5000, help="滑窗长度（默认 5000 bp）")
    parser.add_argument("--window-step", type=int, default=2500, help="滑窗步长（默认 2500 bp）")
    parser.add_argument("--sim-threshold", type=float, default=0.994, help="4-mer 余弦聚类阈值（默认 0.994）")
    args = parser.parse_args(argv)

    result = preprocess_phage_dataset(
        Path(args.data_dir),
        shard_size=args.shard_size,
        window_size=args.window_size,
        window_step=args.window_step,
        sim_threshold=args.sim_threshold,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

