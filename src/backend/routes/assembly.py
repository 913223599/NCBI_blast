import json
import os
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks
from typing import Dict, Any

logger = logging.getLogger("assembly_route")
from ..broadcaster import broadcaster
from ..utils.response import BioResponse
from ..utils.assembly_storage import AssemblyStorage
from ..utils.assembly_queue import assembly_queue

from src.assembly.manager import AssemblyManager
from ..utils.assembly_db import assembly_db

# 🔗 关键：全局单例管理器，用于追踪各个 Worker 中的活进程
_project_root = Path(__file__).parent.parent.parent.parent
manager = AssemblyManager(_project_root)

router = APIRouter(prefix="/assembly", tags=["assembly"])

@router.post("/run")
async def run_assembly_job(payload: Dict[str, Any]):
    """
    将任务提交至队列排队执行
    """
    task_id = payload.get('task_id')
    if not task_id:
        return BioResponse.fail("task_id is required")

    # 1. 准备物理存储
    AssemblyStorage.get_task_dir(task_id)
    
    # 2. 加入队列处理
    await assembly_queue.add_task(payload)
    
    return BioResponse.ok({
        "message": "Task queued successfully",
        "task_id": task_id,
        "queue_position": assembly_queue.get_queue_size()
    })

@router.post("/setup_conda")
async def setup_conda():
    """手动触发 Miniconda 自动部署"""
    from ...assembly.env.conda_installer import CondaInstaller
    project_root = Path(os.getcwd())
    installer = CondaInstaller(project_root)
    
    if installer.download_installer() and installer.run_silent_install():
        return BioResponse.ok("Miniconda deployed successfully")
    return BioResponse.fail("Conda deployment failed")

@router.get("/history")
async def get_assembly_history():
    """获取拼接任务历史列表"""
    from ..utils.assembly_db import assembly_db
    history = assembly_db.get_history()
    return BioResponse.ok(history)

@router.get("/report/{task_id}")
async def get_assembly_report(task_id: str):
    """获取拼接任务的完整分析报告"""
    from ..utils.assembly_report import AssemblyReportParser
    
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if not task_dir.exists():
        return BioResponse.fail("Task directory not found")
    
    parser = AssemblyReportParser(task_dir)
    report = parser.generate_report()
    return BioResponse.ok(report)

@router.get("/report/{task_id}/plot")
async def get_assembly_plot(task_id: str):
    """专用接口：返回总装报告的集成圈图文件流 (采用动态搜索机制)"""
    from fastapi.responses import FileResponse
    task_dir = AssemblyStorage.get_task_dir(task_id)
    plot_dir = task_dir / "phageannotationstep" / "phage_plot"
    
    if plot_dir.exists():
        # 搜索所有 png 文件，按大小降序排列（通常最大的图是高清图）
        png_files = sorted(list(plot_dir.glob("*.png")), key=lambda x: x.stat().st_size, reverse=True)
        if png_files:
            return FileResponse(png_files[0], media_type="image/png")
            
    return BioResponse.fail("Plot not found", code=444)

@router.get("/report/{task_id}/export")
async def export_assembly_report(task_id: str):
    """导出拼接任务的正式 HTML 报告"""
    from ..utils.assembly_report import AssemblyReportParser
    from ..utils.assembly_report_export import ReportExporter
    
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if not task_dir.exists():
        return BioResponse.fail("Task directory not found")
    
    parser = AssemblyReportParser(task_dir)
    report = parser.generate_report()
    
    exporter = ReportExporter(task_dir)
    html_path = exporter.export_html(report)
    
    return BioResponse.ok({
        "path": str(html_path.resolve()),
        "filename": html_path.name
    })


@router.delete("/tasks/{task_id}")
async def delete_assembly_task(task_id: str):
    """清理任务记录与物理文件"""
    from ..utils.assembly_db import assembly_db
    from ..utils.assembly_storage import AssemblyStorage
    
    # 1. 删除数据库记录
    assembly_db.delete_task(task_id)
    
    # 2. 清理物理文件夹
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir)
        
    return BioResponse.ok(f"Task {task_id} and its files have been removed.")

@router.post("/{task_id}/stop")
async def stop_assembly_task(task_id: str):
    """强制停止正在运行的流水线"""
    success = manager.stop_task(task_id)
    if success:
        # 同步数据库状态
        assembly_db.finalize_task(task_id, "aborted", {"message": "User requested abort"})
        # 广播给前端
        broadcaster.broadcast_sync("assembly_progress", {
            "task_id": task_id,
            "step": "ABORTED",
            "progress": 0,
            "status": "error"
        })
        return BioResponse.ok("Task stopped successfully")
    return BioResponse.fail("Task not found or already finished")

async def execute_assembly_pipeline(payload: Dict[str, Any]):
    """
    由 TaskQueue 的 Worker 调用的流水线逻辑
    """
    from ...assembly.manager import AssemblyManager
    from ...assembly.env.conda_resolver import CondaResolver
    from ..utils.assembly_db import assembly_db
    
    task_id = payload.get('task_id')
    client_id = payload.get('client_id', 'unknown')
    tech = payload.get('tech')
    input_files = payload.get('config', {}).get('params', {}).get('input_files', [])
    sample_type = payload.get('sample_type', 'BACTERIA')
    
    # 提前初始化一次 DB（兜底）
    if not assembly_db.get_task(task_id):
        assembly_db.create_task(
            task_id, 
            payload.get('name', 'Task'), 
            "Unknown", 
            sample_type,
            tech, 
            payload.get('config', {})
        )

    # 🔗 使用全局 manager
    # project_root 已在全局初始化

    try:
        # --- 0. 环境探测 ---
        if not CondaResolver.find_conda() and tech != "SANGER":
            assembly_db.update_task_progress(task_id, "ENV_CHECK", 0, "error")
            await broadcaster.broadcast_to_client(client_id, "assembly_status", {
                "task_id": task_id, "status": "waiting_env", "message": "NEED_CONDA"
            })
            return

        # --- 1. NGS 拼装路线 (含 BACTERIA, PHAGE, VIRUS) ---
        if tech != "SANGER":
            if len(input_files) < 2:
                raise ValueError("基因组组装 (NGS) 需要双端 R1/R2 文件")

            sample_type = payload.get('sample_type', 'BACTERIA')
            results = await manager.run_pipeline(
                task_id=task_id,
                sample_type=sample_type,
                r1_input=input_files[0],
                r2_input=input_files[1],
                config=payload.get('config', {})
            )
            
            # 状态上报已由 Manager 内部的 assembly_db.finalize_task 处理
            status = "finished" if results.get("status") == "success" else "error"
            await broadcaster.broadcast_to_client(client_id, "assembly_status", {
                "task_id": task_id, "status": status, "results": results.get("outputs")
            })

    except Exception as e:
        logger.exception(f"Pipeline Worker 崩溃: {e}")
        assembly_db.finalize_task(task_id, "error", {"error": str(e)})
        await broadcaster.broadcast_to_client(client_id, "assembly_status", {
            "task_id": task_id, "status": "error", "error": str(e)
        })
