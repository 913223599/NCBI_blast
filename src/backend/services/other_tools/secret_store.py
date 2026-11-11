# -*- coding: utf-8 -*-
"""邮箱授权码（Key）存取

授权码保存在独立密钥文件（默认 .mail_auth / .mail_smtp_auth，已加入 .gitignore），
接口只返回掩码，不回传明文。
"""
from pathlib import Path
from typing import Optional


def resolve_secret_path(base_dir: Path, name: str) -> Path:
    p = Path(name)
    return p if p.is_absolute() else base_dir / p


def read_secret(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None
    return value or None


def write_secret(path: Path, value: str) -> None:
    """写入授权码；value 为空字符串时删除密钥文件。"""
    value = (value or "").strip()
    if not value:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"

