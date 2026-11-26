# -*- coding: utf-8 -*-
"""
噬菌体基因组诊断报告 HTML 导出引擎 (ReportExporter) 行为回归测试。
锁定正常导出、空值/零除兜底、HTML 实体防 XSS 转义、CDS 截断与防御系统/宿主表格渲染契约。
"""
from __future__ import annotations

import base64
from pathlib import Path

from src.backend.utils.assembly_report_export import ReportExporter


def _build_sample_report_data(cds_count: int = 3) -> dict:
    predictions = [
        {
            "cds_id": f"CDS_{i:03d}",
            "type": "CDS",
            "start": i * 300 + 1,
            "end": (i + 1) * 300,
            "strand": "+",
            "function": "head and packaging" if i % 2 == 0 else "tail",
            "product": "integrase <script>alert(1)</script>" if i == 0 else f"tail protein {i}",
        }
        for i in range(cds_count)
    ]
    return {
        "qc": {
            "before": {
                "total_reads": 2_500_000,
                "total_bases": 375_000_000,
                "q20_rate": 0.985,
                "q30_rate": 0.952,
                "gc_content": 0.483,
                "read1_mean_length": 150,
                "read2_mean_length": 150,
            },
            "after": {
                "total_reads": 2_400_000,
                "total_bases": 358_000_000,
                "q20_rate": 0.991,
                "q30_rate": 0.964,
                "gc_content": 0.481,
                "read1_mean_length": 149,
                "read2_mean_length": 149,
            },
            "filtering": {
                "passed_filter_reads": 2_400_000,
                "low_quality_reads": 50_000,
                "too_many_N_reads": 1_000,
                "too_short_reads": 49_000,
                "too_long_reads": 0,
                "corrected_reads": 12_345,
            },
            "duplication": {"rate": 0.042},
            "insert_size": {"peak": 350, "histogram": [0, 0, 10, 50, 120]},
            "adapter_cutting": {"adapter_trimmed_reads": 8_000},
            "read1_after": {
                "quality_curves": {"mean": [36.5, 37.2, 37.0]},
                "content_curves": {"A": [0.25], "T": [0.25], "C": [0.25], "G": [0.25]},
            },
            "read2_after": {"quality_curves": {"mean": [35.1, 36.0, 35.8]}},
        },
        "host_cleaning": {"host_contamination_percent": 1.25},
        "assembly": {
            "total_length": 48_502,
            "gc_content": 49.8,
            "n50": 48_502,
            "avg_depth": 320.5,
            "num_contigs": 1,
            "l50": 1,
            "longest": 48_502,
            "shortest": 48_502,
            "is_circular": True,
        },
        "checkv": {
            "quality": "Complete",
            "completeness": "100.0",
            "contamination": "0.0",
            "gene_count": 72,
            "miuvig_quality": "High-quality",
            "completeness_method": "DTR",
            "viral_genes": 70,
            "host_genes": 0,
            "provirus": "No",
            "kmer_freq": "1.0",
        },
        "annotation": {
            "type_counts": {"CDS": cds_count, "tRNA": 2, "pseudogene": 0},
            "phold": {"predictions": predictions},
            "pharokka": {
                "functions": [
                    {"name": "CDS", "count": cds_count},
                    {"name": "head and packaging", "count": 2},
                    {"name": "tail", "count": 1},
                ]
            },
        },
        "phagescope_audit": {
            "safety_status": "Secure",
            "lifestyle": "Virulent",
            "amr_genes": [],
            "virulent_factors": ["vf_1"],
            "virulent_factors_direct": ["vf_1"],
            "defense_systems": {
                "LOCUS_01": {"system": "AcrIIA4", "evalue": 1.5e-25},
            },
            "host_origin": "Escherichia coli",
            "taxonomy_info": {
                "top_hit_name": "Escherichia phage T4",
                "Classification": "Caudoviricetes",
                "Genus": "Tequatrovirus",
                "Family": "Straboviridae",
                "Host": "Escherichia",
            },
            "host_prediction_enhanced": {
                "top_hits": [
                    {
                        "description": "E. coli <K12>",
                        "accession": "NC_000913",
                        "distance": "0.02",
                        "confidence": "High",
                        "p_value": "1e-5",
                        "db_source": "RefSeq",
                    }
                ]
            },
        },
    }


def test_export_html_full_report_and_xss_escaping(tmp_path: Path) -> None:
    task_dir = tmp_path / "ASM_TEST_01"
    plot_dir = task_dir / "phageannotationstep" / "phage_plot"
    plot_dir.mkdir(parents=True)
    fake_png = b"\x89PNG\r\n\x1a\nFAKEPNG"
    (plot_dir / "genome_map.png").write_bytes(fake_png * 4)
    (plot_dir / "phage_phylogeny.png").write_bytes(fake_png)

    exporter = ReportExporter(task_dir)
    out_path = exporter.export_html(_build_sample_report_data(cds_count=55))

    assert out_path.is_file()
    assert out_path.name == "assembly_report_ASM_TEST_01.html"
    content = out_path.read_text(encoding="utf-8")

    # XSS 转义检查
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "E. coli &lt;K12&gt;" in content

    # 关键区块内容检查
    assert "Circular (环形基因组)" in content
    assert "2.50M" in content
    assert "375.00 Mbp" in content
    assert "1 个检出 (dbAPIS)" in content
    assert "AcrIIA4" in content
    assert "共 55 条 CDS, 仅展示前 50 条" in content
    assert base64.b64encode(fake_png * 4).decode("utf-8") in content
    assert base64.b64encode(fake_png).decode("utf-8") in content


def test_export_html_handles_empty_and_none_fields_safely(tmp_path: Path) -> None:
    task_dir = tmp_path / "ASM_EMPTY"
    task_dir.mkdir(parents=True)
    exporter = ReportExporter(task_dir)

    out_path = exporter.export_html(
        {
            "qc": None,
            "assembly": None,
            "checkv": None,
            "annotation": None,
            "phagescope_audit": None,
            "host_cleaning": None,
        }
    )

    assert out_path.is_file()
    content = out_path.read_text(encoding="utf-8")
    assert "Linear (线性基因组)" in content
    assert "未检出显著的抗噬菌体防御系统基因" in content
    assert "未发现显著高同源原噬菌体" in content
    assert "暂无可视化数据" in content
