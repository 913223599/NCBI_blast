# -*- coding: utf-8 -*-
"""
测试其他功能工作台后端 API 与服务层
验证：
1. 邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 概览接口（含完整路径与授权码掩码信息）
2. 生工 16S 测序结果自动化 BLAST 与导出流程 概览与结果读取接口
3. 目录修改后的自动迁移与 JSON 路径修正 (dir_migrator.py)
4. 邮箱 Key 读写与掩码 (secret_store.py)
5. 邮件流水线与生工 16S 历史数据清理 (history_cleaner.py)
6. 严禁 Emoji 与强制 UTF-8 合规性检查
"""

import asyncio
import email
import email.utils
import json
import tempfile
from pathlib import Path

from src.backend.routes.other_tools import (
    get_mail_pipeline_overview,
    get_sangon_16s_overview,
    get_sangon_order_results,
)
from src.backend.services.other_tools.dir_migrator import migrate_directory
from src.backend.services.other_tools.history_cleaner import (
    cleanup_mail_history,
    cleanup_sangon_history,
)
from src.backend.services.other_tools.mail_inbox_browser import list_whitelist_mails
from src.backend.services.other_tools.sangon_mail_scanner import (
    init_sangon_order_dir,
    scan_sangon_mails,
)
from src.backend.services.other_tools.sangon_zip_importer import (
    import_order_zips_from_downloads,
    scan_downloads_for_sangon_zips,
)
from src.backend.services.other_tools.secret_store import (
    mask_secret,
    read_secret,
    write_secret,
)
from src.mail_download.config import MailConfig
from src.mail_download.downloader import AttachmentSaver
from src.mail_download.fetcher import MailFetcher


def test_mail_pipeline_overview_structure():
    """验证邮件自动化流水线概览接口返回完整绝对路径、授权码状态与批次统计"""
    res = asyncio.run(get_mail_pipeline_overview())
    assert res["status"] == "success"
    assert "config" in res
    assert "auth" in res
    assert "imap_ready" in res["auth"]
    assert "imap_file" in res["auth"]
    assert Path(res["resolved_download_dir"]).is_absolute()
    assert Path(res["resolved_send_dir"]).is_absolute()
    assert isinstance(res["batches"], list)
    assert isinstance(res["outbound_packages"], list)
    assert isinstance(res["docx_reports"], list)


def test_sangon_16s_overview_and_order_results():
    """验证生工 16S 自动化 BLAST 流水线概览接口与订单 CSV 读取"""
    res = asyncio.run(get_sangon_16s_overview())
    assert res["status"] == "success"
    assert "sangon_root" in res
    assert Path(res["sangon_root"]).is_absolute()
    assert "db_16s_ready" in res
    assert isinstance(res["orders"], list)

    orders_with_csv = [o for o in res["orders"] if o.get("has_result_csv")]
    if orders_with_csv:
        first_order = orders_with_csv[0]["dir_name"]
        detail = asyncio.run(get_sangon_order_results(first_order))
        assert detail["status"] == "success"
        assert len(detail["rows"]) > 0
        assert len(detail["headers"]) == 11


def test_directory_migration_and_json_rewrite():
    """验证修改目录后旧目录内容自动迁移至新目录并修正 JSON 内的旧绝对路径"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_dir = root / "old_downloads"
        new_dir = root / "new_downloads"
        batch_dir = old_dir / "up_20261111_000001"
        batch_dir.mkdir(parents=True)

        fasta_file = batch_dir / "sample.fasta"
        fasta_file.write_text(">seq1\nATGC\n", encoding="utf-8")

        idx_file = old_dir / "processed_index.json"
        idx_file.write_text(
            json.dumps(
                {
                    "abc123": {
                        "sha256": "abc123",
                        "path": str(fasta_file.resolve()),
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        mig = migrate_directory(old_dir, new_dir)
        assert mig["migrated"] is True
        assert mig["moved_count"] == 2
        assert mig["json_rewritten"] == 1
        assert not old_dir.exists()
        assert (new_dir / "up_20261111_000001" / "sample.fasta").exists()

        rewritten = json.loads((new_dir / "processed_index.json").read_text(encoding="utf-8"))
        assert rewritten["abc123"]["path"] == str((new_dir.resolve() / "up_20261111_000001" / "sample.fasta"))


def test_secret_store_read_write_mask():
    """验证邮箱 Key 的写入、读取、掩码与清空删除"""
    with tempfile.TemporaryDirectory() as tmp:
        key_path = Path(tmp) / ".mail_auth"
        assert read_secret(key_path) is None
        write_secret(key_path, "abcdef123456")
        val = read_secret(key_path)
        assert val == "abcdef123456"
        assert mask_secret(val) == "ab********56"

        write_secret(key_path, "")
        assert not key_path.exists()
        assert read_secret(key_path) is None


def test_mail_and_sangon_history_cleanup():
    """验证邮件流水线与生工 16S 历史数据按需清理"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dl = root / "dl"
        send = root / "send"
        anno = root / "anno"
        dl.mkdir()
        send.mkdir()
        anno.mkdir()

        # 构造邮件批次与回传产物
        b1 = dl / "up_20261111_01"
        b1.mkdir()
        (b1 / "a.fasta").write_text(">a\nAA\n", encoding="utf-8")
        (dl / "processed_index.json").write_text(
            json.dumps({"sha1": {"batch": "up_20261111_01", "first_seen": "2026-11-11T10:00:00"}}),
            encoding="utf-8",
        )
        (send / "TASK1.zip").write_bytes(b"PK\x03\x04test")
        (send / "TASK1.manifest.json").write_text(
            json.dumps({"task_id": "TASK1", "zip": "TASK1.zip"}), encoding="utf-8"
        )
        (anno / "TASK1").mkdir()
        (anno / "TASK1" / "inter.txt").write_text("temp", encoding="utf-8")

        res = cleanup_mail_history(dl, send, anno, targets=["batches", "outbound", "annotations"])
        assert res["removed_count"] >= 3
        assert not b1.exists()
        assert not (send / "TASK1.zip").exists()
        assert not (anno / "TASK1").exists()
        # 未勾选 index 时去重索引保留
        idx_after = json.loads((dl / "processed_index.json").read_text(encoding="utf-8"))
        assert "sha1" in idx_after

        # 勾选 index 时清理去重记录
        res2 = cleanup_mail_history(dl, send, anno, targets=["index"])
        assert res2["index_removed"] == 1

        # 构造生工 16S 订单清理测试
        sangon_root = root / "sangon"
        blast_root = root / "blast"
        order_dir = sangon_root / "20261111_1234567890"
        (order_dir / "原始压缩包").mkdir(parents=True)
        (order_dir / "原始数据").mkdir(parents=True)
        (order_dir / "BLAST结果").mkdir(parents=True)
        (order_dir / "原始压缩包" / "raw.zip").write_bytes(b"zip")
        (order_dir / "原始数据" / "seq.1.fasta").write_text(">s\nAA\n", encoding="utf-8")
        (order_dir / "BLAST结果" / "16S鉴定结果.csv").write_text("col1,col2\n", encoding="utf-8")
        (blast_root / "20261111_1234567890_16s").mkdir(parents=True)

        s_res = cleanup_sangon_history(
            sangon_root,
            blast_root,
            ["20261111_1234567890"],
            targets=["raw_extracted", "blast_cache", "result_csv"],
        )
        assert s_res["removed_count"] >= 3
        assert (order_dir / "原始压缩包" / "raw.zip").exists()
        assert not (order_dir / "原始数据" / "seq.1.fasta").exists()
        assert not (order_dir / "BLAST结果" / "16S鉴定结果.csv").exists()
        assert not (blast_root / "20261111_1234567890_16s").exists()


