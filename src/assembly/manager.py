# -*- coding: utf-8 -*-
"""
AssemblyManager - 纯净版基因组组装管理器
全面收敛于 NGCS (Neural Genome Coordinate System) 组装引擎，提供高保真基因组拼接与指标解析服务。
"""

import os
import time
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from .core.base import PipelineContext
from .steps.assembler import AssemblerStep
from .utils.file_handler import AssemblyFileHandler
from src.backend.broadcaster import broadcaster
from src.backend.utils.assembly_db import assembly_db


class AssemblyManager:
    """
    轻量级高效基因组组装管理器
    专注于 NGCS 核心组装流程调度与任务生命周期管理
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logger = logging.getLogger("Assembly.Manager")
        self.results_base = project_root / "results" / "assembly"
        self.results_base.mkdir(parents=True, exist_ok=True)
        self.file_handler = AssemblyFileHandler()
        
        # 活跃任务追踪 (用于强制停止)
        self.active_steps: Dict[str, Any] = {}

    def stop_task(self, task_id: str) -> Optional[str]:
        """强制停止指定任务"""
        target_id = task_id
        if task_id == "current":
            running_tasks = [t for t in assembly_db.get_incomplete_tasks() if t.get('status') == 'running']
            if running_tasks:
                target_id = running_tasks[-1]['id']
            elif self.active_steps:
                target_id = list(self.active_steps.keys())[-1]
            else:
                self.logger.warning("尝试停止 'current' 任务，但无运行中的任务。")
                return None

        # 1. 标记数据库状态为 ABORTED
        assembly_db.update_task_progress(target_id, "ABORTED", 0, "aborted")
        
        # 2. 终止本地进程
        if target_id in self.active_steps:
            step = self.active_steps[target_id]
            self.logger.warning(f"正在强制停止组装任务: {target_id}")
            if hasattr(step, 'context'):
                step.context.is_aborted = True
            if hasattr(step, 'runner'):
                step.runner.terminate()
            self.active_steps.pop(target_id, None)

        return target_id

    async def run_pipeline(self, 
                           task_id: Optional[str], 
                           sample_type: str,
                           r1_input: str, 
                           r2_input: Optional[str] = None, 
                           config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        NGCS 基因组拼接流水线主调度入口
        """
        config = config or {}
        task_id = task_id or f"Assembly_{int(time.time())}"
        task_dir = self.results_base / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"启动 NGCS 基因组组装任务: {task_id} | 样本类型: {sample_type}")

        # 1. 确保数据库初始任务记录存在
        if not assembly_db.get_task(task_id):
            sample_name = config.get("name") or task_id
            tech_val = config.get("tech") or "NGS"
            assembly_db.create_task(task_id, sample_name, task_id, sample_type, tech_val, config)

        # 2. 检查输入数据完整性
        r1_path = Path(r1_input) if r1_input else None
        r2_path = Path(r2_input) if r2_input else None

        if not r1_path or not r1_path.exists():
            err_msg = f"输入测序数据 R1 不存在: {r1_input}"
            self.logger.error(err_msg)
            assembly_db.update_task_progress(task_id, "ERROR", 0, "failed", error=err_msg)
            return {"status": "error", "message": err_msg}

        # 2. 初始化上下文
        ctx = PipelineContext(task_id, task_dir, config)
        ctx.update("r1", r1_path)
        if r2_path and r2_path.exists():
            ctx.update("r2", r2_path)

        # 3. 实例化核心组装器
        assembler = AssemblerStep(ctx)
        self.active_steps[task_id] = assembler

        # 单调递增保护锁：记录当前任务已报告的最大进度，防止回退
        current_max_progress = 0.0

        # 进度与状态广播回调 (线程安全派发，单调递增保护)
        def on_step_progress(progress_val: float, desc_text: Optional[str] = None):
            nonlocal current_max_progress
            desc = desc_text or "计算中..."
            safe_progress = max(current_max_progress, float(progress_val))
            current_max_progress = safe_progress

            self.logger.info(f"[{task_id}] 组装进度: {safe_progress:.1f}% - {desc}")
            assembly_db.update_task_progress(task_id, "NGCS组装", safe_progress, "running")
            # 广播到前端 WebSocket (线程安全，支持从工作线程直接广播)
            broadcaster.broadcast_sync("assembly_progress", {
                "task_id": task_id,
                "step": desc,
                "progress": safe_progress,
                "status": "running"
            })

        # 实时底层输出日志广播回调
        def on_step_log(log_line: str):
            broadcaster.broadcast_sync("assembly_log", {
                "task_id": task_id,
                "line": log_line,
                "timestamp": time.time()
            })

        assembler.on_progress = on_step_progress
        assembler.on_log = on_step_log

        try:
            assembly_db.update_task_progress(task_id, "NGCS组装", 5, "running")
            success = await assembler.execute()

            if getattr(ctx, "is_aborted", False):
                self.logger.warning(f"任务 {task_id} 已被用户中止")
                assembly_db.update_task_progress(task_id, "ABORTED", 0, "aborted")
                return {"status": "aborted", "task_id": task_id}

            if success:
                asm_fasta = ctx.get("assembly_fasta")
                stats = ctx.get("assembly_stats") or {}
                self.logger.info(f"任务 {task_id} 组装成功完成! 产物: {asm_fasta} | 指标: {stats}")

                assembly_db.update_task_progress(task_id, "COMPLETED", 100, "completed")
                assembly_db.update_task_metrics(
                    task_id,
                    total_length=stats.get("total_length", 0),
                    contig_count=stats.get("contigs", 0),
                    n50=stats.get("n50", 0),
                    gc_content=stats.get("gc_percent", 0.0),
                    is_circular=stats.get("is_circular", False),
                    avg_depth=stats.get("avg_depth", 0.0),
                    max_contig_length=stats.get("max_contig_length", 0)
                )

                # 广播成功事件
                await broadcaster.broadcast("assembly_progress", {
                    "task_id": task_id,
                    "step": "组装完成",
                    "progress": 100,
                    "status": "success",
                    "stats": stats,
                    "fasta_path": str(asm_fasta) if asm_fasta else None
                })

                return {
                    "status": "success",
                    "task_id": task_id,
                    "stats": stats,
                    "fasta_path": str(asm_fasta) if asm_fasta else None
                }
            else:
                err_msg = assembler.last_error or "NGCS 组装未产生有效产物"
                self.logger.error(f"任务 {task_id} 组装失败: {err_msg}")
                assembly_db.update_task_progress(task_id, "FAILED", 0, "failed", error=err_msg)
                
                await broadcaster.broadcast("assembly_progress", {
                    "task_id": task_id,
                    "step": f"组装失败: {err_msg}",
                    "progress": 0,
                    "status": "failed",
                    "error": err_msg
                })

                return {"status": "error", "message": err_msg, "task_id": task_id}

        except Exception as e:
            self.logger.error(f"任务 {task_id} 执行异常: {e}", exc_info=True)
            assembly_db.update_task_progress(task_id, "ERROR", 0, "failed", error=str(e))
            return {"status": "error", "message": str(e), "task_id": task_id}

        finally:
            self.active_steps.pop(task_id, None)
