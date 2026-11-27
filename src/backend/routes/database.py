# -*- coding: utf-8 -*-
"""
生物数据库管理 REST API 路由 (/api/database/*)
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter

from ..broadcaster import broadcaster
from ..utils.bio_db.downloader import DownloadCancelledError
from ..utils.bio_db_manager import bio_db_manager
from ..utils.response import BioResponse

logger = logging.getLogger("api_server")

router = APIRouter(prefix="/database", tags=["database"])


@router.get("/status")
async def get_all_db_status():
    """获取所有已注册的生物数据库状态（含进行中/最近一次更新快照）"""
    return BioResponse.ok(bio_db_manager.list_all_status())


@router.post("/update/{db_id}")
async def trigger_db_update(db_id: str):
    """触发特定数据库的自动化更新（并发防重入 + 托管后台任务）"""
    if db_id not in bio_db_manager.dbs:
        return BioResponse.fail(f"Database {db_id} not registered", status_code=404)

    db = bio_db_manager.dbs[db_id]
    started, state, cancel_event = bio_db_manager.begin_update(
        db_id,
        f"正在连接 {db.name} 核心下载源...",
    )
    if not started or cancel_event is None:
        return BioResponse.ok({
            "message": f"{db.name} 正在更新中",
            "already_running": True,
            "state": state,
        })

    bio_db_manager.spawn_update_task(db_id, _run_update_task(db_id, cancel_event))

    return BioResponse.ok({
        "message": f"Update task for {db_id} started in background",
        "state": state,
    })


@router.post("/cancel/{db_id}")
async def cancel_db_update(db_id: str):
    """取消正在进行的数据库更新任务（保留已下载分片以便断点续传）"""
    if db_id not in bio_db_manager.dbs:
        return BioResponse.fail(f"Database {db_id} not registered", status_code=404)

    ok, msg = bio_db_manager.cancel_update(db_id)
    if not ok:
        return BioResponse.fail(msg, status_code=400)

    state = bio_db_manager.get_update_state(db_id) or {
        "db_id": db_id,
        "status": "updating",
        "progress": 0,
        "message": "正在取消更新任务...",
    }
    await broadcaster.broadcast("db_update_event", state)
    return BioResponse.ok({"message": msg, "state": state})


async def _run_update_task(db_id: str, cancel_event: threading.Event) -> None:
    """
    后台更新流水线：实时推流进度并确保任何成功/失败/取消场景均广播终态。
    """
    db = bio_db_manager.dbs[db_id]
    last_emit = [0.0, -1]  # [timestamp, progress]

    def _on_progress(progress: int, message: str) -> None:
        state = bio_db_manager.report_progress(db_id, progress, message)
        now = time.monotonic()
        if (now - last_emit[0]) >= 0.35 or progress != last_emit[1]:
            last_emit[0] = now
            last_emit[1] = progress
            broadcaster.broadcast_sync("db_update_event", state)

    initial_state = bio_db_manager.report_progress(
        db_id,
        5,
        f"正在从官网请求 {db.name} 核心文件...",
    )
    await broadcaster.broadcast("db_update_event", initial_state)

    try:
        success = await db.update_database(
            progress_cb=_on_progress,
            cancel_event=cancel_event,
        )
        if success:
            final_state = bio_db_manager.finish_update(
                db_id,
                "success",
                100,
                f"{db.name} 更新成功",
            )
        else:
            reason = getattr(db, "last_error", None)
            err_msg = f"{db.name} 更新失败" + (f": {reason}" if reason else "，请查看后端日志")
            final_state = bio_db_manager.finish_update(db_id, "error", 0, err_msg)
    except DownloadCancelledError as exc:
        logger.info("数据库更新已取消 [%s]: %s", db_id, exc)
        final_state = bio_db_manager.finish_update(
            db_id,
            "cancelled",
            0,
            f"{db.name} 更新已取消（已下载分片将保留用于续传）",
        )
    except Exception as exc:
        logger.exception("数据库更新任务未捕获异常 [%s]: %s", db_id, exc)
        final_state = bio_db_manager.finish_update(
            db_id,
            "error",
            0,
            f"{db.name} 更新异常: {exc}",
        )

    await broadcaster.broadcast("db_update_event", final_state)
