# -*- coding: utf-8 -*-
"""
邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传 路由子模块 (薄路由层)
说明：通过父路由模块 `other_tools` 动态访问共享配置、运行态及可替换依赖，
确保现有 API 契约与测试 monkeypatch 完全兼容。
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from ....mail_download.batch_state import inspect_batch_pipeline_state, mark_batch_ignored
from ...services.other_tools.dir_migrator import migrate_directory
from ...services.other_tools.history_cleaner import cleanup_mail_history
from ...services.other_tools.mail_composer import (
    build_package_send_draft,
    build_test_send_draft,
    resolve_safe_send_target,
)
from ...services.other_tools.mail_pipeline_runner import (
    build_mail_pipeline_command,
    collect_mail_pipeline_overview,
    execute_mail_fetch_sync,
    execute_package_send_sync,
    execute_test_send_sync,
    run_mail_pipeline_subprocess,
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
    return {
        "imap_ready": bool(cfg.auth_code),
        "imap_masked": mask_secret(cfg.auth_code),
        "imap_file": str(imap_file),
        "smtp_ready": bool(cfg.smtp_auth_code),
        "smtp_masked": mask_secret(cfg.smtp_auth_code),
        "smtp_file": str(smtp_file),
        "smtp_separate": bool(read_secret(smtp_file)),
    }


def _append_mail_pipeline_log(dl_dir: Path, level: str, msg: str) -> None:
    """向 pipeline.log 追加审计日志行。"""
    ot = _ot()
    try:
        dl_dir.mkdir(parents=True, exist_ok=True)
        with (dl_dir / "pipeline.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} [{level.upper()}] {msg}\n")
    except OSError as exc:
        ot.logger.warning(f"写入 pipeline.log 失败: {exc}")


def _infer_mail_stage(line: str, current: str) -> str:
    """从流水线实时日志行推断当前阶段标识。"""
    for tag, stage in (
        ("[收件]", "fetching"),
        ("[队列]", "queued"),
        ("[批次]", "queued"),
        ("[注释]", "annotating"),
        ("[报告]", "reporting"),
        ("[打包]", "packing"),
        ("[回传]", "sending"),
    ):
        if tag in line:
            return stage
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
    return collect_mail_pipeline_overview(_ot(), _mail_auth_info)


@mail_router.post("/mail_pipeline/config")
async def update_mail_pipeline_config(req: MailConfigUpdateRequest):
    """更新保存 mail_config.json；下载/回传目录变更时自动迁移已有数据"""
    ot = _ot()
    existing = ot._read_mail_cfg()
    old_dl = ot._resolve_dir(existing.get("download_dir", "results/email_downloads"))
    old_send = ot._resolve_dir(existing.get("send_dir", "results/email_sends"))
    new_dl = ot._resolve_dir(req.download_dir.strip())
    new_send = ot._resolve_dir(req.send_dir.strip())
    if ((old_dl != new_dl) or (old_send != new_send)) and ot._mail_pipeline_state["running"]:
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
    try:
        res = await asyncio.to_thread(execute_mail_fetch_sync, _ot(), req.since_days, _append_mail_pipeline_log)
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

    cmd = build_mail_pipeline_command(ot, req, dl_dir, resolved_to)
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
    asyncio.get_running_loop().run_in_executor(None, run_mail_pipeline_subprocess, ot, cmd, _infer_mail_stage)
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
            cfg, send_dir, ot.ANNOTATIONS_DIR, note=params.note, attach_latest_report=params.attach_latest_report
        )
        return {k: draft[k] for k in ("to", "reply_to", "from_name", "cc", "subject", "body", "attachment_name", "attached_files")}

    return {"status": "success", **(await asyncio.to_thread(_do_preview))}


@mail_router.post("/mail_pipeline/test_send")
async def test_mail_pipeline_send(req: Optional[MailTestSendRequest] = Body(default=None)):
    """轻量测试 SMTP 发信链路：打包验证文本（可选附带最新 Word 报告）发送到自身或指定邮箱。"""
    params = req or MailTestSendRequest()
    try:
        res, final, attached_files = await asyncio.to_thread(execute_test_send_sync, _ot(), params)
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
        return build_package_send_draft(zip_path, send_dir, cfg, extra_note=req.extra_note)

    return {"status": "success", **(await asyncio.to_thread(_do_preview))}


@mail_router.post("/mail_pipeline/send_package")
async def send_mail_pipeline_package(req: MailPackageSendRequest):
    """将已打包的注释结果压缩包通过 SMTP 发送至本人或指定邮箱。"""
    try:
        res, clean_zip, draft, final = await asyncio.to_thread(
            execute_package_send_sync, _ot(), req, _resolve_outbound_zip_path
        )
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
