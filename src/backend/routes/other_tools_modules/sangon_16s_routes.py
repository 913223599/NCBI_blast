# -*- coding: utf-8 -*-
"""
生工 16S 测序结果自动化 BLAST 与导出流程 路由子模块
说明：通过父路由模块 `other_tools` 动态访问共享配置、运行态及可替换依赖，
确保现有 API 契约与测试 monkeypatch 完全兼容。
"""
import asyncio
import csv
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from ...services.other_tools.dir_migrator import migrate_directory
from ...services.other_tools.history_cleaner import cleanup_sangon_history
from ...services.other_tools.mail_composer import (
    build_sangon_result_draft,
    resolve_final_mail_params,
    resolve_safe_send_target,
    send_mail_compat,
)
from ...services.other_tools.sangon_downloader import (
    _collect_pending_download_targets,
    build_sangon_order_url,
    download_sangon_orders,
)
from ...services.other_tools.sangon_ignore_rules import (
    ignore_orders,
    list_ignored_orders,
    normalize_order_key,
    replace_ignore_rules,
    unignore_orders,
)
from ...services.other_tools.sangon_mail_scanner import init_sangon_order_dir
from ...services.other_tools.sangon_order_annotator import annotate_sangon_orders
from ...services.other_tools.sangon_settings import (
    get_sangon_auth_status,
    get_sangon_root,
    load_sangon_settings,
    resolve_sangon_credentials,
    save_sangon_credentials,
    save_sangon_settings,
)
from ...services.other_tools.sangon_zip_importer import (
    import_order_zips_from_downloads,
    scan_downloads_for_sangon_zips,
)
from ...services.other_tools.schemas import (
    SANGON_CSV_HEADERS,
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
from ....blast.manager import TaskStatus

sangon_router = APIRouter()


def _ot():
    from .. import other_tools as ot
    return ot


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
    ot = _ot()
    processed = 0
    skipped_missing = 0
    failed = 0
    total_orders = len(target_dirs)
    span = max(1, progress_end - progress_start)
    mgr = ot.get_blast_manager()

    for idx, order_dir in enumerate(target_dirs, start=1):
        base_pct = progress_start + int((idx - 1) * span / total_orders)
        done_pct = progress_start + int(idx * span / total_orders)
        ot._sangon_pipeline_state["current_order"] = order_dir.name
        ot._sangon_pipeline_state["current_stage"] = "extracting"
        ot._append_sangon_log(f"({idx}/{total_orders}) 正在检查订单目录: {order_dir.name}")

        zip_dir = order_dir / "原始压缩包"
        raw_dir = order_dir / "原始数据"
        res_dir = order_dir / "BLAST结果"
        raw_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)

        fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])
        has_zip = zip_dir.exists() and any(zip_dir.glob("*.zip"))
        if not fastas and not has_zip:
            dl_dir = ot._sangon_downloads_or_default(downloads_dir)
            imp = import_order_zips_from_downloads(
                root_path,
                dl_dir,
                order_names=[order_dir.name],
                auto_create_order=False,
            )
            if imp["imported_count"] > 0:
                ot._append_sangon_log(
                    f"已从下载目录自动认领压缩包: {imp['imported'][0]['zip_name']} -> 原始压缩包/"
                )

        if not fastas and zip_dir.exists():
            from ....utils.archive_guard import safe_extract_zip
            for zf_path in sorted(zip_dir.glob("*.zip")):
                ot._append_sangon_log(f"正在解压原始压缩包: {zf_path.name} -> 原始数据/")
                safe_extract_zip(zf_path, raw_dir)
            fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])

        if not fastas:
            skipped_missing += 1
            ot._append_sangon_log(
                f"[跳过] {order_dir.name} 未找到压缩包或 *.1.fasta 主序列（请先自动或手动下载压缩包）",
                level="warning",
            )
            with ot._sangon_pipeline_lock:
                ot._sangon_pipeline_state["progress"] = done_pct
                ot._sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }
            continue

        task_name = f"{order_dir.name}_16s"
        task_cache_dir = ot.PROJECT_ROOT / "results" / "blast" / task_name
        reports_dir = task_cache_dir / "reports"

        if force_reblast:
            ot._append_sangon_log(f"强制重新比对：正在清理旧缓存与记录 ({task_name})")
            try:
                mgr.delete_task(task_name)
            except Exception as del_err:
                ot._append_sangon_log(f"清理任务数据库记录提示: {del_err}", level="warning")
            if task_cache_dir.exists():
                shutil.rmtree(task_cache_dir, ignore_errors=True)

        existing_csvs = list(reports_dir.glob("*.csv")) if reports_dir.exists() else []

        blast_ok = True
        if len(existing_csvs) < len(fastas) or force_reblast:
            ot._sangon_pipeline_state["current_stage"] = "blasting"
            ot._append_sangon_log(f"提交 16S BLAST 比对任务 ({len(fastas)} 条主序列): {task_name}")
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
                    ot._append_sangon_log(f"[失败] 未查询到 BLAST 任务状态: {task_id}", level="error")
                    break
                st = st_info.get("status", "unknown")
                prog = st_info.get("progress", 0)
                ot._sangon_pipeline_state["progress"] = base_pct + int(
                    (max(0, min(100, int(prog or 0))) / 100.0) * max(1, done_pct - base_pct)
                )
                if st == TaskStatus.COMPLETED.value:
                    ot._append_sangon_log(f"BLAST 任务结束: {st} (进度 {prog}%)")
                    break
                if st in (TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.PAUSED.value):
                    blast_ok = False
                    err_detail = st_info.get("error") or st
                    ot._append_sangon_log(f"[失败] BLAST 任务未完成 ({st}): {err_detail}", level="error")
                    break
                if time.monotonic() > wait_deadline:
                    blast_ok = False
                    ot._append_sangon_log(f"[超时] BLAST 任务等待超时 (>3600s): {task_id}", level="error")
                    break
                time.sleep(1.0)
        else:
            ot._append_sangon_log(f"复用已有 BLAST 报告 ({len(existing_csvs)} 份 CSV)")

        if not blast_ok:
            failed += 1
            with ot._sangon_pipeline_lock:
                ot._sangon_pipeline_state["progress"] = done_pct
                ot._sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }
            continue

        ot._sangon_pipeline_state["current_stage"] = "exporting"
        ot._append_sangon_log("正在执行物种拉丁文批量翻译并导出 16S鉴定结果.csv ...")
        stats = ot._export_sangon_order_csv(task_name, res_dir)
        processed += 1
        ot._append_sangon_log(
            f"订单 {order_dir.name} 导出完成: 共 {stats['total']} 样本, "
            f"命中 {stats['with_hits']}, 未命中 {stats['no_hits']}"
        )
        with ot._sangon_pipeline_lock:
            ot._sangon_pipeline_state["progress"] = done_pct
            ot._sangon_pipeline_state["summary"] = {
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


def _resolve_sangon_order_csv_path(order_dir_name: str, sangon_root: Optional[str]) -> tuple[str, Path]:
    ot = _ot()
    clean_name = (order_dir_name or "").strip()
    if not clean_name or any(sep in clean_name for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的订单目录名: {order_dir_name}")

    root_path = ot._sangon_root_or_default(sangon_root)
    order_dir = root_path / clean_name
    if not order_dir.exists() or not order_dir.is_dir() or order_dir.parent.resolve() != root_path.resolve():
        raise HTTPException(status_code=404, detail=f"未找到订单目录: {clean_name}")

    csv_path = order_dir / "BLAST结果" / "16S鉴定结果.csv"
    if not csv_path.exists() or not csv_path.is_file():
        raise HTTPException(status_code=404, detail="该订单尚未生成 16S鉴定结果.csv，请先运行比对导出")
    return clean_name, csv_path


@sangon_router.get("/sangon_16s/overview")
async def get_sangon_16s_overview(sangon_root: Optional[str] = None, downloads_dir: Optional[str] = None):
    """获取生工 16S 自动化流程目录、浏览器下载目录待认领压缩包与所有订单状态概览"""
    ot = _ot()
    root_path = ot._sangon_root_or_default(sangon_root)
    dl_dir = ot._sangon_downloads_or_default(downloads_dir)
    orders: List[Dict[str, Any]] = []
    order_by_no: Dict[str, Dict[str, Any]] = {}

    if root_path.exists() and root_path.is_dir():
        for child in sorted(root_path.iterdir(), key=lambda p: p.name, reverse=True):
            if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
                info = ot._inspect_sangon_order_dir(child)
                orders.append(info)
                ono = info.get("order_no", "")
                if ono and ono not in order_by_no:
                    order_by_no[ono] = info

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

    db_16s = ot.PROJECT_ROOT / "database" / "16S" / "ncbi" / "16S_ribosomal_RNA.nin"
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
        "browser_env": ot.inspect_headless_browser(
            project_root=ot.PROJECT_ROOT,
            config_path=ot.CONFIG_JSON_PATH,
            probe_launch=False,
        ),
        "root_exists": root_path.exists(),
        "db_16s_ready": db_16s.exists(),
        "runtime": ot._snapshot_sangon_runtime(),
        "orders": orders,
    }


@sangon_router.get("/sangon_16s/order/{order_dir_name}/results")
async def get_sangon_order_results(order_dir_name: str, sangon_root: Optional[str] = None):
    """读取指定生工 16S 订单的 11 列鉴定结果 CSV 供前端在线表格展示"""
    clean_name, csv_path = _resolve_sangon_order_csv_path(order_dir_name, sangon_root)

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
        "order_dir_name": clean_name,
        "csv_path": str(csv_path),
        "headers": headers,
        "rows": rows,
    }


