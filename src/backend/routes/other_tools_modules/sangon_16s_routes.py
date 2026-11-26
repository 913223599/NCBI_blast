# -*- coding: utf-8 -*-
"""
生工 16S 测序结果自动化 BLAST 与导出流程 路由子模块 (薄路由层)
说明：通过父路由模块 `other_tools` 动态访问共享配置、运行态及可替换依赖，
确保现有 API 契约与测试 monkeypatch 完全兼容。
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException

from ...services.other_tools.dir_migrator import migrate_directory
from ...services.other_tools.history_cleaner import cleanup_sangon_history
from ...services.other_tools.mail_composer import build_sangon_result_draft
from ...services.other_tools.sangon_downloader import (
    _collect_pending_download_targets,
    build_sangon_order_url,
)
from ...services.other_tools.sangon_ignore_rules import (
    ignore_orders,
    replace_ignore_rules,
    unignore_orders,
)
from ...services.other_tools.sangon_mail_scanner import init_sangon_order_dir
from ...services.other_tools.sangon_pipeline_runner import (
    collect_sangon_overview,
    execute_sangon_dirs_pipeline,
    execute_sangon_send_result_sync,
    read_sangon_csv_rows,
    resolve_sangon_run_targets,
    run_sangon_batch_bg,
    run_sangon_download_bg,
)
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
    return execute_sangon_dirs_pipeline(
        _ot(),
        root_path,
        target_dirs,
        downloads_dir=downloads_dir,
        evalue=evalue,
        hitlist_size=hitlist_size,
        force_reblast=force_reblast,
        progress_start=progress_start,
        progress_end=progress_end,
    )


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


def _begin_sangon_runtime(ot: Any, *, stage: str, total: int, start_msg: str) -> None:
    with ot._sangon_pipeline_lock:
        if ot._sangon_pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="生工 16S 自动化流水线正在运行中，请稍候")
        ot._sangon_pipeline_state["running"] = True
        ot._sangon_pipeline_state["current_order"] = None
        ot._sangon_pipeline_state["current_stage"] = stage
        ot._sangon_pipeline_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ot._sangon_pipeline_state["finished_at"] = None
        ot._sangon_pipeline_state["progress"] = 0
        ot._sangon_pipeline_state["last_message"] = start_msg
        ot._sangon_pipeline_state["summary"] = {
            "total": total,
            "processed": 0,
            "skipped_missing": 0,
            "failed": 0,
        }
        ot._sangon_pipeline_state["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] {start_msg}"]
    ot.logger.info("[Sangon16S] %s", start_msg)


@sangon_router.get("/sangon_16s/overview")
async def get_sangon_16s_overview(sangon_root: Optional[str] = None, downloads_dir: Optional[str] = None):
    """获取生工 16S 自动化流程目录、浏览器下载目录待认领压缩包与所有订单状态概览"""
    return collect_sangon_overview(_ot(), sangon_root, downloads_dir)


@sangon_router.get("/sangon_16s/order/{order_dir_name}/results")
async def get_sangon_order_results(order_dir_name: str, sangon_root: Optional[str] = None):
    """读取指定生工 16S 订单的 11 列鉴定结果 CSV 供前端在线表格展示"""
    clean_name, csv_path = _resolve_sangon_order_csv_path(order_dir_name, sangon_root)
    try:
        headers, rows = read_sangon_csv_rows(csv_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 CSV 失败: {e}") from e
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
        return {"status": "success", **(await asyncio.to_thread(_do_scan))}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"扫描生工邮件失败: {e}") from e


@sangon_router.post("/sangon_16s/init_order")
async def init_sangon_order_directory(req: SangonInitOrderRequest):
    """手动为指定通知邮件初始化生工订单三级目录"""
    root_path = _ot()._sangon_root_or_default(req.sangon_root)
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初始化订单目录失败: {e}") from e


@sangon_router.post("/sangon_16s/run_pipeline")
async def run_sangon_16s_pipeline(req: SangonRunRequest):
    """对选定的生工 16S 订单执行自动解压 -> 16S BLAST 比对 -> 中文翻译与 11 列 CSV 导出"""
    ot = _ot()
    root_path = ot._sangon_root_or_default(req.sangon_root)
    if not root_path.exists():
        raise HTTPException(status_code=400, detail=f"生工 16S 目录不存在: {root_path}")

    target_dirs, skipped_ignored = resolve_sangon_run_targets(ot, root_path, req.order_names, req.force_reblast)
    if not target_dirs:
        if skipped_ignored > 0:
            raise HTTPException(status_code=400, detail=f"没有需要处理的订单目录（已自动跳过 {skipped_ignored} 个已忽略订单）")
        raise HTTPException(status_code=400, detail="没有需要处理的订单目录")

    _begin_sangon_runtime(
        ot,
        stage="running",
        total=len(target_dirs),
        start_msg=f"启动生工 16S 批处理，共 {len(target_dirs)} 个订单",
    )
    asyncio.get_running_loop().run_in_executor(
        None, run_sangon_batch_bg, ot, root_path, target_dirs, req, _execute_sangon_dirs_pipeline
    )
    return {"status": "started", "runtime": ot._snapshot_sangon_runtime()}


@sangon_router.post("/sangon_16s/auth")
async def update_sangon_auth_credentials(req: SangonAuthUpdateRequest):
    """保存或更新生工官网登录账号与独立密钥文件 (.sangon_auth)，仅返脱敏掩码"""
    if req.account is None and req.password is None and req.auto_confirm_fee is None:
        raise HTTPException(status_code=400, detail="未提供需要更新的生工账号配置")
    auth_info = save_sangon_credentials(
        account=req.account, password=req.password, auto_confirm_fee=req.auto_confirm_fee
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

    collected = _collect_pending_download_targets(root_path, order_names=params.order_names or None)
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
    mode_label = "自动下载并比对" if params.auto_run_blast else "自动下载压缩包"
    _begin_sangon_runtime(
        ot,
        stage="downloading",
        total=len(targets),
        start_msg=f"启动生工 16S {mode_label}，待检查 {len(targets)} 个订单",
    )
    asyncio.get_running_loop().run_in_executor(
        None,
        lambda: run_sangon_download_bg(
            ot,
            root_path,
            dl_dir,
            targets,
            params,
            _execute_sangon_dirs_pipeline,
            account=account,
            password=password,
            confirm_fee=confirm_fee,
            needs_web_login=needs_web_login,
        ),
    )
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

    return {"status": "success", **(await asyncio.to_thread(_do_preview))}


@sangon_router.post("/sangon_16s/send_result")
async def send_sangon_order_result_mail(req: SangonSendResultRequest):
    """将指定订单的 16S 鉴定结果 CSV 打包为 zip 并通过 SMTP 发送。"""
    clean_name, csv_path = _resolve_sangon_order_csv_path(req.order_dir_name, req.sangon_root)
    try:
        res, draft, final = await asyncio.to_thread(
            execute_sangon_send_result_sync, _ot(), clean_name, csv_path, req
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发送 16S 结果邮件异常: {e}") from e

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
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"目录迁移失败: {e}") from e
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
            ignored_orders=req.ignored_orders, ignore_subject_keywords=req.ignore_subject_keywords
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
    res = (
        ignore_orders(req.order_keys, reason=req.reason, dir_names=req.dir_names)
        if req.ignore
        else unignore_orders(req.order_keys)
    )
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
