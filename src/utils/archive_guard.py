# -*- coding: utf-8 -*-
"""
压缩包安全解压守卫 (ArchiveGuard)

防御 Zip-Slip 与 Tar-Slip 路径穿越漏洞：
- 禁止绝对路径、驱动器前缀、`..` 目录逃逸及指向目标目录之外的符号链接/硬链接；
- 兼容 Python 3.11 与 3.12+（在支持 `filter="data"` 时显式启用标准安全过滤器）。
"""
from __future__ import annotations

import inspect
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Union


def _ensure_within_directory(base_dir: Path, target_path: Path, member_name: str) -> Path:
    base_resolved = base_dir.resolve()
    target_resolved = target_path.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"压缩包成员存在路径穿越风险，已拦截: {member_name}") from exc
    return target_resolved


def safe_extract_zip(zip_source: Union[Path, str, zipfile.ZipFile], dest_dir: Union[Path, str]) -> Path:
    """安全解压 ZIP 文件至目标目录，严防 Zip-Slip 与恶意符号链接。"""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    def _extract(zf: zipfile.ZipFile) -> None:
        for info in zf.infolist():
            name = info.filename
            if not name or name.startswith(("/", "\\")):
                raise ValueError(f"ZIP 成员包含非法绝对路径: {name}")
            # 拦截 Unix 符号链接条目（external_attr 高 16 位为 st_mode）
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise ValueError(f"ZIP 成员包含受限符号链接: {name}")

            target = dest / Path(*Path(name.replace("\\", "/")).parts)
            _ensure_within_directory(dest, target, name)

        for info in zf.infolist():
            zf.extract(info, path=dest)

    if isinstance(zip_source, zipfile.ZipFile):
        _extract(zip_source)
    else:
        with zipfile.ZipFile(zip_source, "r") as zf:
            _extract(zf)
    return dest


def safe_extract_tar(
    tar_source: Union[Path, str, tarfile.TarFile],
    dest_dir: Union[Path, str],
    mode: str = "r:*",
) -> Path:
    """安全解压 TAR/TAR.GZ/TAR.BZ2 归档至目标目录，严防 Tar-Slip 与设备文件/链接逃逸。"""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    def _validate_and_extract(tf: tarfile.TarFile) -> None:
        members = tf.getmembers()
        for member in members:
            name = member.name
            if not name or name.startswith(("/", "\\")) or os.path.isabs(name):
                raise ValueError(f"TAR 成员包含非法绝对路径: {name}")
            if member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                raise ValueError(f"TAR 成员包含非法特殊设备节点: {name}")

            target = dest / name
            _ensure_within_directory(dest, target, name)

            if member.issym() or member.islnk():
                link_target = (target.parent / member.linkname) if member.issym() else (dest / member.linkname)
                _ensure_within_directory(dest, link_target, f"{name} -> {member.linkname}")

        extract_sig = inspect.signature(tf.extractall)
        if "filter" in extract_sig.parameters:
            tf.extractall(path=dest, members=members, filter="data")
        else:
            for member in members:
                tf.extract(member, path=dest)

    if isinstance(tar_source, tarfile.TarFile):
        _validate_and_extract(tar_source)
    else:
        with tarfile.open(tar_source, mode) as tf:
            _validate_and_extract(tf)
    return dest