@sangon_router.post("/sangon_16s/scan_mail")
async def scan_sangon_notification_mails(
    sangon_root: Optional[str] = None,
    req: Optional[SangonScanMailRequest] = Body(default=None),
):
    """连接邮箱扫描生工 (info1@sangon.com) 16S 通知邮件，支持批内/历史去重与服务端翻页"""
    ot = _ot()
    params = req or SangonScanMailRequest()
    root_dir_path = ot._sangon_root_or_default(params.sangon_root or sangon_root)

    def _do_scan():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=True)
        return ot.scan_sangon_mails(
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


@sangon_router.post("/sangon_16s/init_order")
async def init_sangon_order_directory(req: SangonInitOrderRequest):
    """手动为指定通知邮件初始化生工订单三级目录"""
    ot = _ot()
    root_path = ot._sangon_root_or_default(req.sangon_root)
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


@sangon_router.post("/sangon_16s/run_pipeline")
async def run_sangon_16s_pipeline(req: SangonRunRequest):
    """对选定的生工 16S 订单执行自动解压 -> 16S BLAST 比对 -> 中文翻译与 11 列 CSV 导出"""
    ot = _ot()
    root_path = ot._sangon_root_or_default(req.sangon_root)
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
                info = ot._inspect_sangon_order_dir(child)
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

    with ot._sangon_pipeline_lock:
        if ot._sangon_pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")
        start_msg = f"启动生工 16S 批处理，共 {len(target_dirs)} 个订单"
        ot._sangon_pipeline_state["running"] = True
        ot._sangon_pipeline_state["current_order"] = None
        ot._sangon_pipeline_state["current_stage"] = "running"
        ot._sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ot._sangon_pipeline_state["finished_at"] = None
        ot._sangon_pipeline_state["progress"] = 0
        ot._sangon_pipeline_state["last_message"] = start_msg
        ot._sangon_pipeline_state["summary"] = {
            "total": len(target_dirs),
            "processed": 0,
            "skipped_missing": 0,
            "failed": 0,
        }
        ot._sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] {start_msg}"]
    ot.logger.info("[Sangon16S] %s", start_msg)

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

            ot._sangon_pipeline_state["progress"] = 100
            ot._sangon_pipeline_state["current_stage"] = final_stage
            ot._append_sangon_log(summary_msg, level=log_lvl)
        except Exception as exc:
            ot._sangon_pipeline_state["current_stage"] = "failed"
            ot._sangon_pipeline_state["progress"] = 100
            ot._append_sangon_log(f"执行异常: {exc}", level="error")
        finally:
            with ot._sangon_pipeline_lock:
                ot._sangon_pipeline_state["running"] = False
                ot._sangon_pipeline_state["current_order"] = None
                ot._sangon_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ot._sangon_pipeline_state["summary"] = {
                    "total": total_orders,
                    "processed": processed,
                    "skipped_missing": skipped_missing,
                    "failed": failed,
                }

    asyncio.get_running_loop().run_in_executor(None, _run_sangon_bg)
    return {"status": "started", "runtime": ot._snapshot_sangon_runtime()}


