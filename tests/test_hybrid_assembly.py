# -*- coding: utf-8 -*-
"""
单元测试：NGCS 二代+三代混合拼接调度与命令行构建验证
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 注入项目路径
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.assembly.steps.assembler import AssemblerStep
from src.assembly.core.base import PipelineContext


class TestHybridAssemblyOrchestration(unittest.IsolatedAsyncioTestCase):
    """测试混合拼接的上下文准备与 CLI 命令构造"""

    async def test_hybrid_command_construction(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            task_id = "test_hybrid_task_001"
            task_dir = tmp_p / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)

            r1_file = tmp_p / "short_1.fastq.gz"
            r2_file = tmp_p / "short_2.fastq.gz"
            lr_file = tmp_p / "ont_long.fastq.gz"
            r1_file.write_text("@r1\nACGT\n+\nIIII\n", encoding="utf-8")
            r2_file.write_text("@r2\nACGT\n+\nIIII\n", encoding="utf-8")
            lr_file.write_text("@lr\nACGT\n+\nIIII\n", encoding="utf-8")

            config = {
                "name": "HybridSample",
                "tech": "HYBRID",
                "sample_type": "BACTERIA",
                "r1": str(r1_file),
                "r2": str(r2_file),
                "long_reads": str(lr_file),
                "params": {
                    "threads": 16,
                    "mode": "isolate",
                    "min_read_length": 1200,
                    "min_contig_length": 600,
                    "enable_qc": True,
                    "enable_error_correction": True
                }
            }

            ctx = PipelineContext(task_id, task_dir, config)
            ctx.update("r1", r1_file)
            ctx.update("r2", r2_file)
            ctx.update("long_reads", lr_file)

            step = AssemblerStep(ctx)

            async def fake_run_command(cmd, cwd=None, env=None, on_output=None, is_shell=False):
                # 模拟引擎在 cwd 生成了 assembly.fasta
                if cwd:
                    fa = Path(cwd) / "assembly.fasta"
                    fa.parent.mkdir(parents=True, exist_ok=True)
                    fa.write_text(">contig_1 length=5000\nACGT\n", encoding="utf-8")
                return 0

            with patch.object(step, "is_completed", return_value=False), \
                 patch.object(step, "_resolve_ngcs_cli", return_value=Path("E:/NGCS/ngcs/cli.py")), \
                 patch.object(step, "_parse_assembly_stats", return_value={"total_length": 5000, "contigs": 1}), \
                 patch.object(step.runner, "run_command", side_effect=fake_run_command) as mock_run:

                success = await step.execute()

                self.assertTrue(success)
                self.assertTrue(mock_run.called)

                called_cmd = mock_run.call_args[0][0]
                cmd_str = " ".join(called_cmd)

                # 验证 Hybrid 模式参数
                self.assertIn("--mode hybrid", cmd_str)
                self.assertIn("-1", called_cmd)
                self.assertIn("-2", called_cmd)
                self.assertIn("-i", called_cmd)
                self.assertIn("-t 16", cmd_str)
                self.assertIn("--min-len 1200", cmd_str)
                self.assertIn("--min-contig-len 600", cmd_str)


if __name__ == "__main__":
    unittest.main()
