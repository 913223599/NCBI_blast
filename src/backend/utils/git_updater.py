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
import json
import shutil
import subprocess
import logging
import time
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

def _resolve_git_dir(project_root: Path) -> Optional[Path]:
    """解析当前仓库的 .git 目录路径（兼容相对路径返回）。"""
    try:
        res = run_git_cmd(["rev-parse", "--git-dir"], cwd=project_root, timeout=5)
        if res.returncode != 0 or not res.stdout.strip():
            return None
        raw = Path(res.stdout.strip())
        return raw if raw.is_absolute() else (project_root / raw).resolve()
    except Exception:
        return None


def _detect_in_progress_op(project_root: Path) -> Optional[str]:
    """检测仓库当前是否处于未完成 rebase / merge / cherry-pick 状态。"""
    git_dir = _resolve_git_dir(project_root)
    if git_dir is None or not git_dir.exists():
        return None
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    return None


def _get_unmerged_files(project_root: Path) -> List[str]:
    """获取当前索引中所有未合并冲突文件路径列表（按字典序去重）。"""
    try:
        res = run_git_cmd(["diff", "--name-only", "--diff-filter=U"], cwd=project_root, timeout=10)
        if res.returncode != 0 or not res.stdout.strip():
            return []
        return sorted({line.strip() for line in res.stdout.splitlines() if line.strip()})
    except Exception:
        return []


def _get_stash_top_ref(project_root: Path) -> str:
    """返回 refs/stash 顶部提交哈希；若无 stash 返回空字符串。"""
    try:
        res = run_git_cmd(["rev-parse", "-q", "--verify", "refs/stash"], cwd=project_root, timeout=5)
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


def _abort_in_progress_op(project_root: Path, logs: List[str]) -> None:
    """安全中止正在进行的 rebase / merge / cherry-pick 状态。"""
    op = _detect_in_progress_op(project_root)
    if not op:
        return
    cmd_map = {
        "rebase": ["rebase", "--abort"],
        "merge": ["merge", "--abort"],
        "cherry-pick": ["cherry-pick", "--abort"],
    }
    abort_args = cmd_map.get(op)
    if not abort_args:
        return
    logs.append(f"正在中止未完成的 Git {op} 状态 (git {' '.join(abort_args)})...")
    res = run_git_cmd(abort_args, cwd=project_root, timeout=15)
    if res.returncode == 0:
        logs.append(f"已中止未完成的 {op} 状态。")
    else:
        err_txt = (res.stderr or res.stdout or "").strip()
        logs.append(f"中止 {op} 返回告警: {err_txt}")


def _backup_and_reset_conflicts(
    project_root: Path,
    conflict_files: List[str],
    logs: List[str],
) -> Optional[Path]:
    """将冲突文件按相对路径原样备份到 results/git_update_backups/ 后清理未合并索引。"""
    backup_dir: Optional[Path] = None
    existing_targets: List[Path] = []
    for rel in conflict_files:
        cand = (project_root / rel).resolve()
        try:
            cand.relative_to(project_root.resolve())
        except ValueError:
            continue
        if cand.is_file():
            existing_targets.append(cand)

    if existing_targets:
        backup_dir = project_root / "results" / "git_update_backups" / time.strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        for src_file in existing_targets:
            rel_path = src_file.relative_to(project_root.resolve())
            dst_file = backup_dir / rel_path
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
        logs.append(f"已将 {len(existing_targets)} 个冲突文件备份至: {backup_dir}")

    _abort_in_progress_op(project_root, logs)

    logs.append("正在重置未合并的索引条目 (git reset --merge)...")
    reset_res = run_git_cmd(["reset", "--merge"], cwd=project_root, timeout=15)
    if reset_res.returncode != 0:
        err_txt = (reset_res.stderr or reset_res.stdout or "").strip()
        logs.append(f"git reset --merge 返回告警: {err_txt}")

    remaining = _get_unmerged_files(project_root)
    if remaining:
        logs.append(f"检测到仍有 {len(remaining)} 个索引未解除合并，正在强制恢复为 HEAD 状态...")
        run_git_cmd(["reset", "HEAD", "--"] + remaining, cwd=project_root, timeout=15)
        run_git_cmd(["checkout", "-f", "HEAD", "--"] + remaining, cwd=project_root, timeout=15)

    return backup_dir


