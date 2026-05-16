import os
import re
import statistics
import shutil
from pathlib import Path
from Bio import SeqIO
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

class ScaffoldingStep(BaseAssemblyStep):
    """
    支架构建步骤 (Academic Enhanced Edition)
    核心特性：
    1. N-Split Indexing: 预切断 Gap 区域，确保 BWA 能够找回跨越 N 区域的 Reads。
    2. MAD-Sigma Model: 基于 1.4826 缩放因子的鲁棒统计学深度检测，防范零除崩溃。
    3. Chimera Defense: 基于 Z-score 的嵌合体拦截与高重复元件 (Repeat) 打标。
    4. Robust DTR: 基于 Biopython 的安全滑动窗口环形拓扑验证。
    """

    @property
    def name(self) -> str:
        return "Scaffolding (支架构建)"

    async def execute(self) -> bool:
        self.status = "running"
        params = self.context.config.get("params", {})
        if not params.get("fill_gaps", True):
            self.logger.info("用户配置跳过补洞步骤")
            self._bypass_step()
            return True

        # 1. 环境准备与数据拉取
        assembly_path = self.context.get("assembly_path") or self.context.get("assembly_fasta")
        r1, r2 = self.context.get("clean_r1") or self.context.get("r1"), self.context.get("clean_r2") or self.context.get("r2")
        
        if not assembly_path or not Path(assembly_path).exists():
            self.logger.warning("未检测到输入序列，跳过 Scaffolding")
            return True

        if self._should_skip_scaffolding(assembly_path):
            self.logger.info("🎉 序列已完美闭合且无 Gap，智能跳过。")
            self.context.update("scaffold_path", assembly_path)
            self.context.update("assembly_fasta", assembly_path)
            return True

        self.logger.info("开始执行学术级支架构建 (Targeted Gap-Closer Mode)...")

        # 3. 申请执行空间 (通过 ShmManager 统一管理)
        wsl_tmp_outdir = await self._prepare_workspace()

        try:
            # 4. 靶向 Reads 捕获 (N-Split 索引策略)
            mapped_r1, mapped_r2 = await self._run_targeted_extraction(
                assembly_path, r1, r2, wsl_tmp_outdir
            )

            # 5. SPAdes Scaffolding 核心调用
            spades_out = f"{wsl_tmp_outdir}/spades_out"
            success = await self._run_spades_scaffolder(assembly_path, mapped_r1, mapped_r2, spades_out)
            
            if not success:
                self.logger.warning("支架构建生成异常，回退使用原始组装产物")
                self.context.update("scaffold_path", assembly_path)
                self.context.update("assembly_fasta", assembly_path)
                return True

            # 6. 后处理：学术提纯与统计学清洗
            final_clean = self.get_working_dir() / "scaffolds.clean.fasta"
            wsl_raw_scaffold = f"{spades_out}/scaffolds.fasta"
            win_raw_scaffold = self.get_working_dir() / "scaffolds.raw.fasta"
            
            await self.runner.run_command(["cp", "-f", wsl_raw_scaffold, str(win_raw_scaffold)])
            
            wsl_graph = f"{spades_out}/assembly_graph_with_scaffolds.gfa"
            win_graph = self.get_working_dir() / "assembly_graph.gfa"
            if await self.runner.run_command(["test", "-f", wsl_graph]) == 0:
                await self.runner.run_command(["cp", "-f", wsl_graph, str(win_graph)])
            
            self.logger.info("启动 MAD-Sigma 深度分布过滤与 DTR 拓扑验证...")
            self._clean_scaffolds_advanced(str(win_raw_scaffold), str(final_clean))

            self.context.update("scaffold_path", str(final_clean))
            self.context.update("assembly_fasta", str(final_clean))
            self.logger.info(f"支架补接圆满完成，最终产物: {final_clean.name}")
            return True
        finally:
            # 确保释放工作空间，杜绝泄漏
            step_key = self.__class__.__name__.lower()
            if self.context.shm:
                await self.context.shm.release(step_key)
            else:
                await self.runner.run_command(["rm", "-rf", wsl_tmp_outdir], silence_errors=True)

    # --- 核心子模块 ---

    async def _run_targeted_extraction(self, ref, r1, r2, tmp_dir):
        """执行 N-Split 索引与精准 Reads 钓取"""
        wsl_ref = WSLManager.to_wsl_path(str(ref))
        wsl_split_fa = f"{tmp_dir}/ref_split.fasta"
        
        # 🔗 终极无敌修复：采用 Base64 编码方式下发 Python 脚本，彻底隔绝任何路径替换或换行符问题
        import base64
        py_script = (
            f"from Bio import SeqIO\n"
            f"seqs = list(SeqIO.parse('{wsl_ref}', 'fasta'))\n"
            f"for s in seqs:\n"
            f"    frags = s.seq.split('N')\n"
            f"    for i, f in enumerate(frags):\n"
            f"        if len(f) > 30: print(f'>{{s.id}}_{{i}}\\n{{f}}')\n"
        )
        b64_str = base64.b64encode(py_script.encode('utf-8')).decode('utf-8')
        split_cmd = f"python3 -c \"import base64; exec(base64.b64decode('{b64_str}').decode('utf-8'))\" > {wsl_split_fa}"
        await self.runner.run_command(split_cmd, is_shell=True)
        
        bwa_idx = f"{tmp_dir}/idx"
        m_r1, m_r2 = f"{tmp_dir}/t_R1.fq", f"{tmp_dir}/t_R2.fq"
        
        await self.runner.run_command(["bwa", "index", "-p", bwa_idx, wsl_split_fa])
        
        # 线程优化与学术掩码: -F 2304 (排除 Secondary & Supplementary)
        total_threads = max(2, (os.cpu_count() or 8) - 1)
        bwa_t = max(1, int(total_threads * 0.75))
        sam_t = max(1, total_threads - bwa_t)

        bam_file = f"{tmp_dir}/mapped.bam"
        bwa_cmd = f"bwa mem -t {bwa_t} '{bwa_idx}' '{WSLManager.to_wsl_path(str(r1))}' '{WSLManager.to_wsl_path(str(r2))}' | samtools view -@ {sam_t} -b - > '{bam_file}'"
        self.logger.info("🎣 正在靶向比对跨 Gap 区域 Reads (第一阶段: bwa mem -> bam)...")
        await self.runner.run_command(bwa_cmd, is_shell=True)
        
        extract_cmd = (
            f"samtools fastq -@ {sam_t} -F 2304 -G 12 -1 '{m_r1}' -2 '{m_r2}' -s /dev/null -0 /dev/null '{bam_file}'"
        )
        self.logger.info("🎣 正在靶向钓取跨 Gap 区域 Reads (-F 2304)...")
        await self.runner.run_command(extract_cmd, is_shell=True)
        
        return m_r1, m_r2

    async def _run_spades_scaffolder(self, ref, m_r1, m_r2, outdir) -> bool:
        """调用 SPAdes 仅执行 Scaffolding"""
        total_gb = await self.get_total_memory_gb()
        max_mem = self.context.config.get("max_memory") or int(total_gb * 0.7)
        optimal_threads = max(1, (os.cpu_count() or 8) - 1)

        cmd = [
            "spades.py", "--trusted-contigs", WSLManager.to_wsl_path(str(ref)),
            "-1", m_r1, "-2", m_r2,
            "-o", outdir, "--only-assembler",
            "-m", str(max_mem), "-t", str(optimal_threads)
        ]
        ret = await self.runner.run_command(cmd)
        
        # 验证产物
        shm_scaffold = f"{outdir}/scaffolds.fasta"
        res_check = await self.runner.run_command(["ls", shm_scaffold])
        return ret == 0 and res_check == 0

    def _clean_scaffolds_advanced(self, input_fa, output_fa):
        """基于 MAD-Sigma 统计模型的清洗算法"""
        try:
            records = list(SeqIO.parse(input_fa, "fasta"))
            if not records:
                shutil.copy2(input_fa, output_fa)
                return
            
            # 1. 动态特征提取
            max_len = max(len(r.seq) for r in records)
            # 提升 len_cutoff，确保 main_cov 由真正的主序列决定，而不是被大量小碎片带偏
            len_cutoff = max(5000, int(0.05 * max_len))
            
            # 2. 深度统计建模 (MAD 1.4826)
            covs = []
            for r in records:
                m = re.search(r"cov_([\d\.]+)", r.description)
                if m and len(r.seq) >= len_cutoff: 
                    covs.append(float(m.group(1)))
            
            if covs:
                med_cov = statistics.median(covs)
                mad = statistics.median([abs(c - med_cov) for c in covs])
                sigma = max(1.4826 * mad, 0.05 * med_cov) 
                
                # 🚨 修复：基准深度绝对不能取 max(covs)，否则会被高拷贝质粒或折叠重复序列带偏！
                # 必须使用中位数，它能稳健地代表主体基因组的真实深度。
                main_cov = med_cov
            else:
                # 若没有符合长度条件的序列，退化为取所有序列中位深度
                all_covs = [float(m.group(1)) for r in records if (m := re.search(r"cov_([\d\.]+)", r.description))]
                main_cov = statistics.median(all_covs) if all_covs else 1.0
                sigma = max(0.5 * main_cov, 0.1)

            # 统一计算噪音阈值：主体深度的 15%，保底 3x
            noise_threshold = max(3.0, main_cov * 0.15) if main_cov > 10 else 1.0
            clean_records = []
            
            for r in records:
                if len(r.seq) < 1000: 
                    continue # 抛弃绝对无意义的短片段，将底线从 300bp 提升至 1000bp
                
                m = re.search(r"cov_([\d\.]+)", r.description)
                c = float(m.group(1)) if m else 0.0
                z_score = abs(c - main_cov) / sigma
                
                # 动态短片段阈值 (例如最长 174kb，则阈值约 8.7kb，保底 2000bp)
                base_len_threshold = max(2000, int(0.05 * max_len))
                
                # A. 低深度噪音拦截：使用严谨的统计相对阈值 (15% main_cov)
                if c < noise_threshold and len(r.seq) < base_len_threshold:
                    self.logger.warning(f"🚫 拦截低深度杂质: {r.id} ({c}x < {noise_threshold:.1f}x)")
                    continue
                
                # B. 高深度短杂质拦截：放宽至 3.5 倍，防错杀噬菌体末端长反向重复序列等正常元件
                if c > (main_cov * 3.5) and len(r.seq) < base_len_threshold:
                    self.logger.warning(f"🚫 拦截高深度重复小片段: {r.id} ({c}x > {main_cov * 3.5:.1f}x)")
                    continue

                if c < (noise_threshold * 0.5) and len(r.seq) < (0.5 * max_len): # 对于稍长一点的序列，阈值进一步放宽
                    continue
                
                # B. Z-score 打标 (高深度嵌合或重复序列预警)
                if main_cov > 10.0 and z_score > 3.5 and c > main_cov:
                    r.description += f" [Repeat_Candidate|Z={z_score:.1f}]"
                
                # C. 环形验证 (DTR Check)
                if len(r.seq) > 2000 and "circular=true" not in r.description.lower():
                    seq_str = str(r.seq).upper()
                    head_seed = seq_str[:100]
                    # 防止由于序列短于 3000bp 导致 tail_region 包含 head_seed
                    tail_region_start = max(100, len(seq_str) - 3000)
                    tail_region = seq_str[tail_region_start:]
                    
                    if head_seed in tail_region:
                        pos = tail_region.find(head_seed)
                        overlap = len(tail_region) - pos
                        r.description += f" [circular_verified:DTR={overlap}bp]"
                        self.logger.info(f"⭕ 已验证 DTR 环形拓扑: {r.id} (Overlap={overlap}bp)")
                
                clean_records.append(r)
                
            SeqIO.write(clean_records, output_fa, "fasta")
            self.logger.info(f"✨ Scaffolding 清洗完成: 原始={len(records)}, 保留={len(clean_records)}, 基准深度={main_cov:.1f}x")
            
        except Exception as e:
            self.logger.error(f"❌ 产物清洗抛出异常: {e}")
            shutil.copy2(input_fa, output_fa)

    # --- 辅助工具函数 ---
    def _should_skip_scaffolding(self, path) -> bool:
        """检查是否真的无需补洞"""
        try:
            with open(path, "r", encoding='utf-8') as f:
                content = f.read()
            has_n = "N" in content.upper()
            contig_count = content.count(">")
            return contig_count == 1 and not has_n
        except Exception:
            return False

    async def _prepare_workspace(self) -> str:
        """申请最佳流水线工作空间 (优先 SHM)"""
        target_dir = await self.get_best_wsl_tmp_dir(required_gb=12.0)
        
        # 🔗 核心修复：确保目录清空
        await self.runner.run_command(["rm", "-rf", target_dir])
        await self.runner.run_command(["mkdir", "-p", target_dir])
        return target_dir

    def _bypass_step(self):
        fallback = self.context.get("assembly_path") or self.context.get("assembly_fasta")
        if fallback:
            self.context.update("scaffold_path", fallback)
            self.context.update("assembly_fasta", fallback)
        return False