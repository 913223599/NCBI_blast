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
    
    exporter = ReportExporter(task_id, report)
    html_path = exporter.export_html(task_dir)
    
    return BioResponse.ok({
        "path": str(html_path),
        "filename": html_path.name
    })

@router.get("/report/{task_id}/unannotated_proteins")
async def get_unannotated_proteins(task_id: str):
    """提取未注释的蛋白序列（用于后续 BLAST 比对）"""
    from Bio import SeqIO
    
    task_dir = AssemblyStorage.get_task_dir(task_id)
    anno_dir = task_dir / "phageannotationstep"
    
    # 优先使用 Phold 产物，否则用 Pharokka 产物
    phold_faa = anno_dir / "phold_res" / "phold_aa.fasta"
    pharokka_faa = anno_dir / "pharokka_res" / "phanotate.faa"
    
    faa_file = phold_faa if phold_faa.exists() else pharokka_faa
    if not faa_file.exists():
        return BioResponse.fail("未找到蛋白序列文件")
    
    # 读取 Phold 预测结果，筛选出 unknown function 的 CDS ID
    unknown_ids = set()
    phold_tsv = anno_dir / "phold_res" / "phold_per_cds_predictions.tsv"
    pharokka_tsv = anno_dir / "pharokka_res" / "PHAGE_cds_final_merged_output.tsv"
    
    import csv
    tsv_file = phold_tsv if phold_tsv.exists() else pharokka_tsv
    if tsv_file.exists():
        with open(tsv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                func = row.get("function", "").strip().lower()
                if func in ("unknown function", "hypothetical protein", ""):
                    cds_id = row.get("cds_id", "")
                    if cds_id:
                        unknown_ids.add(cds_id)
    
    # 从 FASTA 中提取对应序列
    sequences = []
    for record in SeqIO.parse(faa_file, "fasta"):
        rec_id = record.id.strip()
        # 如果有 TSV 过滤，仅提取未注释的；否则全量导出
        if not unknown_ids or rec_id in unknown_ids:
            sequences.append({
                "id": rec_id,
                "description": record.description,
                "sequence": str(record.seq)
            })
    
    # 同时生成 FASTA 文本
    fasta_text = "\n".join([f">{s['id']} {s['description']}\n{s['sequence']}" for s in sequences])
    
    return BioResponse.ok({
        "count": len(sequences),
        "total_in_file": sum(1 for _ in SeqIO.parse(faa_file, "fasta")),
        "sequences": sequences[:100],  # 前端展示限 100 条
        "fasta_text": fasta_text
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
