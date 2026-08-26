import os
import time
import json
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, File, Form
from pydantic import BaseModel, Field

from ...analysis.annotation.db import annotation_db
from ...analysis.protein_compare.engine import ProteinComparer, PROTEIN_CATEGORIES

logger = logging.getLogger("ProteinCompareAPI")
router = APIRouter(prefix="/api/analysis/protein_compare", tags=["ProteinCompare"])


class RunCompareRequest(BaseModel):
    """跨样本比对请求参数"""
    sample_a_id: str = Field(description="样本A 任务 ID 或文件标识/路径")
    sample_b_id: str = Field(description="样本B 任务 ID 或文件标识/路径")
    sample_a_name: Optional[str] = Field(default=None, description="样本A 显示名称")
    sample_b_name: Optional[str] = Field(default=None, description="样本B 显示名称")
    category: str = Field(default="all", description="目标比对功能大类: all, tail_fiber, lysis, capsid_head, replication, packaging")


class ImportExternalFileRequest(BaseModel):
    """导入外部文件参数"""
    file_path: str = Field(description="本地文件绝对路径")
    task_name: Optional[str] = Field(default=None, description="自定义样本名称")
    sample_type: Optional[str] = Field(default="EXTERNAL", description="样本类型: PHAGE / BACTERIA / EXTERNAL")


def _load_sample_proteins(sample_id: str, custom_name: Optional[str] = None) -> Tuple[List[Any], str]:
    """辅助函数: 统一从任务目录或外部文件载入蛋白质"""
    comparer = ProteinComparer()
    
    # 1. 外部文件路径形式
    if sample_id.startswith("file:") or (":" in sample_id and Path(sample_id).exists()):
        raw_path = sample_id.replace("file:", "")
        p = Path(raw_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"外部文件不存在: {raw_path}")
        proteins, meta = comparer.load_proteins_from_file(p)
        name = custom_name or p.stem or p.name
        return proteins, name

    # 2. 数据库任务形式
    rec = annotation_db.get_task(sample_id)
    if not rec or rec.get("status") != "completed":
        # 尝试直接作为路径查找
        direct_p = Path(sample_id)
        if direct_p.exists() and direct_p.is_file():
            proteins, meta = comparer.load_proteins_from_file(direct_p)
            return proteins, custom_name or direct_p.stem
        raise HTTPException(status_code=404, detail=f"未找到样本或该注释任务尚未完成: {sample_id}")

    name = custom_name or rec.get("task_name") or sample_id
    work_dir = Path(r"f:\NCBI blast\results\annotations") / sample_id
    proteins = comparer.load_proteins_from_annotation(work_dir)
    return proteins, name


@router.post("/import_external")
async def import_external_file(req: ImportExternalFileRequest):
    """
    快速导入外部已注释的 GenBank / FASTA 文件作为持久化比对样本
    """
    try:
        p = Path(req.file_path)
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=400, detail=f"文件不存在或非有效文件: {req.file_path}")

        comparer = ProteinComparer()
        proteins, meta = comparer.load_proteins_from_file(p)
        if not proteins:
            raise HTTPException(status_code=400, detail=f"未能从该文件中解析出任何有效 CDS 蛋白质特征: {p.name}")

        task_id = f"EXT_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        work_dir = Path(r"f:\NCBI blast\results\annotations") / task_id
        work_dir.mkdir(parents=True, exist_ok=True)

        task_name = req.task_name or p.stem or p.name
        sample_type = req.sample_type or "EXTERNAL"

        # 拷贝源文件并落盘 features.json
        dest_file = work_dir / p.name
        try:
            shutil.copy2(p, dest_file)
        except Exception:
            pass

        features_dict = [
            {
                "id": prot.id,
                "locus_tag": prot.locus_tag,
                "product": prot.product,
                "translation": prot.translation,
                "protein_length_aa": prot.length_aa,
                "start": prot.start,
                "end": prot.end,
                "strand": prot.strand,
                "category": prot.category
            }
            for prot in proteins
        ]
        feat_json = work_dir / "features.json"
        with open(feat_json, "w", encoding="utf-8") as f:
            json.dump(features_dict, f, ensure_ascii=False)

        summary = {
            "total_length": meta.get("total_length", 0),
            "num_contigs": 1,
            "cds_count": len(proteins),
            "annotated_count": len([p for p in proteins if p.category != "other" and p.product != "hypothetical protein"]),
            "hypothetical_count": len([p for p in proteins if p.product == "hypothetical protein"]),
            "gc_content": 0.0,
            "engine": f"External ({meta.get('file_type', '')})",
            "is_external": True
        }

        annotation_db.create_task(
            task_id=task_id,
            task_name=f"[外部导入] {task_name}",
            sample_type=sample_type,
            engine="External"
        )
        annotation_db.mark_completed(
            task_id=task_id,
            summary=summary,
            files={"original": str(dest_file), "features_json": str(feat_json)}
        )

        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "task_name": f"[外部导入] {task_name}",
                "sample_type": sample_type,
                "cds_count": len(proteins),
                "total_length": meta.get("total_length", 0),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入外部文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入外部文件异常: {str(e)}")


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
    """执行两个样本的蛋白质跨样本深度对齐与变异分析 (支持历史任务与外部文件)"""
    try:
        proteins_a, sample_a_name = _load_sample_proteins(req.sample_a_id, req.sample_a_name)
        proteins_b, sample_b_name = _load_sample_proteins(req.sample_b_id, req.sample_b_name)

        if not proteins_a:
            raise HTTPException(status_code=400, detail=f"样本 A ({sample_a_name}) 中未提取到任何有效蛋白质 CDS")
        if not proteins_b:
            raise HTTPException(status_code=400, detail=f"样本 B ({sample_b_name}) 中未提取到任何有效蛋白质 CDS")

        comparer = ProteinComparer()
        result = comparer.compare_two_samples(
            sample_a_name=sample_a_name,
            sample_a_proteins=proteins_a,
            sample_b_name=sample_b_name,
            sample_b_proteins=proteins_b,
            target_category=req.category
        )

        return {"success": True, "data": result.model_dump()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行跨样本蛋白质比对失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"比对执行异常: {str(e)}")


@router.post("/export_csv")
async def export_comparison_csv(req: RunCompareRequest):
    """导出比对报告为 CSV 文件流"""
    try:
        proteins_a, sample_a_name = _load_sample_proteins(req.sample_a_id, req.sample_a_name)
        proteins_b, sample_b_name = _load_sample_proteins(req.sample_b_id, req.sample_b_name)

        comparer = ProteinComparer()
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出 CSV 报告失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
