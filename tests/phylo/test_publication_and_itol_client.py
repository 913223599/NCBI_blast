# -*- coding: utf-8 -*-
"""
方案 B（免费 iTOL 上传打包 + batch_downloader.cgi 自动拉图）与方案 C（离线本地出版级多环/矩形渲染）回归测试。
"""
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.routes.phylo import router
from src.phylo.delivery.itol_client import ItolBatchClient
from src.phylo.delivery.itol_generator import ItolTemplateGenerator
from src.phylo.delivery.label_formatter import (
    clean_phage_description,
    enrich_node_metadata,
    format_leaf_label,
)
from src.phylo.delivery.publication_renderer import PublicationTreeRenderer
from src.phylo.models.errors import InvalidInputError, PhyloError
from src.phylo.models.schemas import (
    ItolPullRequest,
    PhyloJobConfig,
    PhyloJobRecord,
    PublicationFigureRequest,
    ReferenceCandidate,
)
from src.phylo.storage.archive_store import PhyloArchiveStore

_SAMPLE_NEWICK = (
    "(((T5-E1_asm:0.01,(T5-E2_asm:0.005,AY587007:0.02)'99.7/100':0.03)'94.6/96':0.08,"
    "(T5-WT_asm:0.002,MK373780:0.004)'100/100':0.15)'88/95':0.22,"
    "('附件2霍氏肠杆菌噬菌体2基因组序列':0.45,NC_055913:0.30)'85/92':0.18);"
)

_SAMPLE_META = {
    "T5-E1_asm": {"role": "query", "genus": "", "genome_length": 104500, "gc_content": 39.2},
    "T5-E2_asm": {"role": "query", "genus": "", "genome_length": 108100, "gc_content": 39.1},
    "AY587007": {
        "role": "ictv_rep",
        "description": "Escherichia phage T5, complete genome",
        "genus": "Tequintavirus",
        "genome_length": 121750,
        "gc_content": 39.3,
    },
    "T5-WT_asm": {"role": "query", "genus": "", "genome_length": 137600, "gc_content": 40.5},
    "MK373780": {
        "role": "ictv_rep",
        "description": "Escherichia phage vB_EcoM_HdK5",
        "genus": "Vequintavirus",
        "genome_length": 139000,
        "gc_content": 40.4,
    },
    "附件2霍氏肠杆菌噬菌体2基因组序列": {
        "role": "query",
        "genus": "",
        "genome_length": 72600,
        "gc_content": 43.8,
    },
    "NC_055913": {
        "role": "outgroup",
        "description": "Vibrio phage Gary",
        "genus": "Thalassavirus",
        "genome_length": 128300,
        "gc_content": 41.2,
    },
}


def test_label_formatter_and_history_enrichment() -> None:
    """校验论文发表标准叶标签格式化及历史任务 INPHARED description 自动补全。"""
    assert clean_phage_description("Escherichia phage T5, complete genome.") == "Escherichia phage T5"
    meta = {"role": "ictv_rep", "description": "Escherichia phage T5, complete genome"}
    assert format_leaf_label("AY587007", meta, "name_acc") == "Escherichia phage T5 (AY587007)"
    assert format_leaf_label("AY587007", meta, "name") == "Escherichia phage T5"
    assert format_leaf_label("AY587007", meta, "accession") == "AY587007"
    assert format_leaf_label("T5-E1_asm", {"role": "query", "description": "ignored"}, "name_acc") == "T5-E1_asm"

    # 若本地存在 INPHARED 数据库，验证历史缺 description 的老任务可自动回填
    old_meta = {"AY587007": {"role": "ictv_rep", "genus": "Tequintavirus"}}
    enriched = enrich_node_metadata(old_meta)
    from src.phylo.engines.ani.inphared_index import get_inphared_index

    if get_inphared_index().is_available():
        assert enriched["AY587007"].get("description") == "Escherichia phage T5"


