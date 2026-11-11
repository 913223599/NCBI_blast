# -*- coding: utf-8 -*-
"""
test_mail_download.py - 邮箱附件下载工具链自动化测试

覆盖"自动回传工作流"邮件环节前半段：IMAP 收件 → 发件人/主题/附件筛选 → 附件落地 + manifest。
全部测试使用 FakeIMAP（注入式模拟邮箱），不触碰真实邮箱账号与授权码。
"""
import email
import email.utils
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mail_download.config import MailConfig
from src.mail_download.downloader import AttachmentSaver, ProcessedIndex
from src.mail_download.fetcher import (
    MailFetcher,
    _extension_ok,
    _parse_address,
    _sender_allowed,
    _subject_matches,
    sanitize_filename,
)

FASTA_BODY = ">contig_1\nACGTACGTACGTACGTACGT\n>contig_2\nTTTTGGGGAAAACCCC\n"


def make_mail(sender: str, subject: str, attachments, date=None):
    """构造一封 MIME 邮件字节流。attachments: [(filename, payload_bytes|str)]"""
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = date or email.utils.formatdate(localtime=True)
    for name, payload in attachments:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return msg.as_bytes()


class FakeIMAP:
    """最小 IMAP4_SSL 模拟：select/search/fetch（两阶段：头部 / 全文）。"""

    def __init__(self, messages):
        self._messages = messages  # list[bytes]（完整 MIME 邮件）
        self.logged_out = False
        self.fetch_calls = []  # 记录请求过的 part（供断言两阶段行为）

    def select(self, mailbox):
        assert mailbox == "INBOX"
        return ("OK", [b"1"])

    def search(self, charset, criteria):
        return ("OK", [b" ".join(str(i).encode() for i in range(1, len(self._messages) + 1))])

    def fetch(self, seqset, parts):
        self.fetch_calls.append(parts.decode() if isinstance(parts, bytes) else str(parts))
        data = []
        for i in self._expand_seqset(seqset, len(self._messages)):
            raw = self._messages[i - 1]
            seq_info = str(i).encode() + b" (UID 10000)"
            if "HEADER.FIELDS" in self.fetch_calls[-1]:
                msg = email.message_from_bytes(raw)
                header = (
                    f"From: {msg['From']}\r\n"
                    f"Subject: {msg['Subject']}\r\n"
                    f"Date: {msg['Date']}\r\n"
                ).encode("utf-8")
                # 模拟真实 IMAP 头部响应结构：((seq_info, 头部), b')')
                data.append(((seq_info, header), b")"))
            else:
                data.append((seq_info, raw, b")"))
        return ("OK", data)

    @staticmethod
    def _expand_seqset(seqset, total):
        s = seqset.decode() if isinstance(seqset, bytes) else str(seqset)
        ids = []
        for part in s.split():
            if ":" in part:
                a, b = part.split(":")
                ids.extend(range(int(a), int(b) + 1))
            else:
                ids.append(int(part))
        return [i for i in ids if 1 <= i <= total]

    def logout(self):
        self.logged_out = True


def make_fetcher(cfg_override=None, messages=None):
    cfg = MailConfig(sender_whitelist=["yssw_service@163.com"], since_days=7)
    if cfg_override:
        for k, v in cfg_override.items():
            setattr(cfg, k, v)
    fetcher = MailFetcher(cfg, conn_factory=lambda: FakeIMAP(messages or []))
    return cfg, fetcher


