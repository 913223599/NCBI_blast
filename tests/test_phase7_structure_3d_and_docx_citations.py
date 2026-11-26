# -*- coding: utf-8 -*-
"""Phase 7 单元测试：3D 蛋白结构坐标安全服务、FastAPI 路由与 Word 自动引文统一闭环。"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.analysis.phage_structure.structure_3d_service import (
    fetch_public_structure,
    list_task_structure_files,
    read_task_structure_file,
)
from src.utils.citations_loader import load_citations_payload
from src.utils.docx_citation_helper import (
    DEFAULT_ANNOTATION_REPORT_TOOL_IDS,
    append_citations_section,
    build_report_references_list,
)


SAMPLE_PDB = (
    "ATOM      1  N   ALA A   1       1.458   0.000   0.000  1.00 92.50           N\n"
    "ATOM      2  CA  ALA A   1       2.300   0.000   1.200  1.00 92.50           C\n"
    "END\n"
)


def test_structure_3d_list_and_read_with_traversal_guard(tmp_path: Path):
    """合法 .pdb/.cif 可枚举与读取；路径穿越与非法后缀必须拦截。"""
    sub = tmp_path / "phold_models"
    sub.mkdir(parents=True)
    pdb_file = sub / "ORF_001.pdb"
    pdb_file.write_text(SAMPLE_PDB, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    files = list_task_structure_files(tmp_path)
    assert len(files) == 1
    assert files[0]["rel_path"] == "phold_models/ORF_001.pdb"
    assert files[0]["format"] == "pdb"

    payload = read_task_structure_file(tmp_path, "phold_models/ORF_001.pdb")
    assert payload["filename"] == "ORF_001.pdb"
    assert "ATOM" in payload["content"]

    with pytest.raises(ValueError):
        read_task_structure_file(tmp_path, "../secret.pdb")
    with pytest.raises(ValueError):
        read_task_structure_file(tmp_path, "notes.txt")
    with pytest.raises(FileNotFoundError):
        read_task_structure_file(tmp_path, "phold_models/missing.pdb")


def test_public_structure_cache_hit_and_validation(tmp_path: Path):
    """公共结构接口应校验 ID 合法性并优先命中本地缓存。"""
    cached_file = tmp_path / "alphafold_P00533.pdb"
    cached_file.write_text(SAMPLE_PDB, encoding="utf-8")

    res = fetch_public_structure("alphafold", "p00533", cache_dir=tmp_path)
    assert res["cached"] is True
    assert res["accession"] == "P00533"
    assert res["format"] == "pdb"
    assert "ATOM" in res["content"]

    with pytest.raises(ValueError):
        fetch_public_structure("rcsb", "INVALID_ID_TOO_LONG", cache_dir=tmp_path)
    with pytest.raises(ValueError):
        fetch_public_structure("unknown_db", "1EMA", cache_dir=tmp_path)


def test_public_structure_route_validation():
    """FastAPI /api/analysis/phage_structure/public-structure 应拒绝非法参数。"""
    from src.backend.api_server import app

    client = TestClient(app)
    resp = client.get(
        "/api/analysis/phage_structure/public-structure",
        params={"source": "rcsb", "accession": "BAD_PDB_ID"},
    )
    assert resp.status_code == 400


def test_citations_single_source_and_docx_injection():
    """验证 citations.json 涵盖全部注释报告文献，并可真实写入 python-docx 文档。"""
    payload = load_citations_payload()
    assert payload["count"] >= 24

    refs = build_report_references_list(DEFAULT_ANNOTATION_REPORT_TOOL_IDS)
    assert len(refs) == len(DEFAULT_ANNOTATION_REPORT_TOOL_IDS)
    bookmarks = [bm for _, bm in refs]
    assert bookmarks == [
        "Ref_Pharokka",
        "Ref_Phanotate",
        "Ref_Phold",
        "Ref_PHROG",
        "Ref_PhageScope",
        "Ref_CARD",
        "Ref_VFDB",
        "Ref_Acranker",
    ]
    assert "10.1093/bioinformatics/btac776" in refs[0][0]
    assert "PMID: 36453861" in refs[0][0]

    docx = pytest.importorskip("docx")
    doc = docx.Document()
    written = append_citations_section(
        doc,
        tool_ids=DEFAULT_ANNOTATION_REPORT_TOOL_IDS,
        heading_text="Methods & References",
    )
    assert len(written) == 8

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    reopened = docx.Document(buf)
    texts = [p.text for p in reopened.paragraphs if p.text.strip()]
    assert "Methods & References" in texts
    assert any("Pharokka" in t and "10.1093/bioinformatics/btac776" in t for t in texts)
    assert any("Phold" in t and "10.1093/nar/gkaf1448" in t for t in texts)
