# -*- coding: utf-8 -*-
"""
科研绘图工坊（Figure Studio）六大顶刊出图引擎与 FastAPI 路由回归测试。
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.figure_studio.models import (
    DiversityRenderRequest,
    GenomeFeatureItem,
    GenomeMapRenderRequest,
    HostMatrixRenderRequest,
    NetworkRenderRequest,
    ParsedGenomeInput,
    SyntenyRenderRequest,
    ViridicRenderRequest,
)
from src.figure_studio.renderers.diversity_renderer import DiversityWindowRenderer
from src.figure_studio.renderers.genome_map_renderer import GenomeMapRenderer
from src.figure_studio.renderers.host_matrix_renderer import HostMatrixRenderer
from src.figure_studio.renderers.network_renderer import GeneNetworkRenderer
from src.figure_studio.renderers.synteny_renderer import SyntenyRibbonRenderer
from src.figure_studio.renderers.viridic_renderer import ViridicHeatmapRenderer


def _make_sample_genomes() -> list[ParsedGenomeInput]:
    seqs = [
        "ATGAAATTTGGGCCCAAATTTGGGCCC" * 180,
        "ATGAAATTTGGGCCCAAATTTGGGCCC" * 180,
        "ATGAAACCCGGGTTTAAATTTGGGCCC" * 180,
    ]
    genomes: list[ParsedGenomeInput] = []
    products = [
        ("terminase large subunit", "head and packaging", "MKTLLVFGDDRAVLQQLAE"),
        ("portal protein", "head and packaging", "MAVRLKPQQWTGDAILLSR"),
        ("major capsid protein", "head and packaging", "MSKVGTLAAIVNQPLDERF"),
        ("tail completion protein", "connector", "MPRTSLQGDLVFAINQKS"),
        ("tail fiber protein", "tail", "MATSGDFNKLPTVYQWRGH"),
        ("holin", "lysis", "MLGIILVVVALLLSKKKQ"),
        ("endolysin", "lysis", "MRIFDGVTGHKLQPSWNAY"),
        ("anti-defence protein", "anti-defence", "MNKPQRLTVSSDDYFAAQ"),
    ]
    for g_idx, gname in enumerate(("Phage_Q1", "Phage_RefA", "Phage_RefB")):
        feats: list[GenomeFeatureItem] = []
        cursor = 120
        for f_idx, (prod, cat, aa_seq) in enumerate(products):
            if g_idx == 2 and f_idx == 4:
                aa_use = "MZZXXYYWWVVUUTTSSRRQQ"
                prod_use = "variant tail fiber protein"
            elif g_idx == 2 and f_idx == 7:
                continue
            else:
                aa_use = aa_seq
                prod_use = prod
            start = cursor
            end = cursor + 420
            cursor = end + 80
            feats.append(
                GenomeFeatureItem(
                    locus_tag=f"{gname}_CDS_{f_idx + 1:03d}",
                    start=start,
                    end=end,
                    strand="-" if f_idx % 4 == 3 else "+",
                    product=prod_use,
                    category=cat,
                    translation=aa_use,
                )
            )
        genomes.append(
            ParsedGenomeInput(
                name=gname,
                sequence=seqs[g_idx],
                length=max(len(seqs[g_idx]), cursor + 200),
                features=feats,
            )
        )
    return genomes


def _assert_valid_outputs(paths: list[Path], expected_exts: tuple[str, ...] = (".pdf", ".svg", ".png")) -> dict[str, Path]:
    by_ext = {p.suffix.lower(): p for p in paths}
    for ext in expected_exts:
        assert ext in by_ext, f"Missing output {ext}"
        assert by_ext[ext].is_file() and by_ext[ext].stat().st_size > 100
    if ".pdf" in by_ext:
        assert by_ext[".pdf"].read_bytes().startswith(b"%PDF")
    if ".png" in by_ext:
        assert by_ext[".png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    if ".svg" in by_ext:
        svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
        assert "<svg" in svg_txt.lower()
    return by_ext


def test_viridic_heatmap_renderer_modes(tmp_path: Path) -> None:
    labels = ["Query_T5", "AY692264", "NC_005859", "NC_055913"]
    wg = [
        [100.0, 97.5, 81.2, 12.4],
        [97.5, 100.0, 82.0, 11.8],
        [81.2, 82.0, 100.0, 13.1],
        [12.4, 11.8, 13.1, 100.0],
    ]
    af = [
        [100.0, 96.0, 78.0, 18.0],
        [95.0, 100.0, 79.0, 17.5],
        [77.0, 80.0, 100.0, 19.0],
        [16.0, 15.5, 18.0, 100.0],
    ]
    lengths = [121400, 121750, 118900, 128300]
    for mode in ("viridic_dual", "tree_triangle"):
        out_dir = tmp_path / f"vir_{mode}"
        paths = ViridicHeatmapRenderer.render(
            out_dir=out_dir,
            req=ViridicRenderRequest(
                mode=mode,  # type: ignore[arg-type]
                labels=labels,
                wgani_matrix=wg,
                af_matrix=af,
                genome_lengths=lengths,
                formats=["pdf", "svg", "png"],
                dpi=120,
            ),
        )
        by_ext = _assert_valid_outputs(paths)
        svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
        assert "Query_T5" in svg_txt


def test_genome_map_renderer_circular_and_linear(tmp_path: Path) -> None:
    genome = _make_sample_genomes()[0]
    for mode in ("circular", "linear_multitrack"):
        out_dir = tmp_path / f"gmap_{mode}"
        paths = GenomeMapRenderer.render(
            genome=genome,
            out_dir=out_dir,
            req=GenomeMapRenderRequest(
                mode=mode,  # type: ignore[arg-type]
                formats=["pdf", "svg", "png"],
                dpi=120,
                title="Escherichia phage Q1",
            ),
        )
        by_ext = _assert_valid_outputs(paths)
        svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
        assert "Phage_Q1" in svg_txt or "Escherichia phage Q1" in svg_txt


def test_synteny_ribbon_renderer_lovis4u_and_clinker(tmp_path: Path) -> None:
    genomes = _make_sample_genomes()
    for mode in ("lovis4u", "clinker"):
        out_dir = tmp_path / f"syn_{mode}"
        paths = SyntenyRibbonRenderer.render(
            genomes=genomes,
            out_dir=out_dir,
            req=SyntenyRenderRequest(
                mode=mode,  # type: ignore[arg-type]
                formats=["pdf", "svg", "png"],
                dpi=120,
                min_identity=40.0,
            ),
        )
        by_ext = _assert_valid_outputs(paths)
        svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
        assert "Phage_Q1" in svg_txt
        assert "Phage_RefB" in svg_txt


def test_diversity_window_renderer(tmp_path: Path) -> None:
    ref_genome = _make_sample_genomes()[0]
    # 构造 4 条高度相似但第 1600-2300bp 有变异峰的同种比对序列
    base = list("ATGCTAGCTAGCATCGATCGTAGCTAGCATCGATCGTAGCTA" * 120)
    seqs = []
    for s_idx in range(4):
        arr = list(base)
        for pos in range(1600, min(len(arr), 2400), 7 + s_idx):
            arr[pos] = "ACGT"[(pos + s_idx) % 4]
        seqs.append((f"Strain_{s_idx + 1}", "".join(arr)))

    paths = DiversityWindowRenderer.render(
        ref_genome=ref_genome,
        sequences=seqs,
        out_dir=tmp_path / "div",
        req=DiversityRenderRequest(
            window_size=200,
            step_size=50,
            formats=["pdf", "svg", "png"],
            dpi=120,
        ),
    )
    by_ext = _assert_valid_outputs(paths)
    svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
    assert "Nucleotide diversity" in svg_txt


def test_gene_network_renderer(tmp_path: Path) -> None:
    nodes = [
        {"id": "Query_01", "label": "Query_01", "group": "Demerecviridae", "is_query": True},
        {"id": "N_01", "label": "T5", "group": "Demerecviridae", "is_query": False},
        {"id": "N_02", "label": "T5_like", "group": "Demerecviridae", "is_query": False},
        {"id": "N_03", "label": "Siph_A", "group": "Demerecviridae", "is_query": False},
        {"id": "M_01", "label": "T4", "group": "Straboviridae", "is_query": False},
        {"id": "M_02", "label": "T4_like", "group": "Straboviridae", "is_query": False},
    ]
    edges = [
        {"source": "Query_01", "target": "N_01", "weight": 0.92},
        {"source": "Query_01", "target": "N_02", "weight": 0.85},
        {"source": "N_01", "target": "N_02", "weight": 0.90},
        {"source": "N_02", "target": "N_03", "weight": 0.65},
        {"source": "M_01", "target": "M_02", "weight": 0.78},
    ]
    paths = GeneNetworkRenderer.render(
        nodes=nodes,
        edges=edges,
        out_dir=tmp_path / "net",
        req=NetworkRenderRequest(formats=["pdf", "svg", "png"], dpi=120),
    )
    by_ext = _assert_valid_outputs(paths)
    svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
    assert "Query_01" in svg_txt


def test_host_matrix_renderer_modes(tmp_path: Path) -> None:
    rows = ["K1", "K2", "K25", "K37"]
    cols = ["Depo_1", "Depo_2", "Depo_3", "Depo_4", "Depo_5"]
    vals = [
        [92.0, 88.0, 0.0, 0.0, 0.0],
        [0.0, 75.0, 85.0, 0.0, 0.0],
        [0.0, 0.0, 12.0, 95.0, 0.0],
        [0.0, 0.0, 0.0, 10.0, 90.0],
    ]
    col_groups = ["podovirus", "siphovirus", "myovirus", "podovirus", "jumbo myovirus"]
    for mode in ("dual_tree_heatmap", "sparse_specificity"):
        paths = HostMatrixRenderer.render(
            out_dir=tmp_path / f"host_{mode}",
            req=HostMatrixRenderRequest(
                mode=mode,  # type: ignore[arg-type]
                row_labels=rows,
                col_labels=cols,
                values=vals,
                col_groups=col_groups,
                formats=["pdf", "svg", "png"],
                dpi=120,
            ),
        )
        by_ext = _assert_valid_outputs(paths)
        svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
        assert "Depo_1" in svg_txt


def test_figure_studio_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.backend.routes.figure_studio import router
    from src.figure_studio import data_bridge

    studio_root = tmp_path / "figure_studio"
    monkeypatch.setattr(data_bridge, "get_studio_root_dir", lambda: studio_root)
    monkeypatch.setattr(
        data_bridge,
        "list_available_sources",
        lambda: {
            "phylo_jobs": [{"job_id": "j_demo", "title": "Demo Phylo"}],
            "annotation_tasks": [{"task_id": "a_demo", "task_name": "Demo Anno"}],
            "sample_presets": [{"id": "tequintavirus", "label": "Tequintavirus Demo"}],
        },
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r_src = client.get("/api/figure-studio/sources")
    assert r_src.status_code == 200
    src_data = r_src.json()
    assert src_data["phylo_jobs"][0]["job_id"] == "j_demo"

    r_ren = client.post(
        "/api/figure-studio/render/viridic",
        json={
            "mode": "viridic_dual",
            "labels": ["Q1", "R1", "R2"],
            "wgani_matrix": [[100, 96, 74], [96, 100, 75], [74, 75, 100]],
            "af_matrix": [[100, 95, 70], [95, 100, 71], [70, 71, 100]],
            "genome_lengths": [121000, 121500, 118000],
            "formats": ["svg", "png"],
            "dpi": 120,
        },
    )
    assert r_ren.status_code == 200
    body = r_ren.json()
    render_id = body["render_id"]
    png_name = next(f["filename"] for f in body["figures"] if f["format"] == "png")

    r_dl = client.get(f"/api/figure-studio/files/{render_id}/{png_name}")
    assert r_dl.status_code == 200
    assert r_dl.headers.get("content-disposition", "").startswith("attachment;")
    assert "no-store" in r_dl.headers.get("cache-control", "").lower()
    assert r_dl.content.startswith(b"\x89PNG\r\n\x1a\n")

    r_inline = client.get(f"/api/figure-studio/files/{render_id}/{png_name}?inline=1")
    assert r_inline.status_code == 200
    assert r_inline.headers.get("content-disposition", "").startswith("inline;")
    assert "no-store" in r_inline.headers.get("cache-control", "").lower()

    r_hist = client.get("/api/figure-studio/history")
    assert r_hist.status_code == 200
    assert any(item["render_id"] == render_id for item in r_hist.json()["items"])