@sangon_router.post("/sangon_16s/auth")
async def update_sangon_auth_credentials(req: SangonAuthUpdateRequest):
    """保存或更新生工官网登录账号与独立密钥文件 (.sangon_auth)，仅返脱敏掩码"""
    if req.account is None and req.password is None and req.auto_confirm_fee is None:
        raise HTTPException(status_code=400, detail="未提供需要更新的生工账号配置")
    auth_info = save_sangon_credentials(
        account=req.account,
        password=req.password,
        auto_confirm_fee=req.auto_confirm_fee,
    )
    return {"status": "success", "sangon_auth": auth_info, "settings": load_sangon_settings()}


@sangon_router.post("/sangon_16s/download_orders")
async def download_sangon_orders_endpoint(req: Optional[SangonDownloadRequest] = Body(default=None)):
    """后台异步执行：优先从本地 Downloads 认领 -> 登录生工官网批量下载压缩包 -> 可选串联 16S BLAST 与导出"""
    ot = _ot()
    params = req or SangonDownloadRequest()
    root_path = ot._sangon_root_or_default(params.sangon_root)
    if not root_path.exists():
        raise HTTPException(status_code=400, detail=f"生工 16S 目录不存在: {root_path}")
    dl_dir = ot._sangon_downloads_or_default(params.downloads_dir)

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

    dl_cands = (
        scan_downloads_for_sangon_zips(dl_dir, order_nos=[t["order_no"] for t in targets])
        if dl_dir.exists()
        else []
    )
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

    with ot._sangon_pipeline_lock:
        if ot._sangon_pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")
        mode_label = "自动下载并比对" if auto_run else "自动下载压缩包"
        start_msg = f"启动生工 16S {mode_label}，待检查 {len(targets)} 个订单"
        ot._sangon_pipeline_state["running"] = True
        ot._sangon_pipeline_state["current_order"] = None
        ot._sangon_pipeline_state["current_stage"] = "downloading"
        ot._sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ot._sangon_pipeline_state["finished_at"] = None
        ot._sangon_pipeline_state["progress"] = 0
        ot._sangon_pipeline_state["last_message"] = start_msg
        ot._sangon_pipeline_state["summary"] = {
            "total": len(targets),
            "processed": 0,
            "skipped_missing": 0,
            "failed": 0,
        }
        ot._sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] {start_msg}"]
    ot.logger.info("[Sangon16S] %s", start_msg)

    def _run_download_bg():
        total_cnt = len(targets)
        dl_end_pct = 45 if auto_run else 100
        processed_cnt = 0
        skipped_cnt = 0
        failed_cnt = 0
        try:
            def _on_dl_prog(idx: int, total_web: int, dname: str) -> None:
                ot._sangon_pipeline_state["current_order"] = dname
                ot._sangon_pipeline_state["current_stage"] = "downloading"
                ot._sangon_pipeline_state["progress"] = int(((idx - 1) / max(1, total_web)) * dl_end_pct)

            if needs_web_login:
                env_snap = ot.inspect_headless_browser(
                    project_root=ot.PROJECT_ROOT,
                    config_path=ot.CONFIG_JSON_PATH,
                    probe_launch=False,
                )
                if not env_snap.get("ready"):
                    ot._append_sangon_log("检测到无头浏览器尚未就绪，正在执行启动前环境自修复...")
                    repaired_env = ot.repair_headless_browser(
                        project_root=ot.PROJECT_ROOT,
                        config_path=ot.CONFIG_JSON_PATH,
                        auto_install=True,
                        probe_launch=False,
                        progress_cb=lambda m: ot._append_sangon_log(m),
                    )
                    for act in repaired_env.get("actions") or []:
                        ot._append_sangon_log(f"[浏览器自修复] {act}")
                    if not repaired_env.get("ready"):
                        ot._append_sangon_log("无头浏览器未能完全就绪，将继续尝试可用兜底或认领已有本地包。")

            dl_res = download_sangon_orders(
                root_path,
                dl_dir,
                order_names=[t["dir_name"] for t in targets],
                account=account,
                password=password,
                auto_confirm_fee=confirm_fee,
                headless=None,
                progress_cb=_on_dl_prog,
                log_cb=lambda m: ot._append_sangon_log(m),
            )
            claimed_cnt = dl_res["claimed_count"]
            downloaded_cnt = dl_res["downloaded_count"]
            skipped_cnt = dl_res["skipped_count"]
            failed_cnt = dl_res["failed_count"]
            captcha_blocked = dl_res.get("captcha_blocked", False)
            ready_dirs = [
                Path(root_path / name)
                for name in dl_res.get("processed_dir_names") or []
                if (root_path / name).is_dir()
            ]

            ot._sangon_pipeline_state["progress"] = dl_end_pct

            if auto_run and ready_dirs and not captcha_blocked:
                ot._append_sangon_log(
                    f"自动下载阶段结束（认领 {claimed_cnt}，官网下载 {downloaded_cnt}），开始衔接 16S BLAST 比对..."
                )
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
                    final_msg = (
                        f"已停止：生工触发安全/人机验证（已完成 {processed_cnt} 个，失败 {failed_cnt} 个），请手动打开下载页验证"
                    )
                elif failed_cnt > 0:
                    final_msg = f"自动下载结束：认领 {claimed_cnt}，官网下载 {downloaded_cnt}，跳过 {skipped_cnt}，失败 {failed_cnt}"
                elif processed_cnt == 0 and skipped_cnt > 0:
                    final_msg = f"自动下载完成：暂无新入库包（跳过 {skipped_cnt} 个订单，详见运行日志）"
                else:
                    final_msg = f"自动下载完成：官网下载 {downloaded_cnt} 个，本地认领 {claimed_cnt} 个" + (
                        f"，跳过 {skipped_cnt} 个" if skipped_cnt else ""
                    )

            ot._sangon_pipeline_state["progress"] = 100
            ot._sangon_pipeline_state["current_stage"] = (
                "failed" if (failed_cnt > 0 and processed_cnt == 0) or captcha_blocked else "completed"
            )
            ot._append_sangon_log(final_msg, level="warning" if failed_cnt > 0 or captcha_blocked else "info")
        except Exception as exc:
            failed_cnt += 1
            ot._sangon_pipeline_state["current_stage"] = "failed"
            ot._sangon_pipeline_state["progress"] = 100
            ot._append_sangon_log(f"自动下载执行异常: {exc}", level="error")
        finally:
            with ot._sangon_pipeline_lock:
                ot._sangon_pipeline_state["running"] = False
                ot._sangon_pipeline_state["current_order"] = None
                ot._sangon_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ot._sangon_pipeline_state["summary"] = {
                    "total": total_cnt,
                    "processed": processed_cnt,
                    "skipped_missing": skipped_cnt,
                    "failed": failed_cnt,
                }

    asyncio.get_running_loop().run_in_executor(None, _run_download_bg)
    return {"status": "started", "runtime": ot._snapshot_sangon_runtime()}


