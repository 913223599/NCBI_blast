# -*- coding: utf-8 -*-
"""跨平台路径兼容工具（Windows 8.3 短路径解析，规避空格路径问题）。"""
from __future__ import annotations

import ctypes
import logging
import os

logger = logging.getLogger("compat")


def get_short_path_name(long_name: str) -> str:
    """获取 Windows 8.3 短路径名，解决外部生信工具对空格路径不兼容的问题。"""
    if os.name != "nt" or not os.path.exists(long_name):
        return long_name

    try:
        from ctypes import wintypes

        _get_short_path_name = ctypes.windll.kernel32.GetShortPathNameW
        _get_short_path_name.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _get_short_path_name.restype = wintypes.DWORD

        buf = ctypes.create_unicode_buffer(1024)
        output_len = _get_short_path_name(long_name, buf, 1024)
        if output_len > 0:
            return buf.value
    except Exception as exc:
        logger.debug("Failed to get short path for %s: %s", long_name, exc)

    return long_name
