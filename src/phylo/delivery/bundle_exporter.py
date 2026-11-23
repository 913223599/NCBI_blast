# -*- coding: utf-8 -*-
"""
DeliveryBundleExporter - 产出完整论文/客户交付归档包
包含：tree.treefile/.nwk、trimmed_alignment.fasta、ani_matrix.csv、
      iTOL 注释模板目录、qc_report.md/json 及可复现脚本 reproduce.sh。
"""
import csv
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from ..models.schemas import AniScreenResult, DeliveryQcReport, MarkerExtractionReport


class DeliveryBundleExporter:
    """将所有构建产物打包为可直接交付/投稿的标准 ZIP 归档。"""

    @staticmethod
    def write_reports_and_pack(
        job_dir: Path,
        job_id: str,
        title: str,
        newick: str,
        qc_report: DeliveryQcReport,
        ani_result: Optional[AniScreenResult],
        marker_report: Optional[MarkerExtractionReport],
        trimmed_msa_path: Optional[Path],
        treefile_path: Optional[Path],
        itol_dir: Path,
        commands_used: List[str],
    ) -> Path:
        delivery_dir = job_dir / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)

        # 1. qc_report.json
        qc_json = delivery_dir / "qc_report.json"
        qc_json.write_text(
            json.dumps(qc_report.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 2. qc_report.md (简体中文可读报告)
        qc_md = delivery_dir / "qc_report.md"
        lines: List[str] = [
            f"# 噬菌体分类鉴定与系统发育交付质检报告 ({title})",
            "",
            f"- 任务 ID: `{job_id}`",
            f"- 综合质检状态: `{qc_report.overall_status.upper()}`",
            f"- 最优替换模型: `{qc_report.best_model or 'N/A'}` (BIC: `{qc_report.best_model_bic if qc_report.best_model_bic is not None else 'N/A'}`)",
            "",
            "## 一、规范分类学结论建议",
            "",
            "**中文表述：**",
            qc_report.conclusion_zh,
            "",
            "**English Statement (Manuscript Ready):**",
            qc_report.conclusion_en,
            "",
            "## 二、交付前质检清单（8 步工作流核查）",
            "",
            "| 检查项 | 通过标准 | 状态 | 实测观测 | 详细说明 |",
            "|---|---|---|---|---|",
        ]
        for chk in qc_report.checks:
            lines.append(
                f"| {chk.title} | {chk.criterion} | {chk.status.upper()} | {chk.observed} | {chk.explanation} |"
            )

        if ani_result and ani_result.top_hits:
            lines.extend(
                [
                    "",
                    "## 三、全基因组 ANI 预判 Top 10",
                    "",
                    "| Accession | wgANI (%) | Aligned ANI (%) | Query AF (%) | Ref AF (%) | ICTV 属 | 宿主 | 初步判定 |",
                    "|---|---|---|---|---|---|---|---|",
                ]
            )
            for hit in ani_result.top_hits[:10]:
                lines.append(
                    f"| {hit.accession} | {hit.wg_ani:.2f} | {hit.aligned_ani:.2f} | {hit.af_query:.1f} | {hit.af_ref:.1f} | "
                    f"{hit.genus or '-'} | {hit.host or '-'} | {hit.classification_call} |"
                )

        if marker_report:
            lines.extend(
                [
                    "",
                    f"## 四、标志基因提取摘要 (`{marker_report.mode}`)",
                    "",
                    f"- 工具: `{marker_report.tool_used}` ({marker_report.tool_version})",
                    f"- 成功提取: `{marker_report.extracted_count}/{marker_report.total_genomes}`",
                ]
            )
            if marker_report.missing_ids:
                lines.append(f"- 缺失样本: `{', '.join(marker_report.missing_ids)}`")

        qc_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 3. ani_matrix.csv (若有矩阵)
        ani_csv: Optional[Path] = None
        if ani_result and ani_result.matrix_labels and ani_result.wgani_matrix:
            ani_csv = delivery_dir / "ani_matrix.csv"
            with open(ani_csv, "w", encoding="utf-8", newline="") as cfh:
                writer = csv.writer(cfh)
                writer.writerow(["Genome"] + ani_result.matrix_labels)
                for lbl, row_vals in zip(
                    ani_result.matrix_labels, ani_result.wgani_matrix, strict=True
                ):
                    writer.writerow([lbl] + [round(float(v), 2) for v in row_vals])

        # 4. reproduce.sh
        repro_sh = delivery_dir / "reproduce.sh"
        sh_lines = ["#!/usr/bin/env bash", "set -euo pipefail", "# PhyloCore Reproducible Commands"]
        for c in commands_used:
            if c.strip():
                sh_lines.append(c.strip())
        if qc_report.iqtree_command:
            sh_lines.append(qc_report.iqtree_command.strip())
        repro_sh.write_text("\n".join(sh_lines) + "\n", encoding="utf-8", newline="\n")

        # 5. 打包 delivery_bundle.zip
        zip_path = job_dir / f"phylo_delivery_{job_id}.zip"
        files_to_pack: Dict[str, Path] = {}
        nwk_file = job_dir / "tree.nwk"
        if not nwk_file.is_file():
            nwk_file.write_text(newick, encoding="utf-8")
        files_to_pack["tree.nwk"] = nwk_file

        if treefile_path and treefile_path.is_file():
            files_to_pack["tree.treefile"] = treefile_path
        if trimmed_msa_path and trimmed_msa_path.is_file():
            files_to_pack["trimmed_alignment.fasta"] = trimmed_msa_path
        if ani_csv and ani_csv.is_file():
            files_to_pack["ani_matrix.csv"] = ani_csv
        files_to_pack["qc_report.md"] = qc_md
        files_to_pack["qc_report.json"] = qc_json
        files_to_pack["reproduce.sh"] = repro_sh

        if itol_dir.is_dir():
            for fp in sorted(itol_dir.iterdir()):
                if fp.is_file():
                    files_to_pack[f"itol/{fp.name}"] = fp

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arc_name, src_path in files_to_pack.items():
                zf.write(src_path, arcname=arc_name)

        return zip_path
