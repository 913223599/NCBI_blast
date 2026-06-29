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
from ..utils.persistent_queue import persistent_queue as assembly_queue

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
    
    # 2. 持久化到数据库
    sample_id = payload.get('sample_id', 'Unknown')
    name = payload.get('name', 'Assembly Task')
    sample_type = payload.get('sample_type', 'BACTERIA')
    tech = payload.get('tech', 'ILLUMINA')
    config = payload.get('config', {})
    logger.info(f"📝 Creating task in DB: {task_id}")
    assembly_db.create_task(task_id, name, sample_id, sample_type, tech, config)
    logger.info(f"✅ Task created in DB: {task_id}")
    
    # 3. 加入队列处理
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
            
    return BioResponse.fail("Plot not found")

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
    """清理任务记录与物理文件，并同时从内存队列中摘除"""
    from ..utils.assembly_db import assembly_db
    from ..utils.assembly_storage import AssemblyStorage
    
    # 0. 尝试从活动等待队列中摘除 (支持 UI 的即时反应)
    assembly_queue.remove_task_from_queue(task_id)
    
    # 1. 删除数据库记录
    assembly_db.delete_task(task_id)
    
    # 2. 清理物理文件夹
    task_dir = AssemblyStorage.get_task_dir(task_id)
    if task_dir.exists():
        import shutil
        shutil.rmtree(task_dir, ignore_errors=True)
        
    return BioResponse.ok(f"Task {task_id} and its files have been removed.")

@router.post("/queue/reorder")
async def reorder_assembly_queue(payload: Dict[str, Any]):
    """处理前端发来的拖拽重排序请求"""
    task_ids = payload.get("task_ids", [])
    if task_ids and isinstance(task_ids, list):
        assembly_queue.reorder_queue(task_ids)
    return BioResponse.ok("Queue successfully reordered")

@router.get("/queue")
async def get_queue_status():
    """获取当前队列状态快照"""
    snapshot = await assembly_queue.get_queue_status()
    return BioResponse.ok(snapshot)

@router.post("/batch")
async def submit_batch(payload: Dict[str, Any]):
    """
    批量提交多组测序文件：
    payload.file_groups: [[R1, R2], [R1, R2], ...]
    每组自动生成独立的 task_id 进入队列
    """
    import time as _time
    file_groups = payload.get('file_groups', [])
    base_config = payload.get('config', {})
    sample_type = payload.get('sample_type', 'BACTERIA')
    tech = payload.get('tech', 'ILLUMINA')
    task_name_prefix = payload.get('name_prefix', 'Batch')

    created_ids = []
    for idx, group in enumerate(file_groups):
        if len(group) < 2:
            continue
        task_id = f"AS_{int(_time.time() * 1000)}_{idx}"
        task_payload = {
            'task_id': task_id,
            'name': f"{task_name_prefix}_{idx + 1}",
            'sample_type': sample_type,
            'tech': tech,
            'config': {
                **base_config,
                'params': {
                    **base_config.get('params', {}),
                    'input_files': list(group)
                }
            }
        }
        AssemblyStorage.get_task_dir(task_id)
        
        # 🔗 关键：持久化到数据库，使 queue 接口能读到
        import os as _os
        sample_id = _os.path.basename(group[0]).split('.')[0] if group else 'Sample'
        
        logger.info(f"📝 Batch: Creating task in DB: {task_id}")
        assembly_db.create_task(
            task_id, 
            task_payload['name'], 
            sample_id, 
            sample_type, 
            tech, 
            task_payload['config']
        )
        logger.info(f"✅ Batch: Task created in DB: {task_id}")
        
        await assembly_queue.add_task(task_payload)
        created_ids.append(task_id)

    return BioResponse.ok({
        'message': f'{len(created_ids)} tasks queued',
        'task_ids': created_ids,
        'queue_size': assembly_queue.get_queue_size()
    })

@router.post("/{task_id}/stop")
async def stop_assembly_task(task_id: str):
    """强制停止正在运行的流水线"""
    actual_id = manager.stop_task(task_id)
    if actual_id:
        # 同步数据库状态
        assembly_db.finalize_task(actual_id, "aborted", {"message": "User requested abort"})
        # 广播给前端
        broadcaster.broadcast_sync("assembly_progress", {
            "task_id": actual_id,
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
    
    task_id = str(payload.get('task_id', ''))
    client_id = str(payload.get('client_id', 'unknown'))
    tech = str(payload.get('tech', ''))
    input_files = payload.get('config', {}).get('params', {}).get('input_files', [])
    sample_type = str(payload.get('sample_type', 'BACTERIA'))
    
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
        else:
            # --- 2. 一代测序 (Sanger) 路线处理 ---
            error_msg = "Sanger 测序流水线当前处于功能开发中 (Under Development)，暂不支持该操作。"
            logger.warning(f"Task {task_id}: {error_msg}")
            
            # 主动置为失败，防止前端死等
            assembly_db.finalize_task(task_id, "error", {"error": error_msg})
            assembly_db.update_task_progress(task_id, "SANGER_NOT_IMPLEMENTED", 0, "error")
            await broadcaster.broadcast_to_client(client_id, "assembly_status", {
                "task_id": task_id, "status": "error", "error": error_msg
            })

    except Exception as e:
        logger.exception(f"Pipeline Worker 崩溃: {e}")
        assembly_db.finalize_task(task_id, "error", {"error": str(e)})
        await broadcaster.broadcast_to_client(client_id, "assembly_status", {
            "task_id": task_id, "status": "error", "error": str(e)
        })
