# -*- coding: utf-8 -*-
"""生工 16S 流程目录、忽略规则与官网账号配置

配置文件：<项目根>/sangon_16s_config.json（本机配置，已加入 .gitignore）。
登录密码独立存放于密钥文件 .sangon_auth（被 .gitignore *.auth 忽略），接口只回传掩码。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .secret_store import mask_secret, read_secret, resolve_secret_path, write_secret

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SANGON_CONFIG_PATH = PROJECT_ROOT / "sangon_16s_config.json"

# 首次使用时的默认配置（可在界面或配置文件中覆盖并持久化）
DEFAULT_SANGON_ROOT = r"G:\测序数据\生工16s"
DEFAULT_DOWNLOADS_DIR = str(Path.home() / "Downloads")
DEFAULT_IGNORE_SUBJECT_KEYWORDS: List[str] = ["已发货", "物流", "快递", "发票", "对账", "付款"]
DEFAULT_SANGON_PASSWORD_FILE = ".sangon_auth"


def _normalize_ignored_orders_dict(raw: Any) -> Dict[str, Dict[str, str]]:
    """兼容旧版列表或新版字典结构的已忽略订单映射，统一以订单号为键。"""
    normalized: Dict[str, Dict[str, str]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k or "").strip()
            if not key:
                continue
            if isinstance(v, dict):
                ono = str(v.get("order_no") or key).strip()
                normalized[ono] = {
                    "order_no": ono,
                    "dir_name": str(v.get("dir_name") or "").strip(),
                    "reason": str(v.get("reason") or "").strip(),
                    "ignored_at": str(v.get("ignored_at") or "").strip(),
                }
            else:
                normalized[key] = {
                    "order_no": key,
                    "dir_name": "",
                    "reason": str(v or "").strip(),
                    "ignored_at": "",
                }
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                ono = str(item.get("order_no") or item.get("key") or "").strip()
                if not ono:
                    continue
                normalized[ono] = {
                    "order_no": ono,
                    "dir_name": str(item.get("dir_name") or "").strip(),
                    "reason": str(item.get("reason") or "").strip(),
                    "ignored_at": str(item.get("ignored_at") or "").strip(),
                }
            else:
                ono = str(item or "").strip()
                if ono:
                    normalized[ono] = {
                        "order_no": ono,
                        "dir_name": "",
                        "reason": "",
                        "ignored_at": "",
                    }
    return normalized


def _normalize_keywords_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return list(DEFAULT_IGNORE_SUBJECT_KEYWORDS)
    cleaned: List[str] = []
    seen = set()
    for item in raw:
        kw = str(item or "").strip()
        if kw and kw not in seen:
            seen.add(kw)
            cleaned.append(kw)
    return cleaned


def load_sangon_settings() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "sangon_root": DEFAULT_SANGON_ROOT,
        "downloads_dir": DEFAULT_DOWNLOADS_DIR,
        "ignored_orders": {},
        "ignore_subject_keywords": list(DEFAULT_IGNORE_SUBJECT_KEYWORDS),
        "sangon_account": "",
        "sangon_password_file": DEFAULT_SANGON_PASSWORD_FILE,
        "auto_confirm_fee": True,
    }
    if SANGON_CONFIG_PATH.exists():
        try:
            loaded = json.loads(SANGON_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                if loaded.get("sangon_root"):
                    data["sangon_root"] = str(loaded["sangon_root"]).strip()
                if loaded.get("downloads_dir"):
                    data["downloads_dir"] = str(loaded["downloads_dir"]).strip()
                if "ignored_orders" in loaded:
                    data["ignored_orders"] = _normalize_ignored_orders_dict(loaded.get("ignored_orders"))
                if "ignore_subject_keywords" in loaded:
                    data["ignore_subject_keywords"] = _normalize_keywords_list(loaded.get("ignore_subject_keywords"))
                if "sangon_account" in loaded:
                    data["sangon_account"] = str(loaded.get("sangon_account") or "").strip()
                if loaded.get("sangon_password_file"):
                    data["sangon_password_file"] = str(loaded["sangon_password_file"]).strip()
                if "auto_confirm_fee" in loaded:
                    data["auto_confirm_fee"] = bool(loaded.get("auto_confirm_fee"))
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_sangon_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    current = load_sangon_settings()
    if data.get("sangon_root"):
        current["sangon_root"] = str(data["sangon_root"]).strip()
    if data.get("downloads_dir"):
        current["downloads_dir"] = str(data["downloads_dir"]).strip()
    if "ignored_orders" in data:
        current["ignored_orders"] = _normalize_ignored_orders_dict(data.get("ignored_orders"))
    if "ignore_subject_keywords" in data:
        current["ignore_subject_keywords"] = _normalize_keywords_list(data.get("ignore_subject_keywords"))
    if "sangon_account" in data and data.get("sangon_account") is not None:
        current["sangon_account"] = str(data.get("sangon_account") or "").strip()
    if data.get("sangon_password_file"):
        current["sangon_password_file"] = str(data["sangon_password_file"]).strip()
    if "auto_confirm_fee" in data and data.get("auto_confirm_fee") is not None:
        current["auto_confirm_fee"] = bool(data.get("auto_confirm_fee"))
    SANGON_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SANGON_CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def get_sangon_root() -> Path:
    return Path(load_sangon_settings()["sangon_root"])


def get_sangon_downloads_dir() -> Path:
    return Path(load_sangon_settings().get("downloads_dir") or DEFAULT_DOWNLOADS_DIR)


def get_sangon_ignored_orders() -> Dict[str, Dict[str, str]]:
    return dict(load_sangon_settings().get("ignored_orders") or {})


def get_sangon_ignore_keywords() -> List[str]:
    kws = load_sangon_settings().get("ignore_subject_keywords")
    return list(kws) if isinstance(kws, list) else list(DEFAULT_IGNORE_SUBJECT_KEYWORDS)


def resolve_sangon_password_file() -> Path:
    settings = load_sangon_settings()
    raw = str(settings.get("sangon_password_file") or DEFAULT_SANGON_PASSWORD_FILE).strip()
    return resolve_secret_path(PROJECT_ROOT, raw or DEFAULT_SANGON_PASSWORD_FILE)


def get_sangon_auth_status() -> Dict[str, Any]:
    """返回生工官网账号与密钥就绪状态（仅返回密码掩码，不泄露明文）。"""
    settings = load_sangon_settings()
    pwd_file = resolve_sangon_password_file()
    pwd = read_secret(pwd_file)
    return {
        "account": str(settings.get("sangon_account") or "").strip(),
        "password_ready": bool(pwd),
        "password_masked": mask_secret(pwd),
        "password_file": str(pwd_file),
        "auto_confirm_fee": bool(settings.get("auto_confirm_fee", True)),
    }


def resolve_sangon_credentials() -> Tuple[str, str]:
    """读取用于自动化登录的生工账号与明文密码（仅限后端内部登录过程调用）。"""
    settings = load_sangon_settings()
    account = str(settings.get("sangon_account") or "").strip()
    password = read_secret(resolve_sangon_password_file()) or ""
    return account, password


def save_sangon_credentials(
    *,
    account: Optional[str] = None,
    password: Optional[str] = None,
    auto_confirm_fee: Optional[bool] = None,
) -> Dict[str, Any]:
    """分别保存生工账号配置与独立密码密钥文件；password=None 表示保留原密钥，空串表示删除。"""
    patch: Dict[str, Any] = {}
    if account is not None:
        patch["sangon_account"] = str(account).strip()
    if auto_confirm_fee is not None:
        patch["auto_confirm_fee"] = bool(auto_confirm_fee)
    if patch:
        save_sangon_settings(patch)

    if password is not None:
        pwd_file = resolve_sangon_password_file()
        write_secret(pwd_file, password)

    return get_sangon_auth_status()
