
import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

logger = logging.getLogger("Assembly.ProphageSeparator")


class ProphageSeparatorStep(BaseAssemblyStep):
    """
    溶源噬菌体分离步骤 — 双引擎前噬菌体检测与序列提取

    工作模式:
      A) PhiSpy 路径 — 从宿主全基因组中精确定位前噬菌体区域
      B) VIBRANT 路径 — 从 de novo 组装 contigs 中识别并分箱噬菌体序列
      C) 交叉验证 — 综合两条路径结果，输出纯化的噬菌体基因组

    触发条件:
      - 用户提供了宿主菌全基因组 (host_genome 参数)
      - sample_type == "PHAGE"

    插入位置:
      - AssemblerStep 之后, ScaffoldingStep 之前
    """

    @property
    def name(self) -> str:
        return "Prophage Separation (PhiSpy + VIBRANT)"

    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        final_fasta = out_dir / "separated_phage.fasta"
        if final_fasta.exists() and final_fasta.stat().st_size > 0:
            self.context.update("assembly_fasta", final_fasta)
            return True
        return False

    async def execute(self) -> bool:
        self.status = "running"

        # ─── 0. 参数收集 ───
        host_genome = self.context.config.get("params", {}).get("host_genome")
        assembly_fasta = self.context.get("assembly_fasta")

        if not assembly_fasta or not Path(assembly_fasta).exists():
            self.logger.error("未找到组装产物 (assembly_fasta)，无法执行前噬菌体检测")
            self.status = "failed"
            return False

        out_dir = self.get_working_dir()
        cpu_count = os.cpu_count() or 8
        threads = max(1, cpu_count - 1)

        # 结果收集器
        phispy_regions: List[Dict] = []
        vibrant_phage_contigs: List[str] = []

        # ─── 1. PhiSpy 路径: 从宿主基因组检测前噬菌体 ───
        if host_genome and Path(host_genome).exists():
            if self.on_progress:
                self.on_progress(5, "PhiSpy: 正在从宿主基因组中检测前噬菌体区域...")
            phispy_regions = await self._run_phispy(
                host_genome_path=Path(host_genome),
                work_dir=out_dir,
                threads=threads
            )
            self.logger.info(f"📊 PhiSpy 检测到 {len(phispy_regions)} 个前噬菌体区域")
        else:
            self.logger.info("未提供宿主基因组，跳过 PhiSpy 路径")

        # ─── 1.5 后置宿主 Contig 级过滤 (溶源模式专属) ───
        # 🚨 审计修复：当 is_lysogenic=True 导致跳过了 Kraken2 读段剔除，
        # 组装器产物中会包含大量的纯宿主 Contigs（可能占 90%+）。
        # 必须在分箱之前先用 Minimap2 做一次 Contig 级的物理大扫除，
        # 否则 VIBRANT/VirSorter2 的 HMM 会被海量宿主序列淹没导致漏检。
        is_lysogenic = self.context.config.get("params", {}).get("is_lysogenic", False)
        if is_lysogenic and host_genome and Path(host_genome).exists():
            if self.on_progress:
                self.on_progress(35, "后置宿主大扫除: Minimap2 剔除宿主级 Contigs...")
            
            pre_filter_fasta = out_dir / "pre_vibrant_filtered.fasta"
            host_removed = await self._bwa_subtract_host(
                assembly_fasta=Path(assembly_fasta),
                host_fasta=Path(host_genome),
                output_fasta=pre_filter_fasta,
                threads=threads
            )
            if host_removed and pre_filter_fasta.exists() and pre_filter_fasta.stat().st_size > 0:
                self.logger.info(f"🧹 后置宿主过滤完成, 剩余纯候选序列用于 VIBRANT 分箱")
                assembly_fasta = pre_filter_fasta
            else:
                self.logger.warning("后置宿主过滤未生效，使用原始组装产物继续")

        # ─── 2. VIBRANT 路径: 从组装 contigs 中识别噬菌体 ───
        if self.on_progress:
            self.on_progress(40, "VIBRANT: 正在对组装 contigs 进行噬菌体分箱...")
        vibrant_phage_contigs = await self._run_vibrant(
            assembly_path=Path(assembly_fasta),
            work_dir=out_dir,
            threads=threads
        )
        self.logger.info(f"📊 VIBRANT 识别到 {len(vibrant_phage_contigs)} 条噬菌体 contig")

        # ─── 3. 交叉验证与序列提取 ───
        if self.on_progress:
            self.on_progress(80, "正在执行交叉验证与最终序列提取...")

        final_fasta = out_dir / "separated_phage.fasta"
        success = await self._merge_and_extract(
            assembly_path=Path(assembly_fasta),
            host_genome_path=Path(host_genome) if host_genome else None,
            phispy_regions=phispy_regions,
            vibrant_contigs=vibrant_phage_contigs,
            output_fasta=final_fasta,
            work_dir=out_dir,
            threads=threads
        )

        if success and final_fasta.exists() and final_fasta.stat().st_size > 0:
            # 更新上下文：后续步骤使用纯化后的噬菌体基因组
            self.context.update("assembly_fasta", final_fasta)
            self.context.update("original_assembly", assembly_fasta)
            self.context.update("prophage_separation", {
                "phispy_regions": len(phispy_regions),
                "vibrant_contigs": len(vibrant_phage_contigs),
                "final_contigs": self._count_contigs(final_fasta),
                "method": "PhiSpy+VIBRANT" if phispy_regions else "VIBRANT"
            })

            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "前噬菌体分离完成")
            return True

        # 降级处理：如果分离失败，保留原始组装
        self.logger.warning("⚠️ 前噬菌体分离未产生有效结果，保留原始组装产物")
        self.status = "completed"
        if self.on_progress:
            self.on_progress(100, "跳过分离 (降级保留原始组装)")
        return True  # 不阻塞流水线

    # ═══════════════════════════════════════════
    #  Engine 1: PhiSpy — 宿主基因组前噬菌体检测
    # ═══════════════════════════════════════════

    async def _run_phispy(self, host_genome_path: Path, work_dir: Path,
                          threads: int) -> List[Dict]:
        """
        使用 PhiSpy 从宿主全基因组中检测前噬菌体区域

        PhiSpy 需要 GenBank 格式输入，所以先用 Prokka/Prodigal 注释宿主
        """
        regions = []
        phispy_dir = work_dir / "phispy_out"
        phispy_dir.mkdir(parents=True, exist_ok=True)

        wsl_host = WSLManager.to_wsl_path(str(host_genome_path))
        wsl_out = WSLManager.to_wsl_path(str(phispy_dir))

        # Step 1: 快速注释宿主基因组 (Prokka → GenBank)
        prokka_dir = work_dir / "prokka_host"
        prokka_dir.mkdir(parents=True, exist_ok=True)
        wsl_prokka = WSLManager.to_wsl_path(str(prokka_dir))

        if self.on_progress:
            self.on_progress(10, "PhiSpy: 正在注释宿主基因组 (Prokka)...")

        # 检查 Prokka 是否可用
        has_prokka = (await self.runner.run_command(["which", "prokka"], silence_errors=True)) == 0
        gbk_file = None

        if has_prokka:
            prokka_cmd = [
                "prokka", "--outdir", wsl_prokka, "--prefix", "host",
                "--cpus", str(threads), "--force", "--fast",
                "--kingdom", "Bacteria", wsl_host
            ]
            ret = await self.runner.run_command(prokka_cmd, is_shell=True)
            if ret == 0:
                gbk_file = prokka_dir / "host.gbk"
        else:
            # 降级: 使用 Prodigal + 自构建 GBK
            self.logger.info("Prokka 不可用，降级使用 Prodigal 进行简化注释")
            gbk_file = await self._prodigal_to_gbk(
                host_genome_path, work_dir / "prodigal_host", threads
            )

        if not gbk_file or not gbk_file.exists():
            self.logger.warning("宿主注释失败，跳过 PhiSpy")
            return regions

        # Step 2: 运行 PhiSpy
        if self.on_progress:
            self.on_progress(20, "PhiSpy: 正在检测前噬菌体区域...")

        has_phispy = (await self.runner.run_command(["which", "phispy"], silence_errors=True)) == 0
        if not has_phispy:
            # 尝试通过 Python 模块调用
            has_phispy = (await self.runner.run_command(
                ["python3", "-c", "import PhiSpyModules"],
                silence_errors=True
            )) == 0

        if has_phispy:
            wsl_gbk = WSLManager.to_wsl_path(str(gbk_file))
            phispy_cmd = [
                "phispy", wsl_gbk, "-o", wsl_out,
                "--threads", str(threads),
                "--phage_genes", "1",   # 最低阈值，提高敏感度
                "--output_choice", "5"  # 输出所有格式
            ]
            ret = await self.runner.run_command(phispy_cmd, is_shell=True)
            if ret == 0:
                regions = self._parse_phispy_output(phispy_dir)
        else:
            self.logger.warning("PhiSpy 不可用，跳过宿主前噬菌体检测")

        return regions

    async def _prodigal_to_gbk(self, fasta_path: Path, work_dir: Path,
                                threads: int) -> Optional[Path]:
        """
        降级方案：Prodigal 注释 + 手动构建 GenBank 文件
        """
        work_dir.mkdir(parents=True, exist_ok=True)

        wsl_fasta = WSLManager.to_wsl_path(str(fasta_path))
        wsl_out = WSLManager.to_wsl_path(str(work_dir))
        gff_file = f"{wsl_out}/host.gff"
        faa_file = f"{wsl_out}/host.faa"

        ret = await self.runner.run_command([
            "prodigal", "-i", wsl_fasta,
            "-o", gff_file, "-f", "gff",
            "-a", faa_file, "-p", "single"
        ])

        if ret != 0:
            return None

        # 使用 BioPython 将 FASTA+GFF 转为简化 GBK
        try:
            gbk_path = work_dir / "host.gbk"
            self._fasta_gff_to_gbk(fasta_path, work_dir / "host.gff", gbk_path)
            return gbk_path
        except Exception as e:
            self.logger.warning(f"GBK 转换失败: {e}")
            return None

    def _fasta_gff_to_gbk(self, fasta_path: Path, gff_path: Path,
                           output_path: Path):
        """
        将 FASTA + Prodigal GFF3 合并为简化 GenBank 格式
        供 PhiSpy 使用
        """
        from Bio import SeqIO
        from Bio.SeqRecord import SeqRecord
        from Bio.SeqFeature import SeqFeature, FeatureLocation

        # 解析 FASTA
        records = {}
        for rec in SeqIO.parse(str(fasta_path), "fasta"):
            rec.annotations["molecule_type"] = "DNA"
            records[rec.id] = rec

        # 解析 GFF (Prodigal 输出)
        if gff_path.exists():
            with open(gff_path, "r") as gf:
                for line in gf:
                    if line.startswith("#"):
                        continue
                    parts = line.strip().split("\t")
                    if len(parts) < 9:
                        continue
                    seq_id = parts[0]
                    feat_type = parts[2]
                    start = int(parts[3]) - 1  # GFF 1-based → 0-based
                    end = int(parts[4])
                    strand_char = parts[6]
                    strand = 1 if strand_char == "+" else -1

                    if seq_id in records and feat_type == "CDS":
                        feature = SeqFeature(
                            FeatureLocation(start, end, strand=strand),
                            type="CDS"
                        )
                        records[seq_id].features.append(feature)

        # 写出 GenBank
        with open(output_path, "w") as out:
            SeqIO.write(list(records.values()), out, "genbank")

    def _parse_phispy_output(self, phispy_dir: Path) -> List[Dict]:
        """
        解析 PhiSpy 输出的前噬菌体区域
        主要解析 prophage_coordinates.tsv
        """
        regions = []
        coord_file = phispy_dir / "prophage_coordinates.tsv"

        if not coord_file.exists():
            # 尝试备选文件名
            for alt in ["prophage.tsv", "prophage_tbl.tsv"]:
                alt_path = phispy_dir / alt
                if alt_path.exists():
                    coord_file = alt_path
                    break

        if not coord_file.exists():
            return regions

        try:
            with open(coord_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#") or line.startswith("Prophage"):
                        continue
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        regions.append({
                            "prophage_id": parts[0] if len(parts) > 0 else "pp1",
                            "contig": parts[1] if len(parts) > 1 else "",
                            "start": int(parts[2]) if len(parts) > 2 else 0,
                            "end": int(parts[3]) if len(parts) > 3 else 0,
                        })
        except Exception as e:
            self.logger.warning(f"解析 PhiSpy 输出失败: {e}")

        return regions

    # ═══════════════════════════════════════════
    #  Engine 2: VIBRANT — 组装 Contigs 噬菌体分箱
    # ═══════════════════════════════════════════

    async def _run_vibrant(self, assembly_path: Path, work_dir: Path,
                           threads: int) -> List[str]:
        """
        使用 VIBRANT 对组装产物进行噬菌体识别与分箱
        
        VIBRANT 输出分为:
          - phages_combined/  噬菌体 contigs
          - prophages_combined/  前噬菌体区域
        """
        phage_contigs = []
        # 通过 ShmManager 申请工作空间 (优先内存盘加速 HMM 搜索)
        if self.context.shm:
            ws = await self.context.shm.acquire_manual("vibrant", required_gb=4.0)
            shm_dir = ws.path
        else:
            shm_id = f"vibrant_{os.urandom(4).hex()}"
            shm_dir = f"/dev/shm/{shm_id}"
            await self.runner.run_command(["mkdir", "-p", shm_dir])
        
        vibrant_dir = work_dir / "vibrant_out"
        vibrant_dir.mkdir(parents=True, exist_ok=True)

        wsl_assembly = WSLManager.to_wsl_path(str(assembly_path))
        wsl_vibrant_shm = shm_dir

        # 检查 VIBRANT 是否可用
        has_vibrant = (await self.runner.run_command(
            ["which", "VIBRANT_run.py"],
            silence_errors=True
        )) == 0

        if not has_vibrant:
            has_vibrant = (await self.runner.run_command(
                ["which", "vibrant"],
                silence_errors=True
            )) == 0

        if not has_vibrant:
            self.logger.info("VIBRANT 不可用，尝试使用 VirSorter2 作为替代")
            return await self._run_virsorter2_fallback(
                assembly_path, work_dir, threads
            )

        vibrant_cmd_name = "VIBRANT_run.py"
        if (await self.runner.run_command(["which", "vibrant"], silence_errors=True)) == 0:
            vibrant_cmd_name = "vibrant"

        db_path = await self._detect_vibrant_db_path()

        vibrant_cmd = [
            vibrant_cmd_name,
            "-i", wsl_assembly,
            "-folder", wsl_vibrant_shm,
            "-t", str(threads),
            "-l", "1000",       # 最小 contig 长度
            "-virome"           # 噬菌体富集模式
        ]
        if db_path:
            vibrant_cmd.extend(["-d", db_path])
            self.logger.info(f"📂 VIBRANT 数据库路径: {db_path}")

        try:
            self.logger.info("🚀 正在内存盘中运行 VIBRANT...")
            ret = await self.runner.run_command(vibrant_cmd, is_shell=True)
            
            # 运行结束后将结果拷回物理磁盘
            if ret == 0:
                await self.runner.run_command(["cp", "-a", f"{shm_dir}/.", WSLManager.to_wsl_path(str(vibrant_dir))])
        finally:
            if self.context.shm:
                await self.context.shm.release("vibrant")
            else:
                await self.runner.run_command(["rm", "-rf", shm_dir])

        # 🔗 检测 VIBRANT 数据库缺失的静默失败
        vibrant_log = None
        for log_file in vibrant_dir.rglob("VIBRANT_log_*.log"):
            vibrant_log = log_file
            break
        if vibrant_log and vibrant_log.exists():
            log_text = vibrant_log.read_text(encoding='utf-8', errors='ignore')
            if "could not identify KEGG HMM" in log_text or "could not identify" in log_text:
                self.logger.warning(
                    "⚠️ VIBRANT 数据库路径不正确 (KEGG HMM 未找到)！"
                    "请确认 conda 环境中 VIBRANT 数据库已正确安装。"
                )
                return phage_contigs  # 返回空列表

        if ret == 0:
            phage_contigs = self._parse_vibrant_output(vibrant_dir, assembly_path)

        return phage_contigs

    async def _detect_vibrant_db_path(self) -> Optional[str]:
        """
        自动探测 VIBRANT KEGG HMM 数据库路径
        使用 test -f 逐一检测已知路径 + VDB_FOUND: 标记前缀防止 WSL 乱码污染
        """
        # 按优先级逐一检测：直接 test -f 最可靠，避免 glob/find/for 在 WSL runner 中的问题
        candidate_paths = [
            "/root/.conda/envs/vibrant/share/vibrant-1.2.1/db/databases",
            "/root/.conda/envs/vibrant/share/vibrant-1.2.0/db/databases",
            "/opt/miniconda3/envs/vibrant/share/vibrant-1.2.1/db/databases",
            "/opt/miniconda3/envs/vibrant/share/vibrant-1.2.0/db/databases",
        ]

        for candidate in candidate_paths:
            out_lines = []
            def collect(line, _out=out_lines):
                stripped = line.strip()
                if stripped.startswith("VDB_FOUND:"):
                    _out.append(stripped[len("VDB_FOUND:"):])

            await self.runner.run_command(
                ["bash", "-c",
                 f'test -f "{candidate}/KEGG_profiles.hmm" '
                 f'&& echo "VDB_FOUND:{candidate}" '
                 f'|| true'],
                on_output=collect, silence_errors=True
            )

            if out_lines and out_lines[0]:
                db_path = out_lines[0]
                self.logger.info(f"✅ 自动探测到 VIBRANT 数据库: {db_path}")
                return db_path

        self.logger.warning("⚠️ 未能自动探测 VIBRANT 数据库路径，将使用 VIBRANT 默认值")
        return None

    async def _run_virsorter2_fallback(self, assembly_path: Path,
                                       work_dir: Path,
                                       threads: int) -> List[str]:
        """
        VirSorter2 降级方案 — 当 VIBRANT 不可用时启用
        """
        has_vs2 = (await self.runner.run_command(["which", "virsorter"], silence_errors=True)) == 0
        if not has_vs2:
            self.logger.warning("VIBRANT 与 VirSorter2 均不可用，跳过 contig 分箱")
            return []

        vs2_dir = work_dir / "virsorter2_out"
        vs2_dir.mkdir(parents=True, exist_ok=True)

        wsl_assembly = WSLManager.to_wsl_path(str(assembly_path))
        wsl_vs2 = WSLManager.to_wsl_path(str(vs2_dir))

        cmd = [
            "virsorter", "run",
            "-i", wsl_assembly,
            "-w", wsl_vs2,
            "--include-groups", "dsDNAphage,ssDNA,NCLDV,RNA,lavidaviridae",
            "-j", str(threads),
            "--min-length", "1000",
            "--min-score", "0.5"
        ]

        ret = await self.runner.run_command(cmd, is_shell=True)
        if ret != 0:
            return []

        # 解析 VirSorter2 输出
        phage_ids = []
        score_file = vs2_dir / "final-viral-score.tsv"
        if score_file.exists():
            with open(score_file, "r") as f:
                for line in f:
                    if line.startswith("seqname"):
                        continue
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        try:
                            score = float(parts[2])
                            if score >= 0.5:
                                phage_ids.append(parts[0])
                        except ValueError:
                            continue

        return phage_ids

    def _parse_vibrant_output(self, vibrant_dir: Path,
                               assembly_path: Path) -> List[str]:
        """
        解析 VIBRANT 输出，提取被判定为噬菌体的 contig ID
        """
        phage_ids = []
        stem = assembly_path.stem  # e.g., "assembly"

        # VIBRANT 输出目录结构:
        #   VIBRANT_{stem}/VIBRANT_phages_{stem}/
        possible_dirs = [
            vibrant_dir / f"VIBRANT_{stem}" / f"VIBRANT_phages_{stem}",
            vibrant_dir / f"VIBRANT_phages_{stem}",
        ]

        # 搜索噬菌体 FASTA
        phage_fasta = None
        for d in possible_dirs:
            candidate = d / f"{stem}.phages_combined.fna"
            if candidate.exists():
                phage_fasta = candidate
                break

        if not phage_fasta:
            # 广度搜索
            for fasta_file in vibrant_dir.rglob("*.phages_combined.fna"):
                phage_fasta = fasta_file
                break

        if phage_fasta and phage_fasta.exists():
            with open(phage_fasta, "r") as f:
                for line in f:
                    if line.startswith(">"):
                        contig_id = line[1:].strip().split()[0]
                        # 去除 VIBRANT 添加的后缀
                        clean_id = re.sub(
                            r'_fragment_\d+$|_prophage$', '', contig_id
                        )
                        phage_ids.append(clean_id)

        return phage_ids

    # ═══════════════════════════════════════════
    #  Stage 3: 交叉验证与最终序列提取
    # ═══════════════════════════════════════════

    async def _merge_and_extract(
        self,
        assembly_path: Path,
        host_genome_path: Optional[Path],
        phispy_regions: List[Dict],
        vibrant_contigs: List[str],
        output_fasta: Path,
        work_dir: Path,
        threads: int
    ) -> bool:
        """
        综合 PhiSpy + VIBRANT 结果，提取最终噬菌体基因组

        核心策略 (优先级从高到低):
        1. 如果 VIBRANT 识别到噬菌体 contigs → 从组装产物中提取
        2. 如果组装产物已包含高深度/环形的完整噬菌体序列 → 直接采纳
           (PhiSpy 切片仅作为补充参考，不替代完整组装)
        3. 仅在组装产物不含噬菌体特征时才降级使用 PhiSpy 切割
        """
        extracted_seqs = []

        try:
            from Bio import SeqIO

            # ─── 预分析: 动态深度对齐识别 (解决 140kb 碎裂导致被误删的问题) ───
            assembly_contigs = list(SeqIO.parse(str(assembly_path), "fasta"))
            
            # 1. 寻找“锚定片段” (最高深度的长片段)
            anchor_depth = 0.0
            for rec in assembly_contigs:
                d = self._parse_depth_from_header(rec.description)
                if len(rec.seq) > 5000 and d > anchor_depth:
                    anchor_depth = d
            
            self.logger.info(f"🔍 识别到主噬菌体锚定深度: {anchor_depth:.2f}x")
            
            high_quality_phage_contigs = []
            for rec in assembly_contigs:
                depth = self._parse_depth_from_header(rec.description)
                is_circular = "circular=true" in rec.description.lower()
                seq_len = len(rec.seq)
                
                # 🛡️ 核心修复逻辑：
                # 只要满足以下任一条件即判定为噬菌体组件：
                #   a) 被 VIBRANT 显式标记 (后续 set 匹配)
                #   b) 深度与锚定片段接近 (70%~150%) 且长度 > 1.5kb (防止引物二聚体干扰)
                #   c) 或者是超长片段 (> 10kb) 且具有基本深度
                
                depth_ratio = (depth / anchor_depth) if anchor_depth > 0 else 0
                is_depth_matched = 0.7 <= depth_ratio <= 1.5
                
                if (is_depth_matched and seq_len > 1500) or (depth >= 1.0 and (is_circular or seq_len > 10000)):
                    high_quality_phage_contigs.append({
                        "rec": rec, "depth": depth,
                        "circular": is_circular, "len": seq_len,
                        "reason": "depth_match" if is_depth_matched else "structural"
                    })

            # ─── A. 从组装产物提取 VIBRANT 标记的噬菌体 contigs ───
            if vibrant_contigs:
                vibrant_set = set(vibrant_contigs)
                def _get_base_id(full_id):
                    return re.sub(r'_fragment_\d+$|_prophage$|(_\d+)?_circular$', '', full_id)
                clean_vibrant_set = { _get_base_id(vid) for vid in vibrant_set }

                for rec in assembly_contigs:
                    clean_rec_id = _get_base_id(rec.id)
                    if clean_rec_id in clean_vibrant_set:
                        extracted_seqs.append(rec)
                        self.logger.info(f"  ✅ VIBRANT 提取: {rec.id} ({len(rec.seq)} bp)")

            # ─── B. 深度与结构特征回收 (解决截断问题的核心) ───
            if high_quality_phage_contigs:
                current_ids = {rec.id for rec in extracted_seqs}
                for c in high_quality_phage_contigs:
                    if c["rec"].id not in current_ids:
                        extracted_seqs.append(c["rec"])
                        reason_str = "深度对齐" if c["reason"] == "depth_match" else "结构特征"
                        self.logger.info(
                            f"  🛡️ 组件回收 ({reason_str}): {c['rec'].id} "
                            f"({c['len']}bp, depth={c['depth']:.2f}x)"
                        )

            # PhiSpy 结果仅记录为诊断参考
            if phispy_regions:
                self.logger.info(
                    f"  📋 PhiSpy 区域监测: 在宿主中检测到 {len(phispy_regions)} 个潜在前噬菌体点位"
                )

            # ─── C. 仅当无 VIBRANT 且无高置信组装时，使用 PhiSpy 切割 ───
            if not extracted_seqs and phispy_regions and host_genome_path and host_genome_path.exists():
                host_seqs = {
                    rec.id: rec
                    for rec in SeqIO.parse(str(host_genome_path), "fasta")
                }

                for region in phispy_regions:
                    contig_id = region["contig"]
                    start = region["start"]
                    end = region["end"]

                    if contig_id in host_seqs:
                        host_rec = host_seqs[contig_id]
                        # 安全边界检查
                        start = max(0, start)
                        end = min(len(host_rec.seq), end)

                        if end - start > 5000:  # 至少 5kb 才有意义
                            from Bio.SeqRecord import SeqRecord
                            from Bio.Seq import Seq

                            prophage_seq = SeqRecord(
                                Seq(str(host_rec.seq[start:end])),
                                id=f"prophage_{region['prophage_id']}_{contig_id}_{start}_{end}",
                                description=f"PhiSpy prophage region [{start}-{end}] from {contig_id}"
                            )
                            extracted_seqs.append(prophage_seq)
                            self.logger.info(
                                f"  ✅ PhiSpy 切割 (降级): {contig_id}[{start}-{end}] "
                                f"({end - start} bp)"
                            )

            # ─── D. 如果没有任何分离结果，使用深度感知策略 ───
            if not extracted_seqs:
                is_lysogenic = self.context.config.get("params", {}).get("is_lysogenic", False)

                if is_lysogenic or (host_genome_path and host_genome_path.exists()):
                    self.logger.info(
                        "PhiSpy+VIBRANT 均无结果，启用深度感知保留策略"
                    )
                    depth_seqs = self._extract_by_depth(
                        assembly_path, host_genome_path, phispy_regions
                    )
                    if depth_seqs:
                        extracted_seqs.extend(depth_seqs)
                    else:
                        # 最终降级: 仅保留高深度的组装条目，拒绝所有长度或深度不足的垃圾数据
                        threshold = 4.0 # 提高门槛
                        self.logger.warning(
                            f"深度感知策略失效，启动高置信降级方案 (Threshold={threshold}x)..."
                        )
                        for rec in assembly_contigs:
                            depth = self._parse_depth_from_header(rec.description)
                            if depth >= threshold and len(rec.seq) >= 1500:
                                extracted_seqs.append(rec)
                                self.logger.info(f"  📥 降级保留 (高深度条目): {rec.id} ({depth}x)")
                elif host_genome_path and host_genome_path.exists():
                    self.logger.info(
                        "PhiSpy+VIBRANT 均无结果，降级使用 BWA 比对去宿主"
                    )
                    return await self._bwa_subtract_host(
                        assembly_path, host_genome_path, output_fasta, threads
                    )

            # ─── E. 去冗余并写出最终结果 ───
            if extracted_seqs:
                # 简单去冗余：按序列长度降序，去除 ID 重复
                seen = set()
                unique_seqs = []
                for rec in sorted(
                    extracted_seqs, key=lambda r: len(r.seq), reverse=True
                ):
                    if rec.id not in seen:
                        seen.add(rec.id)
                        unique_seqs.append(rec)

                SeqIO.write(unique_seqs, str(output_fasta), "fasta")
                self.logger.info(
                    f"📦 最终输出 {len(unique_seqs)} 条噬菌体序列 → "
                    f"{output_fasta.name}"
                )
                return True

        except ImportError:
            self.logger.error("BioPython 未安装，无法执行序列提取")
        except Exception as e:
            self.logger.error(f"序列提取异常: {e}")

        return False

    async def _bwa_subtract_host(self, assembly_fasta: Path,
                                  host_fasta: Path,
                                  output_fasta: Path,
                                  threads: int) -> bool:
        """
        最后手段：BWA 比对组装 contigs 到宿主基因组，
        提取不比对上的序列作为候选噬菌体
        🔗 修复 3: 增加深度保护 — depth 最高的 contig 永不被剔除
        """
        wsl_assembly = WSLManager.to_wsl_path(str(assembly_fasta))
        wsl_host = WSLManager.to_wsl_path(str(host_fasta))
        wsl_out = WSLManager.to_wsl_path(str(output_fasta.parent))

        # 使用 minimap2 进行快速比对 (比 BWA 更适合长 contigs)
        paf_file = f"{wsl_out}/host_alignment.paf"

        # Step 1: 比对
        ret = await self.runner.run_command([
            "minimap2", "-t", str(threads),
            "-x", "asm5",  # assembly-to-reference 模式
            wsl_host, wsl_assembly,
            "-o", paf_file
        ])

        if ret != 0:
            self.logger.warning("minimap2 比对失败")
            return False

        # Step 2: 解析 PAF，找出与宿主高相似的 contigs
        host_contigs = set()
        paf_local = output_fasta.parent / "host_alignment.paf"
        if paf_local.exists():
            with open(paf_local, "r") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 12:
                        query_id = parts[0]
                        query_len = int(parts[1])
                        align_len = int(parts[10])
                        # 如果 >80% 的 contig 比对到了宿主 → 标记为宿主序列
                        if query_len > 0 and (align_len / query_len) > 0.8:
                            host_contigs.add(query_id)

        # Step 3: 深度保护 — 从 header 解析深度，保护 depth 最高的 contig
        protected_contigs = set()
        try:
            from Bio import SeqIO
            max_depth = 0.0
            max_depth_id = None
            for rec in SeqIO.parse(str(assembly_fasta), "fasta"):
                depth = self._parse_depth_from_header(rec.description)
                if depth > max_depth:
                    max_depth = depth
                    max_depth_id = rec.id
            if max_depth_id and max_depth_id in host_contigs:
                self.logger.warning(
                    f"🛡️ 深度保护: contig '{max_depth_id}' (depth={max_depth:.2f}x) "
                    f"虽比对到宿主但为最高深度序列，强制保留为噬菌体候选"
                )
                protected_contigs.add(max_depth_id)
                host_contigs.discard(max_depth_id)
        except Exception:
            pass

        # Step 4: 提取非宿主 contigs
        try:
            from Bio import SeqIO
            phage_seqs = []
            for rec in SeqIO.parse(str(assembly_fasta), "fasta"):
                if rec.id not in host_contigs:
                    phage_seqs.append(rec)
                else:
                    self.logger.info(
                        f"  🗑️ 去除宿主 contig: {rec.id} ({len(rec.seq)} bp)"
                    )

            if phage_seqs:
                SeqIO.write(phage_seqs, str(output_fasta), "fasta")
                self.logger.info(
                    f"📦 BWA 去宿主后保留 {len(phage_seqs)} 条候选噬菌体序列"
                )
                return True
        except Exception as e:
            self.logger.error(f"BWA 去宿主序列提取失败: {e}")

        return False

    def _extract_by_depth(self, assembly_path: Path,
                          host_genome_path: Optional[Path],
                          phispy_regions: List[Dict]) -> list:
        """
        深度感知噬菌体提取策略:
        1. 解析所有 contig 的 depth
        2. 保留 depth 最高的 contig 作为噬菌体候选 (测序富集信号)
        3. 如有 PhiSpy 坐标，用交叉验证增强
        """
        try:
            from Bio import SeqIO

            contigs = []
            for rec in SeqIO.parse(str(assembly_path), "fasta"):
                depth = self._parse_depth_from_header(rec.description)
                contigs.append({"rec": rec, "depth": depth, "len": len(rec.seq)})

            if not contigs:
                return []

            # 按 depth 降序排列
            contigs.sort(key=lambda x: x["depth"], reverse=True)

            # 取 depth 最高的 contig
            top = contigs[0]
            self.logger.info(
                f"🎯 深度感知: 最高深度 contig = {top['rec'].id} "
                f"({top['len']}bp, depth={top['depth']:.2f}x)"
            )

            result = []

            # 策略 A: 如果最高深度 contig 的 depth 远超其他 (至少 10x 倍)，
            #         可以直接确认为噬菌体
            second_depth = contigs[1]["depth"] if len(contigs) > 1 else 0.0
            if top["depth"] > 0 and (second_depth == 0 or top["depth"] / max(second_depth, 0.001) >= 10):
                self.logger.info(
                    f"  ✅ 深度差异显著 (top={top['depth']:.2f}x vs second={second_depth:.2f}x)，"
                    f"确认 {top['rec'].id} 为噬菌体"
                )
                result.append(top["rec"])
            else:
                # 策略 B: 深度差异不够明显，保留所有有 depth 的 contigs
                #         让后续步骤（CheckV/Pharokka）去做进一步验证
                for c in contigs:
                    if c["depth"] > 0 and c["len"] >= 1000:
                        result.append(c["rec"])
                        self.logger.info(
                            f"  📌 保留候选: {c['rec'].id} ({c['len']}bp, depth={c['depth']:.2f}x)"
                        )

            # 策略 C: 如果 PhiSpy 有结果，也把那些区域切出来追加
            if phispy_regions and host_genome_path and host_genome_path.exists():
                host_seqs = {
                    rec.id: rec
                    for rec in SeqIO.parse(str(host_genome_path), "fasta")
                }
                for region in phispy_regions:
                    contig_id = region["contig"]
                    start = max(0, region["start"])
                    end = region["end"]
                    if contig_id in host_seqs:
                        end = min(len(host_seqs[contig_id].seq), end)
                        if end - start > 5000:
                            from Bio.SeqRecord import SeqRecord
                            from Bio.Seq import Seq
                            prophage_seq = SeqRecord(
                                Seq(str(host_seqs[contig_id].seq[start:end])),
                                id=f"prophage_{region['prophage_id']}_{contig_id}_{start}_{end}",
                                description=f"PhiSpy prophage region [{start}-{end}] from {contig_id}"
                            )
                            result.append(prophage_seq)

            return result

        except Exception as e:
            self.logger.error(f"深度感知提取失败: {e}")
            return []

    @staticmethod
    def _parse_depth_from_header(header: str) -> float:
        """
        从 Unicycler/SPAdes 风格的 FASTA header 中解析深度值
        支持格式:
          - depth=1.00x  (Unicycler)
          - cov_8.973700 (SPAdes)
        """
        # Unicycler 格式
        m = re.search(r'depth=([\d\.]+)x?', header)
        if m:
            return float(m.group(1))
        # SPAdes 格式
        m = re.search(r'cov_([\d\.]+)', header)
        if m:
            return float(m.group(1))
        return 0.0

    # ═══════════════════════════════════════════
    #  工具函数
    # ═══════════════════════════════════════════

    def _count_contigs(self, fasta_path: Path) -> int:
        """统计 FASTA 中的序列数量"""
        count = 0
        try:
            with open(fasta_path, "r") as f:
                for line in f:
                    if line.startswith(">"):
                        count += 1
        except Exception:
            pass
        return count
