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
        """清洗并规范化功能描述文本 (自动解码 URL 编码与多余引号)"""
        if not raw_prod:
            return "hypothetical protein"
        from urllib.parse import unquote
        cleaned = unquote(raw_prod.strip())
        # 移除多余的 NCBI 引号或括号包裹
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        cleaned = cleaned.replace("%20", " ").replace("%2C", ",").replace("%3B", ";")
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
        db_path = self.phagescope_dir / "phagescope_proteins"

        # 优先使用 WSL blastp 避开 Windows 路径空格与内存映射限制
        has_wsl = shutil.which("wsl") is not None
        blast_success = False

        if has_wsl and self.phagescope_dir.exists():
            wsl_query = self._get_wsl_path(query_faa)
            wsl_out = self._get_wsl_path(out_tsv)
            wsl_db_dir = self._get_wsl_path(self.phagescope_dir)
            
            # 使用 cd 切换到数据库所在目录，完全规避 BLAST+ 路径空格问题
            bash_cmd = f"cd \"{wsl_db_dir}\" && blastp -query \"{wsl_query}\" -db phagescope_proteins -out \"{wsl_out}\" -outfmt \"6 qseqid sseqid pident length evalue bitscore stitle\" -evalue {evalue_threshold} -max_target_seqs 1 -num_threads {threads}"
            
            try:
                if on_progress:
                    on_progress(35, "正在比对 105 万条 PhageScope 权威噬菌体蛋白库...", bash_cmd)
                cmd = ["wsl", "bash", "-c", bash_cmd]
                logger.info(f"Running functional BLASTP via WSL (threads={threads})...")
                res = subprocess.run(cmd, capture_output=True, timeout=300)
                if res.returncode == 0 and out_tsv.exists() and out_tsv.stat().st_size > 0:
                    blast_success = True
                    logger.info("WSL BLASTP execution succeeded")
            except Exception as e:
                logger.warning(f"WSL BLASTP execution encountered error: {e}")

        # 若 WSL 未成功，尝试本地 Windows blastp
        if not blast_success and shutil.which("blastp"):
            try:
                if on_progress:
                    on_progress(45, "正在通过本地 BLASTP 检索参考数据库...", None)
                logger.info("Attempting native Windows blastp...")
                cmd = [
                    "blastp",
                    "-query", str(query_faa),
                    "-db", "phagescope_proteins",
                    "-out", str(out_tsv),
                    "-outfmt", "6 qseqid sseqid pident length evalue bitscore stitle",
                    "-evalue", str(evalue_threshold),
                    "-max_target_seqs", "1",
                    "-num_threads", str(threads)
                ]
                res = subprocess.run(cmd, cwd=str(self.phagescope_dir), capture_output=True, timeout=300)
                if res.returncode == 0 and out_tsv.exists() and out_tsv.stat().st_size > 0:
                    blast_success = True
            except Exception as e:
                logger.warning(f"Native blastp execution failed: {e}")

        if on_progress:
            on_progress(85, "BLASTP 检索完成，正在解析同源注释与可信度评分...", None)

        if not out_tsv.exists() or out_tsv.stat().st_size == 0:
            logger.warning("No BLASTP output generated, keeping base annotations")
            return {}

        # 1. 读取所有比对命中的目标序列 ID
        hits_map: Dict[str, Dict[str, Any]] = {}
        target_ids: Set[str] = set()

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

        # 2. 匹配真实功能描述元数据
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
                    "target_id": tid
                }
            else:
                # 尝试从 stitle 提取（若包含完整描述）
                stitle = hit.get("stitle", "")
                if stitle and not stitle.startswith(tid) and "hypothetical" not in stitle.lower():
                    functional_results[qid] = {
                        "product": self._clean_product_name(stitle),
                        "category": "general",
                        "gene_name": None,
                        "evalue": hit["evalue"],
                        "identity": hit["identity"],
                        "target_id": tid
                    }

        logger.info(f"Successfully assigned {len(functional_results)} real biological functions to CDS features")
        return functional_results
