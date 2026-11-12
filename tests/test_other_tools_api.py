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
        assert res_p1["new_count"] == 3
        assert res_p1["created_count"] == 3
        assert res_p1["created_order_nos"] == ["2140610003", "2140610002", "2140610001"]
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

        # 已缓存下载链接的待下载订单再次扫描时不重复拉取正文，并保留建目录时间
        fake_cached = _FakeIMAPForOtherTools(mails)
        res_cached = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=200,
            dedup=True,
            auto_create=False,
            conn_factory=lambda: fake_cached,
        )
        assert res_cached["existing_count"] == 3
        by_cached = {m["order_no"]: m for m in res_cached["mails"]}
        assert by_cached["2140610003"]["download_url"].endswith("CX003_NEW")
        assert by_cached["2140610001"]["cx_order_id"] == "CX001"
        assert not [c for c in fake_cached.fetch_calls if "BODY.PEEK[]" in c]
        idx_data = json.loads((root / ".sangon_mail_index.json").read_text(encoding="utf-8"))
        assert idx_data["seen_orders"]["2140610003"]["created_at"]

        # 已下载压缩包的订单不再需要下载链接：清掉缓存后也不应拉取其正文
        (root / "20261103_2140610002" / "原始压缩包" / "x.zip").write_bytes(b"PK")
        idx_data["seen_orders"]["2140610002"]["download_url"] = ""
        (root / ".sangon_mail_index.json").write_text(json.dumps(idx_data, ensure_ascii=False), encoding="utf-8")
        fake_skip = _FakeIMAPForOtherTools(mails)
        scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=200,
            dedup=True,
            auto_create=False,
            conn_factory=lambda: fake_skip,
        )
        assert not [c for c in fake_skip.fetch_calls if "BODY.PEEK[]" in c]

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
        assert res_only_new["existing_count"] == 3
        assert res_only_new["new_count"] == 0

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
            json={
                "page": 2,
                "page_size": 5,
                "dedup": False,
                "only_new": True,
                "auto_create": False,
            },
        )
        assert r_paged.status_code == 200
        assert captured[-1]["page"] == 2
        assert captured[-1]["page_size"] == 5
        assert captured[-1]["dedup"] is False
        assert captured[-1]["only_new"] is True
        assert captured[-1]["auto_create"] is False
        assert "preserve_created_orders" not in captured[-1]

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
        assert by_order["1011709710"]["legacy_dir_exists"] is False
        assert not any("1011709710" in p.name for p in root.iterdir())
        assert by_order["2140698888"]["dedup_status"] == "created"
        assert by_order["2140698888"]["dir_ready"] is True
        assert res["non_sequencing_count"] == 1

        # 即使历史遗留了同名物流目录，仍明确标识为 non_sequencing 而非误报 existing
        (root / "20261102_1011709710").mkdir()
        res_legacy = scan_sangon_mails(
            root,
            cfg,
            page=1,
            page_size=10,
            dedup=True,
            auto_create=False,
            conn_factory=lambda: _FakeIMAPForOtherTools(mails),
        )
        by_legacy = {m["order_no"]: m for m in res_legacy["mails"]}
        assert by_legacy["1011709710"]["dedup_status"] == "non_sequencing"
        assert by_legacy["1011709710"]["legacy_dir_exists"] is True
        assert res_legacy["non_sequencing_count"] == 1
        assert res_legacy["existing_count"] == 1


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


