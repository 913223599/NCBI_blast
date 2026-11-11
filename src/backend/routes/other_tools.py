# -*- coding: utf-8 -*-
"""
其他功能工作台路由模块 (Other Tools & Automation Pipelines)
职责：
1. 邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 全链路状态监控、配置管理与手动/批次触发；
2. 生工 16S 测序结果通知邮件扫描、订单目录管理、自动解压、16S BLAST 比对、物种中文翻译与 11 列 GUI 格式 CSV 导出及在线预览。
"""
import asyncio
import csv
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from ..utils.blast_utils import parse_blast_csv, select_consensus_hit
from ..services.other_tools.dir_migrator import migrate_directory
from ..services.other_tools.history_cleaner import cleanup_mail_history, cleanup_sangon_history
from ..services.other_tools.mail_inbox_browser import list_whitelist_mails
from ..services.other_tools.sangon_mail_scanner import init_sangon_order_dir, scan_sangon_mails
from ..services.other_tools.sangon_order_annotator import annotate_sangon_orders
from ..services.other_tools.sangon_settings import (
    get_sangon_downloads_dir,
    get_sangon_root,
    load_sangon_settings,
    save_sangon_settings,
)
from ..services.other_tools.sangon_zip_importer import (
    import_order_zips_from_downloads,
    scan_downloads_for_sangon_zips,
)
from ..services.other_tools.secret_store import mask_secret, read_secret, resolve_secret_path, write_secret
from ...blast.manager import get_blast_manager, TaskStatus
from ...mail_download.batch_state import inspect_batch_pipeline_state, load_batch_manifest
from ...mail_download.config import load_config
from ...mail_download.downloader import AttachmentSaver
from ...mail_download.fetcher import MailFetcher
from ...mail_download.sender import MailSender
from ...utils.translation.biology_translator import get_global_biology_translator

