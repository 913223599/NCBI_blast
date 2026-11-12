# -*- coding: utf-8 -*-
"""
生工 16S 订单展示信息补充模块
职责：
1. 从 .sangon_mail_index.json 读取订单对应的通知邮件主题、下载页链接与建目录时间；
2. 关联全局忽略名单，为订单与待认领压缩包补充 ignored / ignore_reason / ignored_at；
3. 依据建目录时间与订单状态计算“新订单”标记（新建、未忽略且尚未下载，7 天窗口有效）；
4. 关联浏览器下载目录中已识别、尚未归档的测序压缩包，供订单行直接给出“认领”操作。
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sangon_ignore_rules import list_ignored_orders, normalize_order_key
from .sangon_mail_scanner import SangonMailIndex

NEW_ORDER_WINDOW_DAYS = 7


def _is_recent(created_at: str, now: datetime) -> bool:
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return False
    return now - created <= timedelta(days=NEW_ORDER_WINDOW_DAYS)


def annotate_sangon_orders(
    root_path: Path,
    orders: List[Dict[str, Any]],
    download_candidates: List[Dict[str, Any]],
    ignored_orders: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    """就地为订单与下载候选字典补充邮件来源、下载页、全局忽略与可认领下载包字段。"""
    index = SangonMailIndex(root_path)
    index.load()
    now = datetime.now()
    ignored_map = (
        {
            normalize_order_key(k): dict(v or {})
            for k, v in ignored_orders.items()
            if normalize_order_key(k)
        }
        if ignored_orders is not None
        else list_ignored_orders()
    )

    zip_by_dir: Dict[str, Dict[str, Any]] = {}
    for cand in download_candidates:
        ono_key = normalize_order_key(str(cand.get("order_no") or ""))
        ig_meta = ignored_map.get(ono_key)
        cand["ignored"] = bool(ig_meta)
        cand["ignore_reason"] = (ig_meta or {}).get("reason") or ""
        cand["ignored_at"] = (ig_meta or {}).get("ignored_at") or ""

        dir_name = cand.get("matched_dir_name") or ""
        if dir_name and not cand.get("archived") and not cand["ignored"] and dir_name not in zip_by_dir:
            zip_by_dir[dir_name] = cand

    for order in orders:
        ono_key = normalize_order_key(str(order.get("order_no") or order.get("dir_name") or ""))
        ig_meta = ignored_map.get(ono_key)
        is_ignored = bool(ig_meta)

        meta = index.get_order(str(order.get("order_no") or ""))
        created_at = str(meta.get("created_at") or "")
        order["mail_subject"] = str(meta.get("subject") or "")
        order["mail_date"] = str(meta.get("date") or "")
        order["cx_order_id"] = str(meta.get("cx_order_id") or "")
        order["download_url"] = str(meta.get("download_url") or "")
        order["created_at"] = created_at
        order["ignored"] = is_ignored
        order["ignore_reason"] = (ig_meta or {}).get("reason") or ""
        order["ignored_at"] = (ig_meta or {}).get("ignored_at") or ""
        order["is_new"] = (not is_ignored) and order.get("status") == "pending" and _is_recent(created_at, now)

        cand = zip_by_dir.get(str(order.get("dir_name") or ""))
        order["download_zip_ready"] = bool(cand)
        order["download_zip_name"] = str(cand.get("zip_name") or "") if cand else ""
