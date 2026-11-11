# -*- coding: utf-8 -*-
"""
Unit tests for AssemblyFileHandler ZIP archive detection and streaming extraction.
"""

import os
import zipfile
import tempfile
from pathlib import Path
import pytest

from src.assembly.utils.file_handler import AssemblyFileHandler


def test_is_zip_archive():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # 1. 真实 ZIP 文件
        real_zip = tmp_path / "valid.zip"
        with zipfile.ZipFile(real_zip, "w") as zf:
            zf.writestr("test.txt", "hello world")
        assert AssemblyFileHandler.is_zip_archive(real_zip) is True

        # 2. 伪造的非 ZIP 文件（即使后缀是 .zip）
        fake_zip = tmp_path / "fake.zip"
        with open(fake_zip, "w", encoding="utf-8") as f:
            f.write("not a zip file content")
        assert AssemblyFileHandler.is_zip_archive(fake_zip) is False

        # 3. 普通 FASTQ 文件
        plain_fq = tmp_path / "sample.fastq"
        with open(plain_fq, "w", encoding="utf-8") as f:
            f.write("@read1\nATCG\n+\nIIII\n")
        assert AssemblyFileHandler.is_zip_archive(plain_fq) is False

        # 4. 不存在的文件
        assert AssemblyFileHandler.is_zip_archive(tmp_path / "not_exist.zip") is False


def test_extract_and_merge_zip_fastq():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        zip_file = tmp_path / "multi_part.zip"

        # 构造包含 3 个分卷 FASTQ 和 1 个 CSV 的 ZIP 包
        chunk1 = "@read_0001\nATCGATCG\n+\nIIIIIIII\n"
        chunk2 = "@read_0002\nGGGCCCAT\n+\nIIIIIIII\n"
        chunk3 = "@read_0003\nTTTTAAAA\n+\nIIIIIIII\n"
        meta_csv = "read_id,length\nread_0001,8\nread_0002,8\nread_0003,8\n"

        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.writestr("fastq/reads_0002.fastq", chunk2)
            zf.writestr("fastq/reads_0001.fastq", chunk1)
            zf.writestr("fastq/reads_0003.fastq", chunk3)
            zf.writestr("fastq/signal_info.csv", meta_csv)

        output_fastq = tmp_path / "merged.fastq"
        progress_records = []

        def on_progress(p: float, desc: str):
            progress_records.append((p, desc))

        success = AssemblyFileHandler.extract_and_merge_zip_fastq(
            zip_file,
            output_fastq,
            on_progress=on_progress
        )

        assert success is True
        assert output_fastq.exists()
        assert output_fastq.stat().st_size > 0

        # 读取合并结果，验证按文件名自然排序且排除了 csv
        content = output_fastq.read_text(encoding="utf-8")
        assert "@read_0001" in content
        assert "@read_0002" in content
        assert "@read_0003" in content
        assert "signal_info" not in content
        
        # 验证读取顺序：reads_0001 在 reads_0002 之前，reads_0002 在 reads_0003 之前
        idx1 = content.index("@read_0001")
        idx2 = content.index("@read_0002")
        idx3 = content.index("@read_0003")
        assert idx1 < idx2 < idx3

        # 验证进度回调被触发
        assert len(progress_records) > 0
        assert progress_records[-1][0] == 100.0


def test_i_drive_fastq_zip_inspection():
    """如果 I 盘的 fastq.zip 存在，测试对其的结构探测与识别"""
    i_zip = Path("I:/fastq.zip")
    if not i_zip.exists():
        pytest.skip("I:/fastq.zip not mounted or unavailable")

    assert AssemblyFileHandler.is_zip_archive(i_zip) is True
    # 探查内部包含的 fastq 文件列表
    entries = AssemblyFileHandler.list_zip_fastq_entries(i_zip)
    assert len(entries) >= 70
    assert any("reads_0001" in e for e in entries)


def test_assembler_step_zip_integration():
    """测试 AssemblerStep 上下文与 ZIP 文件输入处理的集成行为"""
    from src.assembly.core.base import PipelineContext
    from src.assembly.steps.assembler import AssemblerStep

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        zip_file = tmp_path / "sample_reads.zip"

        chunk1 = "@ont_read_01\nATCGATCGATCG\n+\nIIIIIIIIIIII\n"
        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.writestr("reads/part1.fastq", chunk1)

        ctx = PipelineContext("test_zip_job", tmp_path, {"tech": "NANOPORE", "sample_type": "BACTERIA"})
        ctx.update("r1", zip_file)

        step = AssemblerStep(ctx)
        # 验证 AssemblyFileHandler 能够正确支持该文件
        assert AssemblyFileHandler.is_zip_archive(ctx.get("r1")) is True
        assert AssemblyFileHandler.get_sample_id(str(zip_file)) == "sample_reads"

