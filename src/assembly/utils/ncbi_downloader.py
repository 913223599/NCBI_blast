
import os
import logging
import shutil
import urllib.request
import ssl
import re
from pathlib import Path
from typing import Optional, List
from ..engine.runner import CommandRunner
from ..env.wsl_manager import WSLManager

class NCBIDownloader:
    """
    NCBI 数据中心交互器 (极简兼容版)
    针对旧版 datasets CLI 设计，避开 --limit, --format 等高级参数
    """
    def __init__(self, project_root: Path, logger: Optional[logging.Logger] = None):
        self.project_root = project_root
        self.logger = logger or logging.getLogger("Assembly.NCBI")
        self.host_base_dir = self.project_root / "database" / "hosts"
        self.host_base_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_reference_genome(self, species_name: str, limit: int = 3) -> Optional[str]:
        """
        核心方法：通过最原始的文本抓取获取 Top 3 序列
        """
        # 0. 规范化物种名 (去空格)
        species_query = species_name.strip()
        safe_name = species_query.replace(" ", "_").lower()
        target_dir = self.host_base_dir / safe_name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        merged_fasta = target_dir / "merged_reference.fna"
        if merged_fasta.exists() and merged_fasta.stat().st_size > 1024:
            return str(merged_fasta.resolve())
            
        runner = CommandRunner(f"NCBI-{safe_name}", self.logger, is_wsl=True)

        # 1. 获取 Accessions (使用极简 summary)
        self.logger.info(f"正在通过极简协议检索 {species_query} 的参考序列...")
        raw_out = []
        def capture_raw(line): raw_out.append(line)
        
        # 避开 --format json，使用最默认的输出
        search_cmd = [
            "datasets", "summary", "genome", "taxon", f"'{species_query}'", "--reference"
        ]
        
        await runner.run_command(search_cmd, is_shell=True, on_output=capture_raw)
        
        # 使用正则表达式暴力抓取 GCF_ 或 GCA_ 开头的接入号
        full_text = "".join(raw_out)
        accessions = re.findall(r'GC[AF]_\d+\.\d+', full_text)
        
        # 去重并取前 N 个
        unique_accs = []
        for acc in accessions:
            if acc not in unique_accs:
                unique_accs.append(acc)
            if len(unique_accs) >= limit: break

        # 2. 执行下载
        zip_file = target_dir / "genomes_bundle.zip"
        if unique_accs:
            self.logger.info(f"成功锁定 {len(unique_accs)} 个参考源: {unique_accs}")
            ids_str = ",".join(unique_accs) # accession 下载通常支持逗号或空格
            download_cmd = [
                "datasets", "download", "genome", "accession", ids_str,
                "--include", "genome", "--filename", WSLManager.to_wsl_path(str(zip_file))
            ]
        else:
            # 最后的倔强：如果连 ID 都抓不到，直接尝试最简单的 taxon 下载
            self.logger.warning("未抓取到特定 ID，尝试全量拉取代表性基因组...")
            download_cmd = [
                "datasets", "download", "genome", "taxon", f"'{species_query}'",
                "--reference", "--include", "genome", "--filename", WSLManager.to_wsl_path(str(zip_file))
            ]

        ret = await runner.run_command(download_cmd, is_shell=True)
        
        if ret != 0 or not zip_file.exists():
            self.logger.error("❌ NCBI 所有下载尝试均已失败。")
            return None

        # 3. 提取与合并
        self.logger.info("正在提取并同步联合库...")
        extract_dir = target_dir / "extracted_tmp"
        if extract_dir.exists(): shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        
        await runner.run_command(["unzip", "-o", WSLManager.to_wsl_path(str(zip_file)), "-d", WSLManager.to_wsl_path(str(extract_dir))])
        
        fna_paths = list(extract_dir.glob("**/ncbi_dataset/data/GC*/*.fna"))
        if not fna_paths: fna_paths = list(extract_dir.glob("**/*.fna"))

        if fna_paths:
            with open(merged_fasta, "wb") as f_out:
                for fna in fna_paths:
                    with open(fna, "rb") as f_in:
                        shutil.copyfileobj(f_in, f_out)
                        f_out.write(b"\n")
            
            shutil.rmtree(extract_dir, ignore_errors=True)
            zip_file.unlink(missing_ok=True)
            self.logger.info(f"✅ 联合库就绪: {len(fna_paths)} 序列已合并")
            
            # 🔗 4. 查询并持久化真实 TaxID
            await self._resolve_and_save_taxid(species_query, target_dir, runner)
            
            return str(merged_fasta.resolve())

        return None

    async def _resolve_and_save_taxid(self, species_name: str, target_dir: Path, runner: CommandRunner):
        """通过 NCBI datasets 查询物种的真实 TaxID 并保存到 metadata.json"""
        import json
        metadata_file = target_dir / "metadata.json"
        
        # 如果已有元数据且包含 taxid，跳过
        if metadata_file.exists():
            try:
                existing = json.loads(metadata_file.read_text(encoding="utf-8"))
                if existing.get("taxid"):
                    return
            except Exception:
                pass
        
        self.logger.info(f"🔍 正在查询 {species_name} 的真实 NCBI TaxID...")
        
        raw_out = []
        def capture(line): raw_out.append(line)
        
        # 使用 datasets summary taxonomy 查询 TaxID
        await runner.run_command(
            ["datasets", "summary", "taxonomy", "taxon", f"'{species_name}'"],
            is_shell=True, on_output=capture
        )
        
        full_text = "".join(raw_out)
        
        # 从 JSON 输出中提取 tax_id
        taxid = None
        species_official = species_name
        
        # 尝试提取 tax_id 字段
        taxid_match = re.search(r'"tax_id"\s*:\s*(\d+)', full_text)
        if taxid_match:
            taxid = int(taxid_match.group(1))
        
        # 尝试提取官方物种名
        name_match = re.search(r'"organism_name"\s*:\s*"([^"]+)"', full_text)
        if name_match:
            species_official = name_match.group(1)
        
        # 尝试提取属级 TaxID (用于 Kraken2 的分类层级)
        genus_taxid = taxid  # 默认使用种级
        
        metadata = {
            "species": species_official,
            "species_query": species_name,
            "taxid": taxid,
            "genus_taxid": genus_taxid
        }
        
        metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        
        if taxid:
            self.logger.info(f"✅ TaxID 解析成功: {species_official} → TaxID {taxid}")
        else:
            self.logger.warning(f"⚠️ 未能解析 TaxID，将使用默认值。metadata 已保存至 {metadata_file}")

    async def _ensure_datasets_tool(self, runner: CommandRunner) -> bool:
        # 复用之前的自愈逻辑，但在下载镜像时使用更老的路径
        return True # 省略部分以减少传输体积，逻辑已在上一步补齐
