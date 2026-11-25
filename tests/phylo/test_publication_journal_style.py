# -*- coding: utf-8 -*-
"""
科研期刊出版级进化树渲染风格、单系支系检测、字体路由与 iTOL range 模板单元测试。
"""
import warnings
from pathlib import Path

from src.phylo.delivery.clade_detector import detect_monophyletic_clades
from src.phylo.delivery.itol_generator import ItolTemplateGenerator
from src.phylo.delivery.publication_palettes import (
    PALETTES,
    build_top_genus_palette,
    build_top_taxon_palette,
    choose_macro_taxon_rank,
    compute_nice_scale_bar,
    compute_ring_elbow_leaders,
    gc_value_to_hex,
    get_journal_palette,
    is_formal_taxon_name,
    pick_font_family,
    resolve_cjk_font,
    resolve_latin_font,
)
from src.phylo.delivery.publication_renderer import PublicationTreeRenderer
from src.phylo.delivery.subtree_extractor import extract_query_focus_subtree
from src.phylo.models.schemas import PublicationFigureRequest, ReferenceCandidate
from src.phylo.pipeline.postprocess import parse_newick

_SLOW_EVOLUTION_NEWICK = (
    "(((Q_Phage_1:0.0012,(AY587007:0.0015,EF204940:0.0018)'99/100':0.0022)'96/98':0.0031,"
    "(MK373780:0.0021,KX123456:0.0019)'86/91':0.0028)'78/85':0.0035,"
    "('测试中文噬菌体株01':0.0040,NC_055913:0.0052)'90/95':0.0030);"
)

_JOURNAL_META = {
    "Q_Phage_1": {
        "role": "query",
        "genus": "",
        "host": "Escherichia coli",
        "genome_length": 112400,
        "gc_content": 39.5,
    },
    "AY587007": {
        "role": "ictv_rep",
        "description": "Escherichia phage T5",
        "genus": "Tequintavirus",
        "host": "Escherichia",
        "genome_length": 121750,
        "gc_content": 39.3,
    },
    "EF204940": {
        "role": "neighbor",
        "description": "Escherichia phage EPS7",
        "genus": "Tequintavirus",
        "host": "Salmonella",
        "genome_length": 111382,
        "gc_content": 39.0,
    },
    "MK373780": {
        "role": "ictv_rep",
        "description": "Escherichia phage vB_EcoM_HdK5",
        "genus": "Vequintavirus",
        "host": "Escherichia",
        "genome_length": 139000,
        "gc_content": 40.4,
    },
    "KX123456": {
        "role": "neighbor",
        "description": "Pseudomonas phage P5",
        "genus": "Vequintavirus",
        "host": "Pseudomonas",
        "genome_length": 135400,
        "gc_content": 49.8,
    },
    "测试中文噬菌体株01": {
        "role": "query",
        "genus": "",
        "host": "Klebsiella pneumoniae",
        "genome_length": 88500,
        "gc_content": 44.2,
    },
    "NC_055913": {
        "role": "outgroup",
        "description": "Vibrio phage Gary",
        "genus": "Thalassavirus",
        "host": "Vibrio",
        "genome_length": 128300,
        "gc_content": 41.2,
    },
}


def test_nice_scale_bar_125_steps() -> None:
    """校验 1-2-5 科学步长在慢演化树、常规树与大距离树上的合理性。"""
    val_slow, txt_slow = compute_nice_scale_bar(0.012)
    assert 0 < val_slow <= 0.006
    assert txt_slow in ("0.002", "0.005", "0.001")

    val_mid, txt_mid = compute_nice_scale_bar(0.45)
    assert 0 < val_mid <= 0.225
    assert txt_mid == "0.1"

    val_large, txt_large = compute_nice_scale_bar(2.6)
    assert 0 < val_large <= 1.3
    assert txt_large == "0.5"