@sangon_router.post("/sangon_16s/import_downloads")
async def import_sangon_downloads(req: Optional[SangonImportDownloadsRequest] = Body(default=None)):
    """扫描浏览器下载目录中的生工测序压缩包，安全复制归档到对应订单 原始压缩包/"""
    ot = _ot()
    params = req or SangonImportDownloadsRequest()
    root_path = ot._sangon_root_or_default(params.sangon_root)
    dl_dir = ot._sangon_downloads_or_default(params.downloads_dir)
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


@sangon_router.post("/sangon_16s/send_preview")
async def preview_sangon_order_result_mail(req: SangonSendPreviewRequest):
    """生成指定生工 16S 订单结果邮件的默认草稿，供前端弹窗预填与逐项修改。"""
    ot = _ot()
    clean_name, csv_path = _resolve_sangon_order_csv_path(req.order_dir_name, req.sangon_root)

    def _do_preview():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
        return build_sangon_result_draft(clean_name, csv_path, cfg, extra_note=req.extra_note)

    draft = await asyncio.to_thread(_do_preview)
    return {"status": "success", **draft}


@sangon_router.post("/sangon_16s/send_result")
async def send_sangon_order_result_mail(req: SangonSendResultRequest):
    """将指定订单的 16S 鉴定结果 CSV 打包为 zip 并通过 SMTP 发送。"""
    ot = _ot()
    clean_name, csv_path = _resolve_sangon_order_csv_path(req.order_dir_name, req.sangon_root)

    def _do_send_16s():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
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
                ot.MailSender(cfg),
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


