# -*- coding: utf-8 -*-
"""
邮件收件箱去重预览与分页浏览服务模块
职责：
1. 按当前发件人白名单/主题关键词/天数窗口检索 IMAP 收件箱；
2. 结合 Message-ID 与收件时间执行批内邮件级去重，合并重复投递；
3. 对接 ProcessedIndex（SHA256 与 Message-ID），标注每封邮件与附件的去重状态；
4. 支持服务端分页切片，仅对当前页拉取全文及附件指纹计算（或 only_new 模式下精准过滤未处理邮件）。
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from ....mail_download.downloader import ProcessedIndex
from ....mail_download.fetcher import (
    MailFetcher,
    _HEADER_FIELDS,
    _attachment_parts,
    _decode_header,
    _extension_ok,
    _parse_address,
    _parse_date,
    _sender_allowed,
    _subject_matches,
    _to_str,
)

logger = logging.getLogger("api.other_tools.mail_inbox_browser")


def _inspect_full_attachments(
    fetcher: MailFetcher,
    conn: Any,
    item: Dict[str, Any],
    known_sha256s: set[str],
    cfg: Any,
) -> Dict[str, Any]:
    """抓取单封邮件全文并检查匹配附件与 SHA256 去重状态。"""
    full = fetcher._fetch_full(conn, item["seq"])
    attachments_info: List[Dict[str, Any]] = []
    new_count = 0
    processed_count = 0

    if full is not None:
        if not item["message_id"]:
            item["message_id"] = _to_str(full.get("Message-ID")).strip()
        parts = _attachment_parts(full)
        max_bytes = getattr(cfg, "max_attach_size_mb", 200) * 1024 * 1024
        for name, payload in parts:
            if not _extension_ok(name, cfg.attachment_exts):
                continue
            if len(payload) > max_bytes:
                continue
            sha = hashlib.sha256(payload).hexdigest()
            already = sha in known_sha256s
            if already:
                processed_count += 1
            else:
                new_count += 1
            attachments_info.append(
                {
                    "filename": name,
                    "size_bytes": len(payload),
                    "sha256": sha,
                    "already_processed": already,
                }
            )

    if not attachments_info:
        status = "no_attachment"
    elif new_count > 0 and processed_count > 0:
        status = "partial"
    elif new_count > 0:
        status = "new"
    else:
        status = "processed"

    return {
        **item,
        "status": status,
        "new_attachment_count": new_count,
        "processed_attachment_count": processed_count,
        "attachments": attachments_info,
    }


def list_whitelist_mails(
    cfg: Any,
    *,
    page: int = 1,
    page_size: int = 10,
    since_days: Optional[int] = None,
    dedup: bool = True,
    only_new: bool = False,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """
    浏览收件箱内符合白名单条件的邮件，支持批内邮件级去重、仅看新邮件与服务端翻页。
    """
    page_size = max(1, min(page_size or 10, 50))
    page = max(1, page or 1)
    effective_days = since_days if since_days is not None else getattr(cfg, "since_days", 7)
    since_dt = datetime.now().astimezone() - timedelta(days=effective_days)

    index = ProcessedIndex(cfg.resolved_download_dir)
    index.load()
    idx_entries = index.entries()
    known_sha256s = set(idx_entries.keys())
    known_message_ids = {
        str(meta.get("message_id", "")).strip()
        for meta in idx_entries.values()
        if meta.get("message_id")
    }

    fetcher = MailFetcher(cfg, conn_factory=conn_factory)
    conn = None
    try:
        conn = fetcher._connect()
        typ, _ = conn.select("INBOX")
        if typ != "OK":
            raise RuntimeError(f"选择收件箱失败: {typ}")

        criteria = fetcher._build_search_criteria(since_dt)
        typ, data = conn.search(None, criteria)
        if typ != "OK" and criteria != "ALL":
            typ, data = conn.search(None, "ALL")
        if typ != "OK":
            raise RuntimeError(f"搜索邮件失败: {typ}")

        seq_ids = data[0].split() if (data and data[0]) else []
        if not seq_ids:
            return {
                "scanned": 0,
                "raw_total": 0,
                "unique_total": 0,
                "dedup_removed": 0,
                "processed_skipped": 0,
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "total_pages": 1,
                "items": [],
            }

        # 阶段 1：轻量头部初筛
        matched_headers: List[Dict[str, Any]] = []
        batch = getattr(cfg, "batch_size", 200)
        for rng in MailFetcher._chunk_ranges(seq_ids, batch):
            htyp, msg_data = conn.fetch(rng.decode("ascii"), f"(BODY.PEEK[HEADER.FIELDS {_HEADER_FIELDS}])")
            if htyp != "OK" or not msg_data:
                continue
            for seq, head in fetcher._iter_messages(msg_data):
                sender = _parse_address(_decode_header(head.get("From")))
                subject = _decode_header(head.get("Subject"))
                date = _parse_date(head.get("Date"))
                if date is not None and date < since_dt:
                    continue
                if not _sender_allowed(sender, cfg.sender_whitelist):
                    continue
                if not _subject_matches(subject, cfg.subject_keywords):
                    continue
                message_id = _to_str(head.get("Message-ID")).strip()
                date_iso = date.isoformat(timespec="seconds") if date else _to_str(head.get("Date"))
                matched_headers.append(
                    {
                        "seq": seq,
                        "message_id": message_id,
                        "sender": sender,
                        "subject": subject,
                        "date": date_iso,
                        "duplicate_count": 1,
                    }
                )

        # 按序号倒序（最新优先）
        matched_headers.sort(key=lambda x: x["seq"], reverse=True)
        raw_total = len(matched_headers)

        # 批内邮件级去重
        dedup_removed = 0
        if dedup:
            buckets: Dict[str, Dict[str, Any]] = {}
            unique_headers: List[Dict[str, Any]] = []
            for item in matched_headers:
                if item["message_id"]:
                    key = f"mid:{item['message_id']}"
                else:
                    key = f"meta:{item['sender']}|{item['subject'].strip()}|{item['date'][:19]}"
                if key in buckets:
                    buckets[key]["duplicate_count"] += 1
                    dedup_removed += 1
                    continue
                buckets[key] = item
                unique_headers.append(item)
        else:
            unique_headers = matched_headers

        processed_skipped = 0
        if only_new:
            new_only_items: List[Dict[str, Any]] = []
            for item in unique_headers:
                if item["message_id"] and item["message_id"] in known_message_ids:
                    processed_skipped += 1
                    continue
                inspected = _inspect_full_attachments(fetcher, conn, item, known_sha256s, cfg)
                if inspected["status"] in ("new", "partial"):
                    new_only_items.append(inspected)
                else:
                    processed_skipped += 1

            total = len(new_only_items)
            total_pages = max(1, (total + page_size - 1) // page_size)
            current_page = min(page, total_pages)
            start = (current_page - 1) * page_size
            page_items = new_only_items[start : start + page_size]
        else:
            # 普通模式先计数后切片，仅对当前页拉取全文检查附件 SHA256
            total = len(unique_headers)
            total_pages = max(1, (total + page_size - 1) // page_size)
            current_page = min(page, total_pages)
            start = (current_page - 1) * page_size
            slice_headers = unique_headers[start : start + page_size]
            page_items = []
            for item in slice_headers:
                inspected = _inspect_full_attachments(fetcher, conn, item, known_sha256s, cfg)
                if inspected["status"] == "processed":
                    processed_skipped += 1
                page_items.append(inspected)

        return {
            "scanned": len(seq_ids),
            "raw_total": raw_total,
            "unique_total": len(unique_headers),
            "dedup_removed": dedup_removed,
            "processed_skipped": processed_skipped,
            "page": current_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "items": page_items,
        }
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
