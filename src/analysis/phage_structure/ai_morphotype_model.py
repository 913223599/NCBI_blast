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
import torch
import torch.nn as nn

from ...workbench.models.tool_config import ToolConfig
from .portable_ai_runtime import (
    get_portable_model_paths,
    has_portable_model_files,
    load_portable_ai_bundle,
    safe_joblib_load,
)
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
FUSION_META_DIM: int = 8 + STRUCT_TOTAL_DIM  # 75 (V1: 4 log-probs + entropy + margin + tail_max + head_max + 67 struct)

# V2 ORF 级 9 通道细粒度形态学角色监督契约
FINE_ROLE_CHANNELS: Tuple[str, ...] = (
    "MYO_TSP",
    "MYO_BASE_TTP",
    "SIPHO_MTP_TAP",
    "LONG_TMP",
    "PODO_CORE",
    "NON_TAILED_CORE",
    "CONN_SIPHO_MYO",
    "CONN_PODO",
    "HEAD_CAPSID",
)
FINE_ROLE_CHANNEL_TO_ROLES: Tuple[Tuple[str, ...], ...] = (
    ("TSP",),
    ("BASEPLATE_MYO", "FIBRITIN_COLLAR", "TTP"),
    ("MTP", "TAP", "DIT"),
    ("TMP",),
    ("TTPA_B", "INTERNAL_VIRION", "TAIL_NEEDLE", "COLLAR_PODO"),
    ("NON_TAILED_MARKER",),
    ("CONN_AD1", "CONN_HC1", "CONN_NECK1", "CONN_TAIL_TERM"),
    ("CONN_AD3", "CONN_HC3"),
    ("MCP", "PORTAL", "TERL", "TERS", "HEAD_SCAFFOLD_PROTEASE"),
)
ROLE_TO_FINE_CHANNEL: Dict[str, int] = {
    role: idx
    for idx, roles in enumerate(FINE_ROLE_CHANNEL_TO_ROLES)
    for role in roles
}

ORF_EMBED_DIM: int = 160 + 1024 + 10 + 10 + 3  # 1207
FINE_ROLE_SUMMARY_DIM: int = len(FINE_ROLE_CHANNELS) * 8 + 12  # 84
FUSION_META_V2_DIM: int = 8 + len(FINE_ROLE_CHANNELS) + STRUCT_TOTAL_DIM + 1  # 85

_AI_PREDICTOR_CACHE: Dict[str, Dict[str, Any]] = {}
_JUDGE_RUNTIME_CACHE: Dict[str, Any] = {}
_FINE_MLP_CACHE: Dict[Tuple[int, str], nn.Module] = {}


def get_ai_model_paths(
    project_root: Optional[Path] = None,
    version: str = "auto",
) -> Tuple[Path, Path]:
    """返回相对工程根目录的 AI 双轨分类器权重路径与元数据路径；auto 模式优先 V2（含便携权重）并平滑回退 V1。"""
    root = Path(project_root) if project_root else ToolConfig.PROJECT_ROOT
    model_dir = root / "models" / "phage_structure"
    v2_p = model_dir / "morphotype_ai_v2.joblib"
    v2_m = model_dir / "morphotype_ai_v2_meta.json"
    v1_p = model_dir / "morphotype_ai_v1.joblib"
    v1_m = model_dir / "morphotype_ai_v1_meta.json"
    if version == "v2":
        return v2_p, v2_m
    if version == "v1":
        return v1_p, v1_m
    if v2_p.is_file() or has_portable_model_files(v2_p):
        return v2_p, v2_m
    return v1_p, v1_m


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
    except Exception as _exc:
        logger.debug("_resolve_unified_judge_dir 忽略非致命异常: %s", _exc)

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