def test_sangon_order_annotator_new_flag_and_claimable_zip():
    """验证订单补充信息：下载页链接、新订单标记（新建且待下载、7 天有效）与可认领下载包"""
    from datetime import datetime, timedelta

    from src.backend.services.other_tools.sangon_mail_scanner import SangonMailIndex
    from src.backend.services.other_tools.sangon_order_annotator import annotate_sangon_orders

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        idx = SangonMailIndex(root)
        idx.record(
            order_no="2140600001", message_id="", dir_name="20261111_2140600001",
            subject="测序结果通知 2140600001", date_text="", cx_order_id="CX1",
            download_url="http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID=CX1",
            created=True,
        )
        idx.record(order_no="2140600002", message_id="", dir_name="20261111_2140600002",
                   subject="", date_text="", created=True)
        idx.record(order_no="2140600003", message_id="", dir_name="20261101_2140600003",
                   subject="", date_text="")
        idx.save()
        # 人为把 0002 的建目录时间改为 10 天前，应不再显示“新”
        data = json.loads((root / ".sangon_mail_index.json").read_text(encoding="utf-8"))
        data["seen_orders"]["2140600002"]["created_at"] = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        (root / ".sangon_mail_index.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        orders = [
            {"dir_name": "20261111_2140600001", "order_no": "2140600001", "status": "pending"},
            {"dir_name": "20261111_2140600002", "order_no": "2140600002", "status": "pending"},
            {"dir_name": "20261101_2140600003", "order_no": "2140600003", "status": "completed"},
        ]
        candidates = [
            {"order_no": "2140600001", "zip_name": "a_2140600001_测序结果.zip",
             "matched_dir_name": "20261111_2140600001", "archived": False},
            {"order_no": "2140600003", "zip_name": "c_2140600003_测序结果.zip",
             "matched_dir_name": "20261101_2140600003", "archived": True},
        ]
        annotate_sangon_orders(root, orders, candidates)
        o1, o2, o3 = orders
        assert o1["is_new"] is True
        assert o1["download_url"].endswith("CX1")
        assert o1["download_zip_ready"] is True
        assert o1["download_zip_name"] == "a_2140600001_测序结果.zip"
        assert o2["is_new"] is False
        assert o2["download_zip_ready"] is False
        assert o3["is_new"] is False
        assert o3["download_zip_ready"] is False


