# -*- coding: utf-8 -*-
"""
邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 路由子模块
说明：通过父路由模块 `other_tools` 动态访问共享配置、运行态及可替换依赖，
确保现有 API 契约与测试 monkeypatch 完全兼容。
"""
import asyncio
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from ...services.other_tools.dir_migrator import migrate_directory
from ...services.other_tools.history_cleaner import cleanup_mail_history
from ...services.other_tools.mail_composer import (
    build_package_send_draft,
    build_test_send_draft,
    resolve_final_mail_params,
    resolve_safe_send_target,
    send_mail_compat,
)
from ...services.other_tools.schemas import (
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
)
from ...services.other_tools.secret_store import (
    mask_secret,
    read_secret,
    resolve_secret_path,
    write_secret,
)
from ....mail_download.batch_state import (
    inspect_batch_pipeline_state,
    load_batch_manifest,
    mark_batch_ignored,
)

mail_router = APIRouter()


def _ot():
    from .. import other_tools as ot
    return ot


def _mail_auth_info(raw_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """汇总 IMAP / SMTP 授权码状态（仅返回掩码）"""
    ot = _ot()
    cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    imap_file = resolve_secret_path(ot.PROJECT_ROOT, raw_cfg.get("auth_code_file", ".mail_auth"))
    smtp_file = resolve_secret_path(ot.PROJECT_ROOT, raw_cfg.get("smtp_auth_code_file", ".mail_smtp_auth"))
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


def _append_mail_pipeline_log(dl_dir: Path, level: str, msg: str) -> None:
    """向 pipeline.log 追加审计日志行。"""
    ot = _ot()
    try:
        dl_dir.mkdir(parents=True, exist_ok=True)
        log_file = dl_dir / "pipeline.log"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} [{level.upper()}] {msg}\n")
    except OSError as exc:
        ot.logger.warning(f"写入 pipeline.log 失败: {exc}")


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


def _resolve_outbound_zip_path(zip_name: str, cfg: Any) -> tuple[str, Path, Path]:
    ot = _ot()
    clean_zip = (zip_name or "").strip()
    if (
        not clean_zip
        or any(sep in clean_zip for sep in ("/", "\\", ".."))
        or not clean_zip.lower().endswith(".zip")
    ):
        raise HTTPException(status_code=400, detail=f"非法的压缩包文件名: {zip_name}")

    send_dir = ot._resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
    zip_path = send_dir / clean_zip
    if not zip_path.exists() or not zip_path.is_file() or zip_path.parent.resolve() != send_dir.resolve():
        raise HTTPException(status_code=404, detail=f"未找到回传压缩包: {clean_zip}")
    return clean_zip, zip_path, send_dir


@mail_router.get("/mail_pipeline/overview")
async def get_mail_pipeline_overview():
    """获取邮件自动注释回传流水线完整状态、批次列表、已发记录与日志"""
    ot = _ot()
    raw_cfg = ot._read_mail_cfg()
    auth_info = _mail_auth_info(raw_cfg)
    auth_ready = auth_info["imap_ready"]

    dl_dir = ot._resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))
    send_dir = ot._resolve_dir(raw_cfg.get("send_dir", "results/email_sends"))

    processed_items: List[Dict[str, Any]] = []
    idx_file = dl_dir / "processed_index.json"
    if idx_file.exists():
        try:
            idx_data = json.loads(idx_file.read_text(encoding="utf-8"))
            if isinstance(idx_data, dict):
                for _sha, meta in idx_data.items():
                    if isinstance(meta, dict):
                        processed_items.append(meta)
                processed_items.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
        except Exception as e:
            ot.logger.warning(f"解析 processed_index.json 失败: {e}")

    cfg_obj = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
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
            state = inspect_batch_pipeline_state(bdir, cfg_obj, send_dir, ot.ANNOTATIONS_DIR, manifest=mf)
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

    if ot.ANNOTATIONS_DIR.exists():
        for pkg in outbound_packages:
            tid = str(pkg.get("task_id") or "").strip()
            if not tid:
                continue
            anno_dir = ot.ANNOTATIONS_DIR / tid
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
        "runtime": ot._mail_pipeline_state,
        "processed_count": len(processed_items),
        "processed_items": processed_items,
        "batches": batches,
        "pending_batches_count": pending_batches_count,
        "ignored_batches_count": ignored_batches_count,
        "outbound_packages": outbound_packages,
        "docx_reports": docx_reports,
        "pipeline_logs": log_lines,
    }


