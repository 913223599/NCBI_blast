# -*- coding: utf-8 -*-
"""SMTP 回传发送：把打包好的结果 zip 作为附件发回。

设计要点：
- 标准库 smtplib + email，零第三方依赖；
- 连接对象可注入（smtp_factory 钩子），自动化测试用 FakeSMTP 替换，
  不触碰真实邮箱账号；
- 授权码仅从环境变量读取，绝不落盘；
- 返回结构化 SendResult（成功/失败、SMTP 阶段），失败不抛异常。
"""
import email.message
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger("mail_download.sender")

DEFAULT_SUBJECT = "噬菌体注释结果回传"
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


def sanitize_zip_filename(name: Optional[str], fallback: str) -> str:
    """校验并规范化附件 zip 文件名，拦截路径穿越及非法文件名字符。"""
    cleaned = (name or "").strip()
    if not cleaned:
        return fallback
    if ".." in cleaned or any(ord(ch) < 32 or ch in _INVALID_FILENAME_CHARS for ch in cleaned):
        raise ValueError(f"附件文件名不能包含路径分隔符或非法字符: {name}")
    if not cleaned.lower().endswith(".zip"):
        cleaned = f"{cleaned}.zip"
    stem = cleaned[:-4].strip()
    if not stem or all(ch == "." for ch in stem):
        raise ValueError(f"附件文件名不能为空: {name}")
    return cleaned


@dataclass
class SendResult:
    ok: bool = False
    to: str = ""
    cc: str = ""
    from_name: str = ""
    subject: str = ""
    attachment: str = ""
    attachment_name: str = ""
    attachment_size: int = 0
    stage: str = ""  # sent / connect_error / auth_error / send_error / missing_auth / missing_attach / invalid_attach_name
    error: Optional[str] = None


class MailSender:
    """SMTP 发送器。smtp_factory 可注入（测试用 FakeSMTP）。"""

    def __init__(self, cfg, smtp_factory: Optional[Callable[[], smtplib.SMTP]] = None):
        self.cfg = cfg
        self._smtp_factory = smtp_factory

    def _connect(self) -> smtplib.SMTP:
        if self._smtp_factory is not None:
            conn = self._smtp_factory()
        else:
            auth = self.cfg.smtp_auth_code
            if not auth:
                raise RuntimeError(
                    f"缺少授权码：请设置环境变量 {self.cfg.smtp_auth_code_env} 后重试"
                )
            timeout = getattr(self.cfg, "socket_timeout", 60)
            context = ssl.create_default_context()
            conn = smtplib.SMTP_SSL(self.cfg.smtp_server, self.cfg.smtp_port,
                                    timeout=timeout, context=context)
        conn.login(self.cfg.smtp_account, self.cfg.smtp_auth_code or "")
        return conn

    # ---- 主流程 ----

    def send(
        self,
        attachment: Path,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        from_name: Optional[str] = None,
        attachment_name: Optional[str] = None,
    ) -> SendResult:
        """发送一封带 zip 附件的邮件。失败时返回 ok=False + 阶段/错误，不抛异常。"""
        attach_path = Path(attachment)
        if not attach_path.exists() or not attach_path.is_file():
            return SendResult(ok=False, stage="missing_attach",
                              error=f"附件不存在: {attach_path}")

        try:
            final_attach_name = sanitize_zip_filename(attachment_name, attach_path.name)
        except ValueError as exc:
            return SendResult(ok=False, stage="invalid_attach_name", error=str(exc))

        recipient = to or self.cfg.reply_to
        if not recipient:
            return SendResult(ok=False, stage="missing_to",
                              error="缺少收件人：请传 --to 或配置 reply_to")

        to_list = [addr.strip() for addr in recipient.replace(";", ",").split(",") if addr.strip()]
        cc_list = [
            addr.strip()
            for raw in (cc or [])
            if raw
            for addr in raw.replace(";", ",").split(",")
            if addr.strip()
        ]
        display_name = (from_name or self.cfg.smtp_display_name or "").strip()
        final_subject = (subject or "").strip() or DEFAULT_SUBJECT
        final_body = body if (body and body.strip()) else self._default_body(attach_path)

        mail = self._build_mail(
            ", ".join(to_list),
            final_subject,
            final_body,
            attach_path,
            cc=cc_list,
            from_name=display_name,
            attachment_name=final_attach_name,
        )
        result = SendResult(
            to=", ".join(to_list),
            cc=", ".join(cc_list),
            from_name=display_name,
            subject=final_subject,
            attachment=str(attach_path),
            attachment_name=final_attach_name,
            attachment_size=attach_path.stat().st_size,
        )
        # 仅真实连接需要授权码；注入（测试）模式跳过
        if self._smtp_factory is None and not self.cfg.smtp_auth_code:
            result.stage = "missing_auth"
            result.error = (f"缺少授权码：请设置环境变量 "
                            f"{self.cfg.smtp_auth_code_env} 后重试")
            return result
        conn = None
        try:
            conn = self._connect()
        except Exception as e:
            logger.error("SMTP 连接/登录失败: %s", e)
            result.stage = "connect_error"
            result.error = str(e)
            return result
        try:
            all_rcpts = to_list + cc_list
            conn.sendmail(self.cfg.smtp_account, all_rcpts, mail.as_string())
            result.ok = True
            result.stage = "sent"
            return result
        except Exception as e:
            logger.error("SMTP 发送失败: %s", e)
            result.stage = "send_error"
            result.error = str(e)
            return result
        finally:
            if conn is not None:
                try:
                    conn.quit()
                except Exception:
                    pass

    # ---- 内部 ----

    def _build_mail(
        self,
        to: str,
        subject: str,
        body: str,
        attach_path: Path,
        cc: List[str],
        from_name: str = "",
        attachment_name: Optional[str] = None,
    ) -> email.message.Message:
        msg = MIMEMultipart()
        msg["From"] = formataddr((from_name, self.cfg.smtp_account)) if from_name else self.cfg.smtp_account
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = Header(subject, "utf-8").encode()
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.cfg.smtp_account.split("@")[-1] if "@" in self.cfg.smtp_account else None)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with open(attach_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="zip")
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", attachment_name or attach_path.name),
        )
        msg.attach(part)
        return msg

    @staticmethod
    def _default_body(attach_path: Path) -> str:
        return (
            f"注释结果已完成，结果包见附件：{attach_path.name}\n"
            f"文件大小：{attach_path.stat().st_size / 1024:.1f} KB\n"
            "如需调整请回复本邮件。"
        )
