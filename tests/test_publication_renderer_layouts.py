# -*- coding: utf-8 -*-
"""
Phase 6A 出版级进化树渲染器拆解回归测试
验证 circular / half_circular / rectangular / composite 四种布局均可正常渲染输出 SVG 文件。
"""
from pathlib import Path

import pytest

from src.phylo.delivery.publication_renderer import PublicationTreeRenderer
from src.phylo.models.schemas import PublicationFigureRequest

pytestmark = pytest.mark.offline

SAMPLE_NEWICK = (
    "(((Query_Phage_1:0.05,Ref_T4_A:0.08)95:0.04,(Ref_T4_B:0.06,Ref_T4_C:0.07)88:0.05)99:0.06,"
    "(Ref_Lambda_1:0.12,Ref_Lambda_2:0.14)92:0.09);"
)

SAMPLE_METADATA = {
    "Query_Phage_1": {
        "role": "query",
        "family": "Straboviridae",
        "genus": "Tequatrovirus",
        "host": "Escherichia coli",
        "gc_content": 35.4,
        "genome_length": 168903,
    },
    "Ref_T4_A": {
        "role": "reference",
        "family": "Straboviridae",
        "genus": "Tequatrovirus",
        "host": "Escherichia coli",
        "gc_content": 35.3,
        "genome_length": 168000,
    },
    "Ref_T4_B": {
        "role": "reference",
        "family": "Straboviridae",
        "genus": "Tequatrovirus",
        "host": "Shigella flexneri",
        "gc_content": 35.8,
        "genome_length": 165000,
    },
    "Ref_T4_C": {
        "role": "reference",
        "family": "Straboviridae",
        "genus": "Mosigvirus",
        "host": "Escherichia coli",
        "gc_content": 37.2,
        "genome_length": 169200,
    },
    "Ref_Lambda_1": {
        "role": "reference",
        "family": "Lambdaviridae",
        "genus": "Lambdavirus",
        "host": "Escherichia coli",
        "gc_content": 49.8,
        "genome_length": 48502,
    },
    "Ref_Lambda_2": {
        "role": "reference",
        "family": "Lambdaviridae",
        "genus": "Lambdavirus",
        "host": "Salmonella enterica",
        "gc_content": 50.1,
        "genome_length": 49100,
    },
}


@pytest.mark.parametrize("layout", ["circular", "half_circular", "rectangular", "composite"])
def test_publication_renderer_all_layouts_export_svg(tmp_path: Path, layout: str):
    req = PublicationFigureRequest(
        layout=layout,
        formats=["svg"],
        title=f"Smoke Test ({layout})",
        show_figure_title=True,
    )
    out_files = PublicationTreeRenderer.render(
        newick=SAMPLE_NEWICK,
        node_metadata=SAMPLE_METADATA,
        out_dir=tmp_path,
        request=req,
        file_prefix="pub_smoke",
        subtitle="Phase 6A Split Verification",
    )
    assert len(out_files) == 1
    svg_path = out_files[0]
    assert svg_path.is_file()
    content = svg_path.read_text(encoding="utf-8")
    assert "<svg" in content and len(content) > 1000
