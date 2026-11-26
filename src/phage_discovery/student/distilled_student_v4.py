# -*- coding: utf-8 -*-
"""
V4 升级版高容量多模态知识蒸馏学生模型与跨窗上下文精修器（全神经网络端到端流水线）

核心改进：
1. Masked Pooling 修复短片段 (<=1kb) 信号稀释问题：对 DNA ResNet+BiGRU 严格按有效长度掩码与 pack_padded 处理，
   确保同一短序列在不同填充长度下表征一致，不被结尾 N-padding 稀释；
2. 内置三模态门控融合网络（约 3.1M 参数）：
   - Branch 1: 1D Dilated ResNet + Packed BiGRU（原始碱基特征 + 200bp 亚窗口分割）；
   - Branch 2: 嵌入式 ORF Synteny Transformer（直接内部抽取操纵子语法表征）；
   - Branch 3: 带内置均值方差归一化的 Residual Tabular MLP（185 维局部结构/理化特征）；
   - Semantic Aux Head: 隐式蛋白功能域监督（离线 DIAMOND 赋予的 4 维语义，推理零 BLASTp）；
3. RegionContextRefiner（跨窗 BiGRU+Attention 精修器）：
   - 在 contig 连续滑窗序列上综合 35kb+ 长程语境与语义概率走势，抑制孤立转座酶脉冲并抬升退化隐蔽前噬菌体。
"""

import argparse
import gc
import json
import logging
import time
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..data.functional_partitions import NUM_FUNC_PARTITIONS
from ..experts.expert_a_xgb import summarize_report
from ..experts.expert_b_cnn import _resolve_part_fasta
from ..experts.expert_c_orf import MAX_ORFS_PER_WIN, _load_or_extract_part
from ..experts.seq_dataset import load_window_sequences
from .v4_arch import (
    REFINER_CTX_AUG_DIM,
    REFINER_STEP_FEAT_DIM,
    SEMANTIC_DIM,
    _normalize_feature_stats,
    build_distilled_student_v4,
    build_region_context_refiner,
)
from .v4_context_refiner import (
    _apply_refiner_augmentations,
    _predict_v4_all,
    extract_refiner_step_features,
    group_windows_by_contig,
    predict_with_context_refiner,
    train_context_refiner,
)
from .v4_sub_head import (
    _compute_boundary_bin_weights,
    _extract_sub_head_inputs,
    refine_student_v4_sub_head,
)
from .v4_eval_helpers import (
    evaluate_and_save_v4_artifacts,
    train_and_eval_refiners,
)
from .v4_training_helpers import (
    load_and_concat_train_parts,
    resolve_teacher_oof_probs,
    run_v4_training_loop,
    setup_v4_model_and_optimizer,
    slice_effective_train_data,
)

logger = logging.getLogger("phage_discovery.student.distilled_student_v4")

CONTIG_REF_PARTS: Tuple[str, ...] = ("chimeras", "mined", "ext_mined", "hard_neg", "hard_v4")

__all__ = [
    "CONTIG_REF_PARTS",
    "SEMANTIC_DIM",
    "REFINER_STEP_FEAT_DIM",
    "REFINER_CTX_AUG_DIM",
    "_normalize_feature_stats",
    "build_distilled_student_v4",
    "build_region_context_refiner",
    "extract_refiner_step_features",
    "group_windows_by_contig",
    "_predict_v4_all",
    "predict_with_context_refiner",
    "_apply_refiner_augmentations",
    "train_context_refiner",
    "_compute_boundary_bin_weights",
    "_extract_sub_head_inputs",
    "refine_student_v4_sub_head",
    "_load_v4_part",
    "TrainV4Config",
    "train_distilled_student_v4",
    "main",
]


