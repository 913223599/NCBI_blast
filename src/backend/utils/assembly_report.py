"""
assembly_report.py - 基因组拼接报告数据解析器
负责从各步骤的产物文件中提取关键信息，生成结构化报告

遵循单一职责原则：只负责解析产物文件，不涉及路由或存储逻辑
"""

import csv
import json
import os
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("api_server")


class AssemblyReportParser:
    """从拼接任务的各步骤产物中提取报告数据"""

    def __init__(self, task_dir: Path):
        self.task_dir = task_dir

    def generate_report(self) -> dict:
        """生成完整的结构化报告"""
        report = {
            "qc": self._parse_qc(),
            "host_removal": self._parse_host_removal(),
            "assembly": self._parse_assembly(),
            "annotation": self._parse_annotation(),
        }
        return report

    # ─── 质控 (QC) ────────────────────────────────────

    def _parse_qc(self) -> Optional[dict]:
        """解析 fastp JSON 报告"""
        qc_dir = self.task_dir / "qualitycontrolstep"
        if not qc_dir.exists():
            return None

        # 寻找 fastp json 报告文件
        fastp_json = None
        for name in ["fastp.json", "fastp_report.json"]:
            candidate = qc_dir / name
            if candidate.exists():
                fastp_json = candidate
                break

        # 如果任务目录没有，尝试项目根目录（fastp 默认输出）
        if not fastp_json:
            project_root = self.task_dir.parent.parent
            for name in ["fastp.json"]:
                candidate = project_root / name
                if candidate.exists():
                    fastp_json = candidate
                    break

        if not fastp_json:
            # 仅报告清洁文件大小
            clean_files = list(qc_dir.glob("*.clean.fq.gz"))
            if clean_files:
                return {
                    "status": "partial",
                    "clean_files": [
                        {"name": f.name, "size_mb": round(f.stat().st_size / 1048576, 1)}
                        for f in clean_files
                    ],
                }
            return None

        try:
            with open(fastp_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            summary = data.get("summary", {})
            before = summary.get("before_filtering", {})
            after = summary.get("after_filtering", {})
            filtering = data.get("filtering_result", {})

            return {
                "status": "ok",
                "before": {
                    "total_reads": before.get("total_reads", 0),
                    "total_bases": before.get("total_bases", 0),
                    "q20_rate": before.get("q20_rate", 0),
                    "q30_rate": before.get("q30_rate", 0),
                    "gc_content": before.get("gc_content", 0),
                },
                "after": {
                    "total_reads": after.get("total_reads", 0),
                    "total_bases": after.get("total_bases", 0),
                    "q20_rate": after.get("q20_rate", 0),
                    "q30_rate": after.get("q30_rate", 0),
                    "gc_content": after.get("gc_content", 0),
                },
                "filtering": {
                    "passed": filtering.get("passed_filter_reads", 0),
                    "low_quality": filtering.get("low_quality_reads", 0),
                    "too_many_N": filtering.get("too_many_N_reads", 0),
                    "too_short": filtering.get("too_short_reads", 0),
                },
            }
        except Exception as e:
            logger.warning(f"[Report] QC parse error: {e}")
            return None

    # ─── 宿主剔除 ─────────────────────────────────────

    def _parse_host_removal(self) -> Optional[dict]:
        """解析宿主剔除步骤的产物"""
        host_dir = self.task_dir / "hostcleanerstep"
        if not host_dir.exists():
            return None

        bam_file = host_dir / "mapped_to_host.bam"
        unmapped_r1 = host_dir / "unmapped_R1.fastq.gz"
        unmapped_r2 = host_dir / "unmapped_R2.fastq.gz"

        result = {"status": "ok", "files": []}
        if bam_file.exists():
            result["bam_size_mb"] = round(bam_file.stat().st_size / 1048576, 1)
        if unmapped_r1.exists():
            result["files"].append(
                {"name": unmapped_r1.name, "size_mb": round(unmapped_r1.stat().st_size / 1048576, 1)}
            )
        if unmapped_r2.exists():
            result["files"].append(
                {"name": unmapped_r2.name, "size_mb": round(unmapped_r2.stat().st_size / 1048576, 1)}
            )

        return result if result["files"] else None

    # ─── 组装 ─────────────────────────────────────────

    def _parse_assembly(self) -> Optional[dict]:
        """解析 Unicycler 组装结果"""
        asm_dir = self.task_dir / "assemblerstep" / "unicycler_run"
        fasta = asm_dir / "assembly.fasta"
        if not fasta.exists():
            return None

        contigs = []
        total_len = 0
        current_id = None
        current_len = 0

        try:
            with open(fasta, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(">"):
                        if current_id is not None:
                            contigs.append({"id": current_id, "length": current_len})
                            total_len += current_len
                        current_id = line[1:].split()[0]
                        current_len = 0
                    else:
                        current_len += len(line)
                if current_id is not None:
                    contigs.append({"id": current_id, "length": current_len})
                    total_len += current_len
        except Exception as e:
            logger.warning(f"[Report] Assembly FASTA parse error: {e}")
            return None

        # 计算 N50
        lengths = sorted([c["length"] for c in contigs], reverse=True)
        n50 = 0
        running = 0
        for l in lengths:
            running += l
            if running >= total_len / 2:
                n50 = l
                break

        return {
            "status": "ok",
            "num_contigs": len(contigs),
            "total_length": total_len,
            "n50": n50,
            "longest": lengths[0] if lengths else 0,
            "shortest": lengths[-1] if lengths else 0,
            "contigs": contigs[:20],  # 最多返回前 20 条
        }

    # ─── 注释 (Pharokka + Phold) ─────────────────────

    def _parse_annotation(self) -> Optional[dict]:
        """解析 Pharokka & Phold 注释产物"""
        anno_dir = self.task_dir / "phageannotationstep"
        pharokka_dir = anno_dir / "pharokka_res"
        phold_dir = anno_dir / "phold_res"

        if not pharokka_dir.exists():
            return None

        result = {"status": "ok", "pharokka": {}, "phold": None}

        # --- Pharokka: 基因组基础信息 ---
        gc_file = pharokka_dir / "PHAGE_length_gc_cds_density.tsv"
        if gc_file.exists():
            result["pharokka"]["genome"] = self._parse_tsv_first_row(gc_file)

        # --- Pharokka: 功能分类统计 ---
        func_file = pharokka_dir / "PHAGE_cds_functions.tsv"
        if func_file.exists():
            result["pharokka"]["functions"] = self._parse_function_tsv(func_file)

        # --- Pharokka: MASH 分类鉴定 ---
        mash_file = pharokka_dir / "PHAGE_top_hits_mash_inphared.tsv"
        if mash_file.exists():
            result["pharokka"]["classification"] = self._parse_tsv_first_row(mash_file)

        # --- Pharokka: 耐药 & 毒力 ---
        card_file = pharokka_dir / "top_hits_card.tsv"
        if card_file.exists():
            result["pharokka"]["card"] = self._parse_tsv_all(card_file)

        vfdb_file = pharokka_dir / "top_hits_vfdb.tsv"
        if vfdb_file.exists():
            result["pharokka"]["vfdb"] = self._parse_tsv_all(vfdb_file)

        # --- Phold: AI 结构预测结果 ---
        if phold_dir.exists():
            phold_cds = phold_dir / "phold_per_cds_predictions.tsv"
            phold_func = phold_dir / "phold_all_cds_functions.tsv"

            phold_data = {}
            if phold_cds.exists():
                rows = self._parse_tsv_all(phold_cds)
                phold_data["total_cds"] = len(rows)
                # 统计各功能类别
                func_counts = {}
                confidence_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
                for row in rows:
                    func = row.get("function", "unknown function")
                    func_counts[func] = func_counts.get(func, 0) + 1
                    conf = row.get("annotation_confidence", "none")
                    if conf in confidence_counts:
                        confidence_counts[conf] += 1
                phold_data["function_summary"] = [
                    {"function": k, "count": v}
                    for k, v in sorted(func_counts.items(), key=lambda x: -x[1])
                ]
                phold_data["confidence"] = confidence_counts
                # 返回前 30 条详细预测
                phold_data["predictions"] = [
                    {
                        "cds_id": r.get("cds_id", ""),
                        "start": r.get("start", ""),
                        "end": r.get("end", ""),
                        "strand": r.get("strand", ""),
                        "function": r.get("function", ""),
                        "product": r.get("product", ""),
                        "method": r.get("annotation_method", ""),
                        "confidence": r.get("annotation_confidence", ""),
                    }
                    for r in rows[:50]
                ]

            if phold_func.exists():
                phold_data["all_functions"] = self._parse_function_tsv(phold_func)

            if phold_data:
                result["phold"] = phold_data

        return result

    # ─── 通用 TSV 解析工具 ────────────────────────────

    @staticmethod
    def _parse_tsv_first_row(path: Path) -> dict:
        """解析 TSV 文件的第一行数据（表头 + 首条记录）"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    return dict(row)
        except Exception:
            pass
        return {}

    @staticmethod
    def _parse_tsv_all(path: Path) -> list:
        """解析 TSV 文件的所有数据行"""
        rows = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    rows.append(dict(row))
        except Exception:
            pass
        return rows

    @staticmethod
    def _parse_function_tsv(path: Path) -> list:
        """解析功能分类 TSV (Description / Count 格式)"""
        items = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    desc = row.get("Description", "")
                    count = row.get("Count", "0")
                    if desc:
                        items.append({"name": desc, "count": int(count)})
        except Exception:
            pass
        return items
