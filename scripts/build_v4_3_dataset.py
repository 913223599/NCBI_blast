# -*- coding: utf-8 -*-
"""
V4.3 零泄露硬负样本与专项训练数据集构建流水线：
1. 仅限 negative_splits.json == "train" 分片执行本地挖掘与全量采样：
   - 303 条 train 质粒（避开 prophage_masks ±5kb，全长 + 6~15kb 多尺度，重采样当前 UV4 误报热点）；
   - 75 条 train 非噬菌体真核/古菌病毒（避开真实噬菌体污染，重采样 UV4 误报热点）；
   - 42 条 train 细菌染色体反向挖掘（避开 prophage_masks ±10kb 与 PHROGs 完整衣壳/颈环真前噬菌体，捕获 Tailocin 与 ICE 硬负例）；
2. 融合 fetch_v4_3_external_tailocins.py 拉取的外源跨属非同源 Tailocin/Diffocin/PVC/Afp/ICE 基因座，再次校验与 Gold-8/Unseen/test 零重叠；
3. 对全部新增硬负 ORF 运行本地 WSL pyhmmer (all_phrogs + defense_finder + dbapis) 标注，构造含 tr_hard_kind 标记的 judge_dataset_v4_3.npz 与 DNA 微调切片集 v4_3_dna/。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gc
import gzip
import hashlib
import json
import logging
import math
import os
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pyrodigal
from Bio import SeqIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.fetch_v4_3_external_tailocins import _build_forbidden_kmer_index, _kmer_set  # noqa: E402
from scripts.run_orf_judge_ablation import _encode_contig_worker  # noqa: E402
from scripts.run_p0_distill_ablation import _aa_key, _load_merged_phrog_phold_annots  # noqa: E402
from src.phage_discovery.data.feature_dataset import iter_fasta  # noqa: E402
from src.phage_discovery.data.functional_partitions import classify_protein_with_p0_teachers  # noqa: E402
from src.phage_discovery.inference.unified_model import ALL_UNIFIED_EXPERTS, UnifiedPhageModel  # noqa: E402
from src.phage_discovery.student.orf_functional_judge import (  # noqa: E402
    CTX_WIN_ORFS,
    MAX_JUDGE_AA_LEN,
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
)
from src.phage_discovery.teachers.hmm_adversarial_teacher import (  # noqa: E402
    resolve_hmm_library_paths,
    run_chunked_hmm_teacher,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("build_v4_3_dataset")

HARD_KIND_NORMAL = 0
HARD_KIND_TAILOCIN = 1
HARD_KIND_PLASMID = 2
HARD_KIND_NONPHAGE_VIRUS = 3
HARD_KIND_MGE_ICE = 4


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _overlaps_masks(s: int, e: int, masks: Sequence[Tuple[int, int]], pad: int = 5000) -> bool:
    for ms, me in masks:
        if max(s, ms - pad) < min(e, me + pad):
            return True
    return False


def _slice_clean_segments(seq: str, masks: Sequence[Tuple[int, int]], *, pad: int = 5000, min_len: int = 5000) -> List[Tuple[int, str]]:
    if not masks:
        return [(0, seq)] if len(seq) >= min_len else []
    bad = sorted((max(0, ms - pad), min(len(seq), me + pad)) for ms, me in masks)
    merged: List[List[int]] = []
    for bs, be in bad:
        if merged and bs <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], be)
        else:
            merged.append([bs, be])
    out: List[Tuple[int, str]] = []
    cur = 0
    for bs, be in merged:
        if bs - cur >= min_len:
            out.append((cur, seq[cur:bs]))
        cur = max(cur, be)
    if len(seq) - cur >= min_len:
        out.append((cur, seq[cur:]))
    return out


def _extract_orfs_pyrodigal(seq: str) -> List[Tuple[int, int, int, str]]:
    s_up = (seq or "").upper()
    lst: List[Tuple[int, int, int, str]] = []
    if len(s_up) >= 300:
        gf = pyrodigal.GeneFinder(meta=True)
        for g in gf.find_genes(s_up.encode("ascii", errors="replace")):
            aa = g.translate(include_stop=False).strip()
            if aa and "*" not in aa:
                lst.append((int(g.begin - 1), int(g.end), int(g.strand), aa))
    lst.sort(key=lambda x: (x[0], x[1]))
    return lst


def _read_gbk_products_by_seq(gbk_path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not gbk_path.is_file():
        return out
    try:
        for rec in SeqIO.parse(str(gbk_path), "genbank"):
            for feat in rec.features:
                if feat.type != "CDS":
                    continue
                aa = str((feat.qualifiers.get("translation") or [""])[0]).strip()
                prod = str((feat.qualifiers.get("product") or [""])[0]).strip()
                if aa and prod:
                    out[aa] = prod
    except Exception:  # noqa: BLE001
        pass
    return out


def collect_hard_neg_contigs(
    pd_root: Path,
    *,
    workers: int = 12,
    device: str = "cuda",
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    收集全量严格零泄露 V4.3 硬负样本 Contig 与原生产模型误报热点：
      - 外源 NCBI 跨属 Tailocin & non-V583 ICE (已通过 5-mer 去重)
      - 内源 train 303 条质粒 + 75 条非噬菌体病毒（扣掩码后整条+短片切分 + UV4 误报区 3x 重采样）
      - 内源 train 42 条细菌染色体被 UV4 误报但无衣壳/连接蛋白 HMM 证据的非噬菌体热点区段
    """
    out_data_dir = pd_root / "training" / "orf_judge_v4_3"
    dna_dir = pd_root / "training" / "v4_3_dna"
    out_data_dir.mkdir(parents=True, exist_ok=True)
    dna_dir.mkdir(parents=True, exist_ok=True)

    cache_pkl = out_data_dir / "collected_hard_contigs.pkl.gz"
    if cache_pkl.is_file():
        logger.info("发现断点缓存 %s，直接加载跳过重复扫描。", cache_pkl)
        with gzip.open(cache_pkl, "rb") as fh:
            obj = pickle.load(fh)
        return obj["contigs"], obj["gbk_prods"]

    neg_root = pd_root / "negative"
    splits = json.loads((pd_root / "benchmarks" / "v1" / "negative_splits.json").read_text(encoding="utf-8"))

    masks_by_acc: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    with (neg_root / "index" / "prophage_masks.tsv").open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            masks_by_acc[str(row["accession"])].append((int(row["start_pos"]), int(row["end_pos"])))

    train_rows: List[Dict[str, str]] = []
    with (neg_root / "index" / "negative_index.tsv").open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            acc = str(row["accession"])
            if row.get("is_valid_negative") == "1" and splits.get(acc) == "train":
                train_rows.append(row)

    logger.info("已锁定 train 分片负样本资产: %d 条", len(train_rows))

    # 加载现役 UV4 模型扫描全部 train 分片，专门定位当前模型仍会误报的高难靶点
    upm = UnifiedPhageModel.from_models_root(
        pd_root / "models" / "full_v4",
        stage1_2_subdir="stage1_2",
        workers=workers,
        device=device,
        active_experts=ALL_UNIFIED_EXPERTS,
        prefer_unified_judge=True,
    )

    gbk_prods: Dict[str, str] = {}
    hard_contigs: List[Dict[str, Any]] = []
    dna_fna_lines: List[str] = []
    dna_manifest: List[Dict[str, Any]] = []
    rng = np.random.default_rng(20261116)

    # 1. 处理外源 NCBI 拉取序列（确保零泄露）
    ext_meta_p = pd_root / "training" / "v4_3_external" / "external_tailocin_ice.json"
    ext_fna_p = pd_root / "training" / "v4_3_external" / "external_tailocin_ice.fna"
    ext_gbk_dir = pd_root / "training" / "v4_3_external" / "raw_gbk"
    if ext_gbk_dir.is_dir():
        for gbf in ext_gbk_dir.glob("*.gbk"):
            gbk_prods.update(_read_gbk_products_by_seq(gbf))

    if ext_fna_p.is_file() and ext_meta_p.is_file():
        ext_info = {r["contig_id"]: r for r in json.loads(ext_meta_p.read_text(encoding="utf-8")).get("accepted", [])}
        ext_seqs = {cid: seq for cid, seq in iter_fasta(ext_fna_p)}
        for cid, seq in ext_seqs.items():
            meta = ext_info.get(cid, {})
            kind_str = str(meta.get("kind", "tailocin"))
            if kind_str == "mge_ice":
                kind, rep_times = HARD_KIND_MGE_ICE, 2
            elif kind_str == "non_phage_virus":
                kind, rep_times = HARD_KIND_NONPHAGE_VIRUS, 3
            elif kind_str == "plasmid":
                kind, rep_times = HARD_KIND_PLASMID, 2
            else:
                kind, rep_times = HARD_KIND_TAILOCIN, 3
            orfs = _extract_orfs_pyrodigal(seq)
            if len(orfs) >= 6:
                hard_contigs.append({
                    "contig_id": cid,
                    "hard_kind": kind,
                    "weight": rep_times,
                    "source": "external_ncbi",
                    "orfs": orfs,
                    "seq": seq,
                })
                dna_fna_lines.append(f">{cid}\n{seq}\n")
                dna_manifest.append({"contig_id": cid, "kind": kind, "length_bp": len(seq), "source": "external_ncbi"})
        logger.info("已纳入外源硬负样本: %d 条 (Tailocin/ICE/古菌病毒/质粒)", len(ext_seqs))

    # 2. 处理 train 303 条质粒与 75 条非噬菌体病毒
    pl_vir_seqs: Dict[str, str] = {}
    pl_vir_meta: Dict[str, Tuple[int, str]] = {}
    for r in train_rows:
        cat = str(r["negative_category"])
        if cat not in ("plasmid", "non_phage_virus"):
            continue
        acc = str(r["accession"])
        fa_p = neg_root / r["fasta_relpath"] if r.get("fasta_relpath") else neg_root / "fasta" / f"{acc}.fasta"
        gb_p = neg_root / r["gbk_relpath"] if r.get("gbk_relpath") else neg_root / "gbk" / f"{acc}.gbk"
        gbk_prods.update(_read_gbk_products_by_seq(gb_p))
        for _, raw_seq in iter_fasta(fa_p):
            clean_segs = _slice_clean_segments(raw_seq, masks_by_acc.get(acc, []), pad=5000, min_len=4000)
            kind = HARD_KIND_PLASMID if cat == "plasmid" else HARD_KIND_NONPHAGE_VIRUS
            for s_idx, (off_bp, sub_seq) in enumerate(clean_segs):
                seg_id = f"TR_{cat}_{acc}_{s_idx}"
                pl_vir_seqs[seg_id] = sub_seq
                pl_vir_meta[seg_id] = (kind, acc)

    # 扫一遍 train 质粒/非噬菌体病毒，精准抓出现行 UV4 仍会误报的目标重点强化
    logger.info("使用现役 UV4 扫描 train 质粒与非噬菌体病毒共 %d 条干净区段以定位误报...", len(pl_vir_seqs))
    pv_res = upm.scan_sequences(pl_vir_seqs)
    pv_fp_cids = {reg.contig_id for reg in pv_res.regions} | {reg.contig_id for reg in pv_res.base_regions}
    logger.info("在 train 质粒/非噬菌体病毒上捕获 UV4 误报/高响应热点 Contig: %d 条", len(pv_fp_cids))

    for seg_id, seq in pl_vir_seqs.items():
        kind, acc = pl_vir_meta[seg_id]
        is_hot = seg_id in pv_fp_cids
        orfs = _extract_orfs_pyrodigal(seq)
        if len(orfs) >= 4:
            hard_contigs.append({
                "contig_id": seg_id,
                "hard_kind": kind,
                "weight": 3 if is_hot else 1,
                "source": f"train_{'hot_fp' if is_hot else 'clean'}",
                "orfs": orfs,
                "seq": seq if is_hot else "",
            })
        # 如果是长质粒或热点，额外切一段 8~14kb 短碎片段模拟 B1 碎片质粒环境
        if len(seq) >= 16000 and (is_hot or len(hard_contigs) % 3 == 0):
            frag_len = int(rng.integers(8000, 14500))
            st_bp = int(rng.integers(0, len(seq) - frag_len + 1))
            frag_seq = seq[st_bp : st_bp + frag_len]
            frag_orfs = _extract_orfs_pyrodigal(frag_seq)
            if len(frag_orfs) >= 4:
                fid = f"{seg_id}_frag{frag_len}"
                hard_contigs.append({
                    "contig_id": fid,
                    "hard_kind": kind,
                    "weight": 2 if is_hot else 1,
                    "source": "train_frag_sim",
                    "orfs": frag_orfs,
                    "seq": frag_seq if is_hot else "",
                })
        if is_hot:
            dna_fna_lines.append(f">{seg_id}\n{seq}\n")
            dna_manifest.append({"contig_id": seg_id, "kind": kind, "length_bp": len(seq), "source": "train_hot_fp"})

    # 为高分被 UV4 误报的精确质粒/病毒预测区段单独落盘 ±2kb DNA 切片
    for reg in pv_res.regions:
        seq = pl_vir_seqs.get(reg.contig_id, "")
        if not seq:
            continue
        kind, _ = pl_vir_meta[reg.contig_id]
        cs = max(0, reg.start_bp - 2000)
        ce = min(len(seq), reg.end_bp + 2000)
        if ce - cs >= 4000:
            rid = f"HOT_{reg.contig_id}_{reg.start_bp}_{reg.end_bp}"
            dna_fna_lines.append(f">{rid}\n{seq[cs:ce]}\n")
            dna_manifest.append({"contig_id": rid, "kind": kind, "length_bp": ce - cs, "source": "train_hot_region"})

    # 3. 扫描 42 条 train 细菌染色体反向挖掘 Tailocin 与未知误报热点（严格避开 prophage_masks ±10kb）
    bact_rows = [r for r in train_rows if r["negative_category"] == "bacterial_chromosome"]
    logger.info("使用现役 UV4 逐株扫描 %d 条 train 细菌染色体反向挖掘细菌素与移动岛热点...", len(bact_rows))
    ph_map = _load_merged_phrog_phold_annots(REPO_ROOT / "database" / "pharokka_db")
    bact_ckpt_dir = out_data_dir / "bact_scan_ckpt"
    bact_ckpt_dir.mkdir(parents=True, exist_ok=True)
    bact_candidates: List[Dict[str, Any]] = []

    for b_idx, row in enumerate(bact_rows, start=1):
        acc = str(row["accession"])
        shard_p = bact_ckpt_dir / f"{acc}.pkl.gz"
        if shard_p.is_file():
            with gzip.open(shard_p, "rb") as fh:
                bact_cands_shard = pickle.load(fh)
            for item in bact_cands_shard:
                gbk_prods.update(item["gbk_prods"])
                bact_candidates.append(item)
            continue

        fa_p = neg_root / row["fasta_relpath"] if row.get("fasta_relpath") else neg_root / "fasta" / f"{acc}.fasta"
        gb_p = neg_root / row["gbk_relpath"] if row.get("gbk_relpath") else neg_root / "gbk" / f"{acc}.gbk"
        seq_dict = {cid: s for cid, s in iter_fasta(fa_p)}
        shard_items: List[Dict[str, Any]] = []
        if seq_dict:
            res = upm.scan_sequences(seq_dict)
            if res.regions or res.base_regions:
                b_masks = masks_by_acc.get(acc, [])
                seen_intervals: List[Tuple[int, int]] = []
                cand_regs = list(res.regions) + [
                    br for br in res.base_regions
                    if not _overlaps_masks(br.start_bp, br.end_bp, [(r.start_bp, r.end_bp) for r in res.regions], pad=2000)
                ]
                if cand_regs:
                    gb_prods_acc = _read_gbk_products_by_seq(gb_p)
                    gbk_prods.update(gb_prods_acc)
                    for reg in cand_regs:
                        if _overlaps_masks(reg.start_bp, reg.end_bp, b_masks, pad=10000):
                            continue
                        if _overlaps_masks(reg.start_bp, reg.end_bp, seen_intervals, pad=2000):
                            continue
                        full_seq = seq_dict.get(reg.contig_id, "")
                        if not full_seq:
                            continue
                        cs = max(0, reg.start_bp - 4000)
                        ce = min(len(full_seq), reg.end_bp + 4000)
                        sub_seq = full_seq[cs:ce]
                        sub_orfs = _extract_orfs_pyrodigal(sub_seq)
                        if len(sub_orfs) < 5:
                            continue
                        seen_intervals.append((reg.start_bp, reg.end_bp))
                        ann = res.region_annotations.get(f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}", {})
                        shard_items.append({
                            "contig_id": f"TR_BACT_{acc}_{reg.start_bp}_{reg.end_bp}",
                            "acc": acc,
                            "seq": sub_seq,
                            "orfs": sub_orfs,
                            "ann": ann,
                            "gbk_prods": gb_prods_acc,
                        })

        tmp_sp = shard_p.with_name(f".{shard_p.name}.tmp")
        with gzip.open(tmp_sp, "wb") as fh:
            pickle.dump(shard_items, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_sp.replace(shard_p)
        bact_candidates.extend(shard_items)

        if b_idx % 10 == 0:
            logger.info("  train 细菌已扫 %d/%d，暂存避掩码高难候选=%d", b_idx, len(bact_rows), len(bact_candidates))

    del upm
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass

    # 对 42 株 train 细菌挖掘出的避掩码热点运行 WSL PHROGs + DefenseFinder 独立验真：
    # 若明显含有 >=2 个衣壳/连接蛋白则视为漏掩蔽的真前噬菌体（坚决剔除，绝不污染负样本！）
    # 若不含 Head/Conn 却含 >=3 个 Tail 则标记为内源 Tailocin (HARD_KIND_TAILOCIN)，否则标为 MGE/细菌硬负例
    if bact_candidates:
        bact_aas = sorted({o[3] for item in bact_candidates for o in item["orfs"]})
        aa_items = [(_aa_key(a), a) for a in bact_aas]
        libs = resolve_hmm_library_paths(db_root=REPO_ROOT / "database")
        bact_hmm = run_chunked_hmm_teacher(
            aa_items,
            out_data_dir / "bact_cand_pyhmmer.pkl.gz",
            libs_cfg=libs,
            selected_libs=("all_phrogs", "defense_finder", "dbapis"),
            chunk_size=12000,
            cpus=max(2, min(12, workers)),
        )
        kept_bact = 0
        skipped_true_phage = 0
        for item in bact_candidates:
            head_conn_cnt = 0
            tail_cnt = 0
            for _, _, _, aa in item["orfs"]:
                ak = _aa_key(aa)
                rec_h = bact_hmm["hits"].get(ak, {})
                ph_id = ""
                if "all_phrogs" in rec_h and float(rec_h["all_phrogs"][1]) <= 1e-5:
                    ph_id = str(rec_h["all_phrogs"][0])
                ph_cat, ph_ann = ("", "")
                if ph_id:
                    pk = ph_id if ph_id.startswith("phrog_") else f"phrog_{ph_id}"
                    ph_cat, ph_ann = ph_map.get(pk, ("unknown function", ""))
                cls = classify_protein_with_p0_teachers(
                    phrog_category=ph_cat,
                    phrog_annot=ph_ann,
                    diamond_title="",
                    gbk_product=item["gbk_prods"].get(aa, ""),
                    phold_hit=None,
                    hmm_hit=rec_h,
                )
                fv = cls["func_vec"]
                if fv[0] > 0.5 or fv[1] > 0.5:
                    head_conn_cnt += 1
                if fv[2] > 0.5:
                    tail_cnt += 1

            # 包含 >=2 个衣壳或连接蛋白极可能是漏 masks 的真残余/完整噬菌体，安全跳过！
            if head_conn_cnt >= 2:
                skipped_true_phage += 1
                continue

            kind = HARD_KIND_TAILOCIN if tail_cnt >= 3 else HARD_KIND_MGE_ICE
            hard_contigs.append({
                "contig_id": item["contig_id"],
                "hard_kind": kind,
                "weight": 3 if kind == HARD_KIND_TAILOCIN else 2,
                "source": "train_bact_mined",
                "orfs": item["orfs"],
                "seq": item["seq"],
            })
            dna_fna_lines.append(f">{item['contig_id']}\n{item['seq']}\n")
            dna_manifest.append({"contig_id": item["contig_id"], "kind": kind, "length_bp": len(item["seq"]), "source": "train_bact_mined"})
            kept_bact += 1
        logger.info("train 细菌反挖校验完成: 纳入硬负例=%d (跳过疑似漏标真前噬菌体=%d)", kept_bact, skipped_true_phage)

    # 4. 最终零泄露保险：利用精确鸽巢倒排索引 + 多核并发检查全部收集到的硬负 Contig 与 Gold-8/Unseen 5-mer Jaccard >= 0.72 重叠
    _, gold_ref_kmers = _build_forbidden_kmer_index(pd_root)
    ref_sets = [rks for _, rks in gold_ref_kmers]
    ref_lens = [len(rks) for rks in ref_sets]
    inv_idx: Dict[str, List[int]] = defaultdict(list)
    for r_i, rks in enumerate(ref_sets):
        for km in rks:
            inv_idx[km].append(r_i)

    def _is_high_jaccard_exact(aa: str, threshold: float = 0.72) -> bool:
        ks = _kmer_set(aa)
        l1 = len(ks)
        if l1 < 20:
            return False
        need_hits = math.ceil(threshold * l1)
        # 鸽巢原理：任意 B 满足 Jaccard(A, B) >= T 必至少有 need_hits 个共同 k-mer，
        # 故按命中参考蛋白数升序抽取前 (l1 - need_hits + 1) 个最稀有 k-mer 必然命中所有真阳性候选（零漏检）。
        probe_n = max(1, l1 - need_hits + 1)
        ranked = sorted(ks, key=lambda m: len(inv_idx.get(m, ())))[:probe_n]
        cand_ids: Set[int] = set()
        for km in ranked:
            cand_ids.update(inv_idx.get(km, ()))
        if not cand_ids:
            return False
        min_l2 = need_hits
        max_l2 = int(l1 / threshold) + 1
        for r_i in cand_ids:
            l2 = ref_lens[r_i]
            if l2 < min_l2 or l2 > max_l2:
                continue
            inter = len(ks & ref_sets[r_i])
            if inter >= need_hits and (inter / float(l1 + l2 - inter)) >= threshold:
                return True
        return False

    unique_aas = sorted({
        aa
        for item in hard_contigs
        if item["source"] != "external_ncbi"
        for _, _, _, aa in item["orfs"]
    })
    leak_aa_set: Set[str] = set()
    if unique_aas:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, min(16, workers))) as ex:
            flags = list(ex.map(_is_high_jaccard_exact, unique_aas, chunksize=128))
        leak_aa_set = {aa for aa, flg in zip(unique_aas, flags) if flg}

    clean_contigs: List[Dict[str, Any]] = []
    leak_dropped = 0
    for item in hard_contigs:
        is_leak = False
        if item["source"] != "external_ncbi":
            is_leak = any(aa in leak_aa_set for _, _, _, aa in item["orfs"])
        if is_leak:
            leak_dropped += 1
            continue
        clean_contigs.append(item)
    logger.info("最终 5-mer 零泄露审计完成 (唯一ORF=%d): 保留=%d, 剔除疑似跨库高相似=%d", len(unique_aas), len(clean_contigs), leak_dropped)

    dna_fna_path = dna_dir / "hard_neg_slices.fna"
    tmp_fna = dna_fna_path.with_name(f".{dna_fna_path.name}.tmp")
    tmp_fna.write_text("".join(dna_fna_lines), encoding="utf-8")
    tmp_fna.replace(dna_fna_path)
    _atomic_write_json(dna_dir / "hard_neg_manifest.json", dna_manifest)

    tmp_pkl = cache_pkl.with_name(f".{cache_pkl.name}.tmp")
    with gzip.open(tmp_pkl, "wb") as fh:
        pickle.dump({"contigs": clean_contigs, "gbk_prods": gbk_prods}, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_pkl.replace(cache_pkl)
    return clean_contigs, gbk_prods


def build_judge_v4_3_npz(pd_root: Path, *, workers: int = 12, device: str = "cuda") -> Path:
    t0 = time.perf_counter()
    contigs, gbk_prods = collect_hard_neg_contigs(pd_root, workers=workers, device=device)

    out_dir = pd_root / "training" / "orf_judge_v4_3"
    all_aas = sorted({o[3] for item in contigs for o in item["orfs"]})
    libs = resolve_hmm_library_paths(db_root=REPO_ROOT / "database")
    full_hmm_cache = out_dir / "hard_neg_pyhmmer.pkl.gz"
    cached_hits: Dict[str, Any] = {}
    if full_hmm_cache.is_file():
        with gzip.open(full_hmm_cache, "rb") as fh:
            old_obj = pickle.load(fh)
        if isinstance(old_obj, dict) and "hits" in old_obj:
            cached_hits = dict(old_obj["hits"])
    missing_aas = [a for a in all_aas if _aa_key(a) not in cached_hits]
    logger.info(
        "硬负样本唯一 ORF 共 %d 个 (复用已有 HMM 缓存命中=%d, 增量补扫新序列 ORF=%d)...",
        len(all_aas),
        len(all_aas) - len(missing_aas),
        len(missing_aas),
    )
    if missing_aas:
        inc_cache = out_dir / "hard_neg_pyhmmer_inc.pkl.gz"
        if inc_cache.is_file():
            inc_cache.unlink()
        inc_state = run_chunked_hmm_teacher(
            [(_aa_key(a), a) for a in missing_aas],
            inc_cache,
            libs_cfg=libs,
            selected_libs=("all_phrogs", "defense_finder", "dbapis"),
            chunk_size=15000,
            cpus=max(2, min(12, workers)),
        )
        cached_hits.update(inc_state["hits"])
        tmp_hc = full_hmm_cache.with_name(f".{full_hmm_cache.name}.tmp.{os.getpid()}")
        with gzip.open(tmp_hc, "wb", compresslevel=4) as fh:
            pickle.dump({"done_chunks": 1, "chunk_size": len(all_aas), "total_items": len(all_aas), "hits": cached_hits}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_hc.replace(full_hmm_cache)
        if inc_cache.is_file():
            inc_cache.unlink()
    hmm_state = {"hits": cached_hits}
    ph_map = _load_merged_phrog_phold_annots(REPO_ROOT / "database" / "pharokka_db")

    # 编码全部硬负样本窗口并严格赋予生物学解耦监督标签
    new_tr_ids, new_tr_lens, new_tr_stat, new_tr_vc, new_tr_y10, new_tr_ph, new_tr_kn, new_tr_hk = [], [], [], [], [], [], [], []
    new_va_ids, new_va_lens, new_va_stat, new_va_vc, new_va_y10, new_va_ph, new_va_kn, new_va_hk = [], [], [], [], [], [], [], []

    for item in contigs:
        cid = item["contig_id"]
        kind = int(item["hard_kind"])
        weight = int(item.get("weight", 1))
        orfs = item["orfs"]

        sub_map: Dict[str, Tuple[np.ndarray, float, float]] = {}
        for _, _, _, aa in orfs:
            ak = _aa_key(aa)
            hmm_rec = hmm_state["hits"].get(ak)
            ph_id = ""
            if hmm_rec and "all_phrogs" in hmm_rec and float(hmm_rec["all_phrogs"][1]) <= 1e-5:
                ph_id = str(hmm_rec["all_phrogs"][0])
            ph_cat, ph_ann = ("", "")
            if ph_id:
                pk = ph_id if ph_id.startswith("phrog_") else f"phrog_{ph_id}"
                ph_cat, ph_ann = ph_map.get(pk, ("unknown function", ""))

            cls = classify_protein_with_p0_teachers(
                phrog_category=ph_cat,
                phrog_annot=ph_ann,
                diamond_title="",
                gbk_product=gbk_prods.get(aa, ""),
                phold_hit=None,
                hmm_hit=hmm_rec,
            )
            y10 = np.zeros(NUM_JUDGE_CLASSES, dtype=np.float32)
            # 核心解耦标记逻辑：
            #   - 整段属于硬负例，所以 is_phage 全部坚定给 0.0
            #   - 若为 Tailocin: 保留其物理模块 P2(Tail)/P3(Lysis) 等结构标注，不给 Head/Conn 伪标签，避免破坏真噬菌体尾丝识别
            #   - 若为质粒/非噬菌体病毒/ICE: 禁止非噬菌体交叉命中污染 P0..P4，仅允许客观保留 P8/P9
            if kind == HARD_KIND_TAILOCIN:
                y10[:9] = cls["func_vec"]
                y10[0] = 0.0
                y10[1] = 0.0
            else:
                y10[8] = float(cls["func_vec"][8])
                if kind == HARD_KIND_PLASMID and y10[8] < 0.5:
                    # 质粒上的未知功能或 P4/P5 基因保持非核心结构 0 监督，但对明确转座/复制质粒标签给予明确认知
                    pass
            if cls["adversarial_host_flag"] or (hmm_rec and "defense_finder" in hmm_rec and float(hmm_rec["defense_finder"][1]) <= 1e-5):
                y10[9] = 1.0
            sub_map[ak] = (y10, 0.0, 1.0)

        _, ids, lens, stat, vc, y10_m, ph_m, kn_m = _encode_contig_worker((cid, orfs, sub_map))
        if len(vc) == 0:
            continue
        hk_m = np.full(len(vc), kind, dtype=np.int32)
        h_val = int(hashlib.md5(cid.encode("utf-8")).hexdigest()[:8], 16) % 10
        if h_val == 0:
            new_va_ids.append(ids)
            new_va_lens.append(lens)
            new_va_stat.append(stat)
            new_va_vc.append(vc)
            new_va_y10.append(y10_m)
            new_va_ph.append(ph_m)
            new_va_kn.append(kn_m)
            new_va_hk.append(hk_m)
        else:
            for _ in range(weight):
                new_tr_ids.append(ids)
                new_tr_lens.append(lens)
                new_tr_stat.append(stat)
                new_tr_vc.append(vc)
                new_tr_y10.append(y10_m)
                new_tr_ph.append(ph_m)
                new_tr_kn.append(kn_m)
                new_tr_hk.append(hk_m)

    # 载入原版零泄露 judge_dataset.npz 并拼接
    base_npz = pd_root / "training" / "orf_judge_ablation" / "judge_dataset.npz"
    logger.info("合并基础零泄露数据集 %s ...", base_npz)
    base_ds = np.load(base_npz, allow_pickle=False)

    tr_n_base = len(base_ds["tr_vc"])
    base_tr_hk = np.zeros(tr_n_base, dtype=np.int32)

    all_tr_ids = np.concatenate([base_ds["tr_ids"]] + new_tr_ids, axis=0)
    all_tr_lens = np.concatenate([base_ds["tr_lens"]] + new_tr_lens, axis=0)
    all_tr_stat = np.concatenate([base_ds["tr_stat"]] + new_tr_stat, axis=0)
    all_tr_vc = np.concatenate([base_ds["tr_vc"]] + new_tr_vc, axis=0)
    all_tr_y10 = np.concatenate([base_ds["tr_y10"]] + new_tr_y10, axis=0)
    all_tr_ph = np.concatenate([base_ds["tr_ph"]] + new_tr_ph, axis=0)
    all_tr_kn = np.concatenate([base_ds["tr_kn"]] + new_tr_kn, axis=0)
    all_tr_hk = np.concatenate([base_tr_hk] + new_tr_hk, axis=0)

    out_npz = out_dir / "judge_dataset_v4_3.npz"
    tmp_npz = out_npz.with_name(f".{out_npz.name}.tmp.{os.getpid()}.npz")
    np.savez(
        tmp_npz,
        # 严格保持 stat_mean / stat_std 与基座一致，确保热启动微调无尺度偏移！
        stat_mean=base_ds["stat_mean"],
        stat_std=base_ds["stat_std"],
        tr_ids=all_tr_ids,
        tr_lens=all_tr_lens,
        tr_stat=all_tr_stat,
        tr_vc=all_tr_vc,
        tr_y10=all_tr_y10,
        tr_ph=all_tr_ph,
        tr_kn=all_tr_kn,
        tr_hard_kind=all_tr_hk,
        # 原 5,325 zero-overlap val 原样保留 + 新增 hard_va_* 独立监控硬负压制效果
        va_ids=base_ds["va_ids"],
        va_lens=base_ds["va_lens"],
        va_stat=base_ds["va_stat"],
        va_vc=base_ds["va_vc"],
        va_y10=base_ds["va_y10"],
        va_ph=base_ds["va_ph"],
        va_kn=base_ds["va_kn"],
        va_unseen=base_ds["va_unseen"],
        hard_va_ids=np.concatenate(new_va_ids, axis=0) if new_va_ids else np.zeros((0, CTX_WIN_ORFS, MAX_JUDGE_AA_LEN), dtype=np.uint8),
        hard_va_lens=np.concatenate(new_va_lens, axis=0) if new_va_lens else np.zeros((0, CTX_WIN_ORFS), dtype=np.int32),
        hard_va_stat=np.concatenate(new_va_stat, axis=0) if new_va_stat else np.zeros((0, CTX_WIN_ORFS, ORF_JUDGE_STAT_DIM), dtype=np.float32),
        hard_va_vc=np.concatenate(new_va_vc, axis=0) if new_va_vc else np.zeros((0,), dtype=np.int32),
        hard_va_hk=np.concatenate(new_va_hk, axis=0) if new_va_hk else np.zeros((0,), dtype=np.int32),
    )
    tmp_npz.replace(out_npz)

    counts = {int(k): int(np.sum(all_tr_hk == k)) for k in range(5)}
    summary = {
        "base_train_windows": int(tr_n_base),
        "added_train_windows": int(len(all_tr_vc) - tr_n_base),
        "total_train_windows": int(len(all_tr_vc)),
        "train_windows_by_hard_kind": {
            "0_base": counts.get(0, 0),
            "1_tailocin": counts.get(1, 0),
            "2_plasmid": counts.get(2, 0),
            "3_non_phage_virus": counts.get(3, 0),
            "4_mge_ice": counts.get(4, 0),
        },
        "hard_val_windows": int(sum(len(x) for x in new_va_vc)),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "output_npz": str(out_npz),
    }
    _atomic_write_json(out_dir / "dataset_v4_3_summary.json", summary)
    logger.info("V4.3 全量训练数据集构建完成: %s", json.dumps(summary, ensure_ascii=False))
    return out_npz


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phage-data-root", default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    build_judge_v4_3_npz(Path(args.phage_data_root).resolve(), workers=args.workers, device=args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
