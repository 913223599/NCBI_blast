# -*- coding: utf-8 -*-
"""
泛基因组与多样本多维比较分析路由 (FastAPI)
"""
import io
import csv
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from src.analysis.pan_genomics.types import PanGenomicsRunRequest, PanGenomicsResult
from src.analysis.pan_genomics.engine import PanGenomicsEngine
from src.analysis.annotation.manager import get_annotation_manager

logger = logging.getLogger("api.analysis.pan_genomics")
router = APIRouter(prefix="/analysis/pan_genomics", tags=["PanGenomics"])

# 内存缓存近期分析结果
_RESULTS_CACHE: Dict[str, PanGenomicsResult] = {}


@router.get("/samples")
async def get_available_samples():
    """获取可用于泛基因组分析的系统内历史注释任务样本列表"""
    manager = get_annotation_manager()
    tasks = manager.list_history(limit=100)
    
    samples = []
    for t in tasks:
        if t.get("status") == "completed":
            summary = t.get("summary") or {}
            samples.append({
                "sample_id": t["task_id"],
                "sample_name": t["task_name"],
                "sample_type": t.get("sample_type", "PHAGE"),
                "cds_count": summary.get("cds_count", t.get("feature_count", 0)),
                "annotated_count": summary.get("annotated_count", 0),
                "hypothetical_count": summary.get("hypothetical_count", 0),
                "created_at": t.get("created_at", "")
            })
    return {"success": True, "data": samples}


@router.post("/run")
async def run_pan_genomics(req: PanGenomicsRunRequest):
    """
    提交并执行多样本泛基因组与深度交叉对比分析
    """
    if len(req.samples) < 2:
        raise HTTPException(status_code=400, detail="泛基因组分析至少需要选择 2 个样本")

    try:
        engine = PanGenomicsEngine()
        result = engine.run_analysis(req)
        _RESULTS_CACHE[result.task_id] = result
        return {"success": True, "data": result.model_dump()}
    except Exception as e:
        logger.error(f"泛基因组分析执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"泛基因组分析失败: {str(e)}")


@router.get("/{task_id}/result")
async def get_pan_genomics_result(task_id: str):
    """获取指定任务的泛基因组分析结果"""
    if task_id in _RESULTS_CACHE:
        return {"success": True, "data": _RESULTS_CACHE[task_id].model_dump()}
    raise HTTPException(status_code=404, detail=f"未找到泛基因组分析任务 {task_id}")


@router.get("/{task_id}/export/csv")
async def export_ortholog_matrix_csv(task_id: str):
    """导出泛基因组正交家族大表 CSV"""
    if task_id not in _RESULTS_CACHE:
        raise HTTPException(status_code=404, detail=f"未找到泛基因组任务 {task_id}")

    res = _RESULTS_CACHE[task_id]
    sample_ids = list(res.sample_names.keys())
    sample_headers = [res.sample_names[sid] for sid in sample_ids]

    output = io.StringIO()
    writer = csv.writer(output)

    # 表头
    writer.writerow([
        "Ortholog_Group",
        "Cluster_Type",
        "Category",
        "Representative_Product",
        "Sample_Count",
        "Total_Genes"
    ] + sample_headers)

    for cl in res.clusters:
        sample_genes_map = {sid: [] for sid in sample_ids}
        for g in cl.genes:
            sample_genes_map[g.sample_id].append(f"{g.locus_tag} ({g.product})")

        row = [
            cl.group_id,
            cl.cluster_type,
            cl.category,
            cl.representative_product,
            cl.sample_count,
            cl.total_genes
        ]
        for sid in sample_ids:
            row.append("; ".join(sample_genes_map[sid]) if sample_genes_map[sid] else "-")

        writer.writerow(row)

    csv_text = output.getvalue()
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pan_genomics_{task_id}.csv"}
    )
