# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测 FastAPI 路由
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ...analysis.phage_structure import (
    StructureInspectRequest,
    StructureRunRequest,
    get_phage_structure_manager,
)

router = APIRouter(prefix="/analysis/phage_structure", tags=["PhageStructure"])

_MEDIA_MAP = {
    "json": ("application/json; charset=utf-8", "structure_report.json"),
    "summary_tsv": ("text/tab-separated-values; charset=utf-8", "morphotype_summary.tsv"),
    "features_tsv": ("text/tab-separated-values; charset=utf-8", "structure_features.tsv"),
    "tmp_tsv": ("text/tab-separated-values; charset=utf-8", "tmp_analysis.tsv"),
    "gbk": ("text/plain; charset=utf-8", "annotated_structure.gbk"),
}


@router.get("/capabilities")
async def get_structure_capabilities():
    """获取结构预测引擎硬件与 PHROG HMM 索引状态。"""
    return get_phage_structure_manager().get_capabilities()


@router.get("/sources")
async def list_structure_linked_sources():
    """列出历史注释任务及前噬菌体扫描记录，供一键导入预测。"""
    return get_phage_structure_manager().list_linked_sources()


@router.post("/inspect")
async def inspect_structure_input(req: StructureInspectRequest):
    """预检输入文件、文本或关联历史任务，返回 Contig 列表。"""
    mgr = get_phage_structure_manager()
    try:
        return mgr.inspect_input(req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run")
async def run_structure_prediction(req: StructureRunRequest):
    """提交异步噬菌体结构与尾部形态预测任务。"""
    mgr = get_phage_structure_manager()
    try:
        return await mgr.submit_task(req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"结构预测任务提交失败: {exc}") from exc


@router.get("/queue/status")
async def get_structure_queue_status():
    return get_phage_structure_manager().queue.get_queue_snapshot()


@router.get("/history")
async def list_structure_history(limit: int = Query(default=100, ge=1, le=500)):
    return {"tasks": get_phage_structure_manager().list_history(limit=limit)}


@router.get("/{task_id}/result")
async def get_structure_result(task_id: str):
    try:
        return get_phage_structure_manager().get_task_result(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/gbk")
async def get_structure_gbk(task_id: str):
    try:
        return get_phage_structure_manager().get_task_gbk(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/download/{file_type}")
async def download_structure_file(task_id: str, file_type: str):
    if file_type not in _MEDIA_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的导出格式: {file_type}")
    try:
        fpath: Path = get_phage_structure_manager().resolve_task_file(task_id, file_type)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    mtype, suffix = _MEDIA_MAP[file_type]
    return FileResponse(path=str(fpath), media_type=mtype, filename=f"{task_id}_{suffix}")


@router.post("/{task_id}/cancel")
async def cancel_structure_task(task_id: str):
    return await get_phage_structure_manager().cancel_task(task_id)


@router.delete("/{task_id}")
async def delete_structure_task(task_id: str):
    get_phage_structure_manager().delete_task(task_id)
    return {"status": "deleted", "task_id": task_id}


@router.post("/{task_id}/open-folder")
async def open_structure_folder(task_id: str):
    try:
        folder: Path = get_phage_structure_manager().resolve_task_file(task_id, "folder")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开目录失败: {exc}") from exc
    return {"status": "opened", "path": str(folder)}
