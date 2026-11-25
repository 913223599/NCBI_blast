# -*- coding: utf-8 -*-
"""受控白名单远程执行服务端（Bearer Token 鉴权 + 来源 IP 白名单 + 动作白名单）。"""
from __future__ import annotations

import hmac
import http.server
import json
import socketserver
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Set

from .actions import execute_whitelisted_action
from .models import ALLOWED_ACTIONS

_MAX_BODY_BYTES = 64 * 1024
_MIN_TOKEN_LEN = 16


class ThreadingAgentHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _validate_token_strength(token: str) -> str:
    clean = (token or "").strip()
    if len(clean) < _MIN_TOKEN_LEN:
        raise ValueError(f"远程执行器 Token 长度至少需 {_MIN_TOKEN_LEN} 个字符")
    return clean


def create_agent_server(
    host: str,
    port: int,
    token: str,
    project_root: Path,
    allowed_ips: Optional[Sequence[str]] = None,
) -> ThreadingAgentHTTPServer:
    """构建带强鉴权与审计日志的受控远程执行服务端。"""
    valid_token = _validate_token_strength(token)
    root = project_root.resolve()
    ip_whitelist: Optional[Set[str]] = (
        {ip.strip() for ip in allowed_ips if ip and ip.strip()} if allowed_ips else None
    )

    class ControlledAgentHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _audit(self, status_code: int, action: str, detail: str = "") -> None:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            client_ip = self.client_address[0]
            sys.stdout.write(
                f"[REMOTE-AGENT {ts}] ip={client_ip} status={status_code} action={action} {detail}\n"
            )
            sys.stdout.flush()

        def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _is_ip_allowed(self) -> bool:
            if ip_whitelist is None:
                return True
            return self.client_address[0] in ip_whitelist

        def _is_authorized(self) -> bool:
            auth = self.headers.get("Authorization") or ""
            prefix = "Bearer "
            if not auth.startswith(prefix):
                return False
            presented = auth[len(prefix) :].strip()
            return hmac.compare_digest(presented.encode("utf-8"), valid_token.encode("utf-8"))

        def do_GET(self) -> None:
            if not self._is_ip_allowed():
                self._audit(403, "GET", f"path={self.path} denied_ip")
                self._send_json(403, {"ok": False, "error": "来源 IP 不在允许白名单内"})
                return

            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send_json(200, {"status": "ok", "actions": list(ALLOWED_ACTIONS)})
                return
            self._send_json(404, {"ok": False, "error": "Not Found"})

        def do_POST(self) -> None:
            if not self._is_ip_allowed():
                self._audit(403, "POST", "denied_ip")
                self._send_json(403, {"ok": False, "error": "来源 IP 不在允许白名单内"})
                return

            if not self._is_authorized():
                self._audit(401, "POST", "unauthorized")
                self._send_json(401, {"ok": False, "error": "无效或缺失 Bearer Token"})
                return

            path = self.path.split("?", 1)[0]
            if path != "/action":
                self._send_json(404, {"ok": False, "error": "Not Found"})
                return

            try:
                content_len = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "非法 Content-Length"})
                return

            if content_len <= 0 or content_len > _MAX_BODY_BYTES:
                self._send_json(400, {"ok": False, "error": f"请求体大小超出限制 (1..{_MAX_BODY_BYTES})"})
                return

            raw_body = self.rfile.read(content_len)
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": f"JSON 解析失败: {exc}"})
                return

            if not isinstance(payload, dict):
                self._send_json(400, {"ok": False, "error": "请求体必须是 JSON 对象"})
                return

            action = str(payload.get("action") or "").strip()
            params = payload.get("params")
            if params is not None and not isinstance(params, dict):
                self._send_json(400, {"ok": False, "error": "params 必须是 JSON 对象"})
                return

            if action not in ALLOWED_ACTIONS:
                self._audit(403, action or "<empty>", "denied_action")
                self._send_json(403, {"ok": False, "error": f"不允许的非白名单动作: {action}"})
                return

            t0 = time.perf_counter()
            try:
                data = execute_whitelisted_action(action=action, project_root=root, params=params)
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                self._audit(200, action, f"elapsed_ms={elapsed_ms}")
                self._send_json(
                    200,
                    {"ok": True, "action": action, "elapsed_ms": elapsed_ms, "data": data},
                )
            except PermissionError as exc:
                self._audit(403, action, f"perm_err={exc}")
                self._send_json(403, {"ok": False, "action": action, "error": str(exc)})
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                self._audit(500, action, f"err={exc}")
                self._send_json(
                    500,
                    {"ok": False, "action": action, "elapsed_ms": elapsed_ms, "error": str(exc)},
                )

    return ThreadingAgentHTTPServer((host, port), ControlledAgentHandler)