@sangon_router.post("/sangon_16s/settings")
async def update_sangon_settings(req: SangonSettingsRequest):
    """修改生工 16S 根目录（支持自动迁移）、下载目录，以及全局忽略订单与邮件主题关键词配置"""
    ot = _ot()
    if ot._sangon_pipeline_state["running"] and (req.sangon_root is not None or req.downloads_dir is not None):
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
    return {
        "status": "success",
        "settings": settings,
        "sangon_auth": get_sangon_auth_status(),
        "migration": migration,
    }


@sangon_router.post("/sangon_16s/ignore")
async def update_sangon_ignored_orders(req: SangonIgnoreRequest):
    """将指定订单号/目录名加入或移出生工 16S 全局忽略名单"""
    if not req.order_keys:
        raise HTTPException(status_code=400, detail="未提供需要处理的订单号或目录名")
    if req.ignore:
        res = ignore_orders(req.order_keys, reason=req.reason, dir_names=req.dir_names)
    else:
        res = unignore_orders(req.order_keys)
    return {"status": "success", "ignore": req.ignore, **res}


@sangon_router.post("/sangon_16s/cleanup")
async def cleanup_sangon_orders(req: SangonCleanupRequest):
    """按订单清理生工 16S 历史数据（解压文件 / BLAST 缓存 / 结果 CSV / 整个订单目录 / 扫描去重记录）"""
    ot = _ot()
    if ot._sangon_pipeline_state["running"]:
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
        cleanup_sangon_history, get_sangon_root(), ot.BLAST_RESULTS_ROOT, order_names, req.targets
    )
    return {"status": "success", **res}
