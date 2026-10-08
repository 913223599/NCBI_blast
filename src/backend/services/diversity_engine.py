# -*- coding: utf-8 -*-
"""
16S 扩增子单分子长读长多样性还原与分析引擎
支持生工测序交付包 (Sangon ZIP) 及多样本 FASTQ 解包、多核并行分类、
rrnDB 16S 拷贝数校正、Alpha/Beta 多样性与分片落盘 Checkpoint。
"""
import os
import gc
import json
import gzip
import io
import time
import math
import shutil
import zipfile
import logging
import threading
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import Counter, defaultdict
import concurrent.futures

import numpy as np

from .rrndb_service import get_rrndb_service
from .diversity_filter import DiversityNoiseFilter
from .heterogeneity_detector import OperonHeterogeneityDetector

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
        task_id = f"div_{int(time.time())}_{os.getpid()}_{len(self.tasks)+1}"
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
                "summary_file": str((task_dir / "summary_report.json").resolve())
            }

        thread = threading.Thread(target=self._run_task_worker, args=(task_id,), daemon=True)
        thread.start()
        return task_id

    def get_latest_task(self) -> Optional[Dict[str, Any]]:
        """获取最近一次运行或已完成的多样性分析任务"""
        with self._lock:
            # 1. 优先返回正在运行或排队的活跃任务
            active = [t for t in self.tasks.values() if t.get("status") in ("running", "queued")]
            if active:
                active.sort(key=lambda x: x.get("start_time", 0), reverse=True)
                return dict(active[0])
            
            # 2. 返回内存中最近的任务
            if self.tasks:
                all_t = list(self.tasks.values())
                all_t.sort(key=lambda x: x.get("start_time", 0), reverse=True)
                return dict(all_t[0])

        # 3. 扫描磁盘最近历史任务
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
                # 尝试从磁盘加载历史
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
                            "summary_file": str(summary_file)
                        }
                    except Exception:
                        pass
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
                            "completed_at": comp_time
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
                        "completed_at": stat.st_mtime
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
                    "completed_at": None
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
        total_samples: int = 0
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

    def _run_task_worker(self, task_id: str):
        task_info = self.tasks[task_id]
        input_path = Path(task_info["input_path"])
        task_dir = Path(task_info["task_dir"])
        samples_dir = task_dir / "samples"
        staged_dir = task_dir / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._update_progress(task_id, 2.0, "正在扫描与解包测序数据...")
            
            # 1. 扫描与提取 FASTQ
            sample_fastq_map = self._collect_fastq_files(input_path, staged_dir)
            if not sample_fastq_map:
                raise ValueError("未在输入路径中发现有效的 .fastq.gz 或 .fastq 文件")

            total_samples = len(sample_fastq_map)
            with self._lock:
                self.tasks[task_id]["status"] = "running"
                self.tasks[task_id]["total_samples"] = total_samples

            logger.info(f"[DiversityEngine] 任务 {task_id}: 发现 {total_samples} 个样本的测序数据")

            # 2. 检查现有 Checkpoints（断点续算机制）
            existing_checkpoints = {}
            for chk in samples_dir.glob("*.json"):
                try:
                    with open(chk, "r", encoding="utf-8") as f:
                        c_data = json.load(f)
                        s_name = c_data.get("sample_name")
                        if s_name:
                            existing_checkpoints[s_name] = c_data
                except Exception:
                    pass

            pending_samples = [s for s in sample_fastq_map.keys() if s not in existing_checkpoints]
            logger.info(f"[DiversityEngine] 已有 Checkpoint: {len(existing_checkpoints)} 个，待处理: {len(pending_samples)} 个")

            # 3. 对待处理样本按 Worker 划分为并行分片 (Chunk)，实现高吞吐多核并行 (规则 7 & 8)
            if pending_samples:
                # 动态计算安全核心数与并行 Worker 配比 (规则 8: 适当保留 CPU 核心数防止主机卡死)
                cpu_total = os.cpu_count() or 4
                reserved_cores = 4 if cpu_total > 8 else 2
                usable_cores = max(2, cpu_total - reserved_cores)

                # 预读待处理样本的 Reads 总数
                read_counts = defaultdict(int)
                sample_reads_dict = {}
                total_reads_to_blast = 0
                for sname in pending_samples:
                    fq_path = sample_fastq_map[sname]
                    reads = self._read_fastq_sequences(fq_path)
                    sample_reads_dict[sname] = reads
                    read_counts[sname] = len(reads)
                    total_reads_to_blast += len(reads)

                # 最优配比：多子进程分片运行，彻底规避单个 BLAST 进程的 OpenMP 互斥锁与异构核同步屏障瓶颈
                if (len(pending_samples) >= 4 or total_reads_to_blast >= 16) and usable_cores >= 16:
                    num_workers = min(4, usable_cores // 4)
                elif (len(pending_samples) >= 2 or total_reads_to_blast >= 8) and usable_cores >= 8:
                    num_workers = min(2, usable_cores // 4)
                else:
                    num_workers = 1

                threads_per_worker = max(2, usable_cores // num_workers)
                total_active_threads = num_workers * threads_per_worker
                logger.info(
                    f"[DiversityEngine] 启动多进程分片并行引擎: {num_workers} 个 Worker 进程，"
                    f"每个 Worker 分配 {threads_per_worker} 线程 (总并发算力: {total_active_threads}/{cpu_total} 核心, 安全预留: {reserved_cores} 核)"
                )

                self._update_progress(
                    task_id=task_id,
                    progress=10.0,
                    step=f"正在将 {len(pending_samples)} 个样本 ({total_reads_to_blast} 条 Reads) 划分为 {num_workers} 个并行分片...",
                    total_samples=total_samples,
                    processed_samples=len(existing_checkpoints)
                )

                chunk_tasks = []

                if len(pending_samples) >= num_workers:
                    # 样本充足场景：按样本轮询分配至各 Chunk (每个 Worker 跑完即可独立落盘样本 Checkpoint)
                    chunk_samples_list = [[] for _ in range(num_workers)]
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
                                    tagged_id = f"{sname}__{rid}"
                                    out_fa.write(f">{tagged_id}\n{seq}\n")

                        chunk_tasks.append({
                            "chunk_id": c_idx,
                            "mode": "sample_grouped",
                            "samples": c_samples,
                            "fa_path": chunk_fa,
                            "out_path": chunk_out,
                            "reads_count": c_reads_cnt
                        })
                else:
                    # 样本较少但 Reads 充裕场景：按 Reads 轮询切片至各 Chunk (彻底消除单进程锁竞争，吃满全部核心)
                    all_tagged_reads = []
                    for sname in pending_samples:
                        for rid, seq in sample_reads_dict[sname]:
                            all_tagged_reads.append((f"{sname}__{rid}", seq))

                    chunk_reads_list = [[] for _ in range(num_workers)]
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
                            "reads_count": len(c_reads)
                        })

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
                    total_samples=total_samples
                )

                # 启动全局流式监控线程 (汇聚所有 chunk 输出文件中的已分类 Reads)
                stop_monitor = threading.Event()
                chunk_out_files = [ct["out_path"] for ct in chunk_tasks]

                def monitor_multi_blast_progress():
                    seen_queries = set()
                    last_sample = ""
                    while not stop_monitor.is_set():
                        for c_out in chunk_out_files:
                            if c_out.exists():
                                try:
                                    with open(c_out, "r", encoding="utf-8", errors="ignore") as f:
                                        for line in f:
                                            parts = line.strip().split("\t")
                                            if parts and parts[0]:
                                                qid = parts[0]
                                                if qid not in seen_queries:
                                                    seen_queries.add(qid)
                                                    if "__" in qid:
                                                        last_sample = qid.split("__", 1)[0]
                                except Exception:
                                    pass

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
                            total_samples=total_samples
                        )
                        stop_monitor.wait(0.4)

                monitor_thread = threading.Thread(target=monitor_multi_blast_progress, daemon=True)
                monitor_thread.start()

                # 单个分片工作线程逻辑：比对 -> 解析 -> 立即单样本 Checkpoint 落盘 (规则 9)
                def execute_chunk(ct: Dict[str, Any]) -> Dict[str, Dict[str, tuple]]:
                    c_id = ct["chunk_id"]
                    c_fa = ct["fa_path"]
                    c_out = ct["out_path"]

                    cmd = [
                        str(blast_exe),
                        "-query", str(c_fa),
                        "-db", "16S_ribosomal_RNA",
                        "-out", str(c_out),
                        "-outfmt", "6 qseqid sseqid pident length mismatch gapopen evalue bitscore stitle",
                        "-max_target_seqs", "1",
                        "-num_threads", str(threads_per_worker)
                    ]

                    # 注入环境变量与 Windows 调度优先级，消除大小核与后台降频惩罚
                    env = os.environ.copy()
                    env["OMP_DYNAMIC"] = "FALSE"
                    env["OMP_WAIT_POLICY"] = "PASSIVE"
                    creationflags = 0x00008000 if os.name == "nt" else 0  # ABOVE_NORMAL_PRIORITY_CLASS

                    logger.info(f"[DiversityEngine] 启动 Chunk {c_id} ({ct['reads_count']} Reads, {threads_per_worker} 线程, 优先级: ABOVE_NORMAL)")
                    proc = subprocess.run(
                        cmd,
                        cwd=str(db_dir),
                        capture_output=True,
                        text=True,
                        env=env,
                        creationflags=creationflags
                    )
                    if proc.returncode != 0:
                        raise RuntimeError(f"Chunk {c_id} BLAST 执行失败: {proc.stderr}")

                    # 立即解析本分片比对结果
                    local_best_hits = defaultdict(dict)
                    if c_out.exists():
                        with open(c_out, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                parts = line.strip().split("\t")
                                if len(parts) >= 9:
                                    qid = parts[0]
                                    if "__" not in qid: continue
                                    sname, raw_rid = qid.split("__", 1)
                                    bitscore = float(parts[7])
                                    pident = float(parts[2])
                                    if pident < 80.0:
                                        continue
                                    stitle = parts[8]
                                    m = re.search(r"([A-Z][a-z]+ [a-z0-9\.\-]+(?: subsp\. [a-z0-9\.\-]+)?)", stitle)
                                    sp = m.group(1) if m else stitle
                                    if raw_rid not in local_best_hits[sname] or bitscore > local_best_hits[sname][raw_rid][0]:
                                        local_best_hits[sname][raw_rid] = (bitscore, sp, pident)

                    # 如果是样本独占模式，立即逐样本落盘 Checkpoint (规则 9: 分片落盘与断点保护)
                    if ct.get("mode") == "sample_grouped":
                        for sname in ct["samples"]:
                            hits = local_best_hits[sname]
                            raw_sp_cnt = dict(Counter([v[1] for v in hits.values()]))
                            filter_res = self.noise_filter.filter_taxa(raw_sp_cnt, total_classified=len(hits))
                            clean_counts = filter_res["filtered_counts"]
                            norm_res = rrndb.normalize_abundance(clean_counts)
                            alpha_metrics = filter_res["alpha_clean"]
                            hetero_advisories = self.hetero_detector.diagnose_sample(raw_sp_cnt)

                            chk_obj = {
                                "sample_name": sname,
                                "total_reads": read_counts[sname],
                                "classified_reads": len(hits),
                                "taxa_counts": clean_counts,
                                "raw_taxa_counts": raw_sp_cnt,
                                "removed_noise_taxa": filter_res["removed_taxa"],
                                "norm_result": norm_res,
                                "alpha_diversity": alpha_metrics,
                                "heterogeneity_advisories": hetero_advisories,
                                "updated_at": time.time()
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
                                total_samples=total_samples
                            )

                    # 释放本分片临时文件以防 OOM
                    if c_fa.exists(): c_fa.unlink()
                    if c_out.exists(): c_out.unlink()
                    gc.collect()
                    logger.info(f"[DiversityEngine] Chunk {c_id} 比对完毕并释放临时磁盘资源")
                    return local_best_hits

                t0 = time.time()
                all_sharded_hits = defaultdict(dict)
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                        futures = [executor.submit(execute_chunk, ct) for ct in chunk_tasks]
                        for future in concurrent.futures.as_completed(futures):
                            chunk_hit_res = future.result()
                            if chunk_tasks[0].get("mode") == "reads_sharded":
                                for sname, hits in chunk_hit_res.items():
                                    all_sharded_hits[sname].update(hits)
                finally:
                    stop_monitor.set()
                    monitor_thread.join(timeout=2.0)

                # 若为 reads_sharded 模式，在此处统一逐样本落盘 Checkpoint
                if chunk_tasks and chunk_tasks[0].get("mode") == "reads_sharded":
                    for sname in pending_samples:
                        hits = all_sharded_hits[sname]
                        raw_sp_cnt = dict(Counter([v[1] for v in hits.values()]))
                        filter_res = self.noise_filter.filter_taxa(raw_sp_cnt, total_classified=len(hits))
                        clean_counts = filter_res["filtered_counts"]
                        norm_res = rrndb.normalize_abundance(clean_counts)
                        alpha_metrics = filter_res["alpha_clean"]
                        hetero_advisories = self.hetero_detector.diagnose_sample(raw_sp_cnt)

                        chk_obj = {
                            "sample_name": sname,
                            "total_reads": read_counts[sname],
                            "classified_reads": len(hits),
                            "taxa_counts": clean_counts,
                            "raw_taxa_counts": raw_sp_cnt,
                            "removed_noise_taxa": filter_res["removed_taxa"],
                            "norm_result": norm_res,
                            "alpha_diversity": alpha_metrics,
                            "heterogeneity_advisories": hetero_advisories,
                            "updated_at": time.time()
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
                            total_samples=total_samples
                        )

                logger.info(f"[DiversityEngine] 多进程分片并行 BLAST 全部完成，总耗时: {time.time()-t0:.2f}s")
                gc.collect()

            # 6. 计算整体 Beta 多样性与宏观汇总
            self._update_progress(task_id, 92.0, "正在计算群落 Beta 多样性与点位空间分布 (PCoA)...")
            all_samples_data = list(existing_checkpoints.values())
            # 按样本名自然排序
            all_samples_data.sort(key=lambda x: self._natural_keys(x["sample_name"]))

            beta_result = self._calc_beta_diversity(all_samples_data)
            taxa_overview = self._calc_global_taxa_overview(all_samples_data)

            final_report = {
                "task_id": task_id,
                "input_path": str(input_path),
                "total_samples": len(all_samples_data),
                "total_reads": sum(s.get("total_reads", 0) for s in all_samples_data),
                "total_classified_reads": sum(s.get("classified_reads", 0) for s in all_samples_data),
                "samples": all_samples_data,
                "beta_diversity": beta_result,
                "taxa_overview": taxa_overview,
                "completed_at": time.time()
            }

            # 落盘全量汇总报告
            summary_path = task_dir / "summary_report.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(final_report, f, ensure_ascii=False, indent=2)

            # 清理 staging 目录
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
                        # 生工格式: 31426091801302_-1.fastq.gz -> 提取 -1
                        base = Path(name).name
                        m = re.search(r"_(-[0-9]+)\.fastq", base)
                        if m:
                            sample_name = m.group(1)
                        else:
                            sample_name = re.sub(r"\.fastq(\.gz)?$", "", base)

                        # 解压到 staged
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
                if not h: break
                seq = f.readline().strip()
                f.readline() # +
                f.readline() # qual
                rid = h.strip().split()[0][1:]
                reads.append((rid, seq))
        return reads

    def _calc_alpha_diversity(self, taxa_counts: Dict[str, int]) -> Dict[str, float]:
        """计算生态学标准 Alpha 多样性指标"""
        total = sum(taxa_counts.values())
        if total == 0:
            return {"richness": 0, "shannon": 0.0, "simpson": 0.0, "chao1": 0.0, "evenness": 0.0}

        proportions = [c / total for c in taxa_counts.values()]
        richness = len(taxa_counts)

        # Shannon-Wiener Index: H = -sum(p * ln(p))
        shannon = -sum(p * math.log(p) for p in proportions if p > 0)

        # Gini-Simpson Index: 1 - sum(p^2)
        simpson = 1.0 - sum(p ** 2 for p in proportions)

        # Pielou's Evenness: J = H / ln(S)
        evenness = (shannon / math.log(richness)) if richness > 1 else 1.0

        # Chao1 Estimator
        singletons = sum(1 for c in taxa_counts.values() if c == 1)
        doubletons = sum(1 for c in taxa_counts.values() if c == 2)
        if doubletons > 0:
            chao1 = richness + (singletons * (singletons - 1)) / (2 * (doubletons + 1))
        else:
            chao1 = richness + (singletons * (singletons - 1)) / 2.0

        return {
            "richness": richness,
            "shannon": round(shannon, 3),
            "simpson": round(simpson, 3),
            "evenness": round(evenness, 3),
            "chao1": round(chao1, 2)
        }

    def _calc_beta_diversity(self, samples_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算 Bray-Curtis 距离矩阵与 PCoA 降维坐标"""
        if len(samples_data) < 2:
            return {"pcoa_points": [], "var_pc1": 0.0, "var_pc2": 0.0, "matrix": []}

        # 1. 收集所有物种构建矩阵
        all_taxa = sorted(list({
            d["taxon"] 
            for s in samples_data 
            for d in s.get("norm_result", {}).get("details", [])
        }))
        if not all_taxa:
            return {"pcoa_points": [], "var_pc1": 0.0, "var_pc2": 0.0, "matrix": []}

        taxa_idx = {t: i for i, t in enumerate(all_taxa)}
        n_samples = len(samples_data)
        abund_mat = np.zeros((n_samples, len(all_taxa)))

        for i, s in enumerate(samples_data):
            for d in s.get("norm_result", {}).get("details", []):
                t = d["taxon"]
                if t in taxa_idx:
                    abund_mat[i, taxa_idx[t]] = d.get("norm_pct", 0.0)

        # 2. Bray-Curtis 距离矩阵
        dist_mat = np.zeros((n_samples, n_samples))
        for i in range(n_samples):
            for j in range(i + 1, n_samples):
                u = abund_mat[i]
                v = abund_mat[j]
                denom = np.sum(u + v)
                bc = (np.sum(np.abs(u - v)) / denom) if denom > 0 else 0.0
                dist_mat[i, j] = bc
                dist_mat[j, i] = bc

        # 3. PCoA 分解 (Gower's Double Centering)
        A = -0.5 * (dist_mat ** 2)
        H = np.eye(n_samples) - np.ones((n_samples, n_samples)) / n_samples
        B = H.dot(A).dot(H)

        eigvals, eigvecs = np.linalg.eigh(B)
        sort_idx = np.argsort(eigvals)[::-1]
        eigvals = eigvals[sort_idx]
        eigvecs = eigvecs[:, sort_idx]

        pos_mask = eigvals > 0
        total_pos = np.sum(eigvals[pos_mask]) if np.sum(pos_mask) > 0 else 1.0

        var_pc1 = float(eigvals[0] / total_pos * 100) if len(eigvals) > 0 and eigvals[0] > 0 else 0.0
        var_pc2 = float(eigvals[1] / total_pos * 100) if len(eigvals) > 1 and eigvals[1] > 0 else 0.0

        pc1 = eigvecs[:, 0] * np.sqrt(max(0, eigvals[0]))
        pc2 = (eigvecs[:, 1] * np.sqrt(max(0, eigvals[1]))) if len(eigvals) > 1 else np.zeros(n_samples)

        pcoa_points = []
        for i, s in enumerate(samples_data):
            pcoa_points.append({
                "sample_name": s["sample_name"],
                "pc1": round(float(pc1[i]), 4),
                "pc2": round(float(pc2[i]), 4),
                "total_reads": s.get("total_reads", 0)
            })

        return {
            "pcoa_points": pcoa_points,
            "var_pc1": round(var_pc1, 2),
            "var_pc2": round(var_pc2, 2),
            "distance_matrix": np.round(dist_mat, 3).tolist()
        }

    def _calc_global_taxa_overview(self, samples_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """全批次物种全局汇总"""
        agg = defaultdict(lambda: {"raw_count": 0, "norm_count": 0.0, "sample_hits": 0, "gcn_mean": 1.0})
        total_norm = 0.0
        total_raw = 0

        for s in samples_data:
            for d in s.get("norm_result", {}).get("details", []):
                taxon = d["taxon"]
                agg[taxon]["raw_count"] += d["raw_count"]
                agg[taxon]["norm_count"] += d["norm_count"]
                agg[taxon]["sample_hits"] += 1
                agg[taxon]["gcn_mean"] = d.get("gcn_mean", 1.0)
                total_norm += d["norm_count"]
                total_raw += d["raw_count"]

        res = []
        for taxon, info in agg.items():
            res.append({
                "taxon": taxon,
                "raw_count": info["raw_count"],
                "raw_pct": round(info["raw_count"] / total_raw * 100.0, 2) if total_raw > 0 else 0.0,
                "norm_pct": round(info["norm_count"] / total_norm * 100.0, 2) if total_norm > 0 else 0.0,
                "sample_frequency": f"{info['sample_hits']}/{len(samples_data)}",
                "gcn_mean": info["gcn_mean"]
            })

        res.sort(key=lambda x: x["norm_pct"], reverse=True)
        return res

    def _get_blastn_path(self) -> Path:
        cand = Path(r"D:\Program Files\NCBI\blast-2.16.0+\bin\blastn.exe")
        if cand.exists():
            return cand
        which = shutil.which("blastn")
        if which:
            return Path(which)
        return cand

    def _natural_keys(self, text: str):
        return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]


_engine_instance = None

def get_diversity_engine() -> DiversityEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = DiversityEngine()
    return _engine_instance