def test_sangon_global_ignore_full_pipeline(monkeypatch):
    """验证生工 16S 全局忽略规则：概览剔除待认领、扫邮件不建目录、下载认领跳过、批量运行跳过、自定义关键词与取消忽略"""
    import zipfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes
    import src.backend.services.other_tools.sangon_settings as ss_mod

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sangon_dir = root / "sangon"
        dl_dir = root / "downloads"
        sangon_dir.mkdir()
        dl_dir.mkdir()

        cfg_path = root / "sangon_16s_config.json"
        monkeypatch.setattr(ss_mod, "SANGON_CONFIG_PATH", cfg_path)

        # 两个已有待下载订单目录，其中一个将被全局忽略
        ignored_dir = sangon_dir / "20261014_2140608938"
        (ignored_dir / "原始压缩包").mkdir(parents=True)
        (ignored_dir / "原始数据").mkdir(parents=True)
        (ignored_dir / "BLAST结果").mkdir(parents=True)

        active_dir = sangon_dir / "20261111_2140690001"
        (active_dir / "原始压缩包").mkdir(parents=True)
        (active_dir / "原始数据").mkdir(parents=True)
        (active_dir / "BLAST结果").mkdir(parents=True)
        (active_dir / "原始数据" / "s1_-1.1.fasta").write_text(">1\nATGC\n", encoding="utf-8")

        # 浏览器下载目录中两个待认领测序压缩包（1 个匹配目录，1 个未建目录）
        zip1 = dl_dir / "吴晨_2140608938_测序结果.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("a_-1.1.fasta", ">1\nATGC\n")
        zip2 = dl_dir / "李四_2140601771_测序结果.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("b_-1.1.fasta", ">1\nGGGG\n")

        assert (
            client.post(
                "/other_tools/sangon_16s/settings",
                json={"sangon_root": str(sangon_dir), "downloads_dir": str(dl_dir), "migrate": False},
            ).status_code
            == 200
        )

        # 1. 全局忽略 2140608938 与 2140601771
        r_ig = client.post(
            "/other_tools/sangon_16s/ignore",
            json={"order_keys": ["20261014_2140608938", "2140601771"], "ignore": True, "reason": "线下已手动比对"},
        )
        assert r_ig.status_code == 200
        assert r_ig.json()["updated_count"] == 2
        assert "2140608938" in r_ig.json()["ignored_orders"]
        assert "2140601771" in r_ig.json()["ignored_orders"]

        # 2. overview：待认领角标降为 0，已忽略下载计数为 2，20261014_2140608938 标为 ignored
        ov = client.get("/other_tools/sangon_16s/overview").json()
        assert ov["pending_download_count"] == 0
        assert ov["ignored_download_count"] == 2
        by_dir = {o["dir_name"]: o for o in ov["orders"]}
        assert by_dir["20261014_2140608938"]["ignored"] is True
        assert by_dir["20261014_2140608938"]["ignore_reason"] == "线下已手动比对"
        assert by_dir["20261014_2140608938"]["download_zip_ready"] is False
        assert by_dir["20261111_2140690001"]["ignored"] is False

        # 3. 批量认领默认跳过全局忽略订单（即使开启 auto_create_order 也不得新建 2140601771）
        imp = import_order_zips_from_downloads(sangon_dir, dl_dir, auto_create_order=True)
        assert imp["imported_count"] == 0
        assert imp["skipped_ignored"] == 2
        assert not any("2140601771" in p.name for p in sangon_dir.iterdir())
        assert not list((ignored_dir / "原始压缩包").glob("*.zip"))

        # 4. 邮件扫描：命中全局忽略的不建目录不抓正文；自定义非测序主题关键词生效
        r_kw = client.post(
            "/other_tools/sangon_16s/settings",
            json={"ignore_subject_keywords": ["已发货", "催款通知"]},
        )
        assert r_kw.status_code == 200
        mails = [
            _make_mime_mail("info1@sangon.com", "测序结果通知 2140601771", body_html="cxOrderID=CX1", message_id="<i1@s>"),
            _make_mime_mail("info1@sangon.com", "生工月度催款通知 2140699001", body_html="催款", message_id="<i2@s>"),
            _make_mime_mail("info1@sangon.com", "测序结果通知 2140699002", body_html="cxOrderID=CX2", message_id="<i3@s>"),
        ]
        fake_imap = _FakeIMAPForOtherTools(mails)
        scan_res = scan_sangon_mails(
            sangon_dir,
            MailConfig(account="u@qq.com"),
            page=1,
            page_size=20,
            dedup=True,
            auto_create=True,
            conn_factory=lambda: fake_imap,
        )
        by_ono = {m["order_no"]: m for m in scan_res["mails"]}
        assert by_ono["2140601771"]["dedup_status"] == "ignored"
        assert by_ono["2140699001"]["dedup_status"] == "non_sequencing"
        assert by_ono["2140699002"]["dedup_status"] == "created"
        assert scan_res["ignored_count"] == 1
        assert not any("2140601771" in p.name for p in sangon_dir.iterdir())
        assert not any("2140699001" in p.name for p in sangon_dir.iterdir())
        # 仅 2140699002 拉取正文
        assert len([c for c in fake_imap.fetch_calls if "BODY.PEEK[]" in c]) == 1

        # 5. 全局运行待处理时自动跳过已忽略订单（只跑未忽略的 active_dir，新建目录也顺手删掉以聚焦测试）
        for p in list(sangon_dir.iterdir()):
            if "2140699002" in p.name:
                import shutil
                shutil.rmtree(p)
        executed_tasks: list[str] = []

        class FakeBlastMgr:
            def create_task(self, params):
                executed_tasks.append(params["task_name"])
                return params["task_name"]

            def get_task_status(self, tid):
                return {"status": ot_routes.TaskStatus.COMPLETED.value, "progress": 100}

        monkeypatch.setattr(ot_routes, "get_blast_manager", lambda: FakeBlastMgr())
        monkeypatch.setattr(ot_routes, "_export_sangon_order_csv", lambda tid, out: {"total": 1, "with_hits": 1, "no_hits": 0})
        ot_routes._sangon_pipeline_state["running"] = False

        r_run = client.post(
            "/other_tools/sangon_16s/run_pipeline",
            json={"sangon_root": str(sangon_dir), "order_names": []},
        )
        assert r_run.status_code == 200
        import time
        for _ in range(40):
            if not ot_routes._sangon_pipeline_state["running"]:
                break
            time.sleep(0.05)
        assert executed_tasks == ["20261111_2140690001_16s"]

        # 6. 取消忽略 2140601771 后恢复待认领计数
        r_unig = client.post(
            "/other_tools/sangon_16s/ignore",
            json={"order_keys": ["2140601771"], "ignore": False},
        )
        assert r_unig.status_code == 200
        assert r_unig.json()["updated_count"] == 1
        ov_after = client.get("/other_tools/sangon_16s/overview").json()
        assert ov_after["pending_download_count"] == 1
        assert ov_after["ignored_download_count"] == 1


