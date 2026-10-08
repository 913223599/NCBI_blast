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

import numpy as np

from .rrndb_service import get_rrndb_service

logger = logging.getLogger("api_server")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class DiversityEngine:
    """扩增子多样性分析引擎"""

    def __init__(self):
        self.results_root = PROJECT_ROOT / "results" / "diversity_checkpoints"
        self.results_root.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

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
                        return {
                            "task_id": task_id,
                            "status": "completed",
                            "progress": 100.0,
                            "current_step": "分析已完成",
                            "total_samples": len(data.get("samples", [])),
                            "processed_samples": len(data.get("samples", [])),
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

    def _update_progress(self, task_id: str, progress: float, step: str, cur_sample: str = ""):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["progress"] = round(progress, 1)
                self.tasks[task_id]["current_step"] = step
                if cur_sample:
                    self.tasks[task_id]["current_sample"] = cur_sample

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

            # 3. 对待处理样本提取 Reads 并打标
            if pending_samples:
                self._update_progress(task_id, 10.0, f"正在汇总待分类 Reads (共 {len(pending_samples)} 个样本)...")
                fa_merged = staged_dir / "batch_reads.fasta"
                read_counts = defaultdict(int)
                
                with open(fa_merged, "w", encoding="utf-8") as out_fa:
                    for sname in pending_samples:
                        fq_path = sample_fastq_map[sname]
                        reads = self._read_fastq_sequences(fq_path)
                        read_counts[sname] = len(reads)
                        for rid, seq in reads:
                            tagged_id = f"{sname}__{rid}"
                            out_fa.write(f">{tagged_id}\n{seq}\n")

                total_reads_to_blast = sum(read_counts.values())
                logger.info(f"[DiversityEngine] 准备比对 {total_reads_to_blast} 条单分子 Reads")

                # 4. 执行多核心并行 BLASTn
                self._update_progress(task_id, 25.0, f"正在多核并行比对 16S 数据库 ({total_reads_to_blast} 条 Reads)...")
                
                # 动态计算安全核心数 (保留 4 个核心防止系统卡死)
                cpu_total = os.cpu_count() or 4
                blast_threads = min(16, max(2, cpu_total - 4))
                
                out_blast = staged_dir / "batch_blast.txt"
                db_dir = PROJECT_ROOT / "database" / "16S" / "ncbi"
                blast_exe = self._get_blastn_path()
                
                cmd = [
                    str(blast_exe),
                    "-query", str(fa_merged),
                    "-db", "16S_ribosomal_RNA",
                    "-out", str(out_blast),
                    "-outfmt", "6 qseqid sseqid pident length mismatch gapopen evalue bitscore stitle",
                    "-max_target_seqs", "1",
                    "-num_threads", str(blast_threads)
                ]
                
                t0 = time.time()
                proc = subprocess.run(cmd, cwd=str(db_dir), capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(f"BLAST 执行失败: {proc.stderr}")
                
                logger.info(f"[DiversityEngine] BLAST 完成，耗时: {time.time()-t0:.2f}s")
                self._update_progress(task_id, 70.0, "正在解析比对结果并执行分片落盘...")

                # 5. 分片解析并持久化 Checkpoint
                sample_best_hits = defaultdict(dict)
                with open(out_blast, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split("\t")
                        if len(parts) >= 9:
                            qid = parts[0]
                            if "__" not in qid: continue
                            sname, raw_rid = qid.split("__", 1)
                            bitscore = float(parts[7])
                            pident = float(parts[2])
                            if pident < 80.0:  # 过滤极端低相似度读长
                                continue
                            stitle = parts[8]
                            m = re.search(r"([A-Z][a-z]+ [a-z0-9\.\-]+(?: subsp\. [a-z0-9\.\-]+)?)", stitle)
                            sp = m.group(1) if m else stitle
                            if raw_rid not in sample_best_hits[sname] or bitscore > sample_best_hits[sname][raw_rid][0]:
                                sample_best_hits[sname][raw_rid] = (bitscore, sp, pident)

                rrndb = get_rrndb_service()

                for idx, sname in enumerate(pending_samples):
                    hits = sample_best_hits[sname]
                    sp_cnt = Counter([v[1] for v in hits.values()])
                    norm_res = rrndb.normalize_abundance(dict(sp_cnt))
                    alpha_metrics = self._calc_alpha_diversity(dict(sp_cnt))

                    chk_obj = {
                        "sample_name": sname,
                        "total_reads": read_counts[sname],
                        "classified_reads": len(hits),
                        "taxa_counts": dict(sp_cnt),
                        "norm_result": norm_res,
                        "alpha_diversity": alpha_metrics,
                        "updated_at": time.time()
                    }

                    # 立即落盘单样本 Checkpoint (Rule 9)
                    sample_chk_file = samples_dir / f"{sname}.json"
                    with open(sample_chk_file, "w", encoding="utf-8") as cf:
                        json.dump(chk_obj, cf, ensure_ascii=False, indent=2)

                    existing_checkpoints[sname] = chk_obj
                    
                    cur_prog = 70.0 + (idx + 1) / len(pending_samples) * 20.0
                    self._update_progress(task_id, cur_prog, f"已完成样本 {sname} 分片落盘", sname)

                # 清理临时大文件以释放磁盘与内存
                if fa_merged.exists(): fa_merged.unlink()
                if out_blast.exists(): out_blast.unlink()
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
