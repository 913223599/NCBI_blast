# -*- coding: utf-8 -*-
"""
前噬菌体与噬菌体智能发现工作台路由 (Student V4.2)
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ...analysis.phage_finder import (
    PhageConfigPathRequest,
    PhageScanInspectRequest,
    PhageScanRunRequest,
    get_phage_discovery_manager,
)

router = APIRouter(prefix="/analysis/phage_discovery", tags=["PhageDiscovery"])

_DOWNLOAD_MEDIA_TYPES = {
    "fasta": ("text/plain; charset=utf-8", "prophages.fasta"),
    "tsv": ("text/tab-separated-values; charset=utf-8", "regions.tsv"),
    "gff3": ("text/plain; charset=utf-8", "prophages.gff3"),
    "gbk": ("text/plain; charset=utf-8", "prophages.gbk"),
}


@router.get("/models")
async def get_phage_discovery_capabilities():
    """获取当前可用 V4.2 模型、GPU/CPU 环境与蛋白门控库状态。"""
    mgr = get_phage_discovery_manager()
    return mgr.get_capabilities()


@router.post("/config")
async def update_phage_discovery_config(req: PhageConfigPathRequest):
    """保存自定义 V4.2 模型目录或蛋白参考库相对路径配置。"""
    mgr = get_phage_discovery_manager()
    try:
        return mgr.update_config(
            models_root=req.models_root,
            default_model_dir=req.default_model_dir,
            blast_db=req.blast_db,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/inspect")
async def inspect_phage_discovery_input(req: PhageScanInspectRequest):
    """预检 FASTA/GenBank 输入，返回 Contig 清单与长度/GC 分布。"""
    mgr = get_phage_discovery_manager()
    try:
        return mgr.inspect_input(fasta_path=req.fasta_path, fasta_content=req.fasta_content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run")
async def run_phage_discovery_task(req: PhageScanRunRequest):
    """提交异步 V4.2 前噬菌体发现扫描任务。"""
    mgr = get_phage_discovery_manager()
    try:
        return await mgr.submit_task(req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"任务提交失败: {exc}") from exc


@router.get("/queue/status")
async def get_phage_discovery_queue_status():
    mgr = get_phage_discovery_manager()
    return mgr.queue.get_queue_snapshot()


@router.get("/history")
async def list_phage_discovery_history(limit: int = Query(default=100, ge=1, le=500)):
    mgr = get_phage_discovery_manager()
    return {"tasks": mgr.list_history(limit=limit)}


@router.get("/{task_id}/result")
async def get_phage_discovery_result(task_id: str):
    mgr = get_phage_discovery_manager()
    try:
        return mgr.get_task_result(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/region/{region_index}/gbk")
async def get_phage_discovery_region_gbk(task_id: str, region_index: int):
    """读取带宿主侧翼的单个前噬菌体区段 GenBank 文本以供图谱浏览。"""
    mgr = get_phage_discovery_manager()
    try:
        return mgr.get_region_gbk(task_id, region_index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/overlay")
async def get_phage_discovery_overlay(
    task_id: str,
    contig_id: Optional[str] = Query(default=None),
):
    """读取指定 Contig 的底图基因与前噬菌体预测叠图 JSON 分片数据。"""
    mgr = get_phage_discovery_manager()
    try:
        return mgr.get_contig_overlay(task_id, contig_id=contig_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/overlay-gbk")
async def get_phage_discovery_overlay_gbk(
    task_id: str,
    contig_id: Optional[str] = Query(default=None),
):
    """组装目标 Contig 完整底图与预测前噬菌体叠图的 GenBank 文本以直连 GenomeViewer。"""
    mgr = get_phage_discovery_manager()
    try:
        return mgr.get_contig_overlay_gbk(task_id, contig_id=contig_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/fasta-text")
async def get_phage_discovery_fasta_text(
    task_id: str,
    region_index: Optional[int] = Query(default=None, ge=1),
):
    """提取所有或单个命中前噬菌体区段的 FASTA 文本以直连功能注释模块。"""
    mgr = get_phage_discovery_manager()
    try:
        fasta_path = mgr.resolve_task_file(task_id, "fasta")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raw_text = fasta_path.read_text(encoding="utf-8")
    if region_index is None:
        return {"fasta_text": raw_text, "label": f"{task_id}_all_prophages"}

    target_prefix = f">Phage_{region_index:03d}|"
    selected_lines = []
    capturing = False
    for line in raw_text.splitlines():
        if line.startswith(">"):
            if line.startswith(target_prefix):
                capturing = True
                selected_lines.append(line)
            else:
                if capturing:
                    break
                capturing = False
        elif capturing:
            selected_lines.append(line)

    if not selected_lines:
        raise HTTPException(status_code=404, detail=f"FASTA 中未找到区域 Phage_{region_index:03d}")
    return {
        "fasta_text": "\n".join(selected_lines) + "\n",
        "label": f"{task_id}_Phage_{region_index:03d}",
    }


@router.get("/{task_id}/download/{file_type}")
async def download_phage_discovery_file(task_id: str, file_type: str):
    if file_type not in _DOWNLOAD_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件导出格式: {file_type}")
    mgr = get_phage_discovery_manager()
    try:
        file_path: Path = mgr.resolve_task_file(task_id, file_type)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type, suffix = _DOWNLOAD_MEDIA_TYPES[file_type]
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=f"{task_id}_{suffix}",
    )


@router.post("/{task_id}/cancel")
async def cancel_phage_discovery_task(task_id: str):
    mgr = get_phage_discovery_manager()
    return await mgr.cancel_task(task_id)


@router.delete("/{task_id}")
async def delete_phage_discovery_task(task_id: str):
    mgr = get_phage_discovery_manager()
    mgr.delete_task(task_id)
    return {"status": "deleted", "task_id": task_id}


@router.post("/{task_id}/open-folder")
async def open_phage_discovery_folder(task_id: str):
    mgr = get_phage_discovery_manager()
    try:
        folder_path = mgr.resolve_task_file(task_id, "folder")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder_path)])
        else:
            subprocess.Popen(["xdg-open", str(folder_path)])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开目录失败: {exc}") from exc

    return {"status": "opened", "path": str(folder_path)}