def test_mail_pipeline_batch_ignore_route_and_state(monkeypatch):
    """验证邮件注释回传模块对收件批次标记“已忽略跳过”与恢复接口、统计及防重入"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes
    from src.mail_download.batch_state import collect_pending_batches

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dl_dir = root / "dl"
        send_dir = root / "sends"
        anno_dir = root / "annotations"
        send_dir.mkdir()
        anno_dir.mkdir()

        for bname, fa_name in (("up_20261111_0001", "a.fasta"), ("up_20261111_0002", "b.fasta")):
            bdir = dl_dir / bname
            bdir.mkdir(parents=True)
            (bdir / fa_name).write_text(">seq\nATGC\n", encoding="utf-8")
            (bdir / "manifest.json").write_text(
                json.dumps({"batch": bname, "mail": {"sender": "s@163.com", "subject": bname}}),
                encoding="utf-8",
            )

        cfg_file = root / "mail_config.json"
        cfg_file.write_text(
            json.dumps({"download_dir": str(dl_dir), "send_dir": str(send_dir)}),
            encoding="utf-8",
        )
        cfg_obj = MailConfig(download_dir=str(dl_dir), send_dir=str(send_dir))
        monkeypatch.setattr(ot_routes, "MAIL_CONFIG_PATH", cfg_file)
        monkeypatch.setattr(ot_routes, "ANNOTATIONS_DIR", anno_dir)
        monkeypatch.setattr(ot_routes, "load_config", lambda *a, **kw: cfg_obj)
        ot_routes._mail_pipeline_state["running"] = False

        # 非法路径穿越返回 400
        assert client.post("/other_tools/mail_pipeline/batch_ignore", json={"batch_name": "../bad"}).status_code == 400

        # 跳过 0001
        r_skip = client.post(
            "/other_tools/mail_pipeline/batch_ignore",
            json={"batch_name": "up_20261111_0001", "ignore": True, "reason": "线下已处理"},
        )
        assert r_skip.status_code == 200
        assert r_skip.json()["ignored"] is True

        ov = client.get("/other_tools/mail_pipeline/overview").json()
        assert ov["pending_batches_count"] == 1
        assert ov["ignored_batches_count"] == 1
        by_name = {b["batch_name"]: b for b in ov["batches"]}
        assert by_name["up_20261111_0001"]["pipeline_status"] == "ignored"
        assert by_name["up_20261111_0001"]["pipeline_status_label"] == "已忽略跳过"
        assert by_name["up_20261111_0001"]["pending"] is False
        assert by_name["up_20261111_0001"]["ignore_reason"] == "线下已处理"

        # 队列收集与原 fasta 文件保留验证
        pending = collect_pending_batches(dl_dir, cfg_obj, send_dir, anno_dir)
        assert [p[0].name for p in pending] == ["up_20261111_0002"]
        assert (dl_dir / "up_20261111_0001" / "a.fasta").is_file()

        # 恢复 0001
        r_res = client.post(
            "/other_tools/mail_pipeline/batch_ignore",
            json={"batch_name": "up_20261111_0001", "ignore": False},
        )
        assert r_res.status_code == 200
        assert r_res.json()["ignored"] is False
        ov2 = client.get("/other_tools/mail_pipeline/overview").json()
        assert ov2["pending_batches_count"] == 2
        assert ov2["ignored_batches_count"] == 0


def test_local_blast_resource_plan_reserves_cores():
    """验证本地 BLAST 并发进程数与单进程线程数受总 CPU 预算约束，避免超配导致主机和 UI 卡死"""
    from src.blast.local_blast import compute_local_blast_resource_plan

    for cpu_cnt, min_reserved in ((32, 4), (16, 4), (12, 4), (8, 2), (4, 2), (2, 1)):
        max_conc, threads = compute_local_blast_resource_plan(cpu_count=cpu_cnt)
        assert max_conc >= 1
        assert threads >= 1
        assert max_conc * threads <= cpu_cnt - min_reserved

    # 高配主机也必须受限于单进程预算，不得超出总预算
    max_conc_32, threads_32 = compute_local_blast_resource_plan(cpu_count=32, requested_threads=64)
    assert max_conc_32 == 2
    assert max_conc_32 * threads_32 <= 28


def test_blast_engine_respects_explicit_max_workers(monkeypatch):
    """验证 BlastEngine 在调用方显式指定 max_workers=2 时遵循约束，不再强制放大到 4 并发"""
    from concurrent.futures import Future
    from src.blast import engine as engine_mod

    observed_workers: list[int] = []

    class DummyExecutor:
        def __init__(self, max_workers):
            observed_workers.append(max_workers)

        def submit(self, fn, *args, **kwargs):
            fut: Future = Future()
            fut.set_result([])
            return fut

        def shutdown(self, wait=False):
            return None

    class DummyMgr:
        def generate_hash(self, s):
            return "h1"

    monkeypatch.setattr(engine_mod, "ThreadPoolExecutor", DummyExecutor)
    monkeypatch.setattr(engine_mod, "get_annotation_manager", lambda: DummyMgr())

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "reports").mkdir(parents=True, exist_ok=True)
        (tmp_dir / "xml_raw").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(engine_mod.BlastEngine, "_init_results_dir", lambda self: tmp_dir)
        engine_mod.BlastEngine("test_explicit_workers_2", {"max_workers": 2}).run(
            [{"id": "seq1", "sequence": "ATGCGTACGTAG"}]
        )
        engine_mod.BlastEngine("test_explicit_workers_cap", {"max_workers": 8}).run(
            [{"id": "seq1", "sequence": "ATGCGTACGTAG"}]
        )
        engine_mod.BlastEngine("test_default_workers", {}).run(
            [{"id": "seq1", "sequence": "ATGCGTACGTAG"}]
        )

    assert observed_workers == [2, 4, 4]


def test_sangon_run_pipeline_progress_summary_logging_and_failure_guard(monkeypatch, caplog):
    """验证生工 16S 流水线：跳过缺包仍推进进度至 100%、终端日志输出、全缺包明确提示、BLAST 失败不误覆盖空 CSV"""
    import logging
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes
    import src.backend.services.other_tools.sangon_settings as ss_mod

    app = FastAPI()
    app.include_router(ot_routes.router)
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sangon_dir = root / "sangon"
        dl_dir = root / "downloads"
        sangon_dir.mkdir()
        dl_dir.mkdir()
        monkeypatch.setattr(ss_mod, "SANGON_CONFIG_PATH", root / "sangon_cfg.json")
        assert (
            client.post(
                "/other_tools/sangon_16s/settings",
                json={"sangon_root": str(sangon_dir), "downloads_dir": str(dl_dir), "migrate": False},
            ).status_code
            == 200
        )

        # 准备 3 个目录：1 空、2 有序列、3 空
        d_miss1 = sangon_dir / "20261101_2140610001"
        d_ok = sangon_dir / "20261102_2140610002"
        d_miss2 = sangon_dir / "20261103_2140610003"
        for d in (d_miss1, d_ok, d_miss2):
            (d / "原始压缩包").mkdir(parents=True)
            (d / "原始数据").mkdir(parents=True)
            (d / "BLAST结果").mkdir(parents=True)
        (d_ok / "原始数据" / "sample_-1.1.fasta").write_text(">s1\nATGCATGC\n", encoding="utf-8")

        executed_tasks: list[str] = []
        exported_calls: list[str] = []
        fake_status_mode = {"status": ot_routes.TaskStatus.COMPLETED.value}

        class FakeBlastMgr:
            def create_task(self, params):
                executed_tasks.append(params["task_name"])
                return params["task_name"]

            def get_task_status(self, tid):
                return {"status": fake_status_mode["status"], "progress": 100}

        monkeypatch.setattr(ot_routes, "get_blast_manager", lambda: FakeBlastMgr())

        def fake_export(tid, out_dir):
            exported_calls.append(tid)
            return {"total": 1, "with_hits": 1, "no_hits": 0}

        monkeypatch.setattr(ot_routes, "_export_sangon_order_csv", fake_export)
        ot_routes._sangon_pipeline_state["running"] = False

        # 1. 全缺包运行时：进度应正常到 100%，summary 记录 skipped_missing=2，last_message 明确提示原因
        with caplog.at_level(logging.INFO):
            r_miss = client.post(
                "/other_tools/sangon_16s/run_pipeline",
                json={"sangon_root": str(sangon_dir), "order_names": [d_miss1.name, d_miss2.name]},
            )
        assert r_miss.status_code == 200
        for _ in range(40):
            if not ot_routes._sangon_pipeline_state["running"]:
                break
            time.sleep(0.05)

        ov_miss = client.get("/other_tools/sangon_16s/overview").json()["runtime"]
        assert ov_miss["running"] is False
        assert ov_miss["progress"] == 100
        assert ov_miss["current_stage"] == "completed"
        assert ov_miss["summary"] == {"total": 2, "processed": 0, "skipped_missing": 2, "failed": 0}
        assert "缺少压缩包或 *.1.fasta" in ov_miss["last_message"]
        assert any("[Sangon16S]" in rec.message for rec in caplog.records)

        # 2. 混合订单运行时：结束进度应达到 100%，而不是卡在 66%
        caplog.clear()
        with caplog.at_level(logging.INFO):
            r_mix = client.post(
                "/other_tools/sangon_16s/run_pipeline",
                json={"sangon_root": str(sangon_dir), "order_names": []},
            )
            assert r_mix.status_code == 200
            for _ in range(40):
                if not ot_routes._sangon_pipeline_state["running"]:
                    break
                time.sleep(0.05)

        ov_mix = client.get("/other_tools/sangon_16s/overview").json()["runtime"]
        assert ov_mix["progress"] == 100
        assert ov_mix["summary"] == {"total": 3, "processed": 1, "skipped_missing": 2, "failed": 0}
        assert executed_tasks == ["20261102_2140610002_16s"]
        assert exported_calls == ["20261102_2140610002_16s"]
        assert any("[Sangon16S] (3/3)" in rec.message for rec in caplog.records)

        # 3. BLAST 失败时不调用 CSV 导出、记录 failed=1 且阶段置为 failed
        exported_calls.clear()
        fake_status_mode["status"] = ot_routes.TaskStatus.FAILED.value
        r_fail = client.post(
            "/other_tools/sangon_16s/run_pipeline",
            json={"sangon_root": str(sangon_dir), "order_names": [d_ok.name], "force_reblast": True},
        )
        assert r_fail.status_code == 200
        for _ in range(40):
            if not ot_routes._sangon_pipeline_state["running"]:
                break
            time.sleep(0.05)

        ov_fail = client.get("/other_tools/sangon_16s/overview").json()["runtime"]
        assert ov_fail["progress"] == 100
        assert ov_fail["current_stage"] == "failed"
        assert ov_fail["summary"]["failed"] == 1
        assert exported_calls == []


def test_sangon_credentials_storage_and_settings(monkeypatch):
    """验证生工官网账号与密钥分离存储（JSON 与 .sangon_auth 分离、仅回传掩码、清空保护）"""
    import src.backend.services.other_tools.sangon_settings as ss_mod

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg_file = root / "sangon_16s_config.json"
        monkeypatch.setattr(ss_mod, "PROJECT_ROOT", root)
        monkeypatch.setattr(ss_mod, "SANGON_CONFIG_PATH", cfg_file)

        st0 = ss_mod.get_sangon_auth_status()
        assert st0["account"] == ""
        assert st0["password_ready"] is False
        assert st0["password_masked"] == ""

        saved = ss_mod.save_sangon_credentials(
            account="15012345678",
            password="SecretPass999",
            auto_confirm_fee=False,
        )
        assert saved["account"] == "15012345678"
        assert saved["password_ready"] is True
        assert "SecretPass999" not in saved["password_masked"]
        assert saved["password_masked"].startswith("Se") and saved["password_masked"].endswith("99")
        assert saved["auto_confirm_fee"] is False

        # 确认明文密码绝对不落地在 json 文件中
        raw_json = cfg_file.read_text(encoding="utf-8")
        assert "SecretPass999" not in raw_json
        assert (root / ".sangon_auth").is_file()
        assert ss_mod.resolve_sangon_credentials() == ("15012345678", "SecretPass999")

        # 传 password=None 仅修改账号与开关，保留既有密钥文件
        st_keep = ss_mod.save_sangon_credentials(account="15099990000", password=None, auto_confirm_fee=True)
        assert st_keep["account"] == "15099990000"
        assert st_keep["password_ready"] is True
        assert st_keep["auto_confirm_fee"] is True
        assert ss_mod.resolve_sangon_credentials() == ("15099990000", "SecretPass999")

        # 传空字符串清除密钥文件
        st_clear = ss_mod.save_sangon_credentials(account="15099990000", password="")
        assert st_clear["password_ready"] is False
        assert not (root / ".sangon_auth").exists()


def test_sangon_downloader_claim_first_atomic_zip_and_routes(monkeypatch):
    """验证自动下载器：优先认领 Downloads 既有包、单会话批量下载原子校验、费用弹窗开关、验证码中止与 API 联动"""
    import io
    import time
    import zipfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.backend.routes.other_tools as ot_routes
    import src.backend.services.other_tools.sangon_downloader as sd_mod
    import src.backend.services.other_tools.sangon_settings as ss_mod
    from src.backend.services.other_tools.sangon_mail_scanner import SangonMailIndex, create_sangon_subdirs

    def _build_zip_bytes(fname: str = "s1_-1.1.fasta") -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(fname, ">s1\nATGCGTACGT\n")
        return buf.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sangon_dir = root / "sangon"
        dl_dir = root / "downloads"
        sangon_dir.mkdir()
        dl_dir.mkdir()

        monkeypatch.setattr(ss_mod, "PROJECT_ROOT", root)
        monkeypatch.setattr(ss_mod, "SANGON_CONFIG_PATH", root / "sangon_16s_config.json")

        # 准备 4 个订单：
        # 1) 2140610001：浏览器 Downloads 已存在，优先就地认领无需走网页下载
        # 2) 2140610002：待网页下载（直出包）
        # 3) 2140610003：待网页下载（会弹 KBSeq 费用确认）
        # 4) 2140610004：被全局忽略，应自动跳过
        d1 = sangon_dir / "20261101_2140610001"
        d2 = sangon_dir / "20261102_2140610002"
        d3 = sangon_dir / "20261103_2140610003"
        d4 = sangon_dir / "20261104_2140610004"
        for d in (d1, d2, d3, d4):
            create_sangon_subdirs(d)

        (dl_dir / "测试_2140610001_测序结果.zip").write_bytes(_build_zip_bytes("c1_-1.1.fasta"))

        idx = SangonMailIndex(sangon_dir)
        for ono, d, cx in (
            ("2140610001", d1, "CX101"),
            ("2140610002", d2, "CX102"),
            ("2140610003", d3, "CX103"),
            ("2140610004", d4, "CX104"),
        ):
            idx.record(
                order_no=ono,
                message_id=f"<{ono}@sangon>",
                dir_name=d.name,
                subject=f"测序通知 {ono}",
                date_text="Wed, 11 Nov 2026 10:00:00 +0800",
                cx_order_id=cx,
                download_url=f"http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID={cx}",
                created=True,
            )
        idx.save()

        ss_mod.save_sangon_settings({
            "sangon_root": str(sangon_dir),
            "downloads_dir": str(dl_dir),
            "ignored_orders": {"2140610004": {"order_no": "2140610004", "reason": "test"}},
        })

        app = FastAPI()
        app.include_router(ot_routes.router)
        client = TestClient(app)

        # 未配置生工账号密码时，overview 应透出未就绪状态，直接触发纯网页单子下载返回 400
        ov0 = client.get("/other_tools/sangon_16s/overview").json()
        assert ov0["sangon_auth"]["password_ready"] is False
        r_no_auth = client.post(
            "/other_tools/sangon_16s/download_orders",
            json={"order_names": [d2.name]},
        )
        assert r_no_auth.status_code == 400

        # 通过路由配置生工账号密码
        r_auth = client.post(
            "/other_tools/sangon_16s/auth",
            json={"account": "15000001111", "password": "TestPwd!123", "auto_confirm_fee": True},
        )
        assert r_auth.status_code == 200
        assert r_auth.json()["sangon_auth"]["password_ready"] is True
        assert r_auth.json()["sangon_auth"]["account"] == "15000001111"

        visited_orders: list[str] = []

        class FakeSession:
            def __init__(self, account, password, headless=True, timeout_ms=90000):
                assert account == "15000001111"
                assert password == "TestPwd!123"
                self.mode = "normal"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download_order(self, order_meta, *, auto_confirm_fee=True, log_cb=None):
                ono = order_meta["order_no"]
                visited_orders.append(ono)
                dest_dir = Path(order_meta["order_path"]) / "原始压缩包"
                if ono == "2140610003" and not auto_confirm_fee:
                    return {
                        "order_no": ono,
                        "dir_name": order_meta["dir_name"],
                        "status": "fee_confirm_required",
                        "message": "检测到 KBSeq 费用确认弹窗，已按设置暂停下载",
                    }
                zip_name = f"测试_{ono}_测序结果.zip"
                dest_zip = dest_dir / zip_name
                dest_zip.write_bytes(_build_zip_bytes(f"{ono}_-1.1.fasta"))
                return {
                    "order_no": ono,
                    "dir_name": order_meta["dir_name"],
                    "status": "downloaded",
                    "zip_name": zip_name,
                    "dest_path": str(dest_zip),
                    "size_bytes": dest_zip.stat().st_size,
                    "fee_confirmed": (ono == "2140610003"),
                    "message": "下载完成",
                }

        # 1. 验证 auto_confirm_fee=False 时费用确认单拦截、正常单与本地认领正常
        res1 = sd_mod.download_sangon_orders(
            sangon_dir,
            dl_dir,
            account="15000001111",
            password="TestPwd!123",
            auto_confirm_fee=False,
            session_factory=FakeSession,
        )
        assert res1["claimed_count"] == 1
        assert res1["downloaded_count"] == 1
        assert res1["skipped_count"] >= 1
        assert "2140610001" not in visited_orders  # Downloads 认领跳过网页
        assert "2140610004" not in visited_orders  # 全局忽略跳过网页
        assert (d1 / "原始压缩包" / "测试_2140610001_测序结果.zip").is_file()
        assert (d2 / "原始压缩包" / "测试_2140610002_测序结果.zip").is_file()
        assert not any((d3 / "原始压缩包").glob("*.zip"))

        # 2. 通过路由触发剩余待下载单（2140610003），开启 auto_confirm_fee=True + auto_run_blast=True 串联全流程
        executed_blast: list[str] = []

        class FakeBlastMgr:
            def create_task(self, params):
                executed_blast.append(params["task_name"])
                return params["task_name"]

            def get_task_status(self, tid):
                return {"status": ot_routes.TaskStatus.COMPLETED.value, "progress": 100}

        monkeypatch.setattr(ot_routes, "get_blast_manager", lambda: FakeBlastMgr())
        monkeypatch.setattr(
            ot_routes,
            "_export_sangon_order_csv",
            lambda tid, out_dir: (
                (out_dir / "16S鉴定结果.csv").write_text("col1,col2\n", encoding="utf-8-sig"),
                {"total": 1, "with_hits": 1, "no_hits": 0},
            )[1],
        )
        monkeypatch.setattr(sd_mod, "SangonBrowserSession", FakeSession)
        ot_routes._sangon_pipeline_state["running"] = False

        r_dl = client.post(
            "/other_tools/sangon_16s/download_orders",
            json={
                "order_names": [d3.name],
                "auto_confirm_fee": True,
                "auto_run_blast": True,
            },
        )
        assert r_dl.status_code == 200
        for _ in range(60):
            if not ot_routes._sangon_pipeline_state["running"]:
                break
            time.sleep(0.05)

        ov_done = client.get("/other_tools/sangon_16s/overview").json()["runtime"]
        assert ov_done["running"] is False
        assert ov_done["progress"] == 100
        assert (d3 / "原始压缩包" / "测试_2140610003_测序结果.zip").is_file()
        assert f"{d3.name}_16s" in executed_blast

        # 3. 验证遇到人机验证弹窗会立刻报错终止，绝不自动绕过
        class CaptchaSession(FakeSession):
            def download_order(self, order_meta, *, auto_confirm_fee=True, log_cb=None):
                raise sd_mod.SangonCaptchaError("检测到生工安全验证弹窗，请手动下载")

        d5 = sangon_dir / "20261105_2140610005"
        create_sangon_subdirs(d5)
        idx.record(
            order_no="2140610005",
            message_id="<2140610005@sangon>",
            dir_name=d5.name,
            subject="测序通知 2140610005",
            date_text="Thu, 12 Nov 2026 09:00:00 +0800",
            cx_order_id="CX105",
            download_url="http://store.sangon.com/cxOrderDetail?cxOrderDetail.cxOrderID=CX105",
            created=True,
        )
        idx.save()
        res_cap = sd_mod.download_sangon_orders(
            sangon_dir,
            dl_dir,
            order_names=[d5.name],
            account="15000001111",
            password="TestPwd!123",
            session_factory=CaptchaSession,
        )
        assert res_cap["captcha_blocked"] is True
        assert res_cap["failed_count"] == 1


def test_no_emoji_and_utf8_in_new_files():
    """验证新增与修改的前后端代码文件全部采用 UTF-8 且不含任何 Emoji 字符"""
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / "scripts" / "build_annotation_report.py",
        repo_root / "src" / "blast" / "engine.py",
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
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_downloader.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_ignore_rules.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_mail_scanner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_order_annotator.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_settings.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_zip_importer.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "secret_store.py",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherToolsView.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "api.ts",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PathField.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "CleanupDialog.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PaginationBar.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "PopoverMenu.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "SangonAccountModal.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "SangonIgnoreModal.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "components" / "SangonMailRecords.vue",
        repo_root / "src" / "web-next" / "src" / "views" / "OtherTools" / "sangonTypes.ts",
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