def get_git_info(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """获取本地 Git 仓库版本与分支元数据"""
    if project_root is None:
        project_root = get_project_root()
        
    from ...utils.app_metadata import get_app_version

    result: Dict[str, Any] = {
        "is_git_repo": False,
        "branch": "master",
        "commit_hash": "",
        "commit_full": "",
        "commit_message": "",
        "commit_date": "",
        "remote_url": "",
        "app_version": get_app_version(),
        "has_uncommitted_changes": False,
        "has_conflicts": False,
        "conflict_files": [],
        "in_progress_op": None,
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

        # 6. 未提交更改与冲突检测
        status_res = run_git_cmd(["status", "--porcelain"], cwd=project_root, timeout=5)
        if status_res.returncode == 0:
            result["has_uncommitted_changes"] = bool(status_res.stdout.strip())

        conflict_files = _get_unmerged_files(project_root)
        in_progress_op = _detect_in_progress_op(project_root)
        result["conflict_files"] = conflict_files
        result["in_progress_op"] = in_progress_op
        result["has_conflicts"] = bool(conflict_files or in_progress_op)

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

def pull_remote_update(
    project_root: Optional[Path] = None,
    auto_stash: bool = True,
    resolve_conflicts: bool = False,
    timeout: int = 60,
) -> Dict[str, Any]:
    """拉取 GitHub 远端最新代码并合并 (git pull --rebase)，支持冲突检测、备份清理与安全回退。"""
    if project_root is None:
        project_root = get_project_root()

    info = get_git_info(project_root)
    if not info.get("is_git_repo"):
        return {
            "success": False,
            "message": info.get("error", "非有效 Git 仓库"),
            "logs": [],
            "need_restart": False,
            "has_conflicts": False,
            "conflict_files": [],
        }

    branch = info.get("branch") or "master"
    logs: List[str] = []
    stashed = False
    backup_dir: Optional[Path] = None

    try:
        # 0. 前置未合并冲突 / 半途 rebase 检测与自愈清理
        if info.get("has_conflicts"):
            conflict_files: List[str] = list(info.get("conflict_files") or [])
            in_prog = info.get("in_progress_op")
            if not resolve_conflicts:
                logs.append(
                    f"[警告] 检测到仓库存在未解决的冲突状态 (in_progress={in_prog or 'none'}, 冲突文件={len(conflict_files)} 个):"
                )
                for cf in conflict_files:
                    logs.append(f"  - {cf}")
                logs.append("请点击“备份冲突文件并清理后更新”，将先备份上述冲突文件并重置索引再拉取更新。")
                return {
                    "success": False,
                    "message": "检测到未合并冲突文件，请先清理冲突后再更新",
                    "logs": logs,
                    "need_restart": False,
                    "has_conflicts": True,
                    "conflict_files": conflict_files,
                }

            logs.append("[步骤 0/4] 检测到未合并冲突，正在执行备份并安全清理冲突现场...")
            backup_dir = _backup_and_reset_conflicts(project_root, conflict_files, logs)
            info = get_git_info(project_root)
            if info.get("has_conflicts"):
                rem = list(info.get("conflict_files") or [])
                logs.append("[错误] 自动清理冲突后仍有未合并文件，请检查仓库文件权限或磁盘占用。")
                return {
                    "success": False,
                    "message": "冲突清理未完全成功，请检查文件占用后重试",
                    "logs": logs,
                    "need_restart": False,
                    "has_conflicts": True,
                    "conflict_files": rem,
                    "backup_dir": str(backup_dir) if backup_dir else None,
                }
            logs.append("冲突现场清理完成，继续执行更新流程。")

        # 1. 检测本地工作区是否包含未提交改动
        if info.get("has_uncommitted_changes"):
            if auto_stash:
                logs.append("[步骤 1/4] 检测到工作区有本地修改，正在自动暂存 (git stash)...")
                stash_before = _get_stash_top_ref(project_root)
                stash_res = run_git_cmd(["stash", "push", "-m", "auto-stash-before-update"], cwd=project_root, timeout=15)
                stash_out = ((stash_res.stdout or "") + "\n" + (stash_res.stderr or "")).strip()
                if stash_res.returncode != 0:
                    logs.append("[错误] 自动暂存失败，已终止更新以防止破坏工作区: " + stash_out)
                    rem_conflicts = _get_unmerged_files(project_root)
                    return {
                        "success": False,
                        "message": "自动暂存本地修改失败，请先处理工作区状态或使用冲突自愈",
                        "logs": logs,
                        "need_restart": False,
                        "has_conflicts": bool(rem_conflicts or _detect_in_progress_op(project_root)),
                        "conflict_files": rem_conflicts,
                    }
                stash_after = _get_stash_top_ref(project_root)
                if "No local changes to save" in stash_out or stash_after == stash_before:
                    stashed = False
                    logs.append("工作区仅含未追踪文件，无需新建 stash。")
                else:
                    stashed = True
                    logs.append("已成功暂存本地工作区修改。")
            else:
                return {
                    "success": False,
                    "message": "本地工作区存在未提交修改，请先提交或开启暂存保护后再更新",
                    "logs": ["本地工作区存在修改，操作已取消。"],
                    "need_restart": False,
                    "has_conflicts": False,
                    "conflict_files": [],
                }
        else:
            logs.append("[步骤 1/4] 本地工作区整洁，准备拉取远程更新...")

        # 2. 执行拉取更新 (git pull --rebase origin <branch>)
        logs.append(f"[步骤 2/4] 正在从 origin/{branch} 拉取更新代码...")
        pull_res = run_git_cmd(["pull", "--rebase", "origin", branch], cwd=project_root, timeout=timeout)

        pull_output = pull_res.stdout.strip()
        if pull_res.stderr.strip():
            pull_output = (pull_output + "\n" + pull_res.stderr.strip()).strip()
        if pull_output:
            logs.append(pull_output)

        if pull_res.returncode != 0:
            logs.append("[错误] git pull --rebase 发生冲突或网络错误，正在清理未完成变基状态...")
            _abort_in_progress_op(project_root, logs)
            if _get_unmerged_files(project_root):
                run_git_cmd(["reset", "--merge"], cwd=project_root, timeout=15)

            if stashed:
                logs.append("正在尝试恢复已暂存的修改 (git stash pop)...")
                pop_err_res = run_git_cmd(["stash", "pop"], cwd=project_root, timeout=15)
                if pop_err_res.returncode != 0:
                    if _get_unmerged_files(project_root):
                        run_git_cmd(["reset", "--merge"], cwd=project_root, timeout=15)
                    logs.append("恢复暂存时存在冲突，已还原工作区并完整保留暂存 (git stash list 可查看)。")
            return {
                "success": False,
                "message": "拉取远程代码失败，已自动回退半途变基状态，请检查网络或本地提交冲突",
                "logs": logs,
                "need_restart": False,
                "has_conflicts": False,
                "conflict_files": [],
            }

        # 3. 如果之前暂存过，尝试恢复暂存；若 pop 冲突则自动回退至干净更新态以免卡死仓库
        if stashed:
            logs.append("[步骤 3/4] 正在恢复本地暂存修改 (git stash pop)...")
            pop_res = run_git_cmd(["stash", "pop"], cwd=project_root, timeout=15)
            if pop_res.returncode == 0:
                logs.append("本地暂存修改恢复成功。")
            else:
                pop_err = ((pop_res.stdout or "") + "\n" + (pop_res.stderr or "")).strip()
                pop_conflicts = _get_unmerged_files(project_root)
                if pop_conflicts:
                    logs.append("[告警] 本地暂存修改与新版代码发生冲突，已自动重置冲突以免仓库卡死，原修改仍保留在 git stash 中:")
                    for cf in pop_conflicts:
                        logs.append(f"  - {cf}")
                    run_git_cmd(["reset", "--merge"], cwd=project_root, timeout=15)
                else:
                    logs.append("恢复暂存时发生告警，请在 Git 中手动检查 stash: " + pop_err)
        else:
            logs.append("[步骤 3/4] 验证代码一致性完成。")

        # 4. 获取最新提交哈希
        latest_info = get_git_info(project_root)
        logs.append(f"[步骤 4/4] 更新完成！当前版本已推进至 Commit: {latest_info.get('commit_hash')}")

        resp: Dict[str, Any] = {
            "success": True,
            "message": "代码拉取成功，请重启应用以使新功能生效！",
            "logs": logs,
            "latest_commit": latest_info.get("commit_hash"),
            "need_restart": True,
            "has_conflicts": False,
            "conflict_files": [],
        }
        if backup_dir is not None:
            resp["backup_dir"] = str(backup_dir)
        return resp

    except subprocess.TimeoutExpired:
        logs.append(f"[错误] 拉取更新超时 ({timeout}秒)，请检查网络连接")
        return {
            "success": False,
            "message": "拉取更新操作超时",
            "logs": logs,
            "need_restart": False,
            "has_conflicts": False,
            "conflict_files": [],
        }
    except Exception as exc:
        logger.error("拉取更新异常: %s", exc)
        logs.append(f"[异常] {exc}")
        return {
            "success": False,
            "message": str(exc),
            "logs": logs,
            "need_restart": False,
            "has_conflicts": False,
            "conflict_files": [],
        }


def _parse_porcelain_status(porcelain_text: str) -> List[Dict[str, str]]:
    """逐行解析 git status --porcelain=v1 输出，保留首位空格避免误判工作区修改。"""
    entries: List[Dict[str, str]] = []
    for raw_line in (porcelain_text or "").splitlines():
        if len(raw_line) < 4:
            continue
        xy = raw_line[:2]
        x, y = xy[0], xy[1]
        path = raw_line[3:].strip()
        if not path:
            continue

        if "U" in xy or xy in ("AA", "DD"):
            category = "unmerged"
        elif xy == "??":
            category = "untracked"
        elif x != " " and y == " ":
            category = "staged"
        else:
            category = "modified"

        entries.append(
            {
                "code": xy,
                "index_status": x,
                "worktree_status": y,
                "path": path,
                "category": category,
            }
        )
    return entries


def get_git_workspace_details(
    project_root: Optional[Path] = None,
    max_items: int = 200,
) -> Dict[str, Any]:
    """只读返回当前 Git 工作区未提交改动、未合并冲突、diff 摘要与 stash 列表明细。"""
    if project_root is None:
        project_root = get_project_root()

    info = get_git_info(project_root)
    counts: Dict[str, int] = {
        "unmerged": 0,
        "staged": 0,
        "modified": 0,
        "untracked": 0,
        "total": 0,
    }
    if not info.get("is_git_repo"):
        return {
            **info,
            "counts": counts,
            "entries": [],
            "truncated": False,
            "diff_stat": "",
            "staged_diff_stat": "",
            "stash_list": [],
        }

    status_res = run_git_cmd(["status", "--porcelain=v1", "-uall"], cwd=project_root, timeout=15)
    all_entries = _parse_porcelain_status(status_res.stdout if status_res.returncode == 0 else "")
    for item in all_entries:
        cat = item["category"]
        if cat in counts:
            counts[cat] += 1
    counts["total"] = len(all_entries)

    safe_limit = max(1, int(max_items))
    truncated = len(all_entries) > safe_limit
    entries = all_entries[:safe_limit]

    diff_stat_res = run_git_cmd(["diff", "--stat"], cwd=project_root, timeout=15)
    staged_stat_res = run_git_cmd(["diff", "--cached", "--stat"], cwd=project_root, timeout=15)
    stash_res = run_git_cmd(["stash", "list", "-n", "10"], cwd=project_root, timeout=10)

    stash_list = (
        [line.strip() for line in stash_res.stdout.splitlines() if line.strip()]
        if stash_res.returncode == 0 and stash_res.stdout
        else []
    )

    return {
        "is_git_repo": True,
        "branch": info.get("branch", ""),
        "commit_hash": info.get("commit_hash", ""),
        "commit_message": info.get("commit_message", ""),
        "commit_date": info.get("commit_date", ""),
        "has_uncommitted_changes": info.get("has_uncommitted_changes", False),
        "has_conflicts": info.get("has_conflicts", False),
        "in_progress_op": info.get("in_progress_op"),
        "conflict_files": info.get("conflict_files", []),
        "counts": counts,
        "entries": entries,
        "truncated": truncated,
        "diff_stat": diff_stat_res.stdout.strip() if diff_stat_res.returncode == 0 else "",
        "staged_diff_stat": staged_stat_res.stdout.strip() if staged_stat_res.returncode == 0 else "",
        "stash_list": stash_list,
    }
