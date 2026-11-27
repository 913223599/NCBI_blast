# -*- coding: utf-8 -*-
"""通用 HTTP/HTTPS 安全流式与多线程分片下载子包 (core.download)。"""
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
    parse_content_range_total,
    safe_unlink,
    save_json_dict,
    stream_download_file,
    stream_download_with_mirrors,
    wait_backoff_with_cancel,
)
from .parallel_downloader import (
    RemoteFileMeta,
    cleanup_parallel_segments,
    parallel_range_download,
    probe_parallel_support,
)

__all__ = [
    "CancelSignal",
    "DEFAULT_USER_AGENT",
    "DownloadCancelledError",
    "DownloadConfig",
    "DownloadProgressCallback",
    "RemoteFileMeta",
    "cleanup_parallel_segments",
    "create_http_session",
    "format_bytes",
    "format_download_progress",
    "load_json_dict",
    "parallel_range_download",
    "parse_content_length",
    "parse_content_range_total",
    "probe_parallel_support",
    "safe_unlink",
    "save_json_dict",
    "stream_download_file",
    "stream_download_with_mirrors",
    "wait_backoff_with_cancel",
]
