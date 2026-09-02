# -*- coding: utf-8 -*-
"""
AssemblerStep - NGCS 基因组组装核心步骤封装
全面采用 NGCS (Neural Genome Coordinate System) 作为核心拼接引擎。
支持二代 (Native C++20 欧拉残差流) 与 三代 (连续谱流形与 SIMD-POA) 测序数据的高保真组装。
"""

import os
import re
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from ..core.base import BaseAssemblyStep

logger = logging.getLogger("Assembly.AssemblerStep")


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
        # 1. 优先从全局配置获取
        custom_path = self.context.config.get("params", {}).get("ngcs_cli_path") or self.context.config.get("ngcs_cli_path")
        if custom_path and Path(custom_path).exists():
            return Path(custom_path).resolve()

        # 2. 检查环境变量
        env_path = os.environ.get("NGCS_CLI_PATH")
        if env_path and Path(env_path).exists():
            return Path(env_path).resolve()

        # 3. 检查标准绝对路径与常用相对路径
        candidate_paths = [
            Path(r"E:\NGCS\ngcs\cli.py"),
            Path(__file__).resolve().parent.parent.parent.parent.parent / "NGCS" / "ngcs" / "cli.py",
            Path(self.context.base_dir).resolve().parent.parent / "NGCS" / "ngcs" / "cli.py"
        ]

        for cand in candidate_paths:
            if cand.exists():
                return cand.resolve()

        # 兜底返回默认路径
        return Path(r"E:\NGCS\ngcs\cli.py")

    async def execute(self) -> bool:
        if self.is_completed():
            self.logger.info("检测到已存在的组装产物，跳过该步骤")
            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "已跳过 (发现历史缓存)")
            return True

        self.status = "running"
        params = self.context.config.get("params", {})
        cpu_count = os.cpu_count() or 8
        optimal_threads = params.get("threads") or max(1, cpu_count - 2)
        threads_str = str(optimal_threads)

        tech = (self.context.config.get("tech") or "ILLUMINA").upper()
        sample_type = (self.context.config.get("sample_type") or "PHAGE").upper()
        
        self.logger.info(f"启动 NGCS 组装调度: 平台={tech}, 样本类型={sample_type}, 分配线程={optimal_threads}")

        ngcs_cli = self._resolve_ngcs_cli()
        if not ngcs_cli.exists():
            err_msg = f"未找到 NGCS 引擎入口文件: {ngcs_cli}"
            self.logger.error(err_msg)
            self.status = "failed"
            if self.on_progress:
                self.on_progress(0, err_msg)
            return False

        # 准备输出目录
        out_dir = self.get_working_dir() / "assembly_run"
        out_dir.mkdir(parents=True, exist_ok=True)
        assembly_fasta = out_dir / "assembly.fasta"

        # 获取输入测序数据
        r1_raw = self.context.get("unmerged_r1") or self.context.get("clean_r1") or self.context.get("r1")
        r2_raw = self.context.get("unmerged_r2") or self.context.get("clean_r2") or self.context.get("r2")
        r1 = str(r1_raw) if r1_raw else None
        r2 = str(r2_raw) if r2_raw else None

        if not r1:
            self.logger.error("未找到有效的输入数据路径")
            self.status = "failed"
            return False

        # 模式配置 (支持 isolate, metagenome, metagenome_deep, unconstrained)
        mode = params.get("mode")
        if not mode or mode not in ["isolate", "metagenome", "metagenome_deep", "unconstrained"]:
            mode = "metagenome" if sample_type in ["PHAGE", "VIRUS", "METAGENOME"] else "isolate"

        # 构建 NGCS CLI 指令
        py_exec = sys.executable
        cmd_list = [py_exec, str(ngcs_cli), "assemble"]

        is_long_read = tech in ["NANOPORE", "PACBIO_HIFI"] or not r2
        if is_long_read:
            min_len = str(params.get("min_read_length") or params.get("min_len") or 1000)
            cmd_list.extend([
                "-i", r1,
                "-o", str(out_dir),
                "-t", threads_str,
                "--min-len", min_len,
                "--mode", mode
            ])
            self.logger.info(f"NGCS 长读长单分子组装模式: 输入={r1}, mode={mode}, min_len={min_len}")
        else:
            cmd_list.extend([
                "-1", r1,
                "-2", r2,
                "-o", str(out_dir),
                "-t", threads_str,
                "--mode", mode
            ])
            self.logger.info(f"NGCS 短读长双端欧拉流组装模式: R1={r1}, R2={r2}, mode={mode}")

        # 附加高级调优参数
        min_contig_len = params.get("min_contig_length") or params.get("min_contig_len")
        if min_contig_len:
            cmd_list.extend(["--min-contig-len", str(min_contig_len)])

        min_containment = params.get("min_containment_identity")
        if min_containment is not None:
            cmd_list.extend(["--min-containment-identity", str(min_containment)])

        max_reads = params.get("max_reads")
        if max_reads:
            cmd_list.extend(["--max-reads", str(max_reads)])

        enable_qc = params.get("enable_qc", True)
        if not enable_qc:
            cmd_list.append("--no-qc")

        # 实时日志捕获与进度遥测映射
        def ngcs_progress_handler(line: str):
            line_str = line.strip()
            if not line_str:
                return

            if "[Phase 00a]" in line_str or "Quality Control" in line_str:
                if self.on_progress:
                    self.on_progress(10, "数据质控与接头修剪 (Fastp)...")
            elif "[Phase 00b]" in line_str or "Native C++20" in line_str:
                if self.on_progress:
                    self.on_progress(25, "Native C++20 欧拉残差流引擎计算中...")
            elif "[Phase 01]" in line_str or "Stream Ingestion" in line_str:
                if self.on_progress:
                    self.on_progress(20, "测序数据流流式加载中...")
            elif "[Phase 02]" in line_str or "Multi-Tier" in line_str or "Resolving Flow Tier" in line_str:
                if self.on_progress:
                    self.on_progress(45, "多层级残差流 De Bruijn 图分解构建...")
            elif "[Phase 03]" in line_str or "Dovetail Merging" in line_str or "Gap-Filling" in line_str:
                if self.on_progress:
                    self.on_progress(65, "全域 0-Indel Dovetail 拓扑合并与补洞...")
            elif "[Phase 04]" in line_str or "Paired-End Jump Scaffolding" in line_str:
                if self.on_progress:
                    self.on_progress(80, "配对跳跃支架构建 (PE Scaffolding)...")
            elif "Solving Graph Laplacian" in line_str or "Disentangling" in line_str:
                if self.on_progress:
                    self.on_progress(40, "连续谱流形相位规约与分子拓扑解缠...")
            elif "SIMD-POA Consensus Engine" in line_str or "Polishing" in line_str:
                if self.on_progress:
                    self.on_progress(75, "SIMD-POA 分层打磨与一致性精修...")
            elif "Scaffolding Complete" in line_str:
                if self.on_progress:
                    self.on_progress(85, "非相交环状支架构建完成...")
            elif "Assembly complete" in line_str or "[SUCCESS]" in line_str or "SUCCESS]" in line_str:
                if self.on_progress:
                    self.on_progress(95, "组装完成，正在整理产物...")

        try:
            returncode = await self.runner.run_command(
                cmd_list,
                cwd=out_dir,
                on_output=ngcs_progress_handler,
                is_shell=False
            )
        except Exception as e:
            self.logger.error(f"NGCS 引擎执行异常: {e}")
            returncode = -1

        # 校验产物
        if returncode == 0 and assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
            self.logger.info(f"NGCS 组装成功生成 FASTA 产物: {assembly_fasta}")
            self.context.update("assembly_fasta", assembly_fasta)
            stats = self._parse_assembly_stats(assembly_fasta)
            self.context.update("assembly_stats", stats)

            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "组装完成")
            return True
        else:
            reason = self._diagnose_failure(out_dir)
            self.last_error = reason
            self.logger.error(f"NGCS 组装未产生有效结果: {reason}")
            if self.on_progress:
                self.on_progress(0, f"Error: {reason}")
            self.status = "failed"
            return False

    def _parse_assembly_stats(self, fasta_path: Path) -> Dict[str, Any]:
        """
        解析 FASTA 产物指标 (加权平均深度、总长度、Contig数、N50、环状标记)
        """
        stats = {
            "total_length": 0,
            "is_circular": False,
            "avg_depth": 0.0,
            "contigs": 0,
            "gc_percent": 0.0,
            "n50": 0
        }
        contig_lengths = []
        total_depth_mass = 0.0
        total_gc = 0
        total_at = 0

        try:
            with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
                current_len = 0
                current_depth = 0.0

                def finish_contig():
                    nonlocal total_depth_mass
                    if current_len > 0:
                        stats["total_length"] += current_len
                        contig_lengths.append(current_len)
                        total_depth_mass += current_depth * current_len

                for line in f:
                    line_str = line.strip()
                    if line_str.startswith(">"):
                        finish_contig()
                        current_len = 0
                        stats["contigs"] += 1
                        header = line_str.lower()

                        # 深度解析
                        depth_match = re.search(r"(?:depth[=]|cov_|cov=)(\d+\.?\d*)", header)
                        current_depth = float(depth_match.group(1)) if depth_match else 1.0

                        # 环状判定
                        if "circular=true" in header or "_circular" in header or "circular" in header:
                            stats["is_circular"] = True
                    else:
                        seq_upper = line_str.upper()
                        current_len += len(seq_upper)
                        total_gc += seq_upper.count("G") + seq_upper.count("C")
                        total_at += seq_upper.count("A") + seq_upper.count("T")

                finish_contig()

            if stats["total_length"] > 0:
                stats["avg_depth"] = round(total_depth_mass / stats["total_length"], 2)
                total_bases = total_gc + total_at
                stats["gc_percent"] = round((total_gc / total_bases * 100.0), 2) if total_bases > 0 else 0.0

                # N50 计算
                contig_lengths.sort(reverse=True)
                half_len = stats["total_length"] / 2.0
                cum_len = 0
                for l in contig_lengths:
                    cum_len += l
                    if cum_len >= half_len:
                        stats["n50"] = l
                        break

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
            except Exception:
                pass

        # 检查日志
        log_candidates = list(out_dir.glob("*.log"))
        for log_f in log_candidates:
            try:
                content = log_f.read_text(encoding="utf-8", errors="ignore")
                if "Out of memory" in content or "bad_alloc" in content:
                    return "硬件内存空间不足，请调小可用线程数"
                if "Insufficient read depth" in content or "too few reads" in content:
                    return "测序深度过低或数据清洗过度"
            except Exception:
                pass

        return "组装过程未生成有效 FASTA 文件，请检查原始数据质量或测序深度"