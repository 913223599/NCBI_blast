# -*- coding: utf-8 -*-
"""
邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 业务执行器

封装概览聚合、IMAP 附件拉取、后台子进程流水线监控、测试发信与压缩包发送逻辑，
统一通过传入的父路由模块 `ot` 访问可替换依赖，确保测试 monkeypatch 100% 兼容。
"""

import json
import os
import sys
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ....mail_download.batch_state import inspect_batch_pipeline_state, load_batch_manifest
from .mail_composer import (
    build_package_send_draft,
    build_test_send_draft,
    resolve_final_mail_params,
    resolve_safe_send_target,
    send_mail_compat,
)


def collect_mail_pipeline_overview(ot: Any, auth_info_fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """收集邮件流水线配置、收件批次、回传包、报告与最近日志。"""
    raw_cfg = ot._read_mail_cfg()
    auth_info = auth_info_fn(raw_cfg)
    dl_dir = ot._resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))
    send_dir = ot._resolve_dir(raw_cfg.get("send_dir", "results/email_sends"))

    processed_items = _load_processed_items(dl_dir, ot.logger)
    cfg_obj = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    batches = _scan_mail_batches(dl_dir, cfg_obj, send_dir, ot.ANNOTATIONS_DIR)
    outbound_packages, docx_reports = _scan_outbound_artifacts(send_dir, ot.ANNOTATIONS_DIR, ot.logger)
    log_lines = _read_recent_pipeline_logs(dl_dir, ot.logger)

    return {
        "status": "success",
        "config": raw_cfg,
        "auth_ready": auth_info["imap_ready"],
        "auth": auth_info,
        "resolved_download_dir": str(dl_dir),
        "resolved_send_dir": str(send_dir),
        "runtime": ot._mail_pipeline_state,
        "processed_count": len(processed_items),
        "processed_items": processed_items,
        "batches": batches,
        "pending_batches_count": sum(1 for item in batches if item.get("pending")),
        "ignored_batches_count": sum(1 for item in batches if item.get("ignored")),
        "outbound_packages": outbound_packages,
        "docx_reports": docx_reports,
        "pipeline_logs": log_lines,
    }


def _load_processed_items(dl_dir: Path, logger_obj: Any) -> List[Dict[str, Any]]:
    processed_items: List[Dict[str, Any]] = []
    idx_file = dl_dir / "processed_index.json"
    if not idx_file.exists():
        return processed_items
    try:
        idx_data = json.loads(idx_file.read_text(encoding="utf-8"))
        if isinstance(idx_data, dict):
            for meta in idx_data.values():
                if isinstance(meta, dict):
                    processed_items.append(meta)
            processed_items.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
    except Exception as e:
        logger_obj.warning(f"解析 processed_index.json 失败: {e}")
    return processed_items


def _scan_mail_batches(dl_dir: Path, cfg_obj: Any, send_dir: Path, annotations_dir: Path) -> List[Dict[str, Any]]:
    batches: List[Dict[str, Any]] = []
    if not dl_dir.exists():
        return batches
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
        state = inspect_batch_pipeline_state(bdir, cfg_obj, send_dir, annotations_dir, manifest=mf)
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
    return batches


