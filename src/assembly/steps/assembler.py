# -*- coding: utf-8 -*-
"""
AssemblerStep - NGCS 基因组组装核心步骤封装
全面采用 NGCS (Neural Genome Coordinate System) 作为核心拼接引擎。
支持二代 (Native C++20 欧拉残差流) 与 三代 (连续谱流形与 SIMD-POA) 测序数据的高保真组装。
"""

import os
import re
import sys
import gzip
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from ..core.base import BaseAssemblyStep
from ..utils.file_handler import AssemblyFileHandler

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

        # =========================================================================
        # 针对中文路径与空格的 ASCII 安全隔离工作区 (确保 WSL / C++20 引擎 100% 兼容)
        # =========================================================================
        safe_work_dir = Path("E:/NGCS_Work/tasks") / self.context.task_id
        safe_work_dir.mkdir(parents=True, exist_ok=True)

        async def _prepare_safe_input(src_path_str: str, file_tag: str) -> str:
            src_p = Path(src_path_str)
            if not src_p.exists():
                return src_path_str

            # 1. 检测是否为 ZIP 测序归档包 (如内含多分卷 FASTQ 的压缩包)
            if AssemblyFileHandler.is_zip_archive(src_p):
                dst_p = safe_work_dir / f"input_{file_tag}.fastq"
                # 断点保护与缓存复用: 若已生成完整聚合文件且时间晚于源压缩包，直接复用
                if dst_p.exists() and dst_p.stat().st_size > 1024 and dst_p.stat().st_mtime >= src_p.stat().st_mtime:
                    self.logger.info(f"复用已流式聚合的测序数据: {dst_p}")
                    return str(dst_p)

                self.logger.info(f"检测到 ZIP 归档测序数据，启动工作线程流式分片聚合: {src_p.name} -> {dst_p.name}")
                if self.on_progress:
                    self.on_progress(3, f"正在解析测序压缩包: {src_p.name}...")

                def on_extract_progress(p_val: float, desc_txt: str):
                    if self.on_progress:
                        # 映射到准备阶段 (3% - 15%)
                        mapped_val = 3.0 + (p_val / 100.0) * 12.0
                        self.on_progress(round(mapped_val, 1), desc_txt)

                # 关键修复：使用 asyncio.to_thread 放入子线程，绝不阻塞主事件循环与 WebSocket 广播
                success = await asyncio.to_thread(
                    AssemblyFileHandler.extract_and_merge_zip_fastq,
                    src_p, dst_p, on_progress=on_extract_progress
                )
                if success and dst_p.exists() and dst_p.stat().st_size > 0:
                    self.logger.info(f"ZIP 测序数据流式聚合完成，产物大小: {dst_p.stat().st_size / (1024*1024):.2f} MB")
                    return str(dst_p)
                else:
                    self.logger.error(f"ZIP 归档测序数据流式聚合失败: {src_p}")

            # 2. 检测是否含非 ASCII 字符或空格
            needs_isolate = any(ord(c) > 127 for c in src_path_str) or (' ' in src_path_str)
            if not needs_isolate:
                return src_path_str

            suffix = "".join(src_p.suffixes) if src_p.suffixes else ".fq.gz"
            dst_p = safe_work_dir / f"input_{file_tag}{suffix}"
            if dst_p.exists() and dst_p.stat().st_size == src_p.stat().st_size:
                return str(dst_p)

            if dst_p.exists():
                try:
                    dst_p.unlink()
                except Exception:
                    pass

            # 优先尝试硬链接 (同盘符 0 内存 0 耗时)
            try:
                os.link(src_p, dst_p)
                self.logger.info(f"建立安全硬链接: {src_p.name} -> {dst_p}")
                return str(dst_p)
            except Exception:
                pass

            # 跨盘符时流式快速复制
            self.logger.info(f"跨盘符安全数据中转: {src_p.name} -> {dst_p}")
            if self.on_progress:
                self.on_progress(5, f"数据安全准备中 ({file_tag})...")
            import shutil
            await asyncio.to_thread(shutil.copyfile, src_p, dst_p)
            return str(dst_p)

        active_r1 = await _prepare_safe_input(r1, "r1")
        active_r2 = (await _prepare_safe_input(r2, "r2")) if r2 else None

        # 模式配置 (支持 isolate, metagenome, metagenome_deep, unconstrained)
        mode = params.get("mode")
        if not mode or mode not in ["isolate", "metagenome", "metagenome_deep", "unconstrained"]:
            mode = "metagenome" if sample_type in ["PHAGE", "VIRUS", "METAGENOME"] else "isolate"

        # 构建 NGCS CLI 指令
        py_exec = sys.executable
        cmd_list = [py_exec, str(ngcs_cli), "assemble"]

        is_long_read = tech in ["NANOPORE", "PACBIO_HIFI"] or not active_r2
        if is_long_read:
            min_len = str(params.get("min_read_length") or params.get("min_len") or 1000)
            cmd_list.extend([
                "-i", active_r1,
                "-o", str(safe_work_dir),
                "-t", threads_str,
                "--min-len", min_len,
                "--mode", mode
            ])
            self.logger.info(f"NGCS 长读长单分子组装模式: 输入={active_r1}, mode={mode}, min_len={min_len}")
        else:
            cmd_list.extend([
                "-1", active_r1,
                "-2", active_r2,
                "-o", str(safe_work_dir),
                "-t", threads_str,
                "--mode", mode
            ])
            self.logger.info(f"NGCS 短读长双端欧拉流组装模式: R1={active_r1}, R2={active_r2}, mode={mode}")

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

        # 长读长骨架读段控制：仅在显式指定时限制，其余情况交由 NGCS 引擎自适应流控
        if is_long_read:
            max_bb = params.get("max_backbone_reads")
            if max_bb:
                cmd_list.extend(["--max-backbone-reads", str(max_bb)])

        enable_qc = params.get("enable_qc", True)
        if not enable_qc:
            cmd_list.append("--no-qc")

        # 实时日志捕获与进度遥测映射 (区分二代与三代平台，严格单调递增)
        step_local_max_progress = 15.0 if active_r1.endswith(".fastq") else 5.0

        def emit_assembly_progress(target_progress: float, step_desc: str):
            nonlocal step_local_max_progress
            if target_progress > step_local_max_progress:
                step_local_max_progress = target_progress
            if self.on_progress:
                self.on_progress(step_local_max_progress, step_desc)

        def ngcs_progress_handler(line: str):
            line_str = line.strip()
            if not line_str:
                return

            # 1. 每一行控制台原始输出，立即流式广播到前端日志终端 (秒级响应)
            if self.on_log:
                self.on_log(line_str)

            # 2. 依据测序平台精准映射流水线阶段，防止 Banner 配置键值误判与进度跳跃
            if is_long_read:
                # ─── 三代长读长 (Nanopore ONT / PacBio HiFi) 阶梯进度 ───
                # 显式屏蔽启动配置 Banner 行 (如 "Scaffolding : Enabled", "Polish Mode : ...")，防止关键词误触
                if ":" in line_str and any(banner_kw in line_str for banner_kw in ["Scaffolding :", "Polish Mode :", "Assembly Mode :", "Min Contig :"]):
                    pass
                elif "[Phase 01]" in line_str or ("Streamed" in line_str and "clean reads" in line_str):
                    emit_assembly_progress(20, "长读长数据质控与载入...")
                elif "[Phase 02]" in line_str or "Constructing Hardware-Accelerated Overlap Graph" in line_str:
                    emit_assembly_progress(35, "长读长重叠图构建中...")
                elif "Graph Built:" in line_str:
                    emit_assembly_progress(45, "重叠图构建完成，开始拓扑聚类...")
                elif "[Phase 03]" in line_str or "Disentangling Independent Molecular" in line_str:
                    emit_assembly_progress(55, "基因组子图聚类与流形分离...")
                elif "Solving Graph Laplacian" in line_str or "Solving contiguous genomic backbones" in line_str:
                    emit_assembly_progress(65, "重叠图谱分析与骨架排序...")
                elif "Generated" in line_str and "raw contig backbone" in line_str:
                    emit_assembly_progress(75, "骨架延伸完成，提取重叠群...")
                elif "[Phase 04]" in line_str or "Executing Disjoint-Circular Scaffolding" in line_str or "Scaffolding Complete:" in line_str:
                    emit_assembly_progress(80, "重叠群支架连接与环化判断...")
                elif "[Phase 05]" in line_str or "SIMD-POA Consensus Engine" in line_str:
                    emit_assembly_progress(88, "重叠群一致性序列打磨校正...")
                elif "Restored" in line_str and "bp in" in line_str:
                    emit_assembly_progress(92, "序列校正完成，整理最终产物...")
                elif "[Phase 06]" in line_str or "Unified Post-Processing" in line_str or "Post-Processing Complete" in line_str:
                    emit_assembly_progress(95, "全基因组跨流形支架缝合与去冗余 (AssemblyPostProcessor)...")
                elif "Assembly complete" in line_str or "[SUCCESS]" in line_str:
                    emit_assembly_progress(98, "组装完成，生成组装报告与指标...")
            else:
                # ─── 二代短读长双端 (Illumina / MGI) 阶梯进度 ───
                if "[Phase 00a]" in line_str or "Fastp Quality Control" in line_str:
                    emit_assembly_progress(10, "测序数据质控与接头修剪 (Fastp)...")
                elif "[Phase 00b]" in line_str or "Residual Eulerian" in line_str:
                    emit_assembly_progress(25, "K-mer 频数统计与图分解...")
                elif "[Phase 01]" in line_str:
                    emit_assembly_progress(35, "读长流式载入与构建...")
                elif "[Phase 02]" in line_str:
                    emit_assembly_progress(50, "De Bruijn 图构建与欧拉路径求解...")
                elif "[Phase 03]" in line_str or "Dovetail Merging" in line_str:
                    emit_assembly_progress(65, "重叠群延伸与空隙填充...")
                elif "[Phase 04]" in line_str:
                    emit_assembly_progress(80, "配对末端支架构建 (PE Scaffolding)...")
                elif "Scaffolding Complete" in line_str:
                    emit_assembly_progress(90, "支架构建完成，导出重叠群...")
                elif "Assembly complete" in line_str or "[SUCCESS]" in line_str:
                    emit_assembly_progress(98, "组装完成，生成组装报告与指标...")

        # 注入 UTF-8 环境变量与 PYTHONPATH
        run_env = dict(os.environ)
        run_env["PYTHONIOENCODING"] = "utf-8"
        run_env["PYTHONUTF8"] = "1"
        project_ngcs = str(Path("E:/NGCS").resolve())
        orig_pythonpath = os.environ.get("PYTHONPATH", "")
        run_env["PYTHONPATH"] = f"{project_ngcs};{orig_pythonpath}" if orig_pythonpath else project_ngcs

        try:
            returncode = await self.runner.run_command(
                cmd_list,
                cwd=safe_work_dir,
                env=run_env,
                on_output=ngcs_progress_handler,
                is_shell=False
            )
        except Exception as e:
            self.logger.error(f"NGCS 引擎执行异常: {e}")
            returncode = -1

        # 产物同步回写：从 safe_work_dir 复制至 out_dir
        safe_fasta = safe_work_dir / "assembly.fasta"
        if safe_fasta.exists() and safe_fasta.stat().st_size > 0:
            import shutil
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_fasta, assembly_fasta)
            for extra_name in ["assembly_manifest.json", "assembly_stats.json"]:
                extra_src = safe_work_dir / extra_name
                if extra_src.exists():
                    shutil.copyfile(extra_src, out_dir / extra_name)
            qc_dir = safe_work_dir / "qc"
            if qc_dir.exists():
                shutil.copytree(qc_dir, out_dir / "qc", dirs_exist_ok=True)

        # 校验产物
        if returncode == 0 and assembly_fasta.exists() and assembly_fasta.stat().st_size > 0:
            self.logger.info(f"NGCS 组装成功生成 FASTA 产物: {assembly_fasta}")
            self.context.update("assembly_fasta", assembly_fasta)
            stats = self._parse_assembly_stats(assembly_fasta, safe_work_dir)
            self.context.update("assembly_stats", stats)

            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "组装完成")
            return True
        else:
            reason = self._diagnose_failure(safe_work_dir)
            self.last_error = reason
            self.logger.error(f"NGCS 组装未产生有效结果: {reason}")
            if self.on_progress:
                self.on_progress(0, f"Error: {reason}")
            self.status = "failed"
            return False

    def _parse_assembly_stats(self, fasta_path: Path, work_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        统一权威对接 NGCS 引擎产出的 assembly_manifest.json 与 assembly.fasta 指标
        优先直接复用 NGCS 底层计算的真实深度、N50、环状结构与片段指标，杜绝业务层重复造轮子。
        """
        stats = {
            "total_length": 0,
            "is_circular": False,
            "avg_depth": 0.0,
            "contigs": 0,
            "gc_percent": 0.0,
            "n50": 0,
            "max_contig_length": 0
        }
        search_dirs = [fasta_path.parent]
        if work_dir and work_dir not in search_dirs:
            search_dirs.append(work_dir)

        # 1. 权威首选：直接读取 NGCS 拼接引擎生成的 assembly_manifest.json
        for s_dir in search_dirs:
            manifest_file = s_dir / "assembly_manifest.json"
            if manifest_file.exists():
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
                            if stats["avg_depth"] > 0.0:
                                return stats
                except Exception as e:
                    self.logger.warning(f"读取 NGCS Manifest 失败: {e}")

        # 2. 轻量容错兜底：单遍解析 FASTA Header 与基础序列指标
        try:
            contig_lengths = []
            total_depth_mass = 0.0
            total_gc = 0
            total_at = 0
            has_explicit_depth = False

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

                        d_match = re.search(r"(?:depth[=:]|cov[=_:]|coverage[=:])(\d+\.?\d*)", header)
                        if d_match:
                            current_depth = float(d_match.group(1))
                            has_explicit_depth = True
                        else:
                            current_depth = 0.0

                        if "circular=false" in header or "circular=n" in header or "linear" in header:
                            pass
                        elif "circular=true" in header or "circular=y" in header or "topology=circular" in header or "_circular" in header:
                            stats["is_circular"] = True
                    else:
                        seq_upper = line_str.upper()
                        current_len += len(seq_upper)
                        total_gc += seq_upper.count("G") + seq_upper.count("C")
                        total_at += seq_upper.count("A") + seq_upper.count("T")

                finish_contig()

            if stats["total_length"] > 0:
                total_bases = total_gc + total_at
                stats["gc_percent"] = round((total_gc / total_bases * 100.0), 2) if total_bases > 0 else 0.0
                contig_lengths.sort(reverse=True)
                stats["max_contig_length"] = contig_lengths[0] if contig_lengths else 0
                half_len = stats["total_length"] / 2.0
                cum_len = 0
                for l in contig_lengths:
                    cum_len += l
                    if cum_len >= half_len:
                        stats["n50"] = l
                        break
                if has_explicit_depth and total_depth_mass > 0:
                    stats["avg_depth"] = round(total_depth_mass / stats["total_length"], 1)
                else:
                    # 极简容错兜底：若既无 Manifest 又无 Header 显式深度，尝试从工作区测序 FASTQ 采样估算深度
                    candidate_fqs = []
                    for k in ["clean_r1", "r1", "unmerged_r1"]:
                        val = self.context.get(k)
                        if val and Path(str(val)).exists():
                            candidate_fqs.append(Path(str(val)))
                    for s_dir in search_dirs:
                        for p in s_dir.glob("*.fastq*"):
                            if p.is_file() and "assembly" not in p.name.lower():
                                candidate_fqs.append(p)
                        for p in s_dir.glob("*.fq*"):
                            if p.is_file() and "assembly" not in p.name.lower():
                                candidate_fqs.append(p)

                    if candidate_fqs:
                        try:
                            tfq = candidate_fqs[0]
                            is_gz = tfq.suffix == ".gz" or tfq.name.endswith(".fq.gz")
                            opener = gzip.open if is_gz else open
                            t_bases = 0
                            with opener(tfq, "rt", encoding="utf-8", errors="ignore") as fq_f:
                                for q_idx, q_l in enumerate(fq_f):
                                    if q_idx % 4 == 1:
                                        t_bases += len(q_l.strip())
                                    if q_idx >= 40000:
                                        break
                            if t_bases > 0:
                                stats["avg_depth"] = round(t_bases / stats["total_length"], 1)
                        except Exception:
                            pass

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