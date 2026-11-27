# -*- coding: utf-8 -*-
"""
生物安全性审计与抗防御系统扫描引擎 (DeepSafetyAuditor)
集成 CARD (耐药基因 AMR)、VFDB (毒力因子 VF)、Anti-CRISPR (Acr) 与防御逃逸扫描
"""
import csv
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from ...workbench.models.tool_config import ToolConfig

logger = logging.getLogger("analysis.annotation.deep_audit")


class DeepSafetyAuditor:
    """深度生物安全性与毒力/耐药性审计器"""

    def __init__(self, root_dir: Optional[Path] = None):
        # 与流水线其他环节保持一致：数据库根目录取自项目根，并兼容 database/database 历史布局
        self.root_dir = Path(root_dir) if root_dir else ToolConfig.PROJECT_ROOT
        self.db_dir = ToolConfig.DATABASE_ROOT
        self.phagescope_dir = ToolConfig.get_db_dir("phagescope")
        self.meta_dir = self.phagescope_dir / "metadata"
        self.diagnostics: Dict[str, Any] = {}

    def _get_wsl_path(self, win_path: Path) -> str:
        p = win_path.resolve()
        drive = p.drive.replace(":", "").lower()
        posix = p.as_posix().replace(f"{p.drive}/", "")
        return f"/mnt/{drive}/{posix}"

    @staticmethod
    def _load_meta_table(sub_dir: Path, id_col: str, desc_col: str) -> Dict[str, str]:
        """读取专家元数据 TSV 表，构建蛋白 ID 到描述的映射。"""
        target_dict: Dict[str, str] = {}
        if not sub_dir.exists():
            return target_dict
        for tsv_file in sub_dir.glob("*.tsv"):
            try:
                with open(tsv_file, "r", encoding="utf-8", errors="ignore") as f:
                    for row in csv.DictReader(f, delimiter="\t"):
                        pid = row.get(id_col)
                        if pid:
                            target_dict[pid] = row.get(desc_col, "")
            except Exception as exc:
                logger.warning("读取安全审计元数据表失败 (%s): %s", tsv_file, exc)
        return target_dict

    @staticmethod
    def _run_local_blastp(
        blastp_bin: str,
        query_faa: Path,
        db_dir: Path,
        db_name: str,
        out_file: Path,
        threads: int,
        max_targets: int = 1,
        evalue: str = "1e-5",
    ) -> bool:
        """执行受控超时与显式 UTF-8 的本地 BLASTP 安全审计比对。"""
        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.touch(exist_ok=True)
            cmd = [
                blastp_bin,
                "-query", str(query_faa.resolve()),
                "-db", db_name,
                "-out", str(out_file.resolve()),
                "-outfmt", "6 qseqid sseqid pident length evalue bitscore stitle",
                "-evalue", evalue,
                "-max_target_seqs", str(max_targets),
                "-num_threads", str(threads),
            ]
            res = subprocess.run(
                cmd,
                cwd=str(db_dir),
                capture_output=True,
                encoding="utf-8",
                errors="ignore",
                timeout=180,
            )
            return res.returncode == 0 and out_file.exists()
        except Exception as exc:
            logger.warning("本地安全审计 BLASTP 执行失败 (db=%s): %s", db_name, exc)
            return False

    def _scan_phagescope_safety(
        self,
        blastp_bin: str,
        query_faa: Path,
        work_dir: Path,
        threads: int,
        amr_index: Dict[str, str],
        vf_index: Dict[str, str],
        acr_index: Dict[str, str],
        amr_hits: Dict[str, dict],
        vf_hits: Dict[str, dict],
        acr_hits: Dict[str, dict],
    ) -> None:
        """扫描 PhageScope 元数据并按最高 bitscore 分别归并至 AMR / VF / Acr 命中池。"""
        if not (self.phagescope_dir.exists() and any(self.phagescope_dir.glob("phagescope_proteins.p*"))):
            return
        ps_out = work_dir / "safety_phagescope_hits.tsv"
        if not self._run_local_blastp(
            blastp_bin, query_faa, self.phagescope_dir, "phagescope_proteins", ps_out, threads, max_targets=5, evalue="1e-10"
        ):
            return
        with open(ps_out, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                cols = line.strip().split("\t")
                if len(cols) < 6:
                    continue
                cds_id, target_id, identity, align_len, evalue, bitscore = cols[:6]
                try:
                    ident_val = float(identity)
                    score_val = float(bitscore)
                    align_val = int(align_len)
                except ValueError as exc:
                    logger.debug("PhageScope 安全审计跳过异常行 (%s): %s", line.strip()[:60], exc)
                    continue

                hit_item = {
                    "cds_id": cds_id,
                    "target_id": target_id,
                    "identity": ident_val,
                    "align_len": align_val,
                    "evalue": evalue,
                    "bitscore": score_val,
                }
                for index_map, hit_pool, desc_key in (
                    (amr_index, amr_hits, "description"),
                    (vf_index, vf_hits, "description"),
                    (acr_index, acr_hits, "source"),
                ):
                    if target_id in index_map and (cds_id not in hit_pool or score_val > hit_pool[cds_id]["bitscore"]):
                        item = dict(hit_item)
                        item[desc_key] = index_map[target_id]
                        hit_pool[cds_id] = item

    def _scan_direct_blastp_db(
        self,
        blastp_bin: str,
        query_faa: Path,
        db_dir: Path,
        db_prefix: str,
        out_file: Path,
        threads: int,
        target_hits: Dict[str, dict],
        min_identity: float = 40.0,
    ) -> None:
        """扫描本地独立安全库 (CARD / VFDB) 并更新命中池。"""
        if not (db_dir.exists() and any(db_dir.glob(f"{db_prefix}.p*"))):
            return
        if not self._run_local_blastp(
            blastp_bin, query_faa, db_dir, db_prefix, out_file, threads, max_targets=1, evalue="1e-10"
        ):
            return
        with open(out_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                cols = line.strip().split("\t")
                if len(cols) < 7:
                    continue
                cds_id, target_id, identity, align_len, evalue, bitscore, stitle = cols[:7]
                try:
                    ident_val = float(identity)
                    if ident_val < min_identity:
                        continue
                    target_hits[cds_id] = {
                        "cds_id": cds_id,
                        "target_id": target_id,
                        "identity": ident_val,
                        "align_len": int(align_len),
                        "evalue": evalue,
                        "bitscore": float(bitscore),
                        "description": stitle,
                    }
                except ValueError as exc:
                    logger.debug("直接安全库 (%s) 跳过异常行 (%s): %s", db_prefix, line.strip()[:60], exc)

    @staticmethod
    def _finalize_audit_result(
        audit_result: Dict[str, Any],
        amr_hits: Dict[str, dict],
        vf_hits: Dict[str, dict],
        acr_hits: Dict[str, dict],
    ) -> Dict[str, Any]:
        """汇总三类命中记录并生成合规状态评级与风险警告。"""
        audit_result["amr_genes"] = list(amr_hits.values())
        audit_result["virulent_factors"] = list(vf_hits.values())
        audit_result["anti_crispr_genes"] = list(acr_hits.values())

        verified_acrs = [
            a for a in audit_result["anti_crispr_genes"]
            if "acranker" not in str(a.get("source", "")).lower() or a.get("identity", 0) >= 80.0
        ]
        total_acrs = len(audit_result["anti_crispr_genes"])
        if verified_acrs:
            audit_result["anti_crispr_status"] = f"Detected ({len(verified_acrs)} high-confidence Acr genes)"
        elif total_acrs > 0:
            audit_result["anti_crispr_status"] = f"Candidate Predicted ({total_acrs} ML predictions, low confidence)"
        else:
            audit_result["anti_crispr_status"] = "Not Detected"

        if audit_result["amr_genes"]:
            audit_result["safety_passed"] = False
            audit_result["risk_warnings"].append(f"检测到 {len(audit_result['amr_genes'])} 个潜在耐药基因 (CARD)")

        if audit_result["virulent_factors"]:
            audit_result["safety_passed"] = False
            audit_result["risk_warnings"].append(f"检测到 {len(audit_result['virulent_factors'])} 个潜在细菌毒力因子 (VFDB)")

        logger.info(
            "Safety Audit Complete: AMR=%s, VF=%s, Acr=%s, SafetyPassed=%s",
            len(audit_result["amr_genes"]),
            len(audit_result["virulent_factors"]),
            len(audit_result["anti_crispr_genes"]),
            audit_result["safety_passed"],
        )
        return audit_result

    def run_safety_audit(self, query_faa: Path, work_dir: Path, threads: int = 8) -> Dict[str, Any]:
        """
        对预测蛋白质执行深度安全性扫描
        返回包含 AMR、VF、Acr 的详细检测结果与安全合规评级
        """
        audit_result: Dict[str, Any] = {
            "amr_genes": [],
            "virulent_factors": [],
            "anti_crispr_genes": [],
            "anti_crispr_status": "Not Detected",
            "safety_passed": True,
            "risk_warnings": [],
        }

        if not query_faa.exists() or query_faa.stat().st_size == 0:
            return audit_result

        amr_index = self._load_meta_table(self.meta_dir / "amr", "Protein_id", "Aligned_Protein_in_CARD")
        vf_index = self._load_meta_table(self.meta_dir / "virulent_factor", "Protein_id", "Aligned_Protein_in_VFDB")
        acr_index = self._load_meta_table(self.meta_dir / "anti_crispr", "Protein_ID", "Source")

        logger.info(
            "Loaded Safety Metadata: %s AMR entries, %s VF entries, %s Acr entries",
            len(amr_index),
            len(vf_index),
            len(acr_index),
        )

        blastp_bin = ToolConfig.resolve_bio_tool("blastp")
        if blastp_bin is None:
            logger.error("未找到 blastp，可执行生物安全性审计被跳过；请安装 NCBI BLAST+ 或配置 blast_bin_path")
            self.diagnostics["blastp"] = "missing"
            return audit_result

        blastp_cmd = str(blastp_bin)
        amr_hits: Dict[str, dict] = {}
        vf_hits: Dict[str, dict] = {}
        acr_hits: Dict[str, dict] = {}

        self._scan_phagescope_safety(
            blastp_cmd, query_faa, work_dir, threads,
            amr_index, vf_index, acr_index,
            amr_hits, vf_hits, acr_hits,
        )
        self._scan_direct_blastp_db(
            blastp_cmd, query_faa, ToolConfig.get_db_dir("card"),
            "card_protein", work_dir / "safety_card_direct_hits.tsv", threads, amr_hits,
        )
        self._scan_direct_blastp_db(
            blastp_cmd, query_faa, ToolConfig.get_db_dir("vfdb"),
            "vfdb", work_dir / "safety_vfdb_direct_hits.tsv", threads, vf_hits,
        )

        return self._finalize_audit_result(audit_result, amr_hits, vf_hits, acr_hits)
