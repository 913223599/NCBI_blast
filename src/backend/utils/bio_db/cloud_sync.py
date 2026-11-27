# -*- coding: utf-8 -*-
"""
NCBI 官方云端 BLAST 数据库高速同步模块 (bio_db.cloud_sync)

优先使用 NCBI 官方同步在 Google Cloud Storage (GCP) 与 Amazon S3 的公共桶：
1. 自动探测 latest-dir 与 <db>-<type>-metadata.json；
2. 仅拉取真实索引分片与元数据（如 16S_ribosomal_RNA 仅 ~17.6 MB，免解压）；
3. 仅当本地缺少 taxdb.btd / taxdb.bti 时按需补拉，避免重复传输 187 MB；
4. 并发拉取时引入内部联动中止信号，任一文件失败立即停止同组其余线程；
5. 先落盘 .cloud_staging 暂存目录，校验通过后原子替换目标目录。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ....core.http_guard import validate_http_url
from .downloader import (
    DEFAULT_USER_AGENT,
    CancelSignal,
    DownloadCancelledError,
    DownloadConfig,
    create_http_session,
    format_download_progress,
    safe_unlink,
    stream_download_file,
)

logger = logging.getLogger("api_server")

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_TAXDB_CORE_FILES: Tuple[str, ...] = ("taxdb.btd", "taxdb.bti")

ProgressReporter = Callable[[int, str], None]


@dataclass(frozen=True)
class NcbiCloudMirror:
    """NCBI 官方云端镜像描述。"""

    name: str
    base_url: str
    bypass_proxy: bool = False


DEFAULT_NCBI_CLOUD_MIRRORS: Tuple[NcbiCloudMirror, ...] = (
    NcbiCloudMirror("NCBI 官方 GCP 云端加速源", "https://storage.googleapis.com/blast-db", bypass_proxy=False),
    NcbiCloudMirror("NCBI 官方 AWS S3 直连源", "https://ncbi-blast-databases.s3.amazonaws.com", bypass_proxy=True),
    NcbiCloudMirror("NCBI 官方 AWS S3 代理源", "https://ncbi-blast-databases.s3.amazonaws.com", bypass_proxy=False),
)


class _CompositeCancelSignal:
    """组合外部用户取消信号与内部同组失败联动中止信号。"""

    def __init__(self, external: Optional[CancelSignal], abort_event: threading.Event) -> None:
        self._external = external
        self._abort = abort_event

    def is_set(self) -> bool:
        return self._abort.is_set() or (self._external is not None and self._external.is_set())


def _validate_safe_name(name: str, kind: str) -> str:
    """严格校验目录名与文件名，杜绝路径穿越。"""
    cleaned = str(name or "").strip()
    if not cleaned or ".." in cleaned or not _SAFE_TOKEN_RE.match(cleaned):
        raise ValueError(f"非法的 NCBI 云端{kind}名: {name!r}")
    return cleaned


def _fetch_cloud_manifest(
    mirror: NcbiCloudMirror,
    db_name: str,
    db_type: str = "nucl",
    timeout: float = 10.0,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """拉取云端 latest-dir 与数据库 metadata JSON，校验并返回安全文件名清单。"""
    base = validate_http_url(mirror.base_url).rstrip("/")
    headers = {"User-Agent": DEFAULT_USER_AGENT}

    with create_http_session(bypass_proxy=mirror.bypass_proxy) as session:
        latest_url = validate_http_url(f"{base}/latest-dir")
        resp_dir = session.get(latest_url, headers=headers, timeout=(timeout, timeout))
        resp_dir.raise_for_status()
        latest_dir = _validate_safe_name(resp_dir.text.strip(), "版本目录")

        meta_name = _validate_safe_name(f"{db_name}-{db_type}-metadata.json", "元数据文件")
        meta_url = validate_http_url(f"{base}/{latest_dir}/{meta_name}")
        resp_meta = session.get(meta_url, headers=headers, timeout=(timeout, timeout))
        resp_meta.raise_for_status()
        metadata = resp_meta.json()

    if not isinstance(metadata, dict):
        raise ValueError("云端元数据格式异常：根节点不是 JSON 对象")
    raw_files = metadata.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("云端元数据缺少有效的 files 文件清单")

    file_names: List[str] = []
    seen = set()
    for item in raw_files:
        raw_str = str(item or "").strip()
        if ".." in raw_str.split("/") or ".." in raw_str.split("\\"):
            raise ValueError(f"检测到非法路径穿越片段: {raw_str!r}")
        fname = raw_str.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        safe_fname = _validate_safe_name(fname, "索引文件")
        if safe_fname not in seen:
            seen.add(safe_fname)
            file_names.append(safe_fname)

    if meta_name not in seen:
        file_names.append(meta_name)
    return latest_dir, metadata, file_names


def _append_missing_taxdb_files(target_dir: Path, file_names: List[str], require_taxdb: bool) -> List[str]:
    """仅当本地缺失 taxdb.btd / taxdb.bti 时补拉，避免重复传输 187 MB。"""
    if not require_taxdb:
        return file_names
    result = list(file_names)
    existing_set = set(result)
    for tax_name in _TAXDB_CORE_FILES:
        local_tax = target_dir / tax_name
        if (not local_tax.is_file() or local_tax.stat().st_size <= 0) and tax_name not in existing_set:
            result.append(tax_name)
            existing_set.add(tax_name)
    return result


class _CloudBatchProgress:
    """聚合多个并发文件下载字节并线性映射到目标百分比区间。"""

    def __init__(
        self,
        source_name: str,
        total_files: int,
        estimated_total_bytes: int,
        progress_cb: Optional[ProgressReporter],
    ) -> None:
        self._lock = threading.Lock()
        self._source_name = source_name
        self._total_files = max(1, total_files)
        self._estimated_total = max(0, estimated_total_bytes)
        self._per_file_done: Dict[str, int] = {}
        self._per_file_total: Dict[str, int] = {}
        self._completed_files = 0
        self._progress_cb = progress_cb
        self._start_ts = time.monotonic()
        self._last_emit_ts = 0.0

    def update_file(self, fname: str, downloaded: int, total: int) -> None:
        with self._lock:
            self._per_file_done[fname] = max(0, downloaded)
            if total > 0:
                self._per_file_total[fname] = total
            self._emit_locked(force=False)

    def mark_file_done(self) -> None:
        with self._lock:
            self._completed_files += 1
            self._emit_locked(force=True)

    def _emit_locked(self, force: bool) -> None:
        if self._progress_cb is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_emit_ts) < 0.4:
            return
        self._last_emit_ts = now

        total_done = sum(self._per_file_done.values())
        known_sum = sum(self._per_file_total.values())
        total_bytes = max(self._estimated_total, known_sum, total_done)
        speed_bps = total_done / max(0.05, now - self._start_ts)
        ratio = min(1.0, total_done / total_bytes) if total_bytes > 0 else min(1.0, self._completed_files / self._total_files)
        pct = 12 + int(round(80 * ratio))
        detail = format_download_progress(total_done, total_bytes, speed_bps)
        self._progress_cb(pct, f"{self._source_name}：{detail} [{self._completed_files}/{self._total_files} 文件]")


def _download_cloud_files(
    mirror: NcbiCloudMirror,
    latest_dir: str,
    file_names: List[str],
    staging_dir: Path,
    tracker: _CloudBatchProgress,
    cancel_event: Optional[CancelSignal],
    max_workers: int,
) -> None:
    """并发拉取云端文件至暂存目录，任一任务失败立即触发联动中止。"""
    base = validate_http_url(mirror.base_url).rstrip("/")
    workers = min(max(1, int(max_workers)), 4, len(file_names))
    abort_event = threading.Event()
    composite_cancel = _CompositeCancelSignal(cancel_event, abort_event)

    def _download_one(fname: str) -> Path:
        if composite_cancel.is_set():
            raise DownloadCancelledError("用户或同组任务已取消下载")
        url = validate_http_url(f"{base}/{latest_dir}/{fname}")
        dest = staging_dir / fname
        cfg = DownloadConfig(
            connect_timeout=12.0,
            read_timeout=25.0,
            max_retries=3,
            log_label=f"{latest_dir}:{fname}",
            num_threads=2,
            min_parallel_size=8 * 1024 * 1024,
            bypass_proxy=mirror.bypass_proxy,
        )
        stream_download_file(
            url,
            dest,
            progress_cb=lambda dl, tot, _spd: tracker.update_file(fname, dl, tot),
            cancel_event=composite_cancel,
            config=cfg,
        )
        if not dest.is_file() or dest.stat().st_size <= 0:
            raise IOError(f"云端文件落盘为空: {fname}")
        tracker.mark_file_done()
        return dest

    first_err: Optional[Exception] = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_download_one, fname) for fname in file_names]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                abort_event.set()
                if first_err is None:
                    first_err = exc

    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError("用户已取消更新")
    if first_err is not None:
        raise first_err


def _commit_staging_files(staging_dir: Path, target_dir: Path, db_name: str, file_names: List[str]) -> None:
    """将暂存目录中全部校验通过的文件原子替换到目标库目录并清理残留。"""
    for fname in file_names:
        os.replace(staging_dir / fname, target_dir / fname)
    shutil.rmtree(staging_dir, ignore_errors=True)
    for stale_name in (f"{db_name}.tar.gz.tmp", f"{db_name}.tar.gz.part", f"{db_name}.tar.gz.part.meta.json"):
        safe_unlink(target_dir / stale_name)


def _sync_from_single_mirror(
    mirror: NcbiCloudMirror,
    db_name: str,
    target_dir: Path,
    db_type: str,
    require_taxdb: bool,
    progress_cb: Optional[ProgressReporter],
    cancel_event: Optional[CancelSignal],
    max_workers: int,
) -> Dict[str, Any]:
    """从单个 NCBI 官方云端源拉取元数据、并发下载并原子提交。"""
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError("用户已取消更新")
    if progress_cb is not None:
        progress_cb(10, f"正在连接 {mirror.name} 获取最新索引清单...")

    latest_dir, metadata, manifest_files = _fetch_cloud_manifest(mirror, db_name, db_type=db_type)
    file_names = _append_missing_taxdb_files(target_dir, manifest_files, require_taxdb)
    raw_bytes_total = metadata.get("bytes-total")
    estimated_total = int(raw_bytes_total) if isinstance(raw_bytes_total, int) and raw_bytes_total > 0 else 0

    staging_dir = target_dir / ".cloud_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    tracker = _CloudBatchProgress(mirror.name, len(file_names), estimated_total, progress_cb)

    _download_cloud_files(mirror, latest_dir, file_names, staging_dir, tracker, cancel_event, max_workers)

    if progress_cb is not None:
        progress_cb(94, f"正在验证并原子替换 {len(file_names)} 个索引文件...")
    _commit_staging_files(staging_dir, target_dir, db_name, file_names)

    return {
        "source": mirror.name,
        "latest_dir": latest_dir,
        "last_updated": str(metadata.get("last-updated") or ""),
        "files_count": len(file_names),
        "bytes_total": estimated_total,
    }


def sync_ncbi_blast_db_from_cloud(
    db_name: str,
    target_dir: Path,
    *,
    db_type: str = "nucl",
    require_taxdb: bool = True,
    progress_cb: Optional[ProgressReporter] = None,
    cancel_event: Optional[CancelSignal] = None,
    mirrors: Sequence[NcbiCloudMirror] = DEFAULT_NCBI_CLOUD_MIRRORS,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """按优先级依次尝试 NCBI 官方云端源同步 BLAST 数据库。"""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []

    for idx, mirror in enumerate(mirrors, 1):
        try:
            logger.info("[NCBI Cloud] 尝试通过 %s 同步 %s...", mirror.name, db_name)
            return _sync_from_single_mirror(
                mirror=mirror,
                db_name=db_name,
                target_dir=target,
                db_type=db_type,
                require_taxdb=require_taxdb,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                max_workers=max_workers,
            )
        except DownloadCancelledError:
            raise
        except Exception as exc:
            errors.append(f"{mirror.name}: {exc}")
            logger.warning("[NCBI Cloud] %s 同步失败 (%s/%s): %s", mirror.name, idx, len(mirrors), exc)

    raise RuntimeError("NCBI 官方云端加速源全部不可用: " + " | ".join(errors))
