# -*- coding: utf-8 -*-
"""
生工 16S 自动化 BLAST 与下载流水线执行器

承接原 routes/other_tools_modules/sangon_16s_routes.py 中的目录批处理、
概览聚合、CSV 解析、后台下载串联与结果邮件发送业务，保持路由层精简。
"""

import csv
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ....blast.manager import TaskStatus
from ....utils.archive_guard import safe_extract_zip
from .mail_composer import (
    build_sangon_result_draft,
    resolve_final_mail_params,
    resolve_safe_send_target,
    send_mail_compat,
)
from .sangon_downloader import download_sangon_orders
from .sangon_ignore_rules import list_ignored_orders, normalize_order_key
from .sangon_order_annotator import annotate_sangon_orders
from .sangon_settings import get_sangon_auth_status, load_sangon_settings
from .sangon_zip_importer import import_order_zips_from_downloads, scan_downloads_for_sangon_zips
from .schemas import SANGON_CSV_HEADERS


def execute_sangon_dirs_pipeline(
    ot: Any,
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
    mgr = ot.get_blast_manager()

    for idx, order_dir in enumerate(target_dirs, start=1):
        base_pct = progress_start + int((idx - 1) * span / total_orders)
        done_pct = progress_start + int(idx * span / total_orders)
        ot._sangon_pipeline_state["current_order"] = order_dir.name
        ot._sangon_pipeline_state["current_stage"] = "extracting"
        ot._append_sangon_log(f"({idx}/{total_orders}) 正在检查订单目录: {order_dir.name}")

        fastas, res_dir = _prepare_order_fastas(ot, root_path, order_dir, downloads_dir)
        if not fastas:
            skipped_missing += 1
            ot._append_sangon_log(
                f"[跳过] {order_dir.name} 未找到压缩包或 *.1.fasta 主序列（请先自动或手动下载压缩包）",
                level="warning",
            )
            _update_sangon_summary(ot, done_pct, total_orders, processed, skipped_missing, failed)
            continue

        task_name = f"{order_dir.name}_16s"
        blast_ok = _ensure_order_blast_reports(
            ot, mgr, task_name, fastas, evalue, hitlist_size, force_reblast, base_pct, done_pct
        )
        if not blast_ok:
            failed += 1
            _update_sangon_summary(ot, done_pct, total_orders, processed, skipped_missing, failed)
            continue

        ot._sangon_pipeline_state["current_stage"] = "exporting"
        ot._append_sangon_log("正在执行物种拉丁文批量翻译并导出 16S鉴定结果.csv ...")
        stats = ot._export_sangon_order_csv(task_name, res_dir)
        processed += 1
        ot._append_sangon_log(
            f"订单 {order_dir.name} 导出完成: 共 {stats['total']} 样本, "
            f"命中 {stats['with_hits']}, 未命中 {stats['no_hits']}"
        )
        _update_sangon_summary(ot, done_pct, total_orders, processed, skipped_missing, failed)

    return {
        "total": total_orders,
        "processed": processed,
        "skipped_missing": skipped_missing,
        "failed": failed,
    }


def _update_sangon_summary(
    ot: Any,
    done_pct: int,
    total_orders: int,
    processed: int,
    skipped_missing: int,
    failed: int,
) -> None:
    with ot._sangon_pipeline_lock:
        ot._sangon_pipeline_state["progress"] = done_pct
        ot._sangon_pipeline_state["summary"] = {
            "total": total_orders,
            "processed": processed,
            "skipped_missing": skipped_missing,
            "failed": failed,
        }


def _prepare_order_fastas(
    ot: Any,
    root_path: Path,
    order_dir: Path,
    downloads_dir: Optional[str],
) -> Tuple[List[Path], Path]:
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
            root_path, dl_dir, order_names=[order_dir.name], auto_create_order=False
        )
        if imp["imported_count"] > 0:
            ot._append_sangon_log(
                f"已从下载目录自动认领压缩包: {imp['imported'][0]['zip_name']} -> 原始压缩包/"
            )

    if not fastas and zip_dir.exists():
        for zf_path in sorted(zip_dir.glob("*.zip")):
            ot._append_sangon_log(f"正在解压原始压缩包: {zf_path.name} -> 原始数据/")
            safe_extract_zip(zf_path, raw_dir)
        fastas = sorted([p for p in raw_dir.rglob("*.1.fasta") if "haplotype" not in p.name.lower()])
    return fastas, res_dir


def _ensure_order_blast_reports(
    ot: Any,
    mgr: Any,
    task_name: str,
    fastas: List[Path],
    evalue: str,
    hitlist_size: str,
    force_reblast: bool,
    base_pct: int,
    done_pct: int,
) -> bool:
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
    if len(existing_csvs) >= len(fastas) and not force_reblast:
        ot._append_sangon_log(f"复用已有 BLAST 报告 ({len(existing_csvs)} 份 CSV)")
        return True

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
            ot._append_sangon_log(f"[失败] 未查询到 BLAST 任务状态: {task_id}", level="error")
            return False
        st = st_info.get("status", "unknown")
        prog = st_info.get("progress", 0)
        ot._sangon_pipeline_state["progress"] = base_pct + int(
            (max(0, min(100, int(prog or 0))) / 100.0) * max(1, done_pct - base_pct)
        )
        if st == TaskStatus.COMPLETED.value:
            ot._append_sangon_log(f"BLAST 任务结束: {st} (进度 {prog}%)")
            return True
        if st in (TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.PAUSED.value):
            err_detail = st_info.get("error") or st
            ot._append_sangon_log(f"[失败] BLAST 任务未完成 ({st}): {err_detail}", level="error")
            return False
        if time.monotonic() > wait_deadline:
            ot._append_sangon_log(f"[超时] BLAST 任务等待超时 (>3600s): {task_id}", level="error")
            return False
        time.sleep(1.0)


