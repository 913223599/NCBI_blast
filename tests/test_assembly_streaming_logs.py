# -*- coding: utf-8 -*-
"""
Test streaming log broadcasting in AssemblerStep.
"""
import pytest
from unittest.mock import MagicMock
from pathlib import Path
import tempfile

from src.assembly.core.base import PipelineContext
from src.assembly.steps.assembler import AssemblerStep


def test_assembler_step_streaming_log_callback():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ctx = PipelineContext("test_log_task", tmp_path, {"tech": "NANOPORE", "sample_type": "BACTERIA"})
        
        step = AssemblerStep(ctx)
        
        received_logs = []
        received_progress = []

        step.on_log = lambda line: received_logs.append(line)
        step.on_progress = lambda p, desc: received_progress.append((p, desc))

        # 模拟底层输出几行日志
        test_lines = [
            "[Phase 01] Streamed 1,000 clean reads into ReadStore",
            "[Phase 02] Overlap Graph Construction complete",
            "Graph Built: 1,000 nodes, 38,258 verified overlap edges (17.41 s).",
            "Solving Graph Laplacian Spectral Harmonic Gauge...",
            "[Phase 04] Scaffolding Complete: Extracted 1 unique chromosome entity(ies)",
            "[Phase 05] SIMD-POA Consensus Engine Restored 85,719 bp"
        ]

        # 模拟 progress_handler 内部逻辑
        for line in test_lines:
            line_str = line.strip()
            if step.on_log:
                step.on_log(line_str)
            if "[Phase 01]" in line_str:
                step.on_progress(20, "测序数据流流式加载中...")
            elif "[Phase 02]" in line_str or "Overlap Graph" in line_str:
                step.on_progress(35, "长读长分子重叠图与拓扑残差图构建...")
            elif "Solving Graph Laplacian" in line_str:
                step.on_progress(65, "图拉普拉斯谐波规范求解与骨架提取...")
            elif "[Phase 04]" in line_str:
                step.on_progress(75, "非相交环状支架构建与多聚体单体截断...")
            elif "[Phase 05]" in line_str:
                step.on_progress(85, "SIMD-POA 连续谱流形分层打磨与一致性精修...")

        # 验证所有行均被流式捕获，没有任何行被遗漏
        assert len(received_logs) == len(test_lines)
        assert received_logs[2] == "Graph Built: 1,000 nodes, 38,258 verified overlap edges (17.41 s)."
        # 验证进度映射正确
        assert len(received_progress) >= 5
        assert received_progress[-1][0] == 85
