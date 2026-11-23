# -*- coding: utf-8 -*-
"""
基于 UnifiedJudge V4.3 深度底座与结构化特征的双轨 AI 形态分类与概率校准模块 (T2.2)

职责：
1. 冻结并按相对路径复用早期自研 `UnifiedJudge V4.3`（1.75M 参数蛋白操纵子注意力网络），
   在零 HMM/Pfam/PTF 依赖条件下毫秒级提取 Contig 级深度表征（`h_base` + `ProstT5 3D 蒸馏向量` + `func10/intact`）；
2. 提取规则引擎生成的结构化模块矩阵、Virfam 连接器、TMP 标尺与 PhageTailFinder 簇特征向量；
3. 加载经 ICTV 科级分组交叉验证及温度校准的双轨模型包 (`morphotype_ai_v1.joblib`)，
   按当前形态完整性与序列上下文自动选择 `dual_modal_fusion` 或 `ai_deep_only`（HMM 失明兜底）轨迹输出校准后验概率；
4. 严格管理 PyTorch CUDA 显存缓存生命周期，防止与 Phold 3D 引擎切换时产生显存叠加溢出。
"""
from __future__ import annotations

import gc
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from ...workbench.models.tool_config import ToolConfig
from .types import (
    AiMorphotypePrediction,
    CompletenessAssessment,
    ConnectorProfile,
    MorphotypePrediction,
    StructuralModuleMatrix,
    StructureProteinItem,
    TailFinderCluster,
    TmpAnalysisItem,
)

logger = logging.getLogger("analysis.phage_structure.ai_model")

MORPH_CLASSES: Tuple[str, ...] = (
    "Myoviridae-like",
    "Siphoviridae-like",
    "Podoviridae-like",
    "Non-tailed",
)

_CONNECTOR_ORDER: Tuple[str, ...] = (
    "Type_1_Sipho_Myo",
    "Type_2_Sipho_Podo",
    "Type_3_Podoviridae",
    "Mixed_or_Uncertain",
    "Absent",
)

# 深度表征分块维度契约（需与训练脚本 ColumnTransformer 切片严格一致）
DEEP_H_DIM: int = 160 * 5  # head_conn_h + tail_h + long_tail_h + global_mean_h + global_max_h
DEEP_DISTILL_DIM: int = 1024 * 2  # tail_distill + head_distill
DEEP_SUMMARY_DIM: int = 68  # func10(30) + intact(20) + 尺度/统计(18)
DEEP_TOTAL_DIM: int = DEEP_H_DIM + DEEP_DISTILL_DIM + DEEP_SUMMARY_DIM  # 2916

DEEP_H_SLICE = slice(0, DEEP_H_DIM)
DEEP_DISTILL_SLICE = slice(DEEP_H_DIM, DEEP_H_DIM + DEEP_DISTILL_DIM)
DEEP_SUMMARY_SLICE = slice(DEEP_H_DIM + DEEP_DISTILL_DIM, DEEP_TOTAL_DIM)

STRUCT_TOTAL_DIM: int = 67
FUSION_META_DIM: int = 8 + STRUCT_TOTAL_DIM  # 75 (4 log-probs + entropy + margin + tail_max + head_max + 67 struct)

_AI_PREDICTOR_CACHE: Optional[Dict[str, Any]] = None
_JUDGE_RUNTIME_CACHE: Dict[str, Any] = {}


def get_ai_model_paths(project_root: Optional[Path] = None) -> Tuple[Path, Path]:
    """返回相对工程根目录的 AI 双轨分类器权重路径与元数据路径。"""
    root = Path(project_root) if project_root else ToolConfig.PROJECT_ROOT
    model_dir = root / "models" / "phage_structure"
    return model_dir / "morphotype_ai_v1.joblib", model_dir / "morphotype_ai_v1_meta.json"


