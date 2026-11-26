# -*- coding: utf-8 -*-
"""
静态安全与可靠性守卫单元测试：
1. src.core.http_guard: 协议白名单校验（拦截 file:// / ftp:// / 空主机）与安全下载；
2. src.core.async_tasks: 托管异步任务强引用持有、完成后自动回收与异常日志记录。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Set

import pytest

from src.core.async_tasks import spawn_tracked_task
from src.core.http_guard import build_safe_request, safe_urlopen, validate_http_url


def test_validate_http_url_allows_http_https_and_blocks_unsafe_schemes() -> None:
    assert validate_http_url("https://example.com/data.cif") == "https://example.com/data.cif"
    assert validate_http_url("http://127.0.0.1:8765/api/health") == "http://127.0.0.1:8765/api/health"

    for bad in (
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
        "javascript:alert(1)",
        "https://",
        "",
    ):
        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            validate_http_url(bad)


def test_build_safe_request_and_safe_urlopen_reject_file_scheme(tmp_path: Path) -> None:
    sample = tmp_path / "secret.txt"
    sample.write_text("top-secret", encoding="utf-8")
    file_url = sample.as_uri()

    with pytest.raises(ValueError):
        build_safe_request(file_url)
    with pytest.raises(ValueError):
        safe_urlopen(file_url)


def test_spawn_tracked_task_retains_and_cleans_up_reference(caplog: pytest.LogCaptureFixture) -> None:
    async def _run() -> None:
        registry: Set[asyncio.Task[object]] = set()
        ran = False

        async def _ok_job() -> None:
            nonlocal ran
            await asyncio.sleep(0.01)
            ran = True

        task = spawn_tracked_task(_ok_job(), registry, label="ok_job")
        assert task in registry
        await task
        await asyncio.sleep(0)
        assert ran is True
        assert task not in registry

        async def _boom_job() -> None:
            raise RuntimeError("simulated bg failure")

        with caplog.at_level(logging.WARNING, logger="core.async_tasks"):
            bad_task = spawn_tracked_task(_boom_job(), registry, label="boom_job")
            with pytest.raises(RuntimeError, match="simulated bg failure"):
                await bad_task
            await asyncio.sleep(0)
        assert bad_task not in registry
        assert "boom_job" in caplog.text

    asyncio.run(_run())