@mail_router.post("/mail_pipeline/config")
async def update_mail_pipeline_config(req: MailConfigUpdateRequest):
    """更新保存 mail_config.json；下载/回传目录变更时自动迁移已有数据"""
    ot = _ot()
    existing = ot._read_mail_cfg()

    old_dl = ot._resolve_dir(existing.get("download_dir", "results/email_downloads"))
    old_send = ot._resolve_dir(existing.get("send_dir", "results/email_sends"))
    new_dl = ot._resolve_dir(req.download_dir.strip())
    new_send = ot._resolve_dir(req.send_dir.strip())
    dir_changed = (old_dl != new_dl) or (old_send != new_send)
    if dir_changed and ot._mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能修改目录")

    migrations: List[Dict[str, Any]] = []
    if req.migrate:
        try:
            if old_dl != new_dl:
                migrations.append(await asyncio.to_thread(migrate_directory, old_dl, new_dl))
            if old_send != new_send:
                migrations.append(await asyncio.to_thread(migrate_directory, old_send, new_send))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"目录迁移失败: {e}") from e

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
    ot.MAIL_CONFIG_PATH.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "success", "config": updated, "migrations": migrations}


@mail_router.post("/mail_pipeline/auth")
async def update_mail_auth(req: MailAuthUpdateRequest):
    """更新邮箱授权码：写入独立密钥文件（不入库），返回掩码"""
    ot = _ot()
    raw_cfg = ot._read_mail_cfg()
    if req.imap_auth_code is not None:
        write_secret(resolve_secret_path(ot.PROJECT_ROOT, raw_cfg.get("auth_code_file", ".mail_auth")), req.imap_auth_code)
    if req.smtp_auth_code is not None:
        write_secret(
            resolve_secret_path(ot.PROJECT_ROOT, raw_cfg.get("smtp_auth_code_file", ".mail_smtp_auth")),
            req.smtp_auth_code,
        )
    return {"status": "success", "auth": _mail_auth_info(raw_cfg)}


@mail_router.post("/mail_pipeline/cleanup")
async def cleanup_mail_pipeline_history(req: MailCleanupRequest):
    """清理邮件流水线历史数据（批次 / 回传包 / 报告 / 注释中间目录 / 去重索引 / 日志）"""
    ot = _ot()
    if ot._mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能清理")
    if not req.targets:
        raise HTTPException(status_code=400, detail="未选择清理项")
    raw_cfg = ot._read_mail_cfg()
    res = await asyncio.to_thread(
        cleanup_mail_history,
        ot._resolve_dir(raw_cfg.get("download_dir", "results/email_downloads")),
        ot._resolve_dir(raw_cfg.get("send_dir", "results/email_sends")),
        ot.ANNOTATIONS_DIR,
        req.targets,
        req.older_than_days,
        req.names,
    )
    return {"status": "success", **res}


@mail_router.post("/mail_pipeline/batch_ignore")
async def toggle_mail_pipeline_batch_ignore(req: MailBatchIgnoreRequest):
    """将指定已收件批次标记为“已忽略跳过”或恢复待处理状态"""
    ot = _ot()
    if ot._mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="流水线运行中，暂不能修改批次跳过状态")
    clean_batch = (req.batch_name or "").strip()
    if not clean_batch or any(sep in clean_batch for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的批次名: {req.batch_name}")

    raw_cfg = ot._read_mail_cfg()
    dl_dir = ot._resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))
    send_dir = ot._resolve_dir(raw_cfg.get("send_dir", "results/email_sends"))
    batch_path = dl_dir / clean_batch
    if not batch_path.exists() or not batch_path.is_dir() or batch_path.parent.resolve() != dl_dir.resolve():
        raise HTTPException(status_code=404, detail=f"未找到批次目录: {clean_batch}")

    cfg_obj = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    await asyncio.to_thread(mark_batch_ignored, batch_path, ignored=req.ignore, reason=req.reason)
    state = inspect_batch_pipeline_state(batch_path, cfg_obj, send_dir, ot.ANNOTATIONS_DIR)
    return {
        "status": "success",
        "batch_name": clean_batch,
        "ignored": state.get("ignored", False),
        "state": state,
    }


@mail_router.post("/mail_pipeline/list_mails")
async def list_mail_inbox(req: MailListRequest):
    """分页浏览并去重展示发件人白名单内的收件箱邮件"""
    ot = _ot()

    def _do_list():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=True)
        return ot.list_whitelist_mails(
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"拉取收件箱失败: {e}") from e