def _resolve_unified_judge_dir(project_root: Optional[Path] = None) -> Optional[Path]:
    """动态发现已部署的 UnifiedJudge V4.3 模型目录（禁止硬编码盘符）。"""
    root = Path(project_root) if project_root else ToolConfig.PROJECT_ROOT
    try:
        from ..phage_finder.model_registry import discover_available_models

        for item in discover_available_models(root):
            uj = str(item.get("unified_judge_dir") or "").strip()
            if uj:
                p = Path(uj)
                if (p / "unified_judge_seq.pt").is_file():
                    return p
    except Exception:
        pass

    sibling_data = root.parent / "Phage data"
    for cand in (
        root / "models" / "full_v4" / "orf_judge_unified",
        sibling_data / "models" / "full_v4" / "orf_judge_unified",
    ):
        if (cand / "unified_judge_seq.pt").is_file():
            return cand
    return None


def check_unified_judge_ready(project_root: Optional[Path] = None) -> bool:
    """检查早期自研 UnifiedJudge V4.3 深度底座是否就绪。"""
    return _resolve_unified_judge_dir(project_root) is not None


def check_ai_classifier_ready(project_root: Optional[Path] = None) -> bool:
    """检查双轨 AI 形态分类权重包与 UnifiedJudge 底座是否均已就绪。"""
    joblib_p, _ = get_ai_model_paths(project_root)
    return joblib_p.is_file() and check_unified_judge_ready(project_root)


def release_ai_judge_memory() -> None:
    """释放缓存的 PyTorch UnifiedJudge 显存并执行垃圾回收，切换引擎前强制调用。"""
    global _JUDGE_RUNTIME_CACHE
    _JUDGE_RUNTIME_CACHE.clear()
    gc.collect()
    try:
        import importlib

        torch = importlib.import_module("torch")
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