def _load_semantic_targets(
    feature_dir: Path,
    split: str,
    part: str,
    n: int,
    clean_labels: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    sem_targets = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
    sem_valid = np.zeros(n, dtype=np.float32)
    sem_path = Path(feature_dir) / f"{split}_{part}_semantic.npz"
    if not sem_path.exists():
        return clean_labels, sem_targets, sem_valid
    with np.load(sem_path, allow_pickle=False) as sem_npz:
        if "clean_labels" in sem_npz and len(sem_npz["clean_labels"]) == n:
            clean_labels = sem_npz["clean_labels"].astype(np.int8)
        if "sem_targets" in sem_npz and len(sem_npz["sem_targets"]) == n:
            raw_sem = sem_npz["sem_targets"].astype(np.float32)
            if raw_sem.ndim == 2 and raw_sem.shape[1] == SEMANTIC_DIM:
                sem_targets = raw_sem
            elif raw_sem.ndim == 2 and raw_sem.shape[1] == 2:
                sem_targets[:, 0] = raw_sem[:, 0]
                sem_targets[:, 2] = raw_sem[:, 1]
        if "sem_valid_mask" in sem_npz and len(sem_npz["sem_valid_mask"]) == n:
            sem_valid = sem_npz["sem_valid_mask"].astype(np.float32)
        elif np.any(sem_targets > 0):
            sem_valid = np.ones(n, dtype=np.float32)
    return clean_labels, sem_targets, sem_valid


def _load_functional_targets(
    feature_dir: Path,
    split: str,
    part: str,
    n: int,
    clean_labels: np.ndarray,
    sem_targets: np.ndarray,
    sem_valid: np.ndarray,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "has_functional": False,
        "func_targets": np.zeros((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
        "func_valid": np.ones((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
        "orf_phage_targets": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        "orf_phage_valid": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        "orf_func_targets": np.zeros((n, MAX_ORFS_PER_WIN, NUM_FUNC_PARTITIONS), dtype=np.float32),
        "orf_func_valid": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
        "clean_labels": clean_labels,
        "sem_targets": sem_targets,
        "sem_valid": sem_valid,
    }
    func_path = Path(feature_dir) / f"{split}_{part}_functional.npz"
    if not func_path.exists():
        return out
    out["has_functional"] = True
    with np.load(func_path, allow_pickle=False) as fn_npz:
        for dst_k, src_k in (
            ("func_targets", "func_targets"),
            ("func_valid", "func_valid_mask"),
            ("orf_phage_targets", "orf_phage_targets"),
            ("orf_phage_valid", "orf_phage_valid"),
            ("orf_func_targets", "orf_func_targets"),
            ("orf_func_valid", "orf_func_valid"),
        ):
            if src_k in fn_npz and len(fn_npz[src_k]) == n:
                out[dst_k] = fn_npz[src_k].astype(np.float32)
        if "sem_targets" in fn_npz and len(fn_npz["sem_targets"]) == n:
            # 严格使用客观三源 4D 语义替换旧版可能存在 y 依赖或 PHROG 回填污染的标签
            out["sem_targets"] = fn_npz["sem_targets"].astype(np.float32)
            out["sem_valid"] = np.ones(n, dtype=np.float32)
        if "clean_labels" in fn_npz and len(fn_npz["clean_labels"]) == n:
            out["clean_labels"] = fn_npz["clean_labels"].astype(np.int8)
    return out


def _load_v4_part(
    feature_dir: Path,
    manifest_or_train_dir: Path,
    split: str,
    part: str,
    max_len: int,
    workers: Optional[int],
    *,
    fasta_override: Optional[Path] = None,
    use_semantic: bool = True,
    use_functional: bool = False,
    feature_profile: str = "v4",
) -> Dict[str, Any]:
    """统一加载某个分片的 tabular 特征、DNA 编码、ORF 张量以及可选 offline 语义/9D功能分区目标。"""
    arrs, tokens, counts = _load_or_extract_part(
        feature_dir,
        manifest_or_train_dir,
        split,
        part,
        Path(feature_dir),
        workers,
        fasta_override=fasta_override,
        use_semantic_clean_labels=False,
        feature_profile=feature_profile,
    )
    orig_labels = arrs["labels"].astype(np.int8, copy=True)
    clean_labels = orig_labels.copy()
    n = len(orig_labels)

    if use_semantic:
        clean_labels, sem_targets, sem_valid = _load_semantic_targets(feature_dir, split, part, n, clean_labels)
    else:
        sem_targets = np.zeros((n, SEMANTIC_DIM), dtype=np.float32)
        sem_valid = np.zeros(n, dtype=np.float32)

    fn_data = (
        _load_functional_targets(feature_dir, split, part, n, clean_labels, sem_targets, sem_valid)
        if use_functional
        else {
            "has_functional": False,
            "func_targets": np.zeros((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
            "func_valid": np.ones((n, NUM_FUNC_PARTITIONS), dtype=np.float32),
            "orf_phage_targets": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
            "orf_phage_valid": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
            "orf_func_targets": np.zeros((n, MAX_ORFS_PER_WIN, NUM_FUNC_PARTITIONS), dtype=np.float32),
            "orf_func_valid": np.zeros((n, MAX_ORFS_PER_WIN), dtype=np.float32),
            "clean_labels": clean_labels,
            "sem_targets": sem_targets,
            "sem_valid": sem_valid,
        }
    )

    fasta = _resolve_part_fasta(feature_dir, manifest_or_train_dir, split, part, fasta_override=fasta_override)
    codes, lengths = load_window_sequences(fasta, arrs["contig_ids"], arrs["starts"], arrs["ends"], max_len=max_len)
    return {
        "arrs": arrs,
        "codes": codes,
        "lengths": lengths,
        "tokens": tokens,
        "counts": counts,
        "orig_labels": orig_labels,
        **fn_data,
    }


def _load_val_eval_bundle(
    eval_feature_dir: Path,
    bench_dir: Path,
    max_len: int,
    workers: Optional[int],
    feature_profile: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    va_w = _load_v4_part(
        eval_feature_dir, bench_dir, "val", "windows", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )
    va_c = _load_v4_part(
        eval_feature_dir, bench_dir, "val", "chimeras", max_len, workers,
        use_semantic=False, feature_profile=feature_profile,
    )
    va_y = np.concatenate([va_w["orig_labels"], va_c["orig_labels"]])
    va_keep = va_y >= 0
    va_bundle = {
        "va_codes": np.concatenate([va_w["codes"], va_c["codes"]]),
        "va_len": np.concatenate([va_w["lengths"], va_c["lengths"]]),
        "va_feats": np.concatenate([va_w["arrs"]["features"], va_c["arrs"]["features"]]),
        "va_tokens": np.concatenate([va_w["tokens"], va_c["tokens"]]),
        "va_counts": np.concatenate([va_w["counts"], va_c["counts"]]),
        "va_y": va_y,
        "va_keep": va_keep,
        "has_two_va": bool(np.any(va_keep) and np.unique(va_y[va_keep]).size > 1),
    }
    return va_w, va_c, va_bundle


@dataclass
class TrainV4Config:
    """V4 三模态蒸馏学生模型与上下文精修器的全量训练超参配置。"""

    # 数据分片与教师蒸馏
    train_parts: Tuple[str, ...] = ("windows", "chimeras")
    extra_mined_fasta: Optional[Path] = None
    extra_fasta_map: Optional[Dict[str, Path]] = None
    part_weights: Optional[Dict[str, float]] = None
    teacher_oof_npz: Optional[Path] = None
    teacher_probs_override: Optional[np.ndarray] = None
    teacher_weights: Tuple[float, float, float] = (0.4, 0.35, 0.25)
    sample_weights_override: Optional[np.ndarray] = None

    # 优化器与网络结构
    epochs: int = 24
    batch_size: int = 64
    lr: float = 8e-4
    patience: int = 6
    max_len: int = 5000
    dna_channels: int = 160
    orf_d_model: int = 128
    orf_nhead: int = 4
    orf_num_layers: int = 3
    fusion_dim: int = 256
    init_student_ckpt: Optional[Path] = None
    backbone_lr_scale: float = 0.25

    # 蒸馏与多任务损失权重
    distill_alpha: float = 0.55
    sub_weight: float = 0.25
    sem_weight: float = 0.25
    temperature: float = 2.0
    focal_gamma: float = 2.0
    modality_dropout_prob: float = 0.10
    use_semantic: bool = True
    use_functional: bool = False
    use_homoscedastic_loss: bool = False
    feature_profile: str = "v4"

    # 精修与运行时控制
    tune_sub_head: bool = True
    train_refiner: bool = True
    refiner_epochs: int = 16
    train_subbin_refiner: bool = True
    subbin_epochs: int = 16
    enable_plateau_decoder: bool = True
    workers: Optional[int] = None
    seed: int = 42

    @classmethod
    def from_overrides(
        cls,
        base: Optional["TrainV4Config"] = None,
        **overrides: Any,
    ) -> "TrainV4Config":
        """基于已有配置或默认配置合并关键字参数，并严格拦截未知字段名。"""
        cfg = base if base is not None else cls()
        if not overrides:
            return cfg
        valid_names = {f.name for f in fields(cls)}
        unknown = sorted(set(overrides) - valid_names)
        if unknown:
            raise TypeError(f"train_distilled_student_v4() 接收到未定义参数: {', '.join(unknown)}")
        return replace(cfg, **overrides)


def train_distilled_student_v4(
    train_feature_dir: Path,
    train_dir: Path,
    eval_feature_dir: Path,
    bench_dir: Path,
    out_dir: Path,
    *,
    config: Optional[TrainV4Config] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """训练 V4 高容量三模态蒸馏学生模型与跨窗上下文精修器并生成测试报告。

    支持传入 `config=TrainV4Config(...)`，亦完全向后兼容直接通过关键字参数覆盖超参。
    """
    import torch

    cfg = TrainV4Config.from_overrides(config, **overrides)
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    t_data0 = time.perf_counter()
    bundle = load_and_concat_train_parts(
        _load_v4_part,
        train_feature_dir,
        train_dir,
        train_parts=cfg.train_parts,
        contig_ref_parts=CONTIG_REF_PARTS,
        extra_mined_fasta=cfg.extra_mined_fasta,
        extra_fasta_map=cfg.extra_fasta_map,
        part_weights=cfg.part_weights,
        sample_weights_override=cfg.sample_weights_override,
        max_len=cfg.max_len,
        workers=cfg.workers,
        use_semantic=cfg.use_semantic,
        use_functional=cfg.use_functional,
        feature_profile=cfg.feature_profile,
    )
    teacher_probs_all, oof_sec = resolve_teacher_oof_probs(
        bundle["clean_y_all"],
        bundle["feats_all"],
        bundle["cids_all"],
        bundle["sw_all"],
        teacher_probs_override=cfg.teacher_probs_override,
        teacher_oof_npz=cfg.teacher_oof_npz,
        teacher_weights=cfg.teacher_weights,
    )
    va_w, va_c, va_bundle = _load_val_eval_bundle(
        eval_feature_dir, bench_dir, cfg.max_len, cfg.workers, cfg.feature_profile
    )
    tr = slice_effective_train_data(bundle, teacher_probs_all)

    setup = setup_v4_model_and_optimizer(
        tr,
        device,
        epochs=cfg.epochs,
        batch_size=cfg.batch_size,
        lr=cfg.lr,
        dna_channels=cfg.dna_channels,
        orf_d_model=cfg.orf_d_model,
        orf_nhead=cfg.orf_nhead,
        orf_num_layers=cfg.orf_num_layers,
        fusion_dim=cfg.fusion_dim,
        use_homoscedastic_loss=cfg.use_homoscedastic_loss,
        init_student_ckpt=cfg.init_student_ckpt,
        backbone_lr_scale=cfg.backbone_lr_scale,
    )
    ckpt_path = out_root / "student_v4.pt"
    loop_res = run_v4_training_loop(
        tr,
        va_bundle,
        setup,
        ckpt_path,
        device,
        rng,
        epochs=cfg.epochs,
        patience=cfg.patience,
        batch_size=cfg.batch_size,
        max_len=cfg.max_len,
        modality_dropout_prob=cfg.modality_dropout_prob,
        distill_alpha=cfg.distill_alpha,
        sub_weight=cfg.sub_weight,
        sem_weight=cfg.sem_weight,
        temperature=cfg.temperature,
        focal_gamma=cfg.focal_gamma,
    )

    model = setup["model"]
    sub_tune_info: Dict[str, Any] = {"enabled": False}
    if cfg.tune_sub_head:
        sub_tune_info = {
            "enabled": True,
            **refine_student_v4_sub_head(
                model,
                tr["codes_tr"],
                tr["len_tr"],
                tr["feats_tr"],
                tr["tokens_tr"],
                tr["counts_tr"],
                tr["sub_tr"],
                tr["sw_tr"],
                va_c["codes"],
                va_c["lengths"],
                va_c["arrs"]["features"],
                va_c["tokens"],
                va_c["counts"],
                va_c["arrs"]["sub_mask"].astype(np.float32),
                out_ckpt_path=ckpt_path,
                device=device,
                seed=cfg.seed,
                tr_labels=tr["y_tr"],
            ),
        }

    train_rows = int(np.sum(tr["use_row"]))
    func_dim = int(tr["func_dim"])
    tr.clear()
    setup["mt_loss_fn"] = None
    gc.collect()

    va_w_pred = _predict_v4_all(
        model, va_w["codes"], va_w["lengths"], va_w["arrs"]["features"], va_w["tokens"], va_w["counts"], device
    )
    va_c_pred = _predict_v4_all(
        model, va_c["codes"], va_c["lengths"], va_c["arrs"]["features"], va_c["tokens"], va_c["counts"], device
    )
    te_w = _load_v4_part(
        eval_feature_dir, bench_dir, "test", "windows", cfg.max_len, cfg.workers,
        use_semantic=False, feature_profile=cfg.feature_profile,
    )
    te_c = _load_v4_part(
        eval_feature_dir, bench_dir, "test", "chimeras", cfg.max_len, cfg.workers,
        use_semantic=False, feature_profile=cfg.feature_profile,
    )
    t_inf0 = time.perf_counter()
    te_w_pred = _predict_v4_all(
        model, te_w["codes"], te_w["lengths"], te_w["arrs"]["features"], te_w["tokens"], te_w["counts"], device
    )
    te_c_pred = _predict_v4_all(
        model, te_c["codes"], te_c["lengths"], te_c["arrs"]["features"], te_c["tokens"], te_c["counts"], device
    )
    infer_sec = round(time.perf_counter() - t_inf0, 3)

    ref_out = train_and_eval_refiners(
        model,
        bundle,
        va_c,
        va_c_pred,
        te_c,
        te_c_pred,
        out_root,
        device,
        max_len=cfg.max_len,
        seed=cfg.seed,
        train_refiner=cfg.train_refiner,
        refiner_epochs=cfg.refiner_epochs,
        train_subbin_refiner=cfg.train_subbin_refiner,
        subbin_epochs=cfg.subbin_epochs,
    )

    for k in ("codes_all", "len_all", "feats_all", "tokens_all", "counts_all", "sub_all"):
        bundle[k] = None
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()

    meta_cfg = {
        "model_version": "v4",
        "feature_profile": cfg.feature_profile,
        "feat_dim": int(setup["feat_std"].shape[0]),
        "orf_feat_dim": setup["orf_feat_dim"],
        "max_len": cfg.max_len,
        "dna_channels": cfg.dna_channels,
        "orf_d_model": cfg.orf_d_model,
        "orf_nhead": cfg.orf_nhead,
        "orf_num_layers": cfg.orf_num_layers,
        "fusion_dim": cfg.fusion_dim,
        "func_dim": func_dim,
        "use_homoscedastic_loss": bool(cfg.use_homoscedastic_loss),
    }
    summary_ctx = {
        "warm_started_from": setup["warm_started_from"],
        "device": str(device),
        "n_params": setup["n_params"],
        "part_names_used": bundle["part_names_used"],
        "train_rows": train_rows,
        "oof_sec": oof_sec,
        "data_prep_sec": round(time.perf_counter() - t_data0, 2),
        "infer_sec": infer_sec,
        "sub_tune_info": sub_tune_info,
        **loop_res,
    }
    del model
    return evaluate_and_save_v4_artifacts(
        bench_dir,
        out_root,
        ckpt_path,
        va_w,
        va_w_pred,
        va_c,
        va_c_pred,
        te_w,
        te_w_pred,
        te_c,
        te_c_pred,
        ref_out,
        meta_cfg,
        summary_ctx,
        enable_plateau_decoder=cfg.enable_plateau_decoder,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="训练 V4 三模态知识蒸馏学生模型与上下文精修器")
    parser.add_argument("--train-feature-dir", required=True)
    parser.add_argument("--train-dir", required=True)
    parser.add_argument("--eval-feature-dir", required=True)
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--extra-mined-fasta", default=None)
    parser.add_argument("--no-refiner", action="store_true")
    parser.add_argument("--no-subbin-refiner", action="store_true")
    args = parser.parse_args()
    rep = train_distilled_student_v4(
        Path(args.train_feature_dir),
        Path(args.train_dir),
        Path(args.eval_feature_dir),
        Path(args.bench_dir),
        Path(args.out_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        extra_mined_fasta=Path(args.extra_mined_fasta) if args.extra_mined_fasta else None,
        train_refiner=not args.no_refiner,
        train_subbin_refiner=not args.no_subbin_refiner,
    )
    print(json.dumps(summarize_report({**rep, "best_iteration": rep["best_epoch"]}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