def collect_sangon_overview(
    ot: Any,
    sangon_root: Optional[str],
    downloads_dir: Optional[str],
) -> Dict[str, Any]:
    """扫描生工根目录与下载目录，聚合订单列表、待认领包与环境状态。"""
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
    db_16s = ot.PROJECT_ROOT / "database" / "16S" / "ncbi" / "16S_ribosomal_RNA.nin"
    return {
        "status": "success",
        "sangon_root": str(root_path),
        "downloads_dir": str(dl_dir),
        "downloads_exists": dl_dir.exists(),
        "download_candidates": download_candidates,
        "pending_download_count": sum(1 for c in download_candidates if not c["archived"] and not c.get("ignored")),
        "ignored_download_count": sum(1 for c in download_candidates if not c["archived"] and c.get("ignored")),
        "settings": load_sangon_settings(),
        "sangon_auth": get_sangon_auth_status(),
        "browser_env": ot.inspect_headless_browser(
            project_root=ot.PROJECT_ROOT, config_path=ot.CONFIG_JSON_PATH, probe_launch=False
        ),
        "root_exists": root_path.exists(),
        "db_16s_ready": db_16s.exists(),
        "runtime": ot._snapshot_sangon_runtime(),
        "orders": orders,
    }


def read_sangon_csv_rows(csv_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    rows: List[Dict[str, str]] = []
    headers: List[str] = SANGON_CSV_HEADERS
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = list(csv.reader(f))
        if reader:
            headers = reader[0]
            for r in reader[1:]:
                if not r:
                    continue
                rows.append({h: (r[idx] if idx < len(r) else "") for idx, h in enumerate(headers)})
    return headers, rows


def resolve_sangon_run_targets(
    ot: Any,
    root_path: Path,
    order_names: Optional[List[str]],
    force_reblast: bool,
) -> Tuple[List[Path], int]:
    target_dirs: List[Path] = []
    skipped_ignored = 0
    if order_names:
        for name in order_names:
            p = root_path / name
            if p.exists() and p.is_dir():
                target_dirs.append(p)
        return target_dirs, skipped_ignored

    ignored_keys = set(list_ignored_orders().keys())
    for child in sorted(root_path.iterdir()):
        if child.is_dir() and re.match(r"^\d{8}_\d+", child.name):
            info = ot._inspect_sangon_order_dir(child)
            order_key = normalize_order_key(str(info.get("order_no") or child.name))
            if order_key in ignored_keys:
                skipped_ignored += 1
                continue
            if info["status"] != "completed" or force_reblast:
                target_dirs.append(child)
    return target_dirs, skipped_ignored


def run_sangon_batch_bg(
    ot: Any,
    root_path: Path,
    target_dirs: List[Path],
    req: Any,
    execute_dirs_fn: Callable[..., Dict[str, Any]],
) -> None:
    """后台线程执行选定生工订单的解压 + 16S BLAST + 翻译导出流水线。"""
    processed = 0
    skipped_missing = 0
    failed = 0
    total_orders = len(target_dirs)
    try:
        res = execute_dirs_fn(
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
            summary_msg = f"生工 16S 批处理结束：成功 {processed} 个，跳过缺包 {skipped_missing} 个，失败 {failed} 个"
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
            summary_msg = f"处理完成：成功 {processed} 个订单，另有 {skipped_missing} 个待下载订单因缺少压缩包已跳过"
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


def run_sangon_download_bg(
    ot: Any,
    root_path: Path,
    dl_dir: Path,
    targets: List[Dict[str, Any]],
    params: Any,
    execute_dirs_fn: Callable[..., Dict[str, Any]],
    *,
    account: str,
    password: str,
    confirm_fee: bool,
    needs_web_login: bool,
) -> None:
    """后台线程执行本地认领 + 生工官网批量下载 + 可选 16S BLAST 串联。"""
    auto_run = params.auto_run_blast
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
            _ensure_browser_ready_for_sangon(ot)

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
            blast_res = execute_dirs_fn(
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
            final_msg = _format_download_only_summary(
                claimed_cnt, downloaded_cnt, processed_cnt, skipped_cnt, failed_cnt, captcha_blocked
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


def _ensure_browser_ready_for_sangon(ot: Any) -> None:
    env_snap = ot.inspect_headless_browser(
        project_root=ot.PROJECT_ROOT, config_path=ot.CONFIG_JSON_PATH, probe_launch=False
    )
    if env_snap.get("ready"):
        return
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


def _format_download_only_summary(
    claimed_cnt: int,
    downloaded_cnt: int,
    processed_cnt: int,
    skipped_cnt: int,
    failed_cnt: int,
    captcha_blocked: bool,
) -> str:
    if captcha_blocked:
        return (
            f"已停止：生工触发安全/人机验证（已完成 {processed_cnt} 个，失败 {failed_cnt} 个），请手动打开下载页验证"
        )
    if failed_cnt > 0:
        return f"自动下载结束：认领 {claimed_cnt}，官网下载 {downloaded_cnt}，跳过 {skipped_cnt}，失败 {failed_cnt}"
    if processed_cnt == 0 and skipped_cnt > 0:
        return f"自动下载完成：暂无新入库包（跳过 {skipped_cnt} 个订单，详见运行日志）"
    return f"自动下载完成：官网下载 {downloaded_cnt} 个，本地认领 {claimed_cnt} 个" + (
        f"，跳过 {skipped_cnt} 个" if skipped_cnt else ""
    )


def execute_sangon_send_result_sync(
    ot: Any,
    clean_name: str,
    csv_path: Path,
    req: Any,
) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """将生工 16S 订单结果 CSV 打包并通过 SMTP 发送。"""
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
