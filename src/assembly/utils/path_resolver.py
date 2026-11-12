# -*- coding: utf-8 -*-
"""
组装模块路径动态解析工具 (Path Resolver)
职责：
1. 动态解析 NGCS 引擎根目录与 CLI 入口，消除硬编码盘符依赖；
2. 动态分配纯 ASCII 且无空格的安全隔离工作目录，防止跨机部署无特定盘符时报错；
3. 兼容历史任务目录检索。
"""

import os
import tempfile
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _is_ascii_no_space(p: Path) -> bool:
    s = str(p)
    return all(ord(c) < 128 for c in s) and (" " not in s)


def resolve_ngcs_root(custom_path: Optional[str] = None) -> Path:
    """动态解析 NGCS 引擎根目录"""
    candidates: List[Path] = []

    if custom_path:
        cp = Path(custom_path)
        candidates.append(cp if cp.is_dir() else cp.parent.parent)

    env_root = os.environ.get("NGCS_ROOT")
    if env_root:
        candidates.append(Path(env_root))

    env_cli = os.environ.get("NGCS_CLI_PATH")
    if env_cli:
        candidates.append(Path(env_cli).resolve().parent.parent)

    # 相对路径优先：项目内 vendor/NGCS、同级目录 ../NGCS、当前盘符根目录 /NGCS
    candidates.extend([
        PROJECT_ROOT / "vendor" / "NGCS",
        PROJECT_ROOT.parent / "NGCS",
    ])
    if PROJECT_ROOT.drive:
        candidates.append(Path(f"{PROJECT_ROOT.drive}/NGCS"))

    # 兼容常见盘符根目录下的 NGCS
    for drv in ("E:", "D:", "F:", "C:"):
        cand = Path(f"{drv}/NGCS")
        if cand not in candidates:
            candidates.append(cand)

    for cand in candidates:
        try:
            if (cand / "ngcs" / "cli.py").exists():
                return cand.resolve()
        except OSError:
            continue

    return (PROJECT_ROOT.parent / "NGCS").resolve()


def resolve_ngcs_cli(custom_cli_path: Optional[str] = None) -> Path:
    """动态解析 NGCS CLI 脚本路径"""
    if custom_cli_path and Path(custom_cli_path).is_file():
        return Path(custom_cli_path).resolve()

    env_cli = os.environ.get("NGCS_CLI_PATH")
    if env_cli and Path(env_cli).is_file():
        return Path(env_cli).resolve()

    root = resolve_ngcs_root(custom_cli_path)
    return root / "ngcs" / "cli.py"


def resolve_safe_work_dir(task_id: str, create: bool = True) -> Path:
    """
    获取针对中文路径与空格的 ASCII 安全隔离工作目录。
    按优先级选择可用盘符，避免在不存在特定盘符的主机上触发 FileNotFoundError。
    """
    candidates: List[Path] = []

    env_work = os.environ.get("NGCS_WORK_DIR")
    if env_work:
        candidates.append(Path(env_work) / "tasks" / task_id)

    # 若项目自身路径已是纯 ASCII 且无空格，可直接用项目 scratch 目录
    scratch_dir = PROJECT_ROOT / "scratch" / "ngcs_work" / "tasks" / task_id
    if _is_ascii_no_space(scratch_dir):
        candidates.append(scratch_dir)

    # 若历史工作目录所在盘符存在，优先复用以保持缓存连续性
    for drv in (PROJECT_ROOT.drive, "E:", "D:", "F:", "C:"):
        if not drv:
            continue
        drive_root = Path(f"{drv}/")
        if drive_root.exists():
            candidates.append(drive_root / "NGCS_Work" / "tasks" / task_id)

    # 兜底：系统临时目录
    candidates.append(Path(tempfile.gettempdir()) / "NGCS_Work" / "tasks" / task_id)

    # 1. 若已有某候选目录存在，直接复用
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue

    # 2. 选择第一个可创建的候选目录
    for cand in candidates:
        try:
            if create:
                cand.mkdir(parents=True, exist_ok=True)
            return cand
        except OSError:
            continue

    fallback = scratch_dir
    if create:
        fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_candidate_safe_work_dirs(task_id: str) -> List[Path]:
    """返回指定任务可能存在的所有安全工作目录列表（用于结果与指标回溯）"""
    dirs: List[Path] = []
    primary = resolve_safe_work_dir(task_id, create=False)
    dirs.append(primary)

    for drv in (PROJECT_ROOT.drive, "E:", "D:", "F:", "C:"):
        if not drv:
            continue
        p = Path(f"{drv}/NGCS_Work/tasks/{task_id}")
        if p not in dirs:
            dirs.append(p)

    scratch_p = PROJECT_ROOT / "scratch" / "ngcs_work" / "tasks" / task_id
    if scratch_p not in dirs:
        dirs.append(scratch_p)

    return dirs
