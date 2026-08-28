# -*- coding: utf-8 -*-
"""
蛋白质真实生物学功能注释与打捞分配引擎 (FunctionalAssigner)
利用本地权威数据库 (PhageScope, RefSeq, GenBank, PhagesDB, PHROGs, VFDB, CARD)
通过 BLASTP 多核并发比对与专家元数据映射，将预测 CDS 从 hypothetical protein 深度赋予真实功能
"""
import os
import csv
import sqlite3
import logging
import subprocess
import shutil
import ctypes
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Callable, Tuple

logger = logging.getLogger("analysis.annotation.functional_assigner")


class FunctionalAssigner:
    """功能注释推断与打捞器"""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir) if root_dir else Path(os.getcwd()).resolve()
        self.db_dir = self.root_dir / "database"
        self.phagescope_dir = self.db_dir / "phagescope"
        self.meta_protein_dir = self.phagescope_dir / "metadata" / "annotated_protein"
        self._protein_meta_cache: Optional[Dict[str, Dict[str, str]]] = None

    def _get_short_path(self, path_obj: Path) -> str:
        """获取 Windows 8.3 短路径，彻底规避包含空格与特殊字符的路径截断问题"""
        path_str = str(path_obj.resolve())
        if os.name != 'nt':
            return path_str
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            res = ctypes.windll.kernel32.GetShortPathNameW(path_str, buffer, 1024)
            if res > 0:
                return buffer.value
        except Exception:
            pass
        return path_str

    def _get_wsl_path(self, win_path: Path) -> str:
        """将 Windows 绝对路径转换为 WSL 路径"""
        p = win_path.resolve()
        drive = p.drive.replace(":", "").lower()
        posix = p.as_posix().replace(f"{p.drive}/", "")
        return f"/mnt/{drive}/{posix}"

    def _load_metadata_for_ids(self, target_ids: Set[str]) -> Dict[str, Dict[str, Optional[str]]]:
        """从元数据 TSV 表中快速按需检索 Target Protein_ID 的真实功能描述"""
        if not target_ids:
            return {}

        results: Dict[str, Dict[str, Optional[str]]] = {}
        tsv_files = [
            self.meta_protein_dir / "refseq_phage_annotated_protein_meta_data.tsv",
            self.meta_protein_dir / "genbank_phage_annotated_protein_meta_data.tsv",
            self.meta_protein_dir / "phagesdb_phage_annotated_protein_meta_data.tsv"
        ]

        for tsv_path in tsv_files:
            if not tsv_path.exists():
                continue
            try:
                with open(tsv_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    for row in reader:
                        pid = row.get("Protein_ID")
                        if pid and pid in target_ids and pid not in results:
                            prod = row.get("Product", "").strip()
                            if prod and "hypothetical protein" not in prod.lower() and prod.lower() != "unknown":
                                results[pid] = {
                                    "product": prod,
                                    "category": row.get("Protein_classification", "general").strip(),
                                    "gene": row.get("Gene_name", "").strip() or None
                                }
                                if len(results) == len(target_ids):
                                    break
            except Exception as e:
                logger.warning(f"Error reading metadata from {tsv_path}: {e}")

        return results

    def _clean_product_name(self, raw_prod: Optional[str]) -> str:
        """清洗并规范化功能描述文本 (自动解码 URL 编码、过滤 UniProt 头尾标识)"""
        if not raw_prod:
            return "hypothetical protein"
        from urllib.parse import unquote
        import re
        cleaned = unquote(raw_prod.strip())
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        cleaned = cleaned.replace("%20", " ").replace("%2C", ",").replace("%3B", ";")
        
        # 清洗 UniProt/Swiss-Prot 格式: sp|P03764|FIBER_LAMBD Tail fiber protein OS=... GN=...
        m_sp = re.match(r"^(?:sp|tr)\|[A-Z0-9_]+\|[A-Z0-9_]+\s+(.+)$", cleaned)
        if m_sp:
            cleaned = m_sp.group(1).strip()
        # 移除 OS=... OX=... GN=... PE=... SV=... 后缀
        cleaned = re.sub(r"\s+OS=.*$", "", cleaned).strip()
        return cleaned or "hypothetical protein"

    def run_blastp_annotation(
        self,
        query_faa: Path,
        work_dir: Path,
        threads: int = 8,
        evalue_threshold: float = 1e-5,
        identity_threshold: float = 30.0,
        on_progress: Optional[Callable[[int, str, Optional[str]], None]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        对 query_faa 蛋白质文件执行本地 BLASTP 并映射真实功能
        返回: { "CDS_ID": { "product": "...", "category": "...", "evalue": "...", "identity": 98.5 } }
        """
        if not query_faa.exists() or query_faa.stat().st_size == 0:
            logger.warning("Query FAA is empty or missing")
            return {}

        if on_progress:
            on_progress(10, "正在构建 BLASTP 同源检索任务 (多核并行)...", None)

        out_tsv = work_dir / "blastp_functional_hits.tsv"
        
        if self.phagescope_dir.exists() and any(self.phagescope_dir.glob("phagescope_proteins.p*")):
            if on_progress:
                on_progress(35, "正在比对 105 万条 PhageScope 权威噬菌体蛋白库...", None)
            self._run_blastp_query(query_faa, self.phagescope_dir, "phagescope_proteins", out_tsv, threads, evalue_threshold)

        if on_progress:
            on_progress(85, "BLASTP 检索完成，正在解析同源注释与可信度评分...", None)

        # 1. 读取所有比对命中的目标序列 ID
        hits_map: Dict[str, Dict[str, Any]] = {}
        target_ids: Set[str] = set()

        if out_tsv.exists() and out_tsv.stat().st_size > 0:
            with open(out_tsv, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 7:
                        qid, tid, pident, length, evalue, bitscore, stitle = parts[:7]
                        try:
                            pident_val = float(pident)
                        except ValueError:
                            pident_val = 0.0

                        if pident_val >= identity_threshold:
                            hits_map[qid] = {
                                "target_id": tid,
                                "identity": pident_val,
                                "evalue": evalue,
                                "bitscore": bitscore,
                                "stitle": stitle
                            }
                            target_ids.add(tid)

        logger.info(f"BLASTP produced {len(hits_map)} hits exceeding identity threshold ({identity_threshold}%)")

        # 2. 匹配真实功能描述元数据 (Tier 1: PhageScope)
        metadata_map = self._load_metadata_for_ids(target_ids)

        # 3. 组装最终注释映射
        functional_results: Dict[str, Dict[str, Any]] = {}
        for qid, hit in hits_map.items():
            tid = hit["target_id"]
            if tid in metadata_map:
                meta = metadata_map[tid]
                prod = self._clean_product_name(meta.get("product", ""))
                functional_results[qid] = {
                    "product": prod,
                    "category": meta.get("category", "general"),
                    "gene_name": meta.get("gene"),
                    "evalue": hit["evalue"],
                    "identity": hit["identity"],
                    "target_id": tid,
                    "source_db": "PhageScope"
                }
            else:
                stitle = hit.get("stitle", "")
                if stitle and not stitle.startswith(tid) and "hypothetical" not in stitle.lower():
                    functional_results[qid] = {
                        "product": self._clean_product_name(stitle),
                        "category": "general",
                        "gene_name": None,
                        "evalue": hit["evalue"],
                        "identity": hit["identity"],
                        "target_id": tid,
                        "source_db": "PhageScope"
                    }

        # 4. Tier 2: Swiss-Prot 金标准蛋白库二次打捞 (对仍为假定蛋白或未命中的 CDS)
        swissprot_dir = self.db_dir / "swissprot"
        if swissprot_dir.exists() and any(swissprot_dir.glob("swissprot.p*")):
            try:
                if on_progress:
                    on_progress(60, "正在通过 UniProt/Swiss-Prot 金标准库二次深度打捞...", None)
                sp_out = work_dir / "swissprot_hits.tsv"
                self._run_blastp_query(query_faa, swissprot_dir, "swissprot", sp_out, threads, evalue_threshold)
                if sp_out.exists() and sp_out.stat().st_size > 0:
                    with open(sp_out, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 7:
                                qid, tid, pident, length, evalue, bitscore, stitle = parts[:7]
                                if qid not in functional_results and float(pident) >= identity_threshold:
                                    prod_name = self._clean_product_name(stitle)
                                    if "hypothetical" not in prod_name.lower():
                                        functional_results[qid] = {
                                            "product": prod_name,
                                            "category": "general",
                                            "gene_name": None,
                                            "evalue": evalue,
                                            "identity": float(pident),
                                            "target_id": tid,
                                            "source_db": "Swiss-Prot"
                                        }
            except Exception as e:
                logger.warning(f"Swiss-Prot cascade annotation failed: {e}")

        # 5. Tier 4: NCBI CDD / Pfam-A 保守结构域与基序深度打捞 (RPS-BLAST)
        cdd_dir = self.db_dir / "cdd_pfam"
        if cdd_dir.exists() and (any(cdd_dir.glob("cdd_pfam.pal")) or any(cdd_dir.glob("cdd_pfam.*.rps"))):
            try:
                if on_progress:
                    on_progress(75, "正在通过 36GB NCBI CDD / Pfam-A 结构域模型库打捞基序特征...", None)
                cdd_out = work_dir / "cdd_hits.tsv"
                self._run_rpsblast_query(query_faa, cdd_dir, "cdd_pfam", cdd_out, threads, evalue_threshold)
                if cdd_out.exists() and cdd_out.stat().st_size > 0:
                    with open(cdd_out, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 7:
                                qid, tid, pident, length, evalue, bitscore, stitle = parts[:7]
                                if qid not in functional_results:
                                    prod_name, cat_name = self._parse_cdd_domain_product(stitle)
                                    if prod_name and "hypothetical" not in prod_name.lower():
                                        functional_results[qid] = {
                                            "product": prod_name,
                                            "category": cat_name,
                                            "gene_name": None,
                                            "evalue": evalue,
                                            "identity": float(pident),
                                            "target_id": tid,
                                            "source_db": "CDD/Pfam"
                                        }
            except Exception as e:
                logger.warning(f"CDD/Pfam cascade annotation failed: {e}")

        # 6. Tier 3: 毒力 (VFDB) 与耐药 (CARD) 安全性专项标记
        self._annotate_safety_flags(query_faa, work_dir, functional_results, threads, evalue_threshold)

        logger.info(f"Successfully assigned {len(functional_results)} real biological functions to CDS features across multi-tier databases")
        return functional_results

    def _run_blastp_query(self, query_faa: Path, db_dir: Path, db_name: str, out_tsv: Path, threads: int, evalue_threshold: float):
        """执行单次 BLASTP 比对通用方法 (自动短路径与跨平台回退)"""
        blastp_cmd = shutil.which("blastp") or "blastp"
        
        # 1. 优先使用 Windows 本地 BLASTP (通过 8.3 短路径规避包含空格引发的 BLAST+ 路径截断)
        try:
            short_query = self._get_short_path(query_faa)
            short_db_dir = self._get_short_path(db_dir)
            short_out = self._get_short_path(out_tsv)
            cmd = [
                blastp_cmd,
                "-query", short_query,
                "-db", db_name,
                "-out", short_out,
                "-outfmt", "6 qseqid sseqid pident length evalue bitscore stitle",
                "-evalue", str(evalue_threshold),
                "-max_target_seqs", "1",
                "-num_threads", str(threads)
            ]
            res = subprocess.run(cmd, cwd=short_db_dir, capture_output=True, encoding="utf-8", errors="ignore", timeout=180)
            if res.returncode == 0 and out_tsv.exists() and out_tsv.stat().st_size > 0:
                return
        except Exception as e:
            logger.warning(f"Native blastp query on {db_name} encountered error: {e}")

        # 2. 备用 WSL blastp 执行
        if shutil.which("wsl") is not None:
            try:
                wsl_q = self._get_wsl_path(query_faa)
                wsl_out = self._get_wsl_path(out_tsv)
                wsl_db = self._get_wsl_path(db_dir)
                bash_cmd = f"cd \"{wsl_db}\" && blastp -query \"{wsl_q}\" -db {db_name} -out \"{wsl_out}\" -outfmt \"6 qseqid sseqid pident length evalue bitscore stitle\" -evalue {evalue_threshold} -max_target_seqs 1 -num_threads {threads}"
                subprocess.run(["wsl", "bash", "-c", bash_cmd], capture_output=True, timeout=180)
            except Exception as e:
                logger.warning(f"WSL blastp query on {db_name} failed: {e}")

    def _annotate_safety_flags(self, query_faa: Path, work_dir: Path, functional_results: Dict[str, Dict[str, Any]], threads: int, evalue_threshold: float):
        """专项扫描 VFDB 与 CARD，并为 CDS 注入安全性标签"""
        # VFDB 毒力因子扫描
        vfdb_dir = self.db_dir / "vfdb"
        if vfdb_dir.exists() and any(vfdb_dir.glob("vfdb.p*")):
            try:
                vf_out = work_dir / "vfdb_hits.tsv"
                self._run_blastp_query(query_faa, vfdb_dir, "vfdb", vf_out, threads, evalue_threshold)
                if vf_out.exists() and vf_out.stat().st_size > 0:
                    with open(vf_out, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 7 and float(parts[2]) >= 40.0:
                                qid = parts[0]
                                if qid in functional_results:
                                    functional_results[qid]["is_virulence"] = True
                                    functional_results[qid]["virulence_desc"] = parts[6]
            except Exception as e:
                logger.warning(f"VFDB scan notice: {e}")

        # CARD 耐药基因扫描
        card_dir = self.db_dir / "card"
        if card_dir.exists() and any(card_dir.glob("card_protein.p*")):
            try:
                card_out = work_dir / "card_hits.tsv"
                self._run_blastp_query(query_faa, card_dir, "card_protein", card_out, threads, evalue_threshold)
                if card_out.exists() and card_out.stat().st_size > 0:
                    with open(card_out, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 7 and float(parts[2]) >= 40.0:
                                qid = parts[0]
                                if qid in functional_results:
                                    functional_results[qid]["is_resistance"] = True
                                    functional_results[qid]["resistance_desc"] = parts[6]
            except Exception as e:
                logger.warning(f"CARD scan notice: {e}")

    def _parse_cdd_domain_product(self, stitle: str) -> tuple:
        """
        解析 CDD/Pfam RPS-BLAST 命中标题并规范化功能产品名称与大类
        例: cd06127, DEDDh, DEDDh 3'-5' exonuclease domain family. -> ('DEDDh 3-5 exonuclease domain-containing protein', 'Replication & Repair')
        """
        if not stitle:
            return None, "general"
        
        raw = stitle.strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        
        # 尝试提取第二或第三段具体描述
        domain_name = ""
        if len(parts) >= 3:
            desc_part = parts[2].split(".")[0].strip()
            # 过滤掉方括号说明 [Transcription, ...]
            import re
            desc_part = re.sub(r"\[.*?\]", "", desc_part).strip()
            if len(desc_part) > 3 and "hypothetical" not in desc_part.lower():
                domain_name = desc_part
        if not domain_name and len(parts) >= 2:
            domain_name = parts[1].strip()

        if not domain_name:
            domain_name = raw.split(".")[0].strip()

        # 规范化命名
        lower_name = domain_name.lower()
        if "protein" not in lower_name:
            product = f"{domain_name} domain-containing protein"
        else:
            product = domain_name

        # 推断大类
        category = "general"
        if any(k in lower_name for k in ["endonuclease", "exonuclease", "helicase", "polymerase", "ligase", "primase", "recombinase", "dna", "rna"]):
            category = "Replication & Repair"
        elif any(k in lower_name for k in ["tail", "capsid", "portal", "baseplate", "head", "sheath", "fiber", "structural", "virion"]):
            category = "Structural"
        elif any(k in lower_name for k in ["lysin", "holin", "lysis", "spanin", "amidase"]):
            category = "Lysis"
        elif any(k in lower_name for k in ["transcription", "repressor", "activator", "regulator", "promoter"]):
            category = "Transcription & Regulation"
        elif any(k in lower_name for k in ["crispr", "restriction", "methyltransferase", "defense", "immunity"]):
            category = "Defense & Host Interaction"
        elif any(k in lower_name for k in ["kinase", "phosphatase", "synthase", "reductase", "dehydrogenase", "metabolism"]):
            category = "Metabolism & AMG"

        return product, category

    def _run_rpsblast_query(self, query_faa: Path, db_dir: Path, db_name: str, out_tsv: Path, threads: int, evalue_threshold: float):
        """执行 RPS-BLAST 结构域检索 (自动短路径与跨平台回退)"""
        rpsblast_cmd = shutil.which("rpsblast") or "rpsblast"
        
        try:
            short_query = self._get_short_path(query_faa)
            short_db_dir = self._get_short_path(db_dir)
            short_out = self._get_short_path(out_tsv)
            cmd = [
                rpsblast_cmd,
                "-query", short_query,
                "-db", db_name,
                "-out", short_out,
                "-outfmt", "6 qseqid sseqid pident length evalue bitscore stitle",
                "-evalue", str(evalue_threshold),
                "-max_target_seqs", "1",
                "-num_threads", str(threads)
            ]
            res = subprocess.run(cmd, cwd=short_db_dir, capture_output=True, encoding="utf-8", errors="ignore", timeout=240)
            if res.returncode == 0 and out_tsv.exists() and out_tsv.stat().st_size > 0:
                return
        except Exception as e:
            logger.warning(f"Native rpsblast query on {db_name} encountered error: {e}")

        # 备用 WSL rpsblast 执行
        if shutil.which("wsl") is not None:
            try:
                wsl_q = self._get_wsl_path(query_faa)
                wsl_out = self._get_wsl_path(out_tsv)
                wsl_db = self._get_wsl_path(db_dir)
                bash_cmd = f"cd \"{wsl_db}\" && rpsblast -query \"{wsl_q}\" -db {db_name} -out \"{wsl_out}\" -outfmt \"6 qseqid sseqid pident length evalue bitscore stitle\" -evalue {evalue_threshold} -max_target_seqs 1 -num_threads {threads}"
                subprocess.run(["wsl", "bash", "-c", bash_cmd], capture_output=True, timeout=240)
            except Exception as e:
                logger.warning(f"WSL rpsblast query on {db_name} failed: {e}")