@mail_router.post("/mail_pipeline/fetch")
async def trigger_mail_fetch(req: MailFetchRequest):
    """立即扫描 IMAP 收件箱并保存新附件"""
    ot = _ot()

    def _do_fetch():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=True)
        fetcher = ot.MailFetcher(cfg)
        f_res = fetcher.fetch(since_days=req.since_days)
        if f_res.connection_error:
            _append_mail_pipeline_log(cfg.resolved_download_dir, "error", f"仅收件失败: {f_res.connection_error}")
            return {"ok": False, "error": f_res.connection_error}
        saved_stats = {"count": 0, "skipped_duplicates": 0, "skipped_processed": 0, "saved_files": []}
        if f_res.matched:
            saver = ot.AttachmentSaver(cfg.resolved_download_dir)
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@mail_router.post("/mail_pipeline/run")
async def trigger_mail_auto_pipeline(req: MailPipelineRunRequest):
    """后台异步启动完整自动流水线 (收件 + 待处理接续 -> 注释 -> Word 报告 -> 打包 -> SMTP 回传)"""
    ot = _ot()
    if ot._mail_pipeline_state["running"]:
        raise HTTPException(status_code=409, detail="邮件自动注释流水线正在运行中，请等待当前任务结束")

    raw_cfg = ot._read_mail_cfg()
    cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
    dl_dir = ot._resolve_dir(raw_cfg.get("download_dir", "results/email_downloads"))

    resolved_to: Optional[str] = None
    if req.to is not None and req.to.strip():
        resolved_to = resolve_safe_send_target(cfg, req.to)
        if not resolved_to:
            raise HTTPException(status_code=400, detail="未配置发件或收件邮箱账号，无法解析目标收件人")

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

    ot._mail_pipeline_state["running"] = True
    ot._mail_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ot._mail_pipeline_state["finished_at"] = None
    ot._mail_pipeline_state["last_exit_code"] = None
    ot._mail_pipeline_state["last_command"] = " ".join(cmd)
    ot._mail_pipeline_state["last_output"] = "流水线已启动，正在连接收件/扫描待处理批次..."
    ot._mail_pipeline_state["current_stage"] = "fetching"

    ot.logger.info(
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
                    ot._mail_pipeline_state["last_output"] = "\n".join(lines_buf)[-4000:]
                    ot._mail_pipeline_state["current_stage"] = _infer_mail_stage(
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

    asyncio.get_running_loop().run_in_executor(None, _run_bg)
    return {"status": "started", "runtime": ot._mail_pipeline_state}


@mail_router.post("/mail_pipeline/test_send_preview")
async def preview_mail_pipeline_test_send(req: Optional[MailTestSendPreviewRequest] = Body(default=None)):
    """生成 SMTP 自检测试邮件的默认草稿，供前端弹窗预填与自由编辑。"""
    ot = _ot()
    params = req or MailTestSendPreviewRequest()

    def _do_preview():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
        send_dir = ot._resolve_dir(getattr(cfg, "send_dir", "results/email_sends"))
        draft = build_test_send_draft(
            cfg,
            send_dir,
            ot.ANNOTATIONS_DIR,
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


@mail_router.post("/mail_pipeline/test_send")
async def test_mail_pipeline_send(req: Optional[MailTestSendRequest] = Body(default=None)):
    """轻量测试 SMTP 发信链路：打包验证文本（可选附带最新 Word 报告）发送到自身或指定邮箱。"""
    ot = _ot()
    params = req or MailTestSendRequest()

    def _do_test_send():
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

            sender = ot.MailSender(cfg)
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试发信异常: {e}") from e

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


@mail_router.post("/mail_pipeline/send_package_preview")
async def preview_mail_pipeline_package(req: MailPackagePreviewRequest):
    """生成已打包注释结果压缩包的默认邮件草稿，供前端弹窗预填与自由编辑。"""
    ot = _ot()

    def _do_preview():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
        _, zip_path, send_dir = _resolve_outbound_zip_path(req.zip_name, cfg)
        draft = build_package_send_draft(zip_path, send_dir, cfg, extra_note=req.extra_note)
        return draft

    data = await asyncio.to_thread(_do_preview)
    return {"status": "success", **data}


@mail_router.post("/mail_pipeline/send_package")
async def send_mail_pipeline_package(req: MailPackageSendRequest):
    """将已打包的注释结果压缩包通过 SMTP 发送至本人或指定邮箱。"""
    ot = _ot()

    def _do_send_package():
        cfg = ot.load_config(str(ot.MAIL_CONFIG_PATH), require_imap_auth=False)
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

    try:
        res, clean_zip, draft, final = await asyncio.to_thread(_do_send_package)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送结果压缩包异常: {e}") from e

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
