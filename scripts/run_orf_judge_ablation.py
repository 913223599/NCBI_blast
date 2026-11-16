# -*- coding: utf-8 -*-
"""
独立轻量 ORF 序列 + 邻域上下文功能精判模块 (OrfFunctionalJudge) 离线验证与消融对比流水线：
1. --step eval_cache : 对 100% 零泄露测试集 (v1_test_chimeras + 4 株 unseen_real_genomes) 预测 ORF，
                       并用 WSL pyhmmer 扫描 all_phrogs / defense_finder / dbapis / vs2_pfam_vir 构建客观黄金标注缓存；
2. --step prep_data  : 复用 Stage 1.2 全量 contig ORF 与 P0 多教师 (三源+HMM+phold) 标签，提取序列张量并按 contig 划分防泄露验证集；
3. --step train      : 训练对照组 Judge(Stat-Only) 与完整版 Judge(AA-Seq + Context)，以验证集 Macro-F1 + AUROC 早停；
4. --step benchmark  : 在零泄露真实测试集上同台对比 Stage 1.2 内置头 vs Judge(Stat-Only) vs Judge(AA-Seq + Context)。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gc
import gzip
import hashlib
import json
import logging
import os
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_p0_distill_ablation import ALL_9_PARTS, _aa_key, _atomic_write_json, _load_merged_phrog_phold_annots  # noqa: E402
from src.phage_discovery.data.feature_dataset import iter_fasta  # noqa: E402
from src.phage_discovery.data.functional_partitions import classify_protein_with_p0_teachers  # noqa: E402
from src.phage_discovery.experts.expert_c_orf import _get_gf  # noqa: E402
from src.phage_discovery.experts.seq_dataset import encode_dna  # noqa: E402
from src.phage_discovery.inference.scanner import GenomeScanner, _extract_contig_worker  # noqa: E402
from src.phage_discovery.student.judge_calibration import (  # noqa: E402
    apply_blended_logit_calibration,
    apply_logit_calibration,
    blend_with_stage1_2_cross_modal,
    fit_logit_blend_and_calibrator,
    fit_logit_calibrator_on_val,
)
from src.phage_discovery.student.orf_functional_judge import (  # noqa: E402
    CTX_WIN_ORFS,
    JUDGE_CLASS_NAMES,
    MAX_JUDGE_AA_LEN,
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
    build_orf_functional_judge,
    predict_contig_orfs_with_judge,
    slice_contig_orf_windows,
)
from src.phage_discovery.teachers.hmm_adversarial_teacher import (  # noqa: E402
    resolve_hmm_library_paths,
    run_chunked_hmm_teacher,
)
from src.phage_discovery.teachers.prostt5_embed_teacher import (  # noqa: E402
    PROSTT5_EMBED_DIM,
    run_chunked_prostt5_embedding,
    select_priority_training_aas,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orf_judge_ablation")


def _resolve_paths(pd_root: Path, *, arch: str = "baseline") -> Dict[str, Path]:
    work_data = pd_root / "training" / "orf_judge_ablation"
    model_subdir = "orf_judge_ablation" if arch == "baseline" else f"orf_judge_ablation_{arch}"
    work_model = pd_root / "models" / "full_v4" / model_subdir
    work_data.mkdir(parents=True, exist_ok=True)
    work_model.mkdir(parents=True, exist_ok=True)
    return {
        "db_root": REPO_ROOT / "database",
        "bench_v1": pd_root / "benchmarks" / "v1",
        "unseen_dir": pd_root / "benchmarks" / "unseen_real_genomes",
        "s12_cache": pd_root / "training" / "stage1_2_ablation" / "func_cache",
        "p0_cache": pd_root / "training" / "stage1_3_p0_ablation" / "func_cache",
        "s12_model_dir": pd_root / "models" / "full_v4" / "stage1_2",
        "work_data": work_data,
        "work_model": work_model,
    }


def _extract_contig_orfs_from_fasta(fa_path: Path) -> Dict[str, List[Tuple[int, int, int, str]]]:
    gf = _get_gf()
    out: Dict[str, List[Tuple[int, int, int, str]]] = {}
    for cid, seq in iter_fasta(fa_path):
        s_up = seq.upper()
        lst: List[Tuple[int, int, int, str]] = []
        if len(s_up) >= 100:
            for g in gf.find_genes(s_up.encode("ascii", errors="replace")):
                aa = g.translate(include_stop=False).strip()
                if aa and "*" not in aa:
                    lst.append((int(g.begin - 1), int(g.end), int(g.strand), aa))
        lst.sort(key=lambda x: x[0])
        out[cid] = lst
    return out


def _classify_label_10d(
    aa: str,
    *,
    phrog_annot_map: Dict[str, Tuple[str, str]],
    exact_prod: Dict[str, str],
    dmnd_hits: Dict[str, str],
    phrog_hits: Dict[str, str],
    hmm_hits: Dict[str, Any],
    phold_hits: Dict[str, Any],
) -> Tuple[np.ndarray, float, float, bool]:
    """
    统一将多源蛋白注释转化为 Judge 目标：
      - y10: (10,) [P0..P8 + P9 host_defense_virulence]
      - is_phage: 1.0/0.0
      - y10_known: 1.0/0.0（phage_unknown 暗物质蛋白豁免 P0..P8 负梯度，但明确标定非宿主对抗 P9=0）
      - is_defense_finder: bool
    """
    ak = _aa_key(aa)
    gb_p = exact_prod.get(aa, "")
    dm_t = dmnd_hits.get(ak, "")
    ph_id = phrog_hits.get(ak, "")
    hmm_rec = hmm_hits.get(ak)
    if not ph_id and hmm_rec and "all_phrogs" in hmm_rec and float(hmm_rec["all_phrogs"][1]) <= 1e-5:
        ph_id = str(hmm_rec["all_phrogs"][0])

    ph_cat, ph_ann = ("", "")
    if ph_id:
        pk = ph_id if ph_id.startswith("phrog_") else f"phrog_{ph_id}"
        ph_cat, ph_ann = phrog_annot_map.get(pk, ("unknown function", ""))

    cls = classify_protein_with_p0_teachers(
        phrog_category=ph_cat,
        phrog_annot=ph_ann,
        diamond_title=dm_t,
        gbk_product=gb_p,
        phold_hit=phold_hits.get(ak),
        hmm_hit=hmm_rec,
    )
    y10 = np.zeros(NUM_JUDGE_CLASSES, dtype=np.float32)
    y10[:9] = cls["func_vec"]
    adv_flag = bool(cls["adversarial_host_flag"])
    if adv_flag:
        y10[9] = 1.0
    is_df = bool(hmm_rec and "defense_finder" in hmm_rec and float(hmm_rec["defense_finder"][1]) <= 1e-5)
    is_phage = 1.0 if cls["is_phage_ortholog"] else 0.0
    y10_known = 1.0 if cls["is_func_known"] else 0.0
    return y10, is_phage, y10_known, is_df


def run_step_eval_cache(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [Judge Step 1] 构建 100% 零泄露真实测试集 ORF 与 pyhmmer 多库真值缓存 ===")
    t0 = time.perf_counter()
    eval_files: List[Tuple[str, Path]] = [("v1_test_chimeras", paths["bench_v1"] / "test_chimeras.fna")]
    for fa in sorted(paths["unseen_dir"].glob("*.fasta")):
        if fa.name.startswith("_"):
            continue
        eval_files.append((fa.stem, fa))

    eval_contigs: Dict[str, Dict[str, List[Tuple[int, int, int, str]]]] = {}
    unique_aas_set: Set[str] = set()
    for ds_name, fa_path in eval_files:
        cmap = _extract_contig_orfs_from_fasta(fa_path)
        eval_contigs[ds_name] = cmap
        for lst in cmap.values():
            for _, _, _, aa in lst:
                unique_aas_set.add(aa)
        logger.info("解析评测集 %s: contigs=%d, orfs=%d", ds_name, len(cmap), sum(len(v) for v in cmap.values()))

    unique_aas = sorted(unique_aas_set)
    aa_items = [(_aa_key(aa), aa) for aa in unique_aas]
    libs = resolve_hmm_library_paths(db_root=paths["db_root"])
    hmm_cache = paths["work_data"] / "eval_pyhmmer_hits.pkl.gz"
    hmm_state = run_chunked_hmm_teacher(
        aa_items,
        hmm_cache,
        libs_cfg=libs,
        selected_libs=("all_phrogs", "defense_finder", "dbapis", "wsl_vs2_pfam_vir"),
        chunk_size=15000,
        cpus=int(args.cpus),
    )

    with gzip.open(paths["s12_cache"] / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        train_aas = set(pickle.load(fh)["unique_aas"])

    ph_map = _load_merged_phrog_phold_annots(paths["db_root"] / "pharokka_db")
    eval_labels: Dict[str, Dict[str, Any]] = {}
    unseen_cnt = 0
    phage_pos_cnt = 0
    df_pos_cnt = 0
    p08_known_pos = 0
    for aa in unique_aas:
        ak = _aa_key(aa)
        y10, is_ph, y10_k, is_df = _classify_label_10d(
            aa,
            phrog_annot_map=ph_map,
            exact_prod={},
            dmnd_hits={},
            phrog_hits={},
            hmm_hits=hmm_state["hits"],
            phold_hits={},
        )
        is_strictly_unseen = aa not in train_aas
        if is_strictly_unseen:
            unseen_cnt += 1
        if is_ph > 0.5:
            phage_pos_cnt += 1
        if is_df:
            df_pos_cnt += 1
        if np.any(y10[:9] > 0.5):
            p08_known_pos += 1
        eval_labels[ak] = {
            "y10": y10,
            "is_phage": is_ph,
            "y10_known": y10_k,
            "is_defense_finder": is_df,
            "strictly_unseen": is_strictly_unseen,
        }

    out_pkl = paths["work_data"] / "eval_truth_cache.pkl.gz"
    with gzip.open(out_pkl, "wb") as fh:
        pickle.dump(
            {
                "eval_contigs": eval_contigs,
                "eval_labels": eval_labels,
                "hmm_hits_count": len(hmm_state["hits"]),
            },
            fh,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    logger.info(
        "黄金评测缓存生成完成: unique_aas=%d (严格零重合=%d, pyhmmer命中=%d, 噬菌体同源=%d, 已知模块=%d, DefenseFinder=%d), 耗时 %.2fs",
        len(unique_aas),
        unseen_cnt,
        len(hmm_state["hits"]),
        phage_pos_cnt,
        p08_known_pos,
        df_pos_cnt,
        time.perf_counter() - t0,
    )


def _encode_contig_worker(
    item: Tuple[str, List[Tuple[int, int, int, str]], Dict[str, Tuple[np.ndarray, float, float]]],
) -> Tuple[str, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    cid, orfs, aa_label_map = item
    wins = slice_contig_orf_windows(orfs, ctx_len=CTX_WIN_ORFS, stride=16, max_aa_len=MAX_JUDGE_AA_LEN)
    if not wins:
        empty_u8 = np.zeros((0, CTX_WIN_ORFS, MAX_JUDGE_AA_LEN), dtype=np.uint8)
        empty_i32 = np.zeros((0, CTX_WIN_ORFS), dtype=np.int32)
        empty_stat = np.zeros((0, CTX_WIN_ORFS, ORF_JUDGE_STAT_DIM), dtype=np.float32)
        empty_vc = np.zeros((0,), dtype=np.int32)
        empty_y10 = np.zeros((0, CTX_WIN_ORFS, NUM_JUDGE_CLASSES), dtype=np.float32)
        empty_f = np.zeros((0, CTX_WIN_ORFS), dtype=np.float32)
        return cid, empty_u8, empty_i32, empty_stat, empty_vc, empty_y10, empty_f, empty_f

    aa_ids = np.stack([w["aa_ids"] for w in wins]).astype(np.uint8)
    aa_lens = np.stack([w["aa_lens"] for w in wins]).astype(np.int32)
    stat_feats = np.stack([w["stat_feats"] for w in wins]).astype(np.float32)
    valid_cnts = np.asarray([w["valid_count"] for w in wins], dtype=np.int32)

    nw = len(wins)
    y10_mat = np.zeros((nw, CTX_WIN_ORFS, NUM_JUDGE_CLASSES), dtype=np.float32)
    phage_mat = np.zeros((nw, CTX_WIN_ORFS), dtype=np.float32)
    known_mat = np.zeros((nw, CTX_WIN_ORFS), dtype=np.float32)

    orf_y10 = [aa_label_map[_aa_key(o[3])][0] for o in orfs]
    orf_ph = [aa_label_map[_aa_key(o[3])][1] for o in orfs]
    orf_kn = [aa_label_map[_aa_key(o[3])][2] for o in orfs]
    for wi, w in enumerate(wins):
        st, ed = w["start_idx"], w["end_idx"]
        vc = ed - st
        y10_mat[wi, :vc] = np.stack(orf_y10[st:ed])
        phage_mat[wi, :vc] = np.asarray(orf_ph[st:ed], dtype=np.float32)
        known_mat[wi, :vc] = np.asarray(orf_kn[st:ed], dtype=np.float32)

    return cid, aa_ids, aa_lens, stat_feats, valid_cnts, y10_mat, phage_mat, known_mat


def run_step_prep_data(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [Judge Step 2] 构建 ORF 上下文训练/零泄露验证数据集 ===")
    t0 = time.perf_counter()
    with gzip.open(paths["s12_cache"] / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        orfs_data = pickle.load(fh)
    unique_aas: List[str] = list(orfs_data["unique_aas"])
    part_contig_orfs = orfs_data["part_contig_orfs"]

    with gzip.open(paths["s12_cache"] / "gbk_aa_index.pkl.gz", "rb") as fh:
        exact_prod = pickle.load(fh)["exact_prod"]
    with gzip.open(paths["s12_cache"] / "diamond_aa_hits.pkl.gz", "rb") as fh:
        dmnd_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["s12_cache"] / "phrog_aa_hits.pkl.gz", "rb") as fh:
        phrog_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["p0_cache"] / "p0_hmm_aa_hits.pkl.gz", "rb") as fh:
        hmm_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["p0_cache"] / "p0_phold_aa_hits.pkl.gz", "rb") as fh:
        phold_hits = pickle.load(fh)["hits"]

    ph_map = _load_merged_phrog_phold_annots(paths["db_root"] / "pharokka_db")

    aa_label_map: Dict[str, Tuple[np.ndarray, float, float]] = {}
    for aa in unique_aas:
        ak = _aa_key(aa)
        y10, is_ph, y10_k, _ = _classify_label_10d(
            aa,
            phrog_annot_map=ph_map,
            exact_prod=exact_prod,
            dmnd_hits=dmnd_hits,
            phrog_hits=phrog_hits,
            hmm_hits=hmm_hits,
            phold_hits=phold_hits,
        )
        aa_label_map[ak] = (y10, is_ph, y10_k)

    all_contigs: List[Tuple[str, List[Tuple[int, int, int, str]], bool]] = []
    for p_name in ALL_9_PARTS:
        for cid, orfs in part_contig_orfs.get(p_name, {}).items():
            if not orfs:
                continue
            full_cid = f"{p_name}::{cid}"
            h_val = int(hashlib.md5(full_cid.encode("utf-8")).hexdigest()[:8], 16) % 10
            is_val = h_val == 0
            all_contigs.append((full_cid, orfs, is_val))

    train_aas_set: Set[str] = set()
    for _, orfs, is_val in all_contigs:
        if not is_val:
            for _, _, _, aa in orfs:
                train_aas_set.add(aa)

    logger.info("切分 Contig 级上下文: total_contigs=%d, train_aa_vocab=%d", len(all_contigs), len(train_aas_set))

    train_batches = []
    val_batches = []
    for full_cid, orfs, is_val in all_contigs:
        sub_map = {_aa_key(o[3]): aa_label_map[_aa_key(o[3])] for o in orfs}
        _, aa_ids, aa_lens, stat_feats, vcnt, y10_m, ph_m, kn_m = _encode_contig_worker((full_cid, orfs, sub_map))
        if len(vcnt) == 0:
            continue
        if is_val:
            wins = slice_contig_orf_windows(orfs, ctx_len=CTX_WIN_ORFS, stride=16, max_aa_len=MAX_JUDGE_AA_LEN)
            unseen_m = np.zeros_like(kn_m)
            for wi, w in enumerate(wins):
                st, ed = w["start_idx"], w["end_idx"]
                for k in range(ed - st):
                    if orfs[st + k][3] not in train_aas_set:
                        unseen_m[wi, k] = 1.0
            val_batches.append((aa_ids, aa_lens, stat_feats, vcnt, y10_m, ph_m, kn_m, unseen_m))
        else:
            train_batches.append((aa_ids, aa_lens, stat_feats, vcnt, y10_m, ph_m, kn_m))

    def _cat(batches, idx):
        return np.concatenate([b[idx] for b in batches], axis=0)

    tr_ids = _cat(train_batches, 0)
    tr_lens = _cat(train_batches, 1)
    tr_stat = _cat(train_batches, 2)
    tr_vc = _cat(train_batches, 3)
    tr_y10 = _cat(train_batches, 4)
    tr_ph = _cat(train_batches, 5)
    tr_kn = _cat(train_batches, 6)

    v_mask = np.arange(CTX_WIN_ORFS)[None, :] < tr_vc[:, None]
    flat_stat = tr_stat[v_mask]
    stat_mean = np.nan_to_num(flat_stat.mean(axis=0), nan=0.0).astype(np.float32)
    stat_std = np.nan_to_num(flat_stat.std(axis=0), nan=1.0).astype(np.float32)
    stat_std = np.where(stat_std < 1e-5, 1.0, stat_std).astype(np.float32)

    out_npz = paths["work_data"] / "judge_dataset.npz"
    tmp_npz = paths["work_data"] / f".judge_dataset.tmp.{os.getpid()}.npz"
    np.savez(
        tmp_npz,
        stat_mean=stat_mean,
        stat_std=stat_std,
        tr_ids=tr_ids,
        tr_lens=tr_lens,
        tr_stat=tr_stat,
        tr_vc=tr_vc,
        tr_y10=tr_y10,
        tr_ph=tr_ph,
        tr_kn=tr_kn,
        va_ids=_cat(val_batches, 0),
        va_lens=_cat(val_batches, 1),
        va_stat=_cat(val_batches, 2),
        va_vc=_cat(val_batches, 3),
        va_y10=_cat(val_batches, 4),
        va_ph=_cat(val_batches, 5),
        va_kn=_cat(val_batches, 6),
        va_unseen=_cat(val_batches, 7),
    )
    tmp_npz.replace(out_npz)
    logger.info(
        "Judge 数据集生成完成: train_windows=%d, val_windows=%d, 耗时 %.2fs -> %s",
        len(tr_vc),
        int(sum(len(b[3]) for b in val_batches)),
        time.perf_counter() - t0,
        out_npz,
    )


def run_step_prostt5_cache(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    """R2 前置离线步：提取高价值训练集蛋白的 ProstT5 1024D 折叠表征并严格对齐至 judge_dataset.npz。"""
    from collections import Counter

    logger.info("=== [R2 Step] 筛选高价值训练蛋白并分片提取本地 ProstT5_fp16 折叠表征 ===")
    t0 = time.perf_counter()
    with gzip.open(paths["s12_cache"] / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        part_contig_orfs = pickle.load(fh)["part_contig_orfs"]
    with gzip.open(paths["s12_cache"] / "gbk_aa_index.pkl.gz", "rb") as fh:
        exact_prod = pickle.load(fh)["exact_prod"]
    with gzip.open(paths["s12_cache"] / "diamond_aa_hits.pkl.gz", "rb") as fh:
        dmnd_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["s12_cache"] / "phrog_aa_hits.pkl.gz", "rb") as fh:
        phrog_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["p0_cache"] / "p0_hmm_aa_hits.pkl.gz", "rb") as fh:
        hmm_hits = pickle.load(fh)["hits"]
    with gzip.open(paths["p0_cache"] / "p0_phold_aa_hits.pkl.gz", "rb") as fh:
        phold_hits = pickle.load(fh)["hits"]
    ph_map = _load_merged_phrog_phold_annots(paths["db_root"] / "pharokka_db")

    tr_freq: Counter = Counter()
    train_contigs: List[Tuple[str, List[Tuple[int, int, int, str]]]] = []
    for p_name in ALL_9_PARTS:
        for cid, orfs in part_contig_orfs.get(p_name, {}).items():
            if not orfs:
                continue
            full_cid = f"{p_name}::{cid}"
            if int(hashlib.md5(full_cid.encode("utf-8")).hexdigest()[:8], 16) % 10 != 0:
                train_contigs.append((full_cid, orfs))
                for _, _, _, aa in orfs:
                    tr_freq[aa] += 1

    # 稀有高价值等级: connector(1), lysis(3), integration(4), transcription(6), moron(7), transposon(8) 或 P9(9)
    rare_idx = (1, 3, 4, 6, 7, 8)
    candidates = []
    for aa, freq in tr_freq.items():
        y10, _, y10_k, _ = _classify_label_10d(
            aa,
            phrog_annot_map=ph_map,
            exact_prod=exact_prod,
            dmnd_hits=dmnd_hits,
            phrog_hits=phrog_hits,
            hmm_hits=hmm_hits,
            phold_hits=phold_hits,
        )
        if y10_k <= 0.5:
            continue
        is_p08 = bool(np.any(y10[:9] > 0.5))
        is_p9 = bool(y10[9] > 0.5)
        is_rare = bool(is_p9 or np.any(y10[list(rare_idx)] > 0.5))
        candidates.append((aa, int(freq), is_p08, is_p9, is_rare))

    max_cnt = int(getattr(args, "prostt5_max_count", 40000))
    picked_aas = select_priority_training_aas(candidates, max_count=max_cnt)
    aa_items = [(_aa_key(aa), aa) for aa in picked_aas]
    logger.info("已筛选高价值蛋白 %d / %d 条，启动 5,000/片 ProstT5 离线提取...", len(aa_items), len(candidates))

    cache_pkl = paths["work_data"] / "prostt5_train_embs.pkl.gz"
    res = run_chunked_prostt5_embedding(
        aa_items,
        cache_pkl,
        chunk_size=5000,
        phold_db_dir=paths["db_root"] / "phold_db",
        max_aa_len=384,
        max_tokens=8192,
    )
    embs_dict: Dict[str, np.ndarray] = res["embs"]

    # 构建紧凑索引表 emb_table (K+0..K-1) 与与 judge_dataset tr_ids 严格对齐的 tr_emb_idx (N_tr, 32)
    ordered_keys = [k for k, _ in aa_items if k in embs_dict]
    key_to_row = {k: idx for idx, k in enumerate(ordered_keys)}
    emb_table = np.stack([embs_dict[k] for k in ordered_keys], axis=0).astype(np.float16)

    idx_rows = []
    for _, orfs in train_contigs:
        m = len(orfs)
        if m <= CTX_WIN_ORFS:
            starts = [0]
        else:
            starts = list(range(0, m - CTX_WIN_ORFS + 1, 16))
            if starts[-1] + CTX_WIN_ORFS < m:
                starts.append(m - CTX_WIN_ORFS)
        mat = np.full((len(starts), CTX_WIN_ORFS), -1, dtype=np.int32)
        for wi, st in enumerate(starts):
            ed = min(m, st + CTX_WIN_ORFS)
            for k in range(ed - st):
                ak = _aa_key(orfs[st + k][3])
                if ak in key_to_row:
                    mat[wi, k] = key_to_row[ak]
        idx_rows.append(mat)
    tr_emb_idx = np.concatenate(idx_rows, axis=0)

    ds = np.load(paths["work_data"] / "judge_dataset.npz", allow_pickle=False)
    if tr_emb_idx.shape[0] != len(ds["tr_vc"]):
        raise RuntimeError(f"ProstT5 对齐行数不一致: {tr_emb_idx.shape[0]} vs {len(ds['tr_vc'])}")

    out_idx = paths["work_data"] / "prostt5_train_index.npz"
    tmp_idx = paths["work_data"] / f".prostt5_train_index.tmp.{os.getpid()}.npz"
    np.savez(tmp_idx, emb_table=emb_table, tr_emb_idx=tr_emb_idx)
    tmp_idx.replace(out_idx)
    cov_slots = int(np.sum(tr_emb_idx >= 0))
    logger.info(
        "ProstT5 离线表征对齐完成: unique_embs=%d, 覆盖训练槽位=%d, 耗时 %.1fs -> %s",
        len(emb_table),
        cov_slots,
        time.perf_counter() - t0,
        out_idx,
    )


def _compute_multilabel_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    known_mask: np.ndarray,
    *,
    threshold: float = 0.5,
) -> Dict[str, Any]:
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

    valid_k = known_mask > 0.5
    yt = y_true[valid_k]
    yp = y_prob[valid_k]
    ypred = (yp >= threshold).astype(np.int32)

    per_class: Dict[str, Dict[str, float]] = {}
    f1_9_list: List[float] = []
    for ci, cname in enumerate(JUDGE_CLASS_NAMES):
        y_c = (yt[:, ci] > 0.5).astype(np.int32)
        pos_n = int(np.sum(y_c))
        if pos_n == 0 or pos_n == len(y_c):
            continue
        f1 = float(f1_score(y_c, ypred[:, ci], zero_division=0))
        auprc = float(average_precision_score(y_c, yp[:, ci]))
        auroc = float(roc_auc_score(y_c, yp[:, ci]))
        per_class[cname] = {
            "positives": pos_n,
            "f1": round(f1, 4),
            "auprc": round(auprc, 4),
            "auroc": round(auroc, 4),
        }
        if ci < 9:
            f1_9_list.append(f1)

    has_p08 = np.sum(yt[:, :9] > 0.5, axis=1) > 0
    if np.any(has_p08):
        pred_top1 = np.argmax(yp[has_p08, :9], axis=1)
        true_mat = yt[has_p08, :9] > 0.5
        top1_acc = float(np.mean(true_mat[np.arange(len(pred_top1)), pred_top1]))
        micro_f1_9 = float(f1_score((yt[:, :9] > 0.5).astype(np.int32), ypred[:, :9], average="micro", zero_division=0))
    else:
        top1_acc = 0.0
        micro_f1_9 = 0.0

    macro_f1_9 = float(np.mean(f1_9_list)) if f1_9_list else 0.0
    return {
        "n_known": int(np.sum(valid_k)),
        "n_p08_pos": int(np.sum(has_p08)),
        "top1_acc_p08": round(top1_acc, 4),
        "macro_f1_p08": round(macro_f1_9, 4),
        "micro_f1_p08": round(micro_f1_9, 4),
        "per_class": per_class,
    }


def _train_single_variant(
    *,
    use_aa_seq: bool,
    ds: Any,
    out_ckpt: Path,
    epochs: int,
    batch_size: int,
    lr: float,
    arch: str = "baseline",
    grad_accum: int = 1,
    prostt5_idx_path: Optional[Path] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    from sklearn.metrics import roc_auc_score

    torch.manual_seed(seed)
    np.random.seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    stat_mean = ds["stat_mean"]
    stat_std = ds["stat_std"]
    aa_mask_prob = 0.12 if (arch == "r1" and use_aa_seq) else (0.10 if (arch in ("r2", "r3") and use_aa_seq) else 0.0)
    use_distill = (arch in ("r2", "r3")) and use_aa_seq and prostt5_idx_path is not None and prostt5_idx_path.is_file()
    emb_table_t = None
    tr_emb_idx_arr = None
    distill_dim = PROSTT5_EMBED_DIM
    if use_distill:
        p5 = np.load(prostt5_idx_path, allow_pickle=False)
        emb_table_t = torch.from_numpy(p5["emb_table"].astype(np.float32))
        tr_emb_idx_arr = p5["tr_emb_idx"]
        distill_dim = int(emb_table_t.shape[1])

    model = build_orf_functional_judge(
        stat_mean=stat_mean,
        stat_std=stat_std,
        use_aa_seq=use_aa_seq,
        arch=arch,
        aa_mask_prob=aa_mask_prob,
        distill_dim=distill_dim,
    ).to(device)
    params = sum(p.numel() for p in model.parameters())
    tag = f"{arch}_{'aa_seq_ctx' if use_aa_seq else 'stat_only_ctx'}"
    logger.info(
        "启动训练变体 [%s]: use_aa_seq=%s, arch=%s, distill=%s, params=%d, device=%s",
        tag,
        use_aa_seq,
        arch,
        use_distill,
        params,
        device,
    )

    tr_tensors = [
        torch.from_numpy(ds["tr_ids"]),
        torch.from_numpy(ds["tr_lens"]),
        torch.from_numpy(ds["tr_stat"]),
        torch.from_numpy(ds["tr_vc"]),
        torch.from_numpy(ds["tr_y10"]),
        torch.from_numpy(ds["tr_ph"]),
        torch.from_numpy(ds["tr_kn"]),
    ]
    if use_distill and tr_emb_idx_arr is not None:
        tr_tensors.append(torch.from_numpy(tr_emb_idx_arr))
    tr_ds = TensorDataset(*tr_tensors)
    va_ds = TensorDataset(
        torch.from_numpy(ds["va_ids"]),
        torch.from_numpy(ds["va_lens"]),
        torch.from_numpy(ds["va_stat"]),
        torch.from_numpy(ds["va_vc"]),
        torch.from_numpy(ds["va_y10"]),
        torch.from_numpy(ds["va_ph"]),
        torch.from_numpy(ds["va_kn"]),
        torch.from_numpy(ds["va_unseen"]),
    )
    tr_loader = DataLoader(tr_ds, batch_size=batch_size, shuffle=True, pin_memory=(device.type == "cuda"))
    va_loader = DataLoader(va_ds, batch_size=batch_size, shuffle=False, pin_memory=(device.type == "cuda"))

    tr_vc = ds["tr_vc"]
    tr_vm = np.arange(CTX_WIN_ORFS)[None, :] < tr_vc[:, None]
    tr_km = tr_vm & (ds["tr_kn"] > 0.5)
    y10_valid = ds["tr_y10"][tr_km]
    pos_cnt = np.maximum(np.sum(y10_valid > 0.5, axis=0), 1.0)
    neg_cnt = np.maximum(len(y10_valid) - pos_cnt, 1.0)
    pw_10 = np.clip(np.sqrt(neg_cnt / pos_cnt), 1.0, 6.0).astype(np.float32)
    pos_weight_t = torch.tensor(pw_10, device=device, dtype=torch.float32)

    wd = 5e-4 if arch in ("r1", "r2", "r3") else 2e-4
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, epochs))
    bce_none = nn.BCEWithLogitsLoss(reduction="none", pos_weight=pos_weight_t)
    bce_phage = nn.BCEWithLogitsLoss(reduction="none")
    scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

    best_score = -1.0
    best_epoch = 0
    best_val_info: Dict[str, Any] = {}
    t_start = time.perf_counter()

    accum = max(1, int(grad_accum))
    for ep in range(1, epochs + 1):
        model.train()
        ep_loss = 0.0
        n_steps = 0
        optimizer.zero_grad(set_to_none=True)
        for step_idx, batch_tup in enumerate(tr_loader):
            if use_distill:
                ids, lens, st, vc, y10, ph, kn, eidx = batch_tup
            else:
                ids, lens, st, vc, y10, ph, kn = batch_tup
                eidx = None
            ids = ids.to(device, dtype=torch.long, non_blocking=True)
            lens = lens.to(device, dtype=torch.long, non_blocking=True)
            st = st.to(device, dtype=torch.float32, non_blocking=True)
            vc = vc.to(device, dtype=torch.long, non_blocking=True)
            y10 = y10.to(device, dtype=torch.float32, non_blocking=True)
            ph = ph.to(device, dtype=torch.float32, non_blocking=True)
            kn = kn.to(device, dtype=torch.float32, non_blocking=True)

            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                w_core_logit = None
                if arch == "r3":
                    out_tup = model(ids, lens, st, vc, return_seq_distill=use_distill, return_win_core=True)
                    if use_distill:
                        f_log, p_log, d_pred, w_core_logit = out_tup
                    else:
                        f_log, p_log, w_core_logit = out_tup
                        d_pred = None
                elif use_distill:
                    f_log, p_log, d_pred = model(ids, lens, st, vc, return_seq_distill=True)
                else:
                    f_log, p_log = model(ids, lens, st, vc)
                    d_pred = None
                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < vc[:, None]).to(torch.float32)
                km = (vm * kn).unsqueeze(-1)
                loss_f = (bce_none(f_log, y10) * km).sum() / km.sum().clamp(min=1.0) / float(NUM_JUDGE_CLASSES)
                loss_p = (bce_phage(p_log, ph) * vm).sum() / vm.sum().clamp(min=1.0)
                loss = 1.5 * loss_f + 1.0 * loss_p
                if arch in ("r1", "r2", "r3"):
                    # 显式强化宿主对抗防御 P9 与噬菌体同源 is_phage 的互斥约束
                    p9_prob = torch.sigmoid(f_log[:, :, 9])
                    ph_prob = torch.sigmoid(p_log)
                    adv_neg_mask = vm * kn * (y10[:, :, 9] > 0.5).to(torch.float32) * (ph < 0.5).to(torch.float32)
                    if torch.any(adv_neg_mask > 0):
                        mutex_pen = torch.relu(ph_prob + p9_prob - 0.90).pow(2)
                        w_mtx = 0.65 if arch == "r3" else 0.5
                        loss = loss + w_mtx * ((mutex_pen * adv_neg_mask).sum() / adv_neg_mask.sum().clamp(min=1.0))
                if arch == "r3" and w_core_logit is not None:
                    # 窗级完整度回归：监督滑窗内究竟凑齐了 P0..P4 五大核心模块的几成，强化 intact vs degraded 边界
                    core_pos_w = ((y10[:, :, :5] > 0.5).to(torch.float32) * (vm * kn).unsqueeze(-1)).max(dim=1).values
                    target_richness = core_pos_w.mean(dim=-1)
                    has_known_win = (vm * kn).sum(dim=1) > 0.5
                    if torch.any(has_known_win):
                        loss_wc = torch.nn.functional.smooth_l1_loss(
                            torch.sigmoid(w_core_logit[has_known_win]),
                            target_richness[has_known_win],
                        )
                        loss = loss + 0.4 * loss_wc

            if use_distill and d_pred is not None and eidx is not None and emb_table_t is not None:
                e_valid = (eidx >= 0) & (pos.cpu() < vc.cpu()[:, None])
                if torch.any(e_valid):
                    flat_t = emb_table_t[eidx[e_valid]].to(device, dtype=torch.float32)
                    flat_p = d_pred[e_valid.to(device)].float()
                    cos_l = (1.0 - torch.nn.functional.cosine_similarity(flat_p, flat_t, dim=-1)).mean()
                    l1_l = torch.nn.functional.smooth_l1_loss(flat_p, flat_t)
                    loss = loss + 0.5 * (0.7 * cos_l + 0.3 * l1_l)

            scaler.scale(loss / float(accum)).backward()
            if (step_idx + 1) % accum == 0 or (step_idx + 1) == len(tr_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)

            ep_loss += float(loss.item())
            n_steps += 1
        scheduler.step()

        model.eval()
        all_yt, all_yp, all_km, all_pt, all_pp, all_vm = [], [], [], [], [], []
        with torch.no_grad():
            for ids, lens, st, vc, y10, ph, kn, unseen_m in va_loader:
                ids = ids.to(device, dtype=torch.long, non_blocking=True)
                lens = lens.to(device, dtype=torch.long, non_blocking=True)
                st = st.to(device, dtype=torch.float32, non_blocking=True)
                vc = vc.to(device, dtype=torch.long, non_blocking=True)
                with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.bfloat16):
                    f_log, p_log = model(ids, lens, st, vc)
                pos = torch.arange(CTX_WIN_ORFS, device=device)[None, :]
                vm = (pos < vc[:, None]).cpu().numpy() & (unseen_m.numpy() > 0.5)
                km = vm & (kn.numpy() > 0.5)
                all_yt.append(y10.numpy())
                all_yp.append(torch.sigmoid(f_log).float().cpu().numpy())
                all_km.append(km.astype(np.float32))
                all_pt.append(ph.numpy())
                all_pp.append(torch.sigmoid(p_log).float().cpu().numpy())
                all_vm.append(vm.astype(np.float32))

        yt_c = np.concatenate(all_yt, axis=0)
        yp_c = np.concatenate(all_yp, axis=0)
        km_c = np.concatenate(all_km, axis=0)
        pt_c = np.concatenate(all_pt, axis=0)
        pp_c = np.concatenate(all_pp, axis=0)
        vm_c = np.concatenate(all_vm, axis=0)

        m_f = _compute_multilabel_metrics(yt_c, yp_c, km_c)
        vm_b = vm_c > 0.5
        ph_auroc = float(roc_auc_score((pt_c[vm_b] > 0.5).astype(np.int32), pp_c[vm_b]))
        score = m_f["macro_f1_p08"] + 0.5 * ph_auroc
        logger.info(
            "[%s] Epoch %d/%d loss=%.4f | zero-overlap val: MacroF1(P0..8)=%.4f Top1Acc=%.4f PhageAUROC=%.4f",
            tag,
            ep,
            epochs,
            ep_loss / max(1, n_steps),
            m_f["macro_f1_p08"],
            m_f["top1_acc_p08"],
            ph_auroc,
        )
        if score > best_score:
            best_score = score
            best_epoch = ep
            best_val_info = {
                "macro_f1_p08": m_f["macro_f1_p08"],
                "top1_acc_p08": m_f["top1_acc_p08"],
                "ph_auroc": round(ph_auroc, 4),
            }
            tmp_pt = out_ckpt.with_name(f".{out_ckpt.name}.tmp.{os.getpid()}.pt")
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "stat_mean": stat_mean,
                    "stat_std": stat_std,
                    "use_aa_seq": use_aa_seq,
                    "arch": arch,
                    "params": params,
                    "best_epoch": best_epoch,
                    "best_val_info": best_val_info,
                },
                tmp_pt,
            )
            tmp_pt.replace(out_ckpt)

    del model, tr_loader, va_loader
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "variant": tag,
        "use_aa_seq": use_aa_seq,
        "params": params,
        "best_epoch": best_epoch,
        "best_val_info": best_val_info,
        "elapsed_sec": round(time.perf_counter() - t_start, 2),
        "ckpt_path": str(out_ckpt),
    }


def run_step_train(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    arch = str(getattr(args, "arch", "baseline"))
    variant = str(getattr(args, "variant", "both"))
    bs = int(args.batch_size)
    ga = int(getattr(args, "grad_accum", 1))
    logger.info("=== [Judge Step 3 | arch=%s | variant=%s] 训练对照变体 (bs=%d, accum=%d) ===", arch, variant, bs, ga)
    ds = np.load(paths["work_data"] / "judge_dataset.npz", allow_pickle=False)
    summary_path = paths["work_model"] / "train_summary.json"
    summary: Dict[str, Any] = {"arch": arch}
    if summary_path.is_file():
        summary.update(json.loads(summary_path.read_text(encoding="utf-8")))
    if variant in ("both", "statonly"):
        summary["stat_only"] = _train_single_variant(
            use_aa_seq=False,
            ds=ds,
            out_ckpt=paths["work_model"] / "orf_judge_statonly.pt",
            epochs=int(args.epochs),
            batch_size=bs,
            lr=float(args.lr),
            arch=arch,
            grad_accum=ga,
        )
    if variant in ("both", "aaseq"):
        # R1/R2/R3 序列分支内部包含自注意力，自动限制单步物理微批至 16 防 8GB 显存溢出，并用等价梯度累积补偿
        seq_bs = min(bs, 16) if arch in ("r1", "r2", "r3") else bs
        seq_ga = max(ga, max(1, bs // seq_bs)) if arch in ("r1", "r2", "r3") else ga
        summary["aa_seq_ctx"] = _train_single_variant(
            use_aa_seq=True,
            ds=ds,
            out_ckpt=paths["work_model"] / "orf_judge_seq.pt",
            epochs=int(args.epochs),
            batch_size=seq_bs,
            lr=float(args.lr),
            arch=arch,
            grad_accum=seq_ga,
            prostt5_idx_path=paths["work_data"] / "prostt5_train_index.npz",
        )
    _atomic_write_json(summary_path, summary)


def _extract_stage1_2_orf_preds(
    model_dir: Path,
    fasta_list: List[Tuple[str, Path]],
    *,
    workers: int = 16,
) -> Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]]:
    scanner = GenomeScanner.from_model_dir(model_dir, workers=workers)
    out: Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]] = defaultdict(dict)
    try:
        for _, fa in fasta_list:
            contigs = dict(iter_fasta(fa))
            tasks = [
                (cid, seq, scanner.win_size, scanner.step_size, True, scanner.feature_profile)
                for cid, seq in contigs.items()
            ]
            extracted = []
            with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, max(1, len(tasks)))) as ex:
                for res in ex.map(_extract_contig_worker, tasks):
                    extracted.append(res)

            feats_l, codes_l, len_l, otk_l, ocn_l, cids_l, starts_l, ends_l = [], [], [], [], [], [], [], []
            for item in extracted:
                cid = item["contig_id"]
                s_up = contigs[cid].upper()
                feats_l.append(item["features"])
                otk_l.append(item["orf_tokens"])
                ocn_l.append(item["orf_counts"])
                for s, e in zip(item["starts"], item["ends"]):
                    sub = s_up[int(s) : int(e)]
                    enc = np.full(scanner.win_size, 4, dtype=np.uint8)
                    raw = encode_dna(sub)[: scanner.win_size]
                    enc[: len(raw)] = raw
                    codes_l.append(enc)
                    len_l.append(len(raw))
                    cids_l.append(cid)
                    starts_l.append(int(s))
                    ends_l.append(int(e))

            feats_arr = np.concatenate(feats_l, axis=0)
            codes_arr = np.stack(codes_l, axis=0)
            len_arr = np.asarray(len_l, dtype=np.int64)
            otk_arr = np.concatenate(otk_l, axis=0)
            ocn_arr = np.concatenate(ocn_l, axis=0)
            scanner._predict_windows_with_profiles(
                codes_arr,
                len_arr,
                feats_arr,
                orf_tokens=otk_arr,
                orf_counts=ocn_arr,
                contig_ids=np.asarray(cids_l),
                starts=np.asarray(starts_l, dtype=np.int64),
                ends=np.asarray(ends_l, dtype=np.int64),
                return_orf_preds=True,
            )
            aux = scanner._last_func_aux or {}
            ph_probs = aux["orf_phage_probs"]
            fn_probs = aux["orf_func_probs"]

            best_cdist: Dict[Tuple[str, int, int, int], float] = {}
            for wi in range(len(cids_l)):
                cid = cids_l[wi]
                ws, we = starts_l[wi], ends_l[wi]
                wlen = max(1.0, float(we - ws))
                cnt = min(otk_arr.shape[1], int(ocn_arr[wi]))
                for k in range(cnt):
                    rs = float(otk_arr[wi, k, 6])
                    re_ = float(otk_arr[wi, k, 7])
                    gs = round(ws + rs * wlen)
                    ge = round(ws + re_ * wlen)
                    st = 1 if float(otk_arr[wi, k, 1]) >= 0.0 else -1
                    cdist = abs(0.5 * (rs + re_) - 0.5)
                    key4 = (cid, gs, ge, st)
                    if key4 not in best_cdist or cdist < best_cdist[key4]:
                        best_cdist[key4] = cdist
                        out[cid][(gs, ge, st)] = (float(ph_probs[wi, k]), fn_probs[wi, k, :9].astype(np.float32))
    finally:
        del scanner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return out


def _infer_val_logits_for_ckpt(
    ckpt_path: Path,
    ds: Any,
    device: str,
    *,
    batch_size: int = 64,
) -> Tuple[np.ndarray, np.ndarray]:
    """在严格零重叠训练的验证集 va_* 上推理提取有效未掩码 ORF 的原始 logits (N_val_unseen, 10) 与 (N_val_unseen,)。"""
    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(ck.get("arch", "baseline")),
    ).to(device)
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()

    va_ds = TensorDataset(
        torch.from_numpy(ds["va_ids"]),
        torch.from_numpy(ds["va_lens"]),
        torch.from_numpy(ds["va_stat"]),
        torch.from_numpy(ds["va_vc"]),
    )
    va_loader = DataLoader(va_ds, batch_size=batch_size, shuffle=False)
    f_list, p_list = [], []
    with torch.no_grad():
        for ids, lens, st, vc in va_loader:
            ids = ids.to(device, dtype=torch.long)
            lens = lens.to(device, dtype=torch.long)
            st = st.to(device, dtype=torch.float32)
            vc = vc.to(device, dtype=torch.long)
            with torch.amp.autocast("cuda", enabled=(str(device).startswith("cuda")), dtype=torch.bfloat16):
                f_log, p_log = model(ids, lens, st, vc)
            f_list.append(f_log.float().cpu().numpy())
            p_list.append(p_log.float().cpu().numpy())
    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    pos = np.arange(CTX_WIN_ORFS)[None, :]
    vm = (pos < ds["va_vc"][:, None]) & (ds["va_unseen"] > 0.5)
    f_all = np.concatenate(f_list, axis=0)[vm]
    p_all = np.concatenate(p_list, axis=0)[vm]
    return f_all, p_all


def fit_and_save_zero_leak_calibrator(
    stat_ckpt_path: Path,
    seq_ckpt_path: Path,
    ds_path: Path,
    out_npz_path: Path,
    *,
    device: str,
) -> Dict[str, Any]:
    """仅使用严格零重合验证集 (judge_dataset.npz 中的 va_* 且 va_unseen==1) 拟合按类 Logit 融合与校准器。"""
    ds = np.load(ds_path, allow_pickle=False)
    pos = np.arange(CTX_WIN_ORFS)[None, :]
    vm = (pos < ds["va_vc"][:, None]) & (ds["va_unseen"] > 0.5)
    va_y10 = ds["va_y10"][vm]
    va_kn = ds["va_kn"][vm]
    va_ph = ds["va_ph"][vm]

    sf, sp = _infer_val_logits_for_ckpt(stat_ckpt_path, ds, device)
    qf, qp = _infer_val_logits_for_ckpt(seq_ckpt_path, ds, device)
    cal = fit_logit_blend_and_calibrator(sf, qf, va_y10, va_kn, sp, qp, va_ph)
    cal["single_seq"] = fit_logit_calibrator_on_val(qf, va_y10, va_kn, qp, va_ph)

    out_npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_npz_path,
        func_alphas=cal["func_alphas"],
        phage_alpha=np.array([cal["phage_alpha"]], dtype=np.float32),
        func_bias=cal["func_bias"],
        phage_bias=np.array([cal["phage_bias"]], dtype=np.float32),
        single_seq_func_bias=cal["single_seq"]["func_bias"],
        single_seq_phage_bias=np.array([cal["single_seq"]["phage_bias"]], dtype=np.float32),
    )
    logger.info(
        "零泄露验证集 Logit 校准器已拟合保存 -> %s (phage_alpha=%.2f, phage_bias=%.3f)",
        out_npz_path,
        cal["phage_alpha"],
        cal["phage_bias"],
    )
    return cal


def run_step_benchmark(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    from sklearn.metrics import average_precision_score, roc_auc_score

    logger.info("=== [Judge Step 4] 零泄露同台评测: Stage 1.2 vs Judge(Stat) vs Judge(AA-Seq) ===")
    with gzip.open(paths["work_data"] / "eval_truth_cache.pkl.gz", "rb") as fh:
        cache = pickle.load(fh)
    eval_contigs: Dict[str, Dict[str, List[Tuple[int, int, int, str]]]] = cache["eval_contigs"]
    eval_labels: Dict[str, Dict[str, Any]] = cache["eval_labels"]

    eval_files: List[Tuple[str, Path]] = [("v1_test_chimeras", paths["bench_v1"] / "test_chimeras.fna")]
    for fa in sorted(paths["unseen_dir"].glob("*.fasta")):
        if not fa.name.startswith("_"):
            eval_files.append((fa.stem, fa))

    t0 = time.perf_counter()
    s12_preds = _extract_stage1_2_orf_preds(paths["s12_model_dir"], eval_files, workers=min(16, int(args.cpus)))
    logger.info("Stage 1.2 全量推理抽样完成: 耗时 %.2fs", time.perf_counter() - t0)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    judge_preds: Dict[str, Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]]] = {}
    judge_logits: Dict[str, Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]]] = {}
    judge_times: Dict[str, float] = {}
    used_ckpts: Dict[str, Path] = {}
    for jname, ckpt_name in [("judge_statonly", "orf_judge_statonly.pt"), ("judge_aaseq", "orf_judge_seq.pt")]:
        ckpt_path = paths["work_model"] / ckpt_name
        if not ckpt_path.is_file() and jname == "judge_statonly":
            fallback_stat = paths["work_model"].parent / "orf_judge_ablation_r1" / ckpt_name
            if fallback_stat.is_file():
                ckpt_path = fallback_stat
        used_ckpts[jname] = ckpt_path
        ck = torch.load(ckpt_path, map_location=device, weights_only=False)
        model = build_orf_functional_judge(
            stat_mean=ck["stat_mean"],
            stat_std=ck["stat_std"],
            use_aa_seq=bool(ck["use_aa_seq"]),
            arch=str(ck.get("arch", "baseline")),
        ).to(device)
        model.load_state_dict(ck["state_dict"], strict=True)
        model.eval()

        t_j = time.perf_counter()
        jmap: Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]] = defaultdict(dict)
        lmap: Dict[str, Dict[Tuple[int, int, int], Tuple[float, np.ndarray]]] = defaultdict(dict)
        for cmap in eval_contigs.values():
            for cid, orfs in cmap.items():
                res = predict_contig_orfs_with_judge(model, orfs, device=device, batch_size=32, return_logits=True)
                for oi, (gs, ge, st, _) in enumerate(orfs):
                    jmap[cid][(gs, ge, st)] = (float(res["phage_probs"][oi]), res["func10_probs"][oi])
                    lmap[cid][(gs, ge, st)] = (float(res["phage_logits"][oi]), res["func10_logits"][oi])
        judge_times[jname] = round(time.perf_counter() - t_j, 2)
        judge_preds[jname] = jmap
        judge_logits[jname] = lmap
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    ds_path = paths["work_data"] / "judge_dataset.npz"
    calibrator = None
    if ds_path.is_file():
        calibrator = fit_and_save_zero_leak_calibrator(
            used_ckpts["judge_statonly"],
            used_ckpts["judge_aaseq"],
            ds_path,
            paths["work_model"] / "logit_calibrator.npz",
            device=device,
        )

    yt_all, km_all, ph_true_all, df_true_all = [], [], [], []
    s12_f9, s12_ph = [], []
    js_f10, js_ph, js_f10_l, js_ph_l = [], [], [], []
    ja_f10, ja_ph, ja_f10_l, ja_ph_l = [], [], [], []

    for cmap in eval_contigs.values():
        for cid, orfs in cmap.items():
            s12_c = s12_preds.get(cid, {})
            js_c = judge_preds["judge_statonly"].get(cid, {})
            ja_c = judge_preds["judge_aaseq"].get(cid, {})
            js_lc = judge_logits["judge_statonly"].get(cid, {})
            ja_lc = judge_logits["judge_aaseq"].get(cid, {})
            for gs, ge, st, aa in orfs:
                ak = _aa_key(aa)
                lab = eval_labels[ak]
                if not lab["strictly_unseen"]:
                    continue
                k3 = (gs, ge, st)
                if k3 not in s12_c or k3 not in js_c or k3 not in ja_c:
                    continue
                yt_all.append(lab["y10"])
                km_all.append(lab["y10_known"])
                ph_true_all.append(lab["is_phage"])
                df_true_all.append(1.0 if lab["is_defense_finder"] else 0.0)

                p_s, f_s = s12_c[k3]
                s12_ph.append(p_s)
                s12_f9.append(f_s)

                p_js, f_js = js_c[k3]
                js_ph.append(p_js)
                js_f10.append(f_js)
                pl_js, fl_js = js_lc[k3]
                js_ph_l.append(pl_js)
                js_f10_l.append(fl_js)

                p_ja, f_ja = ja_c[k3]
                ja_ph.append(p_ja)
                ja_f10.append(f_ja)
                pl_ja, fl_ja = ja_lc[k3]
                ja_ph_l.append(pl_ja)
                ja_f10_l.append(fl_ja)

    yt_arr = np.stack(yt_all)
    km_arr = np.asarray(km_all, dtype=np.float32)
    ph_t = np.asarray(ph_true_all, dtype=np.int32)
    df_t = np.asarray(df_true_all, dtype=np.int32)

    s12_f9_arr = np.stack(s12_f9)
    s12_f10_pad = np.zeros((len(s12_f9), NUM_JUDGE_CLASSES), dtype=np.float32)
    s12_f10_pad[:, :9] = s12_f9_arr
    js_f10_arr = np.stack(js_f10)
    ja_f10_arr = np.stack(ja_f10)
    js_f10_l_arr = np.stack(js_f10_l)
    ja_f10_l_arr = np.stack(ja_f10_l)
    js_ph_l_arr = np.asarray(js_ph_l, dtype=np.float32)
    ja_ph_l_arr = np.asarray(ja_ph_l, dtype=np.float32)

    def _eval_one(f10: np.ndarray, ph_p: np.ndarray, has_p9: bool) -> Dict[str, Any]:
        mf = _compute_multilabel_metrics(yt_arr, f10, km_arr)
        ph_auroc = float(roc_auc_score(ph_t, ph_p))
        ph_auprc = float(average_precision_score(ph_t, ph_p))
        df_mask = df_t == 1
        df_fp_as_phage = float(np.mean(ph_p[df_mask] >= 0.5)) if np.any(df_mask) else 0.0
        out_d: Dict[str, Any] = {
            "n_strictly_unseen_eval_orfs": int(len(ph_t)),
            "is_phage_auroc": round(ph_auroc, 4),
            "is_phage_auprc": round(ph_auprc, 4),
            "defense_finder_count": int(np.sum(df_t)),
            "defense_finder_misclassified_as_phage_rate": round(df_fp_as_phage, 4),
            "func_metrics": mf,
        }
        if has_p9 and np.sum(df_t) > 0:
            p9_score = f10[:, 9]
            out_d["defense_finder_p9_auroc"] = round(float(roc_auc_score(df_t, p9_score)), 4)
            out_d["defense_finder_p9_auprc"] = round(float(average_precision_score(df_t, p9_score)), 4)
        return out_d

    ens_f10_arr = 0.5 * (js_f10_arr + ja_f10_arr)
    ens_ph_arr = 0.5 * (np.asarray(js_ph) + np.asarray(ja_ph))
    cal_f10_arr, cal_ph_arr = apply_blended_logit_calibration(
        js_f10_l_arr,
        ja_f10_l_arr,
        js_ph_l_arr,
        ja_ph_l_arr,
        calibrator,
    )
    cm_f10_arr, cm_ph_arr = blend_with_stage1_2_cross_modal(
        cal_f10_arr,
        cal_ph_arr,
        s12_f9_arr,
        np.asarray(s12_ph, dtype=np.float32),
        s12_phage_weight=0.22,
        s12_func_weight=0.05,
    )
    report = {
        "arch": str(getattr(args, "arch", "baseline")),
        "eval_orfs_aligned": int(len(ph_t)),
        "judge_inference_sec": judge_times,
        "stage1_2_baseline": _eval_one(s12_f10_pad, np.asarray(s12_ph), has_p9=False),
        "judge_statonly": _eval_one(js_f10_arr, np.asarray(js_ph), has_p9=True),
        "judge_aaseq": _eval_one(ja_f10_arr, np.asarray(ja_ph), has_p9=True),
        "judge_ensemble_50_50": _eval_one(ens_f10_arr, ens_ph_arr, has_p9=True),
        "judge_calibrated_ensemble": _eval_one(cal_f10_arr, cal_ph_arr, has_p9=True),
        "judge_cross_modal_s12": _eval_one(cm_f10_arr, cm_ph_arr, has_p9=True),
    }
    if calibrator is not None and "single_seq" in calibrator:
        s_cal_f10, s_cal_ph = apply_logit_calibration(ja_f10_l_arr, ja_ph_l_arr, calibrator["single_seq"])
        report["judge_aaseq_calibrated"] = _eval_one(s_cal_f10, s_cal_ph, has_p9=True)
    out_json = paths["work_model"] / "orf_judge_vs_stage1_2.json"
    _atomic_write_json(out_json, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="OrfFunctionalJudge 独立扩展模块实证消融验证")
    parser.add_argument(
        "--step",
        choices=("eval_cache", "prep_data", "prostt5_cache", "train", "benchmark", "all"),
        required=True,
    )
    parser.add_argument(
        "--phage-data-root",
        default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")),
    )
    parser.add_argument("--arch", choices=("baseline", "r1", "r2", "r3"), default="baseline")
    parser.add_argument("--variant", choices=("both", "statonly", "aaseq"), default="both")
    parser.add_argument("--prostt5-max-count", type=int, default=40000)
    parser.add_argument("--cpus", type=int, default=max(1, min(24, (os.cpu_count() or 8) - 4)))
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--grad-accum", type=int, default=1)
    parser.add_argument("--lr", type=float, default=8e-4)
    args = parser.parse_args()

    paths = _resolve_paths(Path(args.phage_data_root).resolve(), arch=str(args.arch))
    steps = ("eval_cache", "prep_data", "train", "benchmark") if args.step == "all" else (args.step,)
    for st in steps:
        if st == "eval_cache":
            run_step_eval_cache(args, paths)
        elif st == "prep_data":
            run_step_prep_data(args, paths)
        elif st == "prostt5_cache":
            run_step_prostt5_cache(args, paths)
        elif st == "train":
            run_step_train(args, paths)
        elif st == "benchmark":
            run_step_benchmark(args, paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