def _make_mime_mail(
    sender: str,
    subject: str,
    *,
    body_html: str = "",
    message_id: str = "",
    date_str: str = "Wed, 11 Nov 2026 10:00:00 +0800",
    attachments=None,
) -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = date_str
    if message_id:
        msg["Message-ID"] = message_id
    if body_html:
        msg.set_content(body_html, subtype="html", charset="utf-8")
    else:
        msg.set_content("ok", subtype="plain", charset="utf-8")
    for name, payload in (attachments or []):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return msg.as_bytes()


class _FakeIMAPForOtherTools:
    """支持 HEADER.FIELDS (含 Message-ID) 与 BODY.PEEK[] 的轻量 FakeIMAP。"""

    def __init__(self, messages: list[bytes]):
        self._messages = messages
        self.fetch_calls: list[str] = []
        self.logged_out = False

    def select(self, mailbox: str):
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        ids = b" ".join(str(i).encode() for i in range(1, len(self._messages) + 1))
        return ("OK", [ids])

    def fetch(self, seqset, parts):
        parts_str = parts.decode() if isinstance(parts, bytes) else str(parts)
        self.fetch_calls.append(parts_str)
        s = seqset.decode() if isinstance(seqset, bytes) else str(seqset)
        ids = []
        for token in s.replace(",", " ").split():
            if ":" in token:
                a, b = token.split(":")
                ids.extend(range(int(a), int(b) + 1))
            elif token.isdigit():
                ids.append(int(token))
        out = []
        for i in ids:
            if not (1 <= i <= len(self._messages)):
                continue
            raw = self._messages[i - 1]
            seq_info = f"{i} (UID {10000 + i})".encode()
            if "HEADER.FIELDS" in parts_str:
                msg = email.message_from_bytes(raw)
                header = (
                    f"From: {msg.get('From', '')}\r\n"
                    f"Subject: {msg.get('Subject', '')}\r\n"
                    f"Date: {msg.get('Date', '')}\r\n"
                    f"Message-ID: {msg.get('Message-ID', '')}\r\n"
                ).encode("utf-8")
                out.append(((seq_info, header), b")"))
            else:
                out.append((seq_info, raw, b")"))
        return ("OK", out)

    def logout(self):
        self.logged_out = True


