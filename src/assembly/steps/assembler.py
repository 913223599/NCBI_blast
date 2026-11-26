# -*- coding: utf-8 -*-
"""
AssemblerStep - NGCS 基因组组装核心步骤封装
全面采用 NGCS (Neural Genome Coordinate System) 作为核心拼接引擎。
支持二代 (Native C++20 欧拉残差流) 与 三代 (连续谱流形与 SIMD-POA) 测序数据的高保真组装。
"""

import asyncio
import gzip
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...utils.resource_guard import get_safe_cpu_budget
from ..core.base import BaseAssemblyStep
from ..utils.file_handler import AssemblyFileHandler
from ..utils.path_resolver import resolve_ngcs_cli, resolve_ngcs_root, resolve_safe_work_dir

logger = logging.getLogger("Assembly.AssemblerStep")

_VALID_MODES = frozenset({"isolate", "metagenome", "metagenome_deep", "unconstrained", "hybrid"})

_LONG_READ_BANNER_KEYS: Tuple[str, ...] = (
    "Scaffolding :",
    "Polish Mode :",
    "Assembly Mode :",
    "Min Contig :",
)

# 表驱动进度遥测规则：(任意命中关键词元组, 进度百分比, 中文阶段描述)
_HYBRID_PROGRESS_RULES: Tuple[Tuple[Tuple[str, ...], int, str], ...] = (
    (("[NGCS PRODUCTION HYBRID ENGINE]", "[Phase 00a]", "Fastp Quality Control"), 20, "二代短读长质控与接头过滤 (fastp)..."),
    (("Short-Read High-Fidelity Unitig Assembly", "[Phase 00b]", "Residual Eulerian"), 35, "二代短读长 0-Indel Unitig 图拓扑构建..."),
    (("[Phase 01]", "[Phase 02]", "De Bruijn"), 50, "欧拉残差流图化简与 Unitig 提取..."),
    (("Long-Read Physical Bridging", "[Phase 02] Ingested", "minimap2"), 70, "三代长读长物理跨越与重复区桥接..."),
    (("Synthesizing Chromosome Scaffolds", "[Phase 03]", "Circular closure"), 88, "染色体级骨架合成与环化闭环 (Loop Closure)..."),
    (("Hybrid Assembly complete", "[SUCCESS]"), 98, "混合组装完成，生成组装报告与指标..."),
)

_LONG_READ_PROGRESS_RULES: Tuple[Tuple[Tuple[str, ...], int, str], ...] = (
    (("[Phase 01]",), 20, "长读长数据质控与载入..."),
    (("[Phase 02]", "Constructing Hardware-Accelerated Overlap Graph"), 35, "长读长重叠图构建中..."),
    (("Graph Built:",), 45, "重叠图构建完成，开始拓扑聚类..."),
    (("[Phase 03]", "Disentangling Independent Molecular"), 55, "基因组子图聚类与流形分离..."),
    (("Solving Graph Laplacian", "Solving contiguous genomic backbones"), 65, "重叠图谱分析与骨架排序..."),
    (("[Phase 04]", "Executing Disjoint-Circular Scaffolding", "Scaffolding Complete:"), 80, "重叠群支架连接与分相解离..."),
    (("[Phase 05]", "Unified Post-Processing"), 88, "全局拓扑治理、发卡解离与闭环环化 (AssemblyPostProcessor)..."),
    (("[Phase 06]", "Consensus Polishing", "SIMD-POA Consensus Engine"), 94, "染色体全长一致性序列打磨校正..."),
    (("Post-Polish Manifold Deduplication", "Restored"), 97, "打磨后双倍流形去冗余与产物整理..."),
    (("Assembly complete", "[SUCCESS]"), 98, "组装完成，生成组装报告与指标..."),
)

_SHORT_READ_PROGRESS_RULES: Tuple[Tuple[Tuple[str, ...], int, str], ...] = (
    (("[Phase 00a]", "Fastp Quality Control"), 10, "测序数据质控与接头修剪 (Fastp)..."),
    (("[Phase 00c]", "BayesHammer"), 18, "SPAdes BayesHammer 高保真读段纠错中..."),
    (("[Phase 00b]", "Residual Eulerian"), 25, "K-mer 频数统计与图分解..."),
    (("[Phase 01]",), 35, "读长流式载入与构建..."),
    (("[Phase 02]",), 50, "De Bruijn 图构建与欧拉路径求解..."),
    (("[Phase 03]", "Dovetail Merging"), 65, "重叠群延伸与空隙填充..."),
    (("[Phase 04]",), 80, "配对末端支架构建 (PE Scaffolding)..."),
    (("Scaffolding Complete",), 90, "支架构建完成，导出重叠群..."),
    (("Assembly complete", "[SUCCESS]"), 98, "组装完成，生成组装报告与指标..."),
)