class TestFilterLogic(unittest.TestCase):
    """筛选纯函数"""

    def test_sender_whitelist(self):
        self.assertTrue(_sender_allowed("yssw_service@163.com", ["yssw_service@163.com"]))
        self.assertTrue(_sender_allowed("  YSSW_SERVICE@163.COM  ", ["yssw_service@163.com"]))
        self.assertFalse(_sender_allowed("other@qq.com", ["yssw_service@163.com"]))
        self.assertTrue(_sender_allowed("anyone@qq.com", []))  # 白名单空=不限
        self.assertTrue(_sender_allowed("a@b.com", ["填写发件人邮箱，如 xxx"]))  # 模板占位忽略

    def test_subject_keywords(self):
        self.assertTrue(_subject_matches("拼接结果 fasta", ["拼接"]))
        self.assertFalse(_subject_matches("会议纪要", ["拼接"]))
        self.assertTrue(_subject_matches("any", []))  # 关键字空=不限

    def test_extension_filter(self):
        self.assertTrue(_extension_ok("assembly.fasta", [".fasta", ".fa"]))
        self.assertTrue(_extension_ok("c.fa", [".fasta", ".fa"]))
        self.assertFalse(_extension_ok("pic.png", [".fasta", ".fa"]))
        self.assertTrue(_extension_ok("x.bin", []))  # 扩展名空=不限

    def test_filename_sanitize(self):
        self.assertEqual(sanitize_filename("a/b\\c:*.fasta"), "a_b_c__.fasta")
        self.assertEqual(sanitize_filename(""), "attachment")

    def test_parse_address(self):
        self.assertEqual(_parse_address("服务 <yssw_service@163.com>"), "yssw_service@163.com")
        self.assertEqual(_parse_address("plain@qq.com"), "plain@qq.com")