logger = logging.getLogger("api.other_tools")
router = APIRouter(prefix="/other_tools", tags=["other_tools"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
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


def _resolve_send_target(cfg: Any, to_arg: Optional[str]) -> str:
    """解析目标收件人：留空或传入 self 时安全回退到自身发件/收件账号，绝不误发外部邮箱。"""
    val = (to_arg or "").strip()
    if not val or val.lower() == "self":
        return (getattr(cfg, "smtp_account", "") or getattr(cfg, "account", "") or "").strip()
    return val

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

_sangon_pipeline_state: Dict[str, Any] = {
    "running": False,
    "current_order": None,
    "current_stage": "idle",
    "progress": 0,
    "started_at": None,
    "finished_at": None,
    "last_message": "",
    "logs": [],
}

SANGON_CSV_HEADERS = [
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


# ─── Pydantic 请求模型 ───────────────────────────────────────
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
    subject: Optional[str] = None
    extra_note: Optional[str] = None


class MailTestSendRequest(BaseModel):
    to: Optional[str] = None
    subject: Optional[str] = None
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


class SangonImportDownloadsRequest(BaseModel):
    sangon_root: Optional[str] = None
    downloads_dir: Optional[str] = None
    order_names: List[str] = []
    auto_create_order: bool = False


class SangonSendResultRequest(BaseModel):
    order_dir_name: str
    sangon_root: Optional[str] = None
    to: Optional[str] = None
    subject: Optional[str] = None
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


# ==============================================================================
# 1. 邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 接口
# ==============================================================================

@router.get("/mail_pipeline/overview")
async def get_mail_pipeline_overview():
    """获取邮件自动注释回传流水线完整状态、批次列表、已发记录与日志"""
    raw_cfg = _read_mail_cfg()
    auth_info = _mail_auth_info(raw_cfg)
    auth_ready = auth_info["imap_ready"]

    dl_dir = _resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))
    send_dir = _resolve_dir(raw_cfg.get("send_dir", "results/email_sends"))

    # 1. 已处理指纹索引
    processed_items: List[Dict[str, Any]] = []
    idx_file = dl_dir / "processed_index.json"
    if idx_file.exists():
        try:
            idx_data = json.loads(idx_file.read_text(encoding="utf-8"))
            if isinstance(idx_data, dict):
                for sha, meta in idx_data.items():
                    if isinstance(meta, dict):
                        processed_items.append(meta)
                processed_items.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
        except Exception as e:
            logger.warning(f"解析 processed_index.json 失败: {e}")

    # 2. 已下载批次目录 (up_*) 并检测流水线状态
    cfg_obj = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
    batches: List[Dict[str, Any]] = []
    if dl_dir.exists():
        for bdir in sorted(dl_dir.glob("up_*"), key=lambda p: p.name, reverse=True):
            if not bdir.is_dir():
                continue
            mf = load_batch_manifest(bdir)
            mail_meta: Dict[str, Any] = mf.get("mail", {}) if isinstance(mf.get("mail"), dict) else {}
            att_list: List[Dict[str, Any]] = mf.get("attachments", []) if isinstance(mf.get("attachments"), list) else []
            dl_time = str(mf.get("download_time", "") or "")
            if not att_list:
                for fp in bdir.glob("*"):
                    if fp.is_file() and fp.name != "manifest.json":
                        att_list.append({
                            "filename": fp.name,
                            "size_bytes": fp.stat().st_size,
                            "path": str(fp),
                        })
            state = inspect_batch_pipeline_state(bdir, cfg_obj, send_dir, ANNOTATIONS_DIR, manifest=mf)
            batches.append({
                "batch_name": bdir.name,
                "batch_path": str(bdir),
                "download_time": dl_time or datetime.fromtimestamp(bdir.stat().st_mtime).isoformat(timespec="seconds"),
                "sender": mail_meta.get("sender", "-"),
                "subject": mail_meta.get("subject", "-"),
                "mail_date": mail_meta.get("date", "-"),
                "attachments": att_list,
                "pipeline_status": state["status"],
                "pipeline_status_label": state["status_label"],
                "send_status": state["send_status"],
                "task_ids": state["task_ids"],
                "last_error": state["last_error"],
                "pending": state["pending"],
            })
    pending_batches_count = sum(1 for item in batches if item.get("pending"))

    # 3. 已打包与回传产物 (results/email_sends)
    outbound_packages: List[Dict[str, Any]] = []
    docx_reports: List[Dict[str, Any]] = []
    seen_docx_names = set()
    if send_dir.exists():
        for mf in sorted(send_dir.glob("*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                mdata = json.loads(mf.read_text(encoding="utf-8"))
                zip_name = mdata.get("zip", "")
                zip_path = send_dir / zip_name if zip_name else None
                size_bytes = zip_path.stat().st_size if (zip_path and zip_path.exists()) else 0
                outbound_packages.append({
                    "task_id": mdata.get("task_id", mf.stem),
                    "pack_time": mdata.get("pack_time", ""),
                    "zip_name": zip_name,
                    "zip_path": str(zip_path) if zip_path else "",
                    "size_kb": round(size_bytes / 1024, 1),
                    "file_count": mdata.get("file_count", 0),
                    "files": mdata.get("files", []),
                })
            except Exception:
                pass

        for docx in sorted(send_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
            seen_docx_names.add(docx.name)
            docx_reports.append({
                "name": docx.name,
                "path": str(docx),
                "size_kb": round(docx.stat().st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(docx.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "source": "send_dir",
            })

    # 补充关联回传包对应注释产物目录中的 Word 报告（兼容未同步复制至 send_dir 的历史报告）
    if ANNOTATIONS_DIR.exists():
        for pkg in outbound_packages:
            tid = str(pkg.get("task_id") or "").strip()
            if not tid:
                continue
            anno_dir = ANNOTATIONS_DIR / tid
            if not anno_dir.is_dir():
                continue
            for docx in sorted(anno_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
                if docx.name in seen_docx_names:
                    continue
                seen_docx_names.add(docx.name)
                docx_reports.append({
                    "name": docx.name,
                    "path": str(docx),
                    "size_kb": round(docx.stat().st_size / 1024, 1),
                    "mtime": datetime.fromtimestamp(docx.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "annotations",
                })
        docx_reports.sort(key=lambda item: item.get("mtime", ""), reverse=True)

    # 4. 读取 pipeline.log 最后 120 行
    log_lines: List[str] = []
    log_file = dl_dir / "pipeline.log"
    if log_file.exists():
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            log_lines = all_lines[-120:]
        except Exception:
            pass

    return {
        "status": "success",
        "config": raw_cfg,
        "auth_ready": auth_ready,
        "auth": auth_info,
        "resolved_download_dir": str(dl_dir),
        "resolved_send_dir": str(send_dir),
        "runtime": _mail_pipeline_state,
        "processed_count": len(processed_items),
        "processed_items": processed_items,
        "batches": batches,
        "pending_batches_count": pending_batches_count,
        "outbound_packages": outbound_packages,
        "docx_reports": docx_reports,
        "pipeline_logs": log_lines,
    }


@router.post("/mail_pipeline/config")
async def update_mail_pipeline_config(req: MailConfigUpdateRequest):
    """更新保存 mail_config.json；下载/回传目录变更时自动迁移已有数据"""
    existing = _read_mail_cfg()

    old_dl = _resolve_dir(existing.get("download_dir", "results/email_downloads"))
    old_send = _resolve_dir(existing.get("send_dir", "results/email_sends"))
    new_dl = _resolve_dir(req.download_dir.strip())
    new_send = _resolve_dir(req.send_dir.strip())
    dir_changed = (old_dl != new_dl) or (old_send != new_send)
    if dir_changed and _mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能修改目录")

    migrations: List[Dict[str, Any]] = []
    if req.migrate:
        try:
            if old_dl != new_dl:
                migrations.append(await asyncio.to_thread(migrate_directory, old_dl, new_dl))
            if old_send != new_send:
                migrations.append(await asyncio.to_thread(migrate_directory, old_send, new_send))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"目录迁移失败: {e}")

    updated = {
        **existing,
        "imap_server": req.imap_server.strip(),
        "imap_port": req.imap_port,
        "account": req.account.strip(),
        "sender_whitelist": [s.strip() for s in req.sender_whitelist if s.strip()],
        "subject_keywords": [s.strip() for s in req.subject_keywords if s.strip()],
        "attachment_exts": [s.strip() for s in req.attachment_exts if s.strip()],
        "max_attach_size_mb": req.max_attach_size_mb,
        "since_days": req.since_days,
        "download_dir": req.download_dir.strip(),
        "mark_seen": req.mark_seen,
        "smtp_server": req.smtp_server.strip(),
        "smtp_port": req.smtp_port,
        "smtp_account": req.smtp_account.strip(),
        "smtp_display_name": req.smtp_display_name.strip(),
        "reply_to": req.reply_to.strip(),
        "send_dir": req.send_dir.strip(),
    }
    MAIL_CONFIG_PATH.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "success", "config": updated, "migrations": migrations}


def _mail_auth_info(raw_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """汇总 IMAP / SMTP 授权码状态（仅返回掩码）"""
    cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
    imap_file = resolve_secret_path(PROJECT_ROOT, raw_cfg.get("auth_code_file", ".mail_auth"))
    smtp_file = resolve_secret_path(PROJECT_ROOT, raw_cfg.get("smtp_auth_code_file", ".mail_smtp_auth"))
    imap_code = cfg.auth_code
    smtp_code = cfg.smtp_auth_code
    return {
        "imap_ready": bool(imap_code),
        "imap_masked": mask_secret(imap_code),
        "imap_file": str(imap_file),
        "smtp_ready": bool(smtp_code),
        "smtp_masked": mask_secret(smtp_code),
        "smtp_file": str(smtp_file),
        "smtp_separate": bool(read_secret(smtp_file)),
    }


@router.post("/mail_pipeline/auth")
async def update_mail_auth(req: MailAuthUpdateRequest):
    """更新邮箱授权码：写入独立密钥文件（不入库），返回掩码"""
    raw_cfg = _read_mail_cfg()
    if req.imap_auth_code is not None:
        write_secret(resolve_secret_path(PROJECT_ROOT, raw_cfg.get("auth_code_file", ".mail_auth")), req.imap_auth_code)
    if req.smtp_auth_code is not None:
        write_secret(resolve_secret_path(PROJECT_ROOT, raw_cfg.get("smtp_auth_code_file", ".mail_smtp_auth")), req.smtp_auth_code)
    return {"status": "success", "auth": _mail_auth_info(raw_cfg)}


@router.post("/mail_pipeline/cleanup")
async def cleanup_mail_pipeline_history(req: MailCleanupRequest):
    """清理邮件流水线历史数据（批次 / 回传包 / 报告 / 注释中间目录 / 去重索引 / 日志）"""
    if _mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能清理")
    if not req.targets:
        raise HTTPException(status_code=400, detail="未选择清理项")
    raw_cfg = _read_mail_cfg()
    res = await asyncio.to_thread(
        cleanup_mail_history,
        _resolve_dir(raw_cfg.get("download_dir", "results/email_downloads")),
        _resolve_dir(raw_cfg.get("send_dir", "results/email_sends")),
        ANNOTATIONS_DIR,
        req.targets,
        req.older_than_days,
        req.names,
    )
    return {"status": "success", **res}


@router.post("/mail_pipeline/list_mails")
async def list_mail_inbox(req: MailListRequest):
    """分页浏览并去重展示发件人白名单内的收件箱邮件"""
    def _do_list():
        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=True)
        return list_whitelist_mails(
            cfg,
            page=req.page,
            page_size=req.page_size,
            since_days=req.since_days,
            dedup=req.dedup,
            only_new=req.only_new,
        )

    try:
        res = await asyncio.to_thread(_do_list)
        return {"status": "success", **res}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"拉取收件箱失败: {e}")


def _append_mail_pipeline_log(dl_dir: Path, level: str, msg: str) -> None:
    """向 pipeline.log 追加审计日志行。"""
    try:
        dl_dir.mkdir(parents=True, exist_ok=True)
        log_file = dl_dir / "pipeline.log"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} [{level.upper()}] {msg}\n")
    except OSError as exc:
        logger.warning(f"写入 pipeline.log 失败: {exc}")


def _infer_mail_stage(line: str, current: str) -> str:
    """从流水线实时日志行推断当前阶段标识。"""
    if "[收件]" in line:
        return "fetching"
    if "[队列]" in line or "[批次]" in line:
        return "queued"
    if "[注释]" in line:
        return "annotating"
    if "[报告]" in line:
        return "reporting"
    if "[打包]" in line:
        return "packing"
    if "[回传]" in line:
        return "sending"
    return current


@router.post("/mail_pipeline/fetch")
async def trigger_mail_fetch(req: MailFetchRequest):
    """立即扫描 IMAP 收件箱并保存新附件"""
    def _do_fetch():
        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=True)
        fetcher = MailFetcher(cfg)
        f_res = fetcher.fetch(since_days=req.since_days)
        if f_res.connection_error:
            _append_mail_pipeline_log(cfg.resolved_download_dir, "error", f"仅收件失败: {f_res.connection_error}")
            return {"ok": False, "error": f_res.connection_error}
        saved_stats = {"count": 0, "skipped_duplicates": 0, "skipped_processed": 0, "saved_files": []}
        if f_res.matched:
            saver = AttachmentSaver(cfg.resolved_download_dir)
            saved_stats = saver.save(f_res.matched)
        _append_mail_pipeline_log(
            cfg.resolved_download_dir,
            "info",
            f"仅收件扫描: 共 {f_res.scanned} 封, 命中 {len(f_res.matched)} 封, "
            f"新保存 {saved_stats['count']} 个附件 (重复 {saved_stats['skipped_duplicates']}, 去重 {saved_stats['skipped_processed']})",
        )
        return {
            "ok": True,
            "scanned": f_res.scanned,
            "matched": len(f_res.matched),
            "skipped_dup_mails": getattr(f_res, "skipped_dup_mails", 0),
            "saved_count": saved_stats["count"],
            "skipped_duplicates": saved_stats["skipped_duplicates"],
            "skipped_processed": saved_stats["skipped_processed"],
            "saved_files": saved_stats["saved_files"],
        }

    try:
        res = await asyncio.to_thread(_do_fetch)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("error", "邮箱连接失败"))
        return {"status": "success", **res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mail_pipeline/run")
async def trigger_mail_auto_pipeline(req: MailPipelineRunRequest):
    """后台异步启动完整自动流水线 (收件 + 待处理接续 -> 注释 -> Word 报告 -> 打包 -> SMTP 回传)"""
    if _mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="邮件自动注释流水线正在运行中，请等待当前任务结束")

    raw_cfg = _read_mail_cfg()
    cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=False)
    dl_dir = _resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))

    resolved_to: Optional[str] = None
    if req.to is not None and str(req.to).strip():
        resolved_to = _resolve_send_target(cfg, req.to)
        if not resolved_to:
            raise HTTPException(status_code=400, detail="未配置发件或收件邮箱账号，无法解析目标收件人")

    cmd = [sys.executable, "-X", "utf8", "-u", "-m", "src.mail_download.auto_pipeline", "--config", str(MAIL_CONFIG_PATH)]
    if req.since_days is not None:
        cmd += ["--since-days", str(req.since_days)]
    if req.no_send:
        cmd.append("--no-send")
    if req.annotate_only_batch:
        raw_batch = req.annotate_only_batch.strip()
        if not raw_batch or ".." in Path(raw_batch).parts:
            raise HTTPException(status_code=400, detail=f"非法的批次目录: {req.annotate_only_batch}")
        batch_path = Path(raw_batch) if os.path.isabs(raw_batch) else (dl_dir / raw_batch)
        if not batch_path.exists() or not batch_path.is_dir():
            raise HTTPException(status_code=404, detail=f"未找到批次目录: {raw_batch}")
        cmd += ["--annotate-only", str(batch_path)]
        if req.force_send and not req.no_send and not resolved_to:
            cmd.append("--send")
    if req.test_input:
        tp = Path(req.test_input.strip())
        if not tp.is_absolute():
            tp = PROJECT_ROOT / tp
        if not tp.exists() or not tp.is_file():
            raise HTTPException(status_code=404, detail=f"未找到测试输入文件: {req.test_input}")
        cmd += ["--test-input", str(tp)]
    if resolved_to:
        cmd += ["--to", resolved_to]
    if req.subject_prefix:
        cmd += ["--subject-prefix", req.subject_prefix]
    if req.extra_note:
        cmd += ["--extra-note", req.extra_note]

    _mail_pipeline_state["running"] = True
    _mail_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _mail_pipeline_state["finished_at"] = None
    _mail_pipeline_state["last_exit_code"] = None
    _mail_pipeline_state["last_command"] = " ".join(cmd)
    _mail_pipeline_state["last_output"] = "流水线已启动，正在连接收件/扫描待处理批次..."
    _mail_pipeline_state["current_stage"] = "fetching"

    logger.info(
        f"[MailPipeline] 后台任务启动: batch={req.annotate_only_batch or 'ALL'}, "
        f"since_days={req.since_days}, no_send={req.no_send}, to={resolved_to or 'config'}"
    )

    def _run_bg():
        import threading

        lines_buf: List[str] = []
        timer: Optional[threading.Timer] = None
        proc = None
        timed_out = False
        try:
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )

            def _on_timeout():
                nonlocal timed_out
                timed_out = True
                if proc is not None and proc.poll() is None:
                    proc.kill()

            timer = threading.Timer(3600, _on_timeout)
            timer.daemon = True
            timer.start()

            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\r\n")
                    if not line:
                        continue
                    lines_buf.append(line)
                    if len(lines_buf) > 200:
                        lines_buf = lines_buf[-200:]
                    _mail_pipeline_state["last_output"] = "\n".join(lines_buf)[-4000:]
                    _mail_pipeline_state["current_stage"] = _infer_mail_stage(
                        line, _mail_pipeline_state.get("current_stage", "running")
                    )

            rc = proc.wait()
            if timed_out:
                rc = -1
                lines_buf.append("[错误] 流水线执行超时（超过 3600 秒）")
            _mail_pipeline_state["last_exit_code"] = rc
            final_out = "\n".join(lines_buf).strip()[-4000:]
            _mail_pipeline_state["last_output"] = final_out or ("执行完成" if rc == 0 else f"退出码 {rc}")
            _mail_pipeline_state["current_stage"] = "completed" if rc == 0 else "failed"
            logger.info(f"[MailPipeline] 后台任务结束: exit={rc}, stage={_mail_pipeline_state['current_stage']}")
        except Exception as exc:
            _mail_pipeline_state["last_exit_code"] = -1
            _mail_pipeline_state["last_output"] = f"执行异常: {exc}"
            _mail_pipeline_state["current_stage"] = "failed"
            logger.error(f"[MailPipeline] 后台任务异常: {exc}")
        finally:
            if timer is not None:
                timer.cancel()
            _mail_pipeline_state["running"] = False
            _mail_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    asyncio.get_running_loop().run_in_executor(None, _run_bg)
    return {"status": "started", "runtime": _mail_pipeline_state}


