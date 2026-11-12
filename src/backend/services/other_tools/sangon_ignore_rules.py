# -*- coding: utf-8 -*-
"""
生工 16S 全局忽略规则与主题关键词过滤服务模块
职责：
1. 标准化提取订单号（兼容 10 位订单号及 YYYYMMDD_订单号 目录名）；
2. 管理全局忽略名单的读取、新增、移除与整批覆盖保存（与 .sangon_mail_index.json 解耦）；
3. 基于配置化关键词判断邮件主题是否属于生工测序结果通知。
"""
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from . import sangon_settings

_ORDER_NO_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")


def normalize_order_key(raw: str) -> str:
    """将订单目录名或订单号提取为统一的全局忽略键（优先 10 位订单号）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    m = _ORDER_NO_RE.search(text)
    if m:
        return m.group(1)
    if "_" in text:
        suffix = text.split("_", 1)[1].strip()
        if suffix:
            return suffix
    return text


def parse_ignore_keywords(keywords: Optional[Iterable[str]]) -> List[str]:
    """清洗主题过滤关键词列表，保留顺序并去重。"""
    if keywords is None:
        return list(sangon_settings.DEFAULT_IGNORE_SUBJECT_KEYWORDS)
    cleaned: List[str] = []
    seen = set()
    for item in keywords:
        kw = str(item or "").strip()
        if kw and kw not in seen:
            seen.add(kw)
            cleaned.append(kw)
    return cleaned


def is_sequencing_notice_subject(
    subject: str,
    ignore_keywords: Optional[Iterable[str]] = None,
) -> bool:
    """
    判断生工通知邮件主题是否属于测序结果通知：
    - 主题显式含“测序”视为测序结果通知；
    - 否则命中配置关键词（默认：已发货、物流、快递、发票、对账、付款）视为非测序通知。
    """
    s = (subject or "").strip()
    if not s:
        return False
    if "测序" in s:
        return True
    kws = parse_ignore_keywords(
        ignore_keywords if ignore_keywords is not None else sangon_settings.get_sangon_ignore_keywords()
    )
    if any(kw in s for kw in kws):
        return False
    return True


def list_ignored_orders() -> Dict[str, Dict[str, str]]:
    """读取全部全局忽略条目，按标准化订单号返回映射。"""
    raw_map = sangon_settings.get_sangon_ignored_orders()
    out: Dict[str, Dict[str, str]] = {}
    for k, meta in raw_map.items():
        ono = normalize_order_key(k)
        if not ono:
            continue
        dir_name = str((meta or {}).get("dir_name") or "").strip()
        if not dir_name and "_" in str(k):
            dir_name = str(k).strip()
        out[ono] = {
            "order_no": ono,
            "dir_name": dir_name,
            "reason": str((meta or {}).get("reason") or "").strip(),
            "ignored_at": str((meta or {}).get("ignored_at") or "").strip(),
        }
    return out


def ignore_orders(
    order_keys: Iterable[str],
    *,
    reason: str = "",
    dir_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """将指定订单加入全局忽略名单。"""
    current = list_ignored_orders()
    now_iso = datetime.now().isoformat(timespec="seconds")
    clean_reason = str(reason or "").strip()
    dir_lookup = {normalize_order_key(k): str(v).strip() for k, v in (dir_names or {}).items() if str(v).strip()}
    updated = 0
    affected_keys: List[str] = []

    for raw in order_keys:
        raw_str = str(raw or "").strip()
        ono = normalize_order_key(raw_str)
        if not ono:
            continue
        prev = current.get(ono) or {}
        inferred_dir = dir_lookup.get(ono) or (raw_str if "_" in raw_str else "") or prev.get("dir_name", "")
        current[ono] = {
            "order_no": ono,
            "dir_name": inferred_dir,
            "reason": clean_reason or prev.get("reason", ""),
            "ignored_at": prev.get("ignored_at") or now_iso,
        }
        updated += 1
        if ono not in affected_keys:
            affected_keys.append(ono)

    settings = sangon_settings.save_sangon_settings({"ignored_orders": current})
    return {
        "updated_count": updated,
        "affected_orders": affected_keys,
        "ignored_orders": settings["ignored_orders"],
        "settings": settings,
    }


def unignore_orders(order_keys: Iterable[str]) -> Dict[str, Any]:
    """将指定订单移出全局忽略名单。"""
    current = list_ignored_orders()
    removed = 0
    affected_keys: List[str] = []

    for raw in order_keys:
        ono = normalize_order_key(str(raw or ""))
        if not ono:
            continue
        if ono in current:
            del current[ono]
            removed += 1
            if ono not in affected_keys:
                affected_keys.append(ono)

    settings = sangon_settings.save_sangon_settings({"ignored_orders": current})
    return {
        "updated_count": removed,
        "affected_orders": affected_keys,
        "ignored_orders": settings["ignored_orders"],
        "settings": settings,
    }


def replace_ignore_rules(
    *,
    ignored_orders: Optional[Iterable[Any]] = None,
    ignore_subject_keywords: Optional[Iterable[str]] = None,
    default_reason: str = "",
) -> Dict[str, Any]:
    """整批覆盖保存忽略订单名单与/或非测序主题过滤关键词。"""
    patch: Dict[str, Any] = {}
    if ignored_orders is not None:
        prev_map = list_ignored_orders()
        now_iso = datetime.now().isoformat(timespec="seconds")
        next_map: Dict[str, Dict[str, str]] = {}
        clean_default_reason = str(default_reason or "").strip()

        for entry in ignored_orders:
            if isinstance(entry, dict):
                raw_key = str(entry.get("order_no") or entry.get("dir_name") or "").strip()
                ono = normalize_order_key(raw_key)
                if not ono:
                    continue
                prev = prev_map.get(ono) or {}
                dir_name = str(entry.get("dir_name") or (raw_key if "_" in raw_key else "") or prev.get("dir_name", "")).strip()
                reason = str(entry.get("reason") or prev.get("reason") or clean_default_reason).strip()
                ignored_at = str(entry.get("ignored_at") or prev.get("ignored_at") or now_iso).strip()
            else:
                raw_key = str(entry or "").strip()
                ono = normalize_order_key(raw_key)
                if not ono:
                    continue
                prev = prev_map.get(ono) or {}
                dir_name = (raw_key if "_" in raw_key else "") or prev.get("dir_name", "")
                reason = prev.get("reason") or clean_default_reason
                ignored_at = prev.get("ignored_at") or now_iso

            next_map[ono] = {
                "order_no": ono,
                "dir_name": dir_name,
                "reason": reason,
                "ignored_at": ignored_at,
            }
        patch["ignored_orders"] = next_map

    if ignore_subject_keywords is not None:
        patch["ignore_subject_keywords"] = parse_ignore_keywords(ignore_subject_keywords)

    settings = sangon_settings.save_sangon_settings(patch)
    return settings