def test_sangon_scan_dedup_history_and_pagination():
    """验证生工 16S 邮件扫描的批内去重、服务端分页、历史清理防重建与手动建目录"""
    mails = [
        _make_mime_mail(
            "spam@other.com",
            "无关订单 9999999999",
            body_html="cxOrderID=SKIP99",
            message_id="<spam@other>",
        ),
        _make_mime_mail(
            "info1@sangon.com",
            "测序结果通知 2140610001",
            body_html='<a href="http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID=CX001">dl</a>',
            message_id="<m1@sangon.com>",
            date_str="Mon, 02 Nov 2026 09:00:00 +0800",
        ),
        _make_mime_mail(
            "info1@sangon.com",
            "测序结果通知 2140610002",
            body_html="cxOrderID=CX002",
            message_id="<m2@sangon.com>",
            date_str="Tue, 03 Nov 2026 09:00:00 +0800",
        ),
        _make_mime_mail(
            "info1@sangon.com",
            "测序结果通知 2140610003",
            body_html="cxOrderID=CX003",
            message_id="<m3@sangon.com>",
            date_str="Wed, 04 Nov 2026 09:00:00 +0800",
        ),
        # 订单 2140610003 的第 2 封重复通知（不同 Message-ID，同订单号）
        _make_mime_mail(
            "info1@sangon.com",
            "测序结果补充通知 2140610003",
            body_html="cxOrderID=CX003_NEW",
            message_id="<m3-dup@sangon.com>",
            date_str="Thu, 05 Nov 2026 09:00:00 +0800",
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "sangon"
        root.mkdir()
        blast_root = Path(tmp) / "blast"
        cfg = MailConfig(account="user@qq.com")

        fake1 = _FakeIMAPForOtherTools(mails)
        res_p1 = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=2,
            dedup=True,
            auto_create=True,
            conn_factory=lambda: fake1,
        )
        assert res_p1["raw_total"] == 4
        assert res_p1["unique_total"] == 3
        assert res_p1["dedup_removed"] == 1
        assert res_p1["total"] == 3
        assert res_p1["total_pages"] == 2
        assert len(res_p1["mails"]) == 2
        # 第 1 条应为最新的 2140610003（合并了 2 封）
        assert res_p1["mails"][0]["order_no"] == "2140610003"
        assert res_p1["mails"][0]["duplicate_count"] == 2
        assert res_p1["mails"][0]["cx_order_id"] == "CX003_NEW"
        assert res_p1["mails"][0]["dedup_status"] == "created"
        # 阶段 2 应只针对第 1 页这 2 封抓全文
        full_calls = [c for c in fake1.fetch_calls if "BODY.PEEK[]" in c]
        assert len(full_calls) == 2

        # 翻到第 2 页
        fake2 = _FakeIMAPForOtherTools(mails)
        res_p2 = scan_sangon_mails(
            root,
            cfg,
            page=2,
            page_size=2,
            dedup=True,
            auto_create=True,
            conn_factory=lambda: fake2,
        )
        assert res_p2["page"] == 2
        assert len(res_p2["mails"]) == 1
        assert res_p2["mails"][0]["order_no"] == "2140610001"
        assert res_p2["mails"][0]["cx_order_id"] == "CX001"

        # 清理掉 20261102_2140610001 的整个订单目录 -> 再扫应标记为 history_skipped 且不再自动建空目录
        cleanup_sangon_history(root, blast_root, ["20261102_2140610001"], ["order_dir"])
        assert not (root / "20261102_2140610001").exists()

        res_after_clean = scan_sangon_mails(
            root,
            cfg,
            page=2,
            page_size=2,
            dedup=True,
            auto_create=True,
            ignore_history=False,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert res_after_clean["mails"][0]["dedup_status"] == "history_skipped"
        assert not (root / "20261102_2140610001").exists()

        # 手动建目录可按需补建
        manual = init_sangon_order_dir(root, "20261102_2140610001", order_no="2140610001")
        assert manual["created"] is True
        assert (root / "20261102_2140610001" / "原始压缩包").is_dir()

        # 删除目录后再同时清掉 scan_index，下次扫描即可重建
        cleanup_sangon_history(root, blast_root, ["20261102_2140610001"], ["order_dir", "scan_index"])
        assert not (root / "20261102_2140610001").exists()
        res_recreate = scan_sangon_mails(
            root,
            cfg,
            page=2,
            page_size=2,
            dedup=True,
            auto_create=True,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert res_recreate["mails"][0]["dedup_status"] == "created"
        assert (root / "20261102_2140610001").exists()

        # only_new=True 在已全部存在时返回 0 条
        res_only_new = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=10,
            dedup=True,
            only_new=True,
            auto_create=False,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert res_only_new["total"] == 0

        # 关闭去重时展示全部 4 封生工邮件
        res_no_dedup = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=10,
            dedup=False,
            auto_create=False,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert res_no_dedup["total"] == 4


def test_mail_inbox_browser_and_fetcher_dedup():
    """验证邮件收件箱浏览器与 MailFetcher 的 Message-ID 去重、only_new 过滤和服务端翻页"""
    fasta1 = ">seq1\nATGC\n"
    fasta2 = ">seq2\nGGGG\n"
    fasta3 = ">seq3\nCCCC\n"
    mails = [
        _make_mime_mail(
            "yssw_service@163.com",
            "拼接批次 A",
            message_id="<dup-msg@163.com>",
            date_str="Wed, 11 Nov 2026 08:00:00 +0800",
            attachments=[("a.fasta", fasta1)],
        ),
        # 同 Message-ID 重复投递
        _make_mime_mail(
            "yssw_service@163.com",
            "拼接批次 A",
            message_id="<dup-msg@163.com>",
            date_str="Wed, 11 Nov 2026 08:01:00 +0800",
            attachments=[("a.fasta", fasta1)],
        ),
        _make_mime_mail(
            "yssw_service@163.com",
            "拼接批次 B",
            message_id="<msg-b@163.com>",
            date_str="Wed, 11 Nov 2026 09:00:00 +0800",
            attachments=[("b.fasta", fasta2)],
        ),
        _make_mime_mail(
            "yssw_service@163.com",
            "拼接批次 C",
            message_id="<msg-c@163.com>",
            date_str="Wed, 11 Nov 2026 10:00:00 +0800",
            attachments=[("c.fasta", fasta3)],
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        cfg = MailConfig(
            sender_whitelist=["yssw_service@163.com"],
            since_days=30,
            download_dir=tmp,
        )

        # 验证 MailFetcher 的 Message-ID 同批去重
        f_res = MailFetcher(cfg, conn_factory=lambda: _FakeIMAPForOtherTools(mails)).fetch()
        assert f_res.skipped_dup_mails == 1
        assert len(f_res.matched) == 3

        # 浏览器第 1 页（dedup=True, page_size=2）
        p1 = list_whitelist_mails(
            cfg,
            page=1,
            page_size=2,
            dedup=True,
            only_new=False,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert p1["raw_total"] == 4
        assert p1["unique_total"] == 3
        assert p1["dedup_removed"] == 1
        assert p1["total_pages"] == 2
        assert [it["subject"] for it in p1["items"]] == ["拼接批次 C", "拼接批次 B"]

        # 保存其中最新的 1 封（批次 C），验证 ProcessedIndex 记录了 Message-ID
        saver = AttachmentSaver(Path(tmp))
        saver.save([m for m in f_res.matched if m.subject == "拼接批次 C"])
        assert saver.index.has_message_id("<msg-c@163.com>")

        # 开启 only_new=True 后应自动过滤批次 C，仅剩 B 和 A
        only_new_res = list_whitelist_mails(
            cfg,
            page=1,
            page_size=10,
            dedup=True,
            only_new=True,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        assert only_new_res["total"] == 2
        assert only_new_res["processed_skipped"] == 1
        assert [it["subject"] for it in only_new_res["items"]] == ["拼接批次 B", "拼接批次 A"]


def test_other_tools_routes_pagination_and_init_order(monkeypatch):
    """验证新增路由接口的参数兼容、安全路径校验及响应结构"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "sangon"
        root.mkdir()

        # 1. init_order 安全校验与目录建立
        bad = client.post("/other_tools/sangon_16s/init_order", json={"dir_name": "../bad", "sangon_root": str(root)})
        assert bad.status_code == 400

        ok = client.post(
            "/other_tools/sangon_16s/init_order",
            json={"dir_name": "20261111_2140699999", "order_no": "2140699999", "sangon_root": str(root)},
        )
        assert ok.status_code == 200
        assert (root / "20261111_2140699999" / "原始压缩包").is_dir()

        # 2. scan_mail 支持空请求体与分页去重参数
        captured: list[dict] = []

        def fake_scan(root_path, cfg, **kwargs):
            captured.append(kwargs)
            return {
                "page": kwargs.get("page", 1),
                "page_size": kwargs.get("page_size", 10),
                "total": 1,
                "total_pages": 1,
                "raw_total": 2,
                "unique_total": 1,
                "dedup_removed": 1,
                "skipped_known": 0,
                "scanned_count": 2,
                "created_dirs": [],
                "mails": [],
            }

        monkeypatch.setattr(ot_routes, "load_config", lambda *a, **kw: MailConfig(account="user@qq.com"))
        monkeypatch.setattr(ot_routes, "scan_sangon_mails", fake_scan)

        r_empty = client.post("/other_tools/sangon_16s/scan_mail")
        assert r_empty.status_code == 200
        assert r_empty.json()["dedup_removed"] == 1
        assert captured[-1]["page"] == 1
        assert captured[-1]["dedup"] is True

        r_paged = client.post(
            "/other_tools/sangon_16s/scan_mail",
            json={"page": 2, "page_size": 5, "dedup": False, "only_new": True, "auto_create": False},
        )
        assert r_paged.status_code == 200
        assert captured[-1]["page"] == 2
        assert captured[-1]["page_size"] == 5
        assert captured[-1]["dedup"] is False
        assert captured[-1]["only_new"] is True
        assert captured[-1]["auto_create"] is False

        # 3. list_mails 分页去重路由
        def fake_list(cfg, **kwargs):
            return {
                "scanned": 10,
                "raw_total": 5,
                "unique_total": 3,
                "dedup_removed": 2,
                "processed_skipped": 1,
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
                "total": 3,
                "total_pages": 1,
                "items": [],
            }

        monkeypatch.setattr(ot_routes, "list_whitelist_mails", fake_list)
        r_list = client.post(
            "/other_tools/mail_pipeline/list_mails",
            json={"page": 1, "page_size": 20, "dedup": True, "only_new": True},
        )
        assert r_list.status_code == 200
        assert r_list.json()["dedup_removed"] == 2


def test_sangon_scan_excludes_non_sequencing_shipping_mails():
    """验证生工物流发货通知（如订单已发货）标记为 non_sequencing 且不自动建空目录"""
    mails = [
        _make_mime_mail(
            "info1@sangon.com",
            "您的生工订单（1011709710）已发货，欢迎点击查看",
            body_html="已发出",
            message_id="<ship@sangon.com>",
        ),
        _make_mime_mail(
            "info1@sangon.com",
            "生工生物测序结果通知 2140698888",
            body_html="cxOrderID=CX98888",
            message_id="<seq@sangon.com>",
        ),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "sangon"
        root.mkdir()
        cfg = MailConfig(account="user@qq.com")
        res = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=10,
            dedup=True,
            auto_create=True,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        by_order = {m["order_no"]: m for m in res["mails"]}
        assert by_order["1011709710"]["dedup_status"] == "non_sequencing"
        assert by_order["1011709710"]["dir_ready"] is False
        assert not any("1011709710" in p.name for p in root.iterdir())
        assert by_order["2140698888"]["dedup_status"] == "created"
        assert by_order["2140698888"]["dir_ready"] is True


def test_sangon_zip_importer_scan_and_archive():
    """验证浏览器下载目录识别、完整性过滤、最新包优先及安全拷贝归档"""
    import os
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "sangon"
        dl = Path(tmp) / "downloads"
        root.mkdir()
        dl.mkdir()

        order_dir = root / "20261111_2140608938"
        (order_dir / "原始压缩包").mkdir(parents=True)

        # 未完成下载 / 损坏包 / 非测序包应被忽略
        (dl / "吴晨_2140608938_测序结果.zip.crdownload").write_bytes(b"partial")
        (dl / "bad_2140608938_测序结果.zip").write_bytes(b"not-a-zip")
        other_zip = dl / "other_1234567890_invoice.zip"
        with zipfile.ZipFile(other_zip, "w") as zf:
            zf.writestr("invoice.pdf", b"%PDF-1.4")

        # 同订单旧包与新包：应优先选取更新的 zip
        old_zip = dl / "吴晨_2140608938_测序结果.zip"
        with zipfile.ZipFile(old_zip, "w") as zf:
            zf.writestr("s1_-1.1.fasta", ">1\nATGC\n")
        new_zip = dl / "吴晨_2140608938_测序结果(2).zip"
        with zipfile.ZipFile(new_zip, "w") as zf:
            zf.writestr("s1_-1.1.fasta", ">1\nATGC\n")
            zf.writestr("s2_-2.1.fasta", ">2\nGGGG\n")
        os.utime(old_zip, (1000, 1000))
        os.utime(new_zip, (2000, 2000))

        # 额外未建目录的测序包
        uncreated_zip = dl / "张三_2140601771_测序结果.zip"
        with zipfile.ZipFile(uncreated_zip, "w") as zf:
            zf.writestr("x.ab1", b"ABIF")

        scanned = scan_downloads_for_sangon_zips(dl)
        assert len(scanned) == 3
        assert scanned[0]["order_no"] in ("2140601771", "2140608938")

        # 1. 仅匹配已有订单
        imp1 = import_order_zips_from_downloads(root, dl, auto_create_order=False)
        assert imp1["imported_count"] == 1
        assert imp1["imported"][0]["zip_name"] == new_zip.name
        assert (order_dir / "原始压缩包" / new_zip.name).exists()
        # 保留 Downloads 原文件
        assert new_zip.exists()

        # 2. 再次导入跳过同大小重复包；开启 auto_create_order 时自动建 2140601771 目录
        imp2 = import_order_zips_from_downloads(root, dl, auto_create_order=True)
        assert imp2["skipped_existing"] == 1
        assert imp2["imported_count"] == 1
        assert len(imp2["created_dirs"]) == 1
        assert any(p.name.endswith("_2140601771") and (p / "原始压缩包" / uncreated_zip.name).exists() for p in root.iterdir())


def test_sangon_csv_natural_order_and_force_reblast(monkeypatch):
    """验证 16S CSV 导出按样本号数字排序，以及 force_reblast 触发旧缓存与任务记录清理"""
    import src.backend.routes.other_tools as ot_routes
    from src.workbench.models.tool_config import ToolConfig

    with tempfile.TemporaryDirectory() as tmp:
        fake_root = Path(tmp)
        reports_dir = fake_root / "results" / "blast" / "T1_16s" / "reports"
        reports_dir.mkdir(parents=True)
        for idx in (1, 10, 2):
            (reports_dir / f"3142611030000_-{idx}_1.csv").write_text(
                "Query,Title,Accession,E-value,Identity,Align_Len,Mismatch,Gap,BitScore,Species,Genus,Strain,Gene_Source,Seq_Type\n",
                encoding="utf-8-sig",
            )
        monkeypatch.setattr(ot_routes, "PROJECT_ROOT", fake_root)
        monkeypatch.setattr(
            ot_routes,
            "get_global_biology_translator",
            lambda: type("T", (), {"translate_batch": lambda self, sp, category="species": {s: s for s in sp}})(),
        )
        out_dir = fake_root / "out"
        stats = ot_routes._export_sangon_order_csv("T1_16s", out_dir)
        assert stats["total"] == 3
        lines = (out_dir / "16S鉴定结果.csv").read_text(encoding="utf-8-sig").splitlines()
        qids = [line.split(",")[0] for line in lines[1:]]
        assert qids == ["-1", "-2", "-10"]

        # 验证 run_pipeline 在 force_reblast=True 时确实清理旧缓存并重新创建任务
        sangon_dir = fake_root / "sangon"
        order_dir = sangon_dir / "20261111_2140691111"
        (order_dir / "原始压缩包").mkdir(parents=True)
        (order_dir / "原始数据").mkdir(parents=True)
        (order_dir / "BLAST结果").mkdir(parents=True)
        (order_dir / "原始数据" / "s_-1.1.fasta").write_text(">1\nATGC\n", encoding="utf-8")

        task_name = f"{order_dir.name}_16s"
        old_cache = fake_root / "results" / "blast" / task_name / "reports" / "s_-1_1.csv"
        old_cache.parent.mkdir(parents=True)
        old_cache.write_text("cached", encoding="utf-8")

        events: list[tuple[str, str]] = []

        class FakeBlastMgr:
            def delete_task(self, tid):
                events.append(("delete", tid))
                return (True, None)

            def create_task(self, params):
                assert not old_cache.exists(), "force_reblast 未清除旧 CSV 缓存"
                events.append(("create", params["task_name"]))
                return params["task_name"]

            def get_task_status(self, tid):
                return {"status": ot_routes.TaskStatus.COMPLETED.value, "progress": 100}

        monkeypatch.setattr(ot_routes, "get_blast_manager", lambda: FakeBlastMgr())
        monkeypatch.setattr(
            ot_routes,
            "_export_sangon_order_csv",
            lambda tid, out: {"total": 1, "with_hits": 1, "no_hits": 0},
        )
        ot_routes._sangon_pipeline_state["running"] = False

        async def _run_sync():
            await ot_routes.run_sangon_16s_pipeline(
                ot_routes.SangonRunRequest(
                    sangon_root=str(sangon_dir),
                    order_names=[order_dir.name],
                    force_reblast=True,
                )
            )
            import time
            for _ in range(50):
                if not ot_routes._sangon_pipeline_state["running"]:
                    break
                time.sleep(0.05)

        asyncio.run(_run_sync())
        assert ("delete", task_name) in events
        assert ("create", task_name) in events

    # 验证 ToolConfig.resolve_bio_tool 在无 PATH 场景下的多盘符扫描容错
    monkeypatch.setenv("PATH", "")
    resolved = ToolConfig.resolve_bio_tool("blastn")
    if resolved is not None:
        assert resolved.exists()


def test_routes_test_send_sangon_send_result_and_settings(monkeypatch):
    """验证 test_send、sangon_16s/send_result 与 downloads_dir 配置更新路由（安全默认发往自身）"""
    import zipfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes
    import src.backend.services.other_tools.sangon_settings as ss_mod

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    sent_records: list[dict] = []

    class FakeSender:
        def __init__(self, cfg):
            self.cfg = cfg

        def send(self, attachment, to=None, subject=None, body=None, cc=None):
            sent_records.append({
                "to": to,
                "subject": subject,
                "body": body,
                "attach_name": Path(attachment).name,
                "attach_names": zipfile.ZipFile(attachment).namelist(),
                "attach_size": Path(attachment).stat().st_size,
            })
            return type(
                "SendResult",
                (),
                {
                    "ok": True,
                    "to": to,
                    "subject": subject,
                    "stage": "sent",
                    "attachment_size": Path(attachment).stat().st_size,
                    "error": None,
                },
            )()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sangon_dir = root / "sangon"
        dl_dir = root / "downloads"
        send_dir = root / "sends"
        sangon_dir.mkdir()
        dl_dir.mkdir()
        send_dir.mkdir()
        (send_dir / "ANNO_X_注释报告.docx").write_bytes(b"PK\x03\x04dummy-docx")

        cfg = MailConfig(
            account="self@qq.com",
            smtp_account="self@qq.com",
            reply_to="external_client@163.com",
            auth_code_env="TEST_ENV_VAR_NOT_USED",
            smtp_auth_code_env="TEST_ENV_VAR_NOT_USED",
            send_dir=str(send_dir),
        )
        monkeypatch.setenv("TEST_ENV_VAR_NOT_USED", "dummy-auth")
        monkeypatch.setattr(ot_routes, "load_config", lambda *a, **kw: cfg)
        monkeypatch.setattr(ot_routes, "MailSender", FakeSender)
        monkeypatch.setattr(ss_mod, "SANGON_CONFIG_PATH", root / "sangon_16s_config.json")

        # 1. test_send 默认留空不发给 reply_to(external_client)，只发给自己 self@qq.com
        r_ts = client.post(
            "/other_tools/mail_pipeline/test_send",
            json={"note": "自检", "attach_latest_report": True},
        )
        assert r_ts.status_code == 200
        assert sent_records[-1]["to"] == "self@qq.com"
        assert "ANNO_X_注释报告.docx" in sent_records[-1]["attach_names"]
        assert "smtp_self_test.txt" in sent_records[-1]["attach_names"]

        # 2. 更新 downloads_dir（非法路径 400，合法路径 200）
        bad_dl = client.post(
            "/other_tools/sangon_16s/settings",
            json={"downloads_dir": str(root / "not_exists"), "migrate": False},
        )
        assert bad_dl.status_code == 400
        ok_dl = client.post(
            "/other_tools/sangon_16s/settings",
            json={"sangon_root": str(sangon_dir), "downloads_dir": str(dl_dir), "migrate": False},
        )
        assert ok_dl.status_code == 200

        # 3. sangon_16s/send_result：非法路径 400 / 缺 CSV 404 / 成功发往自身
        bad_name = client.post(
            "/other_tools/sangon_16s/send_result",
            json={"order_dir_name": "../bad", "sangon_root": str(sangon_dir)},
        )
        assert bad_name.status_code == 400

        order_dir = sangon_dir / "20261111_2140688888"
        (order_dir / "BLAST结果").mkdir(parents=True)
        missing_csv = client.post(
            "/other_tools/sangon_16s/send_result",
            json={"order_dir_name": order_dir.name, "sangon_root": str(sangon_dir)},
        )
        assert missing_csv.status_code == 404

        (order_dir / "BLAST结果" / "16S鉴定结果.csv").write_text(
            "查询序列,鉴定物种(中文翻译),鉴定概率分布(中文翻译),原始鉴定物种(拉丁文),原始鉴定概率分布(拉丁文),分类/菌株信息,基因/序列库,相似度 (Identity),E值,访问号,详细标题\n"
            "-1,枯草芽孢杆菌,枯草芽孢杆菌(100%),Bacillus subtilis,Bacillus subtilis(100%),Bacillus,16S,100.0%,0.00e+00,NR_027552.1,Bacillus subtilis\n",
            encoding="utf-8-sig",
        )
        r_send_16s = client.post(
            "/other_tools/sangon_16s/send_result",
            json={"order_dir_name": order_dir.name, "sangon_root": str(sangon_dir), "extra_note": "自测"},
        )
        assert r_send_16s.status_code == 200
        body = r_send_16s.json()
        assert body["to"] == "self@qq.com"
        assert body["total_samples"] == 1
        assert body["with_hits"] == 1
        assert "16S鉴定结果_2140688888.csv" in sent_records[-1]["attach_names"]


def test_build_annotation_report_handles_zero_trna_and_safety():
    """验证 build_annotation_report.py 在 tRNA=0 与无 ACR 场景下可顺利生成完整 .docx"""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "build_annotation_report.py"

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "ANNO_TEST"
        data_dir.mkdir()
        (data_dir / "summary.json").write_text(
            json.dumps({
                "sequence_id": "contig_1",
                "genome_length_bp": 12000,
                "gc_content_percent": 48.5,
                "cds_count": 1,
                "trna_count": 0,
                "hypothetical_count": 0,
                "hypothetical_percent": 0.0,
                "coding_density_percent": 75.0,
                "category_distribution": {"Replication & Repair": 1},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "features.json").write_text(
            json.dumps([{
                "type": "CDS",
                "locus_tag": "TEST_0001",
                "start": 1,
                "end": 900,
                "strand": "+",
                "length_bp": 900,
                "product": "DNA polymerase",
                "category": "Replication & Repair",
                "source_engine": "Prodigal",
                "evidence_sources": ["[2]"],
            }], ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "safety_audit.json").write_text(
            json.dumps({
                "safety_passed": True,
                "amr_genes": [],
                "virulent_factors": [],
                "anti_crispr_genes": [],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        out_docx = Path(tmp) / "out_report.docx"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), "--data", str(data_dir), "--out", str(out_docx)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        assert out_docx.exists() and out_docx.stat().st_size > 10000


def test_build_annotation_report_tolerates_missing_safety_and_bad_bitscore():
    """验证 build_annotation_report.py 在缺失 safety_audit.json 与异常 bit score 下仍稳定生成 .docx"""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "build_annotation_report.py"

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "ANNO_MISSING_SAFETY"
        data_dir.mkdir()
        (data_dir / "summary.json").write_text(
            json.dumps({
                "total_length": 12000,
                "gc_content": 48.5,
                "coding_density_pct": 75.0,
                "avg_gene_length": 900.0,
                "annotated_count": 1,
                "hypothetical_count": 0,
                "category_distribution": {"Replication & Repair": 1},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "features.json").write_text(
            json.dumps([{
                "feature_type": "CDS",
                "locus_tag": "TEST_0001",
                "contig_id": "contig_1",
                "start": 1,
                "end": 900,
                "strand": "+",
                "length_bp": 900,
                "product": "DNA polymerase",
                "category": "Replication & Repair",
                "source_engine": "Swiss-Prot",
                "translation": "M" * 300,
                "evidence_sources": ["[Swiss-Prot] P12345 (E-value: 1e-10)"],
            }], ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "swissprot_hits.tsv").write_text(
            "TEST_0001\tsp|P12345|DPOL\t98.0\t300\t1e-20\tN/A\tDNA polymerase OS=Test phage\n",
            encoding="utf-8",
        )
        out_docx = Path(tmp) / "missing_safety.docx"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), "--data", str(data_dir), "--out", str(out_docx)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        assert out_docx.exists() and out_docx.stat().st_size > 10000


def test_mail_pipeline_run_self_overview_fallback_and_send_package(monkeypatch):
    """验证 /mail_pipeline/overview 关联目录 Word 报告、/run 解析 to=self 与 /send_package 安全发己闭环"""
    import zipfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.backend.routes.other_tools as ot_routes

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    sent_records = []
    run_cmds = []

    class FakeSender:
        def __init__(self, cfg):
            self.cfg = cfg

        def send(self, attachment, to=None, subject=None, body=None, cc=None):
            sent_records.append({
                "to": to,
                "subject": subject,
                "body": body,
                "attach_name": Path(attachment).name,
                "attach_size": Path(attachment).stat().st_size,
            })
            return type(
                "SendResult",
                (),
                {
                    "ok": True,
                    "to": to,
                    "subject": subject,
                    "stage": "sent",
                    "attachment_size": Path(attachment).stat().st_size,
                    "error": None,
                },
            )()

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            run_cmds.append(list(cmd))
            self.stdout = iter([
                "[注释] 开始注释 ANNO_TASK_01\n",
                "[打包] 完成归档\n",
                "批次重跑结束：全部环节成功\n",
            ])

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dl_dir = root / "dl"
        send_dir = root / "sends"
        anno_dir = root / "annotations"
        batch_dir = dl_dir / "up_20261111_0008"
        batch_dir.mkdir(parents=True)
        (batch_dir / "sample.fasta").write_text(">c1\nATGC\n", encoding="utf-8")
        send_dir.mkdir(parents=True)
        (anno_dir / "ANNO_TASK_01").mkdir(parents=True)
        (anno_dir / "ANNO_TASK_01" / "ANNO_TASK_01_注释报告.docx").write_bytes(b"PK\x03\x04anno-docx")

        zip_path = send_dir / "ANNO_TASK_01_20261111_120000.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("ANNO.gbk", "LOCUS test\n")
            zf.writestr("ANNO_TASK_01_注释报告.docx", b"PK\x03\x04anno-docx")
        (send_dir / "ANNO_TASK_01_20261111_120000.manifest.json").write_text(
            json.dumps({
                "task_id": "ANNO_TASK_01",
                "pack_time": "2026-11-11T12:00:00",
                "zip": zip_path.name,
                "file_count": 2,
                "files": [
                    {"name": "ANNO.gbk", "size_bytes": 11},
                    {"name": "ANNO_TASK_01_注释报告.docx", "size_bytes": 13},
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        cfg = MailConfig(
            account="self@qq.com",
            smtp_account="self@qq.com",
            reply_to="external_client@163.com",
            auth_code_env="TEST_ENV_VAR_NOT_USED",
            smtp_auth_code_env="TEST_ENV_VAR_NOT_USED",
            download_dir=str(dl_dir),
            send_dir=str(send_dir),
        )
        cfg_file = root / "mail_config.json"
        cfg_file.write_text(
            json.dumps({
                "account": "self@qq.com",
                "smtp_account": "self@qq.com",
                "reply_to": "external_client@163.com",
                "download_dir": str(dl_dir),
                "send_dir": str(send_dir),
            }),
            encoding="utf-8",
        )

        monkeypatch.setenv("TEST_ENV_VAR_NOT_USED", "dummy-auth")
        monkeypatch.setattr(ot_routes, "MAIL_CONFIG_PATH", cfg_file)
        monkeypatch.setattr(ot_routes, "ANNOTATIONS_DIR", anno_dir)
        monkeypatch.setattr(ot_routes, "load_config", lambda *a, **kw: cfg)
        monkeypatch.setattr(ot_routes, "MailSender", FakeSender)
        monkeypatch.setattr(ot_routes.subprocess, "Popen", FakePopen)

        # 1. overview 能回退列出 ANNOTATIONS_DIR 中的 .docx 报告并识别未处理待注释批次
        r_ov = client.get("/other_tools/mail_pipeline/overview")
        assert r_ov.status_code == 200
        ov_data = r_ov.json()
        docx_names = [d["name"] for d in ov_data["docx_reports"]]
        assert "ANNO_TASK_01_注释报告.docx" in docx_names
        assert ov_data["pending_batches_count"] == 1
        assert ov_data["batches"][0]["pipeline_status"] == "downloaded"

        # 2. cleanup 按名字可清理位于 annotations 回退目录的 .docx
        cl = cleanup_mail_history(dl_dir, send_dir, anno_dir, targets=["docx"], names=["ANNO_TASK_01_注释报告.docx"])
        assert cl["removed_count"] == 1
        assert not (anno_dir / "ANNO_TASK_01" / "ANNO_TASK_01_注释报告.docx").exists()

        # 3. send_package：路径穿越返回 400 / 不存在返回 404 / to="self" 安全发往本人
        r_bad = client.post("/other_tools/mail_pipeline/send_package", json={"zip_name": "../bad.zip"})
        assert r_bad.status_code == 400
        r_404 = client.post("/other_tools/mail_pipeline/send_package", json={"zip_name": "not_found.zip"})
        assert r_404.status_code == 404
        r_ok = client.post(
            "/other_tools/mail_pipeline/send_package",
            json={"zip_name": zip_path.name, "to": "self", "extra_note": "回归检查"},
        )
        assert r_ok.status_code == 200
        assert sent_records[-1]["to"] == "self@qq.com"
        assert "ANNO_TASK_01" in sent_records[-1]["subject"]
        assert "ANNO_TASK_01_注释报告.docx" in sent_records[-1]["body"]

        # 4. /run 支持批次重跑并发往 self，且解析 self 为真实邮箱再传给 auto_pipeline
        ot_routes._mail_pipeline_state["running"] = False
        r_run = client.post(
            "/other_tools/mail_pipeline/run",
            json={"annotate_only_batch": batch_dir.name, "no_send": False, "to": "self"},
        )
        assert r_run.status_code == 200
        for _ in range(30):
            if not ot_routes._mail_pipeline_state["running"]:
                break
            import time
            time.sleep(0.05)
        assert len(run_cmds) == 1
        cmd = run_cmds[0]
        assert "--annotate-only" in cmd and str(batch_dir) in cmd
        to_idx = cmd.index("--to")
        assert cmd[to_idx + 1] == "self@qq.com"
        assert ot_routes._mail_pipeline_state["last_exit_code"] == 0
        assert ot_routes._mail_pipeline_state["current_stage"] == "completed"
        assert "批次重跑结束：全部环节成功" in ot_routes._mail_pipeline_state["last_output"]


def test_no_emoji_and_utf8_in_new_files():
    """验证新增与修改的前后端代码文件全部采用 UTF-8 且不含任何 Emoji 字符"""
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / "scripts" / "build_annotation_report.py",
        repo_root / "src" / "blast" / "local_blast.py",
        repo_root / "src" / "workbench" / "models" / "tool_config.py",
        repo_root / "src" / "mail_download" / "auto_pipeline.py",
        repo_root / "src" / "mail_download" / "batch_state.py",
        repo_root / "src" / "mail_download" / "config.py",
        repo_root / "src" / "mail_download" / "downloader.py",
        repo_root / "src" / "mail_download" / "fetcher.py",
        repo_root / "src" / "mail_download" / "packer.py",
        repo_root / "src" / "mail_download" / "scheduler.py",
        repo_root / "src" / "mail_download" / "sender.py",
        repo_root / "src" / "backend" / "routes" / "other_tools.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "dir_migrator.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "history_cleaner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "mail_inbox_browser.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_mail_scanner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_settings.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_zip_importer.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "secret_store.py",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherToolsView.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "api.ts",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PathField.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "CleanupDialog.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PaginationBar.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "MailAutoPipelineModule.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "modules" / "Sangon16SPipelineModule.vue",
    ]
    for path in target_files:
        assert path.exists(), f"Missing file: {path}"
        content = path.read_text(encoding="utf-8")
        for ch in content:
            code = ord(ch)
            is_emoji = (
                0x1F300 <= code <= 0x1FAFF
                or 0x2600 <= code <= 0x27BF
                or 0xFE00 <= code <= 0xFE0F
            )
            assert not is_emoji, f"Emoji character U+{code:04X} found in {path}"