@router.post("/mail_pipeline/test_send")
async def test_mail_pipeline_send(req: Optional[MailTestSendRequest] = Body(default=None)):
    """轻量测试 SMTP 发信链路：打包验证文本（可选附带最新 Word 报告）发送到自身或指定邮箱。"""
    params = req or MailTestSendRequest()

    def _do_test_send():
        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=False)
        target_to = _resolve_send_target(cfg, params.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再测试发信")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        subject = (params.subject or f"【自检验证】邮件自动回传 SMTP 测试 ({stamp})").strip()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / f"SMTP_自检验证包_{stamp}.zip"
            attached_files = ["smtp_self_test.txt"]

            txt_lines = [
                "邮件自动回传工作台 SMTP 链路自检报告",
                f"发送时间: {now_str}",
                f"SMTP 服务器: {cfg.smtp_server}:{cfg.smtp_port}",
                f"发件账号: {cfg.smtp_account}",
                f"目标收件人: {target_to}",
                f"主题: {subject}",
                f"中文与 UTF-8 附件名编码验证: 正常 ({zip_path.name})",
            ]
            if params.note and params.note.strip():
                txt_lines.append(f"附加备注: {params.note.strip()}")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("smtp_self_test.txt", "\n".join(txt_lines).encode("utf-8"))
                if params.attach_latest_report:
                    send_dir = _resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
                    docx_list: List[Path] = []
                    if send_dir.exists():
                        docx_list = sorted(send_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if not docx_list and ANNOTATIONS_DIR.exists():
                        docx_list = sorted(ANNOTATIONS_DIR.rglob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if docx_list:
                        zf.writestr(docx_list[0].name, docx_list[0].read_bytes())
                        attached_files.append(docx_list[0].name)

            body_lines = [
                "您好：",
                "",
                "本邮件为 NCBI Pro 邮件自动回传流水线的 SMTP 发信自检测试邮件。",
                f"发件账号：{cfg.smtp_account}",
                f"目标收件人：{target_to}",
                f"验证时间：{now_str}",
                f"测试附件：{zip_path.name}（包含 {', '.join(attached_files)}）",
            ]
            if params.note and params.note.strip():
                body_lines.append(f"备注信息：{params.note.strip()}")
            body_lines.append("")
            body_lines.append("若您顺利收到本邮件且附件中文名称显示正常，即表示 SMTP 链路畅通。")

            sender = MailSender(cfg)
            res = sender.send(zip_path, to=target_to, subject=subject, body="\n".join(body_lines))
            return res, zip_path.name, attached_files

    try:
        res, zip_name, attached_files = await asyncio.to_thread(_do_test_send)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试发信异常: {e}")

    if not res.ok:
        raise HTTPException(status_code=400, detail=f"发送失败 ({res.stage}): {res.error}")

    return {
        "status": "success",
        "ok": True,
        "to": res.to,
        "subject": res.subject,
        "stage": res.stage,
        "attachment": zip_name,
        "attachment_size": res.attachment_size,
        "attached_files": attached_files,
    }


@router.post("/mail_pipeline/send_package")
async def send_mail_pipeline_package(req: MailPackageSendRequest):
    """将已打包的注释结果压缩包通过 SMTP 发送至本人或指定邮箱。"""
    clean_zip = (req.zip_name or "").strip()
    if (
        not clean_zip
        or any(sep in clean_zip for sep in ("/", "\\", ".."))
        or not clean_zip.lower().endswith(".zip")
    ):
        raise HTTPException(status_code=400, detail=f"非法的压缩包文件名: {req.zip_name}")

    def _do_send_package():
        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=False)
        send_dir = _resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
        zip_path = send_dir / clean_zip
        if not zip_path.exists() or not zip_path.is_file() or zip_path.parent.resolve() != send_dir.resolve():
            raise FileNotFoundError(f"未找到回传压缩包: {clean_zip}")

        target_to = _resolve_send_target(cfg, req.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再发送邮件")

        task_id = zip_path.stem
        pack_time = ""
        file_names: List[str] = []
        manifest_path = send_dir / f"{zip_path.stem}.manifest.json"
        if manifest_path.is_file():
            try:
                mdata = json.loads(manifest_path.read_text(encoding="utf-8"))
                task_id = str(mdata.get("task_id") or task_id)
                pack_time = str(mdata.get("pack_time") or "")
                for entry in mdata.get("files") or []:
                    if isinstance(entry, dict) and entry.get("name"):
                        file_names.append(str(entry["name"]))
                    elif isinstance(entry, str):
                        file_names.append(entry)
            except Exception:
                pass
        if not file_names:
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    file_names = list(zf.namelist())
            except Exception:
                pass

        docx_names = [n for n in file_names if n.lower().endswith(".docx")]
        subject = (req.subject or f"噬菌体注释结果回传 - {task_id}").strip()
        preview = file_names[:20]
        if len(file_names) > 20:
            preview.append(f"...（其余 {len(file_names) - 20} 个文件）")

        body_lines = [
            "您好：",
            "",
            f"现发送噬菌体基因组注释任务 {task_id} 的结果压缩包：",
            f"  附件文件名：{zip_path.name}",
            f"  文件大小：{zip_path.stat().st_size / 1024:.1f} KB",
            f"  内含产物数：{len(file_names)} 个",
        ]
        if pack_time:
            body_lines.append(f"  打包时间：{pack_time}")
        if docx_names:
            body_lines.append(f"  包含 Word 报告：{', '.join(docx_names)}")
        if req.extra_note and req.extra_note.strip():
            body_lines.append(f"  附加备注：{req.extra_note.strip()}")
        if preview:
            body_lines.append("")
            body_lines.append("压缩包内文件清单：")
            body_lines.extend(f"  - {name}" for name in preview)
        body_lines.extend(["", "如需进一步分析或调整，请回复本邮件。", ""])

        res = MailSender(cfg).send(zip_path, to=target_to, subject=subject, body="\n".join(body_lines))
        return res, task_id, len(file_names)

    try:
        res, task_id, file_count = await asyncio.to_thread(_do_send_package)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送结果压缩包异常: {e}")

    if not res.ok:
        raise HTTPException(status_code=400, detail=f"发送失败 ({res.stage}): {res.error}")

    return {
        "status": "success",
        "ok": True,
        "zip_name": clean_zip,
        "task_id": task_id,
        "to": res.to,
        "subject": res.subject,
        "stage": res.stage,
        "attachment": clean_zip,
        "attachment_size": res.attachment_size,
        "file_count": file_count,
    }


# ==============================================================================
# 2. 生工 16S 测序结果自动化 BLAST 与导出流程 接口
# ==============================================================================

def _inspect_sangon_order_dir(order_dir: Path) -> Dict[str, Any]:
    """解析单个生工 16S 订单目录状态"""
    zip_dir = order_dir / "原始压缩包"
    raw_dir = order_dir / "原始数据"
    res_dir = order_dir / "BLAST结果"

    zips = sorted(zip_dir.glob("*.zip")) if zip_dir.exists() else []
    consensus_fastas: List[Path] = []
    ab1_count = 0
    total_raw_files = 0

    if raw_dir.exists():
        for p in raw_dir.rglob("*"):
            if p.is_file():
                total_raw_files += 1
                if p.name.endswith(".1.fasta") and "haplotype" not in p.name.lower():
                    consensus_fastas.append(p)
                elif p.suffix.lower() == ".ab1":
                    ab1_count += 1

    csv_file = res_dir / "16S鉴定结果.csv"
    has_result_csv = csv_file.exists()
    total_rows = 0
    with_hits = 0
    no_hits = 0
    csv_mtime = ""

    if has_result_csv:
        csv_mtime = datetime.fromtimestamp(csv_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(csv_file, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = list(csv.reader(f))
                if len(reader) > 1:
                    for row in reader[1:]:
                        if not row:
                            continue
                        total_rows += 1
                        sp = row[3] if len(row) > 3 else ""
                        if "No Hits" in sp or "未找到匹配项" in sp:
                            no_hits += 1
                        else:
                            with_hits += 1
        except Exception:
            pass

    # 检查 BLAST 任务目录
    task_id = f"{order_dir.name}_16s"
    blast_reports_dir = PROJECT_ROOT / "results" / "blast" / task_id / "reports"
    blast_csv_count = len(list(blast_reports_dir.glob("*.csv"))) if blast_reports_dir.exists() else 0

    parts = order_dir.name.split("_", 1)
    order_date = parts[0] if len(parts) > 1 else ""
    order_no = parts[1] if len(parts) > 1 else order_dir.name

    status = "pending"
    if has_result_csv and total_rows > 0:
        status = "completed"
    elif blast_csv_count > 0:
        status = "blasted"
    elif len(consensus_fastas) > 0:
        status = "extracted"
    elif len(zips) > 0:
        status = "downloaded"

    return {
        "dir_name": order_dir.name,
        "order_date": order_date,
        "order_no": order_no,
        "order_path": str(order_dir),
        "status": status,
        "zip_count": len(zips),
        "zip_files": [{"name": z.name, "size_kb": round(z.stat().st_size / 1024, 1)} for z in zips],
        "raw_file_count": total_raw_files,
        "consensus_fasta_count": len(consensus_fastas),
        "ab1_count": ab1_count,
        "blast_task_id": task_id,
        "blast_report_count": blast_csv_count,
        "has_result_csv": has_result_csv,
        "result_csv_path": str(csv_file) if has_result_csv else "",
        "result_mtime": csv_mtime,
        "total_samples": total_rows,
        "with_hits": with_hits,
        "no_hits": no_hits,
    }


@router.get("/sangon_16s/overview")
async def get_sangon_16s_overview(sangon_root: Optional[str] = None, downloads_dir: Optional[str] = None):
    """获取生工 16S 自动化流程目录、浏览器下载目录待认领压缩包与所有订单状态概览"""
    root_path = _sangon_root_or_default(sangon_root)
    dl_dir = _sangon_downloads_or_default(downloads_dir)
    orders: List[Dict[str, Any]] = []
    order_by_no: Dict[str, Dict[str, Any]] = {}

    if root_path.exists() and root_path.is_dir():
        for child in sorted(root_path.iterdir(), key=lambda p: p.name, reverse=True):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                info = _inspect_sangon_order_dir(child)
                orders.append(info)
                ono = info.get("order_no", "")
                if ono and ono not in order_by_no:
                    order_by_no[ono] = info

    # 扫描本地浏览器下载目录中的生工测序压缩包（每个订单保留最新一条）
    raw_candidates = scan_downloads_for_sangon_zips(dl_dir)
    download_candidates: List[Dict[str, Any]] = []
    seen_dl_orders = set()
    for item in raw_candidates:
        ono = item["order_no"]
        if ono in seen_dl_orders:
            continue
        seen_dl_orders.add(ono)
        matched = order_by_no.get(ono)
        archived = bool(matched and (matched.get("zip_count", 0) > 0 or matched.get("status") == "completed"))
        download_candidates.append({
            **item,
            "matched_dir_name": matched["dir_name"] if matched else "",
            "matched_status": matched["status"] if matched else "uncreated",
            "archived": archived,
        })

    pending_download_count = sum(1 for c in download_candidates if not c["archived"])
    annotate_sangon_orders(root_path, orders, download_candidates)

    db_16s = PROJECT_ROOT / "database" / "16S" / "ncbi" / "16S_ribosomal_RNA.nin"
    return {
        "status": "success",
        "sangon_root": str(root_path),
        "downloads_dir": str(dl_dir),
        "downloads_exists": dl_dir.exists(),
        "download_candidates": download_candidates,
        "pending_download_count": pending_download_count,
        "settings": load_sangon_settings(),
        "root_exists": root_path.exists(),
        "db_16s_ready": db_16s.exists(),
        "runtime": _sangon_pipeline_state,
        "orders": orders,
    }


@router.get("/sangon_16s/order/{order_dir_name}/results")
async def get_sangon_order_results(order_dir_name: str, sangon_root: Optional[str] = None):
    """读取指定生工 16S 订单的 11 列鉴定结果 CSV 供前端在线表格展示"""
    csv_path = _sangon_root_or_default(sangon_root) / order_dir_name / "BLAST结果" / "16S鉴定结果.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到鉴定结果文件: {csv_path}")

    rows: List[Dict[str, str]] = []
    headers: List[str] = SANGON_CSV_HEADERS
    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = list(csv.reader(f))
            if reader:
                headers = reader[0]
                for r in reader[1:]:
                    if not r:
                        continue
                    item = {}
                    for idx, h in enumerate(headers):
                        item[h] = r[idx] if idx < len(r) else ""
                    rows.append(item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 CSV 失败: {e}")

    return {
        "status": "success",
        "order_dir_name": order_dir_name,
        "csv_path": str(csv_path),
        "headers": headers,
        "rows": rows,
    }


@router.post("/sangon_16s/scan_mail")
async def scan_sangon_notification_mails(
    sangon_root: Optional[str] = None,
    req: Optional[SangonScanMailRequest] = Body(default=None),
):
    """连接邮箱扫描生工 (info1@sangon.com) 16S 通知邮件，支持批内/历史去重与服务端翻页"""
    params = req or SangonScanMailRequest()
    root_dir_path = _sangon_root_or_default(params.sangon_root or sangon_root)

    def _do_scan():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=True)
        return scan_sangon_mails(
            root_dir_path,
            cfg,
            page=params.page,
            page_size=params.page_size,
            dedup=params.dedup,
            only_new=params.only_new,
            auto_create=params.auto_create,
            ignore_history=params.ignore_history,
        )

    try:
        res = await asyncio.to_thread(_do_scan)
        return {"status": "success", **res}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描生工邮件失败: {e}")


@router.post("/sangon_16s/init_order")
async def init_sangon_order_directory(req: SangonInitOrderRequest):
    """手动为指定通知邮件初始化生工订单三级目录"""
    root_path = _sangon_root_or_default(req.sangon_root)
    try:
        res = await asyncio.to_thread(
            init_sangon_order_dir,
            root_path,
            req.dir_name,
            order_no=req.order_no,
            subject=req.subject,
            date_text=req.date_text,
            cx_order_id=req.cx_order_id,
            download_url=req.download_url,
        )
        return {"status": "success", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初始化订单目录失败: {e}")


def _sangon_csv_sort_key(p: Path):
    m_num = re.search(r"_-(\d+)(?:_\d+)?\.csv$", p.name)
    if m_num:
        return (0, int(m_num.group(1)), p.name)
    return (1, 0, p.name)


def _export_sangon_order_csv(task_id: str, out_dir: Path) -> Dict[str, int]:
    """解析 BLAST 报告并调用 BiologyTranslator 翻译导出 11 列 16S鉴定结果.csv"""
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = PROJECT_ROOT / "results" / "blast" / task_id / "reports"
    csv_files = sorted(reports_dir.glob("*.csv"), key=_sangon_csv_sort_key) if reports_dir.exists() else []

    all_species = set()
    results = []

    for csv_path in csv_files:
        m = re.search(r"_-(\d+)(?:_\d+)?\.csv$", csv_path.name)
        query_title = f"-{m.group(1)}" if m else csv_path.stem

        hits = parse_blast_csv(str(csv_path), limit=50)
        best = select_consensus_hit(hits) if hits else None
        if not best:
            results.append({
                "queryTitle": query_title,
                "speciesName": "未找到匹配项 (No Hits)",
                "genusStrain": "",
                "geneSource": "",
                "seqType": "",
                "identity": 0.0,
                "evalue": "-",
                "accession": "-",
                "hitTitle": "",
            })
            continue

        species = best.get("species", "Unknown")
        all_species.add(species)
        if best.get("consensusList"):
            for c in best["consensusList"]:
                if c.get("name"):
                    all_species.add(c["name"])

        results.append({
            "queryTitle": query_title,
            "speciesName": species,
            "genusStrain": f"{best.get('genus', '')} · {best.get('strain', '')}".strip(" ·"),
            "geneSource": best.get("gene_type", best.get("gene_source", "")),
            "seqType": best.get("seq_type", ""),
            "identity": float(str(best.get("similarity", "0")).replace("%", "")) if best.get("similarity") else 0.0,
            "evalue": str(best.get("evalue", "N/A")),
            "accession": best.get("acc", "N/A"),
            "hitTitle": best.get("title", ""),
        })

    translator = get_global_biology_translator()
    translated_map = translator.translate_batch(list(all_species), category="species") if all_species else {}

    def _format_row(hit: Dict[str, Any]) -> List[str]:
        full_trans = hit.get("translatedName") or ""
        main_trans = full_trans
        prob_trans = "-"

        full_orig = hit.get("speciesName") or ""
        main_orig = full_orig
        prob_orig = "-"

        if "(" in full_trans and "%" in full_trans:
            m_tr = re.match(r"^([^,(]+)\s*\(", full_trans)
            if m_tr:
                main_trans = m_tr.group(1).strip()
                prob_trans = full_trans

        if "(" in full_orig and "%" in full_orig:
            m_or = re.match(r"^([^,(]+)\s*\(", full_orig)
            if m_or:
                main_orig = m_or.group(1).strip()
                prob_orig = full_orig

        gene_seq = hit.get("geneSource", "")
        if hit.get("seqType"):
            gene_seq = f"{hit.get('geneSource', '')} ({hit.get('seqType', '')})"

        return [
            hit["queryTitle"],
            main_trans,
            prob_trans,
            main_orig,
            prob_orig,
            hit.get("genusStrain", ""),
            gene_seq,
            f"{hit.get('identity', 0.0):.1f}%",
            hit.get("evalue", "-"),
            hit.get("accession", "-"),
            hit.get("hitTitle", ""),
        ]

    for r in results:
        r["translatedName"] = translated_map.get(r["speciesName"])

    out_path = out_dir / "16S鉴定结果.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(SANGON_CSV_HEADERS)
        for r in results:
            writer.writerow(_format_row(r))

    with_hits = sum(1 for r in results if "No Hits" not in r["speciesName"])
    no_hits = sum(1 for r in results if "No Hits" in r["speciesName"])
    return {"total": len(results), "with_hits": with_hits, "no_hits": no_hits}


@router.post("/sangon_16s/run_pipeline")
async def run_sangon_16s_pipeline(req: SangonRunRequest):
    """对选定的生工 16S 订单执行自动解压 -> 16S BLAST 比对 -> 中文翻译与 11 列 CSV 导出"""
    if _sangon_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")

    root_path = _sangon_root_or_default(req.sangon_root)
    if not root_path.exists():
        raise HTTPException(status_code=400, detail=f"生工 16S 目录不存在: {root_path}")

    target_dirs: List[Path] = []
    if req.order_names:
        for name in req.order_names:
            p = root_path / name
            if p.exists() and p.is_dir():
                target_dirs.append(p)
    else:
        for child in sorted(root_path.iterdir()):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                info = _inspect_sangon_order_dir(child)
                if info["status"] != "completed" or req.force_reblast:
                    target_dirs.append(child)

    if not target_dirs:
        raise HTTPException(status_code=400, detail="没有需要处理的订单目录")

    _sangon_pipeline_state["running"] = True
    _sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _sangon_pipeline_state["finished_at"] = None
    _sangon_pipeline_state["progress"] = 0
    _sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] 启动生工 16S 批处理，共 {len(target_dirs)} 个订单"]

    def _append_log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        _sangon_pipeline_state["last_message"] = msg
        _sangon_pipeline_state["logs"].append(f"[{ts}] {msg}")

    def _run_sangon_bg():
        try:
            mgr = get_blast_manager()
            total_orders = len(target_dirs)
            for idx, order_dir in enumerate(target_dirs, start=1):
                _sangon_pipeline_state["current_order"] = order_dir.name
                _sangon_pipeline_state["current_stage"] = "extracting"
                _append_log(f"({idx}/{total_orders}) 正在检查订单目录: {order_dir.name}")

                zip_dir = order_dir / "原始压缩包"
                raw_dir = order_dir / "原始数据"
                res_dir = order_dir / "BLAST结果"
                raw_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(parents=True, exist_ok=True)

                # Step 0: 若原始数据与原始压缩包均为空，自动尝试从浏览器下载目录认领匹配订单包
                fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])
                has_zip = zip_dir.exists() and any(zip_dir.glob("*.zip"))
                if not fastas and not has_zip:
                    dl_dir = _sangon_downloads_or_default(req.downloads_dir)
                    imp = import_order_zips_from_downloads(
                        root_path,
                        dl_dir,
                        order_names=[order_dir.name],
                        auto_create_order=False,
                    )
                    if imp["imported_count"] > 0:
                        _append_log(
                            f"已从下载目录自动认领压缩包: {imp['imported'][0]['zip_name']} -> 原始压缩包/"
                        )

                # Step 1: 若原始数据无 .1.fasta 但原始压缩包有 zip，自动解压
                if not fastas and zip_dir.exists():
                    for zf_path in sorted(zip_dir.glob("*.zip")):
                        _append_log(f"正在解压原始压缩包: {zf_path.name} -> 原始数据/")
                        with zipfile.ZipFile(zf_path, "r") as zf:
                            zf.extractall(raw_dir)
                    fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])

                if not fastas:
                    _append_log(f"[跳过] {order_dir.name} 未找到 *.1.fasta 主序列文件（如刚下载请确认浏览器已完成保存）")
                    continue

                task_name = f"{order_dir.name}_16s"
                task_cache_dir = PROJECT_ROOT / "results" / "blast" / task_name
                reports_dir = task_cache_dir / "reports"

                # 强制重跑时清理旧 BLAST 缓存与数据库记录，避免 BlastEngine 命中既有 reports/*.csv 静默跳过
                if req.force_reblast:
                    _append_log(f"强制重新比对：正在清理旧缓存与记录 ({task_name})")
                    try:
                        mgr.delete_task(task_name)
                    except Exception as del_err:
                        _append_log(f"清理任务数据库记录提示: {del_err}")
                    if task_cache_dir.exists():
                        shutil.rmtree(task_cache_dir, ignore_errors=True)

                existing_csvs = list(reports_dir.glob("*.csv")) if reports_dir.exists() else []

                # Step 2: 运行 16S BLAST
                if len(existing_csvs) < len(fastas) or req.force_reblast:
                    _sangon_pipeline_state["current_stage"] = "blasting"
                    _append_log(f"提交 16S BLAST 比对任务 ({len(fastas)} 条主序列): {task_name}")
                    task_id = mgr.create_task({
                        "task_name": task_name,
                        "files": [str(p) for p in fastas],
                        "program": "auto",
                        "database": "ncbi_16s",
                        "evalue": req.evalue,
                        "hitlist_size": req.hitlist_size,
                        "max_workers": 2,
                        "request_timeout": 10,
                    })
                    while True:
                        st_info = mgr.get_task_status(task_id)
                        if not st_info:
                            break
                        st = st_info.get("status", "unknown")
                        prog = st_info.get("progress", 0)
                        _sangon_pipeline_state["progress"] = prog
                        if st in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
                            _append_log(f"BLAST 任务结束: {st} (进度 {prog}%)")
                            break
                        time.sleep(2)
                else:
                    _append_log(f"复用已有 BLAST 报告 ({len(existing_csvs)} 份 CSV)")

                # Step 3: 翻译并导出 11 列 CSV
                _sangon_pipeline_state["current_stage"] = "exporting"
                _append_log(f"正在执行物种拉丁文批量翻译并导出 16S鉴定结果.csv ...")
                stats = _export_sangon_order_csv(task_name, res_dir)
                _append_log(
                    f"订单 {order_dir.name} 导出完成: 共 {stats['total']} 样本, "
                    f"命中 {stats['with_hits']}, 未命中 {stats['no_hits']}"
                )
                _sangon_pipeline_state["progress"] = int(idx * 100 / total_orders)

            _sangon_pipeline_state["current_stage"] = "completed"
            _append_log("全部生工 16S 订单处理完毕")
        except Exception as exc:
            _sangon_pipeline_state["current_stage"] = "failed"
            _append_log(f"执行异常: {exc}")
        finally:
            _sangon_pipeline_state["running"] = False
            _sangon_pipeline_state["current_order"] = None
            _sangon_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    asyncio.get_running_loop().run_in_executor(None, _run_sangon_bg)
    return {"status": "started", "runtime": _sangon_pipeline_state}


