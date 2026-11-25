# -*- coding: utf-8 -*-
"""
PublicationTreeRenderer - 离线本地科研期刊级多环/矩形/复合进化树矢量渲染薄门面
底层已按单一职责拆解为 renderer_helpers / legend_panel / circular_layout / rectangular_layout。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..models.schemas import PublicationFigureRequest
from .circular_layout import _draw_circular_on_axes, _render_circular, _render_half_circular
from .clade_detector import detect_monophyletic_clades
from .label_formatter import enrich_node_metadata, format_leaf_label
from .legend_panel import _draw_legend_panel, _resolve_lw_scale
from .publication_palettes import (
    build_top_taxon_palette,
    choose_macro_taxon_rank,
    get_journal_palette,
)
from .rectangular_layout import _draw_rectangular_on_axes, _render_composite, _render_rectangular
from .renderer_helpers import (
    _OTHER_TAXON_COLOR,
    _UNCLASSIFIED_LIGHT_COLOR,
    _build_host_phylum_map,
    _collect_leaves,
    _compute_gc_range,
    _compute_node_depths,
    _configure_matplotlib_fonts,
    _deconflict_query_angles,
    _draw_section_header,
    _draw_text,
    _filter_clades_for_mode,
    _format_support_text,
    _ladderize,
    _resolve_effective_clade_mode,
    _resolve_leaf_style,
    _style_legend_entries,
    _subtree_branch_style,
)

__all__ = [
    "PublicationTreeRenderer",
    "_OTHER_TAXON_COLOR",
    "_UNCLASSIFIED_LIGHT_COLOR",
    "_build_host_phylum_map",
    "_collect_leaves",
    "_compute_gc_range",
    "_compute_node_depths",
    "_configure_matplotlib_fonts",
    "_deconflict_query_angles",
    "_draw_circular_on_axes",
    "_draw_legend_panel",
    "_draw_rectangular_on_axes",
    "_draw_section_header",
    "_draw_text",
    "_filter_clades_for_mode",
    "_format_support_text",
    "_ladderize",
    "_render_circular",
    "_render_composite",
    "_render_half_circular",
    "_render_rectangular",
    "_resolve_effective_clade_mode",
    "_resolve_leaf_style",
    "_resolve_lw_scale",
    "_style_legend_entries",
    "_subtree_branch_style",
]


class PublicationTreeRenderer:
    """方案 C 离线发表级进化树多格式渲染入口。"""

    @staticmethod
    def render(
        newick: str,
        node_metadata: Optional[Dict[str, Dict[str, Any]]],
        out_dir: Path,
        request: PublicationFigureRequest,
        file_prefix: str = "publication",
        subtitle: str = "",
    ) -> List[Path]:
        from ..pipeline.postprocess import parse_newick

        _configure_matplotlib_fonts()
        out_dir.mkdir(parents=True, exist_ok=True)

        root = parse_newick(newick)
        if request.ladderize:
            _ladderize(root, ascending=True)
        leaves = _collect_leaves(root)
        if not leaves:
            raise ValueError("Newick 中未包含任何有效叶子节点，无法绘制出版级图件。")

        palette = get_journal_palette(request.palette)
        meta = enrich_node_metadata(node_metadata, [lf.name for lf in leaves])
        display_labels = {
            lf.name: format_leaf_label(lf.name, meta.get(lf.name), request.label_format)
            for lf in leaves
        }
        macro_rank = choose_macro_taxon_rank(leaves, meta)
        taxon_colors, other_taxa, other_count, unclassified_count = build_top_taxon_palette(
            leaves, meta, palette, top_k=request.top_genera_limit, rank_field=macro_rank
        )
        leaf_phylum, phylum_colors = _build_host_phylum_map(leaves, meta, palette)
        eff_clade_mode = _resolve_effective_clade_mode(request)
        raw_clades = (
            detect_monophyletic_clades(root, leaves, meta, taxon_colors, rank_field=macro_rank)
            if eff_clade_mode != "none"
            else []
        )
        clades = _filter_clades_for_mode(raw_clades, root, leaves, meta, palette, eff_clade_mode)

        if request.layout == "composite":
            fig = _render_composite(
                root,
                leaves,
                meta,
                display_labels,
                taxon_colors,
                other_taxa,
                other_count,
                unclassified_count,
                macro_rank,
                leaf_phylum,
                phylum_colors,
                clades,
                palette,
                request,
                subtitle,
            )
        elif request.layout == "circular":
            fig = _render_circular(
                root,
                leaves,
                meta,
                display_labels,
                taxon_colors,
                other_taxa,
                other_count,
                unclassified_count,
                macro_rank,
                leaf_phylum,
                phylum_colors,
                clades,
                palette,
                request,
                subtitle,
            )
        elif request.layout == "half_circular":
            fig = _render_half_circular(
                root,
                leaves,
                meta,
                display_labels,
                taxon_colors,
                other_taxa,
                other_count,
                unclassified_count,
                macro_rank,
                leaf_phylum,
                phylum_colors,
                clades,
                palette,
                request,
                subtitle,
            )
        else:
            fig = _render_rectangular(
                root,
                leaves,
                meta,
                display_labels,
                taxon_colors,
                other_taxa,
                other_count,
                unclassified_count,
                macro_rank,
                leaf_phylum,
                phylum_colors,
                clades,
                palette,
                request,
                subtitle,
            )

        generated: List[Path] = []
        try:
            w_in, h_in = fig.get_size_inches()
            max_side_in = max(float(w_in), float(h_in), 1.0)
            for fmt in dict.fromkeys(request.formats):
                fname = f"{file_prefix}_{request.layout}.{fmt}"
                fpath = out_dir / fname
                save_kw: Dict[str, Any] = {"bbox_inches": "tight", "pad_inches": 0.18, "facecolor": "white"}
                if fmt == "png":
                    safe_dpi = min(request.dpi, max(96, int(11500 / max_side_in)))
                    save_kw["dpi"] = safe_dpi
                fig.savefig(fpath, format=fmt, **save_kw)
                generated.append(fpath)
        finally:
            plt.close(fig)

        return generated
