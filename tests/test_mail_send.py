# -*- coding: utf-8 -*-
"""
test_mail_send.py - 结果打包回传（SMTP 发送）自动化测试

覆盖"自动回传工作流"邮件环节后半段：注释产物打包 zip → MIME 邮件构造 →
SMTP 发送。全部测试使用 FakeSMTP（注入式模拟 SMTP），不触碰真实邮箱账号与授权码。
"""
import email
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mail_download.config import MailConfig
from src.mail_download.packer import ResultPacker
from src.mail_download.sender import MailSender, SendResult


def make_product_dir(base: Path) -> Path:
    """构造一个最小注释产物目录（含 gbk/tsv/faa/ffn/json + 一个干扰文件）。"""
    d = base / "ANNO_5A8C0B32_RE2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ANNO.gbk").write_text("LOCUS       test\nFEATURES             Location/Qualifiers\n",
                                encoding="utf-8")
    (d / "ANNO.tsv").write_text("Locus_Tag\tProduct\nDFVPWCBX_00001\tDnaB helicase\n",
                                encoding="utf-8")
    (d / "ANNO.faa").write_text(">p1\nMKTAYIAKQRQISFVKSHFSRQDILDLWIYHTQ\n", encoding="utf-8")
    (d / "ANNO.ffn").write_text(">g1\nATGAAAACCGCA\n", encoding="utf-8")
    (d / "features.json").write_text(json.dumps([{"id": 1}]), encoding="utf-8")
    (d / "summary.json").write_text(json.dumps({"cds_count": 1}), encoding="utf-8")
    (d / "notes.txt").write_text("noise", encoding="utf-8")  # 白名单外的干扰文件
    return d


class FakeSMTP:
    """最小 SMTP 模拟：记录 login/sendmail/quit 调用与消息体。"""

    def __init__(self, fail_stage=None):
        self.fail_stage = fail_stage  # None / login / sendmail
        self.login_args = None
        self.sent_to = None
        self.sent_msg = None
        self.quitted = False

    def login(self, user, password):
        if self.fail_stage == "login":
            raise RuntimeError("simulated auth failure")
        self.login_args = (user, password)

    def sendmail(self, from_addr, to_addrs, msg):
        if self.fail_stage == "sendmail":
            raise RuntimeError("simulated send failure")
        self.sent_to = to_addrs
        self.sent_msg = msg

    def quit(self):
        self.quitted = True


def make_sender(cfg_override=None, fail_stage=None):
    cfg = MailConfig(smtp_account="yssw_service@163.com", reply_to="client@example.com")
    if cfg_override:
        for k, v in cfg_override.items():
            setattr(cfg, k, v)
    fake = FakeSMTP(fail_stage=fail_stage)
    sender = MailSender(cfg, smtp_factory=lambda: fake)
    return cfg, sender, fake


