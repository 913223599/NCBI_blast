# -*- coding: utf-8 -*-
"""
Pytest 收集期分层剪枝钩子：
当显式执行 `-m offline` 时，在导入测试模块前提前跳过未声明 `pytest.mark.offline`
的测试文件，避免 CI 极简环境因 ml/integration 文件的顶层重包导入而在 collection 阶段中断。
"""
from __future__ import annotations

from pathlib import Path
import pytest


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    markexpr = (getattr(config.option, "markexpr", "") or "").strip()
    if markexpr != "offline":
        return None
    if collection_path.suffix != ".py" or not collection_path.name.startswith("test_"):
        return None
    try:
        text = collection_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return "pytest.mark.offline" not in text
