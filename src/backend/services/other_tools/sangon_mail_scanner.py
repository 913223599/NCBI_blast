# -*- coding: utf-8 -*-
"""
生工 16S 邮件扫描、去重与分页服务模块
职责：
1. 维护本地 .sangon_mail_index.json 扫描去重索引（跨次防误建已清理历史订单）；
2. 两阶段连接 IMAP 扫描 info1@sangon.com 通知邮件，执行批内订单级/Message-ID 去重；
3. 按服务端分页切片，仅对当前页邮件拉取全文解析 cxOrderID 与下载链接；
4. 按需自动或手动初始化 YYYYMMDD_订单号 三级工作目录。
"""
import json
import logging
import re
import shutil
from datetime import datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .sangon_ignore_rules import (
    is_sequencing_notice_subject,
    list_ignored_orders,
    normalize_order_key,
)
from ....mail_download.fetcher import (
    MailFetcher,
    _decode_header,
    _parse_address,
    _to_str,
)

logger = logging.getLogger("api.other_tools.sangon_mail_scanner")

SANGON_MAIL_INDEX_NAME = ".sangon_mail_index.json"
SANGON_SENDER = "info1@sangon.com"
MAX_SCAN_PAGE_SIZE = 200
_ORDER_NO_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")
_CX_ORDER_RE = re.compile(r"cxOrderID=([A-Za-z0-9_-]+)")
_SAFE_DIR_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class SangonMailIndex:
    """持久化生工 16S 已扫描通知邮件与订单目录去重索引。"""

    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self._data: Dict[str, Any] = {"seen_message_ids": {}, "seen_orders": {}}
        self._loaded = False

    @property
    def index_path(self) -> Path:
        return self.root_dir / SANGON_MAIL_INDEX_NAME

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self.index_path
        if not path.exists():
            self._data = {"seen_message_ids": {}, "seen_orders": {}}
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {
                    "seen_message_ids": dict(raw.get("seen_message_ids") or {}),
                    "seen_orders": dict(raw.get("seen_orders") or {}),
                }
            else:
                self._data = {"seen_message_ids": {}, "seen_orders": {}}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("生工邮件扫描索引损坏，已备份重建: %s", e)
            try:
                shutil.copy2(path, path.with_suffix(".corrupt.bak"))
            except OSError:
                pass
            self._data = {"seen_message_ids": {}, "seen_orders": {}}

    def save(self) -> None:
        self.load()
        if not self.root_dir.exists():
            return
        self.index_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_known(self, order_no: str, message_id: str) -> bool:
        """判断订单或邮件是否已录入索引（含曾创建或被清理标记）。"""
        self.load()
        if order_no and order_no in self._data["seen_orders"]:
            return True
        if message_id and message_id in self._data["seen_message_ids"]:
            return True
        return False

    def is_cleaned(self, order_no: str) -> bool:
        self.load()
        entry = self._data["seen_orders"].get(order_no)
        return bool(isinstance(entry, dict) and entry.get("cleaned"))

    def get_order(self, order_no: str) -> Dict[str, Any]:
        """读取单个订单的索引记录（含下载页链接与建目录时间），不存在时返回空字典。"""
        self.load()
        entry = self._data["seen_orders"].get((order_no or "").strip())
        return dict(entry) if isinstance(entry, dict) else {}

    def record(
        self,
        *,
        order_no: str,
        message_id: str,
        dir_name: str,
        subject: str,
        date_text: str,
        cx_order_id: str = "",
        download_url: str = "",
        cleaned: bool = False,
        created: bool = False,
    ) -> None:
        self.load()
        now_iso = datetime.now().isoformat(timespec="seconds")
        if order_no:
            prev = self._data["seen_orders"].get(order_no) or {}
            entry = {
                "order_no": order_no,
                "dir_name": dir_name or prev.get("dir_name", ""),
                "subject": subject or prev.get("subject", ""),
                "date": date_text or prev.get("date", ""),
                "cx_order_id": cx_order_id or prev.get("cx_order_id", ""),
                "download_url": download_url or prev.get("download_url", ""),
                "first_seen": prev.get("first_seen", now_iso),
                "last_seen": now_iso,
                "cleaned": cleaned,
            }
            # 仅在本工具实际新建目录时记录建目录时间，用于订单表“新”标记
            created_at = prev.get("created_at", "")
            if created and (not created_at or prev.get("cleaned")):
                created_at = now_iso
            if created_at:
                entry["created_at"] = created_at
            self._data["seen_orders"][order_no] = entry
        if message_id:
            prev_mid = self._data["seen_message_ids"].get(message_id) or {}
            self._data["seen_message_ids"][message_id] = {
                "message_id": message_id,
                "order_no": order_no or prev_mid.get("order_no", ""),
                "dir_name": dir_name or prev_mid.get("dir_name", ""),
                "subject": subject or prev_mid.get("subject", ""),
                "date": date_text or prev_mid.get("date", ""),
                "first_seen": prev_mid.get("first_seen", now_iso),
                "last_seen": now_iso,
            }

    def mark_cleaned(self, order_nos: Iterable[str]) -> int:
        """订单目录被历史清理删除后，保留 cleaned 标记防止下次扫描自动重建空目录。"""
        self.load()
        now_iso = datetime.now().isoformat(timespec="seconds")
        updated = 0
        for order_no in order_nos:
            ono = (order_no or "").strip()
            if not ono:
                continue
            prev = self._data["seen_orders"].get(ono) or {"order_no": ono, "first_seen": now_iso}
            prev["cleaned"] = True
            prev["cleaned_at"] = now_iso
            prev["last_seen"] = now_iso
            self._data["seen_orders"][ono] = prev
            updated += 1
        if updated:
            self.save()
        return updated

    def clear(self, order_nos: Optional[Iterable[str]] = None) -> int:
        """清空全部或指定订单号的扫描记忆，使其重新进入待新建状态。"""
        self.load()
        if order_nos is None:
            removed = len(self._data["seen_orders"]) + len(self._data["seen_message_ids"])
            self._data = {"seen_message_ids": {}, "seen_orders": {}}
            self.save()
            return removed

        target_set = {(o or "").strip() for o in order_nos if (o or "").strip()}
        removed = 0
        for ono in list(self._data["seen_orders"].keys()):
            if ono in target_set:
                del self._data["seen_orders"][ono]
                removed += 1
        for mid, meta in list(self._data["seen_message_ids"].items()):
            if isinstance(meta, dict) and meta.get("order_no") in target_set:
                del self._data["seen_message_ids"][mid]
                removed += 1
        if removed:
            self.save()
        return removed

    def stats(self) -> Dict[str, int]:
        self.load()
        return {
            "orders": len(self._data["seen_orders"]),
            "message_ids": len(self._data["seen_message_ids"]),
        }