def _scan_outbound_artifacts(
    send_dir: Path,
    annotations_dir: Path,
    logger_obj: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
            except Exception as exc:
                logger_obj.debug("读取回传包清单失败 (%s): %s", mf.name, exc)

        for docx in sorted(send_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True):
            seen_docx_names.add(docx.name)
            docx_reports.append({
                "name": docx.name,
                "path": str(docx),
                "size_kb": round(docx.stat().st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(docx.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "source": "send_dir",
            })

    if annotations_dir.exists():
        for pkg in outbound_packages:
            tid = str(pkg.get("task_id") or "").strip()
            if not tid:
                continue
            anno_dir = annotations_dir / tid
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
    return outbound_packages, docx_reports


def _read_recent_pipeline_logs(dl_dir: Path, logger_obj: Any, limit: int = 120) -> List[str]:
    log_file = dl_dir / "pipeline.log"
    if not log_file.exists():
        return []
    try:
        return log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception as exc:
        logger_obj.debug("读取 pipeline.log 失败 (%s): %s", log_file, exc)
        return []


def execute_mail_fetch_sync(
    ot: Any,
    since_days: Optional[int],
    append_log_fn: Callable[[Path, str, str], None],
) -> Dict[str, Any]:
    """同步扫描 IMAP 收件箱并落盘新附件。"""
    cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=True)
    fetcher = ot.MailFetcher(cfg)
    f_res = fetcher.fetch(since_days=since_days)
    if f_res.connection_error:
        append_log_fn(cfg.resolved_download_dir, "error", f"仅收件失败: {f_res.connection_error}")
        return {"ok": False, "error": f_res.connection_error}
    saved_stats = {"count": 0, "skipped_duplicates": 0, "skipped_processed": 0, "saved_files": []}
    if f_res.matched:
        saver = ot.AttachmentSaver(cfg.resolved_download_dir)
        saved_stats = saver.save(f_res.matched)
    append_log_fn(
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


def build_mail_pipeline_command(
    ot: Any,
    req: Any,
    dl_dir: Path,
    resolved_to: Optional[str],
) -> List[str]:
    """组装邮件自动流水线子进程命令行参数并校验输入路径。"""
    cmd = [sys.executable, "-X", "utf8", "-u", "-m", "src.mail_download.auto_pipeline", "--config", str(ot.MAIL_CONFIG_PATH)]
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
            tp = ot.PROJECT_ROOT / tp
        if not tp.exists() or not tp.is_file():
            raise HTTPException(status_code=404, detail=f"未找到测试输入文件: {req.test_input}")
        cmd += ["--test-input", str(tp)]
    if resolved_to:
        cmd += ["--to", resolved_to]
    if req.subject_prefix:
        cmd += ["--subject-prefix", req.subject_prefix]
    if req.extra_note:
        cmd += ["--extra-note", req.extra_note]
    return cmd


def run_mail_pipeline_subprocess(
    ot: Any,
    cmd: List[str],
    infer_stage_fn: Callable[[str, str], str],
) -> None:
    """在后台线程中运行邮件自动流水线子进程，实时更新运行态并在超时时安全终止。"""
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
        proc = ot.subprocess.Popen(
            cmd,
            cwd=str(ot.PROJECT_ROOT),
            stdout=ot.subprocess.PIPE,
            stderr=ot.subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        def _on_timeout() -> None:
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
                ot._mail_pipeline_state["last_output"] = "\n".join(lines_buf)[-4000:]
                ot._mail_pipeline_state["current_stage"] = infer_stage_fn(
                    line, ot._mail_pipeline_state.get("current_stage", "running")
                )

        rc = proc.wait()
        if timed_out:
            rc = -1
            lines_buf.append("[错误] 流水线执行超时（超过 3600 秒）")
        ot._mail_pipeline_state["last_exit_code"] = rc
        final_out = "\n".join(lines_buf).strip()[-4000:]
        ot._mail_pipeline_state["last_output"] = final_out or ("执行完成" if rc == 0 else f"退出码 {rc}")
        ot._mail_pipeline_state["current_stage"] = "completed" if rc == 0 else "failed"
        ot.logger.info(f"[MailPipeline] 后台任务结束: exit={rc}, stage={ot._mail_pipeline_state['current_stage']}")
    except Exception as exc:
        ot._mail_pipeline_state["last_exit_code"] = -1
        ot._mail_pipeline_state["last_output"] = f"执行异常: {exc}"
        ot._mail_pipeline_state["current_stage"] = "failed"
        ot.logger.error(f"[MailPipeline] 后台任务异常: {exc}")
    finally:
        if timer is not None:
            timer.cancel()
        ot._mail_pipeline_state["running"] = False
        ot._mail_pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def execute_test_send_sync(ot: Any, params: Any) -> Tuple[Any, Dict[str, Any], List[str]]:
    """执行 SMTP 链路自检发信（打包验证文本与可选最新 Word 报告）。"""
    cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    target_to = resolve_safe_send_target(cfg, params.to)
    if not target_to:
        raise ValueError("缺少目标收件人或未配置发件账号")
    if not cfg.smtp_auth_code:
        raise ValueError("缺少 SMTP 授权码，请先配置授权码后再测试发信")

    send_dir = ot._resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
    draft = build_test_send_draft(
        cfg,
        send_dir,
        ot.ANNOTATIONS_DIR,
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
        zip_path = Path(tmp) / final["attachment_name"]
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
        return res, final, attached_files


def execute_package_send_sync(
    ot: Any,
    req: Any,
    resolve_zip_fn: Callable[[str, Any], Tuple[str, Path, Path]],
) -> Tuple[Any, str, Dict[str, Any], Dict[str, Any]]:
    """通过 SMTP 发送已打包的注释结果压缩包。"""
    cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    clean_zip, zip_path, send_dir = resolve_zip_fn(req.zip_name, cfg)

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
        ot.MailSender(cfg),
        zip_path,
        to=target_to,
        subject=final["subject"],
        body=final["body"],
        cc=final["cc_list"],
        from_name=final["from_name"],
        attachment_name=final["attachment_name"],
    )
    return res, clean_zip, draft, final
