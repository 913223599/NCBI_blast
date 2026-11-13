# -*- coding: utf-8 -*-
"""
Expert A：基因组结构与宿主偏倚表格专家（XGBoost，CUDA 优先，自动降级 CPU）

流程：
1. 读取训练特征分片（train split，独立窗口 + 嵌合体滑窗，剔除 label=-1 边界模糊窗口）；
2. 以 v1 val 特征做早停（aucpr），类别平衡样本权重；
3. 在 val 嵌合体上网格搜索滞回解码阈值，原样应用到 v1 test 产出最终成绩单；
4. 模型 JSON、特征重要性、评测报告原子落盘。
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..benchmark.model_eval import evaluate_model_scores_on_split, load_split_info, tune_decoder_on_val
from ..data.feature_dataset import load_split_arrays
from ..features.window_features import FEATURE_NAMES

logger = logging.getLogger("phage_discovery.experts.expert_a_xgb")


def _select_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _balanced_weights(y: np.ndarray) -> np.ndarray:
    n_pos = max(1, int(np.sum(y == 1)))
    n_neg = max(1, int(np.sum(y == 0)))
    w = np.where(y == 1, 0.5 / n_pos, 0.5 / n_neg).astype(np.float32)
    return w * (len(y) / float(w.sum()))


def _load_weighted_train_split(
    train_feature_dir: Path,
    train_parts: Tuple[str, ...],
    part_weights: Optional[Dict[str, float]] = None,
    use_semantic_clean_labels: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按分片加载训练样本并叠加可选分片权重、语义清洗标签与类别平衡权重。"""
    feats_list, labels_list, mult_list = [], [], []
    w_map = part_weights or {}
    for part in train_parts:
        arrs = load_split_arrays(train_feature_dir, "train", parts=(part,))
        labels_raw = arrs["labels"]
        if use_semantic_clean_labels:
            sem_path = Path(train_feature_dir) / f"train_{part}_semantic.npz"
            if sem_path.exists():
                with np.load(sem_path, allow_pickle=False) as sem_npz:
                    if "clean_labels" in sem_npz and len(sem_npz["clean_labels"]) == len(labels_raw):
                        labels_raw = sem_npz["clean_labels"]
        keep = labels_raw >= 0
        if not np.any(keep):
            continue
        f_p = arrs["features"][keep]
        y_p = labels_raw[keep].astype(np.int32)
        m_p = np.full(len(y_p), float(w_map.get(part, 1.0)), dtype=np.float32)
        feats_list.append(f_p)
        labels_list.append(y_p)
        mult_list.append(m_p)
    x_tr = np.concatenate(feats_list, axis=0)
    y_tr = np.concatenate(labels_list, axis=0)
    mult = np.concatenate(mult_list, axis=0)
    sw = _balanced_weights(y_tr) * mult
    sw *= len(y_tr) / max(1e-6, float(sw.sum()))
    return x_tr, y_tr, sw


