# -*- coding: utf-8 -*-
"""软件更新模块 (git_updater) 真实仓库场景回归测试。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backend.utils import git_updater  # noqa: E402


def _run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["git", "-c", f"safe.directory={cwd}", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr or res.stdout}")
    return res


def _init_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    _run_git(tmp_path, "init", "--bare", "--initial-branch=master", str(remote))

    seed = tmp_path / "seed"
    _run_git(tmp_path, "clone", str(remote), str(seed))
    _run_git(seed, "config", "user.name", "Tester")
    _run_git(seed, "config", "user.email", "tester@example.com")
    (seed / "app.txt").write_text("base line\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "init base")
    _run_git(seed, "push", "-u", "origin", "master")

    local = tmp_path / "local"
    _run_git(tmp_path, "clone", str(remote), str(local))
    _run_git(local, "config", "user.name", "Tester")
    _run_git(local, "config", "user.email", "tester@example.com")
    return seed, local


def test_pull_with_only_untracked_files_does_not_pop_old_stash(tmp_path: Path) -> None:
    seed, local = _init_remote_and_clone(tmp_path)

    # 先制造一条历史旧 stash，后续仅保留未追踪文件
    (local / "app.txt").write_text("old stashed edit\n", encoding="utf-8")
    _run_git(local, "stash", "push", "-m", "historical-stash")
    (local / "untracked_note.txt").write_text("keep me untracked\n", encoding="utf-8")

    # 远端推进一个新提交（修改同一个 app.txt，如果误 pop 旧 stash 会直接冲突）
    (seed / "app.txt").write_text("upstream new line\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "upstream update")
    _run_git(seed, "push", "origin", "master")

    res = git_updater.pull_remote_update(project_root=local, auto_stash=True)
    assert res["success"] is True, res["logs"]
    assert res["has_conflicts"] is False
    assert (local / "app.txt").read_text(encoding="utf-8") == "upstream new line\n"
    assert (local / "untracked_note.txt").read_text(encoding="utf-8") == "keep me untracked\n"

    # 历史旧 stash 应仍完整留在 stash 栈内
    stash_list = _run_git(local, "stash", "list").stdout
    assert "historical-stash" in stash_list


def test_stash_pop_conflict_resets_clean_and_preserves_stash(tmp_path: Path) -> None:
    seed, local = _init_remote_and_clone(tmp_path)

    # 本地未提交修改与远端新提交修改同一行，必然在 stash pop 时发生冲突
    (local / "app.txt").write_text("local conflict edit\n", encoding="utf-8")
    (seed / "app.txt").write_text("remote conflict edit\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "remote conflict commit")
    _run_git(seed, "push", "origin", "master")

    res = git_updater.pull_remote_update(project_root=local, auto_stash=True)
    assert res["success"] is True, res["logs"]
    assert res["has_conflicts"] is False
    assert git_updater._get_unmerged_files(local) == []
    assert (local / "app.txt").read_text(encoding="utf-8") == "remote conflict edit\n"

    # 冲突的本地修改仍保存在 stash@{0}，仓库不再卡死在 unmerged 状态
    stash_list = _run_git(local, "stash", "list").stdout
    assert "auto-stash-before-update" in stash_list

    # 后续再次拉取应保持正常可用
    (seed / "app.txt").write_text("remote follow-up commit\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "follow-up")
    _run_git(seed, "push", "origin", "master")
    res2 = git_updater.pull_remote_update(project_root=local, auto_stash=True)
    assert res2["success"] is True, res2["logs"]


def test_preexisting_unmerged_conflict_detection_and_backup_recovery(tmp_path: Path) -> None:
    seed, local = _init_remote_and_clone(tmp_path)

    # 构造本地分支提交与远端分支冲突，并执行 merge 制造真实 unmerged files 现场
    (local / "app.txt").write_text("local diverged\n", encoding="utf-8")
    _run_git(local, "add", "app.txt")
    _run_git(local, "commit", "-m", "local diverged")

    (seed / "app.txt").write_text("remote diverged\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "remote diverged")
    _run_git(seed, "push", "origin", "master")

    _run_git(local, "fetch", "origin", "master")
    merge_res = _run_git(local, "merge", "origin/master", check=False)
    assert merge_res.returncode != 0
    assert git_updater._get_unmerged_files(local) == ["app.txt"]

    info = git_updater.get_git_info(local)
    assert info["has_conflicts"] is True
    assert info["conflict_files"] == ["app.txt"]
    assert info["in_progress_op"] == "merge"

    # 未开启 resolve_conflicts 时明确拦截并提示冲突文件
    blocked = git_updater.pull_remote_update(project_root=local, auto_stash=True, resolve_conflicts=False)
    assert blocked["success"] is False
    assert blocked["has_conflicts"] is True
    assert blocked["conflict_files"] == ["app.txt"]

    # 重置到远端可拉取前先将本地重设到 base，再人为制造纯 unmerged 索引后验证一键备份清理并拉取最新
    # 此处先在 merge 冲突态下直接调用 resolve_conflicts=True：
    # merge --abort 会回到 "local diverged"，然后 pull --rebase 会再遇同一本地提交与远端冲突并自动中止 rebase；
    # 若先把本地重置回 base 后只留 unmerged 条目（模拟远程 e73e7b2 的 unmerged index 现场），验证完整恢复：
    _run_git(local, "merge", "--abort")
    _run_git(local, "reset", "--hard", "HEAD~1")
    (local / "app.txt").write_text("local stash edit\n", encoding="utf-8")
    _run_git(local, "stash", "push", "-m", "simulate-pop-conflict")
    _run_git(local, "pull", "--rebase", "origin", "master")
    pop_res = _run_git(local, "stash", "pop", check=False)
    assert pop_res.returncode != 0
    assert git_updater._get_unmerged_files(local) == ["app.txt"]

    # 推进远端到下一个版本，确认 resolve_conflicts=True 能备份冲突内容、清理索引并顺利拉取更新
    (seed / "app.txt").write_text("remote latest v2\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "remote latest v2")
    _run_git(seed, "push", "origin", "master")

    recovered = git_updater.pull_remote_update(project_root=local, auto_stash=True, resolve_conflicts=True)
    assert recovered["success"] is True, recovered["logs"]
    assert recovered["has_conflicts"] is False
    assert (local / "app.txt").read_text(encoding="utf-8") == "remote latest v2\n"
    backup_dir = Path(recovered["backup_dir"])
    assert backup_dir.is_dir()
    assert (backup_dir / "app.txt").is_file()
    assert "<<<<<<" in (backup_dir / "app.txt").read_text(encoding="utf-8")


def test_rebase_conflict_aborts_cleanly(tmp_path: Path) -> None:
    seed, local = _init_remote_and_clone(tmp_path)

    (local / "app.txt").write_text("local unpushed change\n", encoding="utf-8")
    _run_git(local, "add", "app.txt")
    _run_git(local, "commit", "-m", "local unpushed")

    (seed / "app.txt").write_text("remote incompatible change\n", encoding="utf-8")
    _run_git(seed, "add", "app.txt")
    _run_git(seed, "commit", "-m", "remote incompatible")
    _run_git(seed, "push", "origin", "master")

    res = git_updater.pull_remote_update(project_root=local, auto_stash=True)
    assert res["success"] is False
    assert git_updater._detect_in_progress_op(local) is None
    assert git_updater._get_unmerged_files(local) == []
