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
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from ..services.other_tools.dir_migrator import migrate_directory
from ..services.other_tools.history_cleaner import cleanup_mail_history, cleanup_sangon_history
from ..services.other_tools.mail_composer import (
    build_package_send_draft,
    build_sangon_result_draft,
    build_test_send_draft,
    resolve_final_mail_params,
    resolve_safe_send_target,
    send_mail_compat,
)
from ..services.other_tools.mail_inbox_browser import list_whitelist_mails
from ..services.other_tools.sangon_ignore_rules import (
    ignore_orders,
    list_ignored_orders,
    normalize_order_key,
    replace_ignore_rules,
    unignore_orders,
)
from ..services.other_tools.sangon_downloader import (
    _collect_pending_download_targets,
    build_sangon_order_url,
    download_sangon_orders,
)
from ..services.other_tools.sangon_mail_scanner import init_sangon_order_dir, scan_sangon_mails
from ..services.other_tools.sangon_order_annotator import annotate_sangon_orders
from ..services.other_tools.sangon_settings import (
    get_sangon_auth_status,
    get_sangon_downloads_dir,
    get_sangon_root,
    load_sangon_settings,
    resolve_sangon_credentials,
    save_sangon_credentials,
    save_sangon_settings,
)
from ..services.other_tools.sangon_zip_importer import (
    import_order_zips_from_downloads,
    scan_downloads_for_sangon_zips,
)
from ..services.other_tools.secret_store import mask_secret, read_secret, resolve_secret_path, write_secret
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
from ..services.other_tools.sangon_order_inspector import (
    export_sangon_order_csv,
    inspect_sangon_order_dir,
    sangon_csv_sort_key as _sangon_csv_sort_key,
)
from ...blast.manager import get_blast_manager, TaskStatus
from ...mail_download.batch_state import inspect_batch_pipeline_state, load_batch_manifest, mark_batch_ignored
from ...mail_download.config import load_config
from ...mail_download.downloader import AttachmentSaver
from ...mail_download.fetcher import MailFetcher
from ...mail_download.sender import MailSender
from ...utils.headless_browser_manager import (
    inspect_headless_browser,
    repair_headless_browser,
)
from ...utils.translation.biology_translator import get_global_biology_translator

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

# 请求参数模型与常量已拆分至 ..services.other_tools.schemas 并在此重导出



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
                "ignored": state.get("ignored", False),
                "ignore_reason": state.get("ignore_reason", ""),
                "ignored_at": state.get("ignored_at", ""),
            })
    pending_batches_count = sum(1 for item in batches if item.get("pending"))
    ignored_batches_count = sum(1 for item in batches if item.get("ignored"))

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
        "ignored_batches_count": ignored_batches_count,
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


@router.post("/mail_pipeline/batch_ignore")
async def toggle_mail_pipeline_batch_ignore(req: MailBatchIgnoreRequest):
    """将指定已收件批次标记为“已忽略跳过”（自动流水线跳过接续，保留原附件不删除）或恢复待处理状态"""
    if _mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能修改批次跳过状态")
    clean_batch = (req.batch_name or "").strip()
    if not clean_batch or any(sep in clean_batch for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的批次名: {req.batch_name}")

    raw_cfg = _read_mail_cfg()
    dl_dir = _resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))
    send_dir = _resolve_dir(raw_cfg.get("send_dir", "results/email_sends"))
    batch_path = dl_dir / clean_batch
    if not batch_path.exists() or not batch_path.is_dir() or batch_path.parent.resolve() != dl_dir.resolve():
        raise HTTPException(status_code=404, detail=f"未找到批次目录: {clean_batch}")

    cfg_obj = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
    await asyncio.to_thread(mark_batch_ignored, batch_path, ignored=req.ignore, reason=req.reason)
    state = inspect_batch_pipeline_state(batch_path, cfg_obj, send_dir, ANNOTATIONS_DIR)
    return {
        "status": "success",
        "batch_name": clean_batch,
        "ignored": state.get("ignored", False),
        "state": state,
    }


@router.post("/mail_pipeline/list_mails")
async def list_mail_inbox(req: MailListRequest):
    """分页浏览并去重展示发件人白名单内的收件箱邮件"""
    def _do_list():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=True)
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
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=True)
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
    cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
    dl_dir = _resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))

    resolved_to: Optional[str] = None
    if req.to is not None and req.to.strip():
        resolved_to = resolve_safe_send_target(cfg, req.to)
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


def _resolve_outbound_zip_path(zip_name: str, cfg: Any) -> tuple[str, Path, Path]:
    clean_zip = (zip_name or "").strip()
    if (
        not clean_zip
        or any(sep in clean_zip for sep in ("/", "\\", ".."))
        or not clean_zip.lower().endswith(".zip")
    ):
        raise HTTPException(status_code=400, detail=f"非法的压缩包文件名: {zip_name}")

    send_dir = _resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
    zip_path = send_dir / clean_zip
    if not zip_path.exists() or not zip_path.is_file() or zip_path.parent.resolve() != send_dir.resolve():
        raise HTTPException(status_code=404, detail=f"未找到回传压缩包: {clean_zip}")
    return clean_zip, zip_path, send_dir


