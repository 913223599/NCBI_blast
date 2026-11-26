# -*- coding: utf-8 -*-
"""
静态安全与可靠性守卫单元测试：
1. src.core.http_guard: 协议白名单校验（拦截 file:// / ftp:// / 空主机）与安全下载；
2. src.core.async_tasks: 托管异步任务强引用持有、完成后自动回收与异常日志记录。
"""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from typing import Set
from unittest.mock import AsyncMock, patch

import pytest

from src.core.async_tasks import spawn_tracked_task
from src.core.http_guard import build_safe_request, safe_urlopen, validate_http_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_validate_http_url_allows_http_https_and_blocks_unsafe_schemes() -> None:
    assert validate_http_url("https://example.com/data.cif") == "https://example.com/data.cif"
    assert validate_http_url("http://127.0.0.1:8765/api/health") == "http://127.0.0.1:8765/api/health"

    for bad in (
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz",
        "javascript:alert(1)",
        "https://",
        "",
    ):
        with pytest.raises(ValueError, match="不允许的 URL 协议"):
            validate_http_url(bad)


def test_build_safe_request_and_safe_urlopen_reject_file_scheme(tmp_path: Path) -> None:
    sample = tmp_path / "secret.txt"
    sample.write_text("top-secret", encoding="utf-8")
    file_url = sample.as_uri()

    with pytest.raises(ValueError):
        build_safe_request(file_url)
    with pytest.raises(ValueError):
        safe_urlopen(file_url)


def test_spawn_tracked_task_retains_and_cleans_up_reference(caplog: pytest.LogCaptureFixture) -> None:
    async def _run() -> None:
        registry: Set[asyncio.Task[object]] = set()
        ran = False

        async def _ok_job() -> None:
            nonlocal ran
            await asyncio.sleep(0.01)
            ran = True

        task = spawn_tracked_task(_ok_job(), registry, label="ok_job")
        assert task in registry
        await task
        await asyncio.sleep(0)
        assert ran is True
        assert task not in registry

        async def _boom_job() -> None:
            raise RuntimeError("simulated bg failure")

        with caplog.at_level(logging.WARNING, logger="core.async_tasks"):
            bad_task = spawn_tracked_task(_boom_job(), registry, label="boom_job")
            with pytest.raises(RuntimeError, match="simulated bg failure"):
                await bad_task
            await asyncio.sleep(0)
        assert bad_task not in registry
        assert "boom_job" in caplog.text

    asyncio.run(_run())


def test_no_create_subprocess_shell_or_is_shell_true_in_src() -> None:
    """严禁在 src/ 中使用 create_subprocess_shell 或显式传 is_shell=True。"""
    src_root = PROJECT_ROOT / "src"
    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "create_subprocess_shell":
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno} create_subprocess_shell")
                elif isinstance(func, ast.Name) and func.id == "create_subprocess_shell":
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno} create_subprocess_shell")
                for kw in node.keywords:
                    if kw.arg == "is_shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        violations.append(f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno} is_shell=True")
    assert not violations, "检测到不安全的 shell 执行调用:\n" + "\n".join(violations)


def test_build_wsl_script_argv_validation() -> None:
    """build_wsl_script_argv 应返回参数列表并拒绝非法脚本名。"""
    from src.backend.utils.bio_db_manager import build_wsl_script_argv

    with patch("src.assembly.env.wsl_manager.WSLManager.get_best_distro", return_value="Ubuntu"):
        argv = build_wsl_script_argv("setup_pharokka.sh")
        assert isinstance(argv, list)
        assert argv[:5] == ["wsl", "-d", "Ubuntu", "-u", "root"]
        assert argv[5] == "bash"
        assert argv[6].endswith("/scripts/setup_pharokka.sh")

        for bad in ("../evil.sh", "setup.sh; rm -rf /", "has space.sh", "a/b.sh", ""):
            with pytest.raises(ValueError, match="非法脚本名称"):
                build_wsl_script_argv(bad)


def test_command_runner_uses_create_subprocess_exec() -> None:
    """CommandRunner 应初始化 is_aborted=False 且始终走 create_subprocess_exec。"""
    from src.assembly.engine.runner import CommandRunner

    runner = CommandRunner("TestStep", is_wsl=False)
    assert runner.is_aborted is False

    fake_proc = AsyncMock()
    fake_proc.stdout = AsyncMock()
    fake_proc.stdout.read = AsyncMock(return_value=b"")
    fake_proc.stderr = AsyncMock()
    fake_proc.stderr.read = AsyncMock(return_value=b"")
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.returncode = 0

    async def _run() -> int:
        with patch("asyncio.create_subprocess_exec", return_value=fake_proc) as mock_exec:
            rc = await runner.run_command(["echo", "ok"])
            mock_exec.assert_called_once()
            return rc

    assert asyncio.run(_run()) == 0


def test_no_legacy_s110_logger_in_src() -> None:
    """全仓 src/ 不应残留机械替换生成的 _s110_logger 占位变量。"""
    src_root = PROJECT_ROOT / "src"
    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8")
        if "_s110_logger" in text:
            violations.append(str(py_file.relative_to(PROJECT_ROOT)))
    assert not violations, "检测到遗留 _s110_logger:\n" + "\n".join(violations)


def test_phage_finder_protein_gate_call_uses_threads_kwarg() -> None:
    """确保 phage_finder.manager 调用 evaluate_regions_with_protein_gate 的关键字参数与签名严格匹配。"""
    import inspect

    from src.phage_discovery.inference.protein_gate import evaluate_regions_with_protein_gate

    sig_params = set(inspect.signature(evaluate_regions_with_protein_gate).parameters.keys())
    src_path = PROJECT_ROOT / "src" / "analysis" / "phage_finder" / "manager.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    matched_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            )
            if fn_name == "evaluate_regions_with_protein_gate":
                matched_calls += 1
                bad_kwargs = [kw.arg for kw in node.keywords if kw.arg and kw.arg not in sig_params]
                assert not bad_kwargs, f"检测到非法关键字参数 {bad_kwargs} (允许: {sorted(sig_params)})"
    assert matched_calls >= 1


def test_diversity_engine_blastn_uses_existing_tool_config_method(tmp_path: Path) -> None:
    """确保 DiversityEngine._get_blastn_path 通过存在的 ToolConfig.resolve_bio_tool 解析路径。"""
    from src.backend.services.diversity_engine import DiversityEngine
    from src.workbench.models.tool_config import ToolConfig

    fake_blastn = tmp_path / "blastn.exe"
    fake_blastn.write_text("stub", encoding="utf-8")

    engine = DiversityEngine.__new__(DiversityEngine)
    with patch.object(ToolConfig, "resolve_bio_tool", return_value=fake_blastn) as mock_resolve:
        resolved = engine._get_blastn_path()
        mock_resolve.assert_called_once_with("blastn")
        assert resolved == fake_blastn
