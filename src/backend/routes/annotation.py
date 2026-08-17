# -*- coding: utf-8 -*-
"""
功能注释 API 路由 (FastAPI)
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, PlainTextResponse

from src.analysis.annotation.types import AnnotationRunRequest, FastaInspectRequest
from src.analysis.annotation.manager import get_annotation_manager

logger = logging.getLogger("api.analysis.annotation")
router = APIRouter(prefix="/analysis/annotation", tags=["Annotation"])


@router.post("/inspect")
async def inspect_fasta(req: FastaInspectRequest):
    """
    快速预检查并解析 FASTA 序列的 Contig 列表与长度统计
    """
    if not req.fasta_path and not (req.fasta_content and req.fasta_content.strip()):
        raise HTTPException(status_code=400, detail="必须提供 fasta_path 或 fasta_content")

    manager = get_annotation_manager()
    result = manager.inspect_fasta(fasta_path=req.fasta_path, fasta_content=req.fasta_content)
    return result


@router.post("/run")
async def run_annotation(req: AnnotationRunRequest):
    """
    提交并启动 FASTA 功能注释任务
    支持通过 fasta_path 本地路径或 fasta_content 字符串内容提交
    """
    if not req.fasta_path and not (req.fasta_content and req.fasta_content.strip()):
        raise HTTPException(status_code=400, detail="必须提供 fasta_path 或 fasta_content")
        
    manager = get_annotation_manager()
    result = await manager.submit_task(req)
    return result


@router.get("/history")
async def get_annotation_history(limit: int = 50):
    """获取所有注释历史任务列表"""
    manager = get_annotation_manager()
    tasks = manager.list_history(limit=limit)
    return {"success": True, "data": tasks}


@router.get("/{task_id}/result")
async def get_annotation_result(task_id: str):
    """获取指定任务的详细分析结果与特征数据"""
    manager = get_annotation_manager()
    result = manager.get_task_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"未找到任务 {task_id}")
    return {"success": True, "data": result}


@router.get("/{task_id}/download/{file_type}")
async def download_annotation_file(task_id: str, file_type: str):
    """下载指定格式的产物文件 (gbk, gff, faa, ffn, tsv, json)"""
    manager = get_annotation_manager()
    file_path = manager.get_task_file_path(task_id, file_type)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到任务 {task_id} 的 {file_type} 产物文件")
        
    media_types = {
        "gbk": "text/plain",
        "gff": "text/plain",
        "faa": "text/plain",
        "ffn": "text/plain",
        "tsv": "text/tab-separated-values",
        "json": "application/json"
    }
    media_type = media_types.get(file_type.lower(), "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_type
    )


@router.post("/{task_id}/cancel")
async def cancel_annotation_task(task_id: str):
    """取消正在运行的注释任务"""
    manager = get_annotation_manager()
    success = manager.cancel_task(task_id)
    return {"success": success, "message": "任务已发送取消指令" if success else "任务未在运行或不存在"}


@router.delete("/{task_id}")
async def delete_annotation_task(task_id: str):
    """删除注释任务及其物理文件"""
    manager = get_annotation_manager()
    success = manager.delete_task(task_id)
    return {"success": success, "message": "任务已彻底删除" if success else "删除失败"}
