# -*- coding: utf-8 -*-
"""
PhyloJobExecutor - PhyloCore 统一任务调度与 DAG 流水线执行器
支持：
- 数据感知双轨自动路由 (全基因组无对齐 Mash / 经典 MSA+ML/NJ)
- 内容寻址 StageCache 秒级缓存复用
- 分片落盘与 Checkpoint 断点保护
- 可即时响应并销毁 Windows/WSL 子进程树的强杀取消机制
- 实时阶段、日志与结果事件广播
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core.checkpoint import CheckpointManager, StageCache
from ..core.id_codec import IdCodec
from ..core.profiler import SequenceProfiler
from ..engines.distance.mash import MashDistanceEngine
from ..engines.msa.aligner import MultiSequenceAligner
from ..engines.tree.fasttree import FastTreeEngine
from ..engines.tree.iqtree import IQTreeEngine
from ..engines.tree.mrbayes import MrBayesEngine
from ..engines.tree.nj import NJBioNJEngine
from ..engines.trimmer import AlignmentTrimmer
from ..models.errors import InvalidInputError, PhyloCancelledError, PhyloError
from ..models.schemas import (
    AniEngineType,
    AniScreenResult,
    CapabilitiesResponse,
    DeliveryScopeConfig,
    EngineCapabilities,
    PhyloJobConfig,
    PhyloJobRecord,
    ReferenceCandidate,
    SequenceProfile,
    StageState,
)
from ..runtime.resource_guard import GpuGuard, get_safe_cpu_budget, get_total_logical_cores
from ..runtime.tool_registry import get_tool_registry
from ..storage.archive_store import PhyloArchiveStore, get_phylo_store
from .phage_workflow import PhageTaxonomyWorkflow, run_ani_screening
from .postprocess import compute_tree_metrics, reroot_midpoint, reroot_outgroup

logger = logging.getLogger("phylo.executor")

EventCallback = Callable[[str, Dict[str, Any]], None]


class _ActiveJobHandle:
    def __init__(self, job_id: str, cancel_event: threading.Event) -> None:
        self.job_id = job_id
        self.cancel_event = cancel_event
        self.active_runner: Any = None
        self.thread: Optional[threading.Thread] = None


class PhyloJobExecutor:
    """进化树任务执行中心（单例）。"""

    _instance: Optional["PhyloJobExecutor"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "PhyloJobExecutor":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        store: Optional[PhyloArchiveStore] = None,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        if getattr(self, "_initialized", False):
            if store is not None:
                self.store = store
            if on_event is not None:
                self.on_event = on_event
            return
        self._initialized = True
        self.store = store or get_phylo_store()
        self.on_event: Optional[EventCallback] = on_event
        self._jobs_lock = threading.Lock()
        self._active_jobs: Dict[str, _ActiveJobHandle] = {}
        try:
            recovered = self.store.recover_interrupted_jobs()
            if recovered > 0:
                logger.warning(f"已自动修正 {recovered} 个服务中断残留任务")
        except Exception as exc:
            logger.debug(f"Recover interrupted jobs skipped: {exc}")

    def _set_active_runner(self, handle: _ActiveJobHandle, runner: Any) -> None:
        with self._jobs_lock:
            handle.active_runner = runner

    def set_event_callback(self, callback: EventCallback) -> None:
        self.on_event = callback

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event_type, payload)
            except Exception as exc:
                logger.debug(f"Event callback failed ({event_type}): {exc}")

    # ─── 能力矩阵探测 ─────────────────────────────────────
    def get_capabilities(self, refresh: bool = False) -> CapabilitiesResponse:
        reg = get_tool_registry()
        if refresh:
            tools = reg.refresh()
        else:
            tools = reg.get_all()
        gpu = GpuGuard.probe()
        total_cores = get_total_logical_cores()
        safe_max = max(1, total_cores - 2) if total_cores > 2 else 1
        default_cores = get_safe_cpu_budget(0)

        engines = {
            "bionj": EngineCapabilities(
                engine="bionj",
                label="BioNJ (改良邻接法 - GPU/向量化)",
                available=True,
                supports_dna=True,
                supports_protein=True,
                supports_bootstrap=True,
                min_bootstrap=0,
                max_bootstrap=1000,
                bootstrap_step=50,
                models_dna=["jc69", "k2p", "p-distance"],
                models_protein=["poisson", "p-distance"],
                notes="支持全基因组 Mash 无对齐与 MSA 距离矩阵 + GPU/多核并行 Bootstrap",
            ),
            "nj": EngineCapabilities(
                engine="nj",
                label="Neighbor-Joining (经典邻接法)",
                available=True,
                supports_dna=True,
                supports_protein=True,
                supports_bootstrap=True,
                min_bootstrap=0,
                max_bootstrap=1000,
                bootstrap_step=50,
                models_dna=["jc69", "k2p", "p-distance"],
                models_protein=["poisson", "p-distance"],
                notes="向量化实现，支持 GPU/多核并行 Bootstrap",
            ),
            "fasttree": EngineCapabilities(
                engine="fasttree",
                label="FastTree (大数据集近似最大似然)",
                available=tools["fasttree"].available,
                supports_dna=True,
                supports_protein=True,
                supports_bootstrap=False,
                min_bootstrap=0,
                max_bootstrap=0,
                bootstrap_step=0,
                models_dna=["gtr", "jc"],
                models_protein=["jtt", "wag", "lg"],
                notes="内置 SH-like 局部支持率 (0~100%)，无需额外 Bootstrap",
            ),
            "iqtree": EngineCapabilities(
                engine="iqtree",
                label="IQ-TREE (高精度最大似然 + UFBoot)",
                available=tools["iqtree"].available,
                supports_dna=True,
                supports_protein=True,
                supports_bootstrap=True,
                min_bootstrap=0,
                max_bootstrap=5000,
                bootstrap_step=500,
                models_dna=["MFP", "JC", "K2P", "HKY", "GTR+G"],
                models_protein=["MFP", "JTT+G", "LG+G", "WAG+G"],
                notes="支持 ModelFinder 自动选模；UFBoot 开启时最低 1000 次",
            ),
            "mrbayes": EngineCapabilities(
                engine="mrbayes",
                label="MrBayes (高级贝叶斯 MCMC 推断)",
                available=tools["mrbayes"].available,
                supports_dna=True,
                supports_protein=True,
                supports_bootstrap=False,
                min_bootstrap=0,
                max_bootstrap=0,
                bootstrap_step=0,
                models_dna=["GTR+I+G"],
                models_protein=["Mixed"],
                notes="计算耗时较长，适合中小规模基因精细推断",
            ),
        }

        return CapabilitiesResponse(
            cpu_logical_cores=total_cores,
            cpu_safe_max=safe_max,
            cpu_default=default_cores,
            gpu_available=gpu["available"],
            gpu_name=gpu["name"],
            gpu_total_vram_mb=gpu["total_vram_mb"],
            gpu_free_vram_mb=gpu["free_vram_mb"],
            wsl_available=reg.wsl_available,
            wsl_distro=reg.wsl_distro,
            tools=tools,
            engines=engines,
        )

    def profile_workspace(self, filenames: Optional[List[str]] = None) -> SequenceProfile:
        paths = self.store.get_workspace_paths(filenames)
        profile, _ = SequenceProfiler.profile_files(paths)
        return profile

    def get_active_jobs(self) -> List[PhyloJobRecord]:
        with self._jobs_lock:
            active_ids = list(self._active_jobs.keys())
        out: List[PhyloJobRecord] = []
        for jid in active_ids:
            rec = self.store.get_job(jid)
            if rec:
                out.append(rec)
        return out

    # ─── 噬菌体第 1 & 2 步交互接口 ────────────────────────
    def run_phage_ani_screen(
        self,
        filenames: Optional[List[str]] = None,
        scope: Optional[DeliveryScopeConfig] = None,
        ani_engine: AniEngineType = "viridic_blastn",
        threads: int = 0,
    ) -> AniScreenResult:
        paths = self.store.get_workspace_paths(filenames)
        if not paths:
            raise InvalidInputError("工作区为空，请先上传或导入至少 1 条噬菌体基因组。")
        _, records = SequenceProfiler.profile_files(paths)
        if not records:
            raise InvalidInputError("未解析到有效序列。")

        work_dir = self.store.cache_dir / "interactive_ani" / uuid.uuid4().hex[:8]
        return run_ani_screening(
            query_records=records,
            scope=scope or DeliveryScopeConfig(),
            ani_engine=ani_engine,
            work_dir=work_dir,
            threads=threads,
        )

    def curate_phage_references(
        self,
        filenames: Optional[List[str]],
        ani_result: Optional[AniScreenResult],
        scope: Optional[DeliveryScopeConfig] = None,
    ) -> List[ReferenceCandidate]:
        from ..engines.reference.ref_curator import PhageReferenceCurator

        paths = self.store.get_workspace_paths(filenames)
        if not paths:
            raise InvalidInputError("工作区为空，无法生成参考序列集。")
        _, records = SequenceProfiler.profile_files(paths)
        dedup_ids = IdCodec.deduplicate_ids([r[0] for r in records])
        norm_queries = [(qid, r[1]) for qid, r in zip(dedup_ids, records, strict=True)]
        curator = PhageReferenceCurator()
        return curator.curate_candidates(
            query_records=norm_queries,
            ani_result=ani_result,
            scope=scope or DeliveryScopeConfig(),
        )

    # ─── 提交与取消 ─────────────────────────────────────────
    def submit_job(self, config: PhyloJobConfig) -> PhyloJobRecord:
        with self._jobs_lock:
            if self._active_jobs:
                running_id = next(iter(self._active_jobs.keys()))
                raise PhyloError(f"已有分析任务正在运行 ({running_id})，请先等待完成或手动终止。", code="JOB_CONFLICT")

            paths = self.store.get_workspace_paths(config.files)
            if not paths:
                raise InvalidInputError("工作区为空，请先上传或导入序列。")

            profile, records = SequenceProfiler.profile_files(paths)
            resolved_track: str = (
                profile.recommended_track if config.track == "auto" else config.track
            )
            if resolved_track not in ("genome", "gene", "phage_taxonomy"):
                resolved_track = "gene"

            min_required = 1 if resolved_track == "phage_taxonomy" else 3
            if profile.sequence_count < min_required:
                raise InvalidInputError(
                    f"有效序列不足 {min_required} 条（当前 {profile.sequence_count} 条），无法启动分析。"
                )

            job_id = f"phylo_{datetime.now().strftime('%y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            job_dir = self.store.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)

            title = (config.title or "").strip() or (
                paths[0].stem if len(paths) == 1 else f"{paths[0].stem} 等 {len(paths)} 个文件"
            )
            stages = self._build_initial_stages(resolved_track, config)
            record = PhyloJobRecord(
                job_id=job_id,
                title=title,
                status="pending",
                resolved_track=resolved_track,  # type: ignore[arg-type]
                config=config,
                profile=profile,
                stages=stages,
                progress=0,
                current_stage="pending",
                message="任务已入队，准备启动...",
                created_at=time.time(),
                job_dir=str(job_dir),
            )
            self.store.save_job(record)

            cancel_event = threading.Event()
            handle = _ActiveJobHandle(job_id=job_id, cancel_event=cancel_event)
            self._active_jobs[job_id] = handle

        worker = threading.Thread(
            target=self._run_job_worker,
            args=(job_id, records, handle),
            name=f"phylo-worker-{job_id}",
            daemon=True,
        )
        handle.thread = worker
        worker.start()
        return record

    def cancel_job(self, job_id: str) -> bool:
        with self._jobs_lock:
            handle = self._active_jobs.get(job_id)
            runner = handle.active_runner if handle is not None else None

        if handle is None:
            rec = self.store.get_job(job_id)
            if rec and rec.status in ("pending", "running"):
                rec.status = "cancelled"
                rec.finished_at = time.time()
                rec.message = "任务已标记取消"
                self.store.save_job(rec)
                return True
            return False

        handle.cancel_event.set()
        if runner is not None and hasattr(runner, "terminate_active"):
            try:
                runner.terminate_active()
            except Exception as exc:
                logger.debug(f"terminate_active error: {exc}")
        return True

    def _build_initial_stages(self, resolved_track: str, config: PhyloJobConfig) -> List[StageState]:
        if resolved_track == "phage_taxonomy":
            return [
                StageState(name="ani_screen", label="1. INPHARED Mash + wgANI 预判"),
                StageState(name="curate_derep", label="2. 参考集构建、去冗余与降采样"),
                StageState(
                    name="marker_extract",
                    label="3. 全基因组蛋白质组分析"
                    if config.marker_mode == "proteome"
                    else "3. 大末端酶亚基 (TerL) 提取",
                ),
                StageState(name="msa", label="4. MAFFT 多序列比对"),
                StageState(name="trim", label="4. ClipKIT 位点修剪"),
                StageState(name="tree", label="5. IQ-TREE 最大似然推断"),
                StageState(name="postprocess", label="7. 外群定根与 iTOL 注释模板"),
                StageState(name="qc_delivery", label="8. 6 项质检与交付包打包"),
            ]
        if resolved_track == "genome":
            return [
                StageState(name="preprocess", label="序列质控与短 ID 编码"),
                StageState(name="mash", label="Mash 全基因组 Sketch 与距离矩阵"),
                StageState(name="tree", label=f"拓扑建树 ({config.engine.upper()})"),
                StageState(name="postprocess", label="ID 还原、定根与统计"),
            ]
        stages = [
            StageState(name="preprocess", label="序列质控与短 ID 编码"),
            StageState(name="msa", label=f"多序列比对 ({config.msa.upper()})"),
        ]
        if (config.trim_mode != "none") or (
            config.trim_gap_threshold is not None and config.trim_gap_threshold < 1.0
        ):
            stages.append(StageState(name="trim", label="低质量/高变位点修剪"))
        stages.append(StageState(name="tree", label=f"系统发育建树 ({config.engine.upper()})"))
        stages.append(StageState(name="postprocess", label="ID 还原、定根与统计"))
        return stages

    # ─── 同步或异步执行核心 ──────────────────────────────────
    def run_sync(self, config: PhyloJobConfig, file_paths: List[Path]) -> PhyloJobRecord:
        """同步执行接口（主要供自动化测试与批处理脚本直调）。"""
        profile, records = SequenceProfiler.profile_files(file_paths)
        resolved_track = profile.recommended_track if config.track == "auto" else config.track
        if resolved_track not in ("genome", "gene", "phage_taxonomy"):
            resolved_track = "gene"
        job_id = f"phylo_sync_{datetime.now().strftime('%y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        job_dir = self.store.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        record = PhyloJobRecord(
            job_id=job_id,
            title=config.title or file_paths[0].stem,
            status="pending",
            resolved_track=resolved_track,  # type: ignore[arg-type]
            config=config,
            profile=profile,
            stages=self._build_initial_stages(resolved_track, config),
            created_at=time.time(),
            job_dir=str(job_dir),
        )
        self.store.save_job(record)
        handle = _ActiveJobHandle(job_id=job_id, cancel_event=threading.Event())
        self._run_job_worker(job_id, records, handle)
        return self.store.get_job(job_id) or record

    def _run_job_worker(
        self,
        job_id: str,
        records: List[tuple[str, str]],
        handle: _ActiveJobHandle,
    ) -> None:
        loaded_record = self.store.get_job(job_id)
        if loaded_record is None:
            return
        record: PhyloJobRecord = loaded_record
        job_dir = Path(record.job_dir)
        ckp = CheckpointManager(job_dir)
        cache = StageCache(self.store.cache_dir)
        start_ts = time.time()
        record.status = "running"
        record.started_at = start_ts
        self.store.save_job(record)

        log_path = job_dir / "job.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a", encoding="utf-8", newline="\n")
        log_write_lock = threading.Lock()

        def _log(msg: str) -> None:
            line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
            with log_write_lock:
                if not log_fh.closed:
                    log_fh.write(line.rstrip("\r\n") + "\n")
                    log_fh.flush()
            self._emit("phylo_log", {"job_id": job_id, "line": line})

        def _stage_update(name: str, status: str, progress: int, msg: str, cached: bool = False, elapsed: float = 0.0, artifact: Optional[str] = None) -> None:
            for st in record.stages:
                if st.name == name:
                    st.status = status  # type: ignore[assignment]
                    st.progress = progress
                    st.cached = cached
                    st.elapsed_sec = round(elapsed, 3)
                    st.message = msg
                    st.artifact_path = artifact
                    ckp.update_stage(st)
                    break
            record.current_stage = name
            record.progress = progress
            record.message = msg
            record.elapsed_sec = round(time.time() - start_ts, 2)
            self.store.save_job(record)
            self._emit(
                "phylo_stage",
                {
                    "job_id": job_id,
                    "stage": name,
                    "status": status,
                    "progress": progress,
                    "cached": cached,
                    "message": msg,
                    "elapsed_sec": record.elapsed_sec,
                    "stages": [s.model_dump() for s in record.stages],
                },
            )

        try:
            cancel_ev = handle.cancel_event
            cfg = record.config
            prof = record.profile or SequenceProfiler.profile_records(records)

            if record.resolved_track == "phage_taxonomy":
                PhageTaxonomyWorkflow.execute(
                    record=record,
                    records=records,
                    job_dir=job_dir,
                    ckp=ckp,
                    cache=cache,
                    cancel_ev=cancel_ev,
                    log_fn=_log,
                    stage_fn=_stage_update,
                    set_runner=lambda r: self._set_active_runner(handle, r),
                )
                record.status = "completed"
                record.finished_at = time.time()
                record.elapsed_sec = round(record.finished_at - start_ts, 2)
                self.store.save_job(record)
                leaf_cnt = record.metrics.leaf_count if record.metrics else 0
                _log(f"噬菌体分类鉴定流水线完成，共 {leaf_cnt} 个叶节点，总耗时 {record.elapsed_sec:.2f}s")
                self._emit("phylo_finished", {"job_id": job_id, "record": record.model_dump()})
                return

            # 1. 预处理与短 ID 编码
            t0 = time.time()
            _stage_update("preprocess", "running", 10, "执行序列质控与安全短 ID 编码...")
            sanitized_fasta = job_dir / "sanitized.fasta"
            id_map_path = job_dir / "id_map.json"
            _, codec = SequenceProfiler.write_sanitized_fasta(records, sanitized_fasta, id_map_path)
            ckp.set_artifact("sanitized_fasta", str(sanitized_fasta))
            ckp.set_artifact("id_map", str(id_map_path))
            _log(f"序列预处理完成: {prof.sequence_count} 条 {prof.mol_type.upper()} 序列 (最长 {prof.max_length:,} bp)")
            _stage_update("preprocess", "completed", 20, "序列预处理完成", elapsed=time.time() - t0, artifact=str(sanitized_fasta))

            if cancel_ev.is_set():
                raise PhyloCancelledError("任务已取消")

            raw_nwk_path = job_dir / "tree_raw.nwk"
            dist_npy_path = job_dir / "distance_matrix.npy"
            dist_csv_path = job_dir / "distance_matrix.csv"
            ids_json_path = job_dir / "distance_ids.json"

            # 2A. Track A: 全基因组无对齐模式 (Mash + NJ/BioNJ)
            if record.resolved_track == "genome":
                t_mash = time.time()
                _stage_update("mash", "running", 35, "运行 Mash 全基因组 MinHash 距离计算...")
                mash_cache_key = cache.make_key(
                    prof.content_hash,
                    "mash",
                    {"kmer": cfg.mash_kmer, "sketch": cfg.mash_sketch},
                )
                hit_cache = cfg.use_cache and cache.restore_files(
                    "mash",
                    mash_cache_key,
                    {
                        "distance_matrix.npy": dist_npy_path,
                        "distance_matrix.csv": dist_csv_path,
                        "distance_ids.json": ids_json_path,
                    },
                )
                import numpy as np

                if hit_cache:
                    ids = json.loads(ids_json_path.read_text(encoding="utf-8"))
                    dist_mat = np.load(str(dist_npy_path))
                    _log(f"[Cache Hit] 命中 Mash 全基因组距离矩阵缓存 ({mash_cache_key})")
                    _stage_update("mash", "cached", 65, "命中 Mash 距离矩阵缓存", cached=True, elapsed=time.time() - t_mash, artifact=str(dist_csv_path))
                else:
                    mash_engine = MashDistanceEngine(cancel_event=cancel_ev, on_log=_log)
                    self._set_active_runner(handle, mash_engine)
                    ids, dist_mat = mash_engine.compute_distance_matrix(
                        sanitized_fasta=sanitized_fasta,
                        work_dir=job_dir,
                        kmer=cfg.mash_kmer,
                        sketch_size=cfg.mash_sketch,
                        threads=cfg.threads,
                    )
                    self._set_active_runner(handle, None)
                    MashDistanceEngine.save_matrix_artifacts(
                        ids=ids,
                        matrix=dist_mat,
                        id_map=codec.short_to_orig,
                        npy_path=dist_npy_path,
                        csv_path=dist_csv_path,
                        ids_json_path=ids_json_path,
                    )
                    if cfg.use_cache:
                        cache.store_files(
                            "mash",
                            mash_cache_key,
                            {
                                "distance_matrix.npy": dist_npy_path,
                                "distance_matrix.csv": dist_csv_path,
                                "distance_ids.json": ids_json_path,
                            },
                        )
                    _stage_update("mash", "completed", 65, "Mash 距离矩阵计算完成", elapsed=time.time() - t_mash, artifact=str(dist_csv_path))

                record.artifacts["distance_csv"] = str(dist_csv_path)

                t_tree = time.time()
                tree_method = "nj" if cfg.engine == "nj" else "bionj"
                _stage_update("tree", "running", 75, f"基于 Mash 距离矩阵构建 {tree_method.upper()} 树...")
                nj_engine = NJBioNJEngine(cancel_event=cancel_ev, on_log=_log)
                nj_engine.build_from_matrix(ids, dist_mat, raw_nwk_path, method=tree_method)
                _stage_update("tree", "completed", 88, f"{tree_method.upper()} 构树完成", elapsed=time.time() - t_tree, artifact=str(raw_nwk_path))

            # 2B. Track B: 经典比对构树模式
            else:
                t_msa = time.time()
                msa_fasta = job_dir / "aligned.fasta"
                _stage_update("msa", "running", 30, f"执行 {cfg.msa.upper()} 多序列比对...")

                if cfg.msa == "none":
                    aligner = MultiSequenceAligner(cancel_event=cancel_ev, on_log=_log)
                    aligner.align(sanitized_fasta, msa_fasta, tool="none", threads=cfg.threads, max_seq_len=prof.max_length)
                    _stage_update("msa", "skipped", 50, "输入已对齐，跳过比对阶段", elapsed=time.time() - t_msa, artifact=str(msa_fasta))
                else:
                    msa_key = cache.make_key(
                        prof.content_hash,
                        f"msa_{cfg.msa}",
                        {"strategy": cfg.msa_strategy},
                    )
                    if cfg.use_cache and cache.restore_files("msa", msa_key, {"aligned.fasta": msa_fasta}):
                        _log(f"[Cache Hit] 命中 {cfg.msa.upper()} 多序列比对缓存 ({msa_key})")
                        _stage_update("msa", "cached", 50, f"命中 {cfg.msa.upper()} 比对缓存", cached=True, elapsed=time.time() - t_msa, artifact=str(msa_fasta))
                    else:
                        aligner = MultiSequenceAligner(cancel_event=cancel_ev, on_log=_log)
                        self._set_active_runner(handle, aligner)
                        aligner.align(
                            sanitized_fasta,
                            msa_fasta,
                            tool=cfg.msa,
                            strategy=cfg.msa_strategy,
                            threads=cfg.threads,
                            max_seq_len=prof.max_length,
                        )
                        self._set_active_runner(handle, None)
                        if cfg.use_cache:
                            cache.store_files("msa", msa_key, {"aligned.fasta": msa_fasta})
                        _stage_update("msa", "completed", 50, f"{cfg.msa.upper()} 比对完成", elapsed=time.time() - t_msa, artifact=str(msa_fasta))

                effective_msa = msa_fasta
                record.artifacts["aligned_fasta"] = str(msa_fasta)

                # 可选修剪（支持 ClipKIT KPIC 与 gap 比例）
                use_trim = (cfg.trim_mode != "none") or (
                    cfg.trim_gap_threshold is not None and cfg.trim_gap_threshold < 1.0
                )
                if use_trim:
                    t_trim = time.time()
                    eff_trim_mode = cfg.trim_mode if cfg.trim_mode != "none" else "gap"
                    _stage_update("trim", "running", 58, f"执行位点修剪 ({eff_trim_mode})...")
                    trimmed_fasta = job_dir / "aligned_trimmed.fasta"
                    _, trim_stats = AlignmentTrimmer.trim_with_mode(
                        msa_fasta,
                        trimmed_fasta,
                        mode=eff_trim_mode,
                        max_gap_ratio=cfg.trim_gap_threshold or 0.5,
                        cancel_event=cancel_ev,
                        on_log=_log,
                    )
                    effective_msa = trimmed_fasta
                    _log(f"[Trimmer] ({trim_stats.get('tool')}) 保留列 {trim_stats['kept_cols']}/{trim_stats['original_cols']}")
                    _stage_update("trim", "completed", 64, f"位点修剪完成 ({trim_stats['kept_cols']} 列)", elapsed=time.time() - t_trim, artifact=str(trimmed_fasta))

                # 建树引擎路由
                t_tree = time.time()
                _stage_update("tree", "running", 70, f"执行 {cfg.engine.upper()} 系统发育推断...")
                if cfg.engine in ("nj", "bionj"):
                    nj_engine = NJBioNJEngine(cancel_event=cancel_ev, on_log=_log)
                    nj_engine.build_from_msa(
                        msa_fasta=effective_msa,
                        output_nwk=raw_nwk_path,
                        work_dir=job_dir,
                        mol_type=prof.mol_type,
                        model=cfg.model,
                        method=cfg.engine,
                        bootstrap=cfg.bootstrap,
                        threads=cfg.threads,
                        use_gpu=cfg.use_gpu,
                        dist_matrix_npy=dist_npy_path,
                        dist_matrix_csv=dist_csv_path,
                        id_map=codec.short_to_orig,
                    )
                    record.artifacts["distance_csv"] = str(dist_csv_path)
                elif cfg.engine == "fasttree":
                    ft_engine = FastTreeEngine(cancel_event=cancel_ev, on_log=_log)
                    self._set_active_runner(handle, ft_engine)
                    ft_engine.build(
                        msa_fasta=effective_msa,
                        output_nwk=raw_nwk_path,
                        mol_type=prof.mol_type,
                        model=cfg.model,
                        threads=cfg.threads,
                    )
                    self._set_active_runner(handle, None)
                elif cfg.engine == "iqtree":
                    iq_engine = IQTreeEngine(cancel_event=cancel_ev, on_log=_log)
                    self._set_active_runner(handle, iq_engine)
                    iq_engine.build(
                        msa_fasta=effective_msa,
                        output_nwk=raw_nwk_path,
                        work_dir=job_dir,
                        mol_type=prof.mol_type,
                        model=cfg.model,
                        bootstrap=cfg.bootstrap,
                        threads=cfg.threads,
                        bnni=cfg.iqtree_bnni,
                        alrt=cfg.iqtree_alrt,
                        seed=cfg.iqtree_seed,
                    )
                    self._set_active_runner(handle, None)
                    if iq_engine.last_best_model:
                        record.artifacts["best_model"] = iq_engine.last_best_model
                    if iq_engine.last_best_model_bic is not None:
                        record.artifacts["best_model_bic"] = iq_engine.last_best_model_bic
                elif cfg.engine == "mrbayes":
                    mb_engine = MrBayesEngine(cancel_event=cancel_ev, on_log=_log)
                    self._set_active_runner(handle, mb_engine)
                    mb_engine.build(
                        msa_fasta=effective_msa,
                        output_nwk=raw_nwk_path,
                        work_dir=job_dir,
                        mol_type=prof.mol_type,
                        ngen=cfg.mrbayes_ngen,
                    )
                    self._set_active_runner(handle, None)
                else:
                    raise InvalidInputError(f"不支持的建树引擎: {cfg.engine}")

                _stage_update("tree", "completed", 90, f"{cfg.engine.upper()} 建树完成", elapsed=time.time() - t_tree, artifact=str(raw_nwk_path))

            # 3. 后处理：ID 无损还原、可选中点定根与统计指标
            t_post = time.time()
            _stage_update("postprocess", "running", 95, "还原序列 ID 并计算拓扑质量指标...")
            raw_nwk_text = raw_nwk_path.read_text(encoding="utf-8", errors="replace").strip()
            restored_nwk = IdCodec.restore_newick(raw_nwk_text, codec.short_to_orig)
            final_nwk = reroot_midpoint(restored_nwk) if cfg.midpoint_root else restored_nwk

            final_nwk_path = job_dir / "final_tree.nwk"
            final_nwk_path.write_text(final_nwk + "\n", encoding="utf-8")
            metrics = compute_tree_metrics(
                final_nwk,
                best_model=record.artifacts.get("best_model"),
                best_model_bic=record.artifacts.get("best_model_bic"),
            )

            record.newick = final_nwk
            record.metrics = metrics
            record.artifacts["final_nwk"] = str(final_nwk_path)
            record.status = "completed"
            record.finished_at = time.time()
            record.elapsed_sec = round(record.finished_at - start_ts, 2)
            _stage_update("postprocess", "completed", 100, "分析完成", elapsed=time.time() - t_post, artifact=str(final_nwk_path))

            _log(f"任务完成，共 {metrics.leaf_count} 个叶节点，总耗时 {record.elapsed_sec:.2f}s")
            self._emit("phylo_finished", {"job_id": job_id, "record": record.model_dump()})

        except PhyloCancelledError as exc:
            record.status = "cancelled"
            record.finished_at = time.time()
            record.elapsed_sec = round(record.finished_at - start_ts, 2)
            record.message = exc.message
            for st in record.stages:
                if st.status == "running":
                    st.status = "cancelled"
                    st.message = "已取消"
            self.store.save_job(record)
            _log(f"任务已取消: {exc.message}")
            self._emit("phylo_cancelled", {"job_id": job_id, "message": exc.message})

        except Exception as exc:
            logger.error(f"Phylo job {job_id} failed: {exc}", exc_info=True)
            err_msg = str(exc)
            detail = getattr(exc, "detail", None)
            if detail:
                _log(f"[ERROR DETAIL] {detail}")
            record.status = "failed"
            record.error = err_msg
            record.finished_at = time.time()
            record.elapsed_sec = round(record.finished_at - start_ts, 2)
            record.message = f"失败: {err_msg}"
            for st in record.stages:
                if st.status == "running":
                    st.status = "failed"
                    st.message = err_msg
            self.store.save_job(record)
            _log(f"任务失败: {err_msg}")
            self._emit("phylo_error", {"job_id": job_id, "error": err_msg, "detail": detail})

        finally:
            self._set_active_runner(handle, None)
            with log_write_lock:
                try:
                    log_fh.close()
                except Exception:
                    pass
            GpuGuard.release_vram()
            with self._jobs_lock:
                self._active_jobs.pop(job_id, None)

    def reroot_saved_job(self, job_id: str, mode: str = "midpoint", node_name: Optional[str] = None) -> PhyloJobRecord:
        from ..delivery.label_formatter import enrich_node_metadata

        record = self.store.get_job(job_id)
        if not record or not record.newick:
            raise InvalidInputError(f"未找到可重定根的任务结果: {job_id}")
        if mode == "midpoint":
            updated = reroot_midpoint(record.newick)
        elif mode == "outgroup" and node_name:
            updated = reroot_outgroup(record.newick, node_name)
        else:
            raise InvalidInputError("重定根参数无效，需指定 midpoint 或 outgroup + node_name")

        best_model = (record.metrics.best_model if record.metrics else None) or record.artifacts.get("best_model")
        best_model_bic = (
            record.metrics.best_model_bic
            if record.metrics and record.metrics.best_model_bic is not None
            else record.artifacts.get("best_model_bic")
        )
        record.newick = updated
        record.metrics = compute_tree_metrics(
            updated,
            best_model=best_model,
            best_model_bic=best_model_bic,
        )
        if record.node_metadata:
            record.node_metadata = enrich_node_metadata(record.node_metadata)
        nwk_path = Path(record.job_dir) / "final_tree.nwk"
        if nwk_path.parent.exists():
            nwk_path.write_text(updated + "\n", encoding="utf-8")
        self.store.save_job(record)
        return record


_executor_singleton: Optional[PhyloJobExecutor] = None
_executor_lock = threading.Lock()


def get_phylo_executor() -> PhyloJobExecutor:
    global _executor_singleton
    with _executor_lock:
        if _executor_singleton is None:
            _executor_singleton = PhyloJobExecutor()
        return _executor_singleton
