# -*- coding: utf-8 -*-
"""
PHROGs Profile 遥远同源老师语义补全模块（离线训练监督增强）：
1. 读取 phrog_annot_v4.tsv 建立 phrog_id -> (category, annot) 精确映射；
2. 利用 WSL MMseqs2 (`mmseqs easy-search`) 对去重训练集 ORF 分片并发比对本地 `phrogs_profile_db`；
3. 按实测高特异度规则仅将 `head and packaging` / `connector`（衣壳/门蛋白/连接器）与 `tail` / `lysis`（尾部/裂解酶）
   以及 `transposase` 增量回填进 `sem_targets`，严格屏蔽 `unknown function` 以防宿主背景假阳污染。
"""
from __future__ import annotations

import concurrent.futures
import csv
import logging
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..teachers.checkv_teacher import to_wsl_path
from .feature_dataset import iter_fasta
from .v4_semantic_prep import TRANSPOSASE_SQL_RE, _extract_contig_orfs_raw

logger = logging.getLogger("phage_discovery.data.phrog_teacher")

_HALLMARK_PHROG_CATS = {"head and packaging", "connector"}
_TAIL_LYSIS_PHROG_CATS = {"tail", "lysis"}
_TRANSP_RE = re.compile(
    rf"(?:{TRANSPOSASE_SQL_RE.pattern}|\brecombinase\b|\bresolvase\b)",
    re.IGNORECASE,
)


