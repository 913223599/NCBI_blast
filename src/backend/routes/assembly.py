# -*- coding: utf-8 -*-
"""
Assembly API Routes - 基因组拼接后端接口模块 (薄路由层)
提供任务提交、队列调度、实时进度遥测、指标查询与产物导出接口。
"""

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from ...assembly.manager import AssemblyManager
from ..broadcaster import broadcaster
from ..services.assembly_metrics_service import (
    _extract_contig_depth,
    _read_fastp_total_bases,
    build_assembly_result_payload,
    extract_single_contig_fasta,
    find_assembly_fasta,
    heal_assembly_history_items,
    parse_assembly_fasta_metrics,
)
from ..utils.assembly_db import assembly_db
from ..utils.assembly_storage import AssemblyStorage
from ..utils.persistent_queue import persistent_queue as assembly_queue
from ..utils.response import BioResponse

logger = logging.getLogger("Assembly.Routes")
_DEPTH_BACKFILL_LOCKS: Dict[str, asyncio.Lock] = {}

_project_root = Path(__file__).resolve().parent.parent.parent.parent
manager = AssemblyManager(_project_root)

router = APIRouter(prefix="/assembly", tags=["assembly"])

__all__ = [
    "router",
    "manager",
    "execute_assembly_pipeline",
    "find_assembly_fasta",
    "parse_assembly_fasta_metrics",
    "_extract_contig_depth",
    "_read_fastp_total_bases",
]


async def execute_assembly_pipeline(payload: Dict[str, Any]):
    """持久化串行队列的消费者处理器函数"""
    task_id = payload.get("task_id")
    sample_type = payload.get("sample_type", "BACTERIA")
    config = payload.get("config", {})

    r1_input = payload.get("r1") or config.get("r1") or config.get("params", {}).get("r1")
    r2_input = payload.get("r2") or config.get("r2") or config.get("params", {}).get("r2")
    long_reads_input = payload.get("long_reads") or config.get("long_reads") or config.get("params", {}).get("long_reads")

    files = payload.get("files") or config.get("files") or []
    if not r1_input and files:
        r1_input = files[0]
        if len(files) > 1:
            r2_input = files[1]
        if len(files) > 2 and not long_reads_input:
            long_reads_input = files[2]

    if long_reads_input:
        config["long_reads"] = str(long_reads_input)

    logger.info(f"队列调度执行任务: {task_id} | R1={r1_input} | R2={r2_input} | LR={long_reads_input}")
    await manager.run_pipeline(
        task_id=task_id,
        sample_type=sample_type,
        r1_input=r1_input,
        r2_input=r2_input,
        long_reads_input=long_reads_input,
        config=config,
    )


@router.post("/run")
async def run_assembly_job(payload: Dict[str, Any]):
    """提交基因组组装任务至持久化队列"""
    task_id = payload.get("task_id")
    if not task_id:
        task_id = f"Assembly_{int(time.time() * 1000)}"
        payload["task_id"] = task_id

    AssemblyStorage.get_task_dir(task_id)

    sample_id = payload.get("sample_id", "Unknown")
    name = payload.get("name", "Assembly Task")
    sample_type = payload.get("sample_type", "BACTERIA")
    tech = payload.get("tech", "ILLUMINA")
    config = payload.get("config", {})
    assembly_db.create_task(task_id, name, sample_id, sample_type, tech, config)

    was_busy = assembly_queue.current_task_id is not None or assembly_queue.get_queue_size() > 0
    await assembly_queue.add_task(payload)

    is_running_now = assembly_queue.current_task_id == task_id
    waiting_pos = assembly_queue.get_queue_position(task_id)
    is_busy_now = (not is_running_now) and bool(
        was_busy
        or (assembly_queue.current_task_id is not None and assembly_queue.current_task_id != task_id)
        or waiting_pos > 1
    )
    return BioResponse.ok({
        "message": "Task queued successfully" if is_busy_now else "Task started successfully",
        "task_id": task_id,
        "status": "queued" if is_busy_now else "running",
        "is_busy": is_busy_now,
        "queue_position": max(1, waiting_pos) if is_busy_now else 0,
    })


@router.get("/history")
async def get_assembly_history():
    """获取拼接任务历史列表 (带自动健康检查与历史数据自愈)"""
    history = assembly_db.get_history(limit=100)
    healed = heal_assembly_history_items(history, assembly_db_obj=assembly_db, storage_cls=AssemblyStorage)
    return BioResponse.ok(healed)


@router.get("/status/{task_id}")
async def get_assembly_status(task_id: str):
    """查询指定任务的当前状态与进度"""
    task = assembly_db.get_task(task_id)
    if not task:
        return BioResponse.fail("Task not found")

    queue_pos = assembly_queue.get_queue_position(task_id)
    if task.get("results") and isinstance(task["results"], str):
        try:
            task["results"] = json.loads(task["results"])
        except Exception as exc:
            logger.debug("解析任务 results JSON 失败 (%s): %s", task_id, exc)
    if task.get("config") and isinstance(task["config"], str):
        try:
            task["config"] = json.loads(task["config"])
        except Exception as exc:
            logger.debug("解析任务 config JSON 失败 (%s): %s", task_id, exc)

    task["queue_position"] = queue_pos
    return BioResponse.ok(task)