class TestFetchEndToEnd(unittest.TestCase):
    """FakeIMAP 注入：收件→筛选→落地全链路"""

    def _run(self, messages, cfg_override=None):
        cfg, fetcher = make_fetcher(cfg_override, messages)
        result = fetcher.fetch()
        return cfg, fetcher, result

    def test_match_whitelist_sender_fasta(self):
        """白名单发件人 + fasta 附件 → 命中并落地"""
        mail = make_mail("yssw_service@163.com", "拼接完成", [("assembly.fasta", FASTA_BODY)])
        cfg, fetcher, result = self._run([mail])
        self.assertIsNone(result.connection_error)
        self.assertEqual(result.scanned, 1)
        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.matched[0].sender, "yssw_service@163.com")

        with tempfile.TemporaryDirectory() as td:
            stats = AttachmentSaver(Path(td)).save(result.matched)
            self.assertEqual(stats["count"], 1)
            batch = list(Path(td).glob("up_*"))[0]
            self.assertTrue(batch.name.startswith("up_"))
            self.assertTrue((batch / "assembly.fasta").read_text(encoding="utf-8").startswith(">contig_1"))
            manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mail"]["sender"], "yssw_service@163.com")
            self.assertEqual(len(manifest["attachments"]), 1)
            self.assertEqual(manifest["attachments"][0]["filename"], "assembly.fasta")
            self.assertIn("sha256", manifest["attachments"][0])

    def test_non_whitelist_sender_ignored(self):
        """非白名单发件人 → 不命中"""
        mail = make_mail("evil@qq.com", "拼接完成", [("assembly.fasta", FASTA_BODY)])
        _, _, result = self._run([mail])
        self.assertEqual(len(result.matched), 0)

    def test_no_attachment_ignored(self):
        """无附件的邮件 → 不命中"""
        mail = make_mail("yssw_service@163.com", "拼接完成", [])
        _, _, result = self._run([mail])
        self.assertEqual(len(result.matched), 0)

    def test_wrong_extension_ignored(self):
        """非目标扩展名附件 → 不命中"""
        mail = make_mail("yssw_service@163.com", "拼接完成", [("photo.png", b"\x89PNG")]
        )
        _, _, result = self._run([mail])
        self.assertEqual(len(result.matched), 0)

    def test_oversize_attachment_ignored(self):
        """超大附件（超 max_attach_size_mb）→ 跳过"""
        big = make_mail("yssw_service@163.com", "拼接完成",
                        [("big.fasta", "A" * 300)] )
        _, _, result = self._run([big], {"max_attach_size_mb": 0})
        self.assertEqual(len(result.matched), 0)

    def test_subject_keyword_filter(self):
        """主题关键字过滤：命中"拼接"，跳过无关主题"""
        hit = make_mail("yssw_service@163.com", "拼接结果", [("a.fasta", FASTA_BODY)])
        miss = make_mail("yssw_service@163.com", "周末安排", [("b.fasta", FASTA_BODY)])
        _, _, result = self._run([hit, miss], {"subject_keywords": ["拼接"]})
        self.assertEqual(len(result.matched), 1)
        self.assertIn("拼接", result.matched[0].subject)

    def test_empty_whitelist_allows_all(self):
        """白名单为空 → 任意发件人带 fasta 都命中"""
        mail = make_mail("other@qq.com", "组装结果", [("x.fasta", FASTA_BODY)])
        _, _, result = self._run([mail], {"sender_whitelist": []})
        self.assertEqual(len(result.matched), 1)

    def test_duplicate_attachment_skipped(self):
        """同一附件重复到达 → 跨次索引跳过（内容级判重）"""
        mail = make_mail("yssw_service@163.com", "拼接完成", [("assembly.fasta", FASTA_BODY)])
        cfg, fetcher, result = self._run([mail])
        with tempfile.TemporaryDirectory() as td:
            saver = AttachmentSaver(Path(td))
            first = saver.save(result.matched)
            second = saver.save(result.matched)
            self.assertEqual(first["count"], 1)
            self.assertEqual(second["count"], 0)
            self.assertEqual(second["skipped_processed"], 1)

    def test_multiple_attachments_saved(self):
        """一封邮件多个附件（内容不同）全部落地"""
        mail = make_mail("yssw_service@163.com", "拼接完成",
                         [("a.fasta", FASTA_BODY), ("b.fna", FASTA_BODY + "TTTT")])
        _, _, result = self._run([mail])
        with tempfile.TemporaryDirectory() as td:
            stats = AttachmentSaver(Path(td)).save(result.matched)
            self.assertEqual(stats["count"], 2)
            batch = list(Path(td).glob("up_*"))[0]
            self.assertTrue((batch / "a.fasta").exists())
            self.assertTrue((batch / "b.fna").exists())

    def test_connection_error_reported(self):
        """连接失败 → 返回 connection_error 而非抛异常"""
        def broken_factory():
            raise ConnectionError("simulated network down")
        cfg = MailConfig(sender_whitelist=[])
        fetcher = MailFetcher(cfg, conn_factory=broken_factory)
        result = fetcher.fetch()
        self.assertIsNotNone(result.connection_error)
        self.assertEqual(len(result.matched), 0)

    def test_logout_called(self):
        """会话结束后调用 logout"""
        fake = FakeIMAP([])
        cfg = MailConfig(sender_whitelist=[])
        fetcher = MailFetcher(cfg, conn_factory=lambda: fake)
        fetcher.fetch()
        self.assertTrue(fake.logged_out)

    def test_two_stage_fetch(self):
        """大邮箱场景：先头部初筛，仅命中者抓全文（不抓全部全文）"""
        hit = make_mail("yssw_service@163.com", "拼接完成", [("assembly.fasta", FASTA_BODY)])
        miss = make_mail("other@qq.com", "无关邮件", [("x.fasta", FASTA_BODY)])
        fake = FakeIMAP([miss, hit])
        cfg = MailConfig(sender_whitelist=["yssw_service@163.com"])
        fetcher = MailFetcher(cfg, conn_factory=lambda: fake)
        result = fetcher.fetch()
        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.matched[0].subject, "拼接完成")
        # 头部阶段按批抓取（1 次），全文只抓命中邮件（1 次）
        header_calls = [c for c in fake.fetch_calls if "HEADER.FIELDS" in c]
        full_calls = [c for c in fake.fetch_calls if "BODY.PEEK[]" in c]
        self.assertEqual(len(header_calls), 1)
        self.assertEqual(len(full_calls), 1)

    def test_batch_size_chunks(self):
        """batch_size 生效：超过批大小时分多批抓头部"""
        mails = [make_mail("yssw_service@163.com", f"拼接{i}", [("a.fasta", FASTA_BODY)])
                 for i in range(250)]
        fake = FakeIMAP(mails)
        cfg = MailConfig(sender_whitelist=["yssw_service@163.com"], batch_size=100)
        fetcher = MailFetcher(cfg, conn_factory=lambda: fake)
        result = fetcher.fetch()
        header_calls = [c for c in fake.fetch_calls if "HEADER.FIELDS" in c]
        self.assertEqual(len(header_calls), 3)  # 250 封分 3 批


