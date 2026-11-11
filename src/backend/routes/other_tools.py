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
import subprocess
import sys
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
from ..services.other_tools.sangon_settings import get_sangon_root, load_sangon_settings, save_sangon_settings
from ..services.other_tools.secret_store import mask_secret, read_secret, resolve_secret_path, write_secret
from ...blast.manager import get_blast_manager, TaskStatus
from ...mail_download.config import load_config
from ...mail_download.downloader import AttachmentSaver
from ...mail_download.fetcher import MailFetcher
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
    annotate_only_batch: Optional[str] = None
    test_input: Optional[str] = None
    to: Optional[str] = None
    subject_prefix: str = "【自动】"
    extra_note: Optional[str] = None


class SangonRunRequest(BaseModel):
    sangon_root: Optional[str] = None
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
    sangon_root: str
    migrate: bool = True


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

    # 2. 已下载批次目录 (up_*)
    batches: List[Dict[str, Any]] = []
    if dl_dir.exists():
        for bdir in sorted(dl_dir.glob("up_*"), key=lambda p: p.name, reverse=True):
            if not bdir.is_dir():
                continue
            mf_path = bdir / "manifest.json"
            mail_meta: Dict[str, Any] = {}
            att_list: List[Dict[str, Any]] = []
            dl_time = ""
            if mf_path.exists():
                try:
                    mf = json.loads(mf_path.read_text(encoding="utf-8"))
                    mail_meta = mf.get("mail", {})
                    att_list = mf.get("attachments", [])
                    dl_time = mf.get("download_time", "")
                except Exception:
                    pass
            if not att_list:
                for fp in bdir.glob("*"):
                    if fp.is_file() and fp.name != "manifest.json":
                        att_list.append({
                            "filename": fp.name,
                            "size_bytes": fp.stat().st_size,
                            "path": str(fp),
                        })
            batches.append({
                "batch_name": bdir.name,
                "batch_path": str(bdir),
                "download_time": dl_time or datetime.fromtimestamp(bdir.stat().st_mtime).isoformat(timespec="seconds"),
                "sender": mail_meta.get("sender", "-"),
                "subject": mail_meta.get("subject", "-"),
                "mail_date": mail_meta.get("date", "-"),
                "attachments": att_list,
            })

    # 3. 已打包与回传产物 (results/email_sends)
    outbound_packages: List[Dict[str, Any]] = []
    docx_reports: List[Dict[str, Any]] = []
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
            docx_reports.append({
                "name": docx.name,
                "path": str(docx),
                "size_kb": round(docx.stat().st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(docx.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })

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


@router.post("/mail_pipeline/fetch")
async def trigger_mail_fetch(req: MailFetchRequest):
    """立即扫描 IMAP 收件箱并保存新附件"""
    def _do_fetch():
        cfg = load_config(MAIL_CONFIG_PATH, require_imap_auth=True)
        fetcher = MailFetcher(cfg)
        f_res = fetcher.fetch(since_days=req.since_days)
        if f_res.connection_error:
            return {"ok": False, "error": f_res.connection_error}
        saved_stats = {"count": 0, "skipped_duplicates": 0, "skipped_processed": 0, "saved_files": []}
        if f_res.matched:
            saver = AttachmentSaver(cfg.resolved_download_dir)
            saved_stats = saver.save(f_res.matched)
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
    """后台异步启动完整自动流水线 (收件 -> 注释 -> Word 报告 -> 打包 -> SMTP 回传)"""
    if _mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="邮件自动注释流水线正在运行中，请等待当前任务结束")

    cmd = [sys.executable, "-X", "utf8", "-m", "src.mail_download.auto_pipeline", "--config", str(MAIL_CONFIG_PATH)]
    if req.since_days is not None:
        cmd += ["--since-days", str(req.since_days)]
    if req.no_send:
        cmd.append("--no-send")
    if req.annotate_only_batch:
        batch_path = req.annotate_only_batch
        if not os.path.isabs(batch_path):
            batch_path = str(_resolve_dir(_read_mail_cfg().get("download_dir", "results/email_downloads")) / batch_path)
        cmd += ["--annotate-only", batch_path]
    if req.test_input:
        cmd += ["--test-input", req.test_input]
    if req.to:
        cmd += ["--to", req.to]
    if req.subject_prefix:
        cmd += ["--subject-prefix", req.subject_prefix]
    if req.extra_note:
        cmd += ["--extra-note", req.extra_note]

    _mail_pipeline_state["running"] = True
    _mail_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _mail_pipeline_state["finished_at"] = None
    _mail_pipeline_state["last_exit_code"] = None
    _mail_pipeline_state["last_command"] = " ".join(cmd)
    _mail_pipeline_state["last_output"] = "流水线已启动，正在执行..."
    _mail_pipeline_state["current_stage"] = "running"

    def _run_bg():
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
            )
            out_txt = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            _mail_pipeline_state["last_exit_code"] = proc.returncode
            _mail_pipeline_state["last_output"] = out_txt.strip()[-4000:]
            _mail_pipeline_state["current_stage"] = "completed" if proc.returncode == 0 else "failed"
        except Exception as exc:
            _mail_pipeline_state["last_exit_code"] = -1
            _mail_pipeline_state["last_output"] = f"执行异常: {exc}"
            _mail_pipeline_state["current_stage"] = "failed"
        finally:
            _mail_pipeline_state["running"] = False
            _mail_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    asyncio.get_running_loop().run_in_executor(None, _run_bg)
    return {"status": "started", "runtime": _mail_pipeline_state}


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
async def get_sangon_16s_overview(sangon_root: Optional[str] = None):
    """获取生工 16S 自动化流程目录与所有订单状态概览"""
    root_path = _sangon_root_or_default(sangon_root)
    orders: List[Dict[str, Any]] = []

    if root_path.exists() and root_path.is_dir():
        for child in sorted(root_path.iterdir(), key=lambda p: p.name, reverse=True):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                orders.append(_inspect_sangon_order_dir(child))

    db_16s = PROJECT_ROOT / "database" / "16S" / "ncbi" / "16S_ribosomal_RNA.nin"
    return {
        "status": "success",
        "sangon_root": str(root_path),
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


def _export_sangon_order_csv(task_id: str, out_dir: Path) -> Dict[str, int]:
    """解析 BLAST 报告并调用 BiologyTranslator 翻译导出 11 列 16S鉴定结果.csv"""
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = PROJECT_ROOT / "results" / "blast" / task_id / "reports"
    csv_files = sorted(reports_dir.glob("*.csv")) if reports_dir.exists() else []

    all_species = set()
    results = []

    for csv_path in csv_files:
        m = re.search(r"_-(\d+)_1\.csv$", csv_path.name)
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

                # Step 1: 若原始数据无 .1.fasta 但原始压缩包有 zip，自动解压
                fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])
                if not fastas and zip_dir.exists():
                    for zf_path in sorted(zip_dir.glob("*.zip")):
                        _append_log(f"正在解压原始压缩包: {zf_path.name} -> 原始数据/")
                        with zipfile.ZipFile(zf_path, "r") as zf:
                            zf.extractall(raw_dir)
                    fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])

                if not fastas:
                    _append_log(f"[跳过] {order_dir.name} 未找到 *.1.fasta 主序列文件")
                    continue

                task_name = f"{order_dir.name}_16s"
                reports_dir = PROJECT_ROOT / "results" / "blast" / task_name / "reports"
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


@router.post("/sangon_16s/settings")
async def update_sangon_settings(req: SangonSettingsRequest):
    """修改生工 16S 根目录并持久化；migrate=True 时把旧目录下的订单整体迁移到新目录"""
    if _sangon_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="生工 16S 流水线运行中，暂不能修改目录")
    new_root_str = req.sangon_root.strip()
    if not new_root_str:
        raise HTTPException(status_code=400, detail="目录不能为空")
    new_root = Path(new_root_str)
    if not new_root.is_absolute():
        raise HTTPException(status_code=400, detail="生工 16S 根目录必须为绝对路径")

    old_root = get_sangon_root()
    migration: Optional[Dict[str, Any]] = None
    try:
        if req.migrate:
            migration = await asyncio.to_thread(migrate_directory, old_root, new_root)
        else:
            new_root.mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"目录迁移失败: {e}")

    settings = save_sangon_settings({"sangon_root": str(new_root)})
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

