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
import json
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("api_server.updater")

# 项目内置便携版 Git 的候选相对路径（tools 目录下的便携部署）
PROJECT_GIT_CANDIDATES = (
    Path("tools") / "git" / "cmd" / "git.exe",
    Path("tools") / "git" / "bin" / "git.exe",
    Path("tools") / "MinGit" / "cmd" / "git.exe",
    Path("tools") / "portable-git" / "cmd" / "git.exe",
)

# 系统常见安装位置：覆盖 winget / 官方安装包 / 32 位安装
SYSTEM_GIT_CANDIDATES = (
    Path(r"C:\Program Files\Git\cmd\git.exe"),
    Path(r"C:\Program Files\Git\bin\git.exe"),
    Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
)

# 定位结果缓存，避免每次请求都做磁盘探测
_git_executable_cache: Optional[str] = None
_git_probe_done: bool = False


def get_project_root() -> Path:
    """获取项目根目录绝对路径"""
    # 依据当前文件路径推算: src/backend/utils/git_updater.py -> 项目根目录
    return Path(__file__).resolve().parent.parent.parent.parent


def reset_git_cache() -> None:
    """清除 git 定位缓存（安装 Git 后无需重启应用即可重新探测）"""
    global _git_executable_cache, _git_probe_done
    _git_executable_cache = None
    _git_probe_done = False


def _from_config() -> Optional[str]:
    """读取 config.json 中用户显式指定的 git 路径 (git_bin_path)"""
    raw = _config_value("git_bin_path")
    if not raw:
        return None
    target = Path(raw)
    if target.is_file():
        return str(target)
    if target.is_dir():
        candidate = target / ("git.exe" if os.name == "nt" else "git")
        if candidate.is_file():
            return str(candidate)
    logger.warning("config.json 中 git_bin_path 无效: %s", raw)
    return None


def _config_value(key: str) -> str:
    """读取 config.json 中指定的字符串配置项"""
    try:
        config_file = get_project_root() / "config.json"
        if not config_file.exists():
            return ""
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return str(data.get(key) or "").strip()
    except Exception as exc:
        logger.warning("读取配置 %s 失败: %s", key, exc)
        return ""


def find_git_executable(force: bool = False) -> Optional[str]:
    """
    定位 git 可执行文件，优先级：
    1. config.json 的 git_bin_path（用户显式指定）
    2. 项目内置便携版 (tools/git/...)
    3. 系统 PATH
    4. Git for Windows 常见安装目录（含 winget 默认位置）

    说明：安装 Git 后当前进程的 PATH 不会自动刷新，因此 4 能保证"刚装完就能用"。
    """
    global _git_executable_cache, _git_probe_done
    if _git_probe_done and not force:
        return _git_executable_cache

    candidates: List[Path] = []

    configured = _from_config()
    if configured:
        candidates.append(Path(configured))

    project_root = get_project_root()
    candidates.extend(project_root / rel for rel in PROJECT_GIT_CANDIDATES)
    candidates.extend(SYSTEM_GIT_CANDIDATES)

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Git" / "cmd" / "git.exe")

    which_path = shutil.which("git")
    if which_path:
        candidates.append(Path(which_path))

    resolved: Optional[str] = None
    for candidate in candidates:
        try:
            if candidate.is_file():
                resolved = str(candidate)
                break
        except OSError:
            continue

    _git_executable_cache = resolved
    # 仅在成功定位时缓存；未找到时保留待探测状态，
    # 这样用户安装 Git 后点击“检查更新”即可立即生效，无需重启应用。
    _git_probe_done = resolved is not None
    if resolved:
        logger.info("已定位 Git 可执行文件: %s", resolved)
    else:
        logger.warning("未能定位 Git 可执行文件，请安装 Git for Windows 或配置 git_bin_path")
    return resolved


def is_git_available() -> bool:
    """检测系统中 git 命令是否可用"""
    return find_git_executable() is not None


def _git_base_args(project_root: Path) -> List[str]:
    """构造通用 git 参数：规避 dubious ownership、中文路径转义与代理缺失问题"""
    args = [
        "-c", f"safe.directory={project_root}",
        "-c", "core.quotepath=false",
    ]
    # config.json 可配置 git_proxy（例如 http://127.0.0.1:7897），
    # 用于在 GitHub 直连受限的环境下走本地代理完成 fetch / pull
    proxy = _config_value("git_proxy")
    if proxy:
        args += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    return args


def run_git_cmd(args: List[str], cwd: Optional[Path] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """安全执行 git 命令，强制使用 utf-8 解码与无阻塞超时设置"""
    if cwd is None:
        cwd = get_project_root()

    git_exe = find_git_executable()
    if not git_exe:
        raise FileNotFoundError("未检测到 Git 可执行文件")

    cmd = [git_exe] + _git_base_args(Path(cwd)) + args

    # 禁用交互式凭据提示，避免 fetch/pull 在无人值守时挂起
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")

    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
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
        result["error"] = (
            "系统中未检测到 Git 命令行工具。"
            "请安装 Git for Windows (https://git-scm.com/download/win)，"
            "也可将其解压到项目的 tools\\git 目录，或在 config.json 中配置 git_bin_path。"
        )
        return result

    result["git_exe"] = find_git_executable() or ""

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

_NETWORK_ERROR_MARKERS = (
    "could not connect",
    "failed to connect",
    "could not resolve",
    "connection was reset",
    "connection timed out",
    "operation timed out",
    "network is unreachable",
    "unable to access",
    "proxy",
)


def _network_error_hint(err_msg: str) -> str:
    """把 git 的网络类错误包装成面向用户的可执行提示"""
    text = (err_msg or "").strip()
    lowered = text.lower()
    if any(marker in lowered for marker in _NETWORK_ERROR_MARKERS):
        return (
            f"无法连接 GitHub 远程仓库: {text}\n"
            "处理建议: 1) 开启本机代理后，在 config.json 中设置 "
            "\"git_proxy\": \"http://127.0.0.1:7897\"；"
            "2) 或改用可访问 GitHub 的网络环境后重新点击“检查最新版本”。"
        )
    return f"同步远程仓库失败: {text}"


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
                "error": _network_error_hint(err_msg),
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
            "error": (
                f"连接 GitHub 远端超时 ({timeout}秒)，请检查网络状况。"
                "若本机代理已开启，可在 config.json 中设置 "
                "\"git_proxy\": \"http://127.0.0.1:7897\" 后重试。"
            ),
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
