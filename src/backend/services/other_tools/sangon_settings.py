# -*- coding: utf-8 -*-
"""生工 16S 流程目录配置

配置文件：<项目根>/sangon_16s_config.json（本机路径配置，已加入 .gitignore）。
"""
import json
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SANGON_CONFIG_PATH = PROJECT_ROOT / "sangon_16s_config.json"

# 首次使用时的默认根目录（可在界面修改并持久化）
DEFAULT_SANGON_ROOT = r"G:\测序数据\生工16s"


def load_sangon_settings() -> Dict[str, Any]:
    data: Dict[str, Any] = {"sangon_root": DEFAULT_SANGON_ROOT}
    if SANGON_CONFIG_PATH.exists():
        try:
            data.update(json.loads(SANGON_CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_sangon_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    current = load_sangon_settings()
    current.update(data)
    SANGON_CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def get_sangon_root() -> Path:
    return Path(load_sangon_settings()["sangon_root"])

