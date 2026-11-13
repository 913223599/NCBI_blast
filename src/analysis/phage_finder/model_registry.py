# -*- coding: utf-8 -*-
"""
零硬编码 V4.2 模型与蛋白门控数据库动态发现器

严格使用相对项目根路径解析、环境变量与 ConfigManager 配置，
仅支持并自动探测本地已部署的 Student V4.2 (含 ContextRefiner + 200bp SubBinRefiner) 模型及可选蛋白库。
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ENV_MODELS_ROOT = "PHAGE_DISCOVERY_MODELS_ROOT"
ENV_MODEL_DIR = "PHAGE_DISCOVERY_MODEL_DIR"
ENV_BLAST_DB = "PHAGE_DISCOVERY_BLAST_DB"

# 仅保留 V4.2 版本相对候选路径
_KNOWN_V4_2_SPECS: List[Tuple[str, str, str, int]] = [
    ("student_v4_2", "full_v4/student_v4_2", "Student V4.2 边界精修模型", 1),
    ("student_v4_2", "student_v4_2", "Student V4.2 边界精修模型", 2),
]


def _normalize_storage_path(raw_path: str, project_root: Path = PROJECT_ROOT) -> str:
    """若路径位于项目根目录下则优先序列化为相对路径，否则保留规范化路径。"""
    cleaned = (raw_path or "").strip()
    if not cleaned:
        return ""
    p = Path(cleaned)
    resolved = p.resolve() if p.is_absolute() else (project_root / p).resolve()
    try:
        rel = resolved.relative_to(project_root.resolve())
        return rel.as_posix()
    except ValueError:
        return str(resolved)


def _resolve_user_path(raw_path: Optional[str], project_root: Path = PROJECT_ROOT) -> Optional[Path]:
    """将用户配置或输入路径安全解析为绝对 Path（相对路径以项目根为基准）。"""
    if not raw_path or not raw_path.strip():
        return None
    p = Path(raw_path.strip())
    if p.is_absolute():
        return p.resolve()
    return (project_root / p).resolve()


def _get_phage_config() -> Dict[str, Any]:
    """从 ConfigManager 安全读取 phage_discovery 配置节点。"""
    try:
        from ...utils.config_manager import get_config_manager

        cfg = get_config_manager().config_data
        sec = cfg.get("phage_discovery") if isinstance(cfg, dict) else None
        return dict(sec) if isinstance(sec, dict) else {}
    except Exception:
        return {}


def _get_candidate_model_roots(project_root: Path = PROJECT_ROOT) -> List[Path]:
    """按优先级收集候选模型根目录（零硬编码盘符）。"""
    candidates: List[Path] = []
    env_root = os.environ.get(ENV_MODELS_ROOT)
    if env_root:
        p = _resolve_user_path(env_root, project_root)
        if p is not None:
            candidates.append(p)

    cfg = _get_phage_config()
    cfg_root = _resolve_user_path(cfg.get("models_root"), project_root)
    if cfg_root is not None:
        candidates.append(cfg_root)

    # 项目自身与相邻 Phage data 工作目录相对引用
    sibling_data = project_root.parent / "Phage data"
    candidates.extend([
        project_root / "models" / "phage_discovery",
        project_root / "models",
        sibling_data / "models",
    ])

    unique: List[Path] = []
    seen = set()
    for cand in candidates:
        key = str(cand).lower()
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    return unique


def _inspect_v4_2_dir(
    model_dir: Path,
    *,
    model_id: str,
    label: str,
    priority: int,
) -> Optional[Dict[str, Any]]:
    """校验目录是否为完整 V4.2 模型权重包并返回标定默认值与评估摘要。"""
    root = model_dir.resolve()
    v4_pt = root / "student_v4.pt"
    v4_meta = root / "student_v4_meta.json"
    subbin_pt = root / "subbin_refiner.pt"

    if not (v4_pt.exists() and v4_meta.exists()):
        return None

    meta: Dict[str, Any] = {}
    try:
        meta = json.loads(v4_meta.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    has_subbin = subbin_pt.exists() or bool(meta.get("use_subbin_refiner"))
    if not has_subbin:
        return None

    rep: Dict[str, Any] = {}
    for rep_name in ("student_v4_report.json", "student_report.json"):
        rep_path = root / rep_name
        if rep_path.exists():
            try:
                rep = json.loads(rep_path.read_text(encoding="utf-8"))
                break
            except Exception:
                rep = {}

    dec = rep.get("decoder_tuned_on_val") or {}
    has_ref = (root / "context_refiner.pt").exists() or bool(meta.get("use_context_refiner"))

    return {
        "model_id": model_id,
        "label": label,
        "version": "V4.2",
        "priority": priority,
        "path": str(root),
        "weights_file": str(v4_pt),
        "params": int(meta.get("params") or rep.get("params") or 0),
        "has_context_refiner": has_ref,
        "has_subbin_refiner": True,
        "decoder_defaults": {
            "seed_threshold": float(dec.get("seed_threshold", 0.95)),
            "extend_threshold": float(dec.get("extend_threshold", 0.30)),
            "sub_threshold": float(dec.get("sub_threshold", 0.45)),
            "merge_gap_bp": 3000,
            "min_region_bp": 3000,
        },
        "recommended": True,
    }


def discover_available_models(project_root: Path = PROJECT_ROOT) -> List[Dict[str, Any]]:
    """扫描所有候选位置，仅返回已部署且去重后的可用 V4.2 模型列表。"""
    found: List[Dict[str, Any]] = []
    seen_paths = set()

    # 1. 优先检查环境变量或配置显式指定的 V4.2 模型目录
    cfg = _get_phage_config()
    for source_id, raw_val, lbl, prio in (
        ("env_v4_2", os.environ.get(ENV_MODEL_DIR), "Student V4.2 (环境变量指定)", 0),
        ("config_v4_2", cfg.get("default_model_dir"), "Student V4.2 (工作台配置)", 0),
    ):
        cand_dir = _resolve_user_path(raw_val, project_root)
        if cand_dir is not None and cand_dir.exists():
            info = _inspect_v4_2_dir(
                cand_dir,
                model_id=source_id,
                label=lbl,
                priority=prio,
            )
            if info and info["path"] not in seen_paths:
                seen_paths.add(info["path"])
                found.append(info)

    # 2. 遍历各候选根目录下的 V4.2 标准路径（不再发现旧版 V2/V3/V4.1）
    for root_dir in _get_candidate_model_roots(project_root):
        if not root_dir.exists() or not root_dir.is_dir():
            continue

        direct_info = _inspect_v4_2_dir(
            root_dir,
            model_id="student_v4_2",
            label="Student V4.2 边界精修模型",
            priority=1,
        )
        if direct_info and direct_info["path"] not in seen_paths:
            seen_paths.add(direct_info["path"])
            found.append(direct_info)

        for mid, rel_sub, label, prio in _KNOWN_V4_2_SPECS:
            sub_dir = root_dir / rel_sub
            if not sub_dir.exists():
                continue
            info = _inspect_v4_2_dir(
                sub_dir,
                model_id=mid,
                label=label,
                priority=prio,
            )
            if info and info["path"] not in seen_paths:
                seen_paths.add(info["path"])
                found.append(info)

    found.sort(key=lambda item: (int(item.get("priority", 99)), str(item.get("model_id", ""))))
    return found


def resolve_model_dir(
    model_id: Optional[str] = None,
    custom_model_dir: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """解析并返回唯一受支持的 V4.2 模型目录元信息。"""
    if custom_model_dir and custom_model_dir.strip():
        custom_path = _resolve_user_path(custom_model_dir, project_root)
        if custom_path is None or not custom_path.exists():
            raise FileNotFoundError(f"指定的 V4.2 模型目录不存在: {custom_model_dir}")
        info = _inspect_v4_2_dir(
            custom_path,
            model_id="student_v4_2_custom",
            label=f"Student V4.2 ({custom_path.name})",
            priority=0,
        )
        if not info:
            raise FileNotFoundError(
                f"目录 {custom_path} 不是完整的 V4.2 模型目录 "
                "(需同时包含 student_v4.pt、student_v4_meta.json 与 subbin_refiner.pt)"
            )
        return info

    available = discover_available_models(project_root)
    if not available:
        searched = ", ".join(str(p) for p in _get_candidate_model_roots(project_root))
        raise FileNotFoundError(
            "未检测到可用的 Student V4.2 模型。请将模型放置于项目 models/full_v4/student_v4_2 或 "
            f"同级 Phage data/models/full_v4/student_v4_2 下，或在界面中指定 V4.2 目录。已探测路径: {searched}"
        )

    if model_id:
        for item in available:
            if item["model_id"] == model_id:
                return item

    return available[0]


def resolve_protein_gate_resources(
    custom_blast_db: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """解析可选第二阶段蛋白门控所需的 blastp 可执行文件与噬菌体蛋白参考库。"""
    from ...phage_discovery.inference.protein_gate import _has_blast_db_files
    from ...workbench.models.tool_config import ToolConfig

    blastp_path = ToolConfig.resolve_bio_tool("blastp")

    candidates: List[Path] = []
    if custom_blast_db and custom_blast_db.strip():
        p = _resolve_user_path(custom_blast_db, project_root)
        if p is not None:
            candidates.append(p)

    env_db = os.environ.get(ENV_BLAST_DB)
    if env_db:
        p = _resolve_user_path(env_db, project_root)
        if p is not None:
            candidates.append(p)

    cfg = _get_phage_config()
    cfg_db = _resolve_user_path(cfg.get("blast_db"), project_root)
    if cfg_db is not None:
        candidates.append(cfg_db)

    sibling_data = project_root.parent / "Phage data"
    candidates.extend([
        project_root / "database" / "phage_discovery" / "phage_refseq_prot",
        project_root / "database" / "blastdb" / "phage_refseq_prot",
        project_root / "database" / "swissprot" / "swissprot",
        sibling_data / "blastdb" / "phage_refseq_prot",
    ])

    resolved_db: Optional[Path] = None
    for cand in candidates:
        try:
            if _has_blast_db_files(cand):
                resolved_db = cand
                break
        except OSError:
            continue

    ready = blastp_path is not None and resolved_db is not None
    return {
        "ready": ready,
        "blastp_bin": str(blastp_path) if blastp_path is not None else "",
        "blast_db": str(resolved_db) if resolved_db is not None else "",
    }


def get_safe_workers(requested: Optional[int] = None) -> int:
    """动态计算多核安全并发数，强制保留至少 2 个核心防止桌面主机卡死。"""
    cpu_cnt = os.cpu_count() or 4
    safe_cap = max(1, cpu_cnt - 2)
    if requested is not None and requested > 0:
        return max(1, min(requested, safe_cap))
    return safe_cap


def detect_compute_environment() -> Dict[str, Any]:
    """探测当前 GPU/CUDA 与 CPU 安全线程配置及显存容量信息。"""
    cpu_cnt = os.cpu_count() or 4
    safe_workers = get_safe_workers()
    cuda_available = False
    gpu_name = ""
    gpu_vram_gb = 0.0

    try:
        import torch

        cuda_available = torch.cuda.is_available()
        if cuda_available:
            props = torch.cuda.get_device_properties(0)
            gpu_name = str(props.name)
            gpu_vram_gb = round(float(props.total_memory) / (1024.0 ** 3), 2)
    except Exception:
        cuda_available = False

    return {
        "cpu_cores": cpu_cnt,
        "safe_workers": safe_workers,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
        "gpu_vram_gb": gpu_vram_gb,
        "default_device": "cuda" if cuda_available else "cpu",
    }


def save_phage_discovery_config(
    *,
    models_root: Optional[str] = None,
    default_model_dir: Optional[str] = None,
    blast_db: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """将用户设定的 V4.2 模型目录/蛋白库路径以规范化相对路径持久化至 config.json。"""
    from ...utils.config_manager import get_config_manager

    cm = get_config_manager()
    cur = dict(cm.config_data.get("phage_discovery") or {})
    if models_root is not None:
        cur["models_root"] = _normalize_storage_path(models_root, project_root)
    if default_model_dir is not None:
        cur["default_model_dir"] = _normalize_storage_path(default_model_dir, project_root)
    if blast_db is not None:
        cur["blast_db"] = _normalize_storage_path(blast_db, project_root)

    cm.config_data["phage_discovery"] = cur
    cm._save_config()
    return cur
