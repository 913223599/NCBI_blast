# -*- coding: utf-8 -*-
"""
生物安全性审计与抗防御系统扫描引擎 (DeepSafetyAuditor)
集成 CARD (耐药基因 AMR)、VFDB (毒力因子 VF)、Anti-CRISPR (Acr) 与防御逃逸扫描
"""
import os
import csv
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("analysis.annotation.deep_audit")


class DeepSafetyAuditor:
    """深度生物安全性与毒力/耐药性审计器"""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = Path(root_dir) if root_dir else Path(os.getcwd()).resolve()
        self.db_dir = self.root_dir / "database"
        self.phagescope_dir = self.db_dir / "phagescope"
        self.meta_dir = self.phagescope_dir / "metadata"

    def _get_wsl_path(self, win_path: Path) -> str:
        p = win_path.resolve()
        drive = p.drive.replace(":", "").lower()
        posix = p.as_posix().replace(f"{p.drive}/", "")
        return f"/mnt/{drive}/{posix}"

    def run_safety_audit(self, query_faa: Path, work_dir: Path, threads: int = 8) -> Dict[str, Any]:
        """
        对预测蛋白质执行深度安全性扫描
        返回包含 AMR、VF、Acr 的详细检测结果与安全合规评级
        """
        audit_result = {
            "amr_genes": [],
            "virulent_factors": [],
            "anti_crispr_genes": [],
            "anti_crispr_status": "Not Detected",
            "safety_passed": True,
            "risk_warnings": []
        }

        if not query_faa.exists() or query_faa.stat().st_size == 0:
            return audit_result

        # 1. 装载 CARD、VFDB、Anti-CRISPR 专家元数据字典
        amr_index: Dict[str, str] = {}
        vf_index: Dict[str, str] = {}
        acr_index: Dict[str, str] = {}

        def load_meta_table(sub_dir: Path, id_col: str, desc_col: str, target_dict: dict):
            if not sub_dir.exists():
                return
            for tsv_file in sub_dir.glob("*.tsv"):
                try:
                    with open(tsv_file, "r", encoding="utf-8", errors="ignore") as f:
                        for row in csv.DictReader(f, delimiter="\t"):
                            pid = row.get(id_col)
                            if pid:
                                target_dict[pid] = row.get(desc_col, "")
                except Exception as e:
                    logger.warning(f"Error loading {tsv_file}: {e}")

        load_meta_table(self.meta_dir / "amr", "Protein_id", "Aligned_Protein_in_CARD", amr_index)
        load_meta_table(self.meta_dir / "virulent_factor", "Protein_id", "Aligned_Protein_in_VFDB", vf_index)
        load_meta_table(self.meta_dir / "anti_crispr", "Protein_ID", "Source", acr_index)

        logger.info(f"Loaded Safety Metadata: {len(amr_index)} AMR entries, {len(vf_index)} VF entries, {len(acr_index)} Acr entries")

        # 2. 运行严格 BLASTP 比对 (E-value <= 1e-10)
        out_tsv = work_dir / "safety_audit_blast_hits.tsv"
        wsl_query = self._get_wsl_path(query_faa)
        wsl_out = self._get_wsl_path(out_tsv)
        wsl_db_dir = self._get_wsl_path(self.phagescope_dir)

        bash_cmd = f"cd \"{wsl_db_dir}\" && blastp -query \"{wsl_query}\" -db phagescope_proteins -out \"{wsl_out}\" -outfmt \"6 qseqid sseqid pident length evalue bitscore\" -evalue 1e-10 -max_target_seqs 5 -num_threads {threads}"

        # 临时存储最优 hit
        amr_hits: Dict[str, dict] = {}
        vf_hits: Dict[str, dict] = {}
        acr_hits: Dict[str, dict] = {}

        try:
            res = subprocess.run(["wsl", "bash", "-c", bash_cmd], capture_output=True, timeout=300)
            if res.returncode == 0 and out_tsv.exists() and out_tsv.stat().st_size > 0:
                with open(out_tsv, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        cols = line.strip().split("\t")
                        if len(cols) < 6:
                            continue
                        cds_id, target_id, identity, align_len, evalue, bitscore = cols[:6]
                        try:
                            ident_val = float(identity)
                            score_val = float(bitscore)
                        except ValueError:
                            continue

                        hit_item = {
                            "cds_id": cds_id,
                            "target_id": target_id,
                            "identity": ident_val,
                            "align_len": int(align_len),
                            "evalue": evalue,
                            "bitscore": score_val
                        }

                        # 耐药基因匹配 (取该 CDS 的最高分)
                        if target_id in amr_index:
                            if cds_id not in amr_hits or score_val > amr_hits[cds_id]["bitscore"]:
                                h = dict(hit_item)
                                h["description"] = amr_index[target_id]
                                amr_hits[cds_id] = h

                        # 毒力因子匹配 (取最高分)
                        if target_id in vf_index:
                            if cds_id not in vf_hits or score_val > vf_hits[cds_id]["bitscore"]:
                                h = dict(hit_item)
                                h["description"] = vf_index[target_id]
                                vf_hits[cds_id] = h

                        # Anti-CRISPR 匹配 (取最高分)
                        if target_id in acr_index:
                            if cds_id not in acr_hits or score_val > acr_hits[cds_id]["bitscore"]:
                                h = dict(hit_item)
                                h["source"] = acr_index[target_id]
                                acr_hits[cds_id] = h
        except Exception as e:
            logger.warning(f"Safety audit BLASTP failed: {e}")

        audit_result["amr_genes"] = list(amr_hits.values())
        audit_result["virulent_factors"] = list(vf_hits.values())
        audit_result["anti_crispr_genes"] = list(acr_hits.values())

        # 3. 结果汇总与合规评级
        if audit_result["anti_crispr_genes"]:
            audit_result["anti_crispr_status"] = f"Detected ({len(audit_result['anti_crispr_genes'])} unique Acr genes)"

        if audit_result["amr_genes"]:
            audit_result["safety_passed"] = False
            audit_result["risk_warnings"].append(f"检测到 {len(audit_result['amr_genes'])} 个潜在耐药基因 (AMR)")

        if audit_result["virulent_factors"]:
            audit_result["safety_passed"] = False
            audit_result["risk_warnings"].append(f"检测到 {len(audit_result['virulent_factors'])} 个潜在细菌毒力因子 (VFDB)")

        logger.info(f"Safety Audit Complete: AMR={len(audit_result['amr_genes'])}, VF={len(audit_result['virulent_factors'])}, Acr={len(audit_result['anti_crispr_genes'])}, SafetyPassed={audit_result['safety_passed']}")
        return audit_result
