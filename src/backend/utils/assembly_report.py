"""
assembly_report.py - 基因组拼接报告数据解析器
负责从各步骤的产物文件中提取关键指标, 生成结构化报告
同步兼容前端 AssemblyReportDialog.vue 所需的所有字段
"""

import csv
import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger("api_server")


class AssemblyReportParser:
    """
    从流水线各步骤产物中聚合生信指标的解析器。
    数据源优先级: 物理文件 > 数据库 JSON
    """

    def __init__(self, task_dir: Path):
        self.task_dir = task_dir

    # ═══════════════════════════════════════════════════
    # 顶层入口
    # ═══════════════════════════════════════════════════

    def generate_report(self) -> dict:
        """生成完整的结构化报告"""
        report = {
            "qc": self._parse_qc(),
            "host_cleaning": self._parse_host_removal(),
            "assembly": self._parse_assembly(),
            "checkv": self._parse_checkv(),
            "annotation": self._parse_annotation(),
        }

        # 从数据库恢复深度审计结果 (Lifestyle, Safety, PhageScope)
        self._enrich_from_db(report)
        return report

    # ═══════════════════════════════════════════════════
    # 质控解析 (Fastp)
    # ═══════════════════════════════════════════════════

    def _parse_qc(self) -> dict:
        """解析 fastp 产物, 提取完整 QC 指标"""
        result = {"status": "empty", "before": {}, "after": {}, "filtering": {}}
        qc_dir = self.task_dir / "qualitycontrolstep"
        if not qc_dir.exists():
            return result

        fastp_json = qc_dir / "fastp_report.json"
        if not fastp_json.exists():
            # 兜底: glob 搜索
            fastp_json = next(qc_dir.glob("fastp*.json"), None)
        if not fastp_json:
            return result

        try:
            with open(fastp_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            summary = data.get("summary", {})

            # 为前端 Vue 组件注入短名别名
            # fastp 原始 key: passed_filter_reads → Vue 期望: passed
            raw_filter = data.get("filtering_result", {})
            filtering = {
                **raw_filter,
                "passed": raw_filter.get("passed_filter_reads", 0),
                "low_quality": raw_filter.get("low_quality_reads", 0),
                "too_many_N": raw_filter.get("too_many_N_reads", 0),
                "too_short": raw_filter.get("too_short_reads", 0),
                "too_long": raw_filter.get("too_long_reads", 0),
            }

            return {
                "status": "ok",
                "before": summary.get("before_filtering", {}),
                "after": summary.get("after_filtering", {}),
                "filtering": filtering,
                "duplication": data.get("duplication", {}),
                "insert_size": data.get("insert_size", {}),
                "adapter_cutting": data.get("adapter_cutting", {}),
                # 绘图数据 — 双端
                "read1_before": data.get("read1_before_filtering", {}),
                "read1_after": data.get("read1_after_filtering", {}),
                "read2_before": data.get("read2_before_filtering", {}),
                "read2_after": data.get("read2_after_filtering", {}),
                # 元数据
                "sequencing": summary.get("sequencing", ""),
                "fastp_version": summary.get("fastp_version", ""),
                "command": data.get("command", ""),
            }
        except Exception as e:
            logger.warning(f"[Report] QC parse failed: {e}")
            return result

    # ═══════════════════════════════════════════════════
    # 宿主剔除
    # ═══════════════════════════════════════════════════

    def _parse_host_removal(self) -> dict:
        host_dir = self.task_dir / "hostcleanerstep"
        if not host_dir.exists():
            return {"status": "empty"}
        bam = host_dir / "mapped_to_host.bam"
        return {
            "status": "ok",
            "bam_size_mb": round(bam.stat().st_size / 1048576, 1) if bam.exists() else 0
        }

    # ═══════════════════════════════════════════════════
    # 组装解析 — 使用精修后的 FASTA
    # ═══════════════════════════════════════════════════

    def _parse_assembly(self) -> dict:
        result = {
            "status": "empty", "contigs": [], "num_contigs": 0,
            "total_length": 0, "gc_content": 0.0,
        }

        # 优先解析精修后的 FASTA, 回退到原始组装
        fasta = self.task_dir / "consensuscorrectionstep" / "polished_assembly.fasta"
        if not fasta.exists():
            fasta = self.task_dir / "assemblerstep" / "unicycler_run" / "assembly.fasta"
        if not fasta.exists():
            return result

        contigs = []
        gc_total, at_total = 0, 0
        depth_values = []

        try:
            with open(fasta, "r", encoding="utf-8") as f:
                cid, seq_parts = None, []
                header_meta = {}

                for line in f:
                    line = line.rstrip("\n\r")
                    if line.startswith(">"):
                        # 保存前一条 contig
                        if cid is not None:
                            seq = "".join(seq_parts)
                            clen = len(seq)
                            gc = seq.upper().count("G") + seq.upper().count("C")
                            at = seq.upper().count("A") + seq.upper().count("T")
                            gc_total += gc
                            at_total += at
                            contigs.append({
                                "id": cid, "length": clen,
                                "circular": header_meta.get("circular", False),
                                "depth": header_meta.get("depth", 0.0),
                            })

                        # 解析新 header
                        parts = line[1:].split()
                        cid = parts[0]
                        seq_parts = []
                        header_meta = {}
                        for p in parts[1:]:
                            if "=" in p:
                                k, v = p.split("=", 1)
                                if k == "circular":
                                    header_meta["circular"] = (v.lower() == "true")
                                elif k == "depth":
                                    header_meta["depth"] = float(v.rstrip("x"))
                                elif k == "length":
                                    pass  # 我们自己计算
                    else:
                        seq_parts.append(line.strip())

                # 最后一条 contig
                if cid is not None:
                    seq = "".join(seq_parts)
                    clen = len(seq)
                    gc = seq.upper().count("G") + seq.upper().count("C")
                    at = seq.upper().count("A") + seq.upper().count("T")
                    gc_total += gc
                    at_total += at
                    contigs.append({
                        "id": cid, "length": clen,
                        "circular": header_meta.get("circular", False),
                        "depth": header_meta.get("depth", 0.0),
                    })

            if not contigs:
                return result

            lengths = sorted([c["length"] for c in contigs], reverse=True)
            total_len = sum(lengths)

            # N50 / L50
            n50, l50, running = 0, 0, 0
            for i, length in enumerate(lengths):
                running += length
                if running >= total_len / 2:
                    n50 = length
                    l50 = i + 1
                    break

            # 加权平均深度 (按 contig 长度加权)
            weighted_depth = sum(c["depth"] * c["length"] for c in contigs)
            avg_depth = round(weighted_depth / total_len, 2) if total_len > 0 else 0

            # GC 含量
            gc_at_sum = gc_total + at_total
            gc_pct = round(gc_total / gc_at_sum * 100, 2) if gc_at_sum > 0 else 0

            # 环形判定 (任一 contig 为环形即标记)
            is_circular = any(c["circular"] for c in contigs)

            return {
                "status": "ok",
                "num_contigs": len(contigs),
                "total_length": total_len,
                "n50": n50,
                "l50": l50,
                "longest": lengths[0],
                "shortest": lengths[-1],
                "gc_content": gc_pct,
                "is_circular": is_circular,
                "avg_depth": avg_depth,
                "contigs": contigs[:200],
            }
        except Exception as e:
            logger.warning(f"[Report] Assembly parse failed: {e}")
            return result

    # ═══════════════════════════════════════════════════
    # CheckV 质量评估
    # ═══════════════════════════════════════════════════

    def _parse_checkv(self) -> Optional[dict]:
        summary = self.task_dir / "phageannotationstep" / "checkv_res" / "quality_summary.tsv"
        if not summary.exists():
            return None
        try:
            with open(summary, "r", encoding="utf-8") as f:
                row = next(csv.DictReader(f, delimiter="\t"))
                return {
                    "quality": row.get("checkv_quality", "Unknown"),
                    "miuvig_quality": row.get("miuvig_quality", ""),
                    "completeness": row.get("completeness", "N/A"),
                    "completeness_method": row.get("completeness_method", ""),
                    "contamination": row.get("contamination", "0"),
                    "gene_count": int(row.get("gene_count", 0)),
                    "viral_genes": int(row.get("viral_genes", 0)),
                    "host_genes": int(row.get("host_genes", 0)),
                    "provirus": row.get("provirus", "No"),
                    "kmer_freq": row.get("kmer_freq", ""),
                    "contig_length": int(row.get("contig_length", 0)),
                    "warnings": row.get("warnings", ""),
                }
        except Exception as e:
            logger.warning(f"[Report] CheckV parse failed: {e}")
            return None

    # ═══════════════════════════════════════════════════
    # 注释解析 — 整合 TSV
    # ═══════════════════════════════════════════════════

    def _parse_annotation(self) -> dict:
        anno_dir = self.task_dir / "phageannotationstep"
        result = {
            "status": "ok",
            "pharokka": {"genome": {}, "functions": []},
            "phold": {
                "predictions": [],
                "confidence": {"high": 0, "medium": 0, "low": 0, "none": 0},
                "total_cds": 0,
            },
            "phagescope_backfill": None,
            "visual_map": None,
            "type_counts": {},
        }

        # 1. 整合注释详表
        final_tsv = anno_dir / "Integrated_Final_Annotations.tsv"
        if not final_tsv.exists():
            final_tsv = next(anno_dir.glob("Integrated_Final_Annotations.tsv"), None)

        if final_tsv and final_tsv.exists():
            try:
                with open(final_tsv, "r", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f, delimiter="\t"))

                predictions = []
                func_counts = {}
                type_counts = {}  # CDS / tRNA / pseudogene
                backfill_count = 0

                for r in rows:
                    feat_type = r.get("Type", "CDS")
                    type_counts[feat_type] = type_counts.get(feat_type, 0) + 1

                    func = r.get("Function", "").strip() or "unknown function"
                    func_counts[func] = func_counts.get(func, 0) + 1

                    notes = r.get("Notes", "")
                    # 从实际 Notes 推导置信度:
                    #   有 PhageScope 回填 → medium (结构预测辅助)
                    #   有明确功能且非 unknown → high
                    #   unknown 且无 notes → none
                    if "PhageScope" in notes:
                        conf = "medium"
                        backfill_count += 1
                    elif func != "unknown function" and func:
                        conf = "high"
                    else:
                        conf = "none"

                    predictions.append({
                        "cds_id": r.get("ID", ""),
                        "start": r.get("Start", ""),
                        "end": r.get("End", ""),
                        "strand": r.get("Strand", ""),
                        "type": feat_type,
                        "function": func,
                        "product": r.get("Product", ""),
                        "notes": notes,
                        "confidence": conf,
                    })

                # 置信度统计
                conf_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
                for p in predictions:
                    conf_counts[p["confidence"]] = conf_counts.get(p["confidence"], 0) + 1

                cds_count = type_counts.get("CDS", 0)

                result["phold"]["predictions"] = predictions
                result["phold"]["confidence"] = conf_counts
                result["phold"]["total_cds"] = cds_count
                result["type_counts"] = type_counts

                # 前端图表数据
                result["pharokka"]["functions"] = [
                    {"name": k, "count": v} for k, v in func_counts.items()
                ]
                # 前端需要一个 "CDS" 总计条目
                if "CDS" not in func_counts:
                    result["pharokka"]["functions"].append({"name": "CDS", "count": cds_count})

            except Exception as e:
                logger.warning(f"[Report] Annotation parse failed: {e}")

        # 2. PhageScope 回填摘要
        bf_json = next(anno_dir.rglob("phagescope_backfill_summary.json"), None)
        if bf_json:
            try:
                with open(bf_json, "r", encoding="utf-8") as f:
                    result["phagescope_backfill"] = json.load(f)
            except Exception:
                pass

        # 3. 基因组图谱
        plot_dir = anno_dir / "phage_plot"
        if plot_dir.exists():
            pngs = sorted(
                list(plot_dir.glob("*.png")),
                key=lambda x: x.stat().st_size, reverse=True,
            )
            if pngs:
                result["visual_map"] = f"phageannotationstep/phage_plot/{pngs[0].name}"

        return result

    # ═══════════════════════════════════════════════════
    # 数据库元数据注入
    # ═══════════════════════════════════════════════════

    def _enrich_from_db(self, report: dict):
        """从 SQLite 恢复流水线保存的深度审计结果"""
        try:
            from .assembly_db import assembly_db
            task_data = assembly_db.get_task(self.task_dir.name)
            if not task_data or not task_data.get("results"):
                return

            results_raw = task_data["results"]
            data_obj = json.loads(results_raw) if isinstance(results_raw, str) else results_raw
            # 处理双层嵌套
            results = data_obj.get("results", data_obj) if isinstance(data_obj, dict) else data_obj

            if not isinstance(results, dict):
                return

            report["telemetry"] = results.get("telemetry")
            report["phagescope_audit"] = results.get("phagescope_audit", {})

            # 注入基因组元信息到前端期望位置
            gm = results.get("genomic_metrics", {})
            if report.get("annotation"):
                genome_info = report["annotation"].setdefault("pharokka", {}).setdefault("genome", {})

                gc_str = gm.get("gc_content", "") or ""
                density_str = gm.get("coding_density", "") or ""

                genome_info.update({
                    "length": gm.get("total_length"),
                    "gc_perc": gc_str.replace("%", "") if isinstance(gc_str, str) else gc_str,
                    "cds_coding_density": density_str.replace("%", "") if isinstance(density_str, str) else density_str,
                    "topology": gm.get("topology"),
                })

                # 回填摘要
                if not report["annotation"].get("phagescope_backfill"):
                    report["annotation"]["phagescope_backfill"] = results.get("phagescope_backfill")

        except Exception as e:
            logger.warning(f"[Report] DB enrichment failed: {e}")
