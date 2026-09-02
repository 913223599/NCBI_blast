# -*- coding: utf-8 -*-
"""
Assembly API Routes - 基因组拼接后端接口模块 (纯净重构版)
提供任务提交、队列调度、实时进度遥测、指标查询与产物导出接口。
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..broadcaster import broadcaster
from ..utils.response import BioResponse
from ..utils.assembly_storage import AssemblyStorage
from ..utils.persistent_queue import persistent_queue as assembly_queue
from ..utils.assembly_db import assembly_db
from src.assembly.manager import AssemblyManager

logger = logging.getLogger("Assembly.Routes")

# 全局管理器单例
_project_root = Path(__file__).resolve().parent.parent.parent.parent
manager = AssemblyManager(_project_root)

router = APIRouter(prefix="/assembly", tags=["assembly"])


async def execute_assembly_pipeline(payload: Dict[str, Any]):
    """
    持久化串行队列的消费者处理器函数
    """
    task_id = payload.get('task_id')
    sample_type = payload.get('sample_type', 'BACTERIA')
    config = payload.get('config', {})
    
    r1_input = payload.get('r1') or config.get('r1') or config.get('params', {}).get('r1')
    r2_input = payload.get('r2') or config.get('r2') or config.get('params', {}).get('r2')
    
    files = payload.get('files') or config.get('files') or []
    if not r1_input and files:
        r1_input = files[0]
        if len(files) > 1:
            r2_input = files[1]
            
    logger.info(f"队列调度执行任务: {task_id} | R1={r1_input} | R2={r2_input}")
    await manager.run_pipeline(
        task_id=task_id,
        sample_type=sample_type,
        r1_input=r1_input,
        r2_input=r2_input,
        config=config
    )



@router.post("/run")
async def run_assembly_job(payload: Dict[str, Any]):
    """
    提交基因组组装任务至持久化队列
    """
    task_id = payload.get('task_id')
    if not task_id:
        task_id = f"Assembly_{int(time.time() * 1000)}"
        payload['task_id'] = task_id

    # 1. 创建物理结果目录
    AssemblyStorage.get_task_dir(task_id)
    
    # 2. 持久化记录到数据库
    sample_id = payload.get('sample_id', 'Unknown')
    name = payload.get('name', 'Assembly Task')
    sample_type = payload.get('sample_type', 'BACTERIA')
    tech = payload.get('tech', 'ILLUMINA')
    config = payload.get('config', {})
    
    assembly_db.create_task(task_id, name, sample_id, sample_type, tech, config)
    
    # 3. 加入持久化队列
    await assembly_queue.add_task(payload)
    
    queue_size = assembly_queue.get_queue_size()
    return BioResponse.ok({
        "message": "Task queued successfully",
        "task_id": task_id,
        "queue_position": queue_size
    })


@router.get("/history")
async def get_assembly_history():
    """获取拼接任务历史列表"""
    history = assembly_db.get_history(limit=100)
    return BioResponse.ok(history)


@router.get("/status/{task_id}")
async def get_assembly_status(task_id: str):
    """查询指定任务的当前状态与进度"""
    task = assembly_db.get_task(task_id)
    if not task:
        return BioResponse.fail("Task not found")

    # 检查是否在队列中排队
    waiting_tasks = assembly_db.get_queued_tasks()
    queue_pos = -1
    for idx, t in enumerate(waiting_tasks):
        if t['id'] == task_id:
            queue_pos = idx + 1
            break

    # 解析 JSON 字段
    if task.get('results') and isinstance(task['results'], str):
        try: task['results'] = json.loads(task['results'])
        except: pass
    if task.get('config') and isinstance(task['config'], str):
        try: task['config'] = json.loads(task['config'])
        except: pass

    task['queue_position'] = queue_pos
    return BioResponse.ok(task)


@router.get("/result/{task_id}")
async def get_assembly_result(task_id: str):
    """获取组装结果指标与产物路径"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if not task_dir.exists():
        return BioResponse.fail("Task directory not found")

    task = assembly_db.get_task(task_id) or {}
    
    # 定位 assembly.fasta 文件
    asm_fasta = task_dir / "assembly_run" / "assembly.fasta"
    if not asm_fasta.exists():
        # 兼容备用位置
        asm_fasta = task_dir / "assembly.fasta"

    stats = {}
    if task.get('results'):
        if isinstance(task['results'], str):
            try: stats = json.loads(task['results'])
            except: pass
        elif isinstance(task['results'], dict):
            stats = task['results']

    fasta_exists = asm_fasta.exists() and asm_fasta.stat().st_size > 0
    fasta_size_bytes = asm_fasta.stat().st_size if fasta_exists else 0

    return BioResponse.ok({
        "task_id": task_id,
        "name": task.get("name"),
        "status": task.get("status"),
        "stats": stats,
        "fasta_exists": fasta_exists,
        "fasta_path": str(asm_fasta.resolve()) if fasta_exists else None,
        "fasta_size_bytes": fasta_size_bytes,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "duration_seconds": task.get("duration_seconds", 0)
    })


@router.get("/download/{task_id}")
async def download_assembly_fasta(task_id: str):
    """一键下载组装产物 FASTA"""
    task_dir = AssemblyStorage.get_task_dir(task_id)
    asm_fasta = task_dir / "assembly_run" / "assembly.fasta"
    if not asm_fasta.exists():
        asm_fasta = task_dir / "assembly.fasta"

    if not asm_fasta.exists():
        raise HTTPException(status_code=404, detail="Assembly FASTA file not found")

    task = assembly_db.get_task(task_id) or {}
    safe_name = (task.get("name") or task_id).replace(" ", "_")
    download_filename = f"{safe_name}_assembly.fasta"

    return FileResponse(
        path=str(asm_fasta),
        filename=download_filename,
        media_type="application/octet-stream"
    )


@router.post("/stop/{task_id}")
async def stop_assembly_task(task_id: str):
    """取消/终止组装任务"""
    # 1. 尝试从等待队列中剔除
    assembly_queue.remove_task_from_queue(task_id)
    # 2. 终止运行中的进程
    stopped_id = manager.stop_task(task_id)
    # 3. 广播状态
    await broadcaster.broadcast("assembly_progress", {
        "task_id": task_id,
        "step": "已由用户手动终止",
        "progress": 0,
        "status": "aborted"
    })
    return BioResponse.ok({"message": f"Task {task_id} stopped", "stopped_id": stopped_id})


@router.delete("/tasks/{task_id}")
async def delete_assembly_task(task_id: str):
    """删除拼接任务记录与物理文件"""
    assembly_queue.remove_task_from_queue(task_id)
    assembly_db.delete_task(task_id)
    
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir, ignore_errors=True)

    return BioResponse.ok(f"Task {task_id} and its files have been removed.")


@router.get("/queue")
async def get_assembly_queue_status():
    """获取当前队列状态"""
    waiting = assembly_db.get_queued_tasks()
    running = [t for t in assembly_db.get_incomplete_tasks() if t.get('status') == 'running']
    
    return BioResponse.ok({
        "running_task": running[0] if running else None,
        "waiting_count": len(waiting),
        "waiting_tasks": waiting,
        "is_busy": len(running) > 0
    })
