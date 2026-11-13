# -*- coding: utf-8 -*-
"""
前噬菌体与噬菌体智能发现工作台管理器

负责任务提交、输入验证与持久化、异步调度执行、V4.2 模型与蛋白门控调度、
显存生命周期控制、扫描结果与区域微基因组 GBK 检索以及安全删除。
"""
import asyncio
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool

from ...backend.broadcaster import broadcaster
from ...phage_discovery.inference.scanner import GenomeScanner
from .db import phage_discovery_db
from .exporter import (
    build_contig_overlay_gbk,
    export_scan_artifacts,
    filter_selected_contigs,
    inspect_sequences,
    load_sequences_with_annotations,
    load_sequences_with_meta,
)
from .model_registry import (
    PROJECT_ROOT,
    _resolve_user_path,
    detect_compute_environment,
    discover_available_models,
    get_safe_workers,
    resolve_model_dir,
    resolve_protein_gate_resources,
    save_phage_discovery_config,
)
from .queue import phage_discovery_queue, release_gpu_memory
from .types import PhageScanRunRequest

logger = logging.getLogger("PhageDiscoveryManager")


class PhageDiscoveryManager:
    """单例管理前噬菌体发现工作台全生命周期。"""

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = Path(project_root)
        self.results_root = self.project_root / "results" / "phage_discovery"
        self.results_root.mkdir(parents=True, exist_ok=True)
        self.db = phage_discovery_db
        self.queue = phage_discovery_queue
        self.queue.set_executor(self.execute_pipeline_task)

    async def initialize_queue_worker(self) -> None:
        await self.queue.start()

    def get_capabilities(self) -> Dict[str, Any]:
        """返回当前环境可用的 V4.2 模型、计算设备及可选蛋白门控库配置状态。"""
        models = discover_available_models(self.project_root)
        env = detect_compute_environment()
        gate = resolve_protein_gate_resources(project_root=self.project_root)
        return {
            "models": models,
            "compute": env,
            "protein_gate": gate,
            "has_model": len(models) > 0,
        }

    def update_config(
        self,
        *,
        models_root: Optional[str] = None,
        default_model_dir: Optional[str] = None,
        blast_db: Optional[str] = None,
    ) -> Dict[str, Any]:
        updated = save_phage_discovery_config(
            models_root=models_root,
            default_model_dir=default_model_dir,
            blast_db=blast_db,
            project_root=self.project_root,
        )
        return {
            "config": updated,
            "capabilities": self.get_capabilities(),
        }

    def inspect_input(
        self,
        fasta_path: Optional[str] = None,
        fasta_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        return inspect_sequences(
            fasta_path=fasta_path,
            fasta_content=fasta_content,
            project_root=self.project_root,
        )

    async def submit_task(self, req: PhageScanRunRequest) -> Dict[str, Any]:
        if not req.fasta_path and not (req.fasta_content and req.fasta_content.strip()):
            raise ValueError("必须提供基因组文件路径或粘贴的 FASTA/GenBank 序列文本")

        # 提前解析确认存在可用的 V4.2 模型
        model_info = resolve_model_dir(
            model_id=req.model_id,
            custom_model_dir=req.custom_model_dir,
            project_root=self.project_root,
        )

        # 提前校检蛋白门控依赖（仅当用户开启时要求）
        gate_resources: Dict[str, Any] = {}
        if req.apply_protein_gate:
            gate_resources = resolve_protein_gate_resources(
                custom_blast_db=req.blast_db,
                project_root=self.project_root,
            )
            if not gate_resources.get("ready"):
                raise ValueError(
                    "已勾选 BLASTp 标志蛋白门控，但未检测到可用的 blastp 可执行文件或噬菌体蛋白参考库。"
                    "请配置蛋白库路径或关闭蛋白门控后重跑。"
                )

        env = detect_compute_environment()
        requested_dev = (req.device or "auto").lower()
        if requested_dev == "auto":
            resolved_dev = env["default_device"]
        elif requested_dev == "cuda" and not env["cuda_available"]:
            resolved_dev = "cpu"
        elif requested_dev in {"cuda", "cpu"}:
            resolved_dev = requested_dev
        else:
            resolved_dev = env["default_device"]

        ts_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        task_id = f"phage_{ts_id}"
        out_dir = self.results_root / task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 若为内联文本输入，即刻写入磁盘快照，严禁长期滞留大字符串于内存或数据库
        staged_fasta_path: Optional[str] = req.fasta_path
        if req.fasta_content and req.fasta_content.strip():
            raw_text = req.fasta_content.strip()
            ext = ".gbk" if raw_text.startswith("LOCUS") else ".fasta"
            staged_file = out_dir / f"input_sequences{ext}"
            staged_file.write_text(raw_text + "\n", encoding="utf-8")
            staged_fasta_path = str(staged_file)

        self.db.create_task(
            task_id=task_id,
            task_name=req.task_name or "PhageDiscovery_Task",
            model_id=str(model_info["model_id"]),
            model_version="V4.2",
            device=resolved_dev,
            apply_protein_gate=req.apply_protein_gate,
            status="queued",
        )

        context = {
            "task_dir": str(out_dir),
            "staged_fasta_path": staged_fasta_path,
            "model_info": model_info,
            "resolved_device": resolved_dev,
            "workers": get_safe_workers(req.workers),
            "gate_resources": gate_resources,
            "device_fallback": requested_dev == "cuda" and not env["cuda_available"],
        }
        await self.queue.enqueue(task_id, req, context)

        return {
            "task_id": task_id,
            "status": "queued",
            "model": model_info,
            "device": resolved_dev,
            "message": "前噬菌体扫描任务已加入调度队列",
        }

    def _emit_sync(
        self,
        loop: asyncio.AbstractEventLoop,
        event: str,
        payload: Dict[str, Any],
    ) -> None:
        try:
            asyncio.run_coroutine_threadsafe(broadcaster.broadcast(event, payload), loop)
        except Exception:
            pass

    async def execute_pipeline_task(
        self,
        task_id: str,
        req: PhageScanRunRequest,
        context: Dict[str, Any],
    ) -> None:
        loop = asyncio.get_running_loop()

        def emit_progress(pct: int, msg: str, log_line: Optional[str] = None, level: str = "info") -> None:
            self.db.update_progress(task_id, pct, msg, status="running")
            self._emit_sync(
                loop,
                "phage_discovery_progress",
                {"task_id": task_id, "progress": pct, "message": msg, "status": "running"},
            )
            if log_line:
                self._emit_sync(
                    loop,
                    "phage_discovery_log",
                    {"task_id": task_id, "line": log_line, "level": level},
                )

        def run_blocking() -> Dict[str, Any]:
            t0 = time.perf_counter()
            out_dir = Path(context["task_dir"])
            model_info: Dict[str, Any] = context["model_info"]
            resolved_dev: str = context["resolved_device"]
            workers: int = int(context["workers"])
            gate_res: Dict[str, Any] = context.get("gate_resources") or {}

            if context.get("device_fallback"):
                emit_progress(
                    5,
                    "未检测到 CUDA，已安全切换至 CPU 模式执行",
                    "[WARN] 宿主未检测到可用 CUDA GPU，已自动回落为 CPU 推理",
                    level="warning",
                )

            if self.queue.is_cancelled(task_id):
                raise InterruptedError("任务在启动前被用户取消")

            emit_progress(
                8,
                "正在解析输入基因组并抽取目标 Contig...",
                f"[STEP 1/5] 加载输入序列 (workers={workers}, device={resolved_dev})",
            )
            all_seqs, _, base_features_by_contig, source_format = load_sequences_with_annotations(
                fasta_path=context.get("staged_fasta_path"),
                fasta_content=None,
                project_root=self.project_root,
            )
            target_seqs = filter_selected_contigs(all_seqs, req.selected_contigs)
            target_base_features = {
                cid: list(base_features_by_contig.get(cid, []))
                for cid in target_seqs
            }
            total_bp = sum(len(s) for s in target_seqs.values())
            emit_progress(
                15,
                f"输入解析完成 ({source_format.upper()}): {len(target_seqs)} 条 Contig ({total_bp:,} bp)",
                f"[INFO] 格式={source_format}, 纳入扫描 Contig 数={len(target_seqs)}, 总碱基={total_bp:,} bp",
            )

            if self.queue.is_cancelled(task_id):
                raise InterruptedError("任务已被用户中止")

            dec = model_info.get("decoder_defaults") or {}
            seed_thr = float(req.seed_threshold if req.seed_threshold is not None else dec.get("seed_threshold", 0.95))
            ext_thr = float(req.extend_threshold if req.extend_threshold is not None else dec.get("extend_threshold", 0.30))
            sub_thr = float(req.sub_threshold if req.sub_threshold is not None else dec.get("sub_threshold", 0.45))
            merge_gap = req.merge_gap_bp
            min_len = req.min_region_bp

            blast_db_path: Optional[Path] = None
            blastp_bin = "blastp"
            if req.apply_protein_gate and gate_res.get("ready"):
                blast_db_path = Path(str(gate_res["blast_db"]))
                blastp_bin = str(gate_res.get("blastp_bin") or "blastp")

            emit_progress(
                22,
                "正在加载 Student V4.2 主干网络与 SubBinRefiner 边界精修权重...",
                f"[STEP 2/5] 加载模型目录: {model_info['path']} (V4.2, SubBinRefiner={model_info['has_subbin_refiner']})",
            )

            scanner: Optional[GenomeScanner] = None
            try:
                scanner = GenomeScanner.from_model_dir(
                    Path(str(model_info["path"])),
                    blast_db=blast_db_path,
                    blastp_bin=blastp_bin,
                    workers=workers,
                    device=resolved_dev,
                    seed_threshold=seed_thr,
                    extend_threshold=ext_thr,
                    sub_threshold=sub_thr,
                    merge_gap_bp=merge_gap,
                    min_region_bp=min_len,
                )

                if self.queue.is_cancelled(task_id):
                    raise InterruptedError("任务已被用户中止")

                emit_progress(
                    38,
                    f"正在执行滑动窗口与 200bp SubBin 精细边界分割 ({total_bp:,} bp)...",
                    f"[STEP 3/5] 启动 V4.2 扫描解码 (seed={seed_thr:.2f}, extend={ext_thr:.2f}, sub={sub_thr:.2f})",
                )
                scan_result = scanner.scan_sequences(
                    target_seqs,
                    apply_protein_gate=req.apply_protein_gate,
                    collect_profiles=True,
                    profile_flank_bp=2000,
                )

                if self.queue.is_cancelled(task_id):
                    raise InterruptedError("任务已被用户中止")

                emit_progress(
                    78,
                    f"扫描完成，发现 {len(scan_result.verified_regions if req.apply_protein_gate else scan_result.raw_regions)} 个候选区，正在导出 GFF3/GBK/FASTA...",
                    f"[STEP 4/5] 窗口数={scan_result.total_windows}, 原始命中={len(scan_result.raw_regions)}, 耗时={scan_result.timings_sec.get('total_sec', 0):.2f}s",
                )

                exported = export_scan_artifacts(
                    task_id=task_id,
                    task_name=req.task_name or "PhageDiscovery_Task",
                    model_info=model_info,
                    device_used=resolved_dev,
                    apply_protein_gate=req.apply_protein_gate,
                    sequences=target_seqs,
                    scan_result=scan_result,
                    out_dir=out_dir,
                    flank_bp=3000,
                    base_features_by_contig=target_base_features,
                    source_format=source_format,
                    input_source_path=context.get("staged_fasta_path"),
                    project_root=self.project_root,
                )

                elapsed = round(time.perf_counter() - t0, 2)
                emit_progress(
                    96,
                    "结果文件已全部落盘，正在释放显存并刷新工作台视图...",
                    f"[STEP 5/5] 全部产物已保存至 {exported['files'].get('folder', '')} (总耗时 {elapsed}s)",
                )
                return exported
            finally:
                if scanner is not None:
                    del scanner
                release_gpu_memory()

        try:
            exported = await run_in_threadpool(run_blocking)
            self.db.mark_completed(
                task_id=task_id,
                summary=exported["summary"],
                files=exported["files"],
                result_path=exported["result_path"],
                model_version="V4.2",
                device_used=context["resolved_device"],
            )
            await broadcaster.broadcast(
                "phage_discovery_progress",
                {"task_id": task_id, "progress": 100, "message": "前噬菌体扫描已完成", "status": "completed"},
            )
            await broadcaster.broadcast(
                "phage_discovery_done",
                {"task_id": task_id, "summary": exported["summary"]},
            )
        except InterruptedError as cancel_exc:
            self.db.mark_cancelled(task_id)
            await broadcaster.broadcast(
                "phage_discovery_error",
                {"task_id": task_id, "error": str(cancel_exc), "status": "cancelled"},
            )
        except Exception as exc:
            logger.exception("前噬菌体扫描任务失败 (%s): %s", task_id, exc)
            self.db.mark_failed(task_id, str(exc))
            await broadcaster.broadcast(
                "phage_discovery_error",
                {"task_id": task_id, "error": str(exc), "status": "failed"},
            )

    def list_history(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self.db.list_tasks(limit=limit)

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        task = self.db.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"未找到前噬菌体扫描任务: {task_id}")
        result_rel = str(task.get("result_path") or "").strip()
        payload: Dict[str, Any] = {}
        if result_rel:
            resolved = _resolve_user_path(result_rel, self.project_root)
            if resolved is not None and resolved.exists():
                payload = json.loads(resolved.read_text(encoding="utf-8"))
        return {
            "task": task,
            "result": payload,
        }

    def get_region_gbk(self, task_id: str, region_index: int) -> Dict[str, Any]:
        data = self.get_task_result(task_id)
        regions = (data.get("result") or {}).get("regions") or []
        target = None
        for r in regions:
            if int(r.get("index", 0)) == region_index:
                target = r
                break
        if target is None:
            raise FileNotFoundError(f"任务 {task_id} 中不存在区域序号 {region_index}")
        gbk_rel = str(target.get("gbk_file") or "").strip()
        gbk_path = _resolve_user_path(gbk_rel, self.project_root) if gbk_rel else None
        if gbk_path is None or not gbk_path.exists():
            raise FileNotFoundError(f"区域 GenBank 文件缺失: {gbk_rel}")
        return {
            "region": target,
            "gbk_text": gbk_path.read_text(encoding="utf-8"),
        }

    def get_contig_overlay(self, task_id: str, contig_id: Optional[str] = None) -> Dict[str, Any]:
        """按需读取指定 Contig 的底图特征、连续评分曲线与前噬菌体叠图分片数据。"""
        data = self.get_task_result(task_id)
        result_payload = data.get("result") or {}
        contigs = result_payload.get("contigs") or []
        if not contigs:
            raise FileNotFoundError(f"任务 {task_id} 不包含 Contig 叠图元数据")

        target_meta: Optional[Dict[str, Any]] = None
        if contig_id:
            for item in contigs:
                if item.get("id") == contig_id:
                    target_meta = item
                    break
        else:
            for item in contigs:
                if (item.get("hit_count") or 0) > 0:
                    target_meta = item
                    break
            if target_meta is None:
                target_meta = contigs[0]

        if target_meta is None:
            raise FileNotFoundError(f"任务 {task_id} 中不存在目标 Contig: {contig_id}")

        overlay_rel = str(target_meta.get("overlay_file") or "").strip()
        overlay_path = _resolve_user_path(overlay_rel, self.project_root) if overlay_rel else None
        if overlay_path is None or not overlay_path.exists():
            raise FileNotFoundError(f"Contig 叠图分片文件不存在: {overlay_rel}")

        overlay_data = json.loads(overlay_path.read_text(encoding="utf-8"))
        overlay_data["contigs"] = contigs
        return overlay_data

    def get_contig_overlay_gbk(self, task_id: str, contig_id: Optional[str] = None) -> Dict[str, Any]:
        """组装完整目标 Contig 底图 + 前噬菌体高亮叠图的 GenBank 文本，供 GenomeViewer 展示。"""
        data = self.get_task_result(task_id)
        result_payload = data.get("result") or {}
        overlay = self.get_contig_overlay(task_id, contig_id=contig_id)
        target_cid = str(overlay.get("contig_id") or "")

        files_map = result_payload.get("files") or (data.get("task") or {}).get("files") or {}
        input_source_rel = str(files_map.get("input_source") or "").strip()
        if not input_source_rel:
            raise FileNotFoundError(f"任务 {task_id} 未记录输入源序列路径，无法重建完整 Contig 叠图 GenBank")

        all_seqs, _ = load_sequences_with_meta(
            fasta_path=input_source_rel,
            fasta_content=None,
            project_root=self.project_root,
        )
        contig_seq = all_seqs.get(target_cid)
        if not contig_seq:
            raise FileNotFoundError(f"源序列文件中未找到 Contig '{target_cid}': {input_source_rel}")

        gbk_text = build_contig_overlay_gbk(
            contig_id=target_cid,
            contig_seq=contig_seq,
            base_features=list(overlay.get("base_features") or []),
            regions=list(overlay.get("regions") or []),
            source_format=str(overlay.get("source_format") or "fasta"),
        )
        return {
            "contig_id": target_cid,
            "length_bp": len(contig_seq),
            "source_format": overlay.get("source_format", "fasta"),
            "region_count": len(overlay.get("regions") or []),
            "base_feature_count": len(overlay.get("base_features") or []),
            "gbk_text": gbk_text,
        }

    def resolve_task_file(self, task_id: str, file_type: str) -> Path:
        task = self.db.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"任务不存在: {task_id}")
        files = task.get("files") or {}
        if file_type not in files:
            raise FileNotFoundError(f"任务 {task_id} 不包含产物类型: {file_type}")
        resolved = _resolve_user_path(str(files[file_type]), self.project_root)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(f"磁盘产物文件不存在: {files[file_type]}")
        return resolved

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        return await self.queue.cancel_task(task_id)

    def delete_task(self, task_id: str) -> None:
        task = self.db.get_task(task_id)
        if not task:
            return
        task_dir = self.results_root / task_id
        if task_dir.exists() and task_dir.is_dir():
            shutil.rmtree(task_dir, ignore_errors=True)
        self.db.delete_task(task_id)


_manager_instance: Optional[PhageDiscoveryManager] = None


def get_phage_discovery_manager() -> PhageDiscoveryManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PhageDiscoveryManager()
    return _manager_instance
