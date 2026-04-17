import os
import ctypes
import logging

logger = logging.getLogger("compat")

def get_short_path_name(long_name: str) -> str:
    """获取 Windows 8.3 短路径名，彻底解决路径空格问题"""
    if os.name != 'nt' or not os.path.exists(long_name):
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
    except Exception as e:
        logger.debug(f"Failed to get short path for {long_name}: {e}")
        
    return long_name
