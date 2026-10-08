# -*- coding: utf-8 -*-
"""
16S 扩增子混样多样性与 rrnDB 拷贝数归一化接口路由
"""
import os
import zipfile
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pandas as pd

from ..services.diversity_engine import get_diversity_engine
from ..services.rrndb_service import get_rrndb_service

logger = logging.getLogger("api_server")
router = APIRouter(prefix="/diversity", tags=["Amplicon Diversity"])


class DiversityRunRequest(BaseModel):
    input_path: str
    params: Optional[Dict[str, Any]] = None


class DetectPackageRequest(BaseModel):
    file_path: str


@router.post("/detect_package")
async def detect_package(req: DetectPackageRequest):
    """智能嗅探上传的文件是否属于生工三代测序包或扩增子结果包"""
    p = Path(req.file_path)
    if not p.exists():
        return {"is_amplicon_package": False, "reason": "文件不存在"}

    if p.is_file() and p.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(p, "r") as zf:
                names = zf.namelist()
                fastq_names = [n for n in names if n.endswith(".fastq.gz") or n.endswith(".fastq")]
                has_var = any(n.endswith(".var.xls") for n in names)
                has_haplo = any("haplotype" in n for n in names)
                
                if fastq_names:
                    return {
                        "is_amplicon_package": True,
                        "package_type": "sangon_nanopore" if (has_var or has_haplo) else "generic_amplicon",
                        "fastq_count": len(fastq_names),
                        "file_name": p.name
                    }
        except Exception as e:
            logger.warning(f"检测 ZIP 包异常: {e}")

    return {"is_amplicon_package": False}


@router.post("/run")
async def run_diversity_task(req: DiversityRunRequest):
    """提交多样性分析任务"""
    if not os.path.exists(req.input_path):
        raise HTTPException(status_code=400, detail="指定的输入文件不存在")

    task_id = get_diversity_engine().create_task(req.input_path, req.params)
    return {"status": "started", "task_id": task_id}


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """查询分析任务进度与 Checkpoint 状态"""
    return get_diversity_engine().get_task_status(task_id)


@router.get("/results/{task_id}")
async def get_task_results(task_id: str):
    """获取全量多样性分析报告"""
    res = get_diversity_engine().get_task_results(task_id)
    if not res:
        raise HTTPException(status_code=404, detail="未找到任务结果或分析尚未完成")
    return res


@router.get("/export_excel/{task_id}")
async def export_excel(task_id: str):
    """导出标准科研格式的多工作表 Excel 综合多样性分析表"""
    data = get_diversity_engine().get_task_results(task_id)
    if not data:
        raise HTTPException(status_code=404, detail="未找到分析结果")

    engine = get_diversity_engine()
    task_dir = Path(engine.results_root) / task_id
    excel_path = task_dir / f"16S_Diversity_Report_{task_id}.xlsx"

    samples = data.get("samples", [])
    
    # Sheet 1: Alpha 多样性指标
    alpha_rows = []
    for s in samples:
        a = s.get("alpha_diversity", {})
        alpha_rows.append({
            "样本编号": s.get("sample_name"),
            "总 Reads 数": s.get("total_reads"),
            "已分类 Reads": s.get("classified_reads"),
            "物种丰富度 (Richness)": a.get("richness"),
            "香农指数 (Shannon)": a.get("shannon"),
            "辛普森指数 (Simpson)": a.get("simpson"),
            "Chao1 丰富度估算": a.get("chao1"),
            "Pielou 均匀度 (Evenness)": a.get("evenness")
        })
    df_alpha = pd.DataFrame(alpha_rows)

    # 提取所有分类单元
    all_taxa = sorted(list({
        d["taxon"] 
        for s in samples 
        for d in s.get("norm_result", {}).get("details", [])
    }))

    # Sheet 2: 原始相对丰度表 (Raw %)
    raw_mat = []
    for s in samples:
        row = {"样本编号": s.get("sample_name")}
        d_map = {d["taxon"]: d["raw_pct"] for d in s.get("norm_result", {}).get("details", [])}
        for t in all_taxa:
            row[t] = d_map.get(t, 0.0)
        raw_mat.append(row)
    df_raw = pd.DataFrame(raw_mat)

    # Sheet 3: rrnDB 拷贝数归一化丰度表 (Normalized %)
    norm_mat = []
    for s in samples:
        row = {"样本编号": s.get("sample_name")}
        d_map = {d["taxon"]: d["norm_pct"] for d in s.get("norm_result", {}).get("details", [])}
        for t in all_taxa:
            row[t] = d_map.get(t, 0.0)
        norm_mat.append(row)
    df_norm = pd.DataFrame(norm_mat)

    # Sheet 4: 全局物种列表与 rrnDB GCN 拷贝数
    overview = data.get("taxa_overview", [])
    df_overview = pd.DataFrame(overview)
    if not df_overview.empty:
        df_overview.rename(columns={
            "taxon": "物种/分类单元",
            "raw_count": "全批次总 Reads",
            "raw_pct": "全批次原始占比 (%)",
            "norm_pct": "rrnDB归一化占比 (%)",
            "sample_frequency": "样本检出频次",
            "gcn_mean": "平均 16S 拷贝数 (GCN)"
        }, inplace=True)

    with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
        df_alpha.to_excel(writer, sheet_name="Alpha多样性指数", index=False)
        df_raw.to_excel(writer, sheet_name="原始相对丰度(%)", index=False)
        df_norm.to_excel(writer, sheet_name="rrnDB校正相对丰度(%)", index=False)
        if not df_overview.empty:
            df_overview.to_excel(writer, sheet_name="物种全局概览与拷贝数", index=False)

    return FileResponse(
        path=str(excel_path),
        filename=f"16S_Diversity_Report_{task_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
