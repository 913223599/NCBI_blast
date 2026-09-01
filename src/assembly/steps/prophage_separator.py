
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
        #  修复: 统一宿主路径读取逻辑，与 HostCleanerStep 保持一致
        # 前端提交的宿主路径存储在 host_filter_db 中，host_genome 仅为备选 key
        params = self.context.config.get("params", {})
        host_genome = params.get("host_filter_db") or params.get("host_genome")
        if host_genome:
            self.logger.info(f"已获取宿主参考基因组路径: {host_genome}")
        raw_assembly_fasta = self.context.get("assembly_fasta")

        if not raw_assembly_fasta or not Path(raw_assembly_fasta).exists():
            self.logger.error("未找到组装产物 (assembly_fasta)，无法执行前噬菌体检测")
            self.status = "failed"
            return False

        assembly_fasta: Path = Path(raw_assembly_fasta)
        out_dir = self.get_working_dir()
        cpu_count = os.cpu_count() or 8
        threads = max(1, cpu_count - 1)

        import asyncio

        # 结果收集器
        phispy_regions: List[Dict] = []
        vibrant_results: Dict[str, List] = {"complete_phages": [], "integrated_prophages": []}

        # 定义并行的 PhiSpy 协程任务
        async def run_phispy_task():
            if host_genome and Path(host_genome).exists():
                self.logger.info(" [并发引擎] 启动 PhiSpy 宿主基因组检测...")
                regions = await self._run_phispy(
                    host_genome_path=Path(host_genome),
                    work_dir=out_dir,
                    threads=max(1, threads // 2)
                )
                self.logger.info(f" [并发引擎] PhiSpy 检测完成，识别到 {len(regions)} 个前噬菌体区域")
                return regions
            return []

        # 定义并行的 VIBRANT (包含前置去宿主) 协程任务
        async def run_vibrant_task():
            nonlocal assembly_fasta
            is_lysogenic = self.context.config.get("params", {}).get("is_lysogenic", False)
            if is_lysogenic and host_genome and Path(host_genome).exists():
                self.logger.info(" [并发引擎] 启动后置宿主 Contig 级大扫除 (Minimap2)...")
                pre_filter_fasta = out_dir / "pre_vibrant_filtered.fasta"
                host_removed = await self._bwa_subtract_host(
                    assembly_fasta=assembly_fasta,
                    host_fasta=Path(host_genome),
                    output_fasta=pre_filter_fasta,
                    threads=max(1, threads // 2)
                )
                if host_removed and pre_filter_fasta.exists() and pre_filter_fasta.stat().st_size > 0:
                    self.logger.info(f" [并发引擎] 宿主 Contig 级过滤完成，仅保留候选序列用于 VIBRANT 分箱")
                    assembly_fasta = pre_filter_fasta
            
            self.logger.info(" [并发引擎] 启动 VIBRANT 组装产物分箱...")
            results = await self._run_vibrant(
                assembly_path=assembly_fasta,
                work_dir=out_dir,
                threads=max(1, threads // 2) if host_genome and Path(host_genome).exists() else threads
            )
            self.logger.info(f" [并发引擎] VIBRANT 识别完成，完整游离噬菌体: {len(results.get('complete_phages', []))} 条, 前噬菌体片段: {len(results.get('integrated_prophages', []))} 个")
            return results

        if self.on_progress:
            self.on_progress(5, "并发调度：正在并发启动 PhiSpy 宿主检测 与 VIBRANT 组装分箱...")

        # 并发执行两条路径，大幅节省整体拼装时间
        phispy_regions, vibrant_results = await asyncio.gather(
            run_phispy_task(),
            run_vibrant_task()
        )

        # ─── 3. 交叉验证与序列提取 ───
        if self.on_progress:
            self.on_progress(80, "正在执行交叉验证与最终序列提取...")

        final_fasta = out_dir / "separated_phage.fasta"
        success = await self._merge_and_extract(
            assembly_path=Path(assembly_fasta),
            host_genome_path=Path(host_genome) if host_genome else None,
            phispy_regions=phispy_regions,
            vibrant_results=vibrant_results,
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
                "vibrant_contigs": len(vibrant_results.get("complete_phages", [])) + len(vibrant_results.get("integrated_prophages", [])),
                "final_contigs": self._count_contigs(final_fasta),
                "method": "PhiSpy+VIBRANT" if phispy_regions else "VIBRANT"
            })

            self.status = "completed"
            if self.on_progress:
                self.on_progress(100, "前噬菌体分离完成")
            return True

        # 降级处理：如果分离失败，保留原始组装
        self.logger.warning("️ 前噬菌体分离未产生有效结果，保留原始组装产物")
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
            ret = await self.runner.run_command(prokka_cmd)
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
            ret = await self.runner.run_command(phispy_cmd)
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
                           threads: int) -> Dict[str, List]:
        """
        使用 VIBRANT 对组装产物进行噬菌体识别与分箱
        
        VIBRANT 输出分为:
          - phages_combined/  噬菌体 contigs
          - prophages_combined/  前噬菌体区域
        """
        phage_results = {"complete_phages": [], "integrated_prophages": []}
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
            vs2_ids = await self._run_virsorter2_fallback(
                assembly_path, work_dir, threads
            )
            phage_results["complete_phages"] = vs2_ids
            return phage_results

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
            self.logger.info(f" VIBRANT 数据库路径: {db_path}")

        try:
            self.logger.info(" 正在内存盘中运行 VIBRANT...")
            ret = await self.runner.run_command(vibrant_cmd)
            
            # 运行结束后将结果拷回物理磁盘
            if ret == 0:
                await self.runner.run_command(["cp", "-a", f"{shm_dir}/.", WSLManager.to_wsl_path(str(vibrant_dir))])
        finally:
            if self.context.shm:
                await self.context.shm.release("vibrant")
            else:
                await self.runner.run_command(["rm", "-rf", shm_dir])

        #  检测 VIBRANT 数据库缺失的静默失败
        vibrant_log = None
        for log_file in vibrant_dir.rglob("VIBRANT_log_*.log"):
            vibrant_log = log_file
            break
        if vibrant_log and vibrant_log.exists():
            log_text = vibrant_log.read_text(encoding='utf-8', errors='ignore')
            if "could not identify KEGG HMM" in log_text or "could not identify" in log_text:
                self.logger.warning(
                    "️ VIBRANT 数据库路径不正确 (KEGG HMM 未找到)！"
                    "请确认 conda 环境中 VIBRANT 数据库已正确安装。"
                )
                return phage_results  # 返回空字典

        if ret == 0:
            phage_results = self._parse_vibrant_output(vibrant_dir, assembly_path)

        return phage_results

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
                self.logger.info(f" 自动探测到 VIBRANT 数据库: {db_path}")
                return db_path

        self.logger.warning("️ 未能自动探测 VIBRANT 数据库路径，将使用 VIBRANT 默认值")
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
                               assembly_path: Path) -> Dict[str, List]:
        """
        解析 VIBRANT 输出，提取游离噬菌体 ID 和前噬菌体坐标
        """
        results = {"complete_phages": [], "integrated_prophages": []}
        stem = assembly_path.stem  # e.g., "assembly"

        # 1. 提取前噬菌体精确坐标
        coord_file = vibrant_dir / f"VIBRANT_{stem}" / f"VIBRANT_integrated_prophage_coordinates_{stem}.tsv"
        if not coord_file.exists():
            coord_file = vibrant_dir / f"VIBRANT_integrated_prophage_coordinates_{stem}.tsv"

        if coord_file.exists():
            import csv
            try:
                with open(coord_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    for row in reader:
                        scaffold_raw = row.get("scaffold", "")
                        if scaffold_raw:
                            contig_id = scaffold_raw.split()[0]
                            results["integrated_prophages"].append({
                                "contig_id": contig_id,
                                "start": int(row.get("nucleotide start", 0)),
                                "end": int(row.get("nucleotide stop", 0)),
                                "length": int(row.get("nucleotide length", 0))
                            })
            except Exception as e:
                self.logger.warning(f"解析 VIBRANT 前噬菌体坐标失败: {e}")

        # 2. 提取完整游离噬菌体
        possible_dirs = [
            vibrant_dir / f"VIBRANT_{stem}" / f"VIBRANT_phages_{stem}",
            vibrant_dir / f"VIBRANT_phages_{stem}",
        ]

        phage_fasta = None
        for d in possible_dirs:
            candidate = d / f"{stem}.phages_combined.fna"
            if candidate.exists():
                phage_fasta = candidate
                break

        if not phage_fasta:
            for fasta_file in vibrant_dir.rglob("*.phages_combined.fna"):
                phage_fasta = fasta_file
                break

        if phage_fasta and phage_fasta.exists():
            with open(phage_fasta, "r") as f:
                for line in f:
                    if line.startswith(">"):
                        contig_id = line[1:].strip().split()[0]
                        clean_id = re.sub(r'_fragment_\d+$|_prophage$', '', contig_id)
                        # 只提取未被标记为 fragment/prophage 的完整序列
                        if "_fragment_" not in line and "_prophage" not in line:
                            results["complete_phages"].append(clean_id)

        return results

    # ═══════════════════════════════════════════
    #  Stage 3: 交叉验证与最终序列提取
    # ═══════════════════════════════════════════

    async def _merge_and_extract(
        self,
        assembly_path: Path,
        host_genome_path: Optional[Path],
        phispy_regions: List[Dict],
        vibrant_results: Dict[str, List],
        output_fasta: Path,
        work_dir: Path,
        threads: int
    ) -> bool:
        """
        综合 PhiSpy + VIBRANT 结果，提取最终噬菌体基因组
        核心策略 (智能直切与游离态保留):
        1. 精确直切: 根据 VIBRANT_integrated_prophage_coordinates 从原始宿主 Contig 中切出前噬菌体。
        2. 保留游离态: 提取 VIBRANT 标记的完整无 fragment 后缀的噬菌体。
        3. 仅当 VIBRANT 无任何发现时，降级使用 PhiSpy 切割或深度提取。
        """
        extracted_seqs = []

        try:
            from Bio import SeqIO
            from Bio.SeqRecord import SeqRecord
            from Bio.Seq import Seq
            
            assembly_contigs = {rec.id: rec for rec in SeqIO.parse(str(assembly_path), "fasta")}
            
            has_vibrant_hits = bool(vibrant_results.get("complete_phages")) or bool(vibrant_results.get("integrated_prophages"))

            # ─── A. 精确直切前噬菌体 (VIBRANT) ───
            for region in vibrant_results.get("integrated_prophages", []):
                contig_id = region["contig_id"]
                start = region["start"]
                end = region["end"]
                
                if contig_id in assembly_contigs:
                    host_rec = assembly_contigs[contig_id]
                    # 安全边界检查
                    start = max(0, start)
                    end = min(len(host_rec.seq), end)
                    
                    if end - start > 1500:
                        prophage_seq = SeqRecord(
                            Seq(str(host_rec.seq[start:end])),
                            id=f"prophage_{contig_id}",
                            description=f"VIBRANT exact cut from host contig {contig_id} [{start}-{end}]"
                        )
                        extracted_seqs.append(prophage_seq)
                        self.logger.info(f"  ️ VIBRANT 精确直切: {contig_id}[{start}-{end}] ({end - start} bp)")

            # ─── B. 提取完整的游离态噬菌体 (VIBRANT) ───
            if vibrant_results.get("complete_phages"):
                complete_set = set(vibrant_results["complete_phages"])
                for rec in assembly_contigs.values():
                    clean_rec_id = re.sub(r'_fragment_\d+$|_prophage$|(_\d+)?_circular$', '', rec.id)
                    if clean_rec_id in complete_set:
                        # 避免提取已经被精确直切的主 contig
                        already_cut = any(r.id == f"prophage_{clean_rec_id}" for r in extracted_seqs)
                        if not already_cut:
                            extracted_seqs.append(rec)
                            self.logger.info(f"   VIBRANT 游离提取: {rec.id} ({len(rec.seq)} bp)")

            # ─── C. 降级策略: 当 VIBRANT 失败时，使用 PhiSpy ───
            if not has_vibrant_hits and phispy_regions and host_genome_path and host_genome_path.exists():
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
                        start = max(0, start)
                        end = min(len(host_rec.seq), end)

                        if end - start > 5000:
                            prophage_seq = SeqRecord(
                                Seq(str(host_rec.seq[start:end])),
                                id=f"phispy_{region['prophage_id']}_{contig_id}_{start}_{end}",
                                description=f"PhiSpy prophage region [{start}-{end}] from {contig_id}"
                            )
                            extracted_seqs.append(prophage_seq)
                            self.logger.info(f"   PhiSpy 切割 (降级): {contig_id}[{start}-{end}] ({end - start} bp)")

            # ─── D. 终极降级策略: 深度感知保留 ───
            if not extracted_seqs:
                is_lysogenic = self.context.config.get("params", {}).get("is_lysogenic", False)
                if is_lysogenic or (host_genome_path and host_genome_path.exists()):
                    self.logger.info("VIBRANT+PhiSpy 均无结果，启动高置信降级方案 (Threshold=4.0x)...")
                    for rec in assembly_contigs.values():
                        depth = self._parse_depth_from_header(rec.description)
                        if depth >= 4.0 and len(rec.seq) >= 1500:
                            extracted_seqs.append(rec)
                            self.logger.info(f"   降级保留 (高深度条目): {rec.id} ({depth}x)")
                elif host_genome_path and host_genome_path.exists():
                    self.logger.info("降级使用 BWA 比对去宿主")
                    return await self._bwa_subtract_host(
                        assembly_path, host_genome_path, output_fasta, threads
                    )

            # ─── E. 反向宿主验证 + 去冗余 + 写出最终结果 ───
            if extracted_seqs:
                # E.5 反向宿主验证 (仅对非直切序列进行，直切序列可能包含 att 位点及微量宿主基因)
                if host_genome_path and host_genome_path.exists():
                    extracted_seqs = await self._anti_host_filter(
                        extracted_seqs, host_genome_path, work_dir, threads
                    )

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
                    f" 最终输出 {len(unique_seqs)} 条噬菌体序列 → "
                    f"{output_fasta.name}"
                )
                return True

        except ImportError:
            self.logger.error("BioPython 未安装，无法执行序列提取")
        except Exception as e:
            self.logger.error(f"序列提取异常: {e}")

        return False

    # ═══════════════════════════════════════════
    #  TNF (四核苷酸频率) 聚类工具
    # ═══════════════════════════════════════════

    @staticmethod
    def _calc_tnf(seq_str: str) -> list:
        """计算归一化四核苷酸频率向量 (256维)"""
        try:
            import numpy as np
            
            # 建立映射表 A=0, C=1, G=2, T=3, 其他=-1
            mapping = np.full(256, -1, dtype=np.int8)
            mapping[ord('A')] = 0; mapping[ord('a')] = 0
            mapping[ord('C')] = 1; mapping[ord('c')] = 1
            mapping[ord('G')] = 2; mapping[ord('g')] = 2
            mapping[ord('T')] = 3; mapping[ord('t')] = 3

            # 快速将字符串转为 byte 数组并映射
            seq_bytes = np.frombuffer(seq_str.encode('ascii', errors='ignore'), dtype=np.uint8)
            encoded = mapping[seq_bytes]
            
            if len(encoded) < 4:
                return [0.0] * 256

            # 滑动窗口切片 indices (4-mer)
            w0 = encoded[:-3]
            w1 = encoded[1:-2]
            w2 = encoded[2:-1]
            w3 = encoded[3:]

            # 过滤包含非 ACGT 碱基 (即 -1) 的 kmer
            valid = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) & (w3 >= 0)
            
            # 将 4 个核苷酸合并为 0-255 的平坦整数索引
            kmer_indices = w0[valid] * 64 + w1[valid] * 16 + w2[valid] * 4 + w3[valid]
            
            # 使用 bincount 并发/向量化求和计数
            counts = np.bincount(kmer_indices, minlength=256)
            total = counts.sum()
            if total == 0:
                return [0.0] * 256
            
            return (counts / total).tolist()
        except ImportError:
            import itertools
            from collections import Counter

            tetramers = [''.join(t) for t in itertools.product("ACGT", repeat=4)]
            seq = seq_str.upper()
            counts = Counter()
            for i in range(len(seq) - 3):
                kmer = seq[i:i+4]
                if all(c in "ACGT" for c in kmer):
                    counts[kmer] += 1
            total = sum(counts.values())
            if total == 0:
                return [0.0] * 256
            return [counts.get(t, 0) / total for t in tetramers]

    @staticmethod
    def _tnf_cosine_distance(a: list, b: list) -> float:
        """计算两个 TNF 向量的余弦距离 (0=相同, 1=正交)"""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 1.0
        return 1.0 - dot / (na * nb)

    def _tnf_depth_filter(
        self, candidates: list, vibrant_ids: list
    ) -> list:
        """
        TNF + 深度联合过滤器 (锚点策略):
        1. 从 VIBRANT 种子中选择"最长的高深度种子"作为锚点
           (深度 >= VIBRANT 中位数, 长度 > 10KB 优先)
        2. 用锚点的 TNF 和深度直接过滤全部候选序列

        锚点选择理由:
        - 长序列(>10KB) 保证 TNF 统计量稳定
        - 高深度保证是真正的噬菌体(裂解期扩增)
        - 不依赖复杂聚类，避免假阳性数量优势淹没真信号
        """
        import re
        import statistics

        if len(candidates) <= 2:
            return candidates

        def _clean_id(full_id):
            return re.sub(r'_fragment_\d+$|_prophage$|(_\d+)?_circular$', '', full_id)

        clean_vibrant = {_clean_id(vid) for vid in vibrant_ids}

        # ─── Step 1: 计算 TNF 并寻找锚点 ───
        self.logger.info("TNF 过滤: 计算四核苷酸频率向量...")
        contig_info = []
        vibrant_items = []
        for rec in candidates:
            tnf = self._calc_tnf(str(rec.seq))
            depth = self._parse_depth_from_header(rec.description)
            is_vibrant = _clean_id(rec.id) in clean_vibrant
            info = {
                "rec": rec, "tnf": tnf, "depth": depth,
                "vibrant": is_vibrant, "len": len(rec.seq)
            }
            contig_info.append(info)
            if is_vibrant and info["len"] > 3000:
                vibrant_items.append(info)

        if not vibrant_items:
            self.logger.info("TNF 过滤: 无足够长的 VIBRANT 种子，跳过")
            return candidates

        # 计算 VIBRANT 深度中位数
        v_depths = [c["depth"] for c in vibrant_items if c["depth"] > 0]
        v_median = statistics.median(v_depths) if v_depths else 1.0

        #  综合评分法选择锚点 (Length-Weighted Depth-Stability Score)
        # 单纯用长度：可能会误选由于错误组装拼接而成的长嵌合体（通常深度极度异常）。
        # 单纯用深度：极易误选高拷贝的重复小片段（如 rRNA区、末端重复序列）。
        # 更优策略：长度为主导，深度偏离度作为惩罚项。
        # Score = Length / (1.0 + |Depth - v_median| / v_median)
        anchor = None
        for min_len in [10000, 5000, 3000]:
            candidates_for_anchor = [
                c for c in vibrant_items
                if c["depth"] > 0 and c["len"] > min_len
            ]
            if candidates_for_anchor:
                def anchor_score(c):
                    depth_deviation = abs(c["depth"] - v_median) / v_median
                    return c["len"] / (1.0 + depth_deviation)
                
                anchor = max(candidates_for_anchor, key=anchor_score)
                break

        if not anchor:
            # 最终降级：任何 VIBRANT contig 中最长的
            anchor = max(vibrant_items, key=lambda c: c["len"])

        anchor_tnf = anchor["tnf"]
        anchor_depth = anchor["depth"]
        self.logger.info(
            f"TNF 过滤: 锚点 = contig {anchor['rec'].id} "
            f"({anchor['len']}bp, depth={anchor_depth:.2f}x, "
            f"VIBRANT median={v_median:.2f}x)"
        )

        # ─── Step 2: 用锚点 TNF+深度过滤全部候选 ───
        filtered = []
        for info in contig_info:
            tnf_dist = self._tnf_cosine_distance(info["tnf"], anchor_tnf)

            # 深度匹配: 放宽至 0.3 - 3.0 倍。噬菌体在活跃复制期时，
            # 起点和终点的测序深度会有巨大的天然差异，不能死板卡死在 0.75-1.25。
            if info["depth"] > 0 and anchor_depth > 0:
                depth_ratio = info["depth"] / anchor_depth
                depth_ok = 0.3 <= depth_ratio <= 3.0
            else:
                depth_ok = True

            # TNF 阈值: 长序列严格，短序列放宽
            tnf_threshold = 0.05 if info["len"] >= 5000 else 0.10

            # 环形序列放宽 TNF 阈值
            if "circular=true" in info["rec"].description.lower():
                tnf_threshold = 0.15

            #  针对不同来源序列的分类过滤决策
            is_kept = False
            if info["vibrant"]:
                # VIBRANT 显式鉴定的序列：本身已经是高置信度的病毒序列。
                # TNF 只作为极端异常的兜底，绝不因为微小的波动而丢弃亲骨肉。
                if tnf_dist < (tnf_threshold * 2.5):
                    is_kept = True
            else:
                # 仅靠深度回收的序列 (极可能是凑巧深度接近的宿主染色体片段)：
                # 必须严格满足 TNF 同源性和深度匹配，才能被接纳为本噬菌体的一部分。
                if tnf_dist < tnf_threshold and depth_ok:
                    is_kept = True

            if is_kept:
                filtered.append(info["rec"])
                self.logger.info(
                    f"   TNF 保留: {info['rec'].id} "
                    f"({info['len']}bp, depth={info['depth']:.2f}x, "
                    f"TNF_dist={tnf_dist:.4f})"
                )
            else:
                self.logger.debug(
                    f"   TNF 剔除: {info['rec'].id} "
                    f"({info['len']}bp, depth={info['depth']:.2f}x, "
                    f"TNF_dist={tnf_dist:.4f}, depth_ok={depth_ok})"
                )

        # ─── Step 3: 安全降级 ───
        if not filtered:
            self.logger.warning("TNF 过滤: 过滤后无结果，回退到原始候选集")
            return candidates

        self.logger.info(
            f"TNF 过滤: {len(candidates)} → {len(filtered)} 条 "
            f"(剔除 {len(candidates) - len(filtered)} 条非同源序列)"
        )
        return filtered

    async def _anti_host_filter(
        self, candidates: list, host_genome_path: Path,
        work_dir: Path, threads: int
    ) -> list:
        """
        反向宿主验证：将候选噬菌体序列用 Minimap2 比对到宿主基因组，
        剔除 >80% 比对到宿主的 contigs。
        同时保留最高深度 contig 作为深度保护。
        """
        from Bio import SeqIO
        import tempfile

        if not candidates:
            return candidates

        # 1. 将候选序列写入临时 FASTA
        tmp_candidates = work_dir / "anti_host_candidates.fasta"
        SeqIO.write(candidates, str(tmp_candidates), "fasta")

        wsl_candidates = WSLManager.to_wsl_path(str(tmp_candidates))
        wsl_host = WSLManager.to_wsl_path(str(host_genome_path))
        wsl_out = WSLManager.to_wsl_path(str(work_dir))
        paf_file = f"{wsl_out}/anti_host_check.paf"

        # 2. Minimap2 比对
        ret = await self.runner.run_command([
            "minimap2", "-t", str(threads),
            "-x", "asm5",
            wsl_host, wsl_candidates,
            "-o", paf_file
        ])

        if ret != 0:
            self.logger.warning("反向宿主验证: Minimap2 比对失败，跳过验证直接输出候选集")
            return candidates

        # 3. 解析 PAF，累计每条 contig 的比对覆盖长度
        # 注意：一条 contig 可能有多段比对，需要累计
        from collections import defaultdict
        contig_align_len = defaultdict(int)
        contig_total_len = {}

        paf_local = work_dir / "anti_host_check.paf"
        if paf_local.exists():
            with open(paf_local, "r") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 12:
                        query_id = parts[0]
                        query_len = int(parts[1])
                        align_block = int(parts[3]) - int(parts[2])  # 本段比对的 query 覆盖长度
                        contig_total_len[query_id] = query_len
                        contig_align_len[query_id] += align_block

        # 4. 标记宿主 contigs (>80% 比对到宿主)
        host_contigs = set()
        for qid, total_aligned in contig_align_len.items():
            qlen = contig_total_len.get(qid, 1)
            coverage = total_aligned / qlen
            if coverage > 0.8:
                host_contigs.add(qid)

        if not host_contigs:
            self.logger.info("反向宿主验证: 未发现宿主污染序列，全部候选通过")
            return candidates

        # 5. 深度保护：最高深度 contig 永不被剔除
        max_depth = 0.0
        max_depth_id = None
        for rec in candidates:
            d = self._parse_depth_from_header(rec.description)
            if d > max_depth:
                max_depth = d
                max_depth_id = rec.id

        if max_depth_id and max_depth_id in host_contigs:
            self.logger.warning(
                f"   深度保护: '{max_depth_id}' (depth={max_depth:.2f}x) "
                f"虽比对到宿主但为最高深度序列，强制保留"
            )
            host_contigs.discard(max_depth_id)

        # 6. 过滤
        filtered = []
        for rec in candidates:
            if rec.id in host_contigs:
                self.logger.info(
                    f"   反向验证剔除宿主: {rec.id} ({len(rec.seq):,} bp, "
                    f"host_coverage={contig_align_len.get(rec.id, 0)/contig_total_len.get(rec.id, 1)*100:.1f}%)"
                )
            else:
                filtered.append(rec)

        self.logger.info(
            f"反向宿主验证: {len(candidates)} → {len(filtered)} 条 "
            f"(剔除 {len(candidates) - len(filtered)} 条宿主污染)"
        )
        return filtered

    async def _bwa_subtract_host(self, assembly_fasta: Path,
                                  host_fasta: Path,
                                  output_fasta: Path,
                                  threads: int) -> bool:
        """
        最后手段：BWA 比对组装 contigs 到宿主基因组，
        提取不比对上的序列作为候选噬菌体
         修复 3: 增加深度保护 — depth 最高的 contig 永不被剔除
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
                    f"️ 深度保护: contig '{max_depth_id}' (depth={max_depth:.2f}x) "
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
                        f"  ️ 去除宿主 contig: {rec.id} ({len(rec.seq)} bp)"
                    )

            if phage_seqs:
                SeqIO.write(phage_seqs, str(output_fasta), "fasta")
                self.logger.info(
                    f" BWA 去宿主后保留 {len(phage_seqs)} 条候选噬菌体序列"
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
                f" 深度感知: 最高深度 contig = {top['rec'].id} "
                f"({top['len']}bp, depth={top['depth']:.2f}x)"
            )

            result = []

            # 策略 A: 如果最高深度 contig 的 depth 远超其他 (至少 10x 倍)，
            #         可以直接确认为噬菌体
            second_depth = contigs[1]["depth"] if len(contigs) > 1 else 0.0
            if top["depth"] > 0 and (second_depth == 0 or top["depth"] / max(second_depth, 0.001) >= 10):
                self.logger.info(
                    f"   深度差异显著 (top={top['depth']:.2f}x vs second={second_depth:.2f}x)，"
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
                            f"   保留候选: {c['rec'].id} ({c['len']}bp, depth={c['depth']:.2f}x)"
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
        从 NGCS / FASTA header 中解析深度值
        支持格式:
          - depth=1.00x / depth=1.00
          - cov=8.97 / cov_8.97
        """
        m = re.search(r'(?:depth[=:]|cov[=_:]|cov=)([\d\.]+)', header, re.IGNORECASE)
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
