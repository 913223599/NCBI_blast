
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
    运行高精度共线性分析（统一引擎入口）
    支持 MUMmer / Minimap2 引擎通过 options.engine 切换
    """
    task_id = f"CMP_{os.urandom(4).hex()}"
    base_dir = Path("results/comparison") / task_id
    opts = req.options or {}
    logger.info(f"[Pipeline] 启动共线性对比: {task_id} (engine={opts.get('engine', 'mummer')})")
    
    try:
        # 【存档模式】
        if opts.get("mode") == "save_only" and opts.get("instant_data"):
            data = opts.get("instant_data")
            from src.analysis.comparison.manager import get_comparison_manager
            get_comparison_manager().record_task(
                task_id=data.get("task_id", task_id),
                metadata={
                    "ref_name": req.ref,
                    "query_name": req.query,
                    "was_flipped": data.get("was_flipped", False),
                    "engine": "instant_js"
                },
                summary={
                    "matched_length": data.get("matched_length", 0),
                    "average_identity": data.get("average_identity", 0.0),
                    "total_matches": data.get("total_matches", 0),
                    "ref_length": data.get("ref_length", 0),
                    "query_length": data.get("query_length", 0)
                },
                variant_count=data.get("variant_count", 0)
            )
            return {"status": "success", "task_id": data.get("task_id", task_id), "is_instant": True}

        pipeline = ComparisonPipeline(base_dir)
        opts["task_id"] = task_id
        result = await pipeline.execute(req.ref, req.query, opts)
        
        return {"status": "success", "task_id": task_id, "data": result}
    except Exception as e:
        logger.error(f"Comparison pipeline failed: {str(e)}")
        return {"status": "error", "message": str(e)}

@router.get("/comparison/history")
async def get_comparison_history_list():
    """获取共线性分析历史列表"""
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
    """获取指定任务的详细比对数据（含变异位点）"""
    from src.analysis.comparison.manager import get_comparison_manager
    task_info = get_comparison_manager().get_task(task_id)
    
    base_dir = Path("results/comparison") / task_id
    coords_file = base_dir / "reports" / "mummer_run.coords"
    snps_file = base_dir / "reports" / "mummer_run.snps"
    
    if not coords_file.exists():
        if task_info and task_info.get("engine") == "instant_js":
            return {
                "task_id": task_id,
                "alignments": [],
                "variants": [],
                "variant_count": task_info.get("variant_count", 0),
                "summary": {
                    "ref_length": task_info.get("ref_length", 0),
                    "query_length": task_info.get("query_length", 0),
                    "average_identity": task_info.get("average_identity", 0.0),
                    "matched_length": task_info.get("matched_length", 0),
                },
                "metadata": {
                    "ref_name": task_info.get("ref_name", ""),
                    "query_name": task_info.get("query_name", ""),
                    "was_flipped": bool(task_info.get("was_flipped", 0)),
                    "engine": "instant_js"
                }
            }
        raise HTTPException(status_code=404, detail="Results file not found or task failed")
        
    from src.analysis.comparison.engines.mummer import MummerEngine
    engine = MummerEngine()
    alignments = engine._parse_coords(coords_file)
    variants = engine._parse_snps(snps_file)
    
    metadata = {}
    if task_info:
        metadata = {
            "ref_name": task_info.get("ref_name", ""),
            "query_name": task_info.get("query_name", ""),
            "was_flipped": bool(task_info.get("was_flipped", 0)),
            "engine": task_info.get("engine", "mummer")
        }

    return {
        "task_id": task_id,
        "alignments": alignments,
        "variants": variants[:200],
        "variant_count": len(variants),
        "summary": engine.generate_summary(alignments),
        "metadata": metadata
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