@router.post("/sangon_16s/import_downloads")
async def import_sangon_downloads(req: Optional[SangonImportDownloadsRequest] = Body(default=None)):
    """扫描浏览器下载目录中的生工测序压缩包，安全复制归档到对应订单 原始压缩包/"""
    params = req or SangonImportDownloadsRequest()
    root_path = _sangon_root_or_default(params.sangon_root)
    dl_dir = _sangon_downloads_or_default(params.downloads_dir)
    if not dl_dir.exists() or not dl_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"浏览器下载目录不存在: {dl_dir}")

    res = await asyncio.to_thread(
        import_order_zips_from_downloads,
        root_path,
        dl_dir,
        order_names=params.order_names or None,
        auto_create_order=params.auto_create_order,
    )
    return {"status": "success", **res}


@router.post("/sangon_16s/send_result")
async def send_sangon_order_result_mail(req: SangonSendResultRequest):
    """将指定订单的 16S 鉴定结果 CSV 打包为 zip 并通过 SMTP 发送（默认发送至本人配置邮箱）"""
    clean_name = (req.order_dir_name or "").strip()
    if not clean_name or any(sep in clean_name for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的订单目录名: {req.order_dir_name}")

    root_path = _sangon_root_or_default(req.sangon_root)
    order_dir = root_path / clean_name
    if not order_dir.exists() or not order_dir.is_dir() or order_dir.parent.resolve() != root_path.resolve():
        raise HTTPException(status_code=404, detail=f"未找到订单目录: {clean_name}")

    csv_path = order_dir / "BLAST结果" / "16S鉴定结果.csv"
    if not csv_path.exists() or not csv_path.is_file():
        raise HTTPException(status_code=404, detail=f"该订单尚未生成 16S鉴定结果.csv，请先运行比对导出")

    def _do_send_16s():
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.reader(f))
        data_rows = [r for r in rows[1:] if r] if len(rows) > 1 else []
        total = len(data_rows)
        no_hits = sum(
            1 for r in data_rows
            if ("No Hits" in (r[3] if len(r) > 3 else "") or "未找到匹配项" in (r[3] if len(r) > 3 else ""))
        )
        with_hits = total - no_hits

        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=False)
        target_to = _resolve_send_target(cfg, req.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再发送邮件")

        order_no = clean_name.split("_", 1)[1] if "_" in clean_name else clean_name
        subject = (req.subject or f"生工 16S 测序鉴定结果 - {clean_name}（共 {total} 样本）").strip()

        preview_lines = []
        for r in data_rows[:15]:
            qid = r[0] if len(r) > 0 else "-"
            sp_cn = r[1] if len(r) > 1 else ""
            sp_la = r[3] if len(r) > 3 else ""
            ident = r[7] if len(r) > 7 else ""
            acc = r[9] if len(r) > 9 else ""
            sp_disp = f"{sp_cn} ({sp_la})" if sp_cn and sp_la else (sp_cn or sp_la or "-")
            preview_lines.append(f"  - {qid}: {sp_disp} | Identity={ident} | Acc={acc}")
        if total > 15:
            preview_lines.append(f"  ...（其余 {total - 15} 条结果详见附件 CSV 表格）")

        body_lines = [
            "您好：",
            "",
            f"生工 16S 测序订单 {clean_name}（订单号 {order_no}）的自动 BLAST 鉴定与物种翻译已完成：",
            f"  样本总数：{total}",
            f"  成功命中：{with_hits}",
            f"  未命中：{no_hits}",
        ]
        if req.extra_note and req.extra_note.strip():
            body_lines.append(f"  备注信息：{req.extra_note.strip()}")
        if preview_lines:
            body_lines.append("")
            body_lines.append("鉴定结果预览（前 15 条）：")
            body_lines.extend(preview_lines)
        body_lines.extend(["", "完整 11 列鉴定结果请查收附件压缩包。", ""])

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / f"16S鉴定结果_{clean_name}.zip"
            inner_csv_name = f"16S鉴定结果_{order_no}.csv"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(csv_path, arcname=inner_csv_name)
                zf.writestr("结果说明.txt", "\n".join(body_lines).encode("utf-8"))

            res = MailSender(cfg).send(zip_path, to=target_to, subject=subject, body="\n".join(body_lines))
            return res, zip_path.name, total, with_hits, no_hits

    try:
        res, zip_name, total, with_hits, no_hits = await asyncio.to_thread(_do_send_16s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送 16S 结果邮件异常: {e}")

    if not res.ok:
        raise HTTPException(status_code=400, detail=f"发送失败 ({res.stage}): {res.error}")

    return {
        "status": "success",
        "ok": True,
        "order_dir_name": clean_name,
        "to": res.to,
        "subject": res.subject,
        "stage": res.stage,
        "attachment": zip_name,
        "attachment_size": res.attachment_size,
        "total_samples": total,
        "with_hits": with_hits,
        "no_hits": no_hits,
    }


@router.post("/sangon_16s/settings")
async def update_sangon_settings(req: SangonSettingsRequest):
    """修改生工 16S 根目录（支持自动迁移）或本地浏览器下载目录（仅更新路径不迁移）"""
    if _sangon_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="生工 16S 流水线运行中，暂不能修改目录")

    to_save: Dict[str, Any] = {}
    migration: Optional[Dict[str, Any]] = None

    if req.sangon_root is not None:
        new_root_str = req.sangon_root.strip()
        if not new_root_str:
            raise HTTPException(status_code=400, detail="生工 16S 根目录不能为空")
        new_root = Path(new_root_str)
        if not new_root.is_absolute():
            raise HTTPException(status_code=400, detail="生工 16S 根目录必须为绝对路径")

        old_root = get_sangon_root()
        try:
            if req.migrate:
                migration = await asyncio.to_thread(migrate_directory, old_root, new_root)
            else:
                new_root.mkdir(parents=True, exist_ok=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"目录迁移失败: {e}")
        to_save["sangon_root"] = str(new_root)

    if req.downloads_dir is not None:
        new_dl_str = req.downloads_dir.strip()
        if not new_dl_str:
            raise HTTPException(status_code=400, detail="浏览器下载目录不能为空")
        new_dl = Path(new_dl_str)
        if not new_dl.is_absolute():
            raise HTTPException(status_code=400, detail="浏览器下载目录必须为绝对路径")
        if not new_dl.exists() or not new_dl.is_dir():
            raise HTTPException(status_code=400, detail=f"浏览器下载目录不存在: {new_dl}")
        to_save["downloads_dir"] = str(new_dl)

    if not to_save:
        raise HTTPException(status_code=400, detail="未提供需要更新的目录参数")

    settings = save_sangon_settings(to_save)
    return {"status": "success", "settings": settings, "migration": migration}


@router.post("/sangon_16s/cleanup")
async def cleanup_sangon_orders(req: SangonCleanupRequest):
    """按订单清理生工 16S 历史数据（解压文件 / BLAST 缓存 / 结果 CSV / 整个订单目录 / 扫描去重记录）"""
    if _sangon_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="生工 16S 流水线运行中，暂不能清理")
    if not req.targets:
        raise HTTPException(status_code=400, detail="未选择清理项")
    order_names = req.order_names
    if not order_names:
        if "scan_index" in req.targets:
            order_names = ["__ALL__"]
        else:
            raise HTTPException(status_code=400, detail="未选择订单")
    res = await asyncio.to_thread(
        cleanup_sangon_history, get_sangon_root(), BLAST_RESULTS_ROOT, order_names, req.targets
    )
    return {"status": "success", **res}


@router.post("/open_path")
async def open_local_path(req: OpenPathRequest):
    """在宿主机 Windows 资源管理器中打开指定目录或选中文件"""
    target = Path(req.path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {target}")

    try:
        if sys.platform.startswith("win"):
            if target.is_file():
                subprocess.Popen(["explorer.exe", f"/select,{target}"])
            else:
                os.startfile(str(target))
        return {"status": "success", "path": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