def _match_ngcs_progress(
    line_str: str,
    *,
    is_hybrid: bool,
    is_long_read: bool,
) -> Optional[Tuple[int, str]]:
    """根据测序平台与表驱动规则解析单行 NGCS 进度遥测。"""
    if is_hybrid:
        rules = _HYBRID_PROGRESS_RULES
    elif is_long_read:
        if ":" in line_str and any(kw in line_str for kw in _LONG_READ_BANNER_KEYS):
            return None
        if "Streamed" in line_str and "clean reads" in line_str:
            return (20, "长读长数据质控与载入...")
        if "Generated" in line_str and "raw contig backbone" in line_str:
            return (75, "骨架延伸完成，提取重叠群...")
        rules = _LONG_READ_PROGRESS_RULES
    else:
        rules = _SHORT_READ_PROGRESS_RULES

    for keywords, pct, desc in rules:
        if any(kw in line_str for kw in keywords):
            return (pct, desc)
    return None


class AssemblerStep(BaseAssemblyStep):
    """
    NGCS 基因组组装步骤封装
    核心特性：
    1. 全面基于 NGCS 架构：二代欧拉残差流 + 三代流形谱图拓扑与 SIMD-POA 分层打磨。
    2. 多平台自适应路由：自动分流 Illumina/MGI 短读长双端与 Nanopore/PacBio 长读长单分子数据。
    3. 流式进度遥测感知：实时捕获并解析底层多阶段日志，同步回传细粒度执行状态。
    4. 学术级指标收割：计算加权平均深度、N50、环状拓扑结构、GC 含量与 Contigs 分布。
    """

    def is_completed(self) -> bool:
        """检查组装产物是否已存在且合法"""
        out_dir = self.get_working_dir() / "assembly_run"
        assembly_fasta = out_dir / "assembly.fasta"
        if assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
            self.context.update("assembly_fasta", assembly_fasta)
            stats = self._parse_assembly_stats(assembly_fasta)
            self.context.update("assembly_stats", stats)
            return True
        return False

    def _resolve_ngcs_cli(self) -> Path:
        """动态解析 NGCS CLI 入口路径"""
        custom_path = self.context.config.get("params", {}).get("ngcs_cli_path") or self.context.config.get("ngcs_cli_path")
        return resolve_ngcs_cli(custom_path)

    async def _prepare_safe_input(self, src_path_str: str, file_tag: str, safe_work_dir: Path) -> str:
        """将 ZIP 压缩包或含中文/空格的路径隔离中转到纯 ASCII 安全工作区。"""
        src_p = Path(src_path_str)
        if not src_p.exists():
            return src_path_str

        if AssemblyFileHandler.is_zip_archive(src_p):
            merged = await self._extract_zip_input(src_p, file_tag, safe_work_dir)
            if merged is not None:
                return merged

        needs_isolate = any(ord(c) > 127 for c in src_path_str) or (" " in src_path_str)
        if not needs_isolate:
            return src_path_str

        suffix = "".join(src_p.suffixes) if src_p.suffixes else ".fq.gz"
        dst_p = safe_work_dir / f"input_{file_tag}{suffix}"
        if dst_p.exists() and dst_p.stat().st_size == src_p.stat().st_size:
            return str(dst_p)

        if dst_p.exists():
            try:
                dst_p.unlink()
            except Exception as exc:
                self.logger.debug("移除旧安全中转文件失败 (%s): %s", dst_p, exc)

        try:
            os.link(src_p, dst_p)
            self.logger.info(f"建立安全硬链接: {src_p.name} -> {dst_p}")
            return str(dst_p)
        except Exception as exc:
            self.logger.debug("建立硬链接失败，将回退到安全复制 (%s): %s", src_p.name, exc)

        self.logger.info(f"跨盘符安全数据中转: {src_p.name} -> {dst_p}")
        if self.on_progress:
            self.on_progress(5, f"数据安全准备中 ({file_tag})...")
        await asyncio.to_thread(shutil.copyfile, src_p, dst_p)
        return str(dst_p)

    async def _extract_zip_input(self, src_p: Path, file_tag: str, safe_work_dir: Path) -> Optional[str]:
        dst_p = safe_work_dir / f"input_{file_tag}.fastq"
        if dst_p.exists() and dst_p.stat().st_size > 1024 and dst_p.stat().st_mtime >= src_p.stat().st_mtime:
            self.logger.info(f"复用已流式聚合的测序数据: {dst_p}")
            return str(dst_p)

        self.logger.info(f"检测到 ZIP 归档测序数据，启动工作线程流式分片聚合: {src_p.name} -> {dst_p.name}")
        if self.on_progress:
            self.on_progress(3, f"正在解析测序压缩包: {src_p.name}...")

        def on_extract_progress(p_val: float, desc_txt: str):
            if self.on_progress:
                mapped_val = 3.0 + (p_val / 100.0) * 12.0
                self.on_progress(round(mapped_val, 1), desc_txt)

        success = await asyncio.to_thread(
            AssemblyFileHandler.extract_and_merge_zip_fastq,
            src_p,
            dst_p,
            on_progress=on_extract_progress,
        )
        if success and dst_p.exists() and dst_p.stat().st_size > 0:
            self.logger.info(f"ZIP 测序数据流式聚合完成，产物大小: {dst_p.stat().st_size / (1024 * 1024):.2f} MB")
            return str(dst_p)
        self.logger.error(f"ZIP 归档测序数据流式聚合失败: {src_p}")
        return None

    def _build_ngcs_command(
        self,
        ngcs_cli: Path,
        safe_work_dir: Path,
        *,
        active_r1: str,
        active_r2: Optional[str],
        active_lr: Optional[str],
        tech: str,
        sample_type: str,
        threads_str: str,
        params: Dict[str, Any],
    ) -> Tuple[List[str], bool, bool]:
        """根据平台与参数构建 NGCS CLI 命令行参数列表。"""
        mode = params.get("mode")
        if not mode or mode not in _VALID_MODES:
            mode = "metagenome" if sample_type in ("PHAGE", "VIRUS", "METAGENOME") else "isolate"

        is_hybrid = (tech == "HYBRID") or (mode == "hybrid") or (bool(active_lr) and bool(active_r1))
        is_long_read = (not is_hybrid) and (tech in ("NANOPORE", "PACBIO_HIFI") or not active_r2)

        cmd_list = [sys.executable, str(ngcs_cli), "assemble"]
        if is_hybrid:
            min_len = str(params.get("min_read_length") or params.get("min_len") or 1000)
            cmd_list.extend([
                "-1", active_r1, "-2", active_r2 or active_r1, "-i", active_lr or active_r1,
                "-o", str(safe_work_dir), "-t", threads_str, "--mode", "hybrid", "--min-len", min_len,
            ])
            self.logger.info(f"NGCS 二代+三代混合组装模式: R1={active_r1}, R2={active_r2}, LR={active_lr}, threads={threads_str}")
        elif is_long_read:
            min_len = str(params.get("min_read_length") or params.get("min_len") or 1000)
            cmd_list.extend([
                "-i", active_r1, "-o", str(safe_work_dir), "-t", threads_str,
                "--min-len", min_len, "--mode", mode,
            ])
            self.logger.info(f"NGCS 长读长单分子组装模式: 输入={active_r1}, mode={mode}, min_len={min_len}")
        else:
            assert active_r2 is not None
            cmd_list.extend([
                "-1", active_r1, "-2", active_r2, "-o", str(safe_work_dir),
                "-t", threads_str, "--mode", mode,
            ])
            self.logger.info(f"NGCS 短读长双端欧拉流组装模式: R1={active_r1}, R2={active_r2}, mode={mode}")

        self._append_optional_flags(cmd_list, params, is_long_read=is_long_read)
        return cmd_list, is_hybrid, is_long_read

    @staticmethod
    def _append_optional_flags(cmd_list: List[str], params: Dict[str, Any], *, is_long_read: bool) -> None:
        min_contig_len = params.get("min_contig_length") or params.get("min_contig_len")
        if min_contig_len:
            cmd_list.extend(["--min-contig-len", str(min_contig_len)])
        if params.get("min_containment_identity") is not None:
            cmd_list.extend(["--min-containment-identity", str(params["min_containment_identity"])])
        if params.get("max_reads"):
            cmd_list.extend(["--max-reads", str(params["max_reads"])])
        if is_long_read and params.get("max_backbone_reads"):
            cmd_list.extend(["--max-backbone-reads", str(params["max_backbone_reads"])])
        if not params.get("enable_qc", True):
            cmd_list.append("--no-qc")
        if not params.get("enable_error_correction", True):
            cmd_list.append("--no-error-correction")

    @staticmethod
    def _build_ngcs_env(ngcs_cli: Path) -> Dict[str, str]:
        run_env = dict(os.environ)
        run_env["PYTHONIOENCODING"] = "utf-8"
        run_env["PYTHONUTF8"] = "1"
        project_ngcs = str(resolve_ngcs_root(str(ngcs_cli)))
        orig_pythonpath = os.environ.get("PYTHONPATH", "")
        run_env["PYTHONPATH"] = f"{project_ngcs};{orig_pythonpath}" if orig_pythonpath else project_ngcs
        return run_env

    def _make_progress_handler(
        self,
        *,
        initial_progress: float,
        is_hybrid: bool,
        is_long_read: bool,
    ) -> Callable[[str], None]:
        step_local_max = initial_progress

        def ngcs_progress_handler(line: str) -> None:
            nonlocal step_local_max
            line_str = line.strip()
            if not line_str:
                return
            if self.on_log:
                self.on_log(line_str)
            matched = _match_ngcs_progress(line_str, is_hybrid=is_hybrid, is_long_read=is_long_read)
            if matched is None:
                return
            target_progress, step_desc = matched
            if target_progress > step_local_max:
                step_local_max = target_progress
            if self.on_progress:
                self.on_progress(step_local_max, step_desc)

        return ngcs_progress_handler

    @staticmethod
    def _sync_assembly_outputs(safe_work_dir: Path, out_dir: Path, assembly_fasta: Path) -> None:
        safe_fasta = safe_work_dir / "assembly.fasta"
        if not (safe_fasta.exists() and safe_fasta.stat().st_size > 0):
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe_fasta, assembly_fasta)
        for extra_name in ("assembly_manifest.json", "assembly_stats.json"):
            extra_src = safe_work_dir / extra_name
            if extra_src.exists():
                shutil.copyfile(extra_src, out_dir / extra_name)
        qc_dir = safe_work_dir / "qc"
        if qc_dir.exists():
            shutil.copytree(qc_dir, out_dir / "qc", dirs_exist_ok=True)

    async def execute(self) -> bool:
        if self.is_completed():
            self.logger.info("检测到已存在的组装产物，跳过该步骤")
            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        params = self.context.config.get("params", {})
        optimal_threads = get_safe_cpu_budget(requested=params.get("threads") or 0, reserve_cores=2)
        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        sample_type = (self.context.config.get("sample_type") or "PHAGE").upper()
        self.logger.info(f"启动 NGCS 组装调度: 平台={tech}, 样本类型={sample_type}, 分配线程={optimal_threads}")

        ngcs_cli = self._resolve_ngcs_cli()
        if not ngcs_cli.exists():
            err_msg = (
                f"未找到 NGCS 引擎入口文件: {ngcs_cli} "
                "(可在 config.json 中配置 ngcs_root 或设置环境变量 NGCS_ROOT 指向 NGCS 根目录)"
            )
            self.logger.error(err_msg)
            self.status = "failed"
            if self.on_progress:
                self.on_progress(0, err_msg)
            return False

        r1_raw = self.context.get("unmerged_r1") or self.context.get("clean_r1") or self.context.get("r1")
        r2_raw = self.context.get("unmerged_r2") or self.context.get("clean_r2") or self.context.get("r2")
        lr_raw = self.context.get("long_reads") or self.context.config.get("long_reads") or params.get("long_reads")
        if not r1_raw:
            self.logger.error("未找到有效的输入数据路径")
            self.status = "failed"
            return False

        out_dir = self.get_working_dir() / "assembly_run"
        out_dir.mkdir(parents=True, exist_ok=True)
        assembly_fasta = out_dir / "assembly.fasta"
        safe_work_dir = resolve_safe_work_dir(self.context.task_id, create=True)

        active_r1 = await self._prepare_safe_input(str(r1_raw), "r1", safe_work_dir)
        active_r2 = (await self._prepare_safe_input(str(r2_raw), "r2", safe_work_dir)) if r2_raw else None
        active_lr = (await self._prepare_safe_input(str(lr_raw), "lr", safe_work_dir)) if lr_raw else None

        cmd_list, is_hybrid, is_long_read = self._build_ngcs_command(
            ngcs_cli,
            safe_work_dir,
            active_r1=active_r1,
            active_r2=active_r2,
            active_lr=active_lr,
            tech=tech,
            sample_type=sample_type,
            threads_str=str(optimal_threads),
            params=params,
        )
        progress_handler = self._make_progress_handler(
            initial_progress=15.0 if active_r1.endswith(".fastq") else 5.0,
            is_hybrid=is_hybrid,
            is_long_read=is_long_read,
        )

        try:
            returncode = await self.runner.run_command(
                cmd_list,
                cwd=safe_work_dir,
                env=self._build_ngcs_env(ngcs_cli),
                on_output=progress_handler,
                is_shell=False,
            )
        except Exception as e:
            self.logger.error(f"NGCS 引擎执行异常: {e}")
            returncode = -1

        self._sync_assembly_outputs(safe_work_dir, out_dir, assembly_fasta)

        if returncode == 0 and assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
            self.logger.info(f"NGCS 组装成功生成 FASTA 产物: {assembly_fasta}")
            self.context.update("assembly_fasta", assembly_fasta)
            self.context.update("assembly_stats", self._parse_assembly_stats(assembly_fasta, safe_work_dir))
            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "组装完成")
            return True

        reason = self._diagnose_failure(safe_work_dir)
        self.last_error = reason
        self.logger.error(f"NGCS 组装未产生有效结果: {reason}")
        if self.on_progress:
            self.on_progress(0, f"Error: {reason}")
        self.status = "failed"
        return False

    def _read_manifest_stats(self, search_dirs: List[Path], stats: Dict[str, Any]) -> bool:
        for s_dir in search_dirs:
            manifest_file = s_dir / "assembly_manifest.json"
            if not manifest_file.exists():
                continue
            try:
                with open(manifest_file, "r", encoding="utf-8") as mf:
                    m_data = json.load(mf)
                tot_len = m_data.get("total_length_bp") or m_data.get("total_bp", 0)
                if tot_len > 0:
                    stats["total_length"] = tot_len
                    stats["contigs"] = m_data.get("total_contigs", 0)
                    stats["avg_depth"] = float(m_data.get("avg_depth") or 0.0)
                    stats["n50"] = int(m_data.get("n50") or 0)
                    stats["max_contig_length"] = int(m_data.get("max_contig_length") or 0)
                    stats["gc_percent"] = float(m_data.get("gc_percent") or 0.0)
                    stats["is_circular"] = bool(m_data.get("is_circular", False))
                    if stats["n50"] > 0 and stats["gc_percent"] > 0.0 and stats["avg_depth"] > 0.0:
                        return True
            except Exception as e:
                self.logger.warning(f"读取 NGCS Manifest 失败: {e}")
        return False

    def _estimate_depth_from_fastq(self, search_dirs: List[Path], safe_len: int) -> Optional[float]:
        candidate_fqs: List[Path] = []
        for k in ("clean_r1", "r1", "unmerged_r1"):
            val = self.context.get(k)
            if val and Path(str(val)).exists():
                candidate_fqs.append(Path(str(val)))
        for s_dir in search_dirs:
            for pattern in ("*.fastq*", "*.fq*"):
                for p in s_dir.glob(pattern):
                    if p.is_file() and "assembly" not in p.name.lower():
                        candidate_fqs.append(p)
        if not candidate_fqs:
            return None
        tfq = candidate_fqs[0]
        try:
            is_gz = tfq.suffix == ".gz" or tfq.name.endswith(".fq.gz")
            opener = gzip.open if is_gz else open
            t_bases = 0
            with opener(tfq, "rt", encoding="utf-8", errors="ignore") as fq_f:
                for q_idx, q_l in enumerate(fq_f):
                    if q_idx % 4 == 1:
                        t_bases += len(q_l.strip())
                    if q_idx >= 40000:
                        break
            return round(t_bases / safe_len, 1) if t_bases > 0 else None
        except Exception as exc:
            self.logger.debug("采样估算 FASTQ 测序深度失败 (%s): %s", tfq, exc)
            return None

    def _parse_assembly_stats(self, fasta_path: Path, work_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        统一权威对接 NGCS 引擎产出的 assembly_manifest.json 与 assembly.fasta 指标
        优先直接复用 NGCS 底层计算的真实深度、N50、环状结构与片段指标，杜绝业务层重复造轮子。
        """
        stats: Dict[str, Any] = {
            "total_length": 0,
            "is_circular": False,
            "avg_depth": 0.0,
            "contigs": 0,
            "gc_percent": 0.0,
            "n50": 0,
            "max_contig_length": 0,
        }
        search_dirs = [fasta_path.parent]
        if work_dir and work_dir not in search_dirs:
            search_dirs.append(work_dir)

        if self._read_manifest_stats(search_dirs, stats):
            return stats

        try:
            contig_lengths: List[int] = []
            fasta_total_len = 0
            fasta_contigs = 0
            total_depth_mass = 0.0
            total_gc = 0
            total_at = 0
            has_explicit_depth = False

            with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
                current_len = 0
                current_depth = 0.0

                def finish_contig():
                    nonlocal total_depth_mass, fasta_total_len
                    if current_len > 0:
                        fasta_total_len += current_len
                        contig_lengths.append(current_len)
                        total_depth_mass += current_depth * current_len

                for line in f:
                    line_str = line.strip()
                    if line_str.startswith(">"):
                        finish_contig()
                        current_len = 0
                        fasta_contigs += 1
                        header = line_str.lower()
                        d_match = re.search(r"(?:depth[=:]|cov[=_:]|coverage[=:])(\d+\.?\d*)", header)
                        if d_match:
                            current_depth = float(d_match.group(1))
                            has_explicit_depth = True
                        else:
                            current_depth = 0.0
                        if not any(tok in header for tok in ("circular=false", "circular=n", "linear")):
                            if any(tok in header for tok in ("circular=true", "circular=y", "topology=circular", "_circular")):
                                stats["is_circular"] = True
                    else:
                        seq_upper = line_str.upper()
                        current_len += len(seq_upper)
                        total_gc += seq_upper.count("G") + seq_upper.count("C")
                        total_at += seq_upper.count("A") + seq_upper.count("T")
                finish_contig()

            if fasta_total_len > 0:
                stats["total_length"] = fasta_total_len
                stats["contigs"] = fasta_contigs
                total_bases = total_gc + total_at
                if total_bases > 0 and stats["gc_percent"] <= 0.0:
                    stats["gc_percent"] = round((total_gc / total_bases * 100.0), 2)
                contig_lengths.sort(reverse=True)
                if stats["max_contig_length"] <= 0:
                    stats["max_contig_length"] = contig_lengths[0] if contig_lengths else 0
                if stats["n50"] <= 0:
                    half_len = fasta_total_len / 2.0
                    cum_len = 0
                    for contig_len in contig_lengths:
                        cum_len += contig_len
                        if cum_len >= half_len:
                            stats["n50"] = contig_len
                            break
                safe_len = max(1, int(stats.get("total_length", 0) or fasta_total_len or 1))
                if has_explicit_depth and total_depth_mass > 0:
                    stats["avg_depth"] = round(total_depth_mass / safe_len, 1)
                else:
                    est_depth = self._estimate_depth_from_fastq(search_dirs, safe_len)
                    if est_depth is not None:
                        stats["avg_depth"] = est_depth
            return stats
        except Exception as e:
            self.logger.error(f"解析组装指标失败: {e}")
            return stats

    def _diagnose_failure(self, out_dir: Path) -> str:
        """诊断失败原因"""
        manifest_file = out_dir / "assembly_manifest.json"
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("total_contigs", 0) == 0:
                        return "测序深度过低或有效 Reads 不足，未能提取到有效 Contig"
            except Exception as exc:
                self.logger.debug("读取失败诊断 manifest 异常 (%s): %s", manifest_file, exc)

        for log_f in out_dir.glob("*.log"):
            try:
                content = log_f.read_text(encoding="utf-8", errors="ignore")
                if "Out of memory" in content or "bad_alloc" in content:
                    return "硬件内存空间不足，请调小可用线程数"
                if "Insufficient read depth" in content or "too few reads" in content:
                    return "测序深度过低或数据清洗过度"
            except Exception as exc:
                self.logger.debug("读取组装日志文件异常 (%s): %s", log_f, exc)

        return "组装过程未生成有效 FASTA 文件，请检查原始数据质量或测序深度"
