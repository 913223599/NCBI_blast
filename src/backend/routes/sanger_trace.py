# -*- coding: utf-8 -*-
"""
Sanger 测序色谱峰图分析与解峰路由接口 (Sanger Trace & Peak Deconvolution API)
"""

import os
import io
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..utils.sanger_deconv_engine import SangerDeconvEngine

logger = logging.getLogger("api_server")
router = APIRouter(prefix="/api/sanger", tags=["Sanger Trace"])


class BatchAnalyzeRequest(BaseModel):
    file_paths: List[str]
    trim_threshold: Optional[int] = 20


class ExportFastaRequest(BaseModel):
    samples: List[Dict[str, Any]]
    mode: Optional[str] = "alleles" # 'alleles' (包含InDel单倍型), 'primary_only', 'iupac'


class CreateBlastJobFromTraceRequest(BaseModel):
    task_name: str
    sequences: List[Dict[str, str]] # [{'id': 'sample_1', 'sequence': 'ACGT...'}]
    program: Optional[str] = "blastn"
    database: Optional[str] = "ncbi_16s"
    evalue: Optional[float] = 0.05
    max_hits: Optional[int] = 50
    threads: Optional[int] = 4
    filter_low_complexity: Optional[bool] = True
    matrix: Optional[str] = "BLOSUM62"
    gap_open: Optional[int] = 11
    gap_extend: Optional[int] = 1


def _natural_sort_key(s: str):
    import re
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


@router.post("/trace/analyze_path")
async def analyze_trace_path(req: BatchAnalyzeRequest):
    """
    通过本地文件路径批量分析 AB1 或 ZIP 压缩包
    """
    if not req.file_paths:
        return {"success": False, "error": "未提供有效的文件路径"}

    results = []
    category_summary = {}

    sorted_paths = sorted(req.file_paths, key=_natural_sort_key)

    for p_str in sorted_paths:
        p = Path(p_str)
        if not p.exists():
            continue

        if p.suffix.lower() == '.zip':
            # 处理 ZIP
            zip_res = SangerDeconvEngine.process_zip_archive(str(p.resolve()))
            if zip_res.get("success"):
                for s in zip_res.get("samples", []):
                    results.append(s)
                    if s.get("success"):
                        cat = s["diagnosis"]["category"]
                        category_summary[cat] = category_summary.get(cat, 0) + 1
            else:
                results.append({
                    "success": False,
                    "filename": p.name,
                    "error": zip_res.get("error", "ZIP 解析失败")
                })
        elif p.suffix.lower() in ('.ab1', '.abi'):
            # 处理单文件 AB1
            try:
                with open(p, 'rb') as f:
                    ab1_bytes = f.read()
                res = SangerDeconvEngine.parse_single_ab1_bytes(
                    ab1_bytes,
                    filename=p.name,
                    trim_q=req.trim_threshold or 20
                )
                results.append(res)
                if res.get("success"):
                    cat = res["diagnosis"]["category"]
                    category_summary[cat] = category_summary.get(cat, 0) + 1
            except Exception as e:
                results.append({
                    "success": False,
                    "filename": p.name,
                    "error": str(e)
                })

    results.sort(key=lambda r: _natural_sort_key(r.get("sample_id") or r.get("filename") or ""))

    return {
        "success": True,
        "total_samples": len(results),
        "success_count": sum(1 for r in results if r.get("success")),
        "categories": category_summary,
        "samples": results
    }


@router.post("/trace/upload")
async def upload_and_analyze(
    file: UploadFile = File(...),
    trim_threshold: int = Form(20)
):
    """
    通过 HTTP 上传 AB1 文件或 ZIP 压缩包并即时解析
    """
    try:
        content = await file.read()
        fname = file.filename or "uploaded.ab1"
        ext = Path(fname).suffix.lower()

        if ext == '.zip':
            # 临时保存后解析
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                res = SangerDeconvEngine.process_zip_archive(tmp_path)
                return res
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except:
                        pass
        elif ext in ('.ab1', '.abi'):
            res = SangerDeconvEngine.parse_single_ab1_bytes(content, filename=fname, trim_q=trim_threshold)
            return {
                "success": True,
                "total_samples": 1,
                "success_count": 1 if res.get("success") else 0,
                "categories": {res["diagnosis"]["category"]: 1} if res.get("success") else {},
                "samples": [res]
            }
        else:
            return {"success": False, "error": f"不支持的文件类型: {ext} (仅支持 .ab1, .abi, .zip)"}
    except Exception as exc:
        logger.error(f"上传分析失败: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.post("/trace/export_fasta")
async def export_fasta(req: ExportFastaRequest):
    """
    将选中的解峰序列生成标准 FASTA 文本
    """
    fasta_lines = []
    for sample in req.samples:
        if not sample.get("success"):
            continue
        sample_id = sample.get("sample_id", "sample")
        seqs = sample.get("sequences", {})
        alleles = seqs.get("alleles", [])

        if req.mode == "primary_only":
            p_seq = seqs.get("primary_clean") or ""
            if p_seq:
                fasta_lines.append(f">{sample_id}_Primary_Clean\n{p_seq}")
        elif req.mode == "iupac":
            i_seq = seqs.get("iupac_consensus") or ""
            if i_seq:
                fasta_lines.append(f">{sample_id}_IUPAC_Consensus\n{i_seq}")
        else:
            # 默认导出所有 Alleles (如单倍型 A、单倍型 B 等)
            for a in alleles:
                a_id = a.get("allele_id", "Allele")
                a_seq = a.get("sequence", "")
                if a_seq:
                    fasta_lines.append(f">{sample_id}_{a_id}\n{a_seq}")

    fasta_content = "\n".join(fasta_lines)
    return {
        "success": True,
        "fasta_text": fasta_content,
        "count": len(fasta_lines) // 2
    }


@router.post("/trace/send_to_blast")
async def send_trace_to_blast(req: CreateBlastJobFromTraceRequest):
    """
    将解峰后的序列直接提交到 BLAST 管理器创建比对任务
    """
    from ...blast.manager import get_blast_manager
    try:
        fasta_entries = []
        for s in req.sequences:
            sid = s.get("id", "Unknown")
            seq = s.get("sequence", "")
            if seq:
                fasta_entries.append(f">{sid}\n{seq}")

        if not fasta_entries:
            return {"status": "error", "error": "没有可提交的比对序列"}

        combined_fasta = "\n".join(fasta_entries)
        task_id = get_blast_manager().create_task({
            "query": combined_fasta,
            "program": req.program or "blastn",
            "database": req.database or "ncbi_16s",
            "task_name": req.task_name or f"Deconv_{len(fasta_entries)}_Seqs",
            "evalue": req.evalue if req.evalue is not None else 0.05,
            "max_hits": req.max_hits or 50,
            "threads": req.threads or 4,
            "filter_low_complexity": req.filter_low_complexity if req.filter_low_complexity is not None else True,
            "matrix": req.matrix or "BLOSUM62",
            "gap_open": req.gap_open if req.gap_open is not None else 11,
            "gap_extend": req.gap_extend if req.gap_extend is not None else 1
        })

        return {
            "status": "started",
            "task_id": task_id,
            "sequence_count": len(fasta_entries),
            "database": req.database or "ncbi_16s"
        }
    except Exception as exc:
        logger.error(f"创建 BLAST 任务失败: {exc}", exc_info=True)
        return {"status": "error", "error": str(exc)}
