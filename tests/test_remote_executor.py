# -*- coding: utf-8 -*-
"""受控白名单远程执行器与 Git 工作区明细诊断接口单元测试。"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Tuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.backend.routes import settings as settings_route  # noqa: E402
from src.backend.utils import git_updater  # noqa: E402
from src.ops.remote_executor import (  # noqa: E402
    RemoteOpsClient,
    RemoteTarget,
    create_agent_server,
)


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


def _init_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "--initial-branch=master")
    _run_git(repo, "config", "user.name", "Tester")
    _run_git(repo, "config", "user.email", "tester@example.com")
    (repo / "staged.txt").write_text("v1\n", encoding="utf-8")
    (repo / "modified.txt").write_text("v1\n", encoding="utf-8")
    (repo / "conflict.txt").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _http_call(
    method: str,
    url: str,
    headers: dict | None = None,
    payload: dict | None = None,
) -> Tuple[int, dict]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def test_git_workspace_details_parses_all_categories(tmp_path: Path) -> None:
    repo = _init_sample_repo(tmp_path)

    # 先制造一条 stash 并保留
    (repo / "modified.txt").write_text("stashed line\n", encoding="utf-8")
    _run_git(repo, "stash", "push", "-m", "saved-work")

    # 1. 先构造分支分歧并触发 unmerged (via branch merge conflict)
    _run_git(repo, "checkout", "-b", "side")
    (repo / "conflict.txt").write_text("side line\n", encoding="utf-8")
    _run_git(repo, "commit", "-am", "side change")
    _run_git(repo, "checkout", "master")
    (repo / "conflict.txt").write_text("master line\n", encoding="utf-8")
    _run_git(repo, "commit", "-am", "master change")
    merge_res = _run_git(repo, "merge", "side", check=False)
    assert merge_res.returncode != 0

    # 2. 在保留冲突的同时构造 staged / modified / untracked
    (repo / "staged.txt").write_text("v2 staged\n", encoding="utf-8")
    _run_git(repo, "add", "staged.txt")
    (repo / "modified.txt").write_text("v2 unstaged\n", encoding="utf-8")
    (repo / "new_untracked.txt").write_text("hello\n", encoding="utf-8")

    details = git_updater.get_git_workspace_details(project_root=repo)
    assert details["is_git_repo"] is True
    assert details["has_conflicts"] is True
    assert details["in_progress_op"] == "merge"
    assert details["conflict_files"] == ["conflict.txt"]
    assert details["counts"]["unmerged"] == 1
    assert details["counts"]["staged"] == 1
    assert details["counts"]["modified"] == 1
    assert details["counts"]["untracked"] == 1
    assert details["counts"]["total"] == 4
    cats = {e["path"]: e["category"] for e in details["entries"]}
    assert cats == {
        "conflict.txt": "unmerged",
        "staged.txt": "staged",
        "modified.txt": "modified",
        "new_untracked.txt": "untracked",
    }
    assert any("saved-work" in s for s in details["stash_list"])


def test_settings_workspace_details_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_sample_repo(tmp_path)
    (repo / "modified.txt").write_text("changed\n", encoding="utf-8")

    orig_fn = git_updater.get_git_workspace_details
    monkeypatch.setattr(git_updater, "get_git_workspace_details", lambda max_items=200: orig_fn(repo, max_items=max_items))

    app = FastAPI()
    app.include_router(settings_route.router)
    client = TestClient(app)
    res = client.get("/api/settings/update/workspace-details")
    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["modified"] == 1
    assert body["entries"][0]["path"] == "modified.txt"


def test_agent_rejects_weak_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_agent_server("127.0.0.1", 0, "short-token", tmp_path)


def test_agent_auth_ip_whitelist_and_action_whitelist(tmp_path: Path) -> None:
    repo = _init_sample_repo(tmp_path)
    (repo / "modified.txt").write_text("remote dirty edit\n", encoding="utf-8")
    token = "Strong_Test_Token_1234567890"

    server = create_agent_server("127.0.0.1", 0, token, repo, allowed_ips=["127.0.0.1"])
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # 1. 无 Token -> 401
        c1, _ = _http_call("POST", f"{base}/action", payload={"action": "git_status"})
        assert c1 == 401

        # 2. 错误 Token -> 401
        c2, _ = _http_call(
            "POST",
            f"{base}/action",
            headers={"Authorization": "Bearer wrong_token_000000"},
            payload={"action": "git_status"},
        )
        assert c2 == 401

        # 3. 非白名单动作 (含任意 shell 试探) -> 403
        c3, b3 = _http_call(
            "POST",
            f"{base}/action",
            headers={"Authorization": f"Bearer {token}"},
            payload={"action": "raw_shell", "params": {"cmd": "whoami"}},
        )
        assert c3 == 403
        assert "白名单" in b3["error"]

        # 4. 合法动作 -> 200
        c4, b4 = _http_call(
            "POST",
            f"{base}/action",
            headers={"Authorization": f"Bearer {token}"},
            payload={"action": "git_diff_summary"},
        )
        assert c4 == 200
        assert b4["ok"] is True
        assert b4["data"]["counts"]["modified"] == 1
        assert "modified.txt" in b4["data"]["diff_stat"]
    finally:
        server.shutdown()
        server.server_close()

    # 验证来源 IP 白名单拒绝
    blocked_server = create_agent_server("127.0.0.1", 0, token, repo, allowed_ips=["10.99.99.99"])
    bport = blocked_server.server_address[1]
    bthread = threading.Thread(target=blocked_server.serve_forever, daemon=True)
    bthread.start()
    try:
        c5, _ = _http_call(
            "POST",
            f"http://127.0.0.1:{bport}/action",
            headers={"Authorization": f"Bearer {token}"},
            payload={"action": "git_status"},
        )
        assert c5 == 403
    finally:
        blocked_server.shutdown()
        blocked_server.server_close()


def test_client_agent_mode_and_legacy_api_fallback(tmp_path: Path) -> None:
    repo = _init_sample_repo(tmp_path)
    (repo / "new_file.txt").write_text("x\n", encoding="utf-8")
    token = "Strong_Client_Token_9876543210"

    server = create_agent_server("127.0.0.1", 0, token, repo, allowed_ips=["127.0.0.1"])
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RemoteOpsClient(RemoteTarget(mode="agent", host="127.0.0.1", port=port, token=token))
        res = client.run_action("git_status")
        assert res.ok is True
        assert res.data["counts"]["untracked"] == 1
        assert res.data["entries"][0]["path"] == "new_file.txt"
    finally:
        server.shutdown()
        server.server_close()

    # 模拟旧版后端 (无 workspace-details 路由返回 404，有 /api/settings/update/status)
    import http.server
    import socketserver

    class LegacyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path == "/api/settings/update/status":
                body = json.dumps(
                    {"is_git_repo": True, "branch": "master", "commit_hash": "e73e7b2", "has_uncommitted_changes": True}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    class MockServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    legacy_srv = MockServer(("127.0.0.1", 0), LegacyHandler)
    lport = legacy_srv.server_address[1]
    lthread = threading.Thread(target=legacy_srv.serve_forever, daemon=True)
    lthread.start()
    try:
        api_client = RemoteOpsClient(RemoteTarget(mode="api", host="127.0.0.1", port=lport))
        api_res = api_client.run_action("git_status")
        assert api_res.ok is True
        assert api_res.data["legacy_server"] is True
        assert api_res.data["commit_hash"] == "e73e7b2"
    finally:
        legacy_srv.shutdown()
        legacy_srv.server_close()