def check_ai_classifier_ready(
    project_root: Optional[Path] = None,
    version: str = "auto",
) -> bool:
    """检查双轨 AI 形态分类权重包（便携版或 joblib）与 UnifiedJudge 底座是否均已就绪。"""
    joblib_p, _ = get_ai_model_paths(project_root, version=version)
    has_weights = has_portable_model_files(joblib_p) or joblib_p.is_file()
    return has_weights and check_unified_judge_ready(project_root)


def release_ai_judge_memory() -> None:
    """释放缓存的 PyTorch UnifiedJudge 与细粒度角色解码器显存，切换引擎前强制调用。"""
    global _JUDGE_RUNTIME_CACHE, _FINE_MLP_CACHE
    _JUDGE_RUNTIME_CACHE.clear()
    _FINE_MLP_CACHE.clear()
    gc.collect()
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception as _exc:
        logger.debug("release_ai_judge_memory 忽略非致命异常: %s", _exc)


def load_unified_judge_seq_model(
    *,
    device: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> Tuple[Any, str, str]:
    """加载并缓存冻结的 UnifiedJudge V4.3 主序列+操纵子注意力网络。"""
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
        except Exception as _exc:
            logger.debug("load_unified_judge_seq_model 忽略非致命异常: %s", _exc)
    version_tag = resolve_unified_version_tag(uni_meta, {})

    _JUDGE_RUNTIME_CACHE.clear()
    _JUDGE_RUNTIME_CACHE[eff_dev] = (model, version_tag, eff_dev)
    return model, version_tag, eff_dev


class FineRoleOrfMLP(nn.Module):
    """基于 UnifiedJudge V4.3 逐 ORF 1207 维语义嵌入的 9 通道细粒度结构角色解码器。"""

    def __init__(
        self,
        in_dim: int = ORF_EMBED_DIM,
        num_roles: int = len(FINE_ROLE_CHANNELS),
    ) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.LayerNorm(in_dim),
            nn.Linear(in_dim, 256),
            nn.GELU(),
            nn.Dropout(0.25),
            nn.Linear(256, 128),
            nn.GELU(),
            nn.Dropout(0.20),
            nn.Linear(128, num_roles),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def encode_fine_role_targets(proteins: Sequence[StructureProteinItem]) -> np.ndarray:
    """将结构蛋白角色编码为 9 通道 uint8 多标签矩阵（供 V2 ORF 解码器监督训练）。"""
    y = np.zeros((len(proteins), len(FINE_ROLE_CHANNELS)), dtype=np.uint8)
    for idx, prot in enumerate(proteins):
        ch = ROLE_TO_FINE_CHANNEL.get(prot.structural_role)
        if ch is not None:
            y[idx, ch] = 1
    return y


def predict_fine_role_probs(
    orf_embed: np.ndarray,
    state_dict: Dict[str, Any],
    *,
    device: str = "cpu",
    batch_size: int = 512,
) -> np.ndarray:
    """基于纯 CPU state_dict 重建 FineRoleOrfMLP 并批量输出逐 ORF 9 通道细粒度概率。"""
    if orf_embed.shape[0] == 0:
        return np.zeros((0, len(FINE_ROLE_CHANNELS)), dtype=np.float32)

    cache_key = (id(state_dict), device)
    model = _FINE_MLP_CACHE.get(cache_key)
    if model is None:
        mlp = FineRoleOrfMLP(in_dim=int(orf_embed.shape[1]), num_roles=len(FINE_ROLE_CHANNELS))
        mlp.load_state_dict(state_dict, strict=True)
        mlp.to(device)
        mlp.eval()
        for param in mlp.parameters():
            param.requires_grad_(False)
        _FINE_MLP_CACHE[cache_key] = mlp
        model = mlp

    dev = torch.device(device)
    out_chunks: List[np.ndarray] = []
    bs = max(1, batch_size)
    with torch.no_grad():
        for i in range(0, orf_embed.shape[0], bs):
            xb = torch.from_numpy(orf_embed[i : i + bs]).to(dev, dtype=torch.float32)
            probs = torch.sigmoid(model(xb)).float().cpu().numpy()
            out_chunks.append(probs)
    return np.vstack(out_chunks).astype(np.float32)


def extract_unified_judge_orf_and_genome_features(
    proteins: Sequence[StructureProteinItem],
    length_bp: int,
    gc_percent: float = 50.0,
    *,
    judge_model: Any = None,
    device: Optional[str] = None,
    batch_size: int = 16,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
    """
    仅基于 Contig 排序 ORF（零 HMM / 零 Pfam / 零 PTF）执行单次 UnifiedJudge V4.3 前向，
    同时产出 2916 维 Contig 表征、逐 ORF 1207 维语义嵌入、ORF 氨基酸长度与可解释信号摘要。
    """
    from ...phage_discovery.student.orf_functional_judge import (
        CTX_WIN_ORFS,
        NUM_JUDGE_CLASSES,
        slice_contig_orf_windows,
    )

    sorted_prots = [p for p in sorted(proteins, key=lambda x: x.start) if (p.translation or "").strip()]
    m = len(sorted_prots)
    empty_diag = {"deep_tail_prob_max": 0.0, "deep_head_prob_max": 0.0, "coding_density": 0.0}
    if m == 0:
        return (
            np.zeros(DEEP_TOTAL_DIM, dtype=np.float32),
            np.zeros((0, ORF_EMBED_DIM), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            empty_diag,
        )

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
        return (
            np.zeros(DEEP_TOTAL_DIM, dtype=np.float32),
            np.zeros((0, ORF_EMBED_DIM), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            empty_diag,
        )

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

    eff_bp = max(1.0, float(length_bp))
    rel_pos = np.clip(
        np.array([0.5 * (p.start + p.end) / eff_bp for p in sorted_prots], dtype=np.float32),
        0.0,
        1.0,
    )
    strand_sign = np.array([1.0 if p.strand != "-" else -1.0 for p in sorted_prots], dtype=np.float32)
    log_len_norm = (np.log1p(aa_lens) / 8.0).astype(np.float32)
    orf_embed = np.hstack(
        [
            h_orf,
            dist_orf,
            f_orf,
            i_orf,
            log_len_norm[:, None],
            rel_pos[:, None],
            strand_sign[:, None],
        ]
    ).astype(np.float32)
    orf_embed = np.nan_to_num(orf_embed, nan=0.0, posinf=0.0, neginf=0.0)

    return (
        full_vec,
        orf_embed,
        aa_lens,
        {
            "deep_tail_prob_max": round(deep_tail_max, 4),
            "deep_head_prob_max": round(deep_head_max, 4),
            "coding_density": round(coding_density, 4),
        },
    )


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
    deep_vec, _, _, diag = extract_unified_judge_orf_and_genome_features(
        proteins,
        length_bp=length_bp,
        gc_percent=gc_percent,
        judge_model=judge_model,
        device=device,
        batch_size=batch_size,
    )
    return deep_vec, {
        "deep_tail_prob_max": diag["deep_tail_prob_max"],
        "deep_head_prob_max": diag["deep_head_prob_max"],
    }


def aggregate_fine_role_contig_features(
    orf_role_probs: np.ndarray,
    orf_aa_lens: np.ndarray,
    length_bp: int,
    gc_percent: float = 50.0,
    coding_density: float = 0.85,
) -> np.ndarray:
    """将逐 ORF 9 通道细粒度结构角色概率汇聚为 84 维 Contig 判别特征（零 HMM 依赖）。"""
    m = int(orf_role_probs.shape[0])
    if m == 0:
        return np.zeros(FINE_ROLE_SUMMARY_DIM, dtype=np.float32)

    p = np.clip(np.asarray(orf_role_probs, dtype=np.float64), 0.0, 1.0)
    aa = np.maximum(1.0, np.asarray(orf_aa_lens, dtype=np.float64).reshape(-1))
    log_aa = np.log1p(aa)
    top_k = min(2, m)

    feats: List[float] = []
    max_per_ch: List[float] = []
    for c_i in range(len(FINE_ROLE_CHANNELS)):
        pc = p[:, c_i]
        max_val = float(np.max(pc))
        max_per_ch.append(max_val)
        top2_val = float(np.mean(np.sort(pc)[-top_k:]))
        sum_val = float(np.sum(pc))
        cnt35 = float(np.sum(pc > 0.35))
        cnt50 = float(np.sum(pc > 0.50))
        frac35 = float(cnt35 / max(1, m))
        mask35 = pc > 0.35
        max_len_35 = float(np.log1p(np.max(aa[mask35]))) if np.any(mask35) else 0.0
        w_mean_aa = float(np.sum(pc * log_aa) / max(1e-3, sum_val))
        feats.extend([max_val, top2_val, sum_val, cnt35, cnt50, frac35, max_len_35, w_mean_aa])

    # 6-ORF 滑动窗口共线性共现统计与跨形态对比差异（12 维）
    win_len = min(6, m)
    win_myo = 0.0
    win_sip = 0.0
    win_pod = 0.0
    win_tail_sum = 0.0
    for st in range(0, m - win_len + 1):
        seg = p[st : st + win_len]
        seg_max = np.max(seg, axis=0)
        win_myo = max(win_myo, float(seg_max[0] * seg_max[1]))
        win_sip = max(win_sip, float(seg_max[2] * seg_max[3]))
        win_pod = max(win_pod, float(seg_max[4] * seg_max[8]))
        win_tail_sum = max(win_tail_sum, float(np.sum(np.max(seg[:, :5], axis=1))))

    m0, m1, m2, m3, m4, m5, m6, m7, _ = max_per_ch
    non_capsid_peak = float(np.max(p[:, :8]))
    gc_density_term = float(coding_density * np.log1p(max(1, length_bp)) / 12.0 + 0.05 * (gc_percent / 100.0))

    feats.extend(
        [
            win_myo,
            win_sip,
            win_pod,
            win_tail_sum,
            m0 - m2,
            m1 - m2,
            max(m0, m1) - m4,
            m3 - m4,
            m6 - m7,
            m5 - max(m0, m2, m4),
            non_capsid_peak,
            gc_density_term,
        ]
    )
    vec = np.asarray(feats, dtype=np.float32)
    return np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)


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
    """将校准后 4 类深度概率编码为 8 维高信噪比语义摘要，并与 67 维结构特征拼接为 75 维 Meta-Fusion 向量 (V1)。"""
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


def build_fusion_meta_v2_features(
    deep_probs: np.ndarray,
    deep_tail_max: np.ndarray,
    deep_head_max: np.ndarray,
    fine_role_max_9: np.ndarray,
    struct_features: np.ndarray,
    has_rule_hit: Optional[np.ndarray] = None,
) -> np.ndarray:
    """构建 V2 85 维动态置信度融合特征 (8 维深概率摘要 + 9 维细粒度角色峰值 + 67 维结构特征 + 1 维规则命中指示)。"""
    p = np.clip(np.asarray(deep_probs, dtype=np.float64), 1e-6, 1.0)
    p = p / np.maximum(p.sum(axis=-1, keepdims=True), 1e-12)
    log_p = np.log(p)
    entropy = -np.sum(p * log_p, axis=-1, keepdims=True)
    p_sorted = np.sort(p, axis=-1)
    margin = p_sorted[:, -1:] - p_sorted[:, -2:-1]
    t_max = np.asarray(deep_tail_max, dtype=np.float64).reshape(p.shape[0], 1)
    h_max = np.asarray(deep_head_max, dtype=np.float64).reshape(p.shape[0], 1)
    f9 = np.asarray(fine_role_max_9, dtype=np.float64).reshape(p.shape[0], len(FINE_ROLE_CHANNELS))
    s_mat = np.asarray(struct_features, dtype=np.float64).reshape(p.shape[0], -1)
    if has_rule_hit is None:
        rule_signal = s_mat[:, :16].sum(axis=1) + s_mat[:, 37:52].sum(axis=1) + s_mat[:, 55]
        hit_col = (rule_signal > 0.0).astype(np.float64).reshape(p.shape[0], 1)
    else:
        hit_col = np.asarray(has_rule_hit, dtype=np.float64).reshape(p.shape[0], 1)
    meta = np.hstack([log_p, entropy, margin, t_max, h_max, f9, s_mat, hit_col]).astype(np.float32)
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


def _load_bundle_from_model_path(joblib_p: Path) -> Optional[Dict[str, Any]]:
    """优先加载零 sklearn 依赖便携包 (.portable.npz/.json)，缺失时通过 safe_joblib_load 兼容回退。"""
    if has_portable_model_files(joblib_p):
        npz_p, json_p = get_portable_model_paths(joblib_p)
        bundle = load_portable_ai_bundle(npz_p, json_p)
        if isinstance(bundle, dict):
            return bundle
    if joblib_p.is_file():
        bundle = safe_joblib_load(joblib_p, convert_pipelines=True)
        if isinstance(bundle, dict):
            return bundle
    return None


def load_ai_predictor_bundle(
    *,
    project_root: Optional[Path] = None,
    version: str = "auto",
    force_reload: bool = False,
) -> Optional[Dict[str, Any]]:
    """按相对路径加载并缓存 Morphotype AI 双轨权重包（优先零依赖便携版并兼容 V2/V1 回退）。"""
    joblib_p, _ = get_ai_model_paths(project_root, version=version)
    if not (has_portable_model_files(joblib_p) or joblib_p.is_file()):
        return None
    cache_key = str(joblib_p.resolve())
    if cache_key in _AI_PREDICTOR_CACHE and not force_reload:
        return _AI_PREDICTOR_CACHE[cache_key]

    try:
        bundle = _load_bundle_from_model_path(joblib_p)
    except Exception as exc:
        logger.warning("加载 AI 分类器权重失败 (%s): %s", joblib_p.name, exc)
        if version == "auto" and joblib_p.name == "morphotype_ai_v2.joblib":
            v1_p, _ = get_ai_model_paths(project_root, version="v1")
            if has_portable_model_files(v1_p) or v1_p.is_file():
                try:
                    bundle = _load_bundle_from_model_path(v1_p)
                except Exception as v1_exc:
                    logger.warning("回退加载 V1 权重同样失败 (%s): %s", v1_p.name, v1_exc)
                    return None
            else:
                return None
        else:
            return None

    if not isinstance(bundle, dict):
        return None
    _AI_PREDICTOR_CACHE[cache_key] = bundle
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
    基于 UnifiedJudge V4.3 深度特征 + 结构特征对单条 Contig 运行校准双轨 AI 判别（兼容 V1 与 V2）：
    - 当规则引擎具备结构命中时优先运行双模态融合 (`dual_modal_fusion`)；
    - 当规则引擎陷入 Incomplete 但序列 >=5 kb 时自动切换至纯深层语义轨迹 (`ai_deep_only`)，
      并结合归一化熵、校准置信度与语义峰值实施残缺碎片保守拒识 (`abstained`)。
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

    deep_vec, orf_embed, aa_lens, deep_diag = extract_unified_judge_orf_and_genome_features(
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

    fine_max_9: Optional[np.ndarray] = None
    is_v2 = (
        eff_bundle.get("model_version") == "morphotype_ai_v2"
        or "fine_role_mlp_state_dict" in eff_bundle
    )
    if is_v2 and "fine_role_mlp_state_dict" in eff_bundle and deep_pipe is not None:
        orf_probs = predict_fine_role_probs(
            orf_embed,
            eff_bundle["fine_role_mlp_state_dict"],
            device=eff_dev,
        )
        fine_max_9 = (
            np.max(orf_probs, axis=0).astype(np.float32)
            if orf_probs.shape[0] > 0
            else np.zeros(len(FINE_ROLE_CHANNELS), dtype=np.float32)
        )
        fine_84 = aggregate_fine_role_contig_features(
            orf_probs,
            aa_lens,
            length_bp=length_bp,
            gc_percent=gc_percent,
            coding_density=float(deep_diag.get("coding_density", 0.85)),
        )
        deep_v2_in = np.concatenate([deep_vec, fine_84])[None, :]
        deep_raw = deep_pipe.predict_proba(deep_v2_in)
        deep_cal = apply_temperature_scaling(deep_raw, deep_temp)

        if use_deep_only:
            cal_probs = deep_cal[0]
            mode_tag = "ai_deep_only"
        else:
            has_hit = np.array([[0.0 if rule_prediction.morphotype_code == "Incomplete" else 1.0]], dtype=np.float32)
            x_meta_v2 = build_fusion_meta_v2_features(
                deep_cal,
                np.array([[deep_diag["deep_tail_prob_max"]]], dtype=np.float32),
                np.array([[deep_diag["deep_head_prob_max"]]], dtype=np.float32),
                fine_max_9[None, :],
                struct_vec[None, :],
                has_rule_hit=has_hit,
            )
            pipe = eff_bundle["fusion_pipeline"]
            temp = float(eff_bundle.get("fusion_temperature", 1.0))
            raw_probs = pipe.predict_proba(x_meta_v2)
            cal_probs = apply_temperature_scaling(raw_probs, temp)[0]
            mode_tag = "dual_modal_fusion"
    elif use_deep_only and deep_pipe is not None:
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

    p_safe = np.clip(cal_probs.astype(np.float64), 1e-7, 1.0)
    p_safe = p_safe / np.sum(p_safe)
    entropy_norm = round(float(-np.sum(p_safe * np.log(p_safe)) / np.log(max(2, len(classes)))), 4)

    abstained = False
    if mode_tag == "ai_deep_only":
        fine_tail_max = (
            float(np.max(fine_max_9[:6]))
            if fine_max_9 is not None
            else float(deep_diag["deep_tail_prob_max"])
        )
        extreme_uncertainty = conf < 0.50 or entropy_norm > 0.85
        lacks_structural_semantics = (
            deep_diag["deep_tail_prob_max"] < 0.40
            and deep_diag["deep_head_prob_max"] < 0.40
            and fine_tail_max < 0.45
        )
        if extreme_uncertainty or lacks_structural_semantics:
            abstained = True

    if abstained:
        pred_code = "Incomplete"
        agrees = True
        conflict_note = (
            f"AI 深度表征校准置信度较低 ({conf * 100:.1f}%, 归一化熵 {entropy_norm:.2f}) "
            f"或缺乏结构模块语义信号，采取保守拒识维持 Incomplete"
        )
    else:
        agrees = pred_code == rule_prediction.morphotype_code
        if agrees:
            conflict_note = ""
        elif rule_prediction.morphotype_code == "Incomplete":
            conflict_note = (
                f"规则引擎因缺少 PHROG/Pfam 同源判为 Incomplete，UnifiedJudge 深度表征在零 HMM 依赖下推断为 "
                f"{pred_code} (校准置信度 {conf * 100:.1f}%)"
            )
            if conf < 0.65:
                conflict_note += "（置信度偏低，建议结合 3D 结构复核）"
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
        abstained=abstained,
        entropy_norm=entropy_norm,
        conflict_note=conflict_note,
        deep_tail_prob_max=deep_diag["deep_tail_prob_max"],
        deep_head_prob_max=deep_diag["deep_head_prob_max"],
    )