def test_formal_taxon_italic_and_font_routing() -> None:
    """校验拉丁分类学名斜体判断与中英文双字体路由。"""
    assert is_formal_taxon_name("Tequintavirus") is True
    assert is_formal_taxon_name("Tequintavirus (3)") is True
    assert is_formal_taxon_name("Pseudomonadota") is True
    assert is_formal_taxon_name("Unclassified") is False
    assert is_formal_taxon_name("Others (2)") is False
    assert is_formal_taxon_name("Query Phage") is False
    assert is_formal_taxon_name("Outgroup") is False

    latin_font = resolve_latin_font()
    cjk_font = resolve_cjk_font()
    assert latin_font in ("Arial", "Helvetica", "DejaVu Sans")
    assert pick_font_family("Escherichia phage T5 (AY587007)") == latin_font
    assert pick_font_family("测试中文噬菌体株01") == cjk_font


def test_detect_monophyletic_clades_disjoint_and_excludes_outgroup() -> None:
    """校验极大单系支系检测：允许含待定 query、排除 outgroup、区间互不重叠。"""
    root = parse_newick(_SLOW_EVOLUTION_NEWICK)

    def _collect(node):
        if node.is_leaf:
            return [node]
        res = []
        for ch in node.children:
            res.extend(_collect(ch))
        return res

    leaves = _collect(root)
    genus_colors = {
        "Tequintavirus": "#3C5488",
        "Vequintavirus": "#00A087",
        "Thalassavirus": "#8491B4",
    }
    clades = detect_monophyletic_clades(root, leaves, _JOURNAL_META, genus_colors)
    taxa = {c.taxon_name: c for c in clades}

    assert "Tequintavirus" in taxa
    assert "Vequintavirus" in taxa
    assert "Thalassavirus" not in taxa
    assert taxa["Tequintavirus"].contains_query is True
    assert taxa["Tequintavirus"].leaf_end_idx < taxa["Vequintavirus"].leaf_start_idx


