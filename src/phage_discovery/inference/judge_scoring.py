"""Judge ORF 提取、模型加载、集成评分与基础辅助工具模块。"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ...utils.resource_guard import get_safe_cpu_budget
from ..student.judge_calibration import apply_blended_logit_calibration
from ..student.orf_functional_judge import (
    JUDGE_CLASS_NAMES,
    build_orf_functional_judge,
    predict_contig_orfs_with_judge,
)

logger = logging.getLogger("phage_discovery.inference.judge_region_refiner")

def _extract_single_contig_orfs(item: Tuple[str, str]) -> Tuple[str, List[Tuple[int, int, int, str]]]:
    import pyrodigal

    cid, seq = item
    s_up = (seq or "").upper()
    lst: List[Tuple[int, int, int, str]] = []
    if len(s_up) >= 100:
        gf = pyrodigal.GeneFinder(meta=True)
        for g in gf.find_genes(s_up.encode("ascii", errors="replace")):
            aa = g.translate(include_stop=False).strip()
            if aa and "*" not in aa:
                lst.append((g.begin - 1, g.end, g.strand, aa))
    lst.sort(key=lambda x: (x[0], x[1]))
    return cid, lst

def extract_contig_orfs_pyrodigal(
    contig_seqs: Dict[str, str],
    *,
    contig_ids: Optional[Sequence[str]] = None,
    workers: Optional[int] = None,
) -> Dict[str, List[Tuple[int, int, int, str]]]:
    """按需多核并行提取指定 Contig 的 Pyrodigal 连续 ORF 列表 [(start, end, strand, aa_seq), ...]。"""
    target_ids = list(contig_ids) if contig_ids is not None else list(contig_seqs.keys())
    items = [(cid, contig_seqs[cid]) for cid in target_ids if cid in contig_seqs]
    if not items:
        return {}

    max_w = get_safe_cpu_budget(requested=workers or 0, reserve_cores=4, max_cap=16 if workers is None else None)
    out: Dict[str, List[Tuple[int, int, int, str]]] = {}
    if max_w <= 1 or len(items) == 1:
        for it in items:
            cid, lst = _extract_single_contig_orfs(it)
            out[cid] = lst
        return out

    with ThreadPoolExecutor(max_workers=min(max_w, len(items))) as pool:
        for cid, lst in pool.map(_extract_single_contig_orfs, items):
            out[cid] = lst
    return out

def _load_judge_ckpt(ckpt_path: Path, device: str):
    import torch

    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = build_orf_functional_judge(
        stat_mean=ck["stat_mean"],
        stat_std=ck["stat_std"],
        use_aa_seq=bool(ck["use_aa_seq"]),
        arch=str(ck.get("arch", "baseline")),
    ).to(device)
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()
    return model

def resolve_unified_version_tag(
    uni_meta: Optional[Dict[str, Any]] = None,
    s12_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """按显式声明优先、架构标识与 DNA 微调元信息兜底的契约统一解析版本标签。"""
    u_m = uni_meta or {}
    s_m = s12_meta or {}
    explicit = str(u_m.get("model_version") or u_m.get("version") or "").strip()
    if explicit:
        return explicit

    uni_arch = str(u_m.get("arch") or "").strip().lower()
    if uni_arch.startswith("unified_v"):
        suffix = uni_arch[len("unified_v") :].replace("_", ".")
        if suffix:
            return f"Unified V{suffix}"

    if "v4_3_dna_finetune" in s_m or str(s_m.get("model_version") or "").lower() == "v4_3":
        return "Unified V4.3"
    return "Unified V4"

def load_judge_ensemble_bundle(
    models_v4_root: Path,
    *,
    device: str = "cpu",
    r3_subdir: str = "orf_judge_ablation_r3",
    r2_subdir: str = "orf_judge_ablation_r2",
    prefer_unified: bool = True,
) -> Optional[Dict[str, Any]]:
    """从 models/full_v4 下按相对路径加载统一分化模型（优先）或回退加载 R3 + R2 分离模型组。"""
    root = Path(models_v4_root).resolve()
    uni_dir = root / "orf_judge_unified"
    uni_meta: Dict[str, Any] = {}
    if prefer_unified and (uni_dir / "unified_judge_seq.pt").is_file():
        stat_pt = uni_dir / "orf_judge_statonly.pt"
        if not stat_pt.is_file():
            stat_pt = root / r3_subdir / "orf_judge_statonly.pt"
        seq_pt = uni_dir / "unified_judge_seq.pt"
        cal_npz = uni_dir / "logit_calibrator.npz"
        if not cal_npz.is_file():
            cal_npz = root / r3_subdir / "logit_calibrator.npz"
        summary_p = uni_dir / "unified_summary.json"
        if summary_p.is_file():
            try:
                loaded_sum = json.loads(summary_p.read_text(encoding="utf-8"))
                if isinstance(loaded_sum, dict):
                    uni_meta = loaded_sum
            except Exception:
                uni_meta = {}
        r2_seq_obj = None
        use_uni = True
    else:
        r3_dir = root / r3_subdir
        stat_pt = r3_dir / "orf_judge_statonly.pt"
        seq_pt = r3_dir / "orf_judge_seq.pt"
        cal_npz = r3_dir / "logit_calibrator.npz"
        r2_seq_pt = root / r2_subdir / "orf_judge_seq.pt"
        r2_seq_obj = _load_judge_ckpt(r2_seq_pt, device) if r2_seq_pt.is_file() else None
        use_uni = False

    if not stat_pt.is_file() or not seq_pt.is_file():
        return None

    calibrator = None
    if cal_npz.is_file():
        cd = np.load(cal_npz, allow_pickle=False)
        calibrator = {
            "func_alphas": cd["func_alphas"],
            "phage_alpha": float(cd["phage_alpha"][0]),
            "func_bias": cd["func_bias"],
            "phage_bias": float(cd["phage_bias"][0]),
        }

    r3_seq_model = _load_judge_ckpt(seq_pt, device)
    judge_arch = str(uni_meta.get("arch") or getattr(r3_seq_model, "arch", "") or ("unified" if use_uni else "r3"))
    if use_uni and not uni_meta.get("arch"):
        uni_meta = {**uni_meta, "arch": judge_arch}

    s12_meta: Dict[str, Any] = {}
    s12_meta_p = root / "stage1_2" / "stage1_2_meta.json"
    if s12_meta_p.is_file():
        try:
            loaded_s12 = json.loads(s12_meta_p.read_text(encoding="utf-8"))
            if isinstance(loaded_s12, dict):
                s12_meta = loaded_s12
        except Exception:
            s12_meta = {}
    model_version = resolve_unified_version_tag(uni_meta, s12_meta) if use_uni else "R3+R2 Ensemble"

    return {
        "r3_stat": _load_judge_ckpt(stat_pt, device),
        "r3_seq": r3_seq_model,
        "calibrator": calibrator,
        "r2_seq": r2_seq_obj,
        "unified_mode": use_uni,
        "judge_arch": judge_arch,
        "model_version": model_version,
        "judge_summary_meta": uni_meta,
        "device": device,
    }

def score_contigs_with_judge_bundle(
    bundle: Dict[str, Any],
    orfs_by_contig: Dict[str, List[Tuple[int, int, int, str]]],
    *,
    contig_ids: Optional[Sequence[str]] = None,
    batch_size: int = 32,
    active_experts: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, np.ndarray]]:
    """对每条 Contig 仅执行 1 次共享底座前向推理并按需分化输出 R3 校准概率与完整度分数。"""
    device = str(bundle.get("device", "cpu"))
    m_stat = bundle["r3_stat"]
    m_seq = bundle["r3_seq"]
    m_r2 = bundle.get("r2_seq")
    cal = bundle.get("calibrator")
    is_uni = getattr(m_seq, "arch", "") in ("unified", "unified_v4_3")

    target_cids = list(contig_ids) if contig_ids is not None else list(orfs_by_contig.keys())
    scored: Dict[str, Dict[str, np.ndarray]] = {}
    for cid in target_cids:
        orfs = orfs_by_contig.get(cid, [])
        if not orfs:
            scored[cid] = {
                "phage_probs": np.zeros(0, dtype=np.float32),
                "func10_probs": np.zeros((0, len(JUDGE_CLASS_NAMES)), dtype=np.float32),
                "r2_core_probs": np.zeros((0, 5), dtype=np.float32),
            }
            continue
        rs = predict_contig_orfs_with_judge(m_stat, orfs, device=device, batch_size=batch_size, return_logits=True)
        rq = predict_contig_orfs_with_judge(
            m_seq,
            orfs,
            device=device,
            batch_size=batch_size,
            return_logits=True,
            active_experts=active_experts if is_uni else None,
            return_intact=is_uni,
        )
        f10, ph = apply_blended_logit_calibration(
            rs["func10_logits"],
            rq["func10_logits"],
            rs["phage_logits"],
            rq["phage_logits"],
            cal,
        )
        if is_uni and "intact_func_probs" in rq:
            r2_core = rq["intact_func_probs"][:, :5]
        elif m_r2 is not None:
            r2_out = predict_contig_orfs_with_judge(m_r2, orfs, device=device, batch_size=batch_size)
            r2_core = r2_out["func10_probs"][:, :5]
        else:
            r2_core = f10[:, :5]
        scored[cid] = {
            "phage_probs": ph,
            "func10_probs": f10,
            "r2_core_probs": r2_core,
        }
    return scored

def trim_triggered(new_val: int, old_val: int) -> bool:
    return new_val > old_val

def _get_r2_core_probs(sc: Dict[str, np.ndarray]) -> np.ndarray:
    """安全获取 R2/Head B 核心结构 5 维概率矩阵，缺失时回落至 R3 功能前 5 列。"""
    if "r2_core_probs" in sc and sc["r2_core_probs"] is not None:
        return sc["r2_core_probs"]
    return sc["func10_probs"][:, :5]
