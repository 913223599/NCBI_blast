# -*- coding: utf-8 -*-
"""压缩包安全解压守卫 (archive_guard) 单元测试：验证合法解压与 Zip-Slip / Tar-Slip 防护。"""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from src.utils.archive_guard import safe_extract_tar, safe_extract_zip

pytestmark = pytest.mark.offline


def test_safe_extract_zip_valid_and_blocks_zip_slip(tmp_path: Path):
    good_zip = tmp_path / "good.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("sub/sample.fasta", ">seq1\nATGC\n")

    out_dir = tmp_path / "out_good"
    safe_extract_zip(good_zip, out_dir)
    assert (out_dir / "sub" / "sample.fasta").read_text(encoding="utf-8") == ">seq1\nATGC\n"

    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../../escaped.txt", "pwned")

    with pytest.raises(ValueError, match="路径穿越"):
        safe_extract_zip(evil_zip, tmp_path / "out_evil")


def test_safe_extract_tar_valid_and_blocks_tar_slip_and_symlink(tmp_path: Path):
    good_tar = tmp_path / "good.tar.gz"
    with tarfile.open(good_tar, "w:gz") as tf:
        data = b">seq2\nGGCC\n"
        info = tarfile.TarInfo("dir/db.fa")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    out_dir = tmp_path / "tar_good"
    safe_extract_tar(good_tar, out_dir)
    assert (out_dir / "dir" / "db.fa").read_text(encoding="utf-8") == ">seq2\nGGCC\n"

    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tf:
        data = b"evil"
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    with pytest.raises(ValueError, match="路径穿越"):
        safe_extract_tar(evil_tar, tmp_path / "tar_evil")

    sym_tar = tmp_path / "sym.tar.gz"
    with tarfile.open(sym_tar, "w:gz") as tf:
        info = tarfile.TarInfo("badlink")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../etc/passwd"
        tf.addfile(info)

    with pytest.raises(ValueError, match="路径穿越"):
        safe_extract_tar(sym_tar, tmp_path / "tar_sym")