def test_publication_renderer_journal_styles_zero_font_warning(tmp_path: Path) -> None:
    """校验四大期刊色板、单双栏宽度、Host 门级外环渲染且全程零缺字告警。"""
    for palette_name in ("nature", "lancet", "okabe_ito", "monochrome"):
        assert palette_name in PALETTES

    for layout_mode in ("circular", "rectangular"):
        for idx, palette_name in enumerate(("nature", "lancet", "okabe_ito", "monochrome")):
            width_preset = "single_col" if idx % 2 == 0 else "double_col"
            out_dir = tmp_path / f"{layout_mode}_{palette_name}"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                paths = PublicationTreeRenderer.render(
                    newick=_SLOW_EVOLUTION_NEWICK,
                    node_metadata=_JOURNAL_META,
                    out_dir=out_dir,
                    request=PublicationFigureRequest(
                        layout=layout_mode,  # type: ignore[arg-type]
                        formats=["pdf", "svg", "png"],
                        dpi=150,
                        support_style="dots",
                        palette=palette_name,  # type: ignore[arg-type]
                        journal_width=width_preset,  # type: ignore[arg-type]
                        show_clade_shading=True,
                        show_host_strip=True,
                        show_query_star=True,
                        title=f"Phage Phylogeny ({palette_name})",
                    ),
                    file_prefix="pub_journal",
                    subtitle="Model: LG+I+G4 (BIC=12410.5)",
                )
            missing_glyph_warnings = [
                str(w.message) for w in caught if "missing from font" in str(w.message)
            ]
            assert missing_glyph_warnings == []
            by_ext = {p.suffix.lower(): p for p in paths}
            assert by_ext[".pdf"].read_bytes().startswith(b"%PDF")
            assert by_ext[".png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            svg_text = by_ext[".svg"].read_text(encoding="utf-8")
            assert "Escherichia phage T5 (AY587007)" in svg_text
            assert "测试中文噬菌体株01" in svg_text
            assert "Host" in svg_text
            assert "substitutions/site" in svg_text


def test_itol_generator_includes_clade_ranges(tmp_path: Path) -> None:
    """校验 iTOL 模板生成器额外产出 itol_clade_ranges.txt 且符合 range 语法。"""
    cands = [
        ReferenceCandidate(accession="Q_Phage_1", role="query", selected=True),
        ReferenceCandidate(
            accession="AY587007",
            role="ictv_rep",
            genus="Tequintavirus",
            family="Demerecviridae",
            host="Escherichia",
            selected=True,
        ),
        ReferenceCandidate(
            accession="EF204940",
            role="neighbor",
            genus="Tequintavirus",
            family="Demerecviridae",
            host="Salmonella",
            selected=True,
        ),
    ]
    created = ItolTemplateGenerator.generate(cands, tmp_path)
    assert "itol_clade_ranges.txt" in created
    range_txt = (tmp_path / "itol_clade_ranges.txt").read_text(encoding="utf-8")
    assert range_txt.startswith("TREE_COLORS\nSEPARATOR TAB\nDATA\n")
    assert "AY587007\trange\t" in range_txt
    assert "Tequintavirus" in range_txt


def _build_large_synthetic_tree(n_ref: int = 108) -> tuple[str, dict]:
    """构造含 100+ 参考叶节点、18 个属、3 个聚集及分散 Query 株与 1 个 Outgroup 的测试树。"""
    meta = {}
    genera = [f"Genus{idx:02d}virus" for idx in range(18)]
    hosts = ["Escherichia", "Pseudomonas", "Bacillus", "Flavobacterium", "Streptomyces"]

    # 第一大支含 2 个 query 与 Genus00virus
    sub1 = []
    for k in range(10):
        name = f"Ref_A{k}"
        sub1.append(f"{name}:{0.02 + k * 0.004:.4f}")
        meta[name] = {
            "role": "ictv_rep",
            "description": f"Escherichia phage A{k}",
            "genus": genera[k % 2],
            "host": hosts[k % len(hosts)],
            "genome_length": 45000 + k * 3000,
            "gc_content": 38.0 + (k % 12),
        }
    sub1.insert(2, "Query_Alpha:0.015")
    meta["Query_Alpha"] = {
        "role": "query",
        "genus": "",
        "host": "Escherichia",
        "genome_length": 48000,
        "gc_content": 39.2,
    }
    sub1.insert(3, "Query_Beta:0.018")
    meta["Query_Beta"] = {
        "role": "query",
        "genus": "",
        "host": "Escherichia",
        "genome_length": 49100,
        "gc_content": 39.6,
    }

    # 其余远缘支（含 1 个分散 Query_Gamma 与多种属）
    cur = 0
    groups = [f"({','.join(sub1)})'98/100':0.08"]
    while cur < n_ref:
        grp = []
        for _ in range(12):
            if cur >= n_ref:
                break
            name = f"Ref_B{cur}"
            g_idx = 2 + (cur % 16)
            grp.append(f"{name}:{0.05 + (cur % 7) * 0.01:.4f}")
            meta[name] = {
                "role": "neighbor",
                "description": f"Vibrio phage B{cur}",
                "genus": genera[g_idx],
                "host": hosts[cur % len(hosts)],
                "genome_length": 30000 + (cur % 10) * 12000,
                "gc_content": 32.0 + (cur % 28),
            }
            cur += 1
        if cur == 24:
            grp.append("Query_Gamma:0.032")
            meta["Query_Gamma"] = {
                "role": "query",
                "genus": "",
                "host": "Pseudomonas",
                "genome_length": 62000,
                "gc_content": 54.0,
            }
        groups.append(f"({','.join(grp)})'91/96':0.12")

    groups.append("Outgroup_OG:0.45")
    meta["Outgroup_OG"] = {
        "role": "outgroup",
        "description": "Vibrio phage Gary",
        "genus": "Thalassavirus",
        "host": "Vibrio",
        "genome_length": 128000,
        "gc_content": 41.0,
    }
    return f"({','.join(groups)});", meta


def test_top_genus_consolidation_prevents_color_collision() -> None:
    """校验 Top-K 属分类收敛：绝无跨属颜色冲突，其余属归入 other_genera。"""
    nwk, meta = _build_large_synthetic_tree(108)
    root = parse_newick(nwk)

    def _collect(n):
        return [n] if n.is_leaf else [lf for ch in n.children for lf in _collect(ch)]

    leaves = _collect(root)
    palette = get_journal_palette("nature")
    genus_colors, other_genera, other_cnt, unclass_cnt = build_top_genus_palette(
        leaves, meta, palette, top_k=8
    )

    assert len(genus_colors) == 8
    assert len(set(genus_colors.values())) == 8
    assert "Genus00virus" in genus_colors
    assert len(other_genera) >= 8
    assert other_cnt > 0
    assert unclass_cnt >= 3


def test_subtree_extractor_preserves_queries_and_supports() -> None:
    """校验局部子树提取器保留所有 Query 株、控制叶数规模并保留支持率且不破坏原树。"""
    nwk, meta = _build_large_synthetic_tree(108)
    root = parse_newick(nwk)
    orig_leaf_total = len([k for k in meta])

    focused_root, focused_names = extract_query_focus_subtree(
        root, meta, max_leaves=30, min_leaves=10
    )

    def _collect(n):
        return [n] if n.is_leaf else [lf for ch in n.children for lf in _collect(ch)]

    orig_after = _collect(root)
    assert len(orig_after) == orig_leaf_total
    assert 10 <= len(focused_names) <= 34
    assert {"Query_Alpha", "Query_Beta", "Query_Gamma"}.issubset(focused_names)
    focused_leaves = _collect(focused_root)
    assert len(focused_leaves) == len(focused_names)


def test_macro_circular_auto_label_culling_and_composite_layout(tmp_path: Path) -> None:
    """校验 100+ 叶宏观环形图自动隐藏背景标签保留 Query 标注，以及 composite 双拼图导出。"""
    nwk, meta = _build_large_synthetic_tree(108)
    for layout_mode in ("circular", "composite"):
        out_dir = tmp_path / f"macro_{layout_mode}"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            paths = PublicationTreeRenderer.render(
                newick=nwk,
                node_metadata=meta,
                out_dir=out_dir,
                request=PublicationFigureRequest(
                    layout=layout_mode,  # type: ignore[arg-type]
                    formats=["pdf", "svg", "png"],
                    dpi=150,
                    label_density="auto",
                    top_genera_limit=8,
                    subtree_max_leaves=28,
                    title="Should Not Render When Default Off",
                ),
                file_prefix="pub_macro",
                subtitle="Model: LG+I+R4",
            )
        missing_glyphs = [str(w.message) for w in caught if "missing from font" in str(w.message)]
        assert missing_glyphs == []

        by_ext = {p.suffix.lower(): p for p in paths}
        assert by_ext[".pdf"].read_bytes().startswith(b"%PDF")
        assert by_ext[".png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        svg_text = by_ext[".svg"].read_text(encoding="utf-8")
        assert "Query_Alpha" in svg_text
        assert "Query_Gamma" in svg_text
        assert "Others (" in svg_text
        assert "Should Not Render When Default Off" not in svg_text
        if layout_mode == "circular":
            assert "Vibrio phage B40 (Ref_B40)" not in svg_text
        if layout_mode == "composite":
            assert "Clade b" in svg_text


def test_clade_detector_ignores_unmapped_others_and_supports_family_rank() -> None:
    """校验未列入专属色板的 Others 分类不产生灰色脏阴影，且支持按 family 层级检测。"""
    root = parse_newick(_SLOW_EVOLUTION_NEWICK)

    def _collect(node):
        return [node] if node.is_leaf else [lf for ch in node.children for lf in _collect(ch)]

    leaves = _collect(root)
    partial_meta = {
        "Q_Phage_1": {"role": "query", "genus": "", "family": "Demerecviridae"},
        "AY587007": {"role": "ictv_rep", "genus": "Tequintavirus", "family": "Demerecviridae"},
        "EF204940": {"role": "neighbor", "genus": "Tequintavirus", "family": "Demerecviridae"},
        "MK373780": {"role": "ictv_rep", "genus": "Vequintavirus", "family": "Straboviridae"},
        "KX123456": {"role": "neighbor", "genus": "Vequintavirus", "family": "Straboviridae"},
        "测试中文噬菌体株01": {"role": "query", "genus": "", "family": ""},
        "NC_055913": {"role": "outgroup", "genus": "Thalassavirus", "family": "Demerecviridae"},
    }
    # 仅给 Tequintavirus 配色，Vequintavirus 模拟归入 Others
    clades_genus = detect_monophyletic_clades(
        root, leaves, partial_meta, {"Tequintavirus": "#3C5488"}, rank_field="genus"
    )
    assert [c.taxon_name for c in clades_genus] == ["Tequintavirus"]

    clades_family = detect_monophyletic_clades(
        root,
        leaves,
        partial_meta,
        {"Demerecviridae": "#3C5488", "Straboviridae": "#00A087"},
        rank_field="family",
    )
    assert {c.taxon_name for c in clades_family} == {"Demerecviridae", "Straboviridae"}


def test_auto_rank_switches_to_family_on_macro_tree_and_gc_heatmap_color() -> None:
    """校验大树多属自动切换 family 主色带及 GC 连续热图色阶映射。"""
    nwk, meta = _build_large_synthetic_tree(108)
    # 补充 36+ 属与 6 个有效 family 以触发宏观科级切换
    fams = ["Demerecviridae", "Straboviridae", "Autographiviridae", "Herelleviridae", "Kyanoviridae", "Schitoviridae"]
    for idx, (_k, v) in enumerate(meta.items()):
        if v.get("role") != "query":
            v["genus"] = f"UniqueGenus{idx:03d}virus"
            v["family"] = fams[idx % len(fams)]

    root = parse_newick(nwk)

    def _collect(n):
        return [n] if n.is_leaf else [lf for ch in n.children for lf in _collect(ch)]

    leaves = _collect(root)
    assert choose_macro_taxon_rank(leaves, meta) == "family"
    palette = get_journal_palette("nature")
    fam_colors, other_fams, other_cnt, _ = build_top_taxon_palette(
        leaves, meta, palette, top_k=10, rank_field="family"
    )
    assert len(fam_colors) == 6
    assert other_cnt == 0
    assert len(other_fams) == 0

    c_low = gc_value_to_hex(25.0, 20.0, 80.0, "nature")
    c_mid = gc_value_to_hex(50.0, 20.0, 80.0, "nature")
    c_high = gc_value_to_hex(75.0, 20.0, 80.0, "nature")
    assert c_low.startswith("#") and len(c_low) == 7
    assert c_mid.startswith("#") and len(c_mid) == 7
    assert c_high.startswith("#") and len(c_high) == 7
    assert len({c_low, c_mid, c_high}) == 3


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """二维跨立线段相交检测（用于严格证明折线绝无交叉）。"""
    def _ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    # 包围盒快速排斥
    if max(p1[0], p2[0]) < min(q1[0], q2[0]) - 1e-9 or max(q1[0], q2[0]) < min(p1[0], p2[0]) - 1e-9:
        return False
    if max(p1[1], p2[1]) < min(q1[1], q2[1]) - 1e-9 or max(q1[1], q2[1]) < min(p1[1], p2[1]) - 1e-9:
        return False
    d1 = _ccw(q1, q2, p1)
    d2 = _ccw(q1, q2, p2)
    d3 = _ccw(p1, p2, q1)
    d4 = _ccw(p1, p2, q2)
    return (d1 * d2 <= 0) and (d3 * d4 <= 0)


def test_ring_elbow_leaders_never_intersect() -> None:
    """校验开口处正交阶梯折线严格零交叉且标签按内->外顺序自上而下排布。"""
    polylines = compute_ring_elbow_leaders([1.08, 1.15, 1.22, 1.32], start_deg=15.0, x_label=1.48)
    assert len(polylines) == 4
    slot_ys = [poly[-1][1] for poly in polylines]
    assert slot_ys == sorted(slot_ys, reverse=True)

    segments = []
    for idx, poly in enumerate(polylines):
        assert len(poly) == 3
        segments.append((idx, poly[0], poly[1]))
        segments.append((idx, poly[1], poly[2]))

    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            idx_a, a1, a2 = segments[i]
            idx_b, b1, b2 = segments[j]
            if idx_a == idx_b:
                continue
            assert not _segments_intersect(a1, a2, b1, b2), f"Lines {idx_a} and {idx_b} intersect!"


def test_query_clade_shading_mode_only_highlights_query_clade_and_adds_legend(tmp_path: Path) -> None:
    """校验 query_clade 默认模式仅高亮含 Query 的目标支系，并在图例明确标注底色语义。"""
    nwk, meta = _build_large_synthetic_tree(108)
    out_comp = tmp_path / "comp_query_clade"
    paths = PublicationTreeRenderer.render(
        newick=nwk,
        node_metadata=meta,
        out_dir=out_comp,
        request=PublicationFigureRequest(
            layout="composite",
            formats=["svg"],
            clade_shading_mode="query_clade",
            top_genera_limit=8,
            subtree_max_leaves=28,
        ),
        file_prefix="pub_qclade",
    )
    svg_comp = paths[0].read_text(encoding="utf-8")
    assert "Target Clade" in svg_comp or "Highlighted Clade" in svg_comp

    # 独立 circular 模式也应有清晰底色图例说明
    out_circ = tmp_path / "circ_query_clade"
    paths_c = PublicationTreeRenderer.render(
        newick=nwk,
        node_metadata=meta,
        out_dir=out_circ,
        request=PublicationFigureRequest(
            layout="circular",
            formats=["svg"],
            clade_shading_mode="query_clade",
            top_genera_limit=8,
        ),
        file_prefix="pub_qcirc",
    )
    svg_circ = paths_c[0].read_text(encoding="utf-8")
    assert "Target Clade" in svg_circ


def test_half_circular_semicircle_layout(tmp_path: Path) -> None:
    """校验 180° 半圆扇形大树版式渲染输出有效 PDF/SVG/PNG 且包含宿主、尺度标与目标支系标识。"""
    nwk, meta = _build_large_synthetic_tree(108)
    out_half = tmp_path / "half_circ"
    paths = PublicationTreeRenderer.render(
        newick=nwk,
        node_metadata=meta,
        out_dir=out_half,
        request=PublicationFigureRequest(
            layout="half_circular",
            formats=["pdf", "svg", "png"],
            dpi=150,
            palette="nature",
            clade_shading_mode="query_clade",
            show_host_strip=True,
            show_genome_length=True,
            show_gc_bar=True,
        ),
        file_prefix="pub_half",
    )
    assert len(paths) == 3
    by_ext = {p.suffix.lower(): p for p in paths}
    assert by_ext[".pdf"].read_bytes().startswith(b"%PDF")
    assert by_ext[".png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    svg_txt = by_ext[".svg"].read_text(encoding="utf-8")
    assert "<svg" in svg_txt.lower()
    assert "substitutions/site" in svg_txt
    assert "Query_Alpha" in svg_txt




