# -*- coding: utf-8 -*-
"""
Stage 1.2 P0 多教师离线蒸馏与隔离消融验证流水线：
1. --step hmm     : 使用 WSL pyhmmer 多核并行扫描全量唯一 ORF（dbAPIS + DefenseFinder + VS2 Pfam-Viruses），支持分片 Checkpoint；
2. --step phold   : 使用 WSL GPU phold（本地缓存 ProstT5_fp16 + Foldseek）对无三源已知注释的暗物质蛋白分片提取结构语义；
3. --step targets : 合并三源 + HMM + phold 结构证据生成隔离版 _functional.npz、_semantic.npz、对抗校准 teacher_oof 与难负例权重；
4. --step train   : 零新增推理参数，从 Stage 1.2 现有权重热启动差分学习率微调并重训下游双 Refiner；
5. --step eval    : 与原 Stage 1.2 基线在 v1 test 窗口、嵌合体及 unseen_real_genomes 上进行严格同台冷对比。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import os
import pickle
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.phage_discovery.data.functional_partitions import (  # noqa: E402
    build_p0_teacher_calibration,
    build_window_and_orf_functional_targets,
    classify_protein_with_p0_teachers,
)
from src.phage_discovery.inference.scanner import GenomeScanner  # noqa: E402
from src.phage_discovery.student.distilled_student_v4 import train_distilled_student_v4  # noqa: E402
from src.phage_discovery.teachers.hmm_adversarial_teacher import (  # noqa: E402
    resolve_hmm_library_paths,
    run_chunked_hmm_teacher,
)
from src.phage_discovery.teachers.phold_teacher import (  # noqa: E402
    default_phold_db_dir,
    run_chunked_phold_teacher,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("p0_distill_ablation")

ALL_9_PARTS: Tuple[str, ...] = (
    "windows",
    "chimeras",
    "mined",
    "hard_neg",
    "ext_rare",
    "ext_windows",
    "ext_mined",
    "hard_v4",
    "rare_multiscale",
)


def _aa_key(aa: str) -> str:
    return hashlib.md5(aa.encode("ascii", errors="ignore")).hexdigest()[:16]


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _atomic_save_npz(path: Path, **arrays: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(path)


def _hardlink_or_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _load_merged_phrog_phold_annots(pharokka_db_dir: Path) -> Dict[str, Tuple[str, str]]:
    merged: Dict[str, Tuple[str, str]] = {}
    phrog_tsv = pharokka_db_dir / "phrog_annot_v4.tsv"
    phold_tsv = pharokka_db_dir / "phold_annots_updated.tsv"
    if phrog_tsv.is_file():
        with open(phrog_tsv, "r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                pid = str(row.get("phrog", "")).strip()
                if not pid:
                    continue
                key = pid if pid.startswith("phrog_") else f"phrog_{pid}"
                merged[key] = (
                    str(row.get("category", "unknown function")).strip(),
                    str(row.get("annot", "")).strip(),
                )
    if phold_tsv.is_file():
        with open(phold_tsv, "r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                pid = str(row.get("phrog", "")).strip()
                if not pid:
                    continue
                key = pid if pid.startswith("phrog_") else f"phrog_{pid}"
                fn = str(row.get("function", "")).strip()
                pr = str(row.get("product", "")).strip()
                old_cat, old_annot = merged.get(key, ("unknown function", ""))
                new_cat = fn if (fn and fn.lower() != "unknown function") else old_cat
                new_annot = pr if (pr and "hypothetical" not in pr.lower()) else old_annot
                merged[key] = (new_cat, new_annot)
    return merged


def _build_dark_matter_items(
    s12_cache_dir: Path,
    *,
    min_aa_len: int = 30,
    max_aa_len: int = 600,
    include_hypothetical_gbk: bool = True,
) -> List[Tuple[str, str]]:
    with gzip.open(s12_cache_dir / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        orfs_data = pickle.load(fh)
    unique_aas: List[str] = list(orfs_data["unique_aas"])
    part_contig_orfs = orfs_data["part_contig_orfs"]

    with gzip.open(s12_cache_dir / "diamond_aa_hits.pkl.gz", "rb") as fh:
        dm_hits: Dict[str, str] = pickle.load(fh)["hits"]
    with gzip.open(s12_cache_dir / "phrog_aa_hits.pkl.gz", "rb") as fh:
        ph_hits: Dict[str, str] = pickle.load(fh)["hits"]
    with gzip.open(s12_cache_dir / "gbk_aa_index.pkl.gz", "rb") as fh:
        exact_prod: Dict[str, str] = pickle.load(fh)["exact_prod"]

    # 第一梯队：最核心 6 个难/稀有/挖掘分片；第二梯队：chimeras；第三梯队：windows
    tier1_aas: Set[str] = set()
    for p_name in ("hard_neg", "hard_v4", "rare_multiscale", "ext_rare", "mined", "ext_mined"):
        for lst in part_contig_orfs.get(p_name, {}).values():
            for _, _, _, aa in lst:
                tier1_aas.add(aa)
    tier2_aas: Set[str] = set()
    for lst in part_contig_orfs.get("chimeras", {}).values():
        for _, _, _, aa in lst:
            tier2_aas.add(aa)

    t1_items: List[Tuple[str, str]] = []
    t2_items: List[Tuple[str, str]] = []
    t3_items: List[Tuple[str, str]] = []
    for aa in unique_aas:
        if not aa or "*" in aa or not (int(min_aa_len) <= len(aa) <= int(max_aa_len)):
            continue
        ak = _aa_key(aa)
        if ak in dm_hits or ak in ph_hits:
            continue
        gb_p = exact_prod.get(aa, "")
        is_hyp = (not gb_p) or ("hypothetical" in gb_p.lower())
        if include_hypothetical_gbk and not is_hyp:
            continue
        item = (ak, aa)
        if aa in tier1_aas:
            t1_items.append(item)
        elif aa in tier2_aas:
            t2_items.append(item)
        else:
            t3_items.append(item)

    merged = t1_items + t2_items + t3_items
    logger.info(
        "筛选暗物质蛋白待结构扫库集 (len=%d..%d aa): total=%d (核心6难分片=%d, chimeras=%d, windows=%d)",
        min_aa_len,
        max_aa_len,
        len(merged),
        len(t1_items),
        len(t2_items),
        len(t3_items),
    )
    return merged


def run_step_hmm(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [P0 Step 1] 运行 pyhmmer 离线多库 HMM 扫描 ===")
    with gzip.open(paths["s12_cache"] / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        unique_aas: List[str] = list(pickle.load(fh)["unique_aas"])
    aa_items = [(_aa_key(aa), aa) for aa in unique_aas]
    libs = resolve_hmm_library_paths(db_root=paths["db_root"])
    out_cache = paths["p0_cache"] / "p0_hmm_aa_hits.pkl.gz"
    state = run_chunked_hmm_teacher(
        aa_items,
        out_cache,
        libs_cfg=libs,
        selected_libs=("dbapis", "defense_finder", "wsl_vs2_pfam_vir"),
        chunk_size=int(args.hmm_chunk_size),
        cpus=int(args.cpus),
    )
    logger.info("HMM 离线扫描完成: 累计命中 %d / %d 条唯一蛋白", len(state["hits"]), len(aa_items))


def run_step_phold(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [P0 Step 2] 运行 GPU phold (ProstT5+Foldseek) 暗物质结构语义扫描 ===")
    dark_items = _build_dark_matter_items(
        paths["s12_cache"],
        min_aa_len=30,
        max_aa_len=int(args.phold_max_aa_len),
        include_hypothetical_gbk=True,
    )
    if args.phold_max_items > 0:
        dark_items = dark_items[:int(args.phold_max_items)]
        logger.info("受 --phold-max-items=%d 约束，截断本次扫描规模。", len(dark_items))
    out_cache = paths["p0_cache"] / "p0_phold_aa_hits.pkl.gz"
    state = run_chunked_phold_teacher(
        dark_items,
        out_cache,
        db_dir=default_phold_db_dir(),
        chunk_size=int(args.phold_chunk_size),
        batch_size=int(args.phold_batch_size),
        max_aa_len=int(args.phold_max_aa_len),
        threads=int(args.cpus),
    )
    logger.info("phold 结构扫描完成: 累计结构召回 %d / %d 条暗物质蛋白", len(state["hits"]), len(dark_items))


def run_step_targets(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [P0 Step 3] 融合三源+HMM+phold 构建 P0 隔离特征、软标签与对抗权重 ===")
    t0 = time.perf_counter()

    # 1. 硬链接/复刻基础无改动的特征缓存与 fasta
    p0_feat = paths["p0_feat"]
    s12_feat = paths["s12_feat"]
    p0_feat.mkdir(parents=True, exist_ok=True)
    for part in ALL_9_PARTS:
        for suf in (".npz", "_orf_tokens_stage1.npz"):
            _hardlink_or_copy(s12_feat / f"train_{part}{suf}", p0_feat / f"train_{part}{suf}")
    _hardlink_or_copy(paths["s12_data"] / "train_rare_multiscale.fna", paths["p0_data"] / "train_rare_multiscale.fna")
    _hardlink_or_copy(paths["s12_data"] / "train_rare_multiscale_truth.tsv", paths["p0_data"] / "train_rare_multiscale_truth.tsv")

    # 2. 加载三源索引 + P0 HMM/phold 缓存
    with gzip.open(paths["s12_cache"] / "gbk_aa_index.pkl.gz", "rb") as fh:
        gbk_idx = pickle.load(fh)
    exact_prod: Dict[str, str] = gbk_idx["exact_prod"]
    cterm20_prod: Dict[str, List[Tuple[int, str]]] = gbk_idx["cterm20_prod"]
    with gzip.open(paths["s12_cache"] / "diamond_aa_hits.pkl.gz", "rb") as fh:
        dmnd_hits: Dict[str, str] = pickle.load(fh)["hits"]
    with gzip.open(paths["s12_cache"] / "phrog_aa_hits.pkl.gz", "rb") as fh:
        phrog_hits: Dict[str, str] = pickle.load(fh)["hits"]
    with gzip.open(paths["s12_cache"] / "all_9_parts_orfs.pkl.gz", "rb") as fh:
        part_contig_orfs = pickle.load(fh)["part_contig_orfs"]

    hmm_hits: Dict[str, Any] = {}
    hmm_p = paths["p0_cache"] / "p0_hmm_aa_hits.pkl.gz"
    if hmm_p.exists():
        with gzip.open(hmm_p, "rb") as fh:
            hmm_hits = pickle.load(fh)["hits"]
    phold_hits: Dict[str, Any] = {}
    phold_p = paths["p0_cache"] / "p0_phold_aa_hits.pkl.gz"
    if phold_p.exists():
        with gzip.open(phold_p, "rb") as fh:
            phold_hits = pickle.load(fh)["hits"]

    phold_phrog_map = _load_merged_phrog_phold_annots(paths["db_root"] / "pharokka_db")

    all_aas: Set[str] = set()
    for c_map in part_contig_orfs.values():
        for lst in c_map.values():
            for _, _, _, aa in lst:
                all_aas.add(aa)

    def _lookup_gbk_product(aa: str) -> str:
        p = exact_prod.get(aa)
        if p:
            return p
        if len(aa) >= 25:
            p = exact_prod.get(aa[1:])
            if p:
                return p
            for clen, cprod in cterm20_prod.get(aa[-20:], []):
                if abs(clen - len(aa)) <= max(5, int(0.15 * len(aa))):
                    return cprod
        return ""

    aa_cls_cache: Dict[str, Dict[str, Any]] = {}
    adv_host_aa_cnt = 0
    for aa in all_aas:
        gbk_p = _lookup_gbk_product(aa)
        ak = _aa_key(aa)
        dm_t = dmnd_hits.get(ak, "")
        ph_id = phrog_hits.get(ak, "")
        ph_cat, ph_ann = ("", "")
        if ph_id:
            pkey = ph_id if ph_id.startswith("phrog_") else f"phrog_{ph_id}"
            ph_cat, ph_ann = phold_phrog_map.get(pkey, ("unknown function", ""))
        cls = classify_protein_with_p0_teachers(
            phrog_category=ph_cat,
            phrog_annot=ph_ann,
            diamond_title=dm_t,
            gbk_product=gbk_p,
            phold_hit=phold_hits.get(ak),
            hmm_hit=hmm_hits.get(ak),
        )
        if cls["adversarial_host_flag"]:
            adv_host_aa_cnt += 1
        aa_cls_cache[aa] = cls

    # 3. 与 Stage 1.2 完全相同的泄露 rare_ext accession 过滤逻辑
    leak_info = json.loads((paths["s12_data"] / "leaked_rare_accessions.json").read_text(encoding="utf-8"))
    leaked_accs: Set[str] = {
        x["accession"]
        for x in leak_info["filtered_leaked_accessions"]
        if x.get("tax_group") == "rare_ext" and float(x.get("eval_21mer_containment", 0.0)) >= 0.90
    }
    ext_rare_cid_map: Dict[str, str] = {}
    for tsv in (paths["train_v3"] / "ext_rare_truth.tsv", paths["train_v3"] / "ext_windows_truth.tsv"):
        if tsv.exists():
            with open(tsv, "r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    ext_rare_cid_map[row["contig_id"].strip()] = row["phage_acc"].strip()

    all_clean_y: List[np.ndarray] = []
    all_func_t: List[np.ndarray] = []
    all_adv_cnt: List[np.ndarray] = []
    summary: Dict[str, Any] = {}

    for part in ALL_9_PARTS:
        with np.load(s12_feat / f"train_{part}.npz", allow_pickle=True) as d, np.load(
            s12_feat / f"train_{part}_orf_tokens_stage1.npz"
        ) as ot:
            cids = d["contig_ids"]
            starts = d["starts"]
            ends = d["ends"]
            labels = d["labels"].astype(np.int8)
            tokens = ot["tokens"]
            counts = ot["counts"]

        contig_annotated = {
            cid: [(s, e, st, aa_cls_cache[aa]) for s, e, st, aa in lst]
            for cid, lst in part_contig_orfs[part].items()
        }
        tgt = build_window_and_orf_functional_targets(
            cids,
            starts,
            ends,
            labels,
            tokens,
            counts,
            contig_annotated,
            clean_contradictory_negatives=(part not in ("hard_neg", "hard_v4", "rare_multiscale")),
            iou_threshold=0.80,
            non_clean_contig_prefixes=("ARCHAEA_", "HARDV4_ARCH_"),
        )
        if part in ("ext_rare", "ext_windows") and leaked_accs:
            cl = tgt["clean_labels"].copy()
            for wi, cid in enumerate(cids):
                if ext_rare_cid_map.get(str(cid), "") in leaked_accs:
                    cl[wi] = -1
            tgt["clean_labels"] = cl

        _atomic_save_npz(p0_feat / f"train_{part}_functional.npz", **tgt)
        _atomic_save_npz(
            p0_feat / f"train_{part}_semantic.npz",
            sem_targets=tgt["sem_targets"],
            sem_valid_mask=np.ones(len(labels), dtype=np.float32),
            clean_labels=tgt["clean_labels"],
        )
        all_clean_y.append(tgt["clean_labels"])
        all_func_t.append(tgt["func_targets"])
        all_adv_cnt.append(tgt["adv_host_counts"])
        summary[part] = {
            "rows": int(len(labels)),
            "orf_phage_pos": int(np.sum((tgt["orf_phage_targets"] > 0.5) & (tgt["orf_phage_valid"] > 0.5))),
            "orf_func_known_valid": int(np.sum(tgt["orf_func_valid"] > 0.5)),
            "adv_host_win_cnt": int(np.sum(tgt["adv_host_counts"] > 0)),
        }

    # 4. 读取原 Stage 1.2 teacher OOF 并执行 P0 对抗校准
    y_cat = np.concatenate(all_clean_y)
    func_cat = np.concatenate(all_func_t)
    adv_cat = np.concatenate(all_adv_cnt)
    with np.load(s12_feat / "train_stage1_2_teacher_oof.npz", allow_pickle=False) as tp:
        old_ens = tp["ensemble_oof"].astype(np.float32)

    cal = build_p0_teacher_calibration(
        labels=y_cat,
        teacher_probs=old_ens,
        func_targets=func_cat,
        adv_host_counts=adv_cat,
        hard_neg_weight=float(args.hard_neg_weight),
        suppression_blend=float(args.suppression_blend),
    )
    _atomic_save_npz(p0_feat / "train_p0_teacher_oof.npz", ensemble_oof=cal["teacher_probs"])
    tmp_sw = p0_feat / f".p0_sample_weights.tmp.{os.getpid()}.npy"
    np.save(tmp_sw, cal["sample_weights"])
    tmp_sw.replace(p0_feat / "p0_sample_weights.npy")

    rep = {
        "built_sec": round(time.perf_counter() - t0, 2),
        "hmm_hits_aa": len(hmm_hits),
        "phold_hits_aa": len(phold_hits),
        "adv_host_aa_cnt": adv_host_aa_cnt,
        "calibrated_windows": cal["calibrated_count"],
        "adv_host_neg_count": cal["adv_host_neg_count"],
        "mge_fp_risk_count": cal["mge_fp_risk_count"],
        "parts": summary,
    }
    _atomic_write_json(paths["p0_data"] / "p0_targets_summary.json", rep)
    logger.info("P0 Targets 构建完成: %s", json.dumps(rep, ensure_ascii=False))


def run_step_train(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [P0 Step 4] 零参数增量热启动微调 Stage 1.2 + 重训 Refiners ===")
    p0_feat = paths["p0_feat"]
    sw = np.load(p0_feat / "p0_sample_weights.npy")
    extra_fa: Dict[str, Path] = {
        "mined": paths["mined_fasta"],
        "hard_neg": paths["train_v3"] / "ext_hard_neg.fna",
        "ext_rare": paths["train_v3"] / "ext_rare.fna",
        "ext_windows": paths["train_v3"] / "ext_windows.fna",
        "ext_mined": paths["train_v3"] / "ext_mined.fna",
        "hard_v4": paths["train_v4"] / "ext_hard_v4.fna",
        "rare_multiscale": paths["p0_data"] / "train_rare_multiscale.fna",
    }

    rep = train_distilled_student_v4(
        p0_feat,
        paths["train_v2"],
        paths["eval_feat"],
        paths["bench_v1"],
        paths["p0_model"],
        train_parts=ALL_9_PARTS,
        extra_fasta_map=extra_fa,
        part_weights=None,
        teacher_oof_npz=p0_feat / "train_p0_teacher_oof.npz",
        epochs=int(args.epochs),
        batch_size=int(args.batch_size),
        lr=float(args.lr),
        patience=int(args.patience),
        tune_sub_head=True,
        train_refiner=True,
        refiner_epochs=12,
        train_subbin_refiner=True,
        subbin_epochs=12,
        enable_plateau_decoder=True,
        use_semantic=True,
        use_functional=True,
        use_homoscedastic_loss=True,
        feature_profile="stage1",
        init_student_ckpt=paths["init_ckpt"],
        backbone_lr_scale=float(args.backbone_lr_scale),
        sample_weights_override=sw,
        workers=int(args.cpus),
        seed=42,
    )
    logger.info(
        "P0 热启动蒸馏训练完成: params=%d, best_epoch=%d, best_val_auprc=%.5f",
        rep["params"],
        rep["best_epoch"],
        rep["best_val_auprc"],
    )


def _eval_unseen(model_dir: Path, unseen_dir: Path, *, workers: int = 16) -> Dict[str, Any]:
    import gc
    import torch

    out: Dict[str, Any] = {}
    if not unseen_dir.is_dir():
        return out
    scanner = GenomeScanner.from_model_dir(model_dir, workers=workers)
    try:
        for fa in sorted(unseen_dir.glob("*.f*")):
            if fa.suffix.lower() not in {".fasta", ".fna", ".fa"}:
                continue
            t0 = time.perf_counter()
            res = scanner.scan_fasta(fa, apply_protein_gate=False)
            mods = getattr(res, "region_functional_modules", {}) or {}
            regs = [
                {
                    "contig_id": r.contig_id,
                    "start_bp": int(r.start_bp),
                    "end_bp": int(r.end_bp),
                    "length_bp": int(r.end_bp - r.start_bp),
                    "peak_score": round(float(r.peak_score), 4),
                    "mean_score": round(float(r.mean_score), 4),
                    "hint": (mods.get(f"{r.contig_id}:{r.start_bp}-{r.end_bp}", {}) or {}).get("structural_completeness_hint"),
                    "mge_score": (mods.get(f"{r.contig_id}:{r.start_bp}-{r.end_bp}", {}) or {}).get("mge_contamination_score"),
                }
                for r in res.verified_regions
            ]
            out[fa.name] = {"elapsed_sec": round(time.perf_counter() - t0, 2), "n_regions": len(regs), "regions": regs}
    finally:
        del scanner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return out


def run_step_eval(args: argparse.Namespace, paths: Dict[str, Path]) -> None:
    logger.info("=== [P0 Step 5] 同台冷对比评测 (Stage 1.2 基线 vs P0 增强) ===")
    base_rep_p = paths["s12_model_dir"] / "stage1_2_report.json"
    if not base_rep_p.exists():
        base_rep_p = paths["s12_model_dir"] / "student_v4_report.json"
    p0_rep_p = paths["p0_model"] / "student_v4_report.json"

    base_rep = json.loads(base_rep_p.read_text(encoding="utf-8"))
    p0_rep = json.loads(p0_rep_p.read_text(encoding="utf-8"))

    def _extract_metrics(rep: Dict[str, Any]) -> Dict[str, Any]:
        te = rep["test"]
        wb = te["window_benchmark"]
        ov = wb["overall"]
        by_s = wb.get("by_scale", {})
        ch = te["chimera_benchmark"]["overall"]
        return {
            "params": rep.get("params"),
            "win_auroc": ov.get("auroc"),
            "win_auprc": ov.get("auprc"),
            "win_f1": ov.get("f1"),
            "win_rec": ov.get("recall"),
            "win_fpr": ov.get("fpr"),
            "win_rec_at_0_5pct_fpr": ov.get("recall_at_0_5pct_fpr"),
            "win_fpr_at_95pct_tpr": ov.get("fpr_at_95pct_tpr"),
            "scale_1kb_rec_05fpr": (by_s.get("<=1000bp") or {}).get("recall_at_0_5pct_fpr"),
            "scale_3kb_rec_05fpr": (by_s.get("3000bp") or {}).get("recall_at_0_5pct_fpr"),
            "scale_5kb_f1": (by_s.get("5000bp") or {}).get("f1"),
            "chim_tp_fp_fn": [
                ch["primary"]["tp"],
                ch["primary"]["fp"],
                ch["primary"]["fn"],
            ],
            "chim_f1": ch["primary"]["f1"],
            "chim_strict_f1": ch["strict_iou_0_8"]["f1"],
            "chim_mae_bp": ch["primary"].get("breakpoint_mae_bp"),
            "chim_medae_bp": ch["primary"].get("breakpoint_medae_bp"),
            "chim_fp_per_mb": ch.get("overall_fp_per_mb"),
            "pure_neg_fp_per_mb": ch.get("pure_negative_fp_per_mb"),
        }

    workers = min(16, int(args.cpus))
    unseen_base = _eval_unseen(paths["s12_model_dir"], paths["unseen_dir"], workers=workers)
    unseen_p0 = _eval_unseen(paths["p0_model"], paths["unseen_dir"], workers=workers)
    comparison = {
        "stage1_2_baseline": _extract_metrics(base_rep),
        "stage1_3_p0_ablation": _extract_metrics(p0_rep),
        "unseen_real_genomes_baseline": unseen_base,
        "unseen_real_genomes_p0": unseen_p0,
    }
    out_p = paths["p0_model"] / "p0_vs_stage1_2_comparison.json"
    _atomic_write_json(out_p, comparison)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1.2 P0 多教师蒸馏隔离消融脚本")
    parser.add_argument(
        "--step",
        choices=("hmm", "phold", "targets", "train", "eval", "all"),
        required=True,
    )
    parser.add_argument(
        "--phage-data-root",
        default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")),
        help="Phage data 数据根目录（优先读取环境变量 PHAGE_DATA_ROOT，否则相对项目上级定位）",
    )
    parser.add_argument("--cpus", type=int, default=max(1, min(28, (os.cpu_count() or 8) - 4)))
    parser.add_argument("--hmm-chunk-size", type=int, default=30000)
    parser.add_argument("--phold-chunk-size", type=int, default=4000)
    parser.add_argument("--phold-batch-size", type=int, default=24)
    parser.add_argument("--phold-max-aa-len", type=int, default=600)
    parser.add_argument("--phold-max-items", type=int, default=0, help=">0 时仅扫描高优先级前 N 条暗物质用于快速消融")
    parser.add_argument("--hard-neg-weight", type=float, default=1.75)
    parser.add_argument("--suppression-blend", type=float, default=0.65)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=4e-4)
    parser.add_argument("--backbone-lr-scale", type=float, default=0.25)
    parser.add_argument("--patience", type=int, default=4)
    args = parser.parse_args()

    pd_root = Path(args.phage_data_root).resolve()
    s12_data = pd_root / "training" / "stage1_2_ablation"
    p0_data = pd_root / "training" / "stage1_3_p0_ablation"
    s12_model_dir = pd_root / "models" / "full_v4" / "stage1_2"
    init_ckpt = s12_model_dir / "stage1_2.pt"
    if not init_ckpt.exists():
        init_ckpt = pd_root / "models" / "full_v4" / "stage1_2_ablation" / "student_v4_2_stage1_2" / "student_v4.pt"

    paths = {
        "db_root": REPO_ROOT / "database",
        "train_v2": pd_root / "training" / "full_v2",
        "train_v3": pd_root / "training" / "full_v3",
        "train_v4": pd_root / "training" / "full_v4",
        "mined_fasta": pd_root / "teachers" / "train_prophage_mined" / "mined_chimeras.fna",
        "bench_v1": pd_root / "benchmarks" / "v1",
        "eval_feat": pd_root / "benchmarks" / "v1_stage1" / "features",
        "unseen_dir": pd_root / "benchmarks" / "unseen_real_genomes",
        "s12_data": s12_data,
        "s12_feat": s12_data / "features",
        "s12_cache": s12_data / "func_cache",
        "p0_data": p0_data,
        "p0_feat": p0_data / "features",
        "p0_cache": p0_data / "func_cache",
        "s12_model_dir": s12_model_dir,
        "init_ckpt": init_ckpt,
        "p0_model": pd_root / "models" / "full_v4" / "stage1_3_p0_ablation",
    }

    steps = ("hmm", "phold", "targets", "train", "eval") if args.step == "all" else (args.step,)
    for st in steps:
        if st == "hmm":
            run_step_hmm(args, paths)
        elif st == "phold":
            run_step_phold(args, paths)
        elif st == "targets":
            run_step_targets(args, paths)
        elif st == "train":
            run_step_train(args, paths)
        elif st == "eval":
            run_step_eval(args, paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
