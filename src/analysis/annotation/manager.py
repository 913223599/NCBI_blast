# -*- coding: utf-8 -*-
"""
功能注释单例管理器 (AnnotationManager)
"""
import os
import shutil
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from .types import AnnotationRunRequest
from .db import annotation_db
from .pipeline import AnnotationPipeline

logger = logging.getLogger("analysis.annotation.manager")


class AnnotationManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AnnotationManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        if self._initialized:
            return
        self.root_dir = Path(root_dir) if root_dir else Path(os.getcwd())
        self.results_dir = self.root_dir / "results" / "annotations"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._active_pipelines: Dict[str, AnnotationPipeline] = {}
        self._initialized = True

    def inspect_fasta(self, fasta_path: Optional[str] = None, fasta_content: Optional[str] = None) -> Dict[str, Any]:
        """
        快速预检查并解析 FASTA 序列元信息（Contig ID, 长度, GC% 等）
        用于前端展示序列选择列表
        """
        from Bio import SeqIO
        import io

        records = []
        if fasta_content and fasta_content.strip():
            raw_text = fasta_content.strip()
            if not raw_text.startswith(">"):
                raw_text = f">Sequence_1\n{raw_text}"
            records = list(SeqIO.parse(io.StringIO(raw_text), "fasta"))
        elif fasta_path and Path(fasta_path).exists():
            with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
                records = list(SeqIO.parse(f, "fasta"))

        if not records:
            return {
                "success": False,
                "error": "未检测到有效的 FASTA 序列内容或文件不存在",
                "num_contigs": 0,
                "total_length": 0,
                "gc_content": 0.0,
                "contigs": []
            }

        contigs = []
        total_len = 0
        total_gc_bases = 0

        for r in records:
            seq_str = str(r.seq).upper()
            seq_len = len(seq_str)
            total_len += seq_len
            gc_count = seq_str.count("G") + seq_str.count("C")
            total_gc_bases += gc_count
            gc_pct = round((gc_count / seq_len * 100.0), 2) if seq_len > 0 else 0.0
            
            desc = r.description
            if desc.startswith(r.id):
                desc = desc[len(r.id):].strip()

            contigs.append({
                "id": r.id,
                "description": desc,
                "length_bp": seq_len,
                "gc_content": gc_pct,
                "selected": True
            })

        # 按长度降序排列
        contigs.sort(key=lambda x: x["length_bp"], reverse=True)
        overall_gc = round((total_gc_bases / total_len * 100.0), 2) if total_len > 0 else 0.0

        return {
            "success": True,
            "num_contigs": len(contigs),
            "total_length": total_len,
            "gc_content": overall_gc,
            "contigs": contigs
        }

    async def submit_task(self, req: AnnotationRunRequest) -> Dict[str, Any]:
        """提交并启动异步注释任务"""
        task_id = f"ANNO_{os.urandom(4).hex().upper()}"
        task_name = req.task_name or f"Annotation_{task_id}"
        
        # 1. 注册到数据库
        annotation_db.create_task(
            task_id=task_id,
            task_name=task_name,
            sample_type=req.sample_type,
            engine=req.engine
        )

        task_work_dir = self.results_dir / task_id
        pipeline = AnnotationPipeline(task_id=task_id, work_dir=task_work_dir)
        self._active_pipelines[task_id] = pipeline

        # 2. 启动后台异步协程
        asyncio.create_task(self._run_task_wrapper(pipeline, req, task_id))

        return {
            "success": True,
            "task_id": task_id,
            "task_name": task_name,
            "status": "pending",
            "message": "注释任务已成功创建并启动"
        }

    async def _run_task_wrapper(self, pipeline: AnnotationPipeline, req: AnnotationRunRequest, task_id: str):
        try:
            await pipeline.execute(req)
        except Exception as e:
            logger.error(f"Task {task_id} execution failed in background: {e}")
        finally:
            if task_id in self._active_pipelines:
                del self._active_pipelines[task_id]

    def cancel_task(self, task_id: str) -> bool:
        """取消正在运行的任务"""
        if task_id in self._active_pipelines:
            self._active_pipelines[task_id].cancel()
            annotation_db.mark_cancelled(task_id)
            return True
        return False

    def list_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取注释历史列表"""
        return annotation_db.list_tasks(limit=limit)

    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取指定任务的详细结果数据"""
        task = annotation_db.get_task(task_id)
        if not task:
            return None

        task_work_dir = self.results_dir / task_id
        features_json_file = task_work_dir / "features.json"
        
        features = []
        if features_json_file.exists():
            try:
                with open(features_json_file, "r", encoding="utf-8") as f:
                    features = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read features.json for {task_id}: {e}")

        # 读取 GBK 文本摘要或完整内容
        gbk_file = task_work_dir / f"{task_id}.gbk"
        if not gbk_file.exists():
            # 查找任意 .gbk
            gbk_candidates = list(task_work_dir.glob("*.gbk")) + list(task_work_dir.glob("*/*.gbk"))
            if gbk_candidates:
                gbk_file = gbk_candidates[0]

        gbk_content = ""
        if gbk_file.exists() and gbk_file.stat().st_size < 50 * 1024 * 1024:  # 小于 50MB 可直接载入内存传递
            try:
                with open(gbk_file, "r", encoding="utf-8", errors="ignore") as f:
                    gbk_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read GBK file: {e}")

        task["features"] = features
        task["feature_count"] = len(features)
        task["gbk_content"] = gbk_content
        task["work_dir"] = str(task_work_dir.resolve())
        return task

    def get_task_file_path(self, task_id: str, file_type: str) -> Optional[Path]:
        """获取指定任务的产物物理文件路径"""
        task_work_dir = self.results_dir / task_id
        if not task_work_dir.exists():
            return None

        # 根据扩展名查找
        ext_map = {
            "gbk": "*.gbk",
            "gff": "*.gff",
            "faa": "*.faa",
            "ffn": "*.ffn",
            "tsv": "*.tsv",
            "json": "summary.json"
        }
        pattern = ext_map.get(file_type.lower(), f"*.{file_type.lower()}")
        matches = list(task_work_dir.glob(pattern)) + list(task_work_dir.glob(f"*/{pattern}"))
        if matches:
            return matches[0]
        return None

    def delete_task(self, task_id: str) -> bool:
        """彻底删除任务（含物理结果目录与数据库记录）"""
        # 1. 取消正在运行的任务
        if task_id in self._active_pipelines:
            self._active_pipelines[task_id].cancel()
            del self._active_pipelines[task_id]

        # 2. 清理数据库
        annotation_db.delete_task(task_id)

        # 3. 清理物理目录
        task_work_dir = self.results_dir / task_id
        if task_work_dir.exists():
            try:
                shutil.rmtree(task_work_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"Failed to delete directory {task_work_dir}: {e}")
        return True


def get_annotation_manager() -> AnnotationManager:
    return AnnotationManager()
