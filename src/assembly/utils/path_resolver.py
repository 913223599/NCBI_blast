# -*- coding: utf-8 -*-
"""
组装模块路径动态解析工具 (Path Resolver)
职责：
1. 动态解析 NGCS 引擎根目录与 CLI 入口，消除硬编码盘符依赖；
2. 动态分配纯 ASCII 且无空格的安全隔离工作目录，防止跨机部署无特定盘符时报错；
3. 兼容历史任务目录检索。
"""

import ctypes
import json
import os
import string
import tempfile
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _is_ascii_no_space(p: Path) -> bool:
    s = str(p)
    return all(ord(c) < 128 for c in s) and (" " not in s)


def _list_windows_drives_win32() -> List[str]:
    """在 Python <3.12（缺少 os.listdrives）环境下通过 Win32 API 枚举本地逻辑盘符。"""
    if os.name != "nt":
        return []
    try:
        bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
    except Exception:
        return []
    drives: List[str] = []
    for idx, letter in enumerate(string.ascii_uppercase):
        if (bitmask >> idx) & 1:
            drives.append(f"{letter}:")
    return drives


def _list_system_drives() -> List[str]:
    """动态枚举系统当前挂载的根卷/盘符，避免硬编码盘符字面量"""
    drives: List[str] = []
    if PROJECT_ROOT.drive:
        drives.append(PROJECT_ROOT.drive.rstrip("\\/"))
    if hasattr(os, "listdrives"):
        raw_drives = os.listdrives()
    else:
        raw_drives = _list_windows_drives_win32()
    for d in raw_drives:
        clean = d.rstrip("\\/")
        if clean and clean not in drives:
            drives.append(clean)
    return drives


def _load_ngcs_config_entries(config_path: Optional[Path] = None) -> tuple[List[Path], List[Path]]:
    """从 config.json 读取可选的 NGCS 根目录与 CLI 入口路径配置。"""
    target = config_path or (PROJECT_ROOT / "config.json")
    if not target.is_file():
        return [], []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    if not isinstance(data, dict):
        return [], []

    tool_paths = data.get("tool_paths") if isinstance(data.get("tool_paths"), dict) else {}
    raw_roots = [
        data.get("ngcs_root"),
        tool_paths.get("ngcs_root"),
    ]
    raw_clis = [
        data.get("ngcs_cli_path"),
        tool_paths.get("ngcs_cli_path"),
    ]

    root_candidates: List[Path] = []
    cli_candidates: List[Path] = []
    for raw in raw_clis:
        val = str(raw or "").strip()
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        cli_candidates.append(p)
        root_candidates.append(p.parent.parent)

    for raw in raw_roots:
        val = str(raw or "").strip()
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        root_candidates.append(p)

    return root_candidates, cli_candidates


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

    cfg_roots, _ = _load_ngcs_config_entries()
    candidates.extend(cfg_roots)

    # 相对路径优先：项目内 vendor/NGCS、tools/NGCS、NGCS 及同级目录 ../NGCS
    candidates.extend([
        PROJECT_ROOT / "vendor" / "NGCS",
        PROJECT_ROOT / "tools" / "NGCS",
        PROJECT_ROOT / "NGCS",
        PROJECT_ROOT.parent / "NGCS",
    ])

    # 动态探测系统已挂载盘符根目录下的 NGCS
    for drv in _list_system_drives():
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

    _, cfg_clis = _load_ngcs_config_entries()
    for cli_cand in cfg_clis:
        try:
            if cli_cand.is_file():
                return cli_cand.resolve()
        except OSError:
            continue

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

    # 动态枚举已挂载盘符下的工作目录以保持缓存连续性
    for drv in _list_system_drives():
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

    for drv in _list_system_drives():
        p = Path(f"{drv}/NGCS_Work/tasks/{task_id}")
        if p not in dirs:
            dirs.append(p)

    scratch_p = PROJECT_ROOT / "scratch" / "ngcs_work" / "tasks" / task_id
    if scratch_p not in dirs:
        dirs.append(scratch_p)

    return dirs
