# -*- coding: utf-8 -*-
"""
核心蛋白跨样本比对与变异分析 API 路由
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ...analysis.annotation.db import annotation_db
from ...analysis.protein_compare.engine import ProteinComparer, PROTEIN_CATEGORIES

logger = logging.getLogger("ProteinCompareAPI")
router = APIRouter(prefix="/api/analysis/protein_compare", tags=["ProteinCompare"])


class RunCompareRequest(BaseModel):
    """跨样本比对请求参数"""
    sample_a_id: str = Field(description="样本A 任务 ID 或文件标识")
    sample_b_id: str = Field(description="样本B 任务 ID 或文件标识")
    sample_a_name: Optional[str] = Field(default=None, description="样本A 显示名称")
    sample_b_name: Optional[str] = Field(default=None, description="样本B 显示名称")
    category: str = Field(default="all", description="目标比对功能大类: all, tail_fiber, lysis, capsid_head, replication, packaging")


@router.get("/categories")
async def get_supported_categories():
    """获取支持的关键功能蛋白分类列表"""
    return {
        "success": True,
        "data": [
            {"key": k, "label": v["label"]}
            for k, v in PROTEIN_CATEGORIES.items()
        ]
    }


@router.get("/tasks")
async def get_comparable_tasks(limit: int = 50):
    """获取所有可作为比对源的已完成注释任务"""
    try:
        tasks = annotation_db.list_tasks(limit=limit)
        completed_tasks = []
        for t in tasks:
            if t.get("status") == "completed":
                summary = t.get("summary") or {}
                completed_tasks.append({
                    "task_id": t.get("task_id"),
                    "task_name": t.get("task_name"),
                    "sample_type": t.get("sample_type"),
                    "engine": t.get("engine"),
                    "cds_count": summary.get("cds_count", 0),
                    "total_length": summary.get("total_length", 0),
                    "created_at": t.get("created_at")
                })
        return {"success": True, "data": completed_tasks}
    except Exception as e:
        logger.error(f"获取可比对任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
async def run_protein_comparison(req: RunCompareRequest):
    """执行两个样本的蛋白质跨样本深度对齐与变异分析"""
    try:
        # 1. 查找样本 A 数据
        rec_a = annotation_db.get_task(req.sample_a_id)
        if not rec_a or rec_a.get("status") != "completed":
            raise HTTPException(status_code=404, detail=f"未找到样本 A 或该任务尚未完成: {req.sample_a_id}")
        
        # 2. 查找样本 B 数据
        rec_b = annotation_db.get_task(req.sample_b_id)
        if not rec_b or rec_b.get("status") != "completed":
            raise HTTPException(status_code=404, detail=f"未找到样本 B 或该任务尚未完成: {req.sample_b_id}")

        sample_a_name = req.sample_a_name or rec_a.get("task_name") or req.sample_a_id
        sample_b_name = req.sample_b_name or rec_b.get("task_name") or req.sample_b_id

        # 3. 载入蛋白质 (从结果目录)
        from pathlib import Path
        work_dir_a = Path(r"f:\NCBI blast\results\annotations") / req.sample_a_id
        work_dir_b = Path(r"f:\NCBI blast\results\annotations") / req.sample_b_id

        comparer = ProteinComparer()
        proteins_a = comparer.load_proteins_from_annotation(work_dir_a)
        proteins_b = comparer.load_proteins_from_annotation(work_dir_b)

        if not proteins_a:
            raise HTTPException(status_code=400, detail=f"样本 A ({sample_a_name}) 中未提取到任何有效蛋白质 CDS")
        if not proteins_b:
            raise HTTPException(status_code=400, detail=f"样本 B ({sample_b_name}) 中未提取到任何有效蛋白质 CDS")

        # 4. 执行比对
        result = comparer.compare_two_samples(
            sample_a_name=sample_a_name,
            sample_a_proteins=proteins_a,
            sample_b_name=sample_b_name,
            sample_b_proteins=proteins_b,
            target_category=req.category
        )

        return {"success": True, "data": result.dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行跨样本蛋白质比对失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"比对执行异常: {str(e)}")


@router.post("/export_csv")
async def export_comparison_csv(req: RunCompareRequest):
    """导出比对报告为 CSV 文件流"""
    try:
        rec_a = annotation_db.get_task(req.sample_a_id)
        rec_b = annotation_db.get_task(req.sample_b_id)
        if not rec_a or not rec_b:
            raise HTTPException(status_code=404, detail="样本记录不存在")

        sample_a_name = req.sample_a_name or rec_a.get("task_name") or req.sample_a_id
        sample_b_name = req.sample_b_name or rec_b.get("task_name") or req.sample_b_id

        from pathlib import Path
        work_dir_a = Path(r"f:\NCBI blast\results\annotations") / req.sample_a_id
        work_dir_b = Path(r"f:\NCBI blast\results\annotations") / req.sample_b_id

        comparer = ProteinComparer()
        proteins_a = comparer.load_proteins_from_annotation(work_dir_a)
        proteins_b = comparer.load_proteins_from_annotation(work_dir_b)

        result = comparer.compare_two_samples(
            sample_a_name=sample_a_name,
            sample_a_proteins=proteins_a,
            sample_b_name=sample_b_name,
            sample_b_proteins=proteins_b,
            target_category=req.category
        )

        csv_text = comparer.export_to_csv(result)
        filename = f"Protein_Comparison_{req.sample_a_id}_{req.sample_b_id}.csv"

        return Response(
            content=csv_text.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        logger.error(f"导出比对 CSV 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