def _extract_date_prefix(date_str: str) -> str:
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.strftime("%Y%m%d")
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d")


def _extract_body_details(msg: Message) -> Dict[str, str]:
    body_html = ""
    for part in msg.walk():
        if part.get_content_type() in ("text/html", "text/plain") and not part.get_filename():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                cs = part.get_content_charset() or "utf-8"
                body_html += payload.decode(cs, errors="replace")
            elif isinstance(payload, str):
                body_html += payload
    cx_match = _CX_ORDER_RE.search(body_html)
    cx_order_id = cx_match.group(1) if cx_match else ""
    download_url = (
        f"http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID={cx_order_id}"
        if cx_order_id
        else ""
    )
    body_order_match = _ORDER_NO_RE.search(body_html)
    body_order_no = body_order_match.group(1) if body_order_match else ""
    return {
        "cx_order_id": cx_order_id,
        "download_url": download_url,
        "body_order_no": body_order_no,
    }


def _is_sangon_sender(sender: str) -> bool:
    low = (sender or "").strip().lower()
    if not low:
        return True
    return "sangon" in low


def _is_sequencing_notice_subject(
    subject: str,
    ignore_keywords: Optional[Iterable[str]] = None,
) -> bool:
    """过滤非测序结果通知（如“订单已发货”“发票通知”等物流/商务邮件），避免误建空 16S 目录。"""
    return is_sequencing_notice_subject(subject, ignore_keywords=ignore_keywords)


