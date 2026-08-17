
import os
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from ..core.base import BaseAssemblyStep
from ..env.wsl_manager import WSLManager

class HostCleanerStep(BaseAssemblyStep):
    """
    宿主数据剔除步骤
    使用算法: Kraken2 (核心分类器)
    优化策略: 
    1. 使用 Kraken2 原生 --unclassified-out 进行多线程并行提取 (解决单线程 Python 瓶颈)
    2. 使用内存盘 (/dev/shm) 减少硬盘 IO 压力
    3. 全核并行计算
    """
    
    @property
    def name(self) -> str:
        return "Host Cleaning (Kraken2)"

    def is_completed(self) -> bool:
        out_dir = self.get_working_dir()
        final_r1 = out_dir / "clean_filtered_R1.fq.gz"
        final_r2 = out_dir / "clean_filtered_R2.fq.gz"
        if final_r1.exists() and final_r2.exists():
            self.context.update("clean_r1", final_r1)
            self.context.update("clean_r2", final_r2)
            return True
        return False

    async def execute(self) -> bool:
        self.status = "running"
        params = self.context.config.get("params", {})
        is_lysogenic = params.get("is_lysogenic", False)
        is_strict_parent = params.get("is_strict_parent_strain", True)
        host_fasta = params.get("host_filter_db")
        
        # 🔗 尝试从 host_genome 继承参数以支持靶向噬菌体提取
        if not host_fasta or not Path(host_fasta).exists():
            host_fasta = params.get("host_genome")
            if host_fasta and Path(host_fasta).exists():
                self.logger.info(f"🔄 未提供专项 host_filter_db，自动继承宿主基因组: {host_fasta}")
                
        if is_lysogenic:
            if host_fasta and Path(host_fasta).exists():
                self.logger.info("🛡️ 触发防丢保护与交界区保留：存在宿主参考，进入架构级 Soft-Dehosting (差分下采样) 模式。")
                return await self._run_soft_dehosting(host_fasta, is_strict_parent)
            else:
                self.logger.warning("🛡️ 触发防丢路障：检测到溶源态保护开启，但无参考基因组。跳过全量过滤直接将数据送入组装器！")
                self.context.update("clean_r1", self.context.get("r1"))
                self.context.update("clean_r2", self.context.get("r2"))
                return True

        if not host_fasta or not Path(host_fasta).exists():
            self.logger.info("未配置有效的宿主参考序列，跳过宿主过滤")
            self.context.update("clean_r1", self.context.get("r1"))
            self.context.update("clean_r2", self.context.get("r2"))
            return True

        # 🚀 深度资源调优: 开启全部马力
        cpu_count = os.cpu_count() or 8
        optimal_threads = max(1, cpu_count - 1)
        self.logger.info(f"🚀 自动资源调优: 物理核心数={cpu_count}, 分配任务线程={optimal_threads}")

        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        out_dir = self.get_working_dir()
        
        host_path = Path(host_fasta)
        db_dir = host_path.parent / ".kraken_db"
        
        # 加载物种元数据
        metadata_file = host_path.parent / "metadata.json"
        taxid = 1350
        species_name = "HostGenus"
        
        if metadata_file.exists():
            try:
                meta = json.loads(metadata_file.read_text(encoding="utf-8"))
                taxid = meta.get("taxid") or 1350
                species_name = meta.get("species") or "HostGenus"
            except: pass
        
        # 1. 自动构建索引 (在硬盘完成)
        if not (db_dir / "hash.k2d").exists():
            msg = "正在预热宿主索引库..."
            if self.on_progress: self.on_progress(10, msg)
            await self._build_mini_kraken_db(host_path, db_dir, taxid, species_name)

        # 2. 内存盘加速空间
        shm_dir = await self.get_best_wsl_tmp_dir(required_gb=8.0)
        
        try:
            msg = "🚀 激活内存高速通道 (Ramdisk)..."
            if self.on_progress: self.on_progress(20, msg)
            await self.runner.run_command(["mkdir", "-p", shm_dir])
            
            # 核心变动：利用 Kraken2 的原生剥离能力，支持多线程
            # kraken2 会将 # 替换为 _1 和 _2
            shm_unclassified_pattern = f"{shm_dir}/clean#.fq"
            kraken_report = f"{shm_dir}/kraken.report"
            
            msg = "正在全核并发执行宿主鉴定与剥离..."
            if self.on_progress: self.on_progress(40, msg)
            self.logger.info(msg)
            
            confidence = 0.0

            cmd = (
                f"kraken2 --db '{WSLManager.to_wsl_path(str(db_dir))}' "
                f"--paired '{WSLManager.to_wsl_path(str(r1))}' '{WSLManager.to_wsl_path(str(r2))}' "
                f"--unclassified-out '{shm_unclassified_pattern}' "
                f"--confidence {confidence} "
                f"--report '{kraken_report}' "
                f"--threads {optimal_threads} "
                f"--output /dev/null"
            )
            
            ret = await self.runner.run_command(cmd, is_shell=True)
            if ret != 0: return False

            # 解析报告 (统计污染率)
            contamination = await self._parse_kraken_report_raw(kraken_report, taxid, species_name)
            self.context.data["host_contamination_percent"] = contamination
            self.logger.info(f"📊 宿主占比测量: {contamination:.2f}%")

            # 持久化宿主污染统计至 JSON (供前端报告解析器读取)
            try:
                import json as _json
                with open(out_dir / "host_stats.json", "w", encoding="utf-8") as _f:
                    _json.dump({"host_contamination_percent": contamination}, _f)
            except Exception as _e:
                self.logger.warning(f"无法保存 host_stats.json: {_e}")

            # 3. 将结果并行写回硬盘 (并发封包技术)
            final_r1 = out_dir / "clean_filtered_R1.fq.gz"
            final_r2 = out_dir / "clean_filtered_R2.fq.gz"
            
            msg = "正在内存盘内并发展开数据封包 (Parallel Gzip)..."
            if self.on_progress: self.on_progress(85, msg)
            self.logger.info(msg)
            
            # 检测是否安装了 pigz (多核并行压缩)
            has_pigz = (await self.runner.run_command(["which", "pigz"], silence_errors=True)) == 0
            if not has_pigz:
                self.logger.warning("🚀 性能降级预警：监测到未安装 pigz，将回退至单线程 gzip。请在各节点运行 'sudo apt install pigz' 以极大提升封包速率。")
            
            # 由于是并发压缩两条 Reads，需将线程均分，防止超过物理核心数
            zip_threads = max(1, optimal_threads // 2)
            zip_tool = f"pigz -p {zip_threads}" if has_pigz else "gzip -1"
            
            from ..engine.runner import CommandRunner
            # 为并发压缩准备独立的执行器
            runner_r1 = CommandRunner(f"{self.__class__.__name__}.Zip1", is_wsl=True)
            runner_r2 = CommandRunner(f"{self.__class__.__name__}.Zip2", is_wsl=True)

            # 🚀 I/O 优化：先在内存盘内完成压缩，再一次性搬运到 Windows 盘
            shm_clean_r1 = f"{shm_dir}/clean_1.fq"
            shm_clean_r2 = f"{shm_dir}/clean_2.fq"
            shm_gz_r1 = f"{shm_dir}/clean_1.fq.gz"
            shm_gz_r2 = f"{shm_dir}/clean_2.fq.gz"
            
            cmd1 = f"{zip_tool} -c '{shm_clean_r1}' > '{shm_gz_r1}'"
            cmd2 = f"{zip_tool} -c '{shm_clean_r2}' > '{shm_gz_r2}'"

            # 🔗 并发封包 (在极速内存盘中进行)
            retcodes = await asyncio.gather(
                runner_r1.run_command(cmd1, is_shell=True),
                runner_r2.run_command(cmd2, is_shell=True)
            )

            if any(r != 0 for r in retcodes):
                self.logger.error("并发封包过程中发生致命错误")
                return False

            # 🚀 原子搬运：将压缩好的文件从内存盘拷贝到 Windows 目标目录
            wsl_final_r1 = WSLManager.to_wsl_path(str(final_r1))
            wsl_final_r2 = WSLManager.to_wsl_path(str(final_r2))
            await self.runner.run_command(["cp", shm_gz_r1, wsl_final_r1])
            await self.runner.run_command(["cp", shm_gz_r2, wsl_final_r2])
            
            self.context.update("clean_r1", final_r1)
            self.context.update("clean_r2", final_r2)
            self.logger.info(f"✅ 宿主清理与并发封包完成")
            return True
            
        finally:
            self.logger.info("♻️ 释放内存资源...")
            if self.context.shm:
                await self.context.shm.release(self.__class__.__name__.lower())
            else:
                await self.runner.run_command(["rm", "-rf", shm_dir])

    async def _build_mini_kraken_db(self, fasta: Path, db_dir: Path, taxid: int = 1350, species_name: str = "HostGenus"):
        """构建最小化 Kraken2 参考数据库"""
        wsl_db = WSLManager.to_wsl_path(str(db_dir))
        wsl_fa = WSLManager.to_wsl_path(str(fasta))
        cpu = os.cpu_count() or 16
        
        # 所有路径通过 bash -c + 单引号包裹，防止空格/括号等特殊字符被 shell 误解析
        await self.runner.run_command(
            f"mkdir -p '{wsl_db}/taxonomy' '{wsl_db}/library'", is_shell=True
        )
        
        # 使用 chr() 彻底避开任何 shell 转义和路径替换问题
        nodes_py = (
            "import sys; f=open(sys.argv[1],'w'); "
            "t=chr(9); n=chr(10); "
            "f.write(f'1{t}|{t}1{t}|{t}no rank{t}|{t}{n}'); "
            f"f.write(f'{taxid}{{t}}|{{t}}1{{t}}|{{t}}species{{t}}|{{t}}{{n}}'); "
            "f.close()"
        )
        await self.runner.run_command(
            f"python3 -c \"{nodes_py}\" '{wsl_db}/taxonomy/nodes.dmp'", is_shell=True
        )
        
        names_py = (
            "import sys; f=open(sys.argv[1],'w'); "
            "t=chr(9); n=chr(10); "
            "f.write(f'1{t}|{t}all{t}|{t}{t}|{t}scientific name{t}|{n}'); "
            f"f.write(f'{taxid}{{t}}|{{t}}{species_name}{{t}}|{{t}}{{t}}|{{t}}scientific name{{t}}|{{n}}'); "
            "f.close()"
        )
        await self.runner.run_command(
            f"python3 -c \"{names_py}\" '{wsl_db}/taxonomy/names.dmp'", is_shell=True
        )
        
        # sed 命令: 路径用单引号包裹防止括号/空格被 bash 解析
        await self.runner.run_command(
            f"sed 's/>/>kraken:taxid|{taxid}|/' '{wsl_fa}' > '{wsl_db}/library/host.fna'",
            is_shell=True
        )
        await self.runner.run_command(
            f"kraken2-build --add-to-library '{wsl_db}/library/host.fna' --db '{wsl_db}'",
            is_shell=True
        )
        
        self.logger.info(f"🔨 正在构建 Kraken2 索引 ({species_name}, 线程={cpu})...")
        await self.runner.run_command(
            f"kraken2-build --build --db '{wsl_db}' --threads {cpu}",
            is_shell=True
        )

    async def _parse_kraken_report_raw(self, report_wsl_path: str, taxid: int = 1350, species_name: str = "HostGenus") -> float:
        """从内存盘读取 Kraken2 报告并解析宿主占比"""
        try:
            captured_lines = []
            await self.runner.run_command(["cat", report_wsl_path], on_output=lambda x: captured_lines.append(x))
            taxid_str = str(taxid)
            for line in captured_lines:
                parts = re.split(r'\t+|\s{2,}', line.strip())
                if len(parts) >= 6:
                    if species_name in parts[-1] or taxid_str in parts:
                        return float(parts[0].strip())
            for line in captured_lines:
                if taxid_str in line:
                    parts = re.split(r'\t+|\s{2,}', line.strip())
                    if len(parts) >= 5:
                        return float(parts[0].strip())
        except: pass
        return 0.0

    async def _run_soft_dehosting(self, host_fasta: str, is_strict_parent: bool) -> bool:
        """执行差分下采样的 Soft-Dehosting (基于 Minimap2 和 Samtools)"""
        r1 = self.context.get("clean_r1") or self.context.get("r1")
        r2 = self.context.get("clean_r2") or self.context.get("r2")
        out_dir = self.get_working_dir()
        if self.context.shm:
            ws = await self.context.shm.acquire_manual("softclean", required_gb=4.0)
            shm_dir = ws.path
        else:
            shm_id = f"softclean_{self.context.task_id}"
            shm_dir = f"/dev/shm/{shm_id}"
        
        cpu_count = os.cpu_count() or 8
        optimal_threads = max(1, cpu_count - 1)
        host_path = Path(host_fasta)
        
        try:
            msg = "🚀 建立高速内存隔离区并启动 Minimap2 差分下采样..."
            if self.on_progress: self.on_progress(20, msg)
            await self.runner.run_command(["mkdir", "-p", shm_dir])
            
            wsl_host = WSLManager.to_wsl_path(str(host_path))
            wsl_r1 = WSLManager.to_wsl_path(str(r1))
            wsl_r2 = WSLManager.to_wsl_path(str(r2))
            
            shm_clean_r1 = f"{shm_dir}/clean_R1.fastq"
            shm_clean_r2 = f"{shm_dir}/clean_R2.fastq"
            
            bg_fraction = "05" if is_strict_parent else "15"
            if is_strict_parent:
                self.logger.info("🔪 严格亲本模式：提取不匹配和交界序列，附带 5% 正常背景数据...")
            else:
                self.logger.info("⚖️ 近缘参考模式：相对宽松过滤，保留 15% 背景以保全突变区...")
                
            # SAMTools 处理管线:
            # 1. Minimap2 sr 双端映射
            # 2. 提取不完美成对映射 -F 2 (交界区、完全不匹配) -> unmapped.bam
            # 3. 抽取一定比例的完美成对映射 -f 2 (作为背景补足) -> sampled_bg.bam
            # 4. cat 拼接
            # 5. collate 归集 Pair 排序以符合组装器要求，写出合并好的 fastq
            bash_script = [
                f"minimap2 -t {optimal_threads} -ax sr '{wsl_host}' '{wsl_r1}' '{wsl_r2}' > '{shm_dir}/map.sam'",
                f"samtools view -u -F 2 '{shm_dir}/map.sam' > '{shm_dir}/unmapped.bam'",
                f"samtools view -u -s 42.{bg_fraction} -f 2 '{shm_dir}/map.sam' > '{shm_dir}/sampled_bg.bam'",
                f"samtools cat -o '{shm_dir}/merged.bam' '{shm_dir}/unmapped.bam' '{shm_dir}/sampled_bg.bam'",
                f"samtools collate -u -O '{shm_dir}/merged.bam' | samtools fastq -1 '{shm_clean_r1}' -2 '{shm_clean_r2}' -s '{shm_dir}/singletons.fq' -0 /dev/null -"
            ]
                
            msg = "执行差异过滤与并拢处理..."
            if self.on_progress: self.on_progress(40, msg)
            
            # 🔗 原子化执行 (将复杂的 shell 脚本作为一个整体传给底层 shell 引擎)
            ret = await self.runner.run_command("\n".join(bash_script), is_shell=True)
            if ret != 0:
                self.logger.error("❌ Soft-Dehosting 执行管线异常中断")
                return False
                
            final_r1 = out_dir / "clean_filtered_R1.fq.gz"
            final_r2 = out_dir / "clean_filtered_R2.fq.gz"
            
            msg = "正在内存盘内并发展开数据封包 (Parallel Gzip)..."
            if self.on_progress: self.on_progress(80, msg)
            self.logger.info(msg)
            
            has_pigz = (await self.runner.run_command(["which", "pigz"])) == 0
            zip_tool = "pigz -p 8" if has_pigz else "gzip -1"
            
            import asyncio
            from ..engine.runner import CommandRunner
            runner_r1 = CommandRunner(f"{self.__class__.__name__}.Zip1", is_wsl=True)
            runner_r2 = CommandRunner(f"{self.__class__.__name__}.Zip2", is_wsl=True)

            # 🚀 I/O 优化：先在内存盘内完成压缩，再一次性搬运
            shm_gz_r1 = f"{shm_dir}/clean_R1.fq.gz"
            shm_gz_r2 = f"{shm_dir}/clean_R2.fq.gz"
            
            cmd1 = f"{zip_tool} -c '{shm_clean_r1}' > '{shm_gz_r1}'"
            cmd2 = f"{zip_tool} -c '{shm_clean_r2}' > '{shm_gz_r2}'"

            retcodes = await asyncio.gather(
                runner_r1.run_command(cmd1, is_shell=True),
                runner_r2.run_command(cmd2, is_shell=True)
            )

            if any(r != 0 for r in retcodes):
                self.logger.error("并发封包过程中发生致命错误")
                return False
            
            # 🚀 原子搬运
            wsl_final_r1 = WSLManager.to_wsl_path(str(final_r1))
            wsl_final_r2 = WSLManager.to_wsl_path(str(final_r2))
            await self.runner.run_command(["cp", shm_gz_r1, wsl_final_r1])
            await self.runner.run_command(["cp", shm_gz_r2, wsl_final_r2])
            
            self.context.update("clean_r1", final_r1)
            self.context.update("clean_r2", final_r2)
            self.logger.info(f"✅ Soft-Dehosting 精准净化任务和封包完成")
            return True
            
        finally:
            self.logger.info("释放 Soft-Dehosting 内存资源...")
            if self.context.shm:
                await self.context.shm.release("softclean")
            else:
                await self.runner.run_command(["rm", "-rf", shm_dir])