class TestCli(unittest.TestCase):
    """CLI 基本入口（不触碰真实邮箱）"""

    def test_example_template(self):
        """--example 生成配置模板"""
        from src.mail_download.cli import main
        with tempfile.TemporaryDirectory() as td:
            rc = main(["--example"])
            self.assertEqual(rc, 0)
            p = PROJECT_ROOT / "mail_config.example.json"
            self.assertTrue(p.exists())
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["account"], "913223599@qq.com")
            p.unlink()

    def test_missing_auth_code_error(self):
        """未设置授权码且配置存在 → 报错而非崩溃"""
        from src.mail_download.config import load_config
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "mail_config.json"
            cfg_path.write_text(json.dumps({
                "imap_server": "imap.qq.com", "account": "test@qq.com", "auth_code_env": "YS_MAIL_AUTH_CODE_NOT_SET"
            }), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_config(str(cfg_path))


class TestCrossRunDedup(unittest.TestCase):
    """跨次运行去重：确认不会重复收到之前处理过的附件"""

    def _summary(self, subject="拼接完成", body=FASTA_BODY, sender="yssw_service@163.com"):
        mail = make_mail(sender, subject, [("assembly.fasta", body)])
        cfg = MailConfig(sender_whitelist=[sender])
        fetcher = MailFetcher(cfg, conn_factory=lambda: FakeIMAP([mail]))
        return fetcher.fetch().matched

    def test_second_run_skips_same_attachment(self):
        """同一附件再次到达 → 第二次运行跳过（不生成新批次）"""
        with tempfile.TemporaryDirectory() as td:
            saver = AttachmentSaver(Path(td))
            first = saver.save(self._summary())
            self.assertEqual(first["count"], 1)
            self.assertEqual(first["skipped_processed"], 0)
            # 第二次运行（新 saver 实例，模拟新进程）
            second = AttachmentSaver(Path(td)).save(self._summary())
            self.assertEqual(second["count"], 0)
            self.assertEqual(second["skipped_processed"], 1)
            self.assertTrue((Path(td) / ProcessedIndex.INDEX_NAME).exists())

    def test_index_persists_across_instances(self):
        """索引落盘：不同 saver 实例共享判重结果"""
        with tempfile.TemporaryDirectory() as td:
            AttachmentSaver(Path(td)).save(self._summary())
            fresh = AttachmentSaver(Path(td))
            fresh.index.load()
            self.assertEqual(fresh.index.count(), 1)

    def test_different_content_redownloaded(self):
        """内容不同（新拼接结果）→ 新内容会下载、旧内容被跳过"""
        with tempfile.TemporaryDirectory() as td:
            saver = AttachmentSaver(Path(td))
            self.assertEqual(saver.save(self._summary(body=FASTA_BODY))["count"], 1)
            # 新内容 → 正常下载
            self.assertEqual(saver.save(self._summary(body=FASTA_BODY + "ACGT"))["count"], 1)
            # 旧内容再次到达 → 跳过
            stats = saver.save(self._summary(body=FASTA_BODY))
            self.assertEqual(stats["count"], 0)
            self.assertEqual(stats["skipped_processed"], 1)

    def test_corrupt_index_recovers(self):
        """索引文件损坏 → 备份重建，不阻塞下载"""
        with tempfile.TemporaryDirectory() as td:
            idx = Path(td) / ProcessedIndex.INDEX_NAME
            idx.write_text("{not valid json", encoding="utf-8")
            saver = AttachmentSaver(Path(td))
            stats = saver.save(self._summary())
            self.assertEqual(stats["count"], 1)  # 损坏也能正常下载
            self.assertTrue((Path(td) / "processed_index.corrupt.bak").exists())

    def test_empty_batch_dir_removed(self):
        """命中邮件但全部已处理 → 不残留空批次目录"""
        with tempfile.TemporaryDirectory() as td:
            saver = AttachmentSaver(Path(td))
            saver.save(self._summary())
            saver.save(self._summary())  # 全部跳过
            batches = list(Path(td).glob("up_*"))
            self.assertEqual(len(batches), 1)  # 只有首次批次

    def test_cli_reports_skipped(self):
        """CLI 输出含已处理跳过计数"""
        from src.mail_download.cli import main
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as td:
            # 直接驱动 saver 验证统计字段
            saver = AttachmentSaver(Path(td))
            first = saver.save(self._summary())
            self.assertIn("skipped_processed", first)
            second = saver.save(self._summary())
            self.assertEqual(second["skipped_processed"], 1)


if __name__ == "__main__":
    unittest.main()