def test_publication_renderer_circular_and_rectangular(tmp_path: Path) -> None:
    """校验离线出版级环形与矩形矢量渲染输出的 PDF/SVG/PNG 魔数与中文标签保留。"""
    for layout_mode in ("circular", "rectangular"):
        out_dir = tmp_path / f"figs_{layout_mode}"
        paths = PublicationTreeRenderer.render(
            newick=_SAMPLE_NEWICK,
            node_metadata=_SAMPLE_META,
            out_dir=out_dir,
            request=PublicationFigureRequest(
                layout=layout_mode,  # type: ignore[arg-type]
                formats=["pdf", "svg", "png"],
                dpi=150,
                support_style="both",
                title=f"Phage Delivery ({layout_mode})",
            ),
            file_prefix="pub_test",
            subtitle="Model: LG+I+R2 (BIC=15448.14)",
        )
        assert len(paths) == 3
        by_ext = {p.suffix.lower(): p for p in paths}
        assert by_ext[".pdf"].read_bytes().startswith(b"%PDF")
        assert by_ext[".png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        svg_text = by_ext[".svg"].read_text(encoding="utf-8")
        assert "<svg" in svg_text.lower()
        assert "附件2霍氏肠杆菌噬菌体2基因组序列" in svg_text
        assert "Escherichia phage T5 (AY587007)" in svg_text
        assert "Tequintavirus" in svg_text


def test_itol_client_tree_id_bundle_and_mock_pull(tmp_path: Path) -> None:
    """校验 iTOL Tree ID 提取、上传包生成及 batch_downloader.cgi 响应校验与错误处理。"""
    assert ItolBatchClient.extract_tree_id("123456789012345") == "123456789012345"
    assert (
        ItolBatchClient.extract_tree_id("https://itol.embl.de/tree/9876543210ABC?foo=bar#sec")
        == "9876543210ABC"
    )
    with pytest.raises(InvalidInputError):
        ItolBatchClient.extract_tree_id("   ")
    with pytest.raises(InvalidInputError):
        ItolBatchClient.extract_tree_id("https://itol.embl.de/tree/bad$id")

    ascii_nwk, mapping = ItolBatchClient.sanitize_newick_for_itol(_SAMPLE_NEWICK)
    assert ascii_nwk.isascii()
    assert "/" not in ascii_nwk
    assert mapping.get("附件2霍氏肠杆菌噬菌体2基因组序列") == "Phage_01"

    itol_dir = tmp_path / "itol"
    cands = [
        ReferenceCandidate(accession="T5-E1_asm", role="query", selected=True, genome_length=104500),
        ReferenceCandidate(
            accession="附件2霍氏肠杆菌噬菌体2基因组序列",
            role="query",
            selected=True,
            genome_length=72600,
        ),
        ReferenceCandidate(
            accession="AY587007",
            role="ictv_rep",
            genus="Tequintavirus",
            selected=True,
            genome_length=121750,
        ),
    ]
    ItolTemplateGenerator.generate(cands, itol_dir)
    bundle = ItolBatchClient.build_itol_upload_bundle(
        tmp_path,
        "job_test",
        _SAMPLE_NEWICK,
        itol_dir,
        node_metadata=_SAMPLE_META,
        label_format="name_acc",
    )
    assert bundle.is_file()
    with zipfile.ZipFile(bundle, "r") as zf:
        names = set(zf.namelist())
        nwk_inside = zf.read("tree_itol_ascii.nwk").decode("ascii")
        branch_inside = zf.read("itol/itol_branch_colors.txt").decode("utf-8")
        labels_inside = zf.read("itol/itol_labels_display.txt").decode("utf-8")
    assert "tree_itol_ascii.nwk" in names
    assert "README_iTOL_Upload.txt" in names
    assert "itol/itol_branch_colors.txt" in names
    assert "itol/itol_labels_display.txt" in names
    assert nwk_inside.isascii()
    assert "Phage_01" in branch_inside
    assert "Phage_01\t附件2霍氏肠杆菌噬菌体2基因组序列" in labels_inside
    assert "AY587007\tEscherichia phage T5 (AY587007)" in labels_inside

    # Mock batch_downloader.cgi 正常返回与错误拦截
    fake_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    mock_ok = MagicMock(status_code=200, content=fake_pdf, text="")
    with patch("src.phylo.delivery.itol_client.requests.post", return_value=mock_ok) as m_post:
        tid, out_file = ItolBatchClient.export_from_itol(
            "https://itol.embl.de/tree/1234567890",
            tmp_path / "dl",
            ItolPullRequest(tree_id_or_url="1234567890", format="pdf", display_mode="circular"),
        )
        assert tid == "1234567890"
        assert out_file.is_file()
        assert out_file.read_bytes().startswith(b"%PDF")
        assert m_post.call_args.kwargs["data"]["display_mode"] == "2"

    mock_err = MagicMock(status_code=200, content=b"ERR: Invalid tree ID 0000", text="ERR: Invalid tree ID 0000")
    with patch("src.phylo.delivery.itol_client.requests.post", return_value=mock_err):
        with pytest.raises(PhyloError):
            ItolBatchClient.export_from_itol(
                "000000",
                tmp_path / "dl",
                ItolPullRequest(tree_id_or_url="000000", format="pdf", display_mode="rectangular"),
            )


def test_publication_and_itol_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 FastAPI /render-publication、/export/figure、/export/itol_bundle 与 /itol/pull 路由。"""
    store = PhyloArchiveStore(base_dir=tmp_path)
    job_id = "phylo_pub_test_001"
    job_dir = store.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    itol_dir = job_dir / "itol"
    ItolTemplateGenerator.generate(
        [ReferenceCandidate(accession="T5-E1_asm", role="query", selected=True)],
        itol_dir,
    )
    rec = PhyloJobRecord(
        job_id=job_id,
        title="Test Phage Publication Tree",
        status="completed",
        resolved_track="phage_taxonomy",
        config=PhyloJobConfig(track="phage_taxonomy"),
        created_at=time.time(),
        newick=_SAMPLE_NEWICK,
        job_dir=str(job_dir),
        artifacts={"itol_dir": str(itol_dir)},
        node_metadata=_SAMPLE_META,
    )
    store.save_job(rec)
    monkeypatch.setattr("src.backend.routes.phylo.get_phylo_store", lambda: store)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. 离线出版级渲染接口
    r_pub = client.post(
        f"/api/phylo/jobs/{job_id}/render-publication",
        json={"layout": "circular", "formats": ["svg", "png"], "dpi": 150, "support_style": "dots"},
    )
    assert r_pub.status_code == 200
    pub_data = r_pub.json()
    assert len(pub_data["figures"]) == 2

    # 2. 图件文件下载与内联预览接口
    svg_fig = next(f for f in pub_data["figures"] if f["format"] == "svg")
    png_fig = next(f for f in pub_data["figures"] if f["format"] == "png")
    svg_name = svg_fig["filename"]
    png_name = png_fig["filename"]

    r_dl = client.get(f"/api/phylo/jobs/{job_id}/export/figure/{svg_name}")
    assert r_dl.status_code == 200
    assert r_dl.headers.get("content-disposition", "").startswith("attachment;")
    assert "no-store" in r_dl.headers.get("cache-control", "").lower()
    assert b"<svg" in r_dl.content.lower()

    r_inline = client.get(f"/api/phylo/jobs/{job_id}/export/figure/{svg_name}?inline=1")
    assert r_inline.status_code == 200
    assert r_inline.headers.get("content-disposition", "").startswith("inline;")
    assert "no-store" in r_inline.headers.get("cache-control", "").lower()
    assert b"<svg" in r_inline.content.lower()

    r_png_inline = client.get(f"/api/phylo/jobs/{job_id}/export/figure/{png_name}?inline=1")
    assert r_png_inline.status_code == 200
    assert r_png_inline.headers.get("content-type", "").startswith("image/png")
    assert r_png_inline.headers.get("content-disposition", "").startswith("inline;")
    assert "no-store" in r_png_inline.headers.get("cache-control", "").lower()

    # 3. iTOL 纯 ASCII Newick 接口 & 上传包下载接口
    r_nwk = client.get(f"/api/phylo/jobs/{job_id}/export/itol_newick")
    assert r_nwk.status_code == 200
    assert r_nwk.text.isascii()
    assert "/" not in r_nwk.text

    r_bnd = client.get(f"/api/phylo/jobs/{job_id}/export/itol_bundle")
    assert r_bnd.status_code == 200
    assert r_bnd.content.startswith(b"PK")

    # 4. iTOL 自动拉取接口
    mock_svg = MagicMock(status_code=200, content=b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", text="")
    with patch("src.phylo.delivery.itol_client.requests.post", return_value=mock_svg):
        r_pull = client.post(
            f"/api/phylo/jobs/{job_id}/itol/pull",
            json={
                "tree_id_or_url": "https://itol.embl.de/tree/4455667788",
                "format": "svg",
                "display_mode": "circular",
            },
        )
    assert r_pull.status_code == 200
    assert r_pull.json()["tree_id"] == "4455667788"
    pulled_name = r_pull.json()["filename"]
    r_pull_dl = client.get(f"/api/phylo/jobs/{job_id}/export/figure/{pulled_name}")
    assert r_pull_dl.status_code == 200
    assert b"<svg" in r_pull_dl.content


def test_reroot_preserves_metadata_descriptions_and_model_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """校验后端 /reroot 后保留 model/BIC 指标且回填/保持 node_metadata.description 不丢失。"""
    from src.phylo.models.schemas import TreeMetrics
    from src.phylo.pipeline.executor import PhyloJobExecutor

    store = PhyloArchiveStore(base_dir=tmp_path)
    executor = PhyloJobExecutor(store=store)
    monkeypatch.setattr("src.backend.routes.phylo.get_phylo_executor", lambda: executor)
    monkeypatch.setattr("src.backend.routes.phylo.get_phylo_store", lambda: store)

    job_id = "phylo_reroot_meta_001"
    job_dir = store.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    rec = PhyloJobRecord(
        job_id=job_id,
        title="Reroot Meta Test",
        status="completed",
        resolved_track="phage_taxonomy",
        config=PhyloJobConfig(track="phage_taxonomy"),
        created_at=time.time(),
        newick=_SAMPLE_NEWICK,
        metrics=TreeMetrics(
            leaf_count=7,
            internal_count=5,
            best_model="LG+I+R2",
            best_model_bic=15448.14,
            has_dual_support=True,
        ),
        job_dir=str(job_dir),
        node_metadata={
            "T5-E1_asm": {"role": "query", "genome_length": 104500},
            "AY587007": {"role": "ictv_rep", "genus": "Tequintavirus", "genome_length": 121750},
            "NC_055913": {"role": "outgroup", "genus": "Thalassavirus", "genome_length": 128300},
        },
    )
    store.save_job(rec)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r_mid = client.post(f"/api/phylo/jobs/{job_id}/reroot", json={"mode": "midpoint"})
    assert r_mid.status_code == 200
    body_mid = r_mid.json()
    assert body_mid["metrics"]["best_model"] == "LG+I+R2"
    assert body_mid["metrics"]["best_model_bic"] == 15448.14

    from src.phylo.engines.ani.inphared_index import get_inphared_index

    if get_inphared_index().is_available():
        assert body_mid["node_metadata"]["AY587007"]["description"] == "Escherichia phage T5"

    r_og = client.post(
        f"/api/phylo/jobs/{job_id}/reroot",
        json={"mode": "outgroup", "node_name": "NC_055913"},
    )
    assert r_og.status_code == 200
    body_og = r_og.json()
    assert body_og["metrics"]["best_model"] == "LG+I+R2"
    if get_inphared_index().is_available():
        assert body_og["node_metadata"]["AY587007"]["description"] == "Escherichia phage T5"
