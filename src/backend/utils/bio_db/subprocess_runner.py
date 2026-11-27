# -*- coding: utf-8 -*-
"""
生物数据库子进程执行与 WSL 脚本路径辅助 (bio_db.subprocess_runner)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections import deque
from typing import List, Optional, Tuple

from ....workbench.models.tool_config import ToolConfig
from ..compat import get_short_path_name
from .downloader import DownloadCancelledError, DownloadConfig

logger = logging.getLogger("api_server")

_SAFE_SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def build_wsl_script_argv(script_name: str) -> Optional[List[str]]:
    """构造在 WSL 中执行部署脚本的安全参数列表（禁止拼接 shell 字符串）。"""
    if not _SAFE_SCRIPT_NAME_RE.match(script_name or "") or ".." in script_name:
        raise ValueError(f"非法脚本名称: {script_name!r}")

    from ....assembly.env.wsl_manager import WSLManager

    project_root = str(ToolConfig.PROJECT_ROOT).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)", project_root)
    if not m:
        return None
    distro = WSLManager.get_best_distro()
    mnt_path = f"/mnt/{m.group(1).lower()}/{m.group(2)}/scripts/{script_name}"
    return ["wsl", "-d", distro, "-u", "root", "bash", mnt_path]


def build_wsl_script_command(script_name: str) -> Optional[str]:
    """兼容旧调用：构造在 WSL 中执行部署脚本的完整命令字符串。"""
    argv = build_wsl_script_argv(script_name)
    if not argv:
        return None
    distro, mnt_path = argv[2], argv[6]
    return f'wsl -d "{distro}" -u root bash "{mnt_path}"'


def resolve_makeblastdb() -> str:
    """优先通过 ToolConfig.resolve_bio_tool 解析 makeblastdb，再回退 get_tool_path 并转短路径。"""
    resolved = ToolConfig.resolve_bio_tool("makeblastdb")
    if resolved is None:
        resolved = ToolConfig.get_tool_path("makeblastdb")
    return get_short_path_name(str(resolved))


def check_cancelled(cancel_event: Optional[threading.Event]) -> None:
    """若取消事件已置位，立即抛出 DownloadCancelledError。"""
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError("用户已取消更新")


async def _terminate_subprocess(proc: asyncio.subprocess.Process) -> None:
    """安全终止异步子进程，避免僵尸进程残留。"""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()


async def run_subprocess_with_progress(
    cmd_args: List[str],
    *,
    cwd: Optional[str] = None,
    progress_cb: Optional[object] = None,
    cancel_event: Optional[threading.Event] = None,
    start_pct: int = 10,
    end_pct: int = 95,
    stage_label: str = "正在执行建库命令",
) -> Tuple[int, str]:
    """
    异步执行子进程（禁止 shell=True），流式读取输出、周期汇报进度并响应取消信号。
    """
    check_cancelled(cancel_event)
    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    tail_lines: deque[str] = deque(maxlen=20)
    last_emit = time.monotonic()
    pct = start_pct
    if callable(progress_cb):
        progress_cb(pct, f"{stage_label}...")

    async def _watch_cancel() -> None:
        while proc.returncode is None:
            if cancel_event is not None and cancel_event.is_set():
                await _terminate_subprocess(proc)
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(_watch_cancel())
    try:
        if proc.stdout is not None:
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    tail_lines.append(line)
                    logger.info("[%s] %s", stage_label, line)
                now = time.monotonic()
                if callable(progress_cb) and (now - last_emit) >= 1.0:
                    pct = min(end_pct - 1, pct + 2)
                    preview = line[:80] if line else "正在处理..."
                    progress_cb(pct, f"{stage_label}: {preview}")
                    last_emit = now
        rc = await proc.wait()
    finally:
        if not watcher.done():
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    check_cancelled(cancel_event)
    return rc, "\n".join(tail_lines)


def make_mirror_download_config(log_label: str) -> DownloadConfig:
    """构造生物数据库下载器的标准并发配置。"""
    return DownloadConfig(log_label=log_label)
