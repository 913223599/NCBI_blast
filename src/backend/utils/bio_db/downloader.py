# -*- coding: utf-8 -*-
"""向后兼容门面：通用流式下载实现已下沉至 src/core/download/downloader.py。"""
from ....core.download.downloader import (
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

__all__ = [
    "CancelSignal",
    "DEFAULT_USER_AGENT",
    "DownloadCancelledError",
    "DownloadConfig",
    "DownloadProgressCallback",
    "create_http_session",
    "format_bytes",
    "format_download_progress",
    "load_json_dict",
    "parse_content_length",
    "parse_content_range_total",
    "safe_unlink",
    "save_json_dict",
    "stream_download_file",
    "stream_download_with_mirrors",
    "wait_backoff_with_cancel",
]