def train_expert_a(
    train_feature_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    n_estimators: int = 3000,
    max_depth: int = 7,
    learning_rate: float = 0.04,
    early_stopping_rounds: int = 120,
    train_parts: Tuple[str, ...] = ("windows", "chimeras"),
    n_jobs: Optional[int] = None,
    part_weights: Optional[Dict[str, float]] = None,
    use_semantic_clean_labels: bool = True,
) -> Dict[str, Any]:
    import xgboost as xgb

    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    x_tr, y_tr, sw_tr = _load_weighted_train_split(
        train_feature_dir,
        train_parts,
        part_weights=part_weights,
        use_semantic_clean_labels=use_semantic_clean_labels,
    )
    va = load_split_arrays(eval_feature_dir, "val")
    keep_va = va["labels"] >= 0
    x_va, y_va = va["features"][keep_va], va["labels"][keep_va].astype(np.int32)

    device = _select_device()
    cpu_cnt = os.cpu_count() or 4
    model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.85,
        colsample_bytree=0.75,
        min_child_weight=3.0,
        reg_lambda=2.0,
        reg_alpha=0.5,
        tree_method="hist",
        device=device,
        eval_metric="aucpr",
        early_stopping_rounds=early_stopping_rounds,
        n_jobs=n_jobs if n_jobs is not None else max(1, cpu_cnt - 2),
    )

    t0 = time.perf_counter()
    model.fit(
        x_tr, y_tr,
        sample_weight=sw_tr,
        eval_set=[(x_va, y_va)],
        sample_weight_eval_set=[_balanced_weights(y_va)],
        verbose=False,
    )
    train_sec = round(time.perf_counter() - t0, 2)

    # 释放 GPU 显存（规则 10）：后续推理统一切至 CPU 预测
    try:
        model.set_params(device="cpu")
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

    def _predict(arrs: Dict[str, np.ndarray]) -> np.ndarray:
        return np.asarray(model.predict_proba(arrs["features"]))[:, 1].astype(np.float32)

    va_win = load_split_arrays(eval_feature_dir, "val", parts=("windows",))
    va_chim = load_split_arrays(eval_feature_dir, "val", parts=("chimeras",))
    te_win = load_split_arrays(eval_feature_dir, "test", parts=("windows",))
    te_chim = load_split_arrays(eval_feature_dir, "test", parts=("chimeras",))

    va_win_scores = _predict(va_win)
    va_chim_scores = _predict(va_chim)
    decoder = tune_decoder_on_val(load_split_info(bench_dir, "val"), va_chim, va_chim_scores)

    t1 = time.perf_counter()
    te_win_scores = _predict(te_win)
    te_chim_scores = _predict(te_chim)
    infer_sec = round(time.perf_counter() - t1, 3)

    np.savez_compressed(
        out_root / "expert_a_scores.npz",
        val_windows=va_win_scores,
        val_chimeras=va_chim_scores,
        test_windows=te_win_scores,
        test_chimeras=te_chim_scores,
    )

    val_report = evaluate_model_scores_on_split(
        bench_dir, "val", va_win, va_win_scores, va_chim, va_chim_scores,
        decoder["seed_threshold"], decoder["extend_threshold"],
    )
    test_report = evaluate_model_scores_on_split(
        bench_dir, "test", te_win, te_win_scores, te_chim, te_chim_scores,
        decoder["seed_threshold"], decoder["extend_threshold"],
    )

    booster = model.get_booster()
    gain = booster.get_score(importance_type="gain")
    importance = sorted(
        (
            (FEATURE_NAMES[int(k[1:])], round(float(v[0] if isinstance(v, list) else v), 3))
            for k, v in gain.items()
        ),
        key=lambda kv: kv[1], reverse=True,
    )[:25]

    model_path = out_root / "expert_a_xgb.json"
    tmp_model = out_root / ".expert_a_xgb.tmp.json"
    model.save_model(tmp_model)
    tmp_model.replace(model_path)

    report: Dict[str, Any] = {
        "model_name": "ExpertA_XGBoost",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "device": device,
        "train_rows": len(y_tr),
        "train_pos": int(np.sum(y_tr == 1)),
        "train_neg": int(np.sum(y_tr == 0)),
        "val_rows": len(y_va),
        "best_iteration": int(getattr(model, "best_iteration", -1) or -1),
        "train_sec": train_sec,
        "test_inference_sec": infer_sec,
        "decoder_tuned_on_val": decoder,
        "top25_gain_features": importance,
        "val": val_report,
        "test": test_report,
        "model_path": str(model_path),
    }
    report_path = out_root / "expert_a_report.json"
    tmp_rep = out_root / ".expert_a_report.tmp.json"
    tmp_rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_rep.replace(report_path)
    report["report_path"] = str(report_path)
    return report


def summarize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """提取榜单核心指标。"""
    out: Dict[str, Any] = {
        "model": report["model_name"],
        "device": report["device"],
        "train_rows": report["train_rows"],
        "best_iteration": report["best_iteration"],
        "decoder": report["decoder_tuned_on_val"],
    }
    for split in ("val", "test"):
        w = report[split]["window_benchmark"]["overall"]
        c = report[split]["chimera_benchmark"]["overall"]
        out[split] = {
            "win_auroc": w.get("auroc"),
            "win_auprc": w.get("auprc"),
            "win_recall_at_fpr_0_5pct": w.get("recall_at_fpr_0_5pct"),
            "region_f1_iou05": c["primary"]["f1"],
            "region_precision": c["primary"]["precision"],
            "region_recall": c["primary"]["recall"],
            "region_f1_iou08": c["strict_iou_0_8"]["f1"],
            "breakpoint_mae_bp": c["primary"]["breakpoint_mae_bp"],
            "pure_neg_fp_per_mb": c.get("pure_negative_fp_per_mb"),
        }
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 Expert A (XGBoost) 并在基准上评测")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--n-estimators", type=int, default=3000)
    parser.add_argument("--train-parts", nargs="+", default=["windows", "chimeras"])
    args = parser.parse_args()
    report = train_expert_a(
        Path(args.train_feature_dir), Path(args.eval_feature_dir), Path(args.bench_dir), Path(args.out_dir),
        n_estimators=args.n_estimators, train_parts=tuple(args.train_parts),
    )
    print(json.dumps(summarize_report(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

