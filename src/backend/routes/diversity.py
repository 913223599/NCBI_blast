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


@router.get("/latest_task")
async def get_latest_task():
    """获取最近一次运行或已完成的多样性任务状态"""
    task = get_diversity_engine().get_latest_task()
    if not task:
        return {"status": "none"}
    return task


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """查询分析任务进度与 Checkpoint 状态"""
    return get_diversity_engine().get_task_status(task_id)


class DiversityTranslateRequest(BaseModel):
    taxa: List[str]


class DiversityExportExcelRequest(BaseModel):
    groups: Optional[List[Dict[str, Any]]] = None
    translations: Optional[Dict[str, str]] = None


@router.post("/translate")
async def translate_taxa(req: DiversityTranslateRequest):
    """批量翻译物种学名为中文规范译名"""
    try:
        from ...utils.translation.biology_translator import get_global_biology_translator
        translator = get_global_biology_translator()
        valid = [t for t in req.taxa if t and not t.lower().startswith("other") and "噪声" not in t]
        res = translator.translate_batch(valid, category="species")
        for t in req.taxa:
            if t.lower().startswith("other") or "噪声" in t:
                res[t] = "低频测序噪声 (<1% 过滤合集)"
            elif t not in res:
                res[t] = t
        return {"status": "ok", "translations": res}
    except Exception as exc:
        logger.warning(f"物种批量翻译异常: {exc}")
        return {"status": "error", "translations": {t: t for t in req.taxa}, "error": str(exc)}


@router.get("/results/{task_id}")
async def get_task_results(task_id: str):
    """获取全量多样性分析报告，并预加载物种中文翻译"""
    res = get_diversity_engine().get_task_results(task_id)
    if not res:
        raise HTTPException(status_code=404, detail="未找到任务结果或分析尚未完成")
    
    # 自动补全物种中文翻译对照
    overview = res.get("taxa_overview", [])
    if overview:
        taxa_names = [t.get("taxon", "") for t in overview if t.get("taxon")]
        try:
            from ...utils.translation.biology_translator import get_global_biology_translator
            translator = get_global_biology_translator()
            valid = [t for t in taxa_names if not t.lower().startswith("other") and "噪声" not in t]
            trans_map = translator.translate_batch(valid, category="species")
            for t in taxa_names:
                if t.lower().startswith("other") or "噪声" in t:
                    trans_map[t] = "低频测序噪声 (<1% 过滤合集)"
                elif t not in trans_map:
                    trans_map[t] = t
            res["taxa_translations"] = trans_map
        except Exception as exc:
            logger.warning(f"预加载物种中文翻译失败: {exc}")
            res["taxa_translations"] = {}

    return res


@router.post("/export_excel/{task_id}")
async def export_excel_post(task_id: str, req: Optional[DiversityExportExcelRequest] = None):
    """导出包含完整界面数据、分组聚合卡片及下游生信矩阵的多工作表 Excel 综合报告 (POST 模式支持当前分组状态)"""
    return await _handle_export_excel(task_id, req.groups if req else None, req.translations if req else None)


@router.get("/export_excel/{task_id}")
async def export_excel_get(task_id: str):
    """导出标准科研格式的多工作表 Excel 综合多样性分析表 (GET 模式)"""
    return await _handle_export_excel(task_id, None, None)


async def _handle_export_excel(task_id: str, groups: Optional[List[Dict[str, Any]]], translations: Optional[Dict[str, str]]):
    data = get_diversity_engine().get_task_results(task_id)
    if not data:
        raise HTTPException(status_code=404, detail="未找到分析结果")

    engine = get_diversity_engine()
    task_dir = Path(engine.results_root) / task_id
    excel_path = task_dir / f"16S_Diversity_Report_{task_id}.xlsx"

    from ..services.diversity_excel_exporter import build_rich_diversity_excel
    build_rich_diversity_excel(data, excel_path, custom_groups=groups, translations=translations)

    return FileResponse(
        path=str(excel_path),
        filename=f"16S_Diversity_Report_{task_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/tasks")
async def list_all_diversity_tasks():
    """获取所有历史多样性分析任务列表"""
    return get_diversity_engine().list_all_tasks()


@router.delete("/task/{task_id}")
async def delete_diversity_task(task_id: str):
    """删除指定的多样性分析任务"""
    success = get_diversity_engine().delete_task(task_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除任务失败")
    return {"status": "deleted", "task_id": task_id}


@router.delete("/tasks/clear")
async def clear_all_diversity_tasks():
    """清空所有历史多样性分析任务"""
    success = get_diversity_engine().clear_all_tasks()
    if not success:
        raise HTTPException(status_code=500, detail="清空任务失败")
    return {"status": "cleared"}