def create_sangon_subdirs(order_path: Path) -> None:
    (order_path / "原始压缩包").mkdir(parents=True, exist_ok=True)
    (order_path / "原始数据").mkdir(parents=True, exist_ok=True)
    (order_path / "BLAST结果").mkdir(parents=True, exist_ok=True)


def init_sangon_order_dir(
    root_dir: Path,
    dir_name: str,
    *,
    order_no: str = "",
    subject: str = "",
    date_text: str = "",
    cx_order_id: str = "",
    download_url: str = "",
) -> Dict[str, Any]:
    """手动初始化单个生工订单的三级目录并更新扫描索引。"""
    clean_name = (dir_name or "").strip()
    if not clean_name or not _SAFE_DIR_RE.match(clean_name):
        raise ValueError(f"非法的订单目录名: {dir_name}")
    if not root_dir.exists():
        root_dir.mkdir(parents=True, exist_ok=True)

    order_path = root_dir / clean_name
    if order_path.parent.resolve() != root_dir.resolve():
        raise ValueError("订单目录路径越界")

    existed = order_path.exists()
    create_sangon_subdirs(order_path)

    inferred_no = order_no.strip()
    if not inferred_no and "_" in clean_name:
        inferred_no = clean_name.split("_", 1)[1]

    idx = SangonMailIndex(root_dir)
    idx.load()
    if inferred_no:
        idx.record(
            order_no=inferred_no,
            message_id="",
            dir_name=clean_name,
            subject=subject,
            date_text=date_text,
            cx_order_id=cx_order_id,
            download_url=download_url,
            cleaned=False,
            created=not existed,
        )
        idx.save()

    return {
        "dir_name": clean_name,
        "order_path": str(order_path),
        "created": not existed,
    }


