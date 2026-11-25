# -*- coding: utf-8 -*-
"""
阶段 2 硬件资源守卫与代码健壮性守护测试
覆盖：
1. 全局 src.utils.resource_guard 与 phylo 向后兼容导出
2. 全仓 src/ 零 E722 bare-except（禁止裸 except: 吞噬 KeyboardInterrupt/SystemExit）
"""
import ast
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_global_resource_guard_reserves_cores():
    from src.utils.resource_guard import get_safe_cpu_budget
    from src.phylo.runtime.resource_guard import get_safe_cpu_budget as phylo_budget

    assert get_safe_cpu_budget is phylo_budget

    with patch("src.utils.resource_guard.os.cpu_count", return_value=16):
        assert get_safe_cpu_budget(0) == 12
        assert get_safe_cpu_budget(16) == 14
        assert get_safe_cpu_budget(4) == 4

    with patch("src.utils.resource_guard.os.cpu_count", return_value=4):
        assert get_safe_cpu_budget(0) == 3
        assert get_safe_cpu_budget(4) == 2


def test_gpu_guard_managed_session_runs_cleanly():
    from src.utils.resource_guard import GpuGuard

    with GpuGuard.managed_session() as info:
        assert isinstance(info, dict)
        assert "available" in info


def test_no_bare_except_in_src():
    violations = []
    for p in (PROJECT_ROOT / "src").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(f"{p.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert not violations, "发现裸 except:（请使用 except Exception:）:\n" + "\n".join(violations)


def test_all_subprocess_run_have_explicit_timeout():
    violations = []
    for p in (PROJECT_ROOT / "src").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if "subprocess.run" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                ):
                    kw_names = {kw.arg for kw in node.keywords if kw.arg}
                    if "timeout" not in kw_names:
                        violations.append(f"{p.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert not violations, "发现未设置 timeout 的 subprocess.run 调用:\n" + "\n".join(violations)


def test_cpu_count_centralized_through_resource_guard():
    violations = []
    allowed = {PROJECT_ROOT / "src" / "utils" / "resource_guard.py"}
    for p in (PROJECT_ROOT / "src").rglob("*.py"):
        if "__pycache__" in p.parts or p in allowed:
            continue
        text = p.read_text(encoding="utf-8")
        if "cpu_count" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "cpu_count":
                    violations.append(f"{p.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert not violations, "发现绕过 src.utils.resource_guard 的直接 cpu_count() 调用:\n" + "\n".join(violations)