@router.post("/mail_pipeline/test_send_preview")
async def preview_mail_pipeline_test_send(req: Optional[MailTestSendPreviewRequest] = Body(default=None)):
    """生成 SMTP 自检测试邮件的默认草稿，供前端弹窗预填与自由编辑。"""
    params = req or MailTestSendPreviewRequest()

    def _do_preview():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        send_dir = _resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
        draft = build_test_send_draft(
            cfg,
            send_dir,
            ANNOTATIONS_DIR,
            note=params.note,
            attach_latest_report=params.attach_latest_report,
        )
        return {
            "to": draft["to"],
            "reply_to": draft["reply_to"],
            "from_name": draft["from_name"],
            "cc": draft["cc"],
            "subject": draft["subject"],
            "body": draft["body"],
            "attachment_name": draft["attachment_name"],
            "attached_files": draft["attached_files"],
        }

    data = await asyncio.to_thread(_do_preview)
    return {"status": "success", **data}


@router.post("/mail_pipeline/test_send")
async def test_mail_pipeline_send(req: Optional[MailTestSendRequest] = Body(default=None)):
    """轻量测试 SMTP 发信链路：打包验证文本（可选附带最新 Word 报告）发送到自身或指定邮箱。"""
    params = req or MailTestSendRequest()

    def _do_test_send():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        target_to = resolve_safe_send_target(cfg, params.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再测试发信")

        send_dir = _resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
        draft = build_test_send_draft(
            cfg,
            send_dir,
            ANNOTATIONS_DIR,
            note=params.note,
            attach_latest_report=params.attach_latest_report,
        )
        final = resolve_final_mail_params(
            cfg=cfg,
            draft=draft,
            req_from_name=params.from_name,
            req_subject=params.subject,
            req_body=params.body,
            req_attachment_name=params.attachment_name,
            req_cc=params.cc,
        )
        attached_files = list(draft["attached_files"])
        latest_docx: Optional[Path] = draft["latest_docx_path"]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / final["attachment_name"]

            txt_lines = [
                "邮件自动回传工作台 SMTP 链路自检报告",
                f"发送时间: {draft['now_str']}",
                f"SMTP 服务器: {cfg.smtp_server}:{cfg.smtp_port}",
                f"发件账号: {cfg.smtp_account}",
                f"发信标题: {final['from_name'] or '-'}",
                f"目标收件人: {target_to}",
                f"抄送: {', '.join(final['cc_list']) or '-'}",
                f"主题: {final['subject']}",
                f"中文与 UTF-8 附件名编码验证: 正常 ({final['attachment_name']})",
            ]
            if params.note and params.note.strip():
                txt_lines.append(f"附加备注: {params.note.strip()}")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("smtp_self_test.txt", "\n".join(txt_lines).encode("utf-8"))
                if latest_docx is not None:
                    zf.writestr(latest_docx.name, latest_docx.read_bytes())

            sender = MailSender(cfg)
            res = send_mail_compat(
                sender,
                zip_path,
                to=target_to,
                subject=final["subject"],
                body=final["body"],
                cc=final["cc_list"],
                from_name=final["from_name"],
                attachment_name=final["attachment_name"],
            )
            return res, final, attached_files

    try:
        res, final, attached_files = await asyncio.to_thread(_do_test_send)
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
        "cc": getattr(res, "cc", "") or ", ".join(final["cc_list"]),
        "from_name": getattr(res, "from_name", "") or final["from_name"],
        "subject": res.subject,
        "stage": res.stage,
        "attachment": getattr(res, "attachment_name", "") or final["attachment_name"],
        "attachment_size": res.attachment_size,
        "attached_files": attached_files,
    }


@router.post("/mail_pipeline/send_package_preview")
async def preview_mail_pipeline_package(req: MailPackagePreviewRequest):
    """生成已打包注释结果压缩包的默认邮件草稿，供前端弹窗预填与自由编辑。"""
    def _do_preview():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        _, zip_path, send_dir = _resolve_outbound_zip_path(req.zip_name, cfg)
        draft = build_package_send_draft(zip_path, send_dir, cfg, extra_note=req.extra_note)
        return draft

    data = await asyncio.to_thread(_do_preview)
    return {"status": "success", **data}


@router.post("/mail_pipeline/send_package")
async def send_mail_pipeline_package(req: MailPackageSendRequest):
    """将已打包的注释结果压缩包通过 SMTP 发送至本人或指定邮箱（支持自定义发信标题、主题、正文、抄送与附件名）。"""
    def _do_send_package():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        clean_zip, zip_path, send_dir = _resolve_outbound_zip_path(req.zip_name, cfg)

        target_to = resolve_safe_send_target(cfg, req.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再发送邮件")

        draft = build_package_send_draft(zip_path, send_dir, cfg, extra_note=req.extra_note)
        final = resolve_final_mail_params(
            cfg=cfg,
            draft=draft,
            req_from_name=req.from_name,
            req_subject=req.subject,
            req_body=req.body,
            req_attachment_name=req.attachment_name,
            req_cc=req.cc,
        )

        res = send_mail_compat(
            MailSender(cfg),
            zip_path,
            to=target_to,
            subject=final["subject"],
            body=final["body"],
            cc=final["cc_list"],
            from_name=final["from_name"],
            attachment_name=final["attachment_name"],
        )
        return res, clean_zip, draft, final

    try:
        res, clean_zip, draft, final = await asyncio.to_thread(_do_send_package)
    except HTTPException:
        raise
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
        "task_id": draft["task_id"],
        "to": res.to,
        "cc": getattr(res, "cc", "") or ", ".join(final["cc_list"]),
        "from_name": getattr(res, "from_name", "") or final["from_name"],
        "subject": res.subject,
        "stage": res.stage,
        "attachment": getattr(res, "attachment_name", "") or final["attachment_name"],
        "attachment_size": res.attachment_size,
        "file_count": draft["file_count"],
    }


# ==============================================================================
# 2. 生工 16S 测序结果自动化 BLAST 与导出流程 接口
# ==============================================================================

def _inspect_sangon_order_dir(order_dir: Path) -> Dict[str, Any]:
    """解析单个生工 16S 订单目录状态（委派至 sangon_order_inspector）"""
    return inspect_sangon_order_dir(order_dir, project_root=PROJECT_ROOT)


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

    annotate_sangon_orders(root_path, orders, download_candidates)
    pending_download_count = sum(
        1 for c in download_candidates if not c["archived"] and not c.get("ignored")
    )
    ignored_download_count = sum(
        1 for c in download_candidates if not c["archived"] and c.get("ignored")
    )

    db_16s = PROJECT_ROOT / "database" / "16S" / "ncbi" / "16S_ribosomal_RNA.nin"
    return {
        "status": "success",
        "sangon_root": str(root_path),
        "downloads_dir": str(dl_dir),
        "downloads_exists": dl_dir.exists(),
        "download_candidates": download_candidates,
        "pending_download_count": pending_download_count,
        "ignored_download_count": ignored_download_count,
        "settings": load_sangon_settings(),
        "sangon_auth": get_sangon_auth_status(),
        "browser_env": inspect_headless_browser(
            project_root=PROJECT_ROOT,
            config_path=CONFIG_JSON_PATH,
            probe_launch=False,
        ),
        "root_exists": root_path.exists(),
        "db_16s_ready": db_16s.exists(),
        "runtime": _snapshot_sangon_runtime(),
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


def _export_sangon_order_csv(task_id: str, out_dir: Path) -> Dict[str, int]:
    """解析 BLAST 报告并调用 BiologyTranslator 翻译导出 11 列 16S鉴定结果.csv（委派至 sangon_order_inspector）"""
    return export_sangon_order_csv(
        task_id,
        out_dir,
        project_root=PROJECT_ROOT,
        translator_factory=get_global_biology_translator,
    )


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


def _execute_sangon_dirs_pipeline(
    root_path: Path,
    target_dirs: List[Path],
    *,
    downloads_dir: Optional[str] = None,
    evalue: str = "0.05",
    hitlist_size: str = "50",
    force_reblast: bool = False,
    progress_start: int = 0,
    progress_end: int = 100,
) -> Dict[str, Any]:
    """依次对目标订单目录执行：认领 -> 解压 -> 16S BLAST -> 翻译导出 CSV。"""
    processed = 0
    skipped_missing = 0
    failed = 0
    total_orders = len(target_dirs)
    span = max(1, progress_end - progress_start)
    mgr = get_blast_manager()

    for idx, order_dir in enumerate(target_dirs, start=1):
        base_pct = progress_start + int((idx - 1) * span / total_orders)
        done_pct = progress_start + int(idx * span / total_orders)
        _sangon_pipeline_state["current_order"] = order_dir.name
        _sangon_pipeline_state["current_stage"] = "extracting"
        _append_sangon_log(f"({idx}/{total_orders}) 正在检查订单目录: {order_dir.name}")

        zip_dir = order_dir / "原始压缩包"
        raw_dir = order_dir / "原始数据"
        res_dir = order_dir / "BLAST结果"
        raw_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)

        # Step 0: 若原始数据与原始压缩包均为空，自动尝试从浏览器下载目录认领匹配订单包
        fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])
        has_zip = zip_dir.exists() and any(zip_dir.glob("*.zip"))
        if not fastas and not has_zip:
            dl_dir = _sangon_downloads_or_default(downloads_dir)
            imp = import_order_zips_from_downloads(
                root_path,
                dl_dir,
                order_names=[order_dir.name],
                auto_create_order=False,
            )
            if imp["imported_count"] > 0:
                _append_sangon_log(
                    f"已从下载目录自动认领压缩包: {imp['imported'][0]['zip_name']} -> 原始压缩包/"
                )

        # Step 1: 若原始数据无 .1.fasta 但原始压缩包有 zip，自动解压
        if not fastas and zip_dir.exists():
            for zf_path in sorted(zip_dir.glob("*.zip")):
                _append_sangon_log(f"正在解压原始压缩包: {zf_path.name} -> 原始数据/")
                with zipfile.ZipFile(zf_path, "r") as zf:
                    zf.extractall(raw_dir)
            fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])

        if not fastas:
            skipped_missing += 1
            _append_sangon_log(
                f"[跳过] {order_dir.name} 未找到压缩包或 *.1.fasta 主序列（请先自动或手动下载压缩包）",
                level="warning",
            )
            with _sangon_pipeline_lock:
                _sangon_pipeline_state["progress"] = done_pct
                _sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }
            continue

        task_name = f"{order_dir.name}_16s"
        task_cache_dir = PROJECT_ROOT / "results" / "blast" / task_name
        reports_dir = task_cache_dir / "reports"

        # 强制重跑时清理旧 BLAST 缓存与数据库记录，避免 BlastEngine 命中既有 reports/*.csv 静默跳过
        if force_reblast:
            _append_sangon_log(f"强制重新比对：正在清理旧缓存与记录 ({task_name})")
            try:
                mgr.delete_task(task_name)
            except Exception as del_err:
                _append_sangon_log(f"清理任务数据库记录提示: {del_err}", level="warning")
            if task_cache_dir.exists():
                shutil.rmtree(task_cache_dir, ignore_errors=True)

        existing_csvs = list(reports_dir.glob("*.csv")) if reports_dir.exists() else []

        # Step 2: 运行 16S BLAST
        blast_ok = True
        if len(existing_csvs) < len(fastas) or force_reblast:
            _sangon_pipeline_state["current_stage"] = "blasting"
            _append_sangon_log(f"提交 16S BLAST 比对任务 ({len(fastas)} 条主序列): {task_name}")
            task_id = mgr.create_task({
                "task_name": task_name,
                "files": [str(p) for p in fastas],
                "program": "auto",
                "database": "ncbi_16s",
                "evalue": evalue,
                "hitlist_size": hitlist_size,
                "max_workers": 2,
                "request_timeout": 10,
            })
            wait_deadline = time.monotonic() + 3600.0
            while True:
                st_info = mgr.get_task_status(task_id)
                if not st_info:
                    blast_ok = False
                    _append_log_msg = f"[失败] 未查询到 BLAST 任务状态: {task_id}"
                    _append_sangon_log(_append_log_msg, level="error")
                    break
                st = st_info.get("status", "unknown")
                prog = st_info.get("progress", 0)
                _sangon_pipeline_state["progress"] = base_pct + int(
                    (max(0, min(100, int(prog or 0))) / 100.0) * max(1, done_pct - base_pct)
                )
                if st == TaskStatus.COMPLETED.value:
                    _append_sangon_log(f"BLAST 任务结束: {st} (进度 {prog}%)")
                    break
                if st in (TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.PAUSED.value):
                    blast_ok = False
                    err_detail = st_info.get("error") or st
                    _append_sangon_log(f"[失败] BLAST 任务未完成 ({st}): {err_detail}", level="error")
                    break
                if time.monotonic() > wait_deadline:
                    blast_ok = False
                    _append_sangon_log(f"[超时] BLAST 任务等待超时 (>3600s): {task_id}", level="error")
                    break
                time.sleep(1.0)
        else:
            _append_sangon_log(f"复用已有 BLAST 报告 ({len(existing_csvs)} 份 CSV)")

        if not blast_ok:
            failed += 1
            with _sangon_pipeline_lock:
                _sangon_pipeline_state["progress"] = done_pct
                _sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }
            continue

        # Step 3: 翻译并导出 11 列 CSV
        _sangon_pipeline_state["current_stage"] = "exporting"
        _append_sangon_log("正在执行物种拉丁文批量翻译并导出 16S鉴定结果.csv ...")
        stats = _export_sangon_order_csv(task_name, res_dir)
        processed += 1
        _append_sangon_log(
            f"订单 {order_dir.name} 导出完成: 共 {stats['total']} 样本, "
            f"命中 {stats['with_hits']}, 未命中 {stats['no_hits']}"
        )
        with _sangon_pipeline_lock:
            _sangon_pipeline_state["progress"] = done_pct
            _sangon_pipeline_state["summary"] = {
                "total": total_orders,
                "processed": processed,
                "skipped_missing": skipped_missing,
                "failed": failed,
            }

    return {
        "total": total_orders,
        "processed": processed,
        "skipped_missing": skipped_missing,
        "failed": failed,
    }


@router.post("/sangon_16s/run_pipeline")
async def run_sangon_16s_pipeline(req: SangonRunRequest):
    """对选定的生工 16S 订单执行自动解压 -> 16S BLAST 比对 -> 中文翻译与 11 列 CSV 导出"""
    root_path = _sangon_root_or_default(req.sangon_root)
    if not root_path.exists():
        raise HTTPException(status_code=400, detail=f"生工 16S 目录不存在: {root_path}")

    target_dirs: List[Path] = []
    skipped_ignored = 0
    if req.order_names:
        for name in req.order_names:
            p = root_path / name
            if p.exists() and p.is_dir():
                target_dirs.append(p)
    else:
        ignored_keys = set(list_ignored_orders().keys())
        for child in sorted(root_path.iterdir()):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                info = _inspect_sangon_order_dir(child)
                order_key = normalize_order_key(str(info.get("order_no") or child.name))
                if order_key in ignored_keys:
                    skipped_ignored += 1
                    continue
                if info["status"] != "completed" or req.force_reblast:
                    target_dirs.append(child)

    if not target_dirs:
        if skipped_ignored > 0:
            raise HTTPException(status_code=400, detail=f"没有需要处理的订单目录（已自动跳过 {skipped_ignored} 个已忽略订单）")
        raise HTTPException(status_code=400, detail="没有需要处理的订单目录")

    with _sangon_pipeline_lock:
        if _sangon_pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")
        start_msg = f"启动生工 16S 批处理，共 {len(target_dirs)} 个订单"
        _sangon_pipeline_state["running"] = True
        _sangon_pipeline_state["current_order"] = None
        _sangon_pipeline_state["current_stage"] = "running"
        _sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _sangon_pipeline_state["finished_at"] = None
        _sangon_pipeline_state["progress"] = 0
        _sangon_pipeline_state["last_message"] = start_msg
        _sangon_pipeline_state["summary"] = {
            "total": len(target_dirs),
            "processed": 0,
            "skipped_missing": 0,
            "failed": 0,
        }
        _sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] {start_msg}"]
    logger.info("[Sangon16S] %s", start_msg)

    def _run_sangon_bg():
        processed = 0
        skipped_missing = 0
        failed = 0
        total_orders = len(target_dirs)
        try:
            res = _execute_sangon_dirs_pipeline(
                root_path,
                target_dirs,
                downloads_dir=req.downloads_dir,
                evalue=req.evalue,
                hitlist_size=req.hitlist_size,
                force_reblast=req.force_reblast,
                progress_start=0,
                progress_end=100,
            )
            processed = res["processed"]
            skipped_missing = res["skipped_missing"]
            failed = res["failed"]

            if failed > 0:
                summary_msg = (
                    f"生工 16S 批处理结束：成功 {processed} 个，跳过缺包 {skipped_missing} 个，失败 {failed} 个"
                )
                final_stage = "failed" if processed == 0 else "completed"
                log_lvl = "warning"
            elif processed == 0 and skipped_missing > 0:
                summary_msg = (
                    f"暂无可比对订单：所选 {skipped_missing} 个订单均缺少压缩包或 *.1.fasta"
                    "（请先自动下载或认领下载包）"
                )
                final_stage = "completed"
                log_lvl = "info"
            elif skipped_missing > 0:
                summary_msg = (
                    f"处理完成：成功 {processed} 个订单，另有 {skipped_missing} 个待下载订单因缺少压缩包已跳过"
                )
                final_stage = "completed"
                log_lvl = "info"
            else:
                summary_msg = f"全部生工 16S 订单处理完毕（共 {processed} 个）"
                final_stage = "completed"
                log_lvl = "info"

            _sangon_pipeline_state["progress"] = 100
            _sangon_pipeline_state["current_stage"] = final_stage
            _append_sangon_log(summary_msg, level=log_lvl)
        except Exception as exc:
            _sangon_pipeline_state["current_stage"] = "failed"
            _sangon_pipeline_state["progress"] = 100
            _append_sangon_log(f"执行异常: {exc}", level="error")
        finally:
            with _sangon_pipeline_lock:
                _sangon_pipeline_state["running"] = False
                _sangon_pipeline_state["current_order"] = None
                _sangon_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }

    asyncio.get_running_loop().run_in_executor(None, _run_sangon_bg)
    return {"status": "started", "runtime": _snapshot_sangon_runtime()}


@router.post("/sangon_16s/auth")
async def update_sangon_auth_credentials(req: SangonAuthUpdateRequest):
    """保存或更新生工官网登录账号与独立密钥文件 (.sangon_auth)，仅返脱敏掩码"""
    if (
        req.account is None
        and req.password is None
        and req.auto_confirm_fee is None
    ):
        raise HTTPException(status_code=400, detail="未提供需要更新的生工账号配置")
    auth_info = save_sangon_credentials(
        account=req.account,
        password=req.password,
        auto_confirm_fee=req.auto_confirm_fee,
    )
    return {"status": "success", "sangon_auth": auth_info, "settings": load_sangon_settings()}


@router.post("/sangon_16s/download_orders")
async def download_sangon_orders_endpoint(req: Optional[SangonDownloadRequest] = Body(default=None)):
    """后台异步执行：优先从本地 Downloads 认领 -> 登录生工官网批量下载压缩包 -> 可选串联 16S BLAST 与导出"""
    params = req or SangonDownloadRequest()
    root_path = _sangon_root_or_default(params.sangon_root)
    if not root_path.exists():
        raise HTTPException(status_code=400, detail=f"生工 16S 目录不存在: {root_path}")
    dl_dir = _sangon_downloads_or_default(params.downloads_dir)

    collected = _collect_pending_download_targets(
        root_path,
        order_names=params.order_names or None,
    )
    targets: List[Dict[str, Any]] = collected["targets"]
    if not targets:
        if collected["skipped"]:
            msg_list = ", ".join(f"{it['dir_name']}({it['message']})" for it in collected["skipped"][:3])
            raise HTTPException(status_code=400, detail=f"当前没有需要下载的订单：{msg_list}")
        raise HTTPException(status_code=400, detail="当前没有需要下载的待处理订单")

    # 检查是否存在本地尚未下载且拥有生工链接、必须登录官网的订单
    dl_cands = scan_downloads_for_sangon_zips(dl_dir, order_nos=[t["order_no"] for t in targets]) if dl_dir.exists() else []
    dl_ready_nos = {c["order_no"] for c in dl_cands}
    needs_web_login = any(
        t["order_no"] not in dl_ready_nos
        and bool(build_sangon_order_url(t.get("cx_order_id", ""), t.get("download_url", "")))
        for t in targets
    )

    account, password = resolve_sangon_credentials()
    if needs_web_login and (not account or not password):
        raise HTTPException(
            status_code=400,
            detail="需要登录生工官网自动下载，请先在「生工账号配置」中填写生工账号与登录密码",
        )

    settings = load_sangon_settings()
    confirm_fee = (
        params.auto_confirm_fee
        if params.auto_confirm_fee is not None
        else bool(settings.get("auto_confirm_fee", True))
    )
    auto_run = params.auto_run_blast

    with _sangon_pipeline_lock:
        if _sangon_pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")
        mode_label = "自动下载并比对" if auto_run else "自动下载压缩包"
        start_msg = f"启动生工 16S {mode_label}，待检查 {len(targets)} 个订单"
        _sangon_pipeline_state["running"] = True
        _sangon_pipeline_state["current_order"] = None
        _sangon_pipeline_state["current_stage"] = "downloading"
        _sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _sangon_pipeline_state["finished_at"] = None
        _sangon_pipeline_state["progress"] = 0
        _sangon_pipeline_state["last_message"] = start_msg
        _sangon_pipeline_state["summary"] = {
            "total": len(targets),
            "processed": 0,
            "skipped_missing": 0,
            "failed": 0,
        }
        _sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] {start_msg}"]
    logger.info("[Sangon16S] %s", start_msg)

    def _run_download_bg():
        total_cnt = len(targets)
        dl_end_pct = 45 if auto_run else 100
        processed_cnt = 0
        skipped_cnt = 0
        failed_cnt = 0
        try:
            def _on_dl_prog(idx: int, total_web: int, dname: str) -> None:
                _sangon_pipeline_state["current_order"] = dname
                _sangon_pipeline_state["current_stage"] = "downloading"
                _sangon_pipeline_state["progress"] = int(((idx - 1) / max(1, total_web)) * dl_end_pct)

            if needs_web_login:
                env_snap = inspect_headless_browser(
                    project_root=PROJECT_ROOT,
                    config_path=CONFIG_JSON_PATH,
                    probe_launch=False,
                )
                if not env_snap.get("ready"):
                    _append_sangon_log("检测到无头浏览器尚未就绪，正在执行启动前环境自修复...")
                    repaired_env = repair_headless_browser(
                        project_root=PROJECT_ROOT,
                        config_path=CONFIG_JSON_PATH,
                        auto_install=True,
                        probe_launch=False,
                        progress_cb=lambda m: _append_sangon_log(m),
                    )
                    for act in repaired_env.get("actions") or []:
                        _append_sangon_log(f"[浏览器自修复] {act}")
                    if not repaired_env.get("ready"):
                        _append_sangon_log("无头浏览器未能完全就绪，将继续尝试可用兜底或认领已有本地包。")

            dl_res = download_sangon_orders(
                root_path,
                dl_dir,
                order_names=[t["dir_name"] for t in targets],
                account=account,
                password=password,
                auto_confirm_fee=confirm_fee,
                headless=None,
                progress_cb=_on_dl_prog,
                log_cb=lambda m: _append_sangon_log(m),
            )
            claimed_cnt = dl_res["claimed_count"]
            downloaded_cnt = dl_res["downloaded_count"]
            skipped_cnt = dl_res["skipped_count"]
            failed_cnt = dl_res["failed_count"]
            captcha_blocked = dl_res.get("captcha_blocked", False)
            ready_dirs = [Path(root_path / name) for name in dl_res.get("processed_dir_names") or [] if (root_path / name).is_dir()]

            _sangon_pipeline_state["progress"] = dl_end_pct

            if auto_run and ready_dirs and not captcha_blocked:
                _append_sangon_log(f"自动下载阶段结束（认领 {claimed_cnt}，官网下载 {downloaded_cnt}），开始衔接 16S BLAST 比对...")
                blast_res = _execute_sangon_dirs_pipeline(
                    root_path,
                    ready_dirs,
                    downloads_dir=str(dl_dir),
                    evalue=params.evalue,
                    hitlist_size=params.hitlist_size,
                    force_reblast=params.force_reblast,
                    progress_start=dl_end_pct,
                    progress_end=100,
                )
                processed_cnt = blast_res["processed"]
                skipped_cnt += blast_res["skipped_missing"]
                failed_cnt += blast_res["failed"]
                final_msg = (
                    f"下载并比对完成：认领 {claimed_cnt}，官网下载 {downloaded_cnt}，"
                    f"比对导出 {processed_cnt}，跳过 {skipped_cnt}，失败 {failed_cnt}"
                )
            else:
                processed_cnt = claimed_cnt + downloaded_cnt
                if captcha_blocked:
                    final_msg = f"已停止：生工触发安全/人机验证（已完成 {processed_cnt} 个，失败 {failed_cnt} 个），请手动打开下载页验证"
                elif failed_cnt > 0:
                    final_msg = f"自动下载结束：认领 {claimed_cnt}，官网下载 {downloaded_cnt}，跳过 {skipped_cnt}，失败 {failed_cnt}"
                elif processed_cnt == 0 and skipped_cnt > 0:
                    final_msg = f"自动下载完成：暂无新入库包（跳过 {skipped_cnt} 个订单，详见运行日志）"
                else:
                    final_msg = f"自动下载完成：官网下载 {downloaded_cnt} 个，本地认领 {claimed_cnt} 个" + (
                        f"，跳过 {skipped_cnt} 个" if skipped_cnt else ""
                    )

            _sangon_pipeline_state["progress"] = 100
            _sangon_pipeline_state["current_stage"] = "failed" if (failed_cnt > 0 and processed_cnt == 0) or captcha_blocked else "completed"
            _append_sangon_log(final_msg, level="warning" if failed_cnt > 0 or captcha_blocked else "info")
        except Exception as exc:
            failed_cnt += 1
            _sangon_pipeline_state["current_stage"] = "failed"
            _sangon_pipeline_state["progress"] = 100
            _append_sangon_log(f"自动下载执行异常: {exc}", level="error")
        finally:
            with _sangon_pipeline_lock:
                _sangon_pipeline_state["running"] = False
                _sangon_pipeline_state["current_order"] = None
                _sangon_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _sangon_pipeline_state["summary"] = {
                    "total": total_cnt,
                    "processed": processed_cnt,
                    "skipped_missing": skipped_cnt,
                    "failed": failed_cnt,
                }

    asyncio.get_running_loop().run_in_executor(None, _run_download_bg)
    return {"status": "started", "runtime": _snapshot_sangon_runtime()}


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


def _resolve_sangon_order_csv_path(order_dir_name: str, sangon_root: Optional[str]) -> tuple[str, Path]:
    clean_name = (order_dir_name or "").strip()
    if not clean_name or any(sep in clean_name for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的订单目录名: {order_dir_name}")

    root_path = _sangon_root_or_default(sangon_root)
    order_dir = root_path / clean_name
    if not order_dir.exists() or not order_dir.is_dir() or order_dir.parent.resolve() != root_path.resolve():
        raise HTTPException(status_code=404, detail=f"未找到订单目录: {clean_name}")

    csv_path = order_dir / "BLAST结果" / "16S鉴定结果.csv"
    if not csv_path.exists() or not csv_path.is_file():
        raise HTTPException(status_code=404, detail="该订单尚未生成 16S鉴定结果.csv，请先运行比对导出")
    return clean_name, csv_path


@router.post("/sangon_16s/send_preview")
async def preview_sangon_order_result_mail(req: SangonSendPreviewRequest):
    """生成指定生工 16S 订单结果邮件的默认草稿，供前端弹窗预填与逐项修改。"""
    clean_name, csv_path = _resolve_sangon_order_csv_path(req.order_dir_name, req.sangon_root)

    def _do_preview():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        return build_sangon_result_draft(clean_name, csv_path, cfg, extra_note=req.extra_note)

    draft = await asyncio.to_thread(_do_preview)
    return {"status": "success", **draft}


@router.post("/sangon_16s/send_result")
async def send_sangon_order_result_mail(req: SangonSendResultRequest):
    """将指定订单的 16S 鉴定结果 CSV 打包为 zip 并通过 SMTP 发送（支持修改发信标题、主题、正文、抄送与附件名）"""
    clean_name, csv_path = _resolve_sangon_order_csv_path(req.order_dir_name, req.sangon_root)

    def _do_send_16s():
        cfg = load_config(str(MAIL_CONFIG_PATH), require_imap_auth=False)
        target_to = resolve_safe_send_target(cfg, req.to)
        if not target_to:
            raise ValueError("缺少目标收件人或未配置发件账号")
        if not cfg.smtp_auth_code:
            raise ValueError("缺少 SMTP 授权码，请先配置授权码后再发送邮件")

        draft = build_sangon_result_draft(clean_name, csv_path, cfg, extra_note=req.extra_note)
        final = resolve_final_mail_params(
            cfg=cfg,
            draft=draft,
            req_from_name=req.from_name,
            req_subject=req.subject,
            req_body=req.body,
            req_attachment_name=req.attachment_name,
            req_cc=req.cc,
        )

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / final["attachment_name"]
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(csv_path, arcname=draft["inner_csv_name"])
                zf.writestr("结果说明.txt", final["body"].encode("utf-8"))

            res = send_mail_compat(
                MailSender(cfg),
                zip_path,
                to=target_to,
                subject=final["subject"],
                body=final["body"],
                cc=final["cc_list"],
                from_name=final["from_name"],
                attachment_name=final["attachment_name"],
            )
            return res, draft, final

    try:
        res, draft, final = await asyncio.to_thread(_do_send_16s)
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
        "cc": getattr(res, "cc", "") or ", ".join(final["cc_list"]),
        "from_name": getattr(res, "from_name", "") or final["from_name"],
        "subject": res.subject,
        "stage": res.stage,
        "attachment": getattr(res, "attachment_name", "") or final["attachment_name"],
        "attachment_size": res.attachment_size,
        "total_samples": draft["total_samples"],
        "with_hits": draft["with_hits"],
        "no_hits": draft["no_hits"],
    }


