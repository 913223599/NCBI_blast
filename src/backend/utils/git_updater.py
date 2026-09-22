# -*- coding: utf-8 -*-
"""
git_updater.py - 软件更新服务模块

单一职责：
1. 封装 Git 本地与远程版本检测；
2. 执行远程分支比对 (git fetch) 与差异 Commit 日志提取；
3. 执行安全代码拉取 (git pull / rebase)，支持本地未提交修改暂存保护；
4. 保证全流程跨平台执行与超时防挂起。
"""

import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("api_server.updater")

def get_project_root() -> Path:
    """获取项目根目录绝对路径"""
    # 依据当前文件路径推算: src/backend/utils/git_updater.py -> 项目根目录
    return Path(__file__).resolve().parent.parent.parent.parent

def is_git_available() -> bool:
    """检测系统中 git 命令是否可用"""
    return shutil.which("git") is not None

def run_git_cmd(args: List[str], cwd: Optional[Path] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """安全执行 git 命令，强制使用 utf-8 解码与无阻塞超时设置"""
    if cwd is None:
        cwd = get_project_root()
    
    cmd = ["git"] + args
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout
    )

def get_git_info(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """获取本地 Git 仓库版本与分支元数据"""
    if project_root is None:
        project_root = get_project_root()
        
    result: Dict[str, Any] = {
        "is_git_repo": False,
        "branch": "master",
        "commit_hash": "",
        "commit_full": "",
        "commit_message": "",
        "commit_date": "",
        "remote_url": "",
        "app_version": "2.1.0",
        "has_uncommitted_changes": False
    }

    if not is_git_available():
        result["error"] = "系统中未检测到 Git 命令行工具"
        return result

    try:
        # 1. 验证是否为 git 仓库
        check_repo = run_git_cmd(["rev-parse", "--is-inside-work-tree"], cwd=project_root, timeout=5)
        if check_repo.returncode != 0 or check_repo.stdout.strip() != "true":
            result["error"] = "当前项目目录不是有效的 Git 仓库"
            return result

        result["is_git_repo"] = True

        # 2. 当前分支
        branch_res = run_git_cmd(["branch", "--show-current"], cwd=project_root, timeout=5)
        if branch_res.returncode == 0 and branch_res.stdout.strip():
            result["branch"] = branch_res.stdout.strip()

        # 3. Commit 短哈希与完整哈希
        hash_res = run_git_cmd(["rev-parse", "--short", "HEAD"], cwd=project_root, timeout=5)
        if hash_res.returncode == 0:
            result["commit_hash"] = hash_res.stdout.strip()

        full_hash_res = run_git_cmd(["rev-parse", "HEAD"], cwd=project_root, timeout=5)
        if full_hash_res.returncode == 0:
            result["commit_full"] = full_hash_res.stdout.strip()

        # 4. 最近一次提交说明与时间
        log_res = run_git_cmd(["log", "-1", "--pretty=format:%s%x09%cd", "--date=iso"], cwd=project_root, timeout=5)
        if log_res.returncode == 0 and log_res.stdout.strip():
            parts = log_res.stdout.strip().split("\t")
            result["commit_message"] = parts[0] if len(parts) > 0 else ""
            result["commit_date"] = parts[1] if len(parts) > 1 else ""

        # 5. Remote URL
        remote_res = run_git_cmd(["remote", "get-url", "origin"], cwd=project_root, timeout=5)
        if remote_res.returncode == 0:
            result["remote_url"] = remote_res.stdout.strip()

        # 6. 未提交更改检测
        status_res = run_git_cmd(["status", "--porcelain"], cwd=project_root, timeout=5)
        if status_res.returncode == 0:
            result["has_uncommitted_changes"] = bool(status_res.stdout.strip())

    except Exception as exc:
        logger.error("获取 Git 信息异常: %s", exc)
        result["error"] = str(exc)

    return result

def check_remote_update(project_root: Optional[Path] = None, timeout: int = 35) -> Dict[str, Any]:
    """从 GitHub 远端拉取元数据并比对是否有新提交 (git fetch)"""
    if project_root is None:
        project_root = get_project_root()

    info = get_git_info(project_root)
    if not info.get("is_git_repo"):
        return {
            "has_update": False,
            "error": info.get("error", "非有效 Git 仓库"),
            "current_info": info
        }

    branch = info.get("branch") or "master"

    try:
        # 执行 git fetch origin <branch>
        logger.info("正在执行 git fetch origin %s (超时 %ds)...", branch, timeout)
        fetch_res = run_git_cmd(["fetch", "origin", branch], cwd=project_root, timeout=timeout)
        if fetch_res.returncode != 0:
            err_msg = fetch_res.stderr.strip() or fetch_res.stdout.strip() or "连接 GitHub 失败，请检查网络连接"
            logger.warning("git fetch 失败: %s", err_msg)
            return {
                "has_update": False,
                "error": f"同步远程仓库失败: {err_msg}",
                "current_info": info
            }

        # 检查本地分支落后远程分支的 Commit 数
        rev_res = run_git_cmd(["rev-list", "--count", f"HEAD..origin/{branch}"], cwd=project_root, timeout=10)
        behind_count = 0
        if rev_res.returncode == 0:
            try:
                behind_count = int(rev_res.stdout.strip())
            except ValueError:
                behind_count = 0

        # 获取待更新的 Commit 记录明细
        commits: List[Dict[str, str]] = []
        if behind_count > 0:
            log_fmt = "%h%x09%s%x09%an%x09%cd"
            commits_res = run_git_cmd(
                ["log", f"HEAD..origin/{branch}", f"--pretty=format:{log_fmt}", "--date=short", "-n", "30"],
                cwd=project_root,
                timeout=10
            )
            if commits_res.returncode == 0 and commits_res.stdout.strip():
                for line in commits_res.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    cols = line.split("\t")
                    commits.append({
                        "hash": cols[0] if len(cols) > 0 else "",
                        "message": cols[1] if len(cols) > 1 else "",
                        "author": cols[2] if len(cols) > 2 else "",
                        "date": cols[3] if len(cols) > 3 else ""
                    })

        # 获取远程最新 Commit Hash
        remote_hash_res = run_git_cmd(["rev-parse", "--short", f"origin/{branch}"], cwd=project_root, timeout=5)
        remote_head = remote_hash_res.stdout.strip() if remote_hash_res.returncode == 0 else ""

        return {
            "has_update": behind_count > 0,
            "behind_count": behind_count,
            "remote_head": remote_head,
            "commits": commits,
            "current_info": info,
            "error": None
        }

    except subprocess.TimeoutExpired:
        logger.error("git fetch 超时 (%ds)", timeout)
        return {
            "has_update": False,
            "error": f"连接 GitHub 远端超时 ({timeout}秒)，请检查代理设置或网络状况",
            "current_info": info
        }
    except Exception as exc:
        logger.error("检查更新异常: %s", exc)
        return {
            "has_update": False,
            "error": str(exc),
            "current_info": info
        }

def pull_remote_update(project_root: Optional[Path] = None, auto_stash: bool = True, timeout: int = 60) -> Dict[str, Any]:
    """拉取 GitHub 远端最新代码并合并 (git pull --rebase)"""
    if project_root is None:
        project_root = get_project_root()

    info = get_git_info(project_root)
    if not info.get("is_git_repo"):
        return {
            "success": False,
            "message": info.get("error", "非有效 Git 仓库"),
            "logs": [],
            "need_restart": False
        }

    branch = info.get("branch") or "master"
    logs: List[str] = []
    stashed = False

    try:
        # 1. 检测本地工作区是否包含未提交改动
        if info.get("has_uncommitted_changes"):
            if auto_stash:
                logs.append("[步骤 1/4] 检测到工作区有本地修改，正在自动暂存 (git stash)...")
                stash_res = run_git_cmd(["stash", "push", "-m", "auto-stash-before-update"], cwd=project_root, timeout=10)
                if stash_res.returncode == 0:
                    stashed = True
                    logs.append("已成功暂存本地工作区修改。")
                else:
                    logs.append("暂存修改失败，将尝试直接合并: " + stash_res.stderr.strip())
            else:
                return {
                    "success": False,
                    "message": "本地工作区存在未提交修改，请先提交或开启暂存保护后再更新",
                    "logs": ["本地工作区存在修改，操作已取消。"],
                    "need_restart": False
                }
        else:
            logs.append("[步骤 1/4] 本地工作区整洁，准备拉取远程更新...")

        # 2. 执行拉取更新 (git pull --rebase origin <branch>)
        logs.append(f"[步骤 2/4] 正在从 origin/{branch} 拉取更新代码...")
        pull_res = run_git_cmd(["pull", "--rebase", "origin", branch], cwd=project_root, timeout=timeout)
        
        pull_output = pull_res.stdout.strip()
        if pull_res.stderr.strip():
            pull_output += "\n" + pull_res.stderr.strip()
        logs.append(pull_output)

        if pull_res.returncode != 0:
            logs.append("[错误] git pull 发生冲突或网络错误。")
            if stashed:
                logs.append("正在尝试恢复已暂存的修改 (git stash pop)...")
                run_git_cmd(["stash", "pop"], cwd=project_root, timeout=10)
            return {
                "success": False,
                "message": "拉取远程代码失败，请检查网络或冲突详情",
                "logs": logs,
                "need_restart": False
            }

        # 3. 如果之前暂存过，尝试恢复暂存
        if stashed:
            logs.append("[步骤 3/4] 正在恢复本地暂存修改 (git stash pop)...")
            pop_res = run_git_cmd(["stash", "pop"], cwd=project_root, timeout=10)
            if pop_res.returncode == 0:
                logs.append("本地暂存修改恢复成功。")
            else:
                logs.append("恢复暂存时发生告警，请在 Git 中手动检查 stash: " + pop_res.stderr.strip())
        else:
            logs.append("[步骤 3/4] 验证代码一致性完成。")

        # 4. 获取最新提交哈希
        latest_info = get_git_info(project_root)
        logs.append(f"[步骤 4/4] 更新完成！当前版本已推进至 Commit: {latest_info.get('commit_hash')}")

        return {
            "success": True,
            "message": "代码拉取成功，请重启应用以使新功能生效！",
            "logs": logs,
            "latest_commit": latest_info.get("commit_hash"),
            "need_restart": True
        }

    except subprocess.TimeoutExpired:
        logs.append(f"[错误] 拉取更新超时 ({timeout}秒)，请检查网络连接")
        return {
            "success": False,
            "message": "拉取更新操作超时",
            "logs": logs,
            "need_restart": False
        }
    except Exception as exc:
        logger.error("拉取更新异常: %s", exc)
        logs.append(f"[异常] {exc}")
        return {
            "success": False,
            "message": str(exc),
            "logs": logs,
            "need_restart": False
        }
