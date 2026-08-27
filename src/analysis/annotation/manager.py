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
from .fuser import AnnotationFuser
from .queue import annotation_queue

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

    async def initialize_queue_worker(self):
        """初始化启动队列消费工作者"""
        await annotation_queue.start_workers(self.execute_pipeline_task)

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
        """提交注释任务至持久化调度队列"""
        task_id = f"ANNO_{os.urandom(4).hex().upper()}"
        task_name = req.task_name or f"Annotation_{task_id}"
        
        # 1. 注册到数据库，标记为 queued 状态
        annotation_db.create_task(
            task_id=task_id,
            task_name=task_name,
            sample_type=req.sample_type,
            engine=req.engine,
            status="queued"
        )

        # 2. 推送至调度队列
        payload = {
            "task_id": task_id,
            "task_name": task_name,
            "sample_type": req.sample_type,
            "engine": req.engine,
            "req": req
        }
        enqueue_res = await annotation_queue.add_task(payload)

        return {
            "success": True,
            "task_id": task_id,
            "task_name": task_name,
            "position": enqueue_res.get("position", 1),
            "status": "queued",
            "message": "注释任务已成功加入等待队列"
        }

    async def execute_pipeline_task(self, payload: Dict[str, Any]):
        """执行具体的流水线任务（由 AnnotationQueue 串行/受控派发）"""
        task_id = payload.get("task_id")
        if not task_id or not isinstance(task_id, str):
            logger.error(f"[MANAGER] Invalid task payload, missing task_id: {payload}")
            return

        raw_req = payload.get("req")
        if isinstance(raw_req, dict):
            req = AnnotationRunRequest(**raw_req)
        elif isinstance(raw_req, AnnotationRunRequest):
            req = raw_req
        else:
            logger.error(f"[MANAGER] Invalid task request for {task_id}: {type(raw_req)}")
            return

        task_work_dir = self.results_dir / task_id
        pipeline = AnnotationPipeline(task_id=task_id, work_dir=task_work_dir)
        self._active_pipelines[task_id] = pipeline

        try:
            await pipeline.execute(req)
        finally:
            if task_id in self._active_pipelines:
                del self._active_pipelines[task_id]

    def cancel_task(self, task_id: str) -> bool:
        """取消排队中或正在运行的任务"""
        # 1. 尝试从等待队列中移出
        if annotation_queue.remove_task_from_queue(task_id):
            return True

        # 2. 若正在执行，发送取消指令
        if task_id in self._active_pipelines:
            self._active_pipelines[task_id].cancel()
            annotation_db.mark_cancelled(task_id)
            return True

        return False

    async def get_queue_status(self) -> Dict[str, Any]:
        """获取当前排队与运行状态快照"""
        return await annotation_queue.get_queue_status()

    def reorder_queue(self, task_ids: List[str]):
        """调整等待队列排队顺序"""
        annotation_queue.reorder_queue(task_ids)

    def list_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取注释历史列表并自动纠正完成态任务"""
        tasks = annotation_db.list_tasks(limit=limit)
        incomplete = annotation_db.get_incomplete_tasks()
        waiting_ids = [t["task_id"] for t in incomplete if t["status"] == "queued"]
        
        for t in tasks:
            if t.get("status") == "running" and t.get("progress", 0) >= 100:
                t["status"] = "completed"
                try:
                    annotation_db.mark_completed(
                        task_id=t["task_id"],
                        summary=t.get("summary") or {},
                        files=t.get("files") or {}
                    )
                except Exception:
                    pass
            elif t.get("status") == "queued":
                # 计算排队位置
                if t["task_id"] in waiting_ids:
                    t["position"] = waiting_ids.index(t["task_id"]) + 1
                else:
                    t["position"] = 1
        return tasks

    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取指定任务的详细结果数据"""
        task = annotation_db.get_task(task_id)
        if not task:
            return None

        # 性能极速优化：如果任务处于排队或等待中，无需进行任何磁盘扫描，直接秒级返回
        if task.get("status") in ("queued", "pending"):
            waiting_ids = [p.get("task_id") for p in annotation_queue._queue]
            if task_id in waiting_ids:
                task["position"] = waiting_ids.index(task_id) + 1
            else:
                task["position"] = 1
            task["features"] = []
            task["feature_count"] = 0
            task["gbk_content"] = ""
            task["work_dir"] = str((self.results_dir / task_id).resolve())
            return task

        task_work_dir = self.results_dir / task_id
        features_json_file = task_work_dir / "features.json"
        
        features = []
        if features_json_file.exists():
            try:
                with open(features_json_file, "r", encoding="utf-8") as f:
                    features = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read features.json for {task_id}: {e}")

        # 深度融合生物安全审计证据与 Anti-CRISPR 功能赋名
        safety_audit = task.get("safety_audit")
        if not safety_audit:
            audit_json_file = task_work_dir / "safety_audit.json"
            if audit_json_file.exists():
                try:
                    with open(audit_json_file, "r", encoding="utf-8") as f:
                        safety_audit = json.load(f)
                        task["safety_audit"] = safety_audit
                except Exception:
                    pass

        if features and "summary" in task and isinstance(task["summary"], dict):
            ann_cnt = sum(1 for f in features if f.get("feature_type") == "CDS" and not AnnotationFuser.is_unannotated(f.get("product")))
            hypo_cnt = sum(1 for f in features if f.get("feature_type") == "CDS" and AnnotationFuser.is_unannotated(f.get("product")))
            task["summary"]["annotated_count"] = ann_cnt
            task["summary"]["hypothetical_count"] = hypo_cnt
            
            cat_dist = {}
            engine_contrib = {}
            for f in features:
                if f.get("feature_type") == "CDS":
                    c = f.get("category") or "Other Functional"
                    cat_dist[c] = cat_dist.get(c, 0) + 1
                    eng = f.get("source_engine") or "Pharokka"
                    engine_contrib[eng] = engine_contrib.get(eng, 0) + 1
            task["summary"]["category_distribution"] = cat_dist
            task["summary"]["engine_contributions"] = engine_contrib

            # 同步持久化回写数据库
            try:
                annotation_db.mark_completed(
                    task_id=task_id,
                    summary=task["summary"],
                    files=task.get("files") or {},
                    safety_audit=safety_audit
                )
            except Exception:
                pass

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

        # 计算排队位置
        if task.get("status") in ("queued", "pending"):
            waiting_ids = [p.get("task_id") for p in annotation_queue._queue]
            if task_id in waiting_ids:
                task["position"] = waiting_ids.index(task_id) + 1
            else:
                task["position"] = 1

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
