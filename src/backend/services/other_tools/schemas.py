# -*- coding: utf-8 -*-
"""
其他功能工作台请求参数模型与常量定义模块 (Other Tools Request Schemas)
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

SANGON_CSV_HEADERS: List[str] = [
    "查询序列",
    "鉴定物种(中文翻译)",
    "鉴定概率分布(中文翻译)",
    "原始鉴定物种(拉丁文)",
    "原始鉴定概率分布(拉丁文)",
    "分类/菌株信息",
    "基因/序列库",
    "相似度 (Identity)",
    "E值",
    "访问号",
    "详细标题",
]


class MailConfigUpdateRequest(BaseModel):
    imap_server: str = "imap.qq.com"
    imap_port: int = 993
    account: str = "913223599@qq.com"
    sender_whitelist: List[str] = ["yssw_service@163.com"]
    subject_keywords: List[str] = []
    attachment_exts: List[str] = [".fasta", ".fa", ".fna", ".fas", ".fsa", ".seq", ".txt"]
    max_attach_size_mb: int = 200
    since_days: int = 7
    download_dir: str = "results/email_downloads"
    mark_seen: bool = False
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_account: str = "913223599@qq.com"
    smtp_display_name: str = "元昇生物注释服务"
    reply_to: str = "yssw_service@163.com"
    send_dir: str = "results/email_sends"
    migrate: bool = True


class MailFetchRequest(BaseModel):
    since_days: Optional[int] = None


class MailListRequest(BaseModel):
    page: int = 1
    page_size: int = 10
    since_days: Optional[int] = None
    dedup: bool = True
    only_new: bool = False


class MailPipelineRunRequest(BaseModel):
    since_days: Optional[int] = None
    no_send: bool = False
    force_send: bool = False
    annotate_only_batch: Optional[str] = None
    test_input: Optional[str] = None
    to: Optional[str] = None
    subject_prefix: str = "【自动】"
    extra_note: Optional[str] = None


class MailPackageSendRequest(BaseModel):
    zip_name: str
    to: Optional[str] = None
    cc: Optional[str] = None
    from_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    extra_note: Optional[str] = None
    attachment_name: Optional[str] = None


class MailPackagePreviewRequest(BaseModel):
    zip_name: str
    extra_note: Optional[str] = None


class MailTestSendRequest(BaseModel):
    to: Optional[str] = None
    cc: Optional[str] = None
    from_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    note: Optional[str] = None
    attachment_name: Optional[str] = None
    attach_latest_report: bool = False


class MailTestSendPreviewRequest(BaseModel):
    note: Optional[str] = None
    attach_latest_report: bool = False


class SangonRunRequest(BaseModel):
    sangon_root: Optional[str] = None
    downloads_dir: Optional[str] = None
    order_names: List[str] = []
    evalue: str = "0.05"
    hitlist_size: str = "50"
    force_reblast: bool = False


class OpenPathRequest(BaseModel):
    path: str


class MailAuthUpdateRequest(BaseModel):
    """授权码更新：字段为 None 表示不修改，空字符串表示清除。"""
    imap_auth_code: Optional[str] = None
    smtp_auth_code: Optional[str] = None


class MailCleanupRequest(BaseModel):
    targets: List[str]
    older_than_days: Optional[int] = None
    names: List[str] = []


class SangonSettingsRequest(BaseModel):
    sangon_root: Optional[str] = None
    downloads_dir: Optional[str] = None
    migrate: bool = True
    ignored_orders: Optional[List[Any]] = None
    ignore_subject_keywords: Optional[List[str]] = None
    auto_confirm_fee: Optional[bool] = None


class SangonAuthUpdateRequest(BaseModel):
    """生工官网账号与登录密码更新：password=None 表示不修改，空字符串表示清除。"""
    account: Optional[str] = None
    password: Optional[str] = None
    auto_confirm_fee: Optional[bool] = None


class SangonDownloadRequest(BaseModel):
    sangon_root: Optional[str] = None
    downloads_dir: Optional[str] = None
    order_names: List[str] = []
    auto_confirm_fee: Optional[bool] = None
    auto_run_blast: bool = False
    evalue: str = "0.05"
    hitlist_size: str = "50"
    force_reblast: bool = False


class SangonIgnoreRequest(BaseModel):
    order_keys: List[str] = []
    ignore: bool = True
    reason: str = ""
    dir_names: Dict[str, str] = {}


class MailBatchIgnoreRequest(BaseModel):
    batch_name: str
    ignore: bool = True
    reason: str = ""


class SangonImportDownloadsRequest(BaseModel):
    sangon_root: Optional[str] = None
    downloads_dir: Optional[str] = None
    order_names: List[str] = []
    auto_create_order: bool = False


class SangonSendResultRequest(BaseModel):
    order_dir_name: str
    sangon_root: Optional[str] = None
    to: Optional[str] = None
    cc: Optional[str] = None
    from_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    extra_note: Optional[str] = None
    attachment_name: Optional[str] = None


class SangonSendPreviewRequest(BaseModel):
    order_dir_name: str
    sangon_root: Optional[str] = None
    extra_note: Optional[str] = None


class SangonCleanupRequest(BaseModel):
    order_names: List[str] = []
    targets: List[str]


class SangonScanMailRequest(BaseModel):
    sangon_root: Optional[str] = None
    page: int = 1
    page_size: int = 10
    dedup: bool = True
    only_new: bool = False
    auto_create: bool = True
    ignore_history: bool = False


class SangonInitOrderRequest(BaseModel):
    dir_name: str
    order_no: str = ""
    subject: str = ""
    date_text: str = ""
    cx_order_id: str = ""
    download_url: str = ""
    sangon_root: Optional[str] = None


class BrowserEnvRepairRequest(BaseModel):
    enabled: Optional[bool] = None
    headless: Optional[bool] = None
    auto_install: bool = True
    use_system_browser_fallback: Optional[bool] = None
    executable_path: Optional[str] = None
    browsers_path: Optional[str] = None
    probe_launch: bool = True

