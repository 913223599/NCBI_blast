# -*- coding: utf-8 -*-
"""
应用元数据单一事实源加载器 (AppMetadata)
统一从项目根目录 version.json 读取平台名称、版本号与描述信息，
避免在后端 API、更新器、Electron 主进程与前端包清单之间出现版本号漂移。
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict
import logging
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = PROJECT_ROOT / "version.json"

DEFAULT_METADATA: Dict[str, str] = {
    "name": "NCBI Bio-Station",
    "version": "2.1.0",
    "description": "Local-First Bioinformatics Research Workstation",
}


@lru_cache(maxsize=1)
def get_app_metadata() -> Dict[str, str]:
    """读取并返回应用元数据字典（UTF-8）。"""
    meta = dict(DEFAULT_METADATA)
    if VERSION_FILE.is_file():
        try:
            raw = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("name", "version", "description"):
                    val = raw.get(key)
                    if isinstance(val, str) and val.strip():
                        meta[key] = val.strip()
        except Exception as exc:
            logger.debug("读取 version.json 元信息失败，回退默认值: %s", exc)
    return meta


def get_app_version() -> str:
    """返回当前应用统一版本号。"""
    return get_app_metadata()["version"]
