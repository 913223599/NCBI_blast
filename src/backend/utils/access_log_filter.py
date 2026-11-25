# -*- coding: utf-8 -*-
"""
Uvicorn 访问日志轮询降噪过滤器 (access_log_filter)

单一职责：
仅静默高频硬件监控与健康探测接口的成功 (HTTP 200) GET 访问日志，
保留所有 4xx/5xx 异常状态与全部业务接口日志，避免控制台视觉刷屏。
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

DEFAULT_QUIET_POLLING_PATHS: frozenset[str] = frozenset(
    {
        "/api/core/system_metrics",
        "/api/health",
    }
)

_ACCESS_MSG_RE = re.compile(
    r'"GET\s+([^\s?"]+)(?:\?[^\s"]*)?\s+HTTP/[^"]+"\s+(\d{3})\b'
)


def _normalize_quiet_paths(quiet_paths: Optional[Iterable[str]]) -> frozenset[str]:
    if quiet_paths is None:
        return DEFAULT_QUIET_POLLING_PATHS
    cleaned = {
        item.strip()
        for item in quiet_paths
        if isinstance(item, str) and item.strip().startswith("/")
    }
    return frozenset(cleaned)


class QuietPollingAccessFilter(logging.Filter):
    """过滤高频健康检查与系统监控的 200 GET 访问日志。"""

    def __init__(self, quiet_paths: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self.quiet_paths: frozenset[str] = _normalize_quiet_paths(quiet_paths)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.quiet_paths:
            return True

        args = getattr(record, "args", None)
        if isinstance(args, tuple) and len(args) >= 5:
            method = str(args[1]).strip().upper()
            full_path = str(args[2]).strip()
            base_path = full_path.split("?", 1)[0]
            try:
                status_code = int(args[4])
            except (TypeError, ValueError):
                status_code = None

            if method == "GET" and base_path in self.quiet_paths and status_code == 200:
                return False
            return True

        message = record.getMessage()
        matched = _ACCESS_MSG_RE.search(message)
        if matched:
            base_path = matched.group(1)
            status_code = int(matched.group(2))
            if base_path in self.quiet_paths and status_code == 200:
                return False
        return True


def install_uvicorn_access_filter(
    logger_name: str = "uvicorn.access",
    quiet_paths: Optional[Iterable[str]] = None,
) -> QuietPollingAccessFilter:
    """幂等挂载 QuietPollingAccessFilter 至指定 Uvicorn 访问日志器。"""
    target_logger = logging.getLogger(logger_name)
    for existing in target_logger.filters:
        if isinstance(existing, QuietPollingAccessFilter):
            return existing

    access_filter = QuietPollingAccessFilter(quiet_paths=quiet_paths)
    target_logger.addFilter(access_filter)
    return access_filter
