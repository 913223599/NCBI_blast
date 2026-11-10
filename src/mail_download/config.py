# -*- coding: utf-8 -*-
"""mail_download 配置加载

配置独立存放在 <项目根>/mail_config.json（不写入主 config.json）。
授权码不进入任何配置文件，仅从环境变量 YS_MAIL_AUTH_CODE 读取。
"""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_ATTACHMENT_EXTS = [".fasta", ".fa", ".fna", ".fas", ".fsa", ".seq", ".txt"]


@dataclass
class MailConfig:
    # IMAP 连接
    imap_server: str = "imap.qq.com"
    imap_port: int = 993
    account: str = "913223599@qq.com"
    auth_code_env: str = "YS_MAIL_AUTH_CODE"
    # 附件筛选（白名单为空表示不限发件人）
    sender_whitelist: List[str] = field(default_factory=list)
    subject_keywords: List[str] = field(default_factory=list)
    attachment_exts: List[str] = field(default_factory=lambda: list(DEFAULT_ATTACHMENT_EXTS))
    max_attach_size_mb: int = 200
    # 行为
    since_days: int = 7
    download_dir: str = "results/email_downloads"
    mark_seen: bool = False
    socket_timeout: int = 60
    batch_size: int = 200
    # 落地后可选回调：调用注释 pipeline 的入口（预留，见 docs）
    on_download_cmd: Optional[str] = None
    # SMTP 回传（结果打包发回）
    smtp_server: str = "smtp.163.com"
    smtp_port: int = 465
    smtp_account: str = "yssw_service@163.com"
    smtp_auth_code_env: str = "YS_MAIL_SMTP_AUTH_CODE"
    smtp_display_name: str = "元昇生物注释服务"
    reply_to: str = "yssw_service@163.com"  # 结果回传默认收件人
    send_dir: str = "results/email_sends"

    @property
    def auth_code(self) -> Optional[str]:
        return os.environ.get(self.auth_code_env) or None

    @property
    def smtp_auth_code(self) -> Optional[str]:
        return os.environ.get(self.smtp_auth_code_env) or None

    @property
    def resolved_download_dir(self) -> Path:
        d = Path(self.download_dir)
        return d if d.is_absolute() else PROJECT_ROOT / d

    @property
    def resolved_send_dir(self) -> Path:
        d = Path(self.send_dir)
        return d if d.is_absolute() else PROJECT_ROOT / d

    @classmethod
    def from_dict(cls, data: dict) -> "MailConfig":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


def load_config(config_path: Optional[str] = None, require_imap_auth: bool = True) -> MailConfig:
    """加载 mail_config.json；文件不存在时返回默认配置（测试/演练可用）。

    require_imap_auth=False 用于纯回传（打包+SMTP 发送）场景：
    不需要 IMAP 授权码，只校验 SMTP 授权码由发送器按需检查。
    """
    path = Path(config_path) if config_path else (PROJECT_ROOT / "mail_config.json")
    if not path.exists():
        return MailConfig()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cfg = MailConfig.from_dict(data)
    if require_imap_auth and cfg.auth_code is None:
        raise RuntimeError(
            f"未找到邮箱授权码：请设置环境变量 {cfg.auth_code_env}（QQ 邮箱 IMAP 授权码），"
            f"或用 --auth-code-env 指定其他环境变量。"
        )
    return cfg


def dump_example(path: Optional[Path] = None) -> Path:
    """写出 mail_config.example.json 模板。"""
    target = path or PROJECT_ROOT / "mail_config.example.json"
    example = {
        "imap_server": "imap.qq.com",
        "imap_port": 993,
        "account": "913223599@qq.com",
        "auth_code_env": "YS_MAIL_AUTH_CODE",
        "sender_whitelist": ["填写发件人邮箱，如 yssw_service@163.com"],
        "subject_keywords": ["拼接"],
        "attachment_exts": [".fasta", ".fa", ".fna", ".fas", ".fsa", ".seq", ".txt"],
        "max_attach_size_mb": 200,
        "since_days": 7,
        "download_dir": "results/email_downloads",
        "mark_seen": False,
        "on_download_cmd": None,
        "smtp_server": "smtp.163.com",
        "smtp_port": 465,
        "smtp_account": "yssw_service@163.com",
        "smtp_auth_code_env": "YS_MAIL_SMTP_AUTH_CODE",
        "smtp_display_name": "元昇生物注释服务",
        "reply_to": "yssw_service@163.com",
        "send_dir": "results/email_sends",
    }
    target.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
