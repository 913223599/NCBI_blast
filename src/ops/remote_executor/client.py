# -*- coding: utf-8 -*-
"""受控远程执行客户端（支持直连绕过代理调用 api / agent / ssh 三种模式）。"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .models import ALLOWED_ACTIONS, SSH_READONLY_ACTIONS, ActionResult, RemoteTarget


def _build_no_proxy_opener() -> urllib.request.OpenerDirector:
    """禁用系统/Clash 代理，确保 Radmin VPN 与内网 IP 直连。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(
    method: str,
    url: str,
    timeout: float,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> tuple[int, Dict[str, Any]]:
    opener = _build_no_proxy_opener()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        req_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    from ...core.http_guard import build_safe_request, safe_urlopen

    req = build_safe_request(url, data=data, method=method.upper(), headers=req_headers)
    try:
        with safe_urlopen(req, timeout=timeout, opener=opener) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw.strip() else {"detail": err.reason}
        except Exception:
            body = {"detail": raw or str(err.reason)}
        return err.code, body


class RemoteOpsClient:
    """统一调度受控白名单远程执行与 Git 工作区诊断。"""

    def __init__(self, target: RemoteTarget) -> None:
        self.target = target

    def run_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> ActionResult:
        if action not in ALLOWED_ACTIONS:
            return ActionResult(
                ok=False,
                action=action,
                host=self.target.host,
                elapsed_ms=0.0,
                error=f"不允许的非白名单动作: {action}",
            )

        t0 = time.perf_counter()
        mode = self.target.mode.lower().strip()
        try:
            if mode == "api":
                data, err = self._run_via_api(action)
            elif mode == "agent":
                data, err = self._run_via_agent(action, params or {})
            elif mode == "ssh":
                data, err = self._run_via_ssh(action)
            else:
                return ActionResult(
                    ok=False,
                    action=action,
                    host=self.target.host,
                    elapsed_ms=0.0,
                    error=f"不支持的模式: {self.target.mode}",
                )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return ActionResult(
                ok=(not err),
                action=action,
                host=self.target.host,
                elapsed_ms=elapsed_ms,
                data=data,
                error=err,
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return ActionResult(
                ok=False,
                action=action,
                host=self.target.host,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )

    def _run_via_api(self, action: str) -> tuple[Dict[str, Any], str]:
        base = f"http://{self.target.host}:{self.target.port}"
        if action == "service_health":
            code, body = _http_json("GET", f"{base}/api/health", timeout=self.target.timeout)
            if code == 200:
                return body, ""
            return body, f"HTTP {code}: {body.get('detail') or body.get('error') or ''}"

        if action == "git_status":
            code, body = _http_json(
                "GET",
                f"{base}/api/settings/update/workspace-details",
                timeout=self.target.timeout,
            )
            if code == 200:
                body["legacy_server"] = False
                return body, ""
            if code == 404:
                # 兼容尚未升级到新版 workspace-details 接口的旧后端，回退读取 update/status
                legacy_code, legacy_body = _http_json(
                    "GET",
                    f"{base}/api/settings/update/status",
                    timeout=self.target.timeout,
                )
                if legacy_code == 200:
                    legacy_body["legacy_server"] = True
                    legacy_body["notice"] = (
                        "远程 API 后端版本较旧，尚未包含 /api/settings/update/workspace-details；"
                        "仅返回简要状态，请在远程启动 remote_ops_agent.py 或拉取新版后重启以查看文件级未提交明细。"
                    )
                    return legacy_body, ""
                return legacy_body, f"HTTP {legacy_code}"
            return body, f"HTTP {code}: {body.get('detail') or ''}"

        return (
            {},
            f"api 模式仅支持只读端点 (git_status / service_health)；执行 {action} 请改用 --mode agent 或 --mode ssh",
        )

    def _run_via_agent(self, action: str, params: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
        if not self.target.token.strip():
            return {}, "agent 模式必须提供 Bearer Token (--token 或环境变量 REMOTE_OPS_TOKEN)"
        url = f"http://{self.target.host}:{self.target.port}/action"
        code, body = _http_json(
            "POST",
            url,
            timeout=self.target.timeout,
            headers={"Authorization": f"Bearer {self.target.token.strip()}"},
            payload={"action": action, "params": params},
        )
        if code == 200 and body.get("ok"):
            return dict(body.get("data") or {}), ""
        return body, str(body.get("error") or body.get("detail") or f"HTTP {code}")

    def _run_via_ssh(self, action: str) -> tuple[Dict[str, Any], str]:
        if action not in SSH_READONLY_ACTIONS:
            return {}, f"ssh 模式仅允许只读白名单动作: {', '.join(SSH_READONLY_ACTIONS)}"
        ssh_exe = shutil.which("ssh")
        if not ssh_exe:
            return {}, "本机未找到 ssh 可执行文件"
        if not self.target.remote_dir.strip():
            return {}, "ssh 模式必须指定 --remote-dir（远端项目工作目录路径）"

        dest = f"{self.target.user}@{self.target.host}" if self.target.user else self.target.host
        quoted_dir = shlex.quote(self.target.remote_dir)

        if action == "git_status":
            remote_cmd = (
                f"git -C {quoted_dir} status --porcelain=v1 && "
                f"echo ---STASH--- && git -C {quoted_dir} stash list -n 10"
            )
        elif action == "git_diff_summary":
            remote_cmd = (
                f"git -C {quoted_dir} diff --name-only --diff-filter=U && "
                f"echo ---STAT--- && git -C {quoted_dir} diff --stat"
            )
        else:
            remote_cmd = f"git -C {quoted_dir} rev-parse --short HEAD"

        cmd = [
            ssh_exe,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-p",
            str(self.target.port),
            dest,
            remote_cmd,
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.target.timeout,
        )
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip() or f"SSH exit {res.returncode}"
            return {"raw_stdout": res.stdout, "raw_stderr": res.stderr}, err
        return {"raw_stdout": res.stdout}, ""
