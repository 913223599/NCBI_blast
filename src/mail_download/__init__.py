# -*- coding: utf-8 -*-
"""mail_download —— 从邮箱下载需求附件（拼接 fasta）的工具链

流程：IMAP 连接收件箱 → 按发件人白名单/主题/附件类型筛选 → 下载附件到
      results/email_downloads/up_<时间戳>/ 并写 manifest.json。
授权码仅从环境变量读取，绝不落盘。
"""
from .config import MailConfig, load_config
from .fetcher import MailFetcher, MessageSummary
from .downloader import AttachmentSaver

__all__ = ["MailConfig", "load_config", "MailFetcher", "MessageSummary", "AttachmentSaver"]