def _scan_existing_orders(root_dir: Path) -> Dict[str, str]:
    """扫描当前磁盘已存在的 order_no -> dir_name 映射。"""
    existing: Dict[str, str] = {}
    if not root_dir.exists():
        return existing
    for d in sorted(root_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if d.is_dir() and "_" in d.name:
            order_no = d.name.split("_", 1)[1]
            if order_no and order_no not in existing:
                existing[order_no] = d.name
    return existing


def _order_needs_download(order_path: Path) -> bool:
    """订单目录尚无压缩包且无解压数据时视为待下载（需要下载页链接）。"""
    if not order_path.exists():
        return True
    zip_dir = order_path / "原始压缩包"
    raw_dir = order_path / "原始数据"
    has_zip = zip_dir.exists() and any(zip_dir.glob("*.zip"))
    has_raw = raw_dir.exists() and any(p.is_file() for p in raw_dir.rglob("*"))
    return not (has_zip or has_raw)


def scan_sangon_mails(
    root_dir: Path,
    cfg: Any,
    *,
    page: int = 1,
    page_size: int = 10,
    dedup: bool = True,
    only_new: bool = False,
    auto_create: bool = True,
    ignore_history: bool = False,
    ignored_orders: Optional[Iterable[str]] = None,
    ignore_keywords: Optional[Iterable[str]] = None,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """
    连接邮箱扫描生工通知邮件（两阶段：全量头部去重分页 + 当前页正文链接提取）。
    正文仅对缺少订单号、或待下载且索引中无下载链接缓存的邮件拉取，减少重复扫描耗时。
    支持 conn_factory 注入（FakeIMAP 离线测试）。
    """
    page_size = max(1, min(page_size or 10, MAX_SCAN_PAGE_SIZE))
    page = max(1, page or 1)
    resolved_ignored = (
        {normalize_order_key(k) for k in ignored_orders if normalize_order_key(k)}
        if ignored_orders is not None
        else set(list_ignored_orders().keys())
    )

    fetcher = MailFetcher(cfg, conn_factory=conn_factory)
    conn = None
    try:
        conn = fetcher._connect()
        typ, _ = conn.select("INBOX")
        if typ != "OK":
            raise RuntimeError(f"选择收件箱失败: {typ}")

        typ, data = conn.search(None, "FROM", SANGON_SENDER)
        if typ != "OK":
            typ, data = conn.search(None, "ALL")
        if typ != "OK":
            raise RuntimeError(f"搜索邮件失败: {typ}")

        seq_ids = data[0].split() if (data and data[0]) else []
        if not seq_ids:
            return {
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "total_pages": 1,
                "raw_total": 0,
                "unique_total": 0,
                "dedup_removed": 0,
                "skipped_known": 0,
                "new_count": 0,
                "created_count": 0,
                "existing_count": 0,
                "non_sequencing_count": 0,
                "ignored_count": 0,
                "scanned_count": 0,
                "created_dirs": [],
                "created_order_nos": [],
                "mails": [],
            }

        # 阶段 1：分批抓轻量头部（含 MESSAGE-ID）
        headers_by_seq: List[Dict[str, Any]] = []
        batch = getattr(cfg, "batch_size", 200)
        for rng in MailFetcher._chunk_ranges(seq_ids, batch):
            htyp, msg_data = conn.fetch(
                rng.decode("ascii"), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
            )
            if htyp != "OK" or not msg_data:
                continue
            for seq, head in fetcher._iter_messages(msg_data):
                sender = _parse_address(_decode_header(head.get("From")))
                if not _is_sangon_sender(sender):
                    continue
                subj = _decode_header(head.get("Subject"))
                date_str = _to_str(head.get("Date"))
                message_id = _to_str(head.get("Message-ID")).strip()
                m_order = _ORDER_NO_RE.search(subj)
                order_no = m_order.group(1) if m_order else ""
                date_prefix = _extract_date_prefix(date_str)
                headers_by_seq.append(
                    {
                        "seq": seq,
                        "sender": sender,
                        "subject": subj,
                        "date": date_str,
                        "date_prefix": date_prefix,
                        "message_id": message_id,
                        "order_no": order_no,
                        "duplicate_count": 1,
                    }
                )

        # 按序号倒序（最新邮件优先保留）
        headers_by_seq.sort(key=lambda x: x["seq"], reverse=True)
        raw_total = len(headers_by_seq)

        # 批内去重（按订单号 -> Message-ID -> 主题+日期归并）
        dedup_removed = 0
        if dedup:
            buckets: Dict[str, Dict[str, Any]] = {}
            ordered_items: List[Dict[str, Any]] = []
            for item in headers_by_seq:
                if item["order_no"]:
                    key = f"order:{item['order_no']}"
                elif item["message_id"]:
                    key = f"mid:{item['message_id']}"
                else:
                    key = f"subj:{item['subject']}|{item['date_prefix']}"

                if key in buckets:
                    buckets[key]["duplicate_count"] += 1
                    dedup_removed += 1
                    continue
                buckets[key] = item
                ordered_items.append(item)
        else:
            ordered_items = headers_by_seq

        existing_map = _scan_existing_orders(root_dir)
        index = SangonMailIndex(root_dir)
        index.load()

        # 把当前已存在的目录写入索引基线，确保后续清理能记为 cleaned
        for exist_no, exist_dir in existing_map.items():
            if not index.is_known(exist_no, ""):
                index.record(
                    order_no=exist_no,
                    message_id="",
                    dir_name=exist_dir,
                    subject="",
                    date_text="",
                    cleaned=False,
                )

        created_dirs: List[str] = []
        created_order_nos: List[str] = []
        skipped_known = 0
        existing_count = 0
        non_sequencing_count = 0
        ignored_count = 0
        created_count = 0
        new_count = 0
        processed_items: List[Dict[str, Any]] = []

        for item in ordered_items:
            order_no = item["order_no"]
            message_id = item["message_id"]
            date_prefix = item["date_prefix"]
            is_seq_mail = _is_sequencing_notice_subject(item["subject"], ignore_keywords=ignore_keywords)
            dir_name = existing_map.get(order_no) or (f"{date_prefix}_{order_no}" if (order_no and is_seq_mail) else "")

            in_disk = bool(order_no and order_no in existing_map)
            is_ignored = bool(order_no and normalize_order_key(order_no) in resolved_ignored)
            in_history = (not ignore_history) and index.is_known(order_no, message_id)

            if not is_seq_mail:
                dir_ready = False
                dedup_status = "non_sequencing"
                non_sequencing_count += 1
            elif is_ignored:
                dir_ready = in_disk
                dedup_status = "ignored"
                ignored_count += 1
            elif in_disk:
                dir_ready = True
                dedup_status = "existing"
                existing_count += 1
                if order_no:
                    index.record(
                        order_no=order_no,
                        message_id=message_id,
                        dir_name=dir_name,
                        subject=item["subject"],
                        date_text=item["date"],
                        cleaned=False,
                    )
            elif in_history:
                dir_ready = False
                dedup_status = "history_skipped"
                skipped_known += 1
            elif auto_create and order_no and root_dir.exists():
                order_path = root_dir / dir_name
                create_sangon_subdirs(order_path)
                existing_map[order_no] = dir_name
                created_dirs.append(dir_name)
                created_order_nos.append(order_no)
                dir_ready = True
                dedup_status = "created"
                created_count += 1
                new_count += 1
                index.record(
                    order_no=order_no,
                    message_id=message_id,
                    dir_name=dir_name,
                    subject=item["subject"],
                    date_text=item["date"],
                    cleaned=False,
                    created=True,
                )
            else:
                dir_ready = False
                dedup_status = "new"
                new_count += 1

            item_view = {
                "seq": item["seq"],
                "message_id": message_id,
                "subject": item["subject"],
                "date": item["date"],
                "order_no": order_no,
                "dir_name": dir_name,
                "is_sequencing": is_seq_mail,
                "ignored": is_ignored,
                "legacy_dir_exists": in_disk if not is_seq_mail else False,
                "cx_order_id": "",
                "download_url": "",
                "dir_ready": dir_ready,
                "dedup_status": dedup_status,
                "duplicate_count": item["duplicate_count"],
            }
            processed_items.append(item_view)

        # 过滤仅看新增邮件
        if only_new:
            filtered_items = [
                it for it in processed_items if it["dedup_status"] in ("new", "created")
            ]
        else:
            filtered_items = processed_items

        total = len(filtered_items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        start = (current_page - 1) * page_size
        page_items = filtered_items[start : start + page_size]

        # 阶段 2：仅对当前页中需要下载链接的邮件拉取全文（优先复用索引缓存）
        for item in page_items:
            if item["dedup_status"] in ("non_sequencing", "ignored"):
                continue
            cached = index.get_order(item["order_no"]) if item["order_no"] else {}
            if cached.get("download_url"):
                item["cx_order_id"] = cached.get("cx_order_id", "")
                item["download_url"] = cached.get("download_url", "")
                continue
            needs_body = (not item["order_no"]) or (
                bool(item["dir_name"]) and _order_needs_download(root_dir / item["dir_name"])
            )
            if not needs_body:
                continue
            full = fetcher._fetch_full(conn, item["seq"])
            if full is None:
                continue
            details = _extract_body_details(full)
            item["cx_order_id"] = details["cx_order_id"]
            item["download_url"] = details["download_url"]
            if not item["order_no"] and details["body_order_no"]:
                item["order_no"] = details["body_order_no"]
                item["dir_name"] = f"{_extract_date_prefix(item['date'])}_{item['order_no']}"
            if item["order_no"] and (item["dir_ready"] or item["dedup_status"] in ("existing", "created")):
                index.record(
                    order_no=item["order_no"],
                    message_id=item["message_id"],
                    dir_name=item["dir_name"],
                    subject=item["subject"],
                    date_text=item["date"],
                    cx_order_id=item["cx_order_id"],
                    download_url=item["download_url"],
                    cleaned=False,
                )

        index.save()

        return {
            "page": current_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "raw_total": raw_total,
            "unique_total": len(ordered_items),
            "dedup_removed": dedup_removed,
            "skipped_known": skipped_known,
            "new_count": new_count,
            "created_count": created_count,
            "existing_count": existing_count,
            "non_sequencing_count": non_sequencing_count,
            "ignored_count": ignored_count,
            "scanned_count": raw_total,
            "created_dirs": created_dirs,
            "created_order_nos": created_order_nos,
            "mails": page_items,
        }
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

