# -*- coding: utf-8 -*-
"""
其他功能工作台路由聚合入口 (Other Tools & Automation Pipelines)
职责：
- 维护共享目录配置、线程安全运行态快照与公共辅助函数；
- 聚合挂载 mail_pipeline_routes、sangon_16s_routes、system_routes 三个子路由模块；
- 保持原有外部导入符号与测试 monkeypatch 钩子 100% 向后兼容。
"""
import json
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter

from ..services.other_tools.mail_inbox_browser import list_whitelist_mails
from ..services.other_tools.sangon_mail_scanner import scan_sangon_mails
from ..services.other_tools.sangon_order_inspector import (
    export_sangon_order_csv,
    inspect_sangon_order_dir,
)
from ..services.other_tools.sangon_settings import (
    get_sangon_downloads_dir,
    get_sangon_root,
)
from ..services.other_tools.schemas import (
    SANGON_CSV_HEADERS,
    BrowserEnvRepairRequest,
    MailAuthUpdateRequest,
    MailBatchIgnoreRequest,
    MailCleanupRequest,
    MailConfigUpdateRequest,
    MailFetchRequest,
    MailListRequest,
    MailPackagePreviewRequest,
    MailPackageSendRequest,
    MailPipelineRunRequest,
    MailTestSendPreviewRequest,
    MailTestSendRequest,
    OpenPathRequest,
    SangonAuthUpdateRequest,
    SangonCleanupRequest,
    SangonDownloadRequest,
    SangonIgnoreRequest,
    SangonImportDownloadsRequest,
    SangonInitOrderRequest,
    SangonRunRequest,
    SangonScanMailRequest,
    SangonSendPreviewRequest,
    SangonSendResultRequest,
    SangonSettingsRequest,
)
from ...blast.manager import TaskStatus, get_blast_manager
from ...mail_download.config import load_config
from ...mail_download.downloader import AttachmentSaver
from ...mail_download.fetcher import MailFetcher
from ...mail_download.sender import MailSender
from ...utils.headless_browser_manager import (
    inspect_headless_browser,
    repair_headless_browser,
)
from ...utils.translation.biology_translator import get_global_biology_translator
from .other_tools_modules.mail_pipeline_routes import (
    _append_mail_pipeline_log,
    _infer_mail_stage,
    _mail_auth_info,
    _resolve_outbound_zip_path,
    cleanup_mail_pipeline_history,
    get_mail_pipeline_overview,
    list_mail_inbox,
    mail_router,
    preview_mail_pipeline_package,
    preview_mail_pipeline_test_send,
    send_mail_pipeline_package,
    test_mail_pipeline_send,
    toggle_mail_pipeline_batch_ignore,
    trigger_mail_auto_pipeline,
    trigger_mail_fetch,
    update_mail_auth,
    update_mail_pipeline_config,
)
from .other_tools_modules.sangon_16s_routes import (
    _execute_sangon_dirs_pipeline,
    _resolve_sangon_order_csv_path,
    cleanup_sangon_orders,
    download_sangon_orders_endpoint,
    get_sangon_16s_overview,
    get_sangon_order_results,
    import_sangon_downloads,
    init_sangon_order_directory,
    preview_sangon_order_result_mail,
    run_sangon_16s_pipeline,
    sangon_router,
    scan_sangon_notification_mails,
    send_sangon_order_result_mail,
    update_sangon_auth_credentials,
    update_sangon_ignored_orders,
    update_sangon_settings,
)
from .other_tools_modules.system_routes import (
    get_browser_env_status,
    open_local_path,
    repair_browser_env,
    system_router,
)

