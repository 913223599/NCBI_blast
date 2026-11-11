# -*- coding: utf-8 -*-
"""历史数据清理

邮件流水线可清理项：
- batches   : 下载目录下的 up_* 收件批次
- outbound  : 回传目录下的 *.zip + *.manifest.json
- docx      : 回传目录下的 *.docx 报告
- annotations: results/annotations 下由回传清单记录的 ANNO_* 注释中间目录
- index     : processed_index.json 去重指纹（清除后同一附件可被重新处理）
- logs      : pipeline.log / run_errors.log

生工 16S 可清理项（按订单）：
- raw_extracted : 原始数据/ 下解压出的文件（原始压缩包仍保留，可重新解压）
- blast_cache   : results/blast/<订单>_16s 比对缓存
- result_csv    : BLAST结果/16S鉴定结果.csv
- order_dir     : 整个订单目录（不可恢复；同时保留已清理标记防止扫描重复建空目录）
- scan_index    : .sangon_mail_index.json 扫描去重记录（清除后邮件扫描将重新识别该订单）
"""
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .sangon_mail_scanner import SangonMailIndex

MAIL_TARGETS = {"batches", "outbound", "docx", "annotations", "index", "logs"}
SANGON_TARGETS = {"raw_extracted", "blast_cache", "result_csv", "order_dir", "scan_index"}


def _older_than(path: Path, cutoff: Optional[float]) -> bool:
    if cutoff is None:
        return True
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _remove(path: Path) -> int:
    """删除文件或目录，返回释放字节数。"""
    if not path.exists():
        return 0
    size = 0
    if path.is_dir():
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(path, ignore_errors=True)
    else:
        size = path.stat().st_size
        path.unlink()
    return size


def cleanup_mail_history(
    download_dir: Path,
    send_dir: Path,
    annotations_dir: Path,
    targets: Iterable[str],
    older_than_days: Optional[int] = None,
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """清理邮件流水线历史数据；names 非空时仅删除指定的批次名 / 文件名。"""
    targets = set(targets) & MAIL_TARGETS
    cutoff = time.time() - older_than_days * 86400 if older_than_days else None
    name_set = set(names or [])
    removed: List[str] = []
    freed = 0

    def _pick(p: Path) -> bool:
        if name_set and p.name not in name_set:
            return False
        return _older_than(p, cutoff)

    removed_batches: List[str] = []
    if "batches" in targets and download_dir.exists():
        for b in download_dir.glob("up_*"):
            if b.is_dir() and _pick(b):
                freed += _remove(b)
                removed.append(str(b))
                removed_batches.append(b.name)

    if ("outbound" in targets or "annotations" in targets) and send_dir.exists():
        for mf in send_dir.glob("*.manifest.json"):
            zip_name = ""
            task_id = mf.name[: -len(".manifest.json")]
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                zip_name = data.get("zip", "")
                task_id = data.get("task_id", task_id)
            except (OSError, json.JSONDecodeError):
                pass
            zip_path = send_dir / zip_name if zip_name else None
            key_match = (not name_set) or (zip_name in name_set) or (task_id in name_set) or (mf.name in name_set)
            if not key_match or not _older_than(mf, cutoff):
                continue
            if "annotations" in targets and task_id:
                anno = annotations_dir / task_id
                if anno.is_dir():
                    freed += _remove(anno)
                    removed.append(str(anno))
            if "outbound" in targets:
                if zip_path and zip_path.exists():
                    freed += _remove(zip_path)
                    removed.append(str(zip_path))
                freed += _remove(mf)
                removed.append(str(mf))

    if "docx" in targets:
        if send_dir.exists():
            for d in send_dir.glob("*.docx"):
                if _pick(d):
                    freed += _remove(d)
                    removed.append(str(d))
        if name_set and annotations_dir.exists():
            for sub in annotations_dir.iterdir():
                if not sub.is_dir():
                    continue
                for d in sub.glob("*.docx"):
                    if d.name in name_set and _older_than(d, cutoff):
                        freed += _remove(d)
                        removed.append(str(d))

    index_removed = 0
    idx_file = download_dir / "processed_index.json"
    # 注意：仅删除批次时保留去重指纹，避免已处理附件被重新下载
    if idx_file.exists() and "index" in targets:
        try:
            idx = json.loads(idx_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            idx = {}
        if isinstance(idx, dict):
            if "index" in targets and not name_set and cutoff is None:
                index_removed = len(idx)
                idx = {}
            elif "index" in targets:
                keep = {}
                for sha, meta in idx.items():
                    batch = meta.get("batch", "") if isinstance(meta, dict) else ""
                    seen = meta.get("first_seen", "") if isinstance(meta, dict) else ""
                    hit_name = (not name_set) or batch in name_set or sha in name_set
                    hit_time = True
                    if cutoff is not None and seen:
                        try:
                            hit_time = time.mktime(time.strptime(seen[:19], "%Y-%m-%dT%H:%M:%S")) < cutoff
                        except ValueError:
                            hit_time = False
                    if hit_name and hit_time:
                        index_removed += 1
                    else:
                        keep[sha] = meta
                idx = keep
            idx_file.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

    if "logs" in targets:
        for log_name in ("pipeline.log", "run_errors.log"):
            lf = download_dir / log_name
            if lf.exists():
                freed += lf.stat().st_size
                lf.write_text("", encoding="utf-8")
                removed.append(str(lf))

    return {
        "removed": removed,
        "removed_count": len(removed),
        "index_removed": index_removed,
        "freed_mb": round(freed / 1024 / 1024, 2),
    }


def cleanup_sangon_history(
    sangon_root: Path,
    blast_results_root: Path,
    order_names: List[str],
    targets: Iterable[str],
) -> Dict[str, Any]:
    """按订单清理生工 16S 历史数据。"""
    targets = set(targets) & SANGON_TARGETS
    removed: List[str] = []
    freed = 0
    cleaned_order_nos: List[str] = []
    target_order_nos: List[str] = []
    clear_all_index = "__ALL__" in order_names

    for name in order_names:
        if name == "__ALL__":
            continue
        if "_" in name:
            target_order_nos.append(name.split("_", 1)[1])
        else:
            target_order_nos.append(name)

        order_dir = sangon_root / name
        if not order_dir.is_dir() or order_dir.parent.resolve() != sangon_root.resolve():
            continue
        if "blast_cache" in targets or "order_dir" in targets:
            cache = blast_results_root / f"{name}_16s"
            if cache.is_dir():
                freed += _remove(cache)
                removed.append(str(cache))
        if "order_dir" in targets:
            freed += _remove(order_dir)
            removed.append(str(order_dir))
            if "_" in name:
                cleaned_order_nos.append(name.split("_", 1)[1])
            continue
        if "raw_extracted" in targets:
            raw = order_dir / "原始数据"
            if raw.is_dir():
                for child in list(raw.iterdir()):
                    freed += _remove(child)
                removed.append(str(raw))
        if "result_csv" in targets:
            csv_file = order_dir / "BLAST结果" / "16S鉴定结果.csv"
            if csv_file.exists():
                freed += _remove(csv_file)
                removed.append(str(csv_file))

    scan_index_cleared = 0
    idx = SangonMailIndex(sangon_root)
    if "scan_index" in targets:
        scan_index_cleared = idx.clear(None if clear_all_index else target_order_nos)
    elif cleaned_order_nos:
        idx.mark_cleaned(cleaned_order_nos)

    return {
        "removed": removed,
        "removed_count": len(removed),
        "scan_index_cleared": scan_index_cleared,
        "freed_mb": round(freed / 1024 / 1024, 2),
    }
