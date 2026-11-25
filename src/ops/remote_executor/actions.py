# -*- coding: utf-8 -*-
"""受控远程执行器白名单动作实现（禁止任意 shell 命令透传）。"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...backend.utils.git_updater import get_git_info, get_git_workspace_details, pull_remote_update
from .models import ALLOWED_ACTIONS

_MAX_CONFLICT_SNIPPETS = 5
_MAX_SNIPPET_LINES = 40
_MAX_SNIPPET_CHARS = 2000


def _collect_conflict_snippets(project_root: Path, conflict_files: List[str]) -> Dict[str, str]:
    """只读截取前几个冲突文件的头部片段，防止大文件撑爆响应。"""
    snippets: Dict[str, str] = {}
    root_resolved = project_root.resolve()
    for rel in conflict_files[:_MAX_CONFLICT_SNIPPETS]:
        target = (root_resolved / rel).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            continue
        if not target.is_file():
            continue
        try:
            lines: List[str] = []
            with target.open("r", encoding="utf-8", errors="replace") as fh:
                for idx, line in enumerate(fh):
                    if idx >= _MAX_SNIPPET_LINES:
                        break
                    lines.append(line.rstrip("\r\n"))
            joined = "\n".join(lines)
            if len(joined) > _MAX_SNIPPET_CHARS:
                joined = joined[:_MAX_SNIPPET_CHARS] + "\n... [truncated]"
            snippets[rel] = joined
        except OSError as exc:
            snippets[rel] = f"[读取失败: {exc}]"
    return snippets


def _probe_local_api_health(port: int = 8765) -> Dict[str, Any]:
    """绕过系统代理探活本机 FastAPI 后端。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with opener.open(url, timeout=3) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"reachable": True, "status_code": resp.status, "body": json.loads(raw)}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


def _run_phold_gpu_check(project_root: Path) -> Dict[str, Any]:
    """只读检查本机 WSL + Phold PyTorch CUDA kernel 就绪态。"""
    ps_script = (project_root / "scripts" / "fix_phold_gpu_wsl.ps1").resolve()
    if not ps_script.is_file():
        return {"ok": False, "error": f"未找到诊断脚本: {ps_script}"}

    pwsh_exe = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh_exe:
        return {"ok": False, "error": "未检测到 pwsh 或 powershell"}

    res = subprocess.run(
        [pwsh_exe, "-NoProfile", "-File", str(ps_script), "-CheckOnly"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return {
        "ok": res.returncode == 0,
        "exit_code": res.returncode,
        "output": ((res.stdout or "") + "\n" + (res.stderr or "")).strip()[-4000:],
    }


def execute_whitelisted_action(
    action: str,
    project_root: Path,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行预定义白名单运维/诊断动作；非白名单动作一律抛出 PermissionError。"""
    if action not in ALLOWED_ACTIONS:
        raise PermissionError(f"不允许执行非白名单动作: {action}")

    opts = params or {}
    root = project_root.resolve()

    if action == "git_status":
        max_items = int(opts.get("max_items", 200))
        return get_git_workspace_details(project_root=root, max_items=max(1, min(1000, max_items)))

    if action == "git_diff_summary":
        details = get_git_workspace_details(project_root=root, max_items=int(opts.get("max_items", 200)))
        snippets = _collect_conflict_snippets(root, list(details.get("conflict_files") or []))
        details["conflict_snippets"] = snippets
        return details

    if action == "git_recover_and_pull":
        auto_stash = bool(opts.get("auto_stash", True))
        resolve_conflicts = bool(opts.get("resolve_conflicts", True))
        return pull_remote_update(
            project_root=root,
            auto_stash=auto_stash,
            resolve_conflicts=resolve_conflicts,
            timeout=int(opts.get("timeout", 60)),
        )

    if action == "phold_gpu_check":
        return _run_phold_gpu_check(root)

    if action == "service_health":
        info = get_git_info(project_root=root)
        api_port = int(opts.get("api_port", 8765))
        return {
            "hostname": os.environ.get("COMPUTERNAME") or platform.node(),
            "python_version": sys.version.split()[0],
            "project_root": str(root),
            "branch": info.get("branch", ""),
            "commit_hash": info.get("commit_hash", ""),
            "has_uncommitted_changes": info.get("has_uncommitted_changes", False),
            "has_conflicts": info.get("has_conflicts", False),
            "local_api": _probe_local_api_health(port=api_port),
        }

    raise PermissionError(f"未实现的白名单动作: {action}")