def load_phrog_annotations(annot_tsv: Path) -> Dict[str, Tuple[str, str]]:
    """解析 phrog_annot_v4.tsv，返回 {'phrog_<id>': (category, annot)}。"""
    tsv_path = Path(annot_tsv).resolve()
    if not tsv_path.exists():
        raise FileNotFoundError(f"PHROGs 注释表不存在: {tsv_path}")
    mapping: Dict[str, Tuple[str, str]] = {}
    with open(tsv_path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            pid = str(row.get("phrog", "")).strip()
            if not pid:
                continue
            key = pid if pid.startswith("phrog_") else f"phrog_{pid}"
            cat = str(row.get("category", "")).strip()
            annot = str(row.get("annot", "")).strip()
            mapping[key] = (cat, annot)
    return mapping


def classify_phrog_category(target_id: str, annots: Dict[str, Tuple[str, str]]) -> str:
    """将 PHROGs 命中映射为高特异度语义类别。"""
    key = target_id if target_id.startswith("phrog_") else f"phrog_{target_id}"
    cat, annot = annots.get(key, ("unknown function", ""))
    if annot and TRANSPOSASE_SQL_RE.search(annot):
        return "transposase"
    if cat in _HALLMARK_PHROG_CATS:
        return "phrog_hallmark"
    if cat in _TAIL_LYSIS_PHROG_CATS:
        return "phrog_tail_lysis"
    if cat == "integration and excision":
        return "phrog_integrase"
    if cat == "unknown function":
        return "phrog_unknown"
    return "phrog_other"


def _parse_mmseqs_tsv(
    tsv_path: Path,
    *,
    min_qcov: float = 0.35,
    max_evalue: float = 1e-4,
    min_bits: float = 40.0,
) -> Dict[str, Tuple[float, str, float, float]]:
    """解析 mmseqs easy-search 结果并为每条 query 保留最高 bitscore 命中。"""
    best: Dict[str, Tuple[float, str, float, float]] = {}
    if not tsv_path.exists():
        return best
    with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 5:
                continue
            qid, tid = parts[0], parts[1]
            try:
                ev = float(parts[2])
                bits = float(parts[3])
                qcov = float(parts[4])
            except ValueError:
                continue
            if ev > max_evalue or qcov < min_qcov or bits < min_bits:
                continue
            prev = best.get(qid)
            if prev is None or bits > prev[0]:
                best[qid] = (bits, tid, qcov, ev)
    return best


def run_batch_phrog_mmseqs(
    orf_records: Sequence[Tuple[str, str]],
    phrogs_profile_db: Path,
    *,
    evalue: float = 1e-4,
    min_qcov: float = 0.35,
    min_bits: float = 40.0,
    sensitivity: float = 4.0,
    chunk_size: int = 80000,
    threads: Optional[int] = None,
) -> Dict[str, Tuple[float, str, float, float]]:
    """通过 WSL mmseqs easy-search 对海量去重 ORF 分块检索 PHROGs profile 库。"""
    if not orf_records:
        return {}
    db_path = Path(phrogs_profile_db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"PHROGs profile 库不存在: {db_path}")

    cpu_cnt = os.cpu_count() or 4
    n_threads = threads if threads is not None else max(1, cpu_cnt - 2)
    db_wsl = to_wsl_path(db_path)
    best_all: Dict[str, Tuple[float, str, float, float]] = {}

    with tempfile.TemporaryDirectory(prefix="phage_phrog_mmseqs_") as tmpdir:
        tmp_root = Path(tmpdir)
        n_chunks = (len(orf_records) + chunk_size - 1) // chunk_size
        for cidx in range(n_chunks):
            chunk = orf_records[cidx * chunk_size:(cidx + 1) * chunk_size]
            q_fa = tmp_root / f"queries_{cidx}.faa"
            out_tsv = tmp_root / f"hits_{cidx}.tsv"
            with open(q_fa, "w", encoding="utf-8") as fh:
                for oid, aa in chunk:
                    fh.write(f">{oid}\n{aa}\n")

            wsl_tmp = f"/tmp/mmseqs_phrog_{uuid.uuid4().hex[:10]}"
            try:
                proc = subprocess.run(
                    [
                        "wsl",
                        "mmseqs",
                        "easy-search",
                        to_wsl_path(q_fa),
                        db_wsl,
                        to_wsl_path(out_tsv),
                        wsl_tmp,
                        "--threads",
                        str(n_threads),
                        "-e",
                        str(evalue),
                        "-s",
                        str(sensitivity),
                        "--format-output",
                        "query,target,evalue,bits,qcov,tcov",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode != 0:
                    raise RuntimeError(f"WSL mmseqs easy-search 失败 (rc={proc.returncode}): {proc.stderr[-600:]}")
                chunk_hits = _parse_mmseqs_tsv(
                    out_tsv, min_qcov=min_qcov, max_evalue=evalue, min_bits=min_bits,
                )
                for qid, val in chunk_hits.items():
                    prev = best_all.get(qid)
                    if prev is None or val[0] > prev[0]:
                        best_all[qid] = val
            finally:
                subprocess.run(["wsl", "rm", "-rf", wsl_tmp], capture_output=True, check=False)
                q_fa.unlink(missing_ok=True)
                out_tsv.unlink(missing_ok=True)

    return best_all


def enrich_semantic_targets_with_phrog(
    part_specs: Sequence[Tuple[str, Path, Path, Optional[Path]]],
    out_dir: Path,
    *,
    annot_tsv: Path,
    phrogs_profile_db: Optional[Path] = None,
    workers: Optional[int] = None,
    hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    在独立目标目录 `out_dir` 生成增强版 `train_{part}_semantic.npz`（绝不覆写源语义缓存）：
    part_specs: [(part_name, train_part_npz, fasta_path, base_semantic_npz_or_None), ...]
    """
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    annots = load_phrog_annotations(annot_tsv)

    unique_contigs: Dict[str, str] = {}
    part_rows: Dict[str, Dict[str, Any]] = {}
    for pname, npz_p, fa_p, base_sem_p in part_specs:
        npz_path = Path(npz_p).resolve()
        fa_path = Path(fa_p).resolve()
        if not npz_path.exists() or not fa_path.exists():
            continue
        with np.load(npz_path, allow_pickle=False) as d:
            arrs = {
                "contig_ids": d["contig_ids"],
                "starts": d["starts"],
                "ends": d["ends"],
                "labels": d["labels"].astype(np.int8),
            }
        needed = {str(c) for c in arrs["contig_ids"]}
        for cid, seq in iter_fasta(fa_path):
            if cid in needed and cid not in unique_contigs:
                unique_contigs[cid] = seq

        n = len(arrs["labels"])
        sem_targets = np.zeros((n, 4), dtype=np.float32)
        sem_valid_mask = np.ones(n, dtype=np.float32)
        hall_cnts = np.zeros(n, dtype=np.int16)
        transp_cnts = np.zeros(n, dtype=np.int16)
        clean_labels = arrs["labels"].copy()
        if base_sem_p is not None and Path(base_sem_p).exists():
            with np.load(Path(base_sem_p), allow_pickle=False) as sd:
                if len(sd["sem_targets"]) == n:
                    sem_targets = sd["sem_targets"].astype(np.float32).copy()
                    sem_valid_mask = sd["sem_valid_mask"].astype(np.float32).copy()
                    hall_cnts = sd["hallmark_counts"].astype(np.int16).copy()
                    transp_cnts = sd["transposase_counts"].astype(np.int16).copy()
                    clean_labels = sd["clean_labels"].astype(np.int8).copy()

        part_rows[pname] = {
            **arrs,
            "sem_targets": sem_targets,
            "sem_valid_mask": sem_valid_mask,
            "hallmark_counts": hall_cnts,
            "transposase_counts": transp_cnts,
            "clean_labels": clean_labels,
        }

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
            if len(aa) >= 25:
                orf_records.append((f"{cid}__orf{oi}", aa))

    if hit_fetcher is not None:
        raw_hits = hit_fetcher(orf_records)
    elif phrogs_profile_db is not None:
        raw_hits = run_batch_phrog_mmseqs(orf_records, phrogs_profile_db, threads=n_workers)
    else:
        raw_hits = {}

    contig_phrog_cls: Dict[str, List[Tuple[int, int, str]]] = {}
    for cid, orfs in contig_orfs.items():
        lst: List[Tuple[int, int, str]] = []
        for oi, (s0, e0, _) in enumerate(orfs):
            hit = raw_hits.get(f"{cid}__orf{oi}")
            if hit is None:
                continue
            tid = str(hit[1])
            cls = classify_phrog_category(tid, annots)
            if cls in ("phrog_hallmark", "phrog_tail_lysis", "transposase"):
                lst.append((s0, e0, cls))
        lst.sort(key=lambda t: t[0])
        contig_phrog_cls[cid] = lst

    summary: Dict[str, Dict[str, Any]] = {}
    for pname, item in part_rows.items():
        cids = item["contig_ids"]
        starts = item["starts"]
        ends = item["ends"]
        sem_targets = item["sem_targets"]
        hall_cnts = item["hallmark_counts"]
        transp_cnts = item["transposase_counts"]
        n = len(cids)

        backfill_hall = 0
        backfill_tl = 0
        for idx in range(n):
            cid = str(cids[idx])
            ws = int(starts[idx])
            we = int(ends[idx])
            ph_hall = 0
            ph_tl = 0
            ph_tr = 0
            for gs, ge, cls in contig_phrog_cls.get(cid, ()):
                if ge <= ws:
                    continue
                if gs >= we:
                    break
                mid = (gs + ge) // 2
                if ws <= mid < we:
                    if cls == "phrog_hallmark":
                        ph_hall += 1
                    elif cls == "phrog_tail_lysis":
                        ph_tl += 1
                    elif cls == "transposase":
                        ph_tr += 1

            if ph_hall > 0:
                prev_h = float(sem_targets[idx, 0])
                new_h = 1.0 if ph_hall >= 2 else 0.65
                if prev_h < 0.5 and max(prev_h, new_h) >= 0.5:
                    backfill_hall += 1
                sem_targets[idx, 0] = max(prev_h, new_h)
                hall_cnts[idx] = np.int16(int(hall_cnts[idx]) + ph_hall)
            if ph_tl > 0:
                prev_tl = float(sem_targets[idx, 3])
                new_tl = 1.0 if ph_tl >= 2 else 0.60
                if prev_tl < 0.5 and max(prev_tl, new_tl) >= 0.5:
                    backfill_tl += 1
                sem_targets[idx, 3] = max(prev_tl, new_tl)
            if ph_tr > 0 and ph_hall == 0 and float(sem_targets[idx, 0]) < 0.5:
                sem_targets[idx, 2] = max(float(sem_targets[idx, 2]), 0.8 if ph_tr == 1 else 1.0)
                transp_cnts[idx] = np.int16(int(transp_cnts[idx]) + ph_tr)

        sem_out = out_root / f"train_{pname}_semantic.npz"
        tmp_sem = sem_out.with_name(f".{sem_out.stem}.tmp.npz")
        np.savez_compressed(
            tmp_sem,
            sem_targets=sem_targets,
            sem_valid_mask=item["sem_valid_mask"],
            hallmark_counts=hall_cnts,
            transposase_counts=transp_cnts,
            clean_labels=item["clean_labels"],
        )
        tmp_sem.replace(sem_out)
        summary[pname] = {
            "rows": n,
            "backfilled_hallmark_windows": backfill_hall,
            "backfilled_tail_lysis_windows": backfill_tl,
            "total_hallmark_pos_windows": int(np.sum(sem_targets[:, 0] >= 0.5)),
            "total_tail_lysis_windows": int(np.sum(sem_targets[:, 3] >= 0.5)),
            "semantic_npz": str(sem_out),
        }
        logger.info(f"PHROGs 遥远同源语义补全 train_{pname}: {summary[pname]}")

    return summary

