# -*- coding: utf-8 -*-
"""附件落地：时间戳目录 + manifest.json + 同批去重 + 跨次运行去重。

跨次去重（确认"不会重复收到之前的内容"）：
- 持久化处理索引 <download_dir>/processed_index.json，键为附件内容 SHA256；
- 每次 save 前加载索引，已处理过的附件直接跳过（skipped_processed）；
- 内容级判重：同一拼接 fasta 再次到达时，即使文件名/批次不同也会被识别跳过。
"""
import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fetcher import MessageSummary

logger = logging.getLogger("mail_download.downloader")

INDEX_NAME = "processed_index.json"


class ProcessedIndex:
    """已处理附件的内容指纹索引（持久化到 download_dir）。"""

    INDEX_NAME = "processed_index.json"

    def __init__(self, download_dir: Path):
        self.download_dir = Path(download_dir)
        self._data: Dict[str, Dict] = {}
        self._loaded = False

    @property
    def index_path(self) -> Path:
        return self.download_dir / self.INDEX_NAME

    def load(self) -> None:
        """加载索引；缺失=空索引，损坏=备份后重建（不阻塞下载）。"""
        if self._loaded:
            return
        self._loaded = True
        path = self.index_path
        if not path.exists():
            self._data = {}
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._data = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("处理索引损坏，已重建: %s", e)
            backup = path.with_suffix(".corrupt.bak")
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
            self._data = {}

    @staticmethod
    def fingerprint(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def contains(self, payload: bytes) -> bool:
        self.load()
        return self.fingerprint(payload) in self._data

    def record(self, summary: MessageSummary, name: str, payload: bytes,
               batch_dir: Path, path: str) -> None:
        self.load()
        fp = self.fingerprint(payload)
        msg_id = ""
        if getattr(summary, "raw", None) is not None:
            msg_id = str(summary.raw.get("Message-ID", "") or "").strip()
        self._data[fp] = {
            "sha256": fp,
            "message_id": msg_id,
            "filename": name,
            "first_seen": datetime.now().isoformat(timespec="seconds"),
            "batch": Path(batch_dir).name,
            "path": path,
            "sender": summary.sender,
            "subject": summary.subject,
            "mail_date": summary.date_text,
        }

    def has_message_id(self, message_id: str) -> bool:
        """判断邮件 Message-ID 是否已在处理索引中出现过。"""
        mid = (message_id or "").strip()
        if not mid:
            return False
        self.load()
        return any(
            isinstance(meta, dict) and meta.get("message_id") == mid
            for meta in self._data.values()
        )

    def save(self) -> None:
        self.load()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def count(self) -> int:
        self.load()
        return len(self._data)

    def entries(self) -> Dict[str, Dict[str, Any]]:
        """返回只读副本：sha256 -> 元信息。"""
        self.load()
        return {
            sha: dict(meta)
            for sha, meta in self._data.items()
            if isinstance(meta, dict)
        }


class AttachmentSaver:
    """把筛选命中的邮件附件写入 <download_dir>/up_<时间戳>_<seq>/。"""

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.index = ProcessedIndex(download_dir)

    def save(self, summaries: List[MessageSummary]) -> Dict[str, Any]:
        """保存全部命中邮件的附件。返回汇总统计（含跨次去重 skipped_processed）。"""
        self.index.load()
        saved_files: List[Dict[str, Any]] = []
        skipped_duplicates = 0
        skipped_processed = 0
        total_bytes = 0

        for summary in summaries:
            atts = getattr(summary, "_matched_attachments", [])
            if not atts:
                continue
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_dir = self.download_dir / f"up_{stamp}_{summary.seq:06d}"
            batch_dir.mkdir(parents=True, exist_ok=True)

            mail_meta = {
                "seq": summary.seq,
                "uid": summary.uid,
                "date": summary.date_text,
                "sender": summary.sender,
                "subject": summary.subject,
            }
            attachments_meta = []
            for name, payload in atts:
                digest = hashlib.sha256(payload).hexdigest()
                if self.index.contains(payload):
                    skipped_processed += 1
                    continue
                target = batch_dir / name
                if target.exists():
                    # 同批同名文件已存在：内容相同=重复；内容不同=写不冲突文件名
                    if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                        skipped_duplicates += 1
                        continue
                    stem, suffix = target.stem, target.suffix
                    alt, k = target, 2
                    while alt.exists():
                        alt = batch_dir / f"{stem}_{k}{suffix}"
                        k += 1
                    target = alt
                target.write_bytes(payload)
                total_bytes += len(payload)
                path_str = str(target)
                attachments_meta.append({
                    "filename": name,
                    "size_bytes": len(payload),
                    "sha256": digest,
                    "path": path_str,
                })
                saved_files.append({
                    "mail": mail_meta,
                    "filename": name,
                    "path": path_str,
                    "size_bytes": len(payload),
                    "sha256": digest,
                })
                self.index.record(summary, name, payload, batch_dir, path_str)

            if attachments_meta:
                manifest = {
                    "batch": batch_dir.name,
                    "download_time": datetime.now().isoformat(timespec="seconds"),
                    "mail": mail_meta,
                    "attachments": attachments_meta,
                }
                (batch_dir / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                # 本批全部被跨次去重跳过：清掉空目录，保持目录整洁
                try:
                    batch_dir.rmdir()
                except OSError:
                    pass

            self.index.save()

        return {
            "saved_files": saved_files,
            "count": len(saved_files),
            "total_bytes": total_bytes,
            "skipped_duplicates": skipped_duplicates,
            "skipped_processed": skipped_processed,
            "download_dir": str(self.download_dir),
        }

    def save_one(self, name: str, payload: bytes, batch_dir: Path) -> Path:
        """单文件保存（供测试/工具使用）。"""
        batch_dir.mkdir(parents=True, exist_ok=True)
        target = batch_dir / name
        target.write_bytes(payload)
        return target
