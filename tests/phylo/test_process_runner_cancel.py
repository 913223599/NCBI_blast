# -*- coding: utf-8 -*-
"""
阶段一测试：ProcessRunner 即时强杀取消机制（Windows 与 WSL 进程组验证）
"""
import subprocess
import sys
import threading
import time
import uuid

import pytest

from src.phylo.models.errors import PhyloCancelledError
from src.phylo.runtime.process_runner import ProcessRunner
from src.phylo.runtime.tool_registry import get_tool_registry

pytestmark = pytest.mark.offline


def test_native_process_cancel_fast():
    cancel_ev = threading.Event()
    runner = ProcessRunner(cancel_event=cancel_ev)

    def _trigger_cancel():
        time.sleep(0.5)
        cancel_ev.set()

    threading.Thread(target=_trigger_cancel, daemon=True).start()
    t0 = time.time()
    with pytest.raises(PhyloCancelledError):
        runner.run_native([sys.executable, "-c", "import time; time.sleep(30)"])
    elapsed = time.time() - t0
    assert elapsed < 4.0


def test_wsl_process_group_cancel_leaves_no_orphan():
    reg = get_tool_registry()
    if not reg.wsl_available:
        pytest.skip("WSL 不可用，跳过 WSL 进程组取消测试")

    marker = f"phylo_cancel_probe_{uuid.uuid4().hex[:8]}"
    cancel_ev = threading.Event()
    runner = ProcessRunner(cancel_event=cancel_ev, wsl_distro=reg.wsl_distro or "Ubuntu")

    def _trigger_cancel():
        time.sleep(1.2)
        cancel_ev.set()

    threading.Thread(target=_trigger_cancel, daemon=True).start()
    t0 = time.time()
    with pytest.raises(PhyloCancelledError):
        runner.run_wsl(["python3", "-c", f"import time; x='{marker}'; time.sleep(30)"])
    elapsed = time.time() - t0
    assert elapsed < 5.0

    # 检查 WSL 内确保没有任何带 marker 的残留进程（排除 pgrep 自身命令行）
    time.sleep(0.3)
    probe = subprocess.run(
        [
            "wsl",
            "-d",
            reg.wsl_distro or "Ubuntu",
            "-u",
            "root",
            "bash",
            "-c",
            f"ps -ef | grep -F '{marker}' | grep -v grep || true",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
    )
    assert marker not in probe.stdout
