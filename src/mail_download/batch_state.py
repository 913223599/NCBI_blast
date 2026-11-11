# -*- coding: utf-8 -*-
"""邮件批次的流水线处理状态判定与持久化。

职责：
1. 统一清洗序列文件名用于生成任务编号（ANNO_<stem>_<stamp>）；
2. 读取与更新 <batch>/manifest.json 中的 pipeline 处理状态；
3. 兼容无 pipeline 字段的历史批次，依据 annotations/ 与 send_dir/ 中的真实产物判断是否已处理；
4. 筛选「已收件下载但尚未完成注释/打包/回传」的待接续批次，确保先“仅收件”或中途失败后再次“运行流水线”可继续执行。
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .config import DEFAULT_ATTACHMENT_EXTS

IGNORED_BATCH_FILES = {"manifest.json", "pipeline.log", "run_errors.log"}

STATUS_LABELS = {
    "downloaded": "待注释处理",
    "running": "执行中",
    "completed": "已完成",
    "failed": "上次失败",
    "empty": "无序列附件",
}


def clean_task_stem(att_name: str) -> str:
    """将附件主名清洗为安全的任务编号片段。"""
    stem = Path(att_name).stem or "input"
    for ch in (" ", "(", ")", "[", "]", "&", "="):
        stem = stem.replace(ch, "_")
    return stem


def collect_batch_fastas(batch_dir: Path, cfg: Any = None) -> List[Path]:
    """收集批次目录下所有匹配配置扩展名的序列文件（按文件名升序）。"""
    if not batch_dir.exists() or not batch_dir.is_dir():
        return []
    raw_exts = getattr(cfg, "attachment_exts", None) or DEFAULT_ATTACHMENT_EXTS
    allowed = {
        (e.lower() if e.startswith(".") else f".{e.lower()}")
        for e in raw_exts
        if isinstance(e, str) and e.strip()
    }
    found: List[Path] = []
    for p in sorted(batch_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.name in IGNORED_BATCH_FILES:
            continue
        if not allowed or p.suffix.lower() in allowed:
            found.append(p)
    return found


def load_batch_manifest(batch_dir: Path) -> Dict[str, Any]:
    """安全读取批次 manifest.json；缺失或损坏时返回空字典。"""
    mf_path = batch_dir / "manifest.json"
    if not mf_path.is_file():
        return {}
    try:
        data = json.loads(mf_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def is_test_batch(batch_dir: Path, manifest: Optional[Dict[str, Any]] = None) -> bool:
    """判断是否为本地 --test-input 注册的测试批次（不参与日常自动回传）。"""
    if batch_dir.name.endswith("_TEST"):
        return True
    mf = manifest if manifest is not None else load_batch_manifest(batch_dir)
    mail_meta = mf.get("mail") if isinstance(mf.get("mail"), dict) else {}
    sender = str(mail_meta.get("sender") or "").strip().lower()
    return sender == "local-test-input" or str(mail_meta.get("seq") or "").strip().upper() == "TEST"


def _find_legacy_task_ids_for_fasta(
    fasta_name: str,
    send_dir: Path,
    annotations_dir: Path,
) -> List[str]:
    """为无 pipeline 状态字段的老批次查找是否已经生成过注释/回传产物。"""
    stem = clean_task_stem(fasta_name)
    prefix = f"ANNO_{stem}_"
    anno_pat = re.compile(rf"^{re.escape(prefix)}\d{{8}}_\d{{6}}$")
    zip_pat = re.compile(rf"^{re.escape(prefix)}\d{{8}}_\d{{6}}(?:_\d{{8}}_\d{{6}})?\.(?:zip|manifest\.json)$")
    matched_ids: List[str] = []

    if annotations_dir.exists():
        for entry in annotations_dir.iterdir():
            if not entry.is_dir() or not anno_pat.match(entry.name):
                continue
            if (entry / "summary.json").is_file() or (entry / "features.json").is_file():
                matched_ids.append(entry.name)

    if send_dir.exists():
        for entry in send_dir.iterdir():
            if not entry.is_file():
                continue
            m = zip_pat.match(entry.name)
            if m:
                tid = entry.name.split(".manifest.json")[0]
                if entry.name.endswith(".zip"):
                    tid = entry.stem
                if tid not in matched_ids:
                    matched_ids.append(tid)

    return sorted(matched_ids)


def inspect_batch_pipeline_state(
    batch_dir: Path,
    cfg: Any,
    send_dir: Path,
    annotations_dir: Path,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """检查单个批次当前在流水线中的状态（供调度与前端展示共用）。"""
    mf = manifest if manifest is not None else load_batch_manifest(batch_dir)
    fastas = collect_batch_fastas(batch_dir, cfg)
    pipeline_meta = mf.get("pipeline") if isinstance(mf.get("pipeline"), dict) else {}

    if pipeline_meta and pipeline_meta.get("status"):
        status = str(pipeline_meta.get("status"))
        task_ids = [str(t) for t in (pipeline_meta.get("task_ids") or []) if t]
        send_status = str(pipeline_meta.get("send_status") or "")
        label = STATUS_LABELS.get(status, status)
        if status == "completed" and send_status == "skipped_no_send":
            label = "已完成（未发信）"
        return {
            "status": status,
            "status_label": label,
            "send_status": send_status,
            "task_ids": task_ids,
            "last_error": str(pipeline_meta.get("last_error") or ""),
            "updated_at": str(pipeline_meta.get("updated_at") or ""),
            "is_test": is_test_batch(batch_dir, mf),
            "pending": status in ("downloaded", "failed") and bool(fastas) and not is_test_batch(batch_dir, mf),
        }

    if not fastas:
        return {
            "status": "empty",
            "status_label": STATUS_LABELS["empty"],
            "send_status": "",
            "task_ids": [],
            "last_error": "",
            "updated_at": "",
            "is_test": is_test_batch(batch_dir, mf),
            "pending": False,
        }

    # 无 pipeline 字段：通过真实产物反推老批次是否已完成
    legacy_ids: List[str] = []
    all_have_artifacts = True
    for f in fastas:
        found = _find_legacy_task_ids_for_fasta(f.name, send_dir, annotations_dir)
        if not found:
            all_have_artifacts = False
        for tid in found:
            if tid not in legacy_ids:
                legacy_ids.append(tid)

    test_flag = is_test_batch(batch_dir, mf)
    if all_have_artifacts and legacy_ids:
        return {
            "status": "completed",
            "status_label": STATUS_LABELS["completed"],
            "send_status": "",
            "task_ids": legacy_ids,
            "last_error": "",
            "updated_at": "",
            "is_test": test_flag,
            "pending": False,
        }

    return {
        "status": "downloaded",
        "status_label": STATUS_LABELS["downloaded"],
        "send_status": "",
        "task_ids": legacy_ids,
        "last_error": "",
        "updated_at": "",
        "is_test": test_flag,
        "pending": not test_flag,
    }


def mark_batch_pipeline_state(
    batch_dir: Path,
    status: str,
    *,
    task_ids: Optional[List[str]] = None,
    zips: Optional[List[str]] = None,
    send_status: Optional[str] = None,
    last_error: Optional[str] = None,
) -> None:
    """将批次流水线执行状态原子写回 manifest.json（保留原有邮件与附件信息）。"""
    mf_path = batch_dir / "manifest.json"
    data = load_batch_manifest(batch_dir)
    if not data:
        data = {
            "batch": batch_dir.name,
            "download_time": datetime.now().isoformat(timespec="seconds"),
            "mail": {},
            "attachments": [],
        }

    prev = data.get("pipeline") if isinstance(data.get("pipeline"), dict) else {}
    merged = {
        **prev,
        "status": status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if task_ids is not None:
        merged["task_ids"] = list(task_ids)
    if zips is not None:
        merged["zips"] = list(zips)
    if send_status is not None:
        merged["send_status"] = send_status
    if last_error is not None:
        merged["last_error"] = last_error
    elif status == "completed":
        merged.pop("last_error", None)
    if status == "completed":
        merged["completed_at"] = merged["updated_at"]

    data["pipeline"] = merged
    batch_dir.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_pending_batches(
    download_dir: Path,
    cfg: Any,
    send_dir: Path,
    annotations_dir: Path,
    exclude_batches: Optional[Iterable[Path]] = None,
) -> List[Tuple[Path, List[Path]]]:
    """扫描 download_dir 下所有已下载但尚未走完流水线的批次（按批名升序处理）。"""
    if not download_dir.exists() or not download_dir.is_dir():
        return []
    excluded: Set[Path] = {Path(p).resolve() for p in (exclude_batches or [])}
    pending: List[Tuple[Path, List[Path]]] = []

    for bdir in sorted(download_dir.glob("up_*"), key=lambda p: p.name):
        if not bdir.is_dir():
            continue
        if bdir.resolve() in excluded:
            continue
        state = inspect_batch_pipeline_state(bdir, cfg, send_dir, annotations_dir)
        if not state.get("pending"):
            continue
        fastas = collect_batch_fastas(bdir, cfg)
        if fastas:
            pending.append((bdir, fastas))
    return pending

