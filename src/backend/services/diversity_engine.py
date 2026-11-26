# -*- coding: utf-8 -*-
"""
16S 扩增子单分子长读长多样性还原与分析引擎
支持生工测序交付包 (Sangon ZIP) 及多样本 FASTQ 解包、多核并行分类、
rrnDB 16S 拷贝数校正、Alpha/Beta 多样性与分片落盘 Checkpoint。
"""
import concurrent.futures
import gc
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...utils.resource_guard import get_safe_cpu_budget, get_total_logical_cores
from .diversity_filter import DiversityNoiseFilter
from .diversity_metrics import (
    calc_alpha_diversity,
    calc_beta_diversity,
    calc_global_taxa_overview,
    natural_keys,
    parse_chunk_blast_output,
)
from .fastq_qc_service import FastqQCFilter
from .heterogeneity_detector import OperonHeterogeneityDetector
from .rrndb_service import RrnDBService, get_rrndb_service

logger = logging.getLogger("api_server")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class DiversityEngine:
    """扩增子多样性分析引擎"""

    def __init__(self):
        self.results_root = PROJECT_ROOT / "results" / "diversity_checkpoints"
        self.results_root.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.noise_filter = DiversityNoiseFilter(min_rel_abundance=0.5, min_reads_count=2, preserve_other=True)
        self.hetero_detector = OperonHeterogeneityDetector()

    def create_task(self, zip_or_dir_path: str, params: Optional[Dict[str, Any]] = None) -> str:
        params = params or {}
        task_id = f"div_{int(time.time())}_{os.getpid()}_{len(self.tasks) + 1}"
        task_dir = self.results_root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "samples").mkdir(parents=True, exist_ok=True)

        with self._lock:
            self.tasks[task_id] = {
                "task_id": task_id,
                "input_path": zip_or_dir_path,
                "status": "queued",
                "progress": 0.0,
                "current_step": "任务已排队",
                "current_sample": "",
                "total_samples": 0,
                "processed_samples": 0,
                "error": None,
                "start_time": time.time(),
                "end_time": None,
                "params": params,
                "task_dir": str(task_dir.resolve()),
                "summary_file": str((task_dir / "summary_report.json").resolve()),
            }

        thread = threading.Thread(target=self._run_task_worker, args=(task_id,), daemon=True)
        thread.start()
        return task_id

    def get_latest_task(self) -> Optional[Dict[str, Any]]:
        """获取最近一次运行或已完成的多样性分析任务"""
        with self._lock:
            active = [t for t in self.tasks.values() if t.get("status") in ("running", "queued")]
            if active:
                active.sort(key=lambda x: x.get("start_time", 0), reverse=True)
                return dict(active[0])
            if self.tasks:
                all_t = list(self.tasks.values())
                all_t.sort(key=lambda x: x.get("start_time", 0), reverse=True)
                return dict(all_t[0])

        if self.results_root.exists():
            dirs = [d for d in self.results_root.iterdir() if d.is_dir()]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for d in dirs:
                status = self.get_task_status(d.name)
                if status and status.get("status") != "not_found":
                    return status

        return None

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            t = self.tasks.get(task_id)
            if not t:
                summary_file = self.results_root / task_id / "summary_report.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        total_s = len(data.get("samples", []))
                        total_r = sum(s.get("total_reads", 0) for s in data.get("samples", []))
                        return {
                            "task_id": task_id,
                            "status": "completed",
                            "progress": 100.0,
                            "current_step": "分析已完成",
                            "total_samples": total_s,
                            "processed_samples": total_s,
                            "total_reads": total_r,
                            "processed_reads": total_r,
                            "summary_file": str(summary_file),
                        }
                    except Exception as exc:
                        logger.debug("[DiversityEngine] 读取任务状态摘要失败 (%s): %s", task_id, exc)
                return {"task_id": task_id, "status": "not_found"}
            return dict(t)

    def get_task_results(self, task_id: str) -> Optional[Dict[str, Any]]:
        summary_file = self.results_root / task_id / "summary_report.json"
        if summary_file.exists():
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[DiversityEngine] 读取任务报告失败: {e}")
        return None

    def list_all_tasks(self) -> List[Dict[str, Any]]:
        """列出所有历史多样性分析任务 (支持倒序排列与实时状态聚合)"""
        tasks_map = {}
        if self.results_root.exists():
            for task_dir in self.results_root.iterdir():
                if not task_dir.is_dir():
                    continue
                tid = task_dir.name
                summary_file = task_dir / "summary_report.json"
                if summary_file.exists():
                    try:
                        stat = summary_file.stat()
                        with open(summary_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        input_p = data.get("input_path", "")
                        file_name = Path(input_p).name if input_p else tid
                        samples_cnt = data.get("total_samples") or len(data.get("samples", []))
                        reads_cnt = data.get("total_reads") or data.get("total_classified_reads", 0)
                        species_cnt = len(data.get("taxa_overview", [])) or len(data.get("species_ranking", []))
                        comp_time = data.get("completed_at") or stat.st_mtime
                        tasks_map[tid] = {
                            "task_id": tid,
                            "task_name": file_name,
                            "input_path": input_p,
                            "status": "completed",
                            "progress": 100.0,
                            "total_samples": samples_cnt,
                            "total_reads": reads_cnt,
                            "species_count": species_cnt,
                            "created_at": getattr(stat, "st_birthtime", stat.st_mtime),
                            "completed_at": comp_time,
                        }
                    except Exception as e:
                        logger.warning(f"[DiversityEngine] 解析历史任务 {tid} 摘要失败: {e}")
                else:
                    stat = task_dir.stat()
                    tasks_map[tid] = {
                        "task_id": tid,
                        "task_name": tid,
                        "input_path": "",
                        "status": "interrupted",
                        "progress": 0.0,
                        "total_samples": 0,
                        "total_reads": 0,
                        "species_count": 0,
                        "created_at": getattr(stat, "st_birthtime", stat.st_mtime),
                        "completed_at": stat.st_mtime,
                    }

        with self._lock:
            for tid, tinfo in self.tasks.items():
                input_p = tinfo.get("input_path", "")
                fname = Path(input_p).name if input_p else tid
                tasks_map[tid] = {
                    "task_id": tid,
                    "task_name": fname,
                    "input_path": input_p,
                    "status": tinfo.get("status", "running"),
                    "progress": tinfo.get("progress", 0.0),
                    "total_samples": tinfo.get("total_samples", 0),
                    "total_reads": tinfo.get("total_reads", 0),
                    "species_count": 0,
                    "created_at": tinfo.get("created_at", time.time()),
                    "completed_at": None,
                }

        all_tasks = list(tasks_map.values())
        all_tasks.sort(key=lambda x: x.get("completed_at") or x.get("created_at") or 0, reverse=True)
        return all_tasks

    def delete_task(self, task_id: str) -> bool:
        """删除指定的多样性分析任务及其所有 Checkpoint 文件"""
        with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]

        task_dir = self.results_root / task_id
        if task_dir.exists():
            try:
                shutil.rmtree(task_dir)
                logger.info(f"[DiversityEngine] 任务 {task_id} 及其目录已物理删除")
                return True
            except Exception as e:
                logger.error(f"[DiversityEngine] 删除任务目录 {task_id} 失败: {e}")
                return False
        return True

    def clear_all_tasks(self) -> bool:
        """清空所有历史多样性分析任务"""
        with self._lock:
            self.tasks.clear()

        if self.results_root.exists():
            for sub in self.results_root.iterdir():
                if sub.is_dir():
                    try:
                        shutil.rmtree(sub)
                    except Exception as e:
                        logger.error(f"[DiversityEngine] 删除历史目录 {sub.name} 失败: {e}")
        logger.info("[DiversityEngine] 已清空所有历史多样性分析任务")
        return True

    def _update_progress(
        self,
        task_id: str,
        progress: float,
        step: str,
        cur_sample: str = "",
        processed_reads: int = 0,
        total_reads: int = 0,
        processed_samples: int = 0,
        total_samples: int = 0,
    ):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["progress"] = round(progress, 1)
                self.tasks[task_id]["current_step"] = step
                if cur_sample:
                    self.tasks[task_id]["current_sample"] = cur_sample
                if processed_reads > 0 or total_reads > 0:
                    self.tasks[task_id]["processed_reads"] = processed_reads
                    self.tasks[task_id]["total_reads"] = total_reads
                if processed_samples > 0 or total_samples > 0:
                    self.tasks[task_id]["processed_samples"] = processed_samples
                    self.tasks[task_id]["total_samples"] = total_samples

    def _load_existing_checkpoints(self, samples_dir: Path) -> Dict[str, Dict[str, Any]]:
        """加载已落盘的样本 Checkpoint，支持断点续算。"""
        existing: Dict[str, Dict[str, Any]] = {}
        for chk in samples_dir.glob("*.json"):
            try:
                with open(chk, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                s_name = c_data.get("sample_name")
                if s_name:
                    existing[s_name] = c_data
            except Exception as exc:
                logger.debug("[DiversityEngine] 忽略损坏的样本 Checkpoint (%s): %s", chk.name, exc)
        return existing

    def _run_fastq_qc_batch(
        self,
        pending_samples: List[str],
        sample_fastq_map: Dict[str, Path],
        *,
        min_len: int,
        max_len: int,
        min_qscore: float,
    ) -> Tuple[Dict[str, List[tuple]], Dict[str, Dict[str, Any]], Dict[str, int], int]:
        """对所有待处理样本执行前置 FASTQ 质量过滤。"""
        qc_filter = FastqQCFilter(
            min_len=min_len,
            max_len=max_len,
            min_avg_qscore=min_qscore,
            max_n_ratio=0.05,
            auto_adapt_length=True,
        )
        read_counts: Dict[str, int] = defaultdict(int)
        sample_reads_dict: Dict[str, List[tuple]] = {}
        sample_qc_map: Dict[str, Dict[str, Any]] = {}
        total_reads_to_blast = 0
        for sname in pending_samples:
            fq_path = sample_fastq_map[sname]
            clean_reads, qc_rep = qc_filter.filter_fastq_file(fq_path, sample_name=sname)
            sample_reads_dict[sname] = clean_reads
            sample_qc_map[sname] = qc_rep.to_dict()
            read_counts[sname] = len(clean_reads)
            total_reads_to_blast += len(clean_reads)
            logger.info(
                f"[FastqQC] 样本 {sname}: 原始 {qc_rep.total_raw_reads} 条, "
                f"质控剔除劣质/长短不合序列 {qc_rep.total_raw_reads - qc_rep.passed_clean_reads} 条, "
                f"留存 Clean Reads: {len(clean_reads)} 条 (通过率: {qc_rep.pass_rate_pct}%, "
                f"平均长度: {qc_rep.mean_len_clean} bp, 平均质量值: Q{qc_rep.mean_qscore_clean})"
            )
        return sample_reads_dict, sample_qc_map, read_counts, total_reads_to_blast

    @staticmethod
    def _compute_worker_topology(num_pending: int, total_reads: int) -> Tuple[int, int, int, int]:
        """根据物理核数和安全预留计算最优并行 Worker 进程数与每进程线程数。"""
        cpu_total = get_total_logical_cores()
        reserved_cores = 4 if cpu_total > 8 else 2
        usable_cores = max(2, get_safe_cpu_budget(reserve_cores=reserved_cores))

        if (num_pending >= 4 or total_reads >= 16) and usable_cores >= 16:
            num_workers = min(4, usable_cores // 4)
        elif (num_pending >= 2 or total_reads >= 8) and usable_cores >= 8:
            num_workers = min(2, usable_cores // 4)
        else:
            num_workers = 1

        threads_per_worker = max(2, usable_cores // num_workers)
        logger.info(
            f"[DiversityEngine] 启动多进程分片并行引擎: {num_workers} 个 Worker 进程，"
            f"每个 Worker 分配 {threads_per_worker} 线程 "
            f"(总并发算力: {num_workers * threads_per_worker}/{cpu_total} 核心, 安全预留: {reserved_cores} 核)"
        )
        return num_workers, threads_per_worker, cpu_total, reserved_cores

    @staticmethod
    def _build_blast_chunks(
        pending_samples: List[str],
        sample_reads_dict: Dict[str, List[tuple]],
        staged_dir: Path,
        num_workers: int,
    ) -> List[Dict[str, Any]]:
        """将待比对 Reads 划分为样本分组或读段分片 FASTA 文件。"""
        chunk_tasks: List[Dict[str, Any]] = []
        if len(pending_samples) >= num_workers:
            chunk_samples_list: List[List[str]] = [[] for _ in range(num_workers)]
            for idx, sname in enumerate(pending_samples):
                chunk_samples_list[idx % num_workers].append(sname)
            for c_idx, c_samples in enumerate(chunk_samples_list):
                if not c_samples:
                    continue
                chunk_fa = staged_dir / f"chunk_{c_idx}_reads.fasta"
                chunk_out = staged_dir / f"chunk_{c_idx}_blast.txt"
                if chunk_out.exists():
                    chunk_out.unlink()
                c_reads_cnt = 0
                with open(chunk_fa, "w", encoding="utf-8") as out_fa:
                    for sname in c_samples:
                        reads = sample_reads_dict[sname]
                        c_reads_cnt += len(reads)
                        for rid, seq in reads:
                            out_fa.write(f">{sname}__{rid}\n{seq}\n")
                chunk_tasks.append({
                    "chunk_id": c_idx,
                    "mode": "sample_grouped",
                    "samples": c_samples,
                    "fa_path": chunk_fa,
                    "out_path": chunk_out,
                    "reads_count": c_reads_cnt,
                })
            return chunk_tasks

        all_tagged_reads = [
            (f"{sname}__{rid}", seq)
            for sname in pending_samples
            for rid, seq in sample_reads_dict[sname]
        ]
        chunk_reads_list: List[List[Tuple[str, str]]] = [[] for _ in range(num_workers)]
        for idx, item in enumerate(all_tagged_reads):
            chunk_reads_list[idx % num_workers].append(item)
        for c_idx, c_reads in enumerate(chunk_reads_list):
            if not c_reads:
                continue
            chunk_fa = staged_dir / f"chunk_{c_idx}_reads.fasta"
            chunk_out = staged_dir / f"chunk_{c_idx}_blast.txt"
            if chunk_out.exists():
                chunk_out.unlink()
            with open(chunk_fa, "w", encoding="utf-8") as out_fa:
                for tid, seq in c_reads:
                    out_fa.write(f">{tid}\n{seq}\n")
            chunk_tasks.append({
                "chunk_id": c_idx,
                "mode": "reads_sharded",
                "samples": pending_samples,
                "fa_path": chunk_fa,
                "out_path": chunk_out,
                "reads_count": len(c_reads),
            })
        return chunk_tasks

    @staticmethod
    def _parse_chunk_blast_output(
        c_out: Path,
        *,
        min_identity: float,
        min_coverage: float,
    ) -> Dict[str, Dict[str, tuple]]:
        """解析单个分片的 BLAST tabular 结果，按同一性与覆盖度过滤并取各读段最佳命中。"""
        return parse_chunk_blast_output(c_out, min_identity=min_identity, min_coverage=min_coverage)

    def _persist_sample_checkpoint(
        self,
        *,
        task_id: str,
        sname: str,
        hits: Dict[str, tuple],
        rrndb: RrnDBService,
        sample_qc_map: Dict[str, Dict[str, Any]],
        read_counts: Dict[str, int],
        samples_dir: Path,
        existing_checkpoints: Dict[str, Dict[str, Any]],
        total_samples: int,
        total_reads_to_blast: int,
    ) -> None:
        """对单样本执行噪声过滤、rrnDB 归一化、异质性诊断并立即落盘 Checkpoint。"""
        raw_sp_cnt = dict(Counter([v[1] for v in hits.values()]))
        filter_res = self.noise_filter.filter_taxa(raw_sp_cnt, total_classified=len(hits))
        clean_counts = filter_res["filtered_counts"]
        norm_res = rrndb.normalize_abundance(clean_counts)
        alpha_metrics = filter_res["alpha_clean"]
        hetero_advisories = self.hetero_detector.diagnose_sample(raw_sp_cnt)

        s_qc = sample_qc_map.get(sname, {})
        chk_obj = {
            "sample_name": sname,
            "total_raw_reads": s_qc.get("total_raw_reads", read_counts[sname]),
            "total_reads": read_counts[sname],
            "qc_stats": s_qc,
            "classified_reads": len(hits),
            "taxa_counts": clean_counts,
            "raw_taxa_counts": raw_sp_cnt,
            "removed_noise_taxa": filter_res["removed_taxa"],
            "norm_result": norm_res,
            "alpha_diversity": alpha_metrics,
            "heterogeneity_advisories": hetero_advisories,
            "updated_at": time.time(),
        }

        sample_chk_file = samples_dir / f"{sname}.json"
        with open(sample_chk_file, "w", encoding="utf-8") as cf:
            json.dump(chk_obj, cf, ensure_ascii=False, indent=2)

        with self._lock:
            existing_checkpoints[sname] = chk_obj
            cur_done = len(existing_checkpoints)

        chk_prog = 70.0 + (cur_done / max(1, total_samples)) * 20.0
        self._update_progress(
            task_id=task_id,
            progress=chk_prog,
            step=f"已完成样本 {sname} 分片落盘 ({cur_done}/{total_samples})",
            cur_sample=sname,
            processed_reads=total_reads_to_blast,
            total_reads=total_reads_to_blast,
            processed_samples=cur_done,
            total_samples=total_samples,
        )

    def _start_blast_monitor(
        self,
        *,
        task_id: str,
        chunk_out_files: List[Path],
        total_reads_to_blast: int,
        total_samples: int,
        existing_checkpoints: Dict[str, Dict[str, Any]],
    ) -> Tuple[threading.Event, threading.Thread]:
        stop_monitor = threading.Event()

        def monitor_multi_blast_progress():
            seen_queries = set()
            last_sample = ""
            while not stop_monitor.is_set():
                for c_out in chunk_out_files:
                    if not c_out.exists():
                        continue
                    try:
                        with open(c_out, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                parts = line.strip().split("\t")
                                if parts and parts[0] and parts[0] not in seen_queries:
                                    qid = parts[0]
                                    seen_queries.add(qid)
                                    if "__" in qid:
                                        last_sample = qid.split("__", 1)[0]
                    except Exception as exc:
                        logger.debug("[DiversityEngine] 监控读取分片输出失败 (%s): %s", c_out.name, exc)

                cur_reads = len(seen_queries)
                prog = 15.0 + min(55.0, (cur_reads / max(1, total_reads_to_blast)) * 55.0)
                with self._lock:
                    cur_done = len(existing_checkpoints)
                self._update_progress(
                    task_id=task_id,
                    progress=prog,
                    step=f"正在多核并行比对 16S 数据库 ({cur_reads} / {total_reads_to_blast} 条 Reads)",
                    cur_sample=last_sample,
                    processed_reads=cur_reads,
                    total_reads=total_reads_to_blast,
                    processed_samples=cur_done,
                    total_samples=total_samples,
                )
                stop_monitor.wait(0.4)

        monitor_thread = threading.Thread(target=monitor_multi_blast_progress, daemon=True)
        monitor_thread.start()
        return stop_monitor, monitor_thread

    def _run_single_blast_chunk(
        self,
        ct: Dict[str, Any],
        *,
        task_id: str,
        blast_exe: Path,
        db_dir: Path,
        threads_per_worker: int,
        min_identity: float,
        min_coverage: float,
        rrndb: RrnDBService,
        sample_qc_map: Dict[str, Dict[str, Any]],
        read_counts: Dict[str, int],
        samples_dir: Path,
        existing_checkpoints: Dict[str, Dict[str, Any]],
        total_samples: int,
        total_reads_to_blast: int,
    ) -> Dict[str, Dict[str, tuple]]:
        c_id = ct["chunk_id"]
        c_fa = ct["fa_path"]
        c_out = ct["out_path"]
        cmd = [
            str(blast_exe),
            "-query", str(c_fa),
            "-db", "16S_ribosomal_RNA",
            "-out", str(c_out),
            "-outfmt", "6 qseqid sseqid pident length mismatch gapopen evalue bitscore stitle qcovs",
            "-max_target_seqs", "1",
            "-num_threads", str(threads_per_worker),
        ]
        env = os.environ.copy()
        env["OMP_DYNAMIC"] = "FALSE"
        env["OMP_WAIT_POLICY"] = "PASSIVE"
        creationflags = 0x00008000 if os.name == "nt" else 0  # ABOVE_NORMAL_PRIORITY_CLASS

        logger.info(
            f"[DiversityEngine] 启动 Chunk {c_id} ({ct['reads_count']} Reads, "
            f"{threads_per_worker} 线程, 优先级: ABOVE_NORMAL)"
        )
        proc = subprocess.run(
            cmd,
            cwd=str(db_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
            timeout=3600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Chunk {c_id} BLAST 执行失败: {proc.stderr}")

        local_best_hits = self._parse_chunk_blast_output(
            c_out, min_identity=min_identity, min_coverage=min_coverage
        )
        if ct.get("mode") == "sample_grouped":
            for sname in ct["samples"]:
                self._persist_sample_checkpoint(
                    task_id=task_id,
                    sname=sname,
                    hits=local_best_hits[sname],
                    rrndb=rrndb,
                    sample_qc_map=sample_qc_map,
                    read_counts=read_counts,
                    samples_dir=samples_dir,
                    existing_checkpoints=existing_checkpoints,
                    total_samples=total_samples,
                    total_reads_to_blast=total_reads_to_blast,
                )

        if c_fa.exists():
            c_fa.unlink()
        if c_out.exists():
            c_out.unlink()
        gc.collect()
        logger.info(f"[DiversityEngine] Chunk {c_id} 比对完毕并释放临时磁盘资源")
        return local_best_hits

    def _process_pending_samples(
        self,
        *,
        task_id: str,
        pending_samples: List[str],
        sample_fastq_map: Dict[str, Path],
        staged_dir: Path,
        samples_dir: Path,
        existing_checkpoints: Dict[str, Dict[str, Any]],
        total_samples: int,
        qc_cfg: Dict[str, Any],
    ) -> None:
        sample_reads_dict, sample_qc_map, read_counts, total_reads_to_blast = self._run_fastq_qc_batch(
            pending_samples,
            sample_fastq_map,
            min_len=qc_cfg["min_len"],
            max_len=qc_cfg["max_len"],
            min_qscore=qc_cfg["min_qscore"],
        )
        num_workers, threads_per_worker, _, _ = self._compute_worker_topology(
            len(pending_samples), total_reads_to_blast
        )
        self._update_progress(
            task_id=task_id,
            progress=10.0,
            step=f"正在将 {len(pending_samples)} 个样本 ({total_reads_to_blast} 条 Reads) 划分为 {num_workers} 个并行分片...",
            total_samples=total_samples,
            processed_samples=len(existing_checkpoints),
        )

        chunk_tasks = self._build_blast_chunks(pending_samples, sample_reads_dict, staged_dir, num_workers)
        logger.info(f"[DiversityEngine] 分片准备就绪: {len(chunk_tasks)} 个分片，共 {total_reads_to_blast} 条单分子 Reads")

        db_dir = PROJECT_ROOT / "database" / "16S" / "ncbi"
        blast_exe = self._get_blastn_path()
        rrndb = get_rrndb_service()

        self._update_progress(
            task_id=task_id,
            progress=15.0,
            step=f"正在多核并行比对 16S 数据库 (0 / {total_reads_to_blast} 条 Reads)...",
            cur_sample=pending_samples[0] if pending_samples else "",
            processed_reads=0,
            total_reads=total_reads_to_blast,
            processed_samples=len(existing_checkpoints),
            total_samples=total_samples,
        )

        stop_monitor, monitor_thread = self._start_blast_monitor(
            task_id=task_id,
            chunk_out_files=[ct["out_path"] for ct in chunk_tasks],
            total_reads_to_blast=total_reads_to_blast,
            total_samples=total_samples,
            existing_checkpoints=existing_checkpoints,
        )

        t0 = time.time()
        all_sharded_hits: Dict[str, Dict[str, tuple]] = defaultdict(dict)
        is_reads_sharded = bool(chunk_tasks and chunk_tasks[0].get("mode") == "reads_sharded")
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [
                    executor.submit(
                        self._run_single_blast_chunk,
                        ct,
                        task_id=task_id,
                        blast_exe=blast_exe,
                        db_dir=db_dir,
                        threads_per_worker=threads_per_worker,
                        min_identity=qc_cfg["min_identity"],
                        min_coverage=qc_cfg["min_coverage"],
                        rrndb=rrndb,
                        sample_qc_map=sample_qc_map,
                        read_counts=read_counts,
                        samples_dir=samples_dir,
                        existing_checkpoints=existing_checkpoints,
                        total_samples=total_samples,
                        total_reads_to_blast=total_reads_to_blast,
                    )
                    for ct in chunk_tasks
                ]
                for future in concurrent.futures.as_completed(futures):
                    chunk_hit_res = future.result()
                    if is_reads_sharded:
                        for sname, hits in chunk_hit_res.items():
                            all_sharded_hits[sname].update(hits)
        finally:
            stop_monitor.set()
            monitor_thread.join(timeout=2.0)

        if is_reads_sharded:
            for sname in pending_samples:
                self._persist_sample_checkpoint(
                    task_id=task_id,
                    sname=sname,
                    hits=all_sharded_hits[sname],
                    rrndb=rrndb,
                    sample_qc_map=sample_qc_map,
                    read_counts=read_counts,
                    samples_dir=samples_dir,
                    existing_checkpoints=existing_checkpoints,
                    total_samples=total_samples,
                    total_reads_to_blast=total_reads_to_blast,
                )

        logger.info(f"[DiversityEngine] 多进程分片并行 BLAST 全部完成，总耗时: {time.time() - t0:.2f}s")
        gc.collect()

    def _assemble_and_save_summary(
        self,
        *,
        task_id: str,
        input_path: Path,
        task_dir: Path,
        existing_checkpoints: Dict[str, Dict[str, Any]],
        qc_cfg: Dict[str, Any],
    ) -> None:
        """汇总群落 Beta 多样性、物种全局概览与全批次质控指标并落盘。"""
        self._update_progress(task_id, 92.0, "正在计算群落 Beta 多样性与点位空间分布 (PCoA)...")
        all_samples_data = list(existing_checkpoints.values())
        all_samples_data.sort(key=lambda x: self._natural_keys(x["sample_name"]))

        beta_result = self._calc_beta_diversity(all_samples_data)
        taxa_overview = self._calc_global_taxa_overview(all_samples_data)

        qc_list = [s.get("qc_stats") for s in all_samples_data if s.get("qc_stats")]
        tot_raw = (
            sum(q.get("total_raw_reads", 0) for q in qc_list)
            if qc_list
            else sum(s.get("total_reads", 0) for s in all_samples_data)
        )
        tot_clean = (
            sum(q.get("passed_clean_reads", 0) for q in qc_list)
            if qc_list
            else sum(s.get("total_reads", 0) for s in all_samples_data)
        )
        qc_summary = {
            "total_raw_reads": tot_raw,
            "total_clean_reads": tot_clean,
            "total_dropped_reads": tot_raw - tot_clean,
            "overall_pass_rate_pct": round((tot_clean / max(1, tot_raw)) * 100.0, 2),
            "filter_criteria": {
                "min_length": qc_cfg["min_len"],
                "max_length": qc_cfg["max_len"],
                "min_qscore": qc_cfg["min_qscore"],
                "min_identity": qc_cfg["min_identity"],
                "min_coverage": qc_cfg["min_coverage"],
            },
        }

        final_report = {
            "task_id": task_id,
            "input_path": str(input_path),
            "total_samples": len(all_samples_data),
            "total_reads": sum(s.get("total_reads", 0) for s in all_samples_data),
            "total_classified_reads": sum(s.get("classified_reads", 0) for s in all_samples_data),
            "qc_summary": qc_summary,
            "samples": all_samples_data,
            "beta_diversity": beta_result,
            "taxa_overview": taxa_overview,
            "completed_at": time.time(),
        }
        summary_path = task_dir / "summary_report.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, ensure_ascii=False, indent=2)

    def _run_task_worker(self, task_id: str):
        task_info = self.tasks[task_id]
        input_path = Path(task_info["input_path"])
        task_dir = Path(task_info["task_dir"])
        samples_dir = task_dir / "samples"
        staged_dir = task_dir / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)

        task_params = task_info.get("params") or {}
        qc_cfg = {
            "min_len": int(task_params.get("min_len", 200)),
            "max_len": int(task_params.get("max_len", 2500)),
            "min_qscore": float(task_params.get("min_qscore", 7.0)),
            "min_identity": float(task_params.get("min_identity", 80.0)),
            "min_coverage": float(task_params.get("min_coverage", 0.0)),
        }

        try:
            self._update_progress(task_id, 2.0, "正在扫描与解包测序数据...")
            sample_fastq_map = self._collect_fastq_files(input_path, staged_dir)
            if not sample_fastq_map:
                raise ValueError("未在输入路径中发现有效的 .fastq.gz 或 .fastq 文件")

            total_samples = len(sample_fastq_map)
            with self._lock:
                self.tasks[task_id]["status"] = "running"
                self.tasks[task_id]["total_samples"] = total_samples
            logger.info(f"[DiversityEngine] 任务 {task_id}: 发现 {total_samples} 个样本的测序数据")

            existing_checkpoints = self._load_existing_checkpoints(samples_dir)
            pending_samples = [s for s in sample_fastq_map.keys() if s not in existing_checkpoints]
            logger.info(
                f"[DiversityEngine] 已有 Checkpoint: {len(existing_checkpoints)} 个，待处理: {len(pending_samples)} 个"
            )

            if pending_samples:
                self._process_pending_samples(
                    task_id=task_id,
                    pending_samples=pending_samples,
                    sample_fastq_map=sample_fastq_map,
                    staged_dir=staged_dir,
                    samples_dir=samples_dir,
                    existing_checkpoints=existing_checkpoints,
                    total_samples=total_samples,
                    qc_cfg=qc_cfg,
                )

            self._assemble_and_save_summary(
                task_id=task_id,
                input_path=input_path,
                task_dir=task_dir,
                existing_checkpoints=existing_checkpoints,
                qc_cfg=qc_cfg,
            )

            if staged_dir.exists():
                shutil.rmtree(staged_dir, ignore_errors=True)

            with self._lock:
                self.tasks[task_id]["status"] = "completed"
                self.tasks[task_id]["progress"] = 100.0
                self.tasks[task_id]["current_step"] = "分析完成"
                self.tasks[task_id]["end_time"] = time.time()
            logger.info(f"[DiversityEngine] 任务 {task_id} 全部成功完成并已保存至 Checkpoint！")

        except Exception as e:
            logger.error(f"[DiversityEngine] 任务 {task_id} 发生异常: {e}", exc_info=True)
            with self._lock:
                self.tasks[task_id]["status"] = "error"
                self.tasks[task_id]["error"] = str(e)
                self.tasks[task_id]["current_step"] = f"分析出错: {e}"

    def _collect_fastq_files(self, input_path: Path, staged_dir: Path) -> Dict[str, Path]:
        """从 ZIP 或目录中收集每个样本的 fastq 文件"""
        sample_map = {}
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(input_path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".fastq.gz") or name.endswith(".fastq"):
                        base = Path(name).name
                        m = re.search(r"_(-[0-9]+)\.fastq", base)
                        sample_name = m.group(1) if m else re.sub(r"\.fastq(\.gz)?$", "", base)
                        target = staged_dir / base
                        with zf.open(name) as s, open(target, "wb") as t:
                            shutil.copyfileobj(s, t)
                        sample_map[sample_name] = target
        elif input_path.is_dir():
            for f in input_path.rglob("*"):
                if f.name.endswith(".fastq.gz") or f.name.endswith(".fastq"):
                    base = f.name
                    m = re.search(r"_(-[0-9]+)\.fastq", base)
                    sample_name = m.group(1) if m else re.sub(r"\.fastq(\.gz)?$", "", base)
                    sample_map[sample_name] = f
        return sample_map

    def _read_fastq_sequences(self, fq_path: Path) -> List[tuple]:
        """读取 FASTQ 中的 header 与 sequence"""
        reads = []
        is_gz = fq_path.suffix.lower() == ".gz"
        open_fn = gzip.open if is_gz else open
        with open_fn(fq_path, "rt", encoding="utf-8", errors="ignore") as f:
            while True:
                h = f.readline()
                if not h:
                    break
                seq = f.readline().strip()
                f.readline()  # +
                f.readline()  # qual
                rid = h.strip().split()[0][1:]
                reads.append((rid, seq))
        return reads

    def _calc_alpha_diversity(self, taxa_counts: Dict[str, int]) -> Dict[str, float]:
        """计算生态学标准 Alpha 多样性指标"""
        return calc_alpha_diversity(taxa_counts)

    def _calc_beta_diversity(self, samples_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算 Bray-Curtis 距离矩阵与 PCoA 降维坐标"""
        return calc_beta_diversity(samples_data)

    def _calc_global_taxa_overview(self, samples_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """全批次物种全局汇总 (真实物种优先排序，低频噪声与 Other 合集沉底)"""
        return calc_global_taxa_overview(samples_data)

    def _get_blastn_path(self) -> Path:
        try:
            from ...workbench.models.tool_config import ToolConfig

            exe = ToolConfig.resolve_bio_tool("blastn")
            if exe and Path(exe).exists():
                return Path(exe)
        except Exception as exc:
            logger.debug("[DiversityEngine] 从 ToolConfig 获取 blastn 路径失败，将回退本地路径: %s", exc)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        local_cand = project_root / "tools" / "ncbi_dist" / "bin" / ("blastn.exe" if os.name == "nt" else "blastn")
        if local_cand.exists():
            return local_cand
        which = shutil.which("blastn")
        if which:
            return Path(which)
        return local_cand

    def _natural_keys(self, text: str):
        return natural_keys(text)


_engine_instance = None


def get_diversity_engine() -> DiversityEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DiversityEngine()
    return _engine_instance
