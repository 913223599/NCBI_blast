# -*- coding: utf-8 -*-
"""
多线程 HTTP Range 分片并发下载模块 (core.download.parallel_downloader)

通过 RemoteFileMeta / SegmentSpec / ParallelRunContext 数据载体收口参数，
支持分片级断点续传、线程安全进度聚合、原子流式合并及受控降级。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from .downloader import (
    DEFAULT_USER_AGENT,
    CancelSignal,
    DownloadCancelledError,
    DownloadConfig,
    DownloadProgressCallback,
    create_http_session,
    format_bytes,
    format_download_progress,
    load_json_dict,
    parse_content_length,
    safe_unlink,
    save_json_dict,
    wait_backoff_with_cancel,
)

logger = logging.getLogger("core.download")


@dataclass(frozen=True)
class RemoteFileMeta:
    """远端支持 Range 分片的元信息快照。"""

    total_bytes: int
    etag: str
    last_modified: str


@dataclass(frozen=True)
class SegmentSpec:
    """单个字节区间分片描述。"""

    index: int
    start: int
    end: int
    path: Path

    @property
    def expected_len(self) -> int:
        return self.end - self.start + 1


class ParallelProgressTracker:
    """线程安全的并发分片进度聚合器。"""

    def __init__(
        self,
        total_bytes: int,
        initial_done: int,
        workers: int,
        progress_cb: Optional[DownloadProgressCallback],
        label: str,
    ) -> None:
        self._lock = threading.Lock()
        self._total_bytes = total_bytes
        self._initial_done = initial_done
        self._done = initial_done
        self._workers = workers
        self._progress_cb = progress_cb
        self._label = label
        self._start_ts = time.monotonic()
        self._last_cb_ts = 0.0
        self._last_cb_pct = -1
        self._last_log_ts = self._start_ts

    def add_bytes(self, delta: int) -> None:
        if delta <= 0:
            return
        with self._lock:
            self._done += delta
            now = time.monotonic()
            speed_bps = max(0.0, (self._done - self._initial_done) / max(0.05, now - self._start_ts))
            pct = int(self._done * 100 / self._total_bytes) if self._total_bytes > 0 else -1
            if self._progress_cb is not None and ((now - self._last_cb_ts) >= 0.5 or pct > self._last_cb_pct):
                self._progress_cb(min(self._done, self._total_bytes), self._total_bytes, speed_bps)
                self._last_cb_ts = now
                self._last_cb_pct = pct
            if (now - self._last_log_ts) >= 5.0:
                logger.info(
                    "[%s] [%s线程] %s",
                    self._label,
                    self._workers,
                    format_download_progress(min(self._done, self._total_bytes), self._total_bytes, speed_bps),
                )
                self._last_log_ts = now

    def emit_final(self) -> None:
        if self._progress_cb is None:
            return
        with self._lock:
            speed_bps = max(0.0, (self._done - self._initial_done) / max(0.05, time.monotonic() - self._start_ts))
            self._progress_cb(min(self._done, self._total_bytes), self._total_bytes, speed_bps)


@dataclass
class ParallelRunContext:
    """并发分片下载共享运行上下文，替代超长参数传递。"""

    safe_url: str
    cfg: DownloadConfig
    cancel_event: Optional[CancelSignal]
    abort_event: threading.Event
    tracker: ParallelProgressTracker


def probe_parallel_support(safe_url: str, cfg: DownloadConfig) -> Tuple[RemoteFileMeta, bool]:
    """探测远端是否支持 HTTP Range 与准确 Content-Length。"""
    probe_timeout = min(8.0, cfg.connect_timeout)
    try:
        with create_http_session(bypass_proxy=cfg.bypass_proxy) as session:
            resp = session.head(
                safe_url,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"},
                timeout=(probe_timeout, probe_timeout),
                allow_redirects=True,
            )
            if resp.status_code >= 400:
                return RemoteFileMeta(-1, "", ""), False
            total = parse_content_length(resp.headers.get("Content-Length"))
            accept_ranges = str(resp.headers.get("Accept-Ranges") or "").lower()
            supports_range = "bytes" in accept_ranges and total > 0
            meta = RemoteFileMeta(
                total_bytes=total,
                etag=str(resp.headers.get("ETag") or "").strip(),
                last_modified=str(resp.headers.get("Last-Modified") or "").strip(),
            )
            return meta, supports_range
    except requests.RequestException as exc:
        logger.debug("HEAD 并行能力探测失败，回退单连接模式 (%s): %s", safe_url, exc)
        return RemoteFileMeta(-1, "", ""), False


def cleanup_parallel_segments(target: Path, max_segments: int = 8) -> None:
    """清理多线程分片临时文件与元数据。"""
    safe_unlink(Path(f"{target}.segs.meta.json"))
    for idx in range(max_segments):
        safe_unlink(Path(f"{target}.seg.{idx}"))
    for extra in target.parent.glob(f"{target.name}.seg.*"):
        safe_unlink(extra)


def _prepare_segment_layout(
    target: Path,
    safe_url: str,
    file_meta: RemoteFileMeta,
    workers: int,
) -> List[SegmentSpec]:
    """校验或重置多线程分片布局，返回分片描述列表。"""
    seg_meta_path = Path(f"{target}.segs.meta.json")
    old_meta = load_json_dict(seg_meta_path)
    meta_valid = (
        str(old_meta.get("url") or "") == safe_url
        and old_meta.get("total_bytes") == file_meta.total_bytes
        and old_meta.get("workers") == workers
        and (not old_meta.get("etag") or not file_meta.etag or str(old_meta.get("etag")) == file_meta.etag)
    )
    if not meta_valid:
        cleanup_parallel_segments(target, workers)
        save_json_dict(
            seg_meta_path,
            {
                "url": safe_url,
                "total_bytes": file_meta.total_bytes,
                "workers": workers,
                "etag": file_meta.etag,
                "last_modified": file_meta.last_modified,
            },
        )

    base_span = file_meta.total_bytes // workers
    layout: List[SegmentSpec] = []
    for idx in range(workers):
        start = idx * base_span
        end = file_meta.total_bytes - 1 if idx == workers - 1 else (start + base_span - 1)
        layout.append(SegmentSpec(idx, start, end, Path(f"{target}.seg.{idx}")))
    return layout


def _download_single_segment_once(spec: SegmentSpec, ctx: ParallelRunContext) -> None:
    """下载单个字节区间的分片，支持已有分片长度续传。"""
    existing = spec.path.stat().st_size if spec.path.is_file() else 0
    if existing > spec.expected_len:
        safe_unlink(spec.path)
        existing = 0
    if existing == spec.expected_len:
        return

    req_start = spec.start + existing
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Encoding": "identity",
        "Range": f"bytes={req_start}-{spec.end}",
    }
    with create_http_session(bypass_proxy=ctx.cfg.bypass_proxy) as session:
        with session.get(
            ctx.safe_url,
            headers=headers,
            stream=True,
            timeout=(ctx.cfg.connect_timeout, ctx.cfg.read_timeout),
            allow_redirects=True,
        ) as resp:
            if resp.status_code != 206:
                raise IOError(f"分片 Range 请求返回非 206 状态码: {resp.status_code}")
            if hasattr(resp.raw, "decode_content"):
                resp.raw.decode_content = False

            written = existing
            with (open(spec.path, "ab") if existing > 0 else open(spec.path, "wb")) as fh:
                for chunk in resp.iter_content(chunk_size=ctx.cfg.chunk_size):
                    if ctx.cancel_event is not None and ctx.cancel_event.is_set():
                        raise DownloadCancelledError("用户已取消下载")
                    if ctx.abort_event.is_set():
                        raise IOError("同组其他分片失败，中止当前分片")
                    if not chunk:
                        continue
                    fh.write(chunk)
                    written += len(chunk)
                    ctx.tracker.add_bytes(len(chunk))

    if written != spec.expected_len:
        raise IOError(f"分片长度不完整 ({written} / {spec.expected_len})")


def _download_segment_with_retry(spec: SegmentSpec, ctx: ParallelRunContext) -> None:
    """带独立退避重试的分片下载 worker。"""
    attempts = max(1, int(ctx.cfg.max_retries))
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        if ctx.cancel_event is not None and ctx.cancel_event.is_set():
            raise DownloadCancelledError("用户已取消下载")
        if ctx.abort_event.is_set():
            raise IOError("并行任务已中止")
        try:
            _download_single_segment_once(spec, ctx)
            return
        except DownloadCancelledError:
            ctx.abort_event.set()
            raise
        except (requests.RequestException, OSError) as exc:
            last_exc = exc
            if attempt >= attempts or ctx.abort_event.is_set():
                break
            wait_backoff_with_cancel(min(4.0, float(attempt)), ctx.cancel_event)
    ctx.abort_event.set()
    raise IOError(f"分片下载失败: {last_exc}")


def _merge_segments_atomically(layout: List[SegmentSpec], target: Path) -> None:
    """校验全部分片字节完整后按序流式合并并原子替换落盘。"""
    part_path = Path(f"{target}.part")
    with open(part_path, "wb") as out_fh:
        for spec in layout:
            actual = spec.path.stat().st_size if spec.path.is_file() else -1
            if actual != spec.expected_len:
                raise IOError(f"分片 {spec.path.name} 校验失败 ({actual} != {spec.expected_len})")
            with open(spec.path, "rb") as in_fh:
                while True:
                    buf = in_fh.read(1024 * 1024)
                    if not buf:
                        break
                    out_fh.write(buf)
    os.replace(part_path, target)
    cleanup_parallel_segments(target, len(layout))
    safe_unlink(Path(f"{target}.part.meta.json"))
    safe_unlink(Path(f"{target}.tmp"))


def parallel_range_download(
    safe_url: str,
    target: Path,
    file_meta: RemoteFileMeta,
    cfg: DownloadConfig,
    progress_cb: Optional[DownloadProgressCallback] = None,
    cancel_event: Optional[CancelSignal] = None,
) -> Path:
    """使用线程池执行 HTTP Range 并发分片下载与合并。"""
    workers = min(8, max(2, int(cfg.num_threads)))
    label = cfg.log_label or target.name
    layout = _prepare_segment_layout(target, safe_url, file_meta, workers)
    initial_done = sum(spec.path.stat().st_size for spec in layout if spec.path.is_file())
    tracker = ParallelProgressTracker(file_meta.total_bytes, initial_done, workers, progress_cb, label)
    if progress_cb is not None:
        progress_cb(min(initial_done, file_meta.total_bytes), file_meta.total_bytes, 0.0)

    logger.info("[%s] 启用 %s 线程 HTTP Range 并发下载 (%s)", label, workers, format_bytes(file_meta.total_bytes))
    ctx = ParallelRunContext(
        safe_url=safe_url,
        cfg=cfg,
        cancel_event=cancel_event,
        abort_event=threading.Event(),
        tracker=tracker,
    )
    cancelled_exc: Optional[DownloadCancelledError] = None
    other_exc: Optional[Exception] = None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_download_segment_with_retry, spec, ctx) for spec in layout]
        for fut in as_completed(futures):
            try:
                fut.result()
            except DownloadCancelledError as exc:
                cancelled_exc = exc
                ctx.abort_event.set()
            except Exception as exc:
                if other_exc is None:
                    other_exc = exc
                ctx.abort_event.set()

    if cancelled_exc is not None:
        raise cancelled_exc
    if other_exc is not None:
        raise other_exc

    tracker.emit_final()
    _merge_segments_atomically(layout, target)
    return target