@router.get("/result/{task_id}")
async def get_assembly_result(task_id: str):
    """获取组装结果指标与产物路径 (Manifest 与 FASTA 深度融合版)"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if not task_dir.exists():
        return BioResponse.fail("Task directory not found")

    task = assembly_db.get_task(task_id) or {}
    payload = await build_assembly_result_payload(
        task_id,
        task,
        task_dir,
        assembly_db_obj=assembly_db,
        depth_locks=_DEPTH_BACKFILL_LOCKS,
    )
    return BioResponse.ok(payload)


@router.get("/download/{task_id}")
async def download_assembly_fasta(task_id: str):
    """一键下载组装产物 FASTA"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    asm_fasta = find_assembly_fasta(task_id, task_dir)
    if not asm_fasta or not asm_fasta.exists():
        raise HTTPException(status_code=404, detail="Assembly FASTA file not found")

    task = assembly_db.get_task(task_id) or {}
    safe_name = (task.get("name") or task_id).replace(" ", "_")
    return FileResponse(
        path=str(asm_fasta),
        filename=f"{safe_name}_assembly.fasta",
        media_type="application/octet-stream",
    )


@router.get("/download/{task_id}/contig/{contig_name}")
async def download_single_contig(task_id: str, contig_name: str):
    """单独下载指定 Contig 的 FASTA 文件 (流式切片提取)"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    asm_fasta = find_assembly_fasta(task_id, task_dir)
    if not asm_fasta or not asm_fasta.exists():
        raise HTTPException(status_code=404, detail="Assembly FASTA file not found")

    extracted = extract_single_contig_fasta(asm_fasta, contig_name)
    if extracted is None:
        clean_target = contig_name.strip().lstrip(">")
        raise HTTPException(status_code=404, detail=f"Contig '{clean_target}' not found")

    clean_target, fasta_content = extracted
    task = assembly_db.get_task(task_id) or {}
    safe_task_name = (task.get("name") or task_id).replace(" ", "_")
    safe_contig_name = clean_target.replace("/", "_").replace("\\", "_")
    download_filename = f"{safe_task_name}_{safe_contig_name}.fasta"
    return Response(
        content=fasta_content.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
    )


@router.post("/open-folder/{task_id}")
async def open_task_folder(task_id: str):
    """在系统资源管理器中高亮定位组装产物所在目录"""
    clean_id = (task_id or "").strip()
    if not clean_id or any(sep in clean_id for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail=f"非法的任务 ID: {task_id}")

    task_dir = AssemblyStorage.get_task_dir(clean_id).resolve()
    run_dir = task_dir / "assembly_run"
    target_dir = run_dir if run_dir.exists() else task_dir
    if not target_dir.exists():
        alt_dirs = list(task_dir.glob("**/assembly.fasta"))
        if alt_dirs:
            target_dir = alt_dirs[0].parent
    if not target_dir.exists():
        return BioResponse.fail("产物目录不存在")

    asm_fasta = target_dir / "assembly.fasta"
    try:
        if sys.platform == "win32":
            if asm_fasta.exists():
                subprocess.Popen(["explorer.exe", f"/select,{asm_fasta.resolve()}"])
            else:
                subprocess.Popen(["explorer.exe", str(target_dir.resolve())])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target_dir.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(target_dir.resolve())])
        return BioResponse.ok({"message": "已打开产物目录", "path": str(target_dir)})
    except Exception as e:
        return BioResponse.fail(f"打开目录失败: {e}")


@router.post("/stop/{task_id}")
async def stop_assembly_task(task_id: str):
    """取消/终止组装任务"""
    assembly_queue.remove_task_from_queue(task_id)
    stopped_id = manager.stop_task(task_id)
    await broadcaster.broadcast("assembly_progress", {
        "task_id": task_id,
        "step": "已由用户手动终止",
        "progress": 0,
        "status": "aborted",
    })
    return BioResponse.ok({"message": f"Task {task_id} stopped", "stopped_id": stopped_id})


@router.delete("/tasks/{task_id}")
async def delete_assembly_task(task_id: str):
    """删除拼接任务记录与物理文件"""
    assembly_queue.remove_task_from_queue(task_id)
    assembly_db.delete_task(task_id)
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    return BioResponse.ok(f"Task {task_id} and its files have been removed.")


@router.get("/queue")
async def get_assembly_queue_status():
    """获取当前队列状态（与 WS assembly_queue_status 共享权威快照）"""
    snap = assembly_queue.get_queue_snapshot()
    return BioResponse.ok({
        "running_task": snap["running_task"],
        "waiting_count": snap["waiting_count"],
        "waiting_tasks": snap["waiting_tasks"],
        "is_busy": snap["is_busy"],
        "paused": snap["paused"],
        "current_task_id": snap["current_task_id"],
    })