def load_unified_judge_seq_model(
    *,
    device: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> Tuple[Any, str, str]:
    """加载并缓存冻结的 UnifiedJudge V4.3 主序列+操纵子注意力网络。"""
    import torch
    from ...phage_discovery.inference.judge_region_refiner import resolve_unified_version_tag
    from ...phage_discovery.student.orf_functional_judge import build_orf_functional_judge

    eff_dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    cached = _JUDGE_RUNTIME_CACHE.get(eff_dev)
    if cached is not None:
        return cached

    uni_dir = _resolve_unified_judge_dir(project_root)
    if uni_dir is None:
        raise FileNotFoundError("未找到 UnifiedJudge V4.3 模型目录 (unified_judge_seq.pt)")

    seq_pt = uni_dir / "unified_judge_seq.pt"
    ck = torch.load(seq_pt, map_location=eff_dev, weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(ck.get("arch", "unified_v4_3")),
    ).to(eff_dev)
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()
    for param in model.parameters():
        param.requires_grad_(False)

    uni_meta: Dict[str, Any] = {}
    summary_p = uni_dir / "unified_summary.json"
    if summary_p.is_file():
        try:
            loaded = json.loads(summary_p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                uni_meta = loaded
        except Exception:
            pass
    version_tag = resolve_unified_version_tag(uni_meta, {})

    _JUDGE_RUNTIME_CACHE.clear()
    _JUDGE_RUNTIME_CACHE[eff_dev] = (model, version_tag, eff_dev)
    return model, version_tag, eff_dev


def extract_unified_judge_genome_features(
    proteins: Sequence[StructureProteinItem],
    length_bp: int,
    gc_percent: float = 50.0,
    *,
    judge_model: Any = None,
    device: Optional[str] = None,
    batch_size: int = 16,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    仅基于 Contig 排序 ORF（零 HMM / 零 Pfam / 零 PTF）通过 UnifiedJudge V4.3 提取 2916 维深度特征，
    同时返回核心可解释信号摘要 (deep_tail_prob_max, deep_head_prob_max)。
    """
    import torch
    from ...phage_discovery.student.orf_functional_judge import (
        CTX_WIN_ORFS,
        NUM_JUDGE_CLASSES,
        slice_contig_orf_windows,
    )

    sorted_prots = [p for p in sorted(proteins, key=lambda x: x.start) if (p.translation or "").strip()]
    m = len(sorted_prots)
    if m == 0:
        return np.zeros(DEEP_TOTAL_DIM, dtype=np.float32), {"deep_tail_prob_max": 0.0, "deep_head_prob_max": 0.0}

    if judge_model is None:
        judge_model, _, eff_dev = load_unified_judge_seq_model(device=device)
    else:
        eff_dev = device or str(next(judge_model.parameters()).device)

    orfs: List[Tuple[int, int, int, str]] = [
        (max(0, p.start - 1), p.end, 1 if p.strand != "-" else -1, p.translation)
        for p in sorted_prots
    ]
    aa_lens = np.array([max(1, len((p.translation or "").strip().rstrip("*"))) for p in sorted_prots], dtype=np.float32)

    windows = slice_contig_orf_windows(orfs, ctx_len=CTX_WIN_ORFS, stride=16)
    if not windows:
        return np.zeros(DEEP_TOTAL_DIM, dtype=np.float32), {"deep_tail_prob_max": 0.0, "deep_head_prob_max": 0.0}

    acc_h = np.zeros((m, 160), dtype=np.float64)
    acc_distill = np.zeros((m, 1024), dtype=np.float64)
    acc_func = np.zeros((m, NUM_JUDGE_CLASSES), dtype=np.float64)
    acc_intact = np.zeros((m, NUM_JUDGE_CLASSES), dtype=np.float64)
    acc_weight = np.zeros(m, dtype=np.float64)

    center = 0.5 * (CTX_WIN_ORFS - 1)
    half_span = max(1.0, 0.5 * CTX_WIN_ORFS)
    dev = torch.device(eff_dev)
    bs = max(1, batch_size)

    with torch.no_grad():
        for i in range(0, len(windows), bs):
            chunk = windows[i : i + bs]
            t_ids = torch.from_numpy(np.stack([w["aa_ids"] for w in chunk])).to(dev, dtype=torch.long)
            t_lens = torch.from_numpy(np.stack([w["aa_lens"] for w in chunk])).to(dev, dtype=torch.long)
            t_stat = torch.from_numpy(np.stack([w["stat_feats"] for w in chunk])).to(dev, dtype=torch.float32)
            t_cnt = torch.tensor([w["valid_count"] for w in chunk], device=dev, dtype=torch.long)

            exp_d = judge_model(
                t_ids,
                t_lens,
                t_stat,
                t_cnt,
                return_seq_distill=True,
                return_experts=True,
            )
            h_np = exp_d["h_base"].float().cpu().numpy()
            dist_raw = exp_d["distill_out"]
            dist_np = dist_raw.float().cpu().numpy() if dist_raw is not None else np.zeros((len(chunk), CTX_WIN_ORFS, 1024), dtype=np.float32)
            f_probs = torch.sigmoid(exp_d["func10_logits"]).float().cpu().numpy()
            if exp_d.get("intact_func_logits") is not None:
                i_probs = torch.sigmoid(exp_d["intact_func_logits"]).float().cpu().numpy()
            else:
                i_probs = f_probs

            for wi, w in enumerate(chunk):
                st = int(w["start_idx"])
                vcnt = int(w["valid_count"])
                for k in range(vcnt):
                    wt = 1.0 - 0.7 * (abs(float(k) - center) / half_span)
                    acc_h[st + k] += h_np[wi, k] * wt
                    acc_distill[st + k] += dist_np[wi, k] * wt
                    acc_func[st + k] += f_probs[wi, k] * wt
                    acc_intact[st + k] += i_probs[wi, k] * wt
                    acc_weight[st + k] += wt

    denom = np.maximum(acc_weight, 1e-6)[:, None]
    h_orf = (acc_h / denom).astype(np.float32)
    dist_orf = (acc_distill / denom).astype(np.float32)
    dist_norms = np.linalg.norm(dist_orf, axis=1, keepdims=True)
    dist_orf = np.where(dist_norms > 1e-6, dist_orf / np.maximum(dist_norms, 1e-6), 0.0)
    f_orf = (acc_func / denom).astype(np.float32)
    i_orf = (acc_intact / denom).astype(np.float32)

    p0 = f_orf[:, 0]  # head_packaging
    p1 = f_orf[:, 1]  # connector
    p2 = f_orf[:, 2]  # tail
    p3 = f_orf[:, 3]  # lysis

    def _weighted_pool(mat: np.ndarray, weights: np.ndarray, min_sum: float = 1e-3) -> np.ndarray:
        w = np.maximum(0.0, weights.astype(np.float64))
        s = float(np.sum(w))
        if s < min_sum:
            return np.zeros(mat.shape[1], dtype=np.float32)
        return ((w[:, None] * mat).sum(axis=0) / s).astype(np.float32)

    head_conn_w = p0 + p1
    head_conn_h = _weighted_pool(h_orf, head_conn_w)
    tail_h = _weighted_pool(h_orf, p2)
    long_tail_h = _weighted_pool(h_orf, p2 * np.log1p(aa_lens))
    global_mean_h = h_orf.mean(axis=0).astype(np.float32)
    global_max_h = h_orf.max(axis=0).astype(np.float32)

    tail_distill = _weighted_pool(dist_orf, p2)
    head_distill = _weighted_pool(dist_orf, head_conn_w)

    p2_mask35 = p2 > 0.35
    p2_lens = np.sort(aa_lens[p2_mask35])[::-1] if np.any(p2_mask35) else np.zeros(0, dtype=np.float32)
    max_p2_aa = float(p2_lens[0]) if len(p2_lens) >= 1 else 0.0
    top2_p2_aa = float(p2_lens[1]) if len(p2_lens) >= 2 else 0.0

    sorted_aa = np.sort(aa_lens)[::-1]
    top3_aa_mean = float(sorted_aa[: min(3, len(sorted_aa))].mean())
    covered_bp = sum(max(0, p.end - p.start + 1) for p in sorted_prots)
    coding_density = float(covered_bp / max(1, length_bp))
    deep_tail_max = float(np.max(p2))
    deep_head_max = float(np.max(p0))

    scalars = np.array(
        [
            float(np.sum(p2 > 0.35)),
            float(np.sum(p2 > 0.50)),
            float(np.sum(p2 > 0.50) / max(1, m)),
            float(np.log1p(max_p2_aa)),
            float(np.log1p(top2_p2_aa)),
            float(np.sum(p2_mask35 & (aa_lens >= 400))),
            float(np.sum(p2_mask35 & (aa_lens >= 650))),
            float(np.log1p(float(sorted_aa[0]))),
            float(np.log1p(top3_aa_mean)),
            float(np.sum(p0 > 0.50)),
            float(np.sum(p1 > 0.50)),
            float(np.sum(p3 > 0.50)),
            float(np.log1p(max(1, length_bp))),
            float(np.log1p(m)),
            coding_density,
            float(gc_percent) / 100.0,
            deep_tail_max,
            deep_head_max,
        ],
        dtype=np.float32,
    )

    summary_vec = np.concatenate(
        [
            f_orf.max(axis=0),
            f_orf.mean(axis=0),
            (f_orf > 0.50).mean(axis=0),
            i_orf.max(axis=0),
            i_orf.mean(axis=0),
            scalars,
        ]
    ).astype(np.float32)

    full_vec = np.concatenate(
        [
            head_conn_h,
            tail_h,
            long_tail_h,
            global_mean_h,
            global_max_h,
            tail_distill,
            head_distill,
            summary_vec,
        ]
    ).astype(np.float32)
    full_vec = np.nan_to_num(full_vec, nan=0.0, posinf=0.0, neginf=0.0)
    return full_vec, {
        "deep_tail_prob_max": round(deep_tail_max, 4),
        "deep_head_prob_max": round(deep_head_max, 4),
    }


def extract_structured_morph_features(
    module_matrix: StructuralModuleMatrix,
    connector_profile: ConnectorProfile,
    tmp_analyses: Sequence[TmpAnalysisItem],
    ptf_clusters: Sequence[TailFinderCluster],
    completeness: CompletenessAssessment,
    length_bp: int,
    total_orfs: int,
) -> np.ndarray:
    """将结构化规则特征矩阵编码为固定 67 维数值向量（供双模态融合与消融对比）。"""
    mm_vals = np.array(
        [
            module_matrix.head_packaging_count,
            module_matrix.connector_count,
            module_matrix.tail_sheath_count,
            module_matrix.tail_tube_count,
            module_matrix.major_tail_count,
            module_matrix.tail_assembly_chaperone_count,
            module_matrix.tape_measure_count,
            module_matrix.tail_tubular_ab_count,
            module_matrix.internal_virion_count,
            module_matrix.tail_needle_count,
            module_matrix.baseplate_count,
            module_matrix.tail_fiber_rbp_count,
            module_matrix.lysis_count,
            module_matrix.integrase_count,
            module_matrix.non_tailed_marker_count,
            module_matrix.t6ss_confounder_count,
        ],
        dtype=np.float32,
    )
    mm_log = np.log1p(np.maximum(0.0, mm_vals))

    conn_oh = np.array([1.0 if connector_profile.type_hint == ct else 0.0 for ct in _CONNECTOR_ORDER], dtype=np.float32)
    conn_sub = np.array(
        [
            connector_profile.portal_count,
            connector_profile.ad1_count,
            connector_profile.ad2_count,
            connector_profile.ad3_count,
            connector_profile.hc1_count,
            connector_profile.hc2_count,
            connector_profile.hc3_count,
            connector_profile.neck1_count,
            connector_profile.tail_terminator_count,
            connector_profile.collar_podo_count,
            connector_profile.general_connector_count,
        ],
        dtype=np.float32,
    )

    confirmed_cnt = sum(1 for t in tmp_analyses if t.evidence_kind == "confirmed_tmp")
    merged_cnt = sum(1 for t in tmp_analyses if t.evidence_kind == "merged_split_tmp")
    gp29_cnt = sum(1 for t in tmp_analyses if t.evidence_kind == "gp29_tail_length")
    syntenic_cnt = sum(1 for t in tmp_analyses if t.evidence_kind == "putative_syntenic_tmp")
    max_tmp_aa = max((t.length_aa for t in tmp_analyses), default=0)
    max_polyx_pct = max((t.polyx_fraction_pct for t in tmp_analyses), default=0.0)
    max_tr_pct = max((t.tr_fraction_pct for t in tmp_analyses), default=0.0)
    tmp_vec = np.array(
        [
            confirmed_cnt,
            merged_cnt,
            gp29_cnt,
            syntenic_cnt,
            float(np.log1p(max_tmp_aa)),
            float(max_polyx_pct) / 100.0,
            float(max_tr_pct) / 100.0,
        ],
        dtype=np.float32,
    )

    tot_cl_orfs = sum(cl.orf_count for cl in ptf_clusters)
    max_cl_orfs = max((cl.orf_count for cl in ptf_clusters), default=0)
    max_cl_prob = max((cl.mean_tail_prob for cl in ptf_clusters), default=0.0)
    novel_cl_orfs = sum(cl.novel_orf_count for cl in ptf_clusters)
    ptf_vec = np.array(
        [len(ptf_clusters), tot_cl_orfs, max_cl_orfs, max_cl_prob, novel_cl_orfs],
        dtype=np.float32,
    )

    comp_vec = np.array(
        [
            float(completeness.score),
            1.0 if completeness.has_dtr else 0.0,
            1.0 if completeness.has_itr else 0.0,
            1.0 if completeness.has_intact_head_packaging else 0.0,
            1.0 if completeness.has_truncated_long_tail_remnant else 0.0,
            float(np.log1p(max(1, length_bp))),
            float(np.log1p(max(0, total_orfs))),
        ],
        dtype=np.float32,
    )

    vec = np.concatenate([mm_vals, mm_log, conn_oh, conn_sub, tmp_vec, ptf_vec, comp_vec]).astype(np.float32)
    return np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)


def apply_temperature_scaling(probs: np.ndarray, temperature: float) -> np.ndarray:
    """对类别概率分布执行单参数温度缩放校准并保持总和严格为 1。"""
    p = np.clip(probs.astype(np.float64), 1e-7, 1.0)
    t = max(0.05, float(temperature))
    scaled_log = np.log(p) / t
    scaled_log -= scaled_log.max(axis=-1, keepdims=True)
    exp_v = np.exp(scaled_log)
    return (exp_v / exp_v.sum(axis=-1, keepdims=True)).astype(np.float64)


def build_fusion_meta_features(
    deep_probs: np.ndarray,
    deep_tail_max: np.ndarray,
    deep_head_max: np.ndarray,
    struct_features: np.ndarray,
) -> np.ndarray:
    """将校准后 4 类深度概率编码为 8 维高信噪比语义摘要，并与 67 维结构特征拼接为 75 维 Meta-Fusion 向量。"""
    p = np.clip(np.asarray(deep_probs, dtype=np.float64), 1e-6, 1.0)
    p = p / np.maximum(p.sum(axis=-1, keepdims=True), 1e-12)
    log_p = np.log(p)
    entropy = -np.sum(p * log_p, axis=-1, keepdims=True)
    p_sorted = np.sort(p, axis=-1)
    margin = p_sorted[:, -1:] - p_sorted[:, -2:-1]
    t_max = np.asarray(deep_tail_max, dtype=np.float64).reshape(p.shape[0], 1)
    h_max = np.asarray(deep_head_max, dtype=np.float64).reshape(p.shape[0], 1)
    s_mat = np.asarray(struct_features, dtype=np.float64).reshape(p.shape[0], -1)
    meta = np.hstack([log_p, entropy, margin, t_max, h_max, s_mat]).astype(np.float32)
    return np.nan_to_num(meta, nan=0.0, posinf=0.0, neginf=0.0)


def compute_ece(y_true: Union[Sequence[int], np.ndarray], probs: np.ndarray, *, n_bins: int = 10) -> float:
    """计算多分类 Expected Calibration Error (ECE)。"""
    yt = np.asarray(y_true, dtype=np.int64)
    if len(yt) == 0:
        return 0.0
    conf = np.max(probs, axis=1)
    pred = np.argmax(probs, axis=1)
    acc = (pred == yt).astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for b in range(n_bins):
        lo, hi = bins[b], bins[b + 1]
        if b == 0:
            mask = (conf >= lo) & (conf <= hi)
        else:
            mask = (conf > lo) & (conf <= hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            ece += (cnt / len(yt)) * abs(float(np.mean(acc[mask])) - float(np.mean(conf[mask])))
    return round(float(ece), 5)


def load_ai_predictor_bundle(
    *,
    project_root: Optional[Path] = None,
    force_reload: bool = False,
) -> Optional[Dict[str, Any]]:
    """按相对路径加载并缓存 Morphotype AI 双轨权重包。"""
    global _AI_PREDICTOR_CACHE
    if _AI_PREDICTOR_CACHE is not None and not force_reload:
        return _AI_PREDICTOR_CACHE
    joblib_p, _ = get_ai_model_paths(project_root)
    if not joblib_p.is_file():
        return None
    import joblib

    bundle = joblib.load(joblib_p)
    if not isinstance(bundle, dict):
        return None
    _AI_PREDICTOR_CACHE = bundle
    return bundle


def predict_contig_morphotype_ai(
    *,
    proteins: Sequence[StructureProteinItem],
    length_bp: int,
    gc_percent: float,
    module_matrix: StructuralModuleMatrix,
    connector_profile: ConnectorProfile,
    tmp_analyses: Sequence[TmpAnalysisItem],
    ptf_clusters: Sequence[TailFinderCluster],
    completeness: CompletenessAssessment,
    rule_prediction: MorphotypePrediction,
    bundle: Optional[Dict[str, Any]] = None,
    judge_model: Any = None,
    device: Optional[str] = None,
    min_deep_rescue_bp: int = 5000,
) -> Optional[AiMorphotypePrediction]:
    """
    基于 UnifiedJudge V4.3 深度特征 + 结构特征对单条 Contig 运行校准双轨 AI 判别：
    - 当规则引擎具备结构命中时优先运行双模态融合 (`dual_modal_fusion`)；
    - 当规则引擎陷入 Incomplete 但序列 >=5 kb 时自动切换至纯深层语义轨迹 (`ai_deep_only`) 进行零 HMM 救回推断。
    """
    eff_bundle = bundle or load_ai_predictor_bundle()
    if eff_bundle is None:
        return None

    try:
        if judge_model is None:
            judge_model, judge_ver, eff_dev = load_unified_judge_seq_model(device=device)
        else:
            judge_ver = str(eff_bundle.get("judge_version") or "Unified V4.3")
            eff_dev = device or str(next(judge_model.parameters()).device)
    except Exception as exc:
        logger.debug("跳过 AI 形态预测，UnifiedJudge 加载失败: %s", exc)
        return None

    deep_vec, deep_diag = extract_unified_judge_genome_features(
        proteins,
        length_bp=length_bp,
        gc_percent=gc_percent,
        judge_model=judge_model,
        device=eff_dev,
    )
    if float(np.sum(np.abs(deep_vec))) == 0.0:
        return None

    struct_vec = extract_structured_morph_features(
        module_matrix=module_matrix,
        connector_profile=connector_profile,
        tmp_analyses=tmp_analyses,
        ptf_clusters=ptf_clusters,
        completeness=completeness,
        length_bp=length_bp,
        total_orfs=len(proteins),
    )

    classes: Tuple[str, ...] = tuple(str(c) for c in (eff_bundle.get("classes") or MORPH_CLASSES))
    deep_pipe = eff_bundle.get("deep_only_pipeline")
    deep_temp = float(eff_bundle.get("deep_only_temperature", 1.0))
    use_deep_only = (
        rule_prediction.morphotype_code == "Incomplete"
        and length_bp >= min_deep_rescue_bp
        and deep_pipe is not None
    )
    if use_deep_only and deep_pipe is not None:
        raw_probs = deep_pipe.predict_proba(deep_vec[None, :])
        cal_probs = apply_temperature_scaling(raw_probs, deep_temp)[0]
        mode_tag = "ai_deep_only"
    elif eff_bundle.get("fusion_feature_mode") == "meta_75" and deep_pipe is not None:
        deep_raw = deep_pipe.predict_proba(deep_vec[None, :])
        deep_cal = apply_temperature_scaling(deep_raw, deep_temp)
        x_meta = build_fusion_meta_features(
            deep_cal,
            np.array([[deep_diag["deep_tail_prob_max"]]], dtype=np.float32),
            np.array([[deep_diag["deep_head_prob_max"]]], dtype=np.float32),
            struct_vec[None, :],
        )
        pipe = eff_bundle["fusion_pipeline"]
        temp = float(eff_bundle.get("fusion_temperature", 1.0))
        raw_probs = pipe.predict_proba(x_meta)
        cal_probs = apply_temperature_scaling(raw_probs, temp)[0]
        mode_tag = "dual_modal_fusion"
    else:
        pipe = eff_bundle["fusion_pipeline"]
        temp = float(eff_bundle.get("fusion_temperature", 1.0))
        x_in = np.concatenate([deep_vec, struct_vec])[None, :]
        raw_probs = pipe.predict_proba(x_in)
        cal_probs = apply_temperature_scaling(raw_probs, temp)[0]
        mode_tag = "dual_modal_fusion"

    best_idx = int(np.argmax(cal_probs))
    pred_code = classes[best_idx]
    conf = round(float(cal_probs[best_idx]), 4)
    prob_map = {cls_name: round(float(cal_probs[i]), 4) for i, cls_name in enumerate(classes)}

    agrees = pred_code == rule_prediction.morphotype_code
    if agrees:
        conflict_note = ""
    elif rule_prediction.morphotype_code == "Incomplete":
        conflict_note = (
            f"规则引擎因缺少 PHROG/Pfam 同源判为 Incomplete，UnifiedJudge 深度表征在零 HMM 依赖下推断为 "
            f"{pred_code} (校准置信度 {conf * 100:.1f}%)"
        )
    else:
        conflict_note = (
            f"AI 模型 ({pred_code}, {conf * 100:.1f}%) 与规则引擎 ({rule_prediction.morphotype_code}) 结论不一致，建议结合 3D 复核与基因簇人工核实"
        )

    return AiMorphotypePrediction(
        predicted_morphotype=pred_code,  # type: ignore[arg-type]
        confidence=conf,
        calibrated_probs=prob_map,
        mode=mode_tag,  # type: ignore[arg-type]
        model_version=f"{eff_bundle.get('model_version', 'morphotype_ai_v1')} ({judge_ver})",
        agreement_with_rules=agrees,
        conflict_note=conflict_note,
        deep_tail_prob_max=deep_diag["deep_tail_prob_max"],
        deep_head_prob_max=deep_diag["deep_head_prob_max"],
    )
