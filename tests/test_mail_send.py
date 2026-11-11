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

    def test_pack_includes_docx_report(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prod = make_product_dir(base)
            (prod / "ANNO_5A8C0B32_RE2_注释报告.docx").write_bytes(b"PK\x03\x04docx-dummy")
            info = ResultPacker(base / "sends").pack(prod)
            with zipfile.ZipFile(info["zip"]) as zf:
                names = set(zf.namelist())
            self.assertIn("ANNO_5A8C0B32_RE2_注释报告.docx", names)


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

    def test_send_with_cc_multi_recipients_and_message_id(self):
        """支持分号/逗号多收件人、CC 抄送列表投递，并自动生成 Message-ID"""
        with tempfile.TemporaryDirectory() as td:
            zip_path = self._attach(Path(td))
            cfg, sender, fake = make_sender()
            result = sender.send(
                zip_path,
                to="a@example.com; b@example.com",
                cc=["cc1@example.com", "cc2@example.com"],
                subject="抄送与多收件人测试",
            )
            self.assertTrue(result.ok)
            self.assertEqual(
                fake.sent_to,
                ["a@example.com", "b@example.com", "cc1@example.com", "cc2@example.com"],
            )
            msg = email.message_from_string(fake.sent_msg)
            self.assertEqual(msg["To"], "a@example.com, b@example.com")
            self.assertEqual(msg["Cc"], "cc1@example.com, cc2@example.com")
            self.assertTrue(msg.get("Message-ID"))


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


class TestAutoPipelineAndScheduler(unittest.TestCase):
    """auto_pipeline 断点闭环（docx 同步、--to self、--annotate-only 发信）与 scheduler 修复验证"""

    def test_pack_and_send_syncs_docx_and_resolves_self(self):
        import src.mail_download.auto_pipeline as ap_mod

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prod = make_product_dir(base)
            docx_file = prod / "ANNO_5A8C0B32_RE2_注释报告.docx"
            docx_file.write_bytes(b"PK\x03\x04docx-sync")
            send_dir = base / "sends"
            dl_dir = base / "dl"
            dl_dir.mkdir()
            ap_mod.PIPELINE_LOG = dl_dir / "pipeline.log"

            cfg = MailConfig(
                account="self@qq.com",
                smtp_account="self@qq.com",
                reply_to="client@example.com",
                download_dir=str(dl_dir),
                send_dir=str(send_dir),
            )
            fake = FakeSMTP()
            orig_init = ap_mod.MailSender.__init__
            ap_mod.MailSender.__init__ = lambda self_s, c, smtp_factory=None: orig_init(self_s, c, smtp_factory=lambda: fake)
            try:
                ok = ap_mod._pack_and_send(
                    cfg,
                    prod,
                    "ANNO_5A8C0B32_RE2",
                    do_send=True,
                    to="self",
                    subject_prefix="【测试】",
                    mail_info={"subject": "原邮件", "attachments": ["a.fasta"]},
                )
            finally:
                ap_mod.MailSender.__init__ = orig_init

            self.assertTrue(ok)
            self.assertEqual(fake.sent_to, ["self@qq.com"])
            self.assertTrue((send_dir / docx_file.name).is_file())
            self.assertEqual(len(list(send_dir.glob("*.zip"))), 1)

    def test_resolve_self_without_own_account_fails_safely(self):
        import src.mail_download.auto_pipeline as ap_mod

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            prod = make_product_dir(base)
            cfg = MailConfig(account="", smtp_account="", reply_to="client@example.com", send_dir=str(base / "sends"))
            ap_mod.PIPELINE_LOG = base / "pipeline.log"
            ok = ap_mod._pack_and_send(cfg, prod, "ANNO_X", do_send=True, to="self", subject_prefix="")
            self.assertFalse(ok)

    def test_annotate_only_supports_fas_manifest_and_to_self_and_exit_code(self):
        import src.mail_download.auto_pipeline as ap_mod
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dl_dir = base / "dl"
            send_dir = base / "sends"
            batch = dl_dir / "up_20261111_0001"
            batch.mkdir(parents=True)
            fas = batch / "sample_x.fas"
            fas.write_text(">phage_x\nATGCATGC\n", encoding="utf-8")
            (batch / "manifest.json").write_text(
                json.dumps(
                    {
                        "mail": {"subject": "送测批次001", "date": "2026-11-11"},
                        "attachments": [{"filename": "sample_x.fas"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            cfg_path = base / "mail_config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "account": "self@qq.com",
                        "smtp_account": "self@qq.com",
                        "reply_to": "client@example.com",
                        "download_dir": str(dl_dir),
                        "send_dir": str(send_dir),
                    }
                ),
                encoding="utf-8",
            )

            out_prod = make_product_dir(base / "anno_out")
            docx_out = out_prod / "ANNO_X_注释报告.docx"
            docx_out.write_bytes(b"PK\x03\x04report")

            async def fake_annotate(_batch, _fasta):
                return {"task_id": "ANNO_X", "out_dir": out_prod, "files": {}}

            fake = FakeSMTP()
            orig_init = ap_mod.MailSender.__init__
            ap_mod.MailSender.__init__ = lambda self_s, c, smtp_factory=None: orig_init(self_s, c, smtp_factory=lambda: fake)
            try:
                # 1. --annotate-only 传 --to self：触发注释、报告、打包并只发往 self@qq.com
                with patch.object(ap_mod, "_annotate", side_effect=fake_annotate), \
                     patch.object(ap_mod, "_build_report", return_value=docx_out):
                    rc = ap_mod.main(["--config", str(cfg_path), "--annotate-only", str(batch), "--to", "self"])
                self.assertEqual(rc, 0)
                self.assertEqual(fake.sent_to, ["self@qq.com"])
                msg = email.message_from_string(fake.sent_msg)
                body_part = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
                body_txt = body_part.get_payload(decode=True).decode("utf-8")
                self.assertIn("送测批次001", body_txt)
                self.assertTrue((send_dir / docx_out.name).is_file())

                # 2. 报告生成失败返回 None 时退出码必须非 0
                fake.sent_to = None
                with patch.object(ap_mod, "_annotate", side_effect=fake_annotate), \
                     patch.object(ap_mod, "_build_report", return_value=None):
                    rc_fail = ap_mod.main(["--config", str(cfg_path), "--annotate-only", str(batch)])
                self.assertEqual(rc_fail, 1)
                self.assertIsNone(fake.sent_to)
            finally:
                ap_mod.MailSender.__init__ = orig_init

    def test_scheduler_run_poll_no_none_arg(self):
        import src.mail_download.scheduler as sched_mod
        from types import SimpleNamespace
        from unittest.mock import patch

        captured = []
        with patch.object(sched_mod, "cli_main", side_effect=lambda argv: captured.append(argv) or 0):
            rc1 = sched_mod.run_poll(SimpleNamespace(since_days=5, config=None, verbose=False))
            rc2 = sched_mod.run_poll(SimpleNamespace(since_days=7, config="mail.json", verbose=False))
            rc3 = sched_mod.run_poll(SimpleNamespace(since_days=3, config="mail.json", verbose=True))

        self.assertEqual((rc1, rc2, rc3), (0, 0, 0))
        self.assertEqual(captured[0], ["--since-days", "5"])
        self.assertEqual(captured[1], ["--since-days", "7", "--config", "mail.json"])
        self.assertEqual(captured[2], ["--since-days", "3", "--config", "mail.json", "--verbose"])

    def test_fetch_only_then_auto_pipeline_resumes_pending_and_skips_completed(self):
        """复现场景：仅收件落盘并入去重索引后，点击运行流水线自动接续注释，完成后不再重复处理"""
        import src.mail_download.auto_pipeline as ap_mod
        from types import SimpleNamespace
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dl_dir = base / "dl"
            send_dir = base / "sends"
            anno_dir = base / "annotations"
            dl_dir.mkdir()
            send_dir.mkdir()
            anno_dir.mkdir()

            # 1) 模拟“仅收件”刚落盘但未运行流水线的批次（含无 pipeline 字段的老结构，复现用户真实目录）
            pending_batch = dl_dir / "up_20261111_182735_003520"
            pending_batch.mkdir()
            pending_fa = pending_batch / "12-A_asm_ngcs_scaffold_1.fasta"
            pending_fa.write_text(">ngcs_scaffold_1\nATGCATGCATGC\n", encoding="utf-8")
            (pending_batch / "manifest.json").write_text(
                json.dumps(
                    {
                        "batch": pending_batch.name,
                        "download_time": "2026-11-11T18:27:35",
                        "mail": {"seq": 3520, "sender": "yssw_service@163.com", "subject": "12-A_asm_ngcs_scaffold_1"},
                        "attachments": [{"filename": pending_fa.name, "sha256": "abc"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            # 2) 模拟一个无 pipeline 字段但 annotations/ 中已有产物的历史已完成批次（不能被误重跑）
            legacy_done_batch = dl_dir / "up_20261028_134429_002147"
            legacy_done_batch.mkdir()
            (legacy_done_batch / "G2-1.fasta").write_text(">g2\nATGC\n", encoding="utf-8")
            (legacy_done_batch / "manifest.json").write_text(
                json.dumps(
                    {"batch": legacy_done_batch.name, "mail": {"sender": "yssw_service@163.com", "subject": "G2-1"}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            legacy_anno = anno_dir / "ANNO_G2-1_20261028_140000"
            legacy_anno.mkdir()
            (legacy_anno / "summary.json").write_text("{}", encoding="utf-8")

            # 3) 模拟一个 _TEST 本地测试批次（不能被日常流程自动发送）
            test_batch = dl_dir / "up_20261028_185036_TEST"
            test_batch.mkdir()
            (test_batch / "demo.fasta").write_text(">t1\nATGC\n", encoding="utf-8")

            cfg_path = base / "mail_config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "account": "self@qq.com",
                        "smtp_account": "self@qq.com",
                        "reply_to": "client@example.com",
                        "download_dir": str(dl_dir),
                        "send_dir": str(send_dir),
                    }
                ),
                encoding="utf-8",
            )

            annotated_batches: list[str] = []

            async def fake_annotate(batch_dir, fasta_path):
                annotated_batches.append(f"{batch_dir.name}/{fasta_path.name}")
                prod = make_product_dir(anno_dir / f"run_{len(annotated_batches)}")
                docx_out = prod / "ANNO_12A_注释报告.docx"
                docx_out.write_bytes(b"PK\x03\x04report")
                return {"task_id": "ANNO_12A", "out_dir": prod, "files": {}}

            sent_count = 0
            fake = FakeSMTP()
            orig_init = ap_mod.MailSender.__init__
            orig_send = ap_mod.MailSender.send

            def wrapped_send(self_s, zip_path, to=None, subject=None, body=None, cc=None):
                nonlocal sent_count
                sent_count += 1
                return orig_send(self_s, zip_path, to=to, subject=subject, body=body, cc=cc)

            ap_mod.MailSender.__init__ = lambda self_s, c, smtp_factory=None: orig_init(self_s, c, smtp_factory=lambda: fake)
            ap_mod.MailSender.send = wrapped_send
            orig_anno_dir = ap_mod.ANNOTATIONS_DIR
            ap_mod.ANNOTATIONS_DIR = anno_dir
            try:
                fake_fetch_cls = lambda _cfg: type(
                    "Fetcher",
                    (),
                    {"fetch": lambda self, since_days=None: SimpleNamespace(connection_error=None, scanned=5, matched=[])},
                )()
                with patch.object(ap_mod, "MailFetcher", side_effect=fake_fetch_cls), \
                     patch.object(ap_mod, "_annotate", side_effect=fake_annotate), \
                     patch.object(ap_mod, "_build_report", side_effect=lambda out_dir, tid, *_: out_dir / "ANNO_12A_注释报告.docx"):
                    # 第一次运行：邮箱无新附件，但自动发现并接续处理了 pending_batch
                    rc1 = ap_mod.main(["--config", str(cfg_path), "--to", "self"])
                    self.assertEqual(rc1, 0)
                    self.assertEqual(annotated_batches, ["up_20261111_182735_003520/12-A_asm_ngcs_scaffold_1.fasta"])
                    self.assertEqual(sent_count, 1)
                    self.assertEqual(fake.sent_to, ["self@qq.com"])
                    mf_after = json.loads((pending_batch / "manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual(mf_after["pipeline"]["status"], "completed")
                    self.assertEqual(mf_after["pipeline"]["send_status"], "sent")
                    self.assertIn("收件扫描", (dl_dir / "pipeline.log").read_text(encoding="utf-8"))

                    # 第二次运行：已完成批次不会重复运行注释与发信
                    rc2 = ap_mod.main(["--config", str(cfg_path), "--to", "self"])
                    self.assertEqual(rc2, 0)
                    self.assertEqual(len(annotated_batches), 1)
                    self.assertEqual(sent_count, 1)
                    self.assertIn("没有需要处理的新附件或待处理批次", (dl_dir / "pipeline.log").read_text(encoding="utf-8"))
            finally:
                ap_mod.ANNOTATIONS_DIR = orig_anno_dir
                ap_mod.MailSender.__init__ = orig_init
                ap_mod.MailSender.send = orig_send


if __name__ == "__main__":
    unittest.main()
