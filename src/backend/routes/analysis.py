
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

from src.analysis.comparison.pipeline import ComparisonPipeline

class ComparisonRequest(BaseModel):
    ref: str
    query: str
    options: Optional[dict] = {}

@router.post("/comparison/run")
async def run_comparison(req: ComparisonRequest):
    """
    运行高精度共线性分析（MUMmer 架构）
    """
    task_id = f"CMP_{os.urandom(4).hex()}"
    base_dir = Path("results/comparison") / task_id
    
    logger.info(f"🚀 [Pipeline] 启动高精度共线性对比: {task_id}")
    
    try:
        pipeline = ComparisonPipeline(base_dir)
        # 显式传递 task_id 以便 Manager 内部索引文件
        req.options["task_id"] = task_id
        result = await pipeline.execute(req.ref, req.query, req.options)
        
        return {"status": "success", "task_id": task_id, "data": result}
    except Exception as e:
        logger.error(f"Comparison pipeline failed: {str(e)}")
        return {"status": "error", "message": str(e)}

@router.get("/comparison/history")
async def get_comparison_history_list():
    """获取共线性分析专用历史列表"""
    from src.analysis.comparison.manager import get_comparison_manager
    return get_comparison_manager().list_history()

@router.delete("/comparison/{task_id}")
async def delete_comparison_task_entry(task_id: str):
    """彻底删除共线性分析任务（含物理文件）"""
    from src.analysis.comparison.manager import get_comparison_manager
    success = get_comparison_manager().delete_task(task_id)
    return {"status": "success" if success else "failed"}

@router.get("/comparison/{task_id}/results")
async def get_comparison_task_results(task_id: str):
    """获取指定任务的详细比对数据结果"""
    from src.analysis.comparison.engines.mummer import MummerEngine
    base_dir = Path("results/comparison") / task_id
    coords_file = base_dir / "reports" / "mummer_run.coords"
    
    if not coords_file.exists():
        raise HTTPException(status_code=404, detail="Results file not found or task failed")
        
    engine = MummerEngine()
    alignments = engine._parse_coords(coords_file)
    
    # 尝试加载参数
    params = {}
    params_file = base_dir / "params.json"
    if params_file.exists():
        import json
        with open(params_file, 'r') as f: params = json.load(f)

    return {
        "task_id": task_id,
        "alignments": alignments,
        "metadata": params
    }

@router.get("/history")
async def get_analysis_history():
    """获取所有简略分析历史 (Legacy)"""
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