logger = logging.getLogger("api.other_tools")
router = APIRouter(prefix="/other_tools", tags=["other_tools"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_JSON_PATH = PROJECT_ROOT / "config.json"
MAIL_CONFIG_PATH = PROJECT_ROOT / "mail_config.json"
ANNOTATIONS_DIR = PROJECT_ROOT / "results" / "annotations"
BLAST_RESULTS_ROOT = PROJECT_ROOT / "results" / "blast"


def _resolve_dir(value: str) -> Path:
    """配置中的目录：绝对路径原样使用，相对路径基于项目根目录。"""
    p = Path(value)
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()


def _read_mail_cfg() -> Dict[str, Any]:
    if MAIL_CONFIG_PATH.exists():
        try:
            return json.loads(MAIL_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取 mail_config.json 失败: {e}")
    return {}


def _sangon_root_or_default(value: Optional[str]) -> Path:
    return Path(value) if value else get_sangon_root()


def _sangon_downloads_or_default(value: Optional[str]) -> Path:
    return Path(value) if value else get_sangon_downloads_dir()


def _inspect_sangon_order_dir(order_dir: Path) -> Dict[str, Any]:
    """解析单个生工 16S 订单目录状态（委派至 sangon_order_inspector）"""
    return inspect_sangon_order_dir(order_dir, project_root=PROJECT_ROOT)


def _export_sangon_order_csv(task_id: str, out_dir: Path) -> Dict[str, int]:
    """解析 BLAST 报告并调用 BiologyTranslator 翻译导出 11 列 16S鉴定结果.csv"""
    return export_sangon_order_csv(
        task_id,
        out_dir,
        project_root=PROJECT_ROOT,
        translator_factory=get_global_biology_translator,
    )


# ─── 全局运行状态追踪 ─────────────────────────────────────────
_mail_pipeline_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_exit_code": None,
    "last_command": "",
    "last_output": "",
    "current_stage": "idle",
}

_sangon_pipeline_lock = threading.Lock()

_sangon_pipeline_state: Dict[str, Any] = {
    "running": False,
    "current_order": None,
    "current_stage": "idle",
    "progress": 0,
    "started_at": None,
    "finished_at": None,
    "last_message": "",
    "summary": {"total": 0, "processed": 0, "skipped_missing": 0, "failed": 0},
    "logs": [],
}


def _snapshot_sangon_runtime() -> Dict[str, Any]:
    """返回生工 16S 运行态浅拷贝快照，防止序列化期间日志或摘要被后台线程并发修改。"""
    with _sangon_pipeline_lock:
        return {
            **_sangon_pipeline_state,
            "summary": dict(_sangon_pipeline_state.get("summary") or {}),
            "logs": list(_sangon_pipeline_state.get("logs") or []),
        }


def _append_sangon_log(msg: str, level: str = "info") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _sangon_pipeline_lock:
        _sangon_pipeline_state["last_message"] = msg
        logs = _sangon_pipeline_state["logs"]
        logs.append(f"[{ts}] {msg}")
        if len(logs) > 500:
            del logs[:-500]
    log_fn = getattr(logger, level, logger.info)
    log_fn("[Sangon16S] %s", msg)


router.include_router(mail_router)
router.include_router(sangon_router)
router.include_router(system_router)

__all__ = [
    "router",
    "subprocess",
    "TaskStatus",
    "SANGON_CSV_HEADERS",
    "BrowserEnvRepairRequest",
    "MailAuthUpdateRequest",
    "MailBatchIgnoreRequest",
    "MailCleanupRequest",
    "MailConfigUpdateRequest",
    "MailFetchRequest",
    "MailListRequest",
    "MailPackagePreviewRequest",
    "MailPackageSendRequest",
    "MailPipelineRunRequest",
    "MailTestSendPreviewRequest",
    "MailTestSendRequest",
    "OpenPathRequest",
    "SangonAuthUpdateRequest",
    "SangonCleanupRequest",
    "SangonDownloadRequest",
    "SangonIgnoreRequest",
    "SangonImportDownloadsRequest",
    "SangonInitOrderRequest",
    "SangonRunRequest",
    "SangonScanMailRequest",
    "SangonSendPreviewRequest",
    "SangonSendResultRequest",
    "SangonSettingsRequest",
    "load_config",
    "MailSender",
    "MailFetcher",
    "AttachmentSaver",
    "list_whitelist_mails",
    "scan_sangon_mails",
    "get_blast_manager",
    "inspect_headless_browser",
    "repair_headless_browser",
    "get_global_biology_translator",
    "get_mail_pipeline_overview",
    "update_mail_pipeline_config",
    "update_mail_auth",
    "cleanup_mail_pipeline_history",
    "toggle_mail_pipeline_batch_ignore",
    "list_mail_inbox",
    "trigger_mail_fetch",
    "trigger_mail_auto_pipeline",
    "preview_mail_pipeline_test_send",
    "test_mail_pipeline_send",
    "preview_mail_pipeline_package",
    "send_mail_pipeline_package",
    "get_sangon_16s_overview",
    "get_sangon_order_results",
    "scan_sangon_notification_mails",
    "init_sangon_order_directory",
    "run_sangon_16s_pipeline",
    "update_sangon_auth_credentials",
    "download_sangon_orders_endpoint",
    "import_sangon_downloads",
    "preview_sangon_order_result_mail",
    "send_sangon_order_result_mail",
    "update_sangon_settings",
    "update_sangon_ignored_orders",
    "cleanup_sangon_orders",
    "get_browser_env_status",
    "repair_browser_env",
    "open_local_path",
    "_mail_auth_info",
    "_append_mail_pipeline_log",
    "_infer_mail_stage",
    "_resolve_outbound_zip_path",
    "_execute_sangon_dirs_pipeline",
    "_resolve_sangon_order_csv_path",
]