@router.post("/sangon_16s/settings")
async def update_sangon_settings(req: SangonSettingsRequest):
    """修改生工 16S 根目录（支持自动迁移）、下载目录，以及全局忽略订单与邮件主题关键词配置"""
    if _sangon_pipeline_state["running"] and (req.sangon_root is not None or req.downloads_dir is not None):
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

    if req.auto_confirm_fee is not None:
        to_save["auto_confirm_fee"] = req.auto_confirm_fee

    has_rules_update = req.ignored_orders is not None or req.ignore_subject_keywords is not None
    if not to_save and not has_rules_update:
        raise HTTPException(status_code=400, detail="未提供需要更新的配置参数")

    settings = save_sangon_settings(to_save) if to_save else load_sangon_settings()
    if has_rules_update:
        settings = replace_ignore_rules(
            ignored_orders=req.ignored_orders,
            ignore_subject_keywords=req.ignore_subject_keywords,
        )
    return {"status": "success", "settings": settings, "sangon_auth": get_sangon_auth_status(), "migration": migration}


@router.post("/sangon_16s/ignore")
async def update_sangon_ignored_orders(req: SangonIgnoreRequest):
    """将指定订单号/目录名加入或移出生工 16S 全局忽略名单"""
    if not req.order_keys:
        raise HTTPException(status_code=400, detail="未提供需要处理的订单号或目录名")
    if req.ignore:
        res = ignore_orders(req.order_keys, reason=req.reason, dir_names=req.dir_names)
    else:
        res = unignore_orders(req.order_keys)
    return {"status": "success", "ignore": req.ignore, **res}


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


@router.get("/browser_env")
async def get_browser_env_status(probe: bool = False):
    """查询无头浏览器（Playwright Chromium / 系统浏览器兜底）健康状态与配置"""
    report = await asyncio.to_thread(
        inspect_headless_browser,
        PROJECT_ROOT,
        CONFIG_JSON_PATH,
        probe,
    )
    return {"status": "success", **report}


@router.post("/browser_env/repair")
async def repair_browser_env(req: Optional[BrowserEnvRepairRequest] = Body(default=None)):
    """更新无头浏览器配置并执行完整检查与自动自修复（补齐配置、清理残缺内核、国内源重装与标签修复）"""
    params = req or BrowserEnvRepairRequest()
    patch_cfg: Dict[str, Any] = {}
    if params.enabled is not None:
        patch_cfg["enabled"] = params.enabled
    if params.headless is not None:
        patch_cfg["headless"] = params.headless
    if params.use_system_browser_fallback is not None:
        patch_cfg["use_system_browser_fallback"] = params.use_system_browser_fallback
    if params.executable_path is not None:
        patch_cfg["executable_path"] = params.executable_path
    if params.browsers_path is not None:
        patch_cfg["browsers_path"] = params.browsers_path

    def _do_repair() -> Dict[str, Any]:
        return repair_headless_browser(
            project_root=PROJECT_ROOT,
            config_path=CONFIG_JSON_PATH,
            auto_install=params.auto_install,
            probe_launch=params.probe_launch,
            patch_config=patch_cfg or None,
        )

    report = await asyncio.to_thread(_do_repair)
    return {"status": "success", **report}


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

