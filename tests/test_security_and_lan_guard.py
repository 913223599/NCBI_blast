# -*- coding: utf-8 -*-
"""
阶段 0/1 安全红线与局域网访问控制守护测试
覆盖：
1. FastAPI /api/health 探活端点
2. FastAPI CORS 安全配置（禁止 * 与 allow_credentials=True 并发）
3. LAN 访问隔离中间件（lan_share=False 时拦截非本机 IP）
4. lan_share.py 与 HelpManager 路径穿越防护
5. Electron main.js 安全与生命周期结构不变量
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_health_endpoint_ok():
    from src.backend.api_server import app

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("status") == "ok"


def test_cors_does_not_allow_untrusted_origin_with_credentials():
    from src.backend.api_server import app

    client = TestClient(app)
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = resp.headers.get("access-control-allow-origin")
    allow_creds = resp.headers.get("access-control-allow-credentials")
    assert allow_origin != "https://evil.example.com"
    assert not (allow_origin == "*" and allow_creds == "true")


def test_cors_allows_local_vite_origin():
    from src.backend.api_server import app

    client = TestClient(app)
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_lan_guard_blocks_non_loopback_when_disabled():
    from src.backend.api_server import is_client_ip_allowed

    assert is_client_ip_allowed("127.0.0.1", lan_share_enabled=False) is True
    assert is_client_ip_allowed("::1", lan_share_enabled=False) is True
    assert is_client_ip_allowed("localhost", lan_share_enabled=False) is True
    assert is_client_ip_allowed("192.168.1.55", lan_share_enabled=False) is False
    assert is_client_ip_allowed("10.0.0.8", lan_share_enabled=False) is False
    assert is_client_ip_allowed("192.168.1.55", lan_share_enabled=True) is True


def test_lan_guard_middleware_enforces_403_for_remote_ip():
    from src.backend.api_server import app

    with patch("src.backend.api_server._is_lan_share_enabled", return_value=False), patch(
        "src.backend.api_server._extract_client_host", return_value="192.168.1.88"
    ):
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 403


def test_lan_share_path_traversal_blocked(tmp_path: Path):
    from src.backend.lan_share import resolve_safe_dist_file

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    secret_file = tmp_path / "config.json"
    secret_file.write_text('{"api_key": "secret"}', encoding="utf-8")
    index_file = dist_dir / "index.html"
    index_file.write_text("<html>ok</html>", encoding="utf-8")

    assert resolve_safe_dist_file(dist_dir, "index.html") == index_file.resolve()
    assert resolve_safe_dist_file(dist_dir, "../config.json") is None
    assert resolve_safe_dist_file(dist_dir, "..\\config.json") is None
    assert resolve_safe_dist_file(dist_dir, "/etc/passwd") is None


def test_help_manager_blocks_path_traversal():
    from src.utils.help_manager import get_help_manager

    mgr = get_help_manager()
    content = mgr.get_help_content("../../config")
    assert "api_key" not in content
    assert "非法" in content or "错误" in content


def test_electron_main_security_and_lifecycle_invariants():
    main_js = (PROJECT_ROOT / "electron-shell" / "main.js").read_text(encoding="utf-8")

    # Context7 Electron 35 安全清单核心项
    assert "sandbox: true" in main_js
    assert "contextIsolation: true" in main_js
    assert "nodeIntegration: false" in main_js
    assert "validateSender" in main_js
    assert "Content-Security-Policy" in main_js
    assert "/api/health" in main_js

    # IPC 异步化与协议白名单
    assert "fs.promises.readFile" in main_js
    assert "fs.promises.writeFile" in main_js
    assert "isAllowedExternalUrl" in main_js

    # 生命周期退出不变量与禁止无差别终止全部 WSL 分发版
    assert "isQuitting" in main_js
    assert "wsl --list --running --quiet" not in main_js


def test_core_citations_endpoint_returns_structured_references():
    from fastapi.testclient import TestClient
    from src.backend.api_server import app

    client = TestClient(app)
    r_all = client.get("/api/core/citations")
    assert r_all.status_code == 200
    body_all = r_all.json()
    assert body_all["count"] >= 10
    assert len(body_all["tools"]) == body_all["count"]
    assert all({"id", "name", "module", "authors", "year", "title", "journal", "doi"} <= set(t.keys()) for t in body_all["tools"])

    r_studio = client.get("/api/core/citations", params={"module": "figure_studio"})
    assert r_studio.status_code == 200
    body_studio = r_studio.json()
    assert body_studio["count"] >= 2
    assert all(t["module"] == "figure_studio" for t in body_studio["tools"])


def test_core_version_system_metrics_and_citations_loader():
    import json
    from fastapi.testclient import TestClient
    from src.backend.api_server import app
    from src.utils.citations_loader import format_bibtex_entries, format_methods_citations_text

    version_meta = json.loads((PROJECT_ROOT / "version.json").read_text(encoding="utf-8"))
    client = TestClient(app)

    r_ver = client.get("/api/core/version")
    assert r_ver.status_code == 200
    ver_body = r_ver.json()
    assert ver_body["name"] == version_meta["name"]
    assert ver_body["version"] == version_meta["version"]

    r_metrics = client.get("/api/core/system_metrics")
    assert r_metrics.status_code == 200
    m = r_metrics.json()
    assert isinstance(m.get("cpu_cores"), int) and m["cpu_cores"] >= 1
    assert isinstance(m.get("safe_cpu_budget"), int) and 1 <= m["safe_cpu_budget"] <= m["cpu_cores"]
    assert isinstance(m.get("gpu"), dict) and "available" in m["gpu"]

    methods_txt = format_methods_citations_text(tool_ids=["phold", "lovis4u"])
    assert "10.1093/nar/gkaf1448" in methods_txt
    assert "10.1093/nargab/lqaf009" in methods_txt
    bib_txt = format_bibtex_entries(tool_ids=["checkv"])
    assert "@article{checkv_2021," in bib_txt
