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


def test_no_emoji_and_utf8_in_new_files():
    """验证新增与修改的前后端代码文件全部采用 UTF-8 且不含任何 Emoji 字符"""
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / "src" / "mail_download" / "config.py",
        repo_root / "src" / "mail_download" / "downloader.py",
        repo_root / "src" / "mail_download" / "fetcher.py",
        repo_root / "src" / "backend" / "routes" / "other_tools.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "dir_migrator.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "history_cleaner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "mail_inbox_browser.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_mail_scanner.py",
        repo_root / "src" / "backend" / "services" / "other_tools" / "sangon_settings.py",
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