class TestResultPacker(unittest.TestCase):
    """打包器：产物收集、zip 内容、清单"""

    def _pack(self, base):
        packer = ResultPacker(base / "sends")
        return packer.pack(make_product_dir(base))

    def test_pack_creates_zip_with_products_only(self):
        with tempfile.TemporaryDirectory() as td:
            info = self._pack(Path(td))
            self.assertTrue(info["zip"].endswith(".zip"))
            self.assertTrue(Path(info["zip"]).exists())
            self.assertGreater(info["size_bytes"], 0)
            names = set()
            with zipfile.ZipFile(info["zip"]) as zf:
                names = set(zf.namelist())
            # 注释产物全在，干扰文件不在
            for expected in ("ANNO.gbk", "ANNO.tsv", "ANNO.faa", "ANNO.ffn",
                             "features.json", "summary.json"):
                self.assertIn(expected, names)
            self.assertNotIn("notes.txt", names)
            self.assertEqual(len(names), 6)

    def test_pack_file_count_and_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            info = self._pack(Path(td))
            self.assertEqual(info["file_count"], 6)
            self.assertEqual(len(info["sha256"]), 64)
            self.assertEqual(info["task_id"], "ANNO_5A8C0B32_RE2")

    def test_pack_custom_task_id(self):
        with tempfile.TemporaryDirectory() as td:
            packer = ResultPacker(Path(td) / "sends")
            info = packer.pack(make_product_dir(Path(td)), task_id="TASK-001")
            self.assertEqual(info["task_id"], "TASK-001")
            self.assertTrue(info["zip_name"].startswith("TASK-001_"))

    def test_pack_missing_dir_raises(self):
        with tempfile.TemporaryDirectory() as td:
            packer = ResultPacker(Path(td) / "sends")
            with self.assertRaises(FileNotFoundError):
                packer.pack(Path(td) / "not_exist")

    def test_pack_empty_dir_raises(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            packer = ResultPacker(Path(td) / "sends")
            with self.assertRaises(ValueError):
                packer.pack(empty)

    def test_manifest_written(self):
        with tempfile.TemporaryDirectory() as td:
            info = self._pack(Path(td))
            manifest = json.loads(Path(info["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_id"], "ANNO_5A8C0B32_RE2")
            self.assertEqual(manifest["file_count"], 6)
            self.assertEqual(manifest["zip"], Path(info["zip"]).name)


class TestMailSender(unittest.TestCase):
    """发送器：邮件构造、调用序列、异常路径"""

    def _attach(self, base):
        packer = ResultPacker(base / "sends")
        return packer.pack(make_product_dir(base))["zip"]

    def test_send_success(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            cfg, sender, fake = make_sender()
            result = sender.send(zip_path, to="client@example.com", subject="注释结果")
            self.assertTrue(result.ok)
            self.assertEqual(result.stage, "sent")
            self.assertEqual(result.to, "client@example.com")
            self.assertEqual(result.attachment_size, Path(zip_path).stat().st_size)
            # SMTP 调用序列
            self.assertEqual(fake.login_args[0], cfg.smtp_account)
            self.assertEqual(fake.sent_to, ["client@example.com"])
            self.assertTrue(fake.quitted)
            # 消息体结构：multipart，含正文与 zip 附件
            msg = email.message_from_string(fake.sent_msg)
            self.assertEqual(msg["To"], "client@example.com")
            parts = list(msg.walk())
            types = [p.get_content_type() for p in parts]
            self.assertIn("multipart/mixed", types)
            self.assertIn("application/zip", types)
            zip_part = next(p for p in parts if p.get_content_type() == "application/zip")
            self.assertEqual(zip_part.get_filename(), Path(zip_path).name)

    def test_send_uses_default_recipient_and_subject(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            cfg, sender, fake = make_sender()
            result = sender.send(zip_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.to, cfg.reply_to)
            self.assertEqual(result.subject, "噬菌体注释结果回传")

    def test_send_missing_attachment(self):
        cfg, sender, fake = make_sender()
        result = sender.send(Path("N:/definitely/not/exist.zip"))
        self.assertFalse(result.ok)
        self.assertEqual(result.stage, "missing_attach")

    def test_send_missing_recipient(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            cfg = MailConfig(reply_to="")  # 无默认收件人
            fake = FakeSMTP()
            sender = MailSender(cfg, smtp_factory=lambda: fake)
            result = sender.send(zip_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "missing_to")

    def test_send_auth_failure(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            _, sender, fake = make_sender(fail_stage="login")
            result = sender.send(zip_path, to="a@b.com")
            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "connect_error")

    def test_send_smtp_failure(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            _, sender, fake = make_sender(fail_stage="sendmail")
            result = sender.send(zip_path, to="a@b.com")
            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "send_error")
            self.assertTrue(fake.quitted)  # finally 仍然 quit

    def test_send_without_auth_code_reports_missing_auth(self):
        """无 SMTP 授权码且走真实连接 → 缺授权码错误（不尝试连接）"""
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            cfg = MailConfig(smtp_account="yssw_service@163.com")
            # 不注入 factory，走真实 _connect：缺授权码应短路
            sender = MailSender(cfg)
            result = sender.send(zip_path, to="a@b.com")
            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "missing_auth")


class TestCliPackSend(unittest.TestCase):
    """CLI 打包/回传入口（--pack-results / --send-results）"""

    def test_pack_cli(self):
        from src.mail_download.cli import main
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prod = make_product_dir(base)
            send_dir = base / "sends"
            cfg_path = base / "mail_config.json"
            cfg_path.write_text(json.dumps({
                "send_dir": str(send_dir),
                "smtp_account": "yssw_service@163.com",
            }), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--config", str(cfg_path), "--pack-results", str(prod)])
            self.assertEqual(rc, 0)
            zips = list(send_dir.glob("*.zip"))
            self.assertEqual(len(zips), 1)
            self.assertIn("ANNO.gbk", zipfile.ZipFile(zips[0]).namelist())

    def test_send_cli_success(self):
        from src.mail_download.cli import main
        import src.mail_download.cli as cli_mod
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prod = make_product_dir(base)
            send_dir = base / "sends"
            cfg_path = base / "mail_config.json"
            cfg_path.write_text(json.dumps({
                "send_dir": str(send_dir),
                "smtp_account": "yssw_service@163.com",
                "reply_to": "client@example.com",
            }), encoding="utf-8")
            fake = FakeSMTP()
            # 注入 FakeSMTP：替换 MailSender._connect 的工厂
            orig = cli_mod.MailSender.__init__
            def patched_init(self, cfg, smtp_factory=None):
                orig(self, cfg, smtp_factory=lambda: fake)
            cli_mod.MailSender.__init__ = patched_init
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = main(["--config", str(cfg_path), "--send-results", str(prod)])
                self.assertEqual(rc, 0)
                self.assertEqual(fake.sent_to, ["client@example.com"])
                self.assertIn("已回传给", buf.getvalue())
            finally:
                cli_mod.MailSender.__init__ = orig


if __name__ == "__main__":
    unittest.main()
