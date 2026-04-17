
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import logging
from pathlib import Path
from src.analysis.sequence_utils import RotationChecker

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = logging.getLogger("api.analysis")

from src.backend.analysis_db import db as adb
from src.analysis.manager import AnalysisManager

class AlignmentRequest(BaseModel):
    mode: str = "pairwise" 
    target_path: Optional[str] = None
    query_path: Optional[str] = None
    file_paths: List[str] = []
    task_id: Optional[str] = None

@router.post("/align")
async def start_alignment(req: AlignmentRequest):
    """
    执行序列比对调度（支持两两、参考、矩阵模式）
    """
    task_id = req.task_id or f"AN_{os.urandom(4).hex()}"
    base_dir = os.path.join("results", "analysis", task_id)
    os.makedirs(base_dir, exist_ok=True)
    
    logger.info(f"📥 [Analysis] 启动比对任务 (Mode: {req.mode}, Task: {task_id})")
    
    try:
        results = []
        if req.mode == "pairwise":
            if not req.target_path or not req.query_path:
                raise HTTPException(status_code=400, detail="Pairwise mode requires target and query paths")
            res = AnalysisManager.run_pairwise_mode(req.target_path, req.query_path, base_dir)
            results.append(res)
            
        elif req.mode == "reference":
            if not req.target_path or len(req.file_paths) < 1:
                raise HTTPException(status_code=400, detail="Reference mode requires target and file_paths")
            results = AnalysisManager.run_reference_mode(req.target_path, req.file_paths, base_dir)
            
        elif req.mode == "matrix":
            if len(req.file_paths) < 2:
                raise HTTPException(status_code=400, detail="Matrix mode requires at least 2 file paths")
            results = AnalysisManager.run_cross_mode(req.file_paths, base_dir)
        else:
            raise HTTPException(status_code=400, detail="Unsupported analysis mode")

        # 异步持久化到数据库
        for r in results:
            adb.save_record(req.mode, r)

        return {"success": True, "task_id": task_id, "mode": req.mode, "results": results}
            
    except Exception as e:
        logger.error(f"Analysis task failed: {str(e)}")
        return {"success": False, "error": str(e)}

@router.get("/history")
async def get_analysis_history():
    """获取所有简略分析历史"""
    return {"data": adb.get_history()}

@router.get("/history/{record_id}")
async def get_history_detail(record_id: int):
    """获取单条比对详情数据"""
    detail = adb.get_detail(record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Record not found")
    return detail

@router.delete("/history/{record_id}")
async def delete_history_record(record_id: int):
    """删除历史记录"""
    adb.delete_record(record_id)
    return {"success": True}
