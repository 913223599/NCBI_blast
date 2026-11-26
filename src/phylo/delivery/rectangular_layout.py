# -*- coding: utf-8 -*-
"""出版级进化树矩形多轨布局与复合双拼图 (Panel a + b) 渲染模块。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle

from ..models.schemas import PublicationFigureRequest
from .circular_layout import _draw_circular_on_axes
from .clade_detector import MonophyleticClade, detect_monophyletic_clades
from .label_formatter import format_leaf_label
from .legend_panel import _draw_legend_panel, _resolve_lw_scale
from .publication_palettes import (
    JournalPalette,
    build_top_taxon_palette,
    compute_nice_scale_bar,
    gc_value_to_hex,
    is_formal_taxon_name,
    pick_font_family,
    resolve_latin_font,
)
from .renderer_helpers import (
    _OTHER_TAXON_COLOR,
    _UNCLASSIFIED_LIGHT_COLOR,
    _collect_leaves,
    _compute_gc_range,
    _compute_node_depths,
    _draw_text,
    _filter_clades_for_mode,
    _format_support_text,
    _ladderize,
    _resolve_effective_clade_mode,
    _resolve_leaf_style,
    _subtree_branch_style,
)
from .subtree_extractor import extract_query_focus_subtree

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode


def _assign_rectangular_y_positions(root: "PhyloNode", leaves: List["PhyloNode"]) -> Dict[int, float]:
    """为矩形进化树的所有节点分配自顶向下的 Y 坐标。"""
    n_leaves = len(leaves)
    y_pos: Dict[int, float] = {id(lf): float(n_leaves - 1 - idx) for idx, lf in enumerate(leaves)}

    def _assign_y(node: "PhyloNode") -> float:
        if node.is_leaf:
            return y_pos[id(node)]
        ys = [_assign_y(ch) for ch in node.children]
        val = sum(ys) / len(ys)
        y_pos[id(node)] = val
        return val

    _assign_y(root)
    return y_pos


def _draw_clade_shading(
    ax_tree: plt.Axes,
    clades: List[MonophyleticClade],
    depths: Dict[int, float],
    max_depth: float,
    label_pad: float,
    right_margin: float,
    n_leaves: int,
    has_strip_axes: bool,
    palette: JournalPalette,
    lw_scale: float,
    label_font: float,
) -> None:
    """绘制单系支系柔和背景阴影及无轨道时的右侧支系括号标签。"""
    shade_right = max_depth + label_pad + right_margin * 0.94
    for cl in clades:
        x_left = max(0.0, depths[id(cl.node)] - max_depth * 0.006)
        y_top = float(n_leaves - 1 - cl.leaf_start_idx) + 0.42
        y_bot = float(n_leaves - 1 - cl.leaf_end_idx) - 0.42
        ax_tree.add_patch(
            Rectangle(
                (x_left, y_bot),
                shade_right - x_left,
                y_top - y_bot,
                facecolor=cl.color,
                alpha=palette.clade_alpha,
                edgecolor="none",
                zorder=0.6,
            )
        )
        if not has_strip_axes:
            bx = shade_right + max_depth * 0.015
            ax_tree.plot([bx, bx], [y_bot + 0.06, y_top - 0.06], color=cl.color, linewidth=1.3 * lw_scale, zorder=3)
            _draw_text(
                ax_tree,
                bx + max_depth * 0.015,
                (y_top + y_bot) * 0.5,
                cl.taxon_name,
                fontsize=max(5.8, label_font * 0.9),
                fontstyle="italic" if is_formal_taxon_name(cl.taxon_name) else "normal",
                fontweight="bold",
                color=cl.color,
                va="center",
                ha="left",
                zorder=5,
            )


def _draw_rectangular_branches(
    ax_tree: plt.Axes,
    root: "PhyloNode",
    depths: Dict[int, float],
    y_pos: Dict[int, float],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str,
) -> None:
    """收集并批量绘制矩形进化树主分支线段。"""
    segments: List[List[Tuple[float, float]]] = []
    seg_cols: List[str] = []
    seg_lws: List[float] = []
    seg_lss: List[str] = []

    def _collect(node: "PhyloNode") -> None:
        xp = depths[id(node)]
        yp = y_pos[id(node)]
        for ch in node.children:
            xc = depths[id(ch)]
            yc = y_pos[id(ch)]
            col, lw, ls = _subtree_branch_style(
                ch, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field=rank_field
            )
            segments.append([(xp, yp), (xp, yc)])
            seg_cols.append(col)
            seg_lws.append(lw)
            seg_lss.append("-")
            segments.append([(xp, yc), (xc, yc)])
            seg_cols.append(col)
            seg_lws.append(lw)
            seg_lss.append(ls)
            _collect(ch)

    _collect(root)
    if segments:
        ax_tree.add_collection(
            LineCollection(
                segments, colors=seg_cols, linewidths=seg_lws, linestyles=seg_lss, capstyle="round", zorder=2
            )
        )


def _draw_rectangular_leaf_tips(
    ax_tree: plt.Axes,
    leaves: List["PhyloNode"],
    depths: Dict[int, float],
    y_pos: Dict[int, float],
    max_depth: float,
    label_pad: float,
    label_font: float,
    display_labels: Dict[str, str],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str,
    show_query_star: bool,
) -> None:
    """绘制叶节点虚线对齐、Query 星标及叶标签文字。"""
    for lf in leaves:
        x_tip = depths[id(lf)]
        y_tip = y_pos[id(lf)]
        disp_text = display_labels.get(lf.name, lf.name)
        role, _, _, _ = _resolve_leaf_style(
            lf.name, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field
        )
        if x_tip < max_depth:
            ax_tree.plot(
                [x_tip, max_depth + label_pad * 0.6],
                [y_tip, y_tip],
                color="#cbd5e1",
                linewidth=0.5 * lw_scale,
                linestyle=":",
                zorder=1,
            )
        if role == "query" and show_query_star:
            ax_tree.scatter(
                [x_tip],
                [y_tip],
                marker="*",
                s=46 * lw_scale,
                color=palette.query_color,
                edgecolor="white",
                linewidth=0.35,
                zorder=6,
            )
        _draw_text(
            ax_tree,
            max_depth + label_pad,
            y_tip,
            disp_text,
            fontsize=label_font,
            fontweight="bold" if role == "query" else "normal",
            color=palette.query_text_color if role == "query" else ("#475569" if role == "outgroup" else "#0f172a"),
            va="center",
            ha="left",
            zorder=5,
        )


def _draw_support_values(
    ax_tree: plt.Axes,
    root: "PhyloNode",
    depths: Dict[int, float],
    y_pos: Dict[int, float],
    max_depth: float,
    label_font: float,
    dense_mode: bool,
    lw_scale: float,
    palette: JournalPalette,
    support_style: str,
) -> None:
    """绘制内部节点支持率圆点与数值标注。"""
    dot_s_strong = 10.0 if dense_mode else 12.0 * lw_scale
    dot_s_mod = 8.0 if dense_mode else 10.0 * lw_scale

    def _draw_sup(node: "PhyloNode") -> None:
        if not node.is_leaf and node is not root:
            txt, uf_val = _format_support_text(node.name)
            xn = depths[id(node)]
            yn = y_pos[id(node)]
            if uf_val is not None and support_style in ("dots", "both"):
                if uf_val >= 95.0:
                    ax_tree.scatter(
                        [xn], [yn], s=dot_s_strong, facecolor=palette.strong_dot_color,
                        edgecolor="white", linewidth=0.4, zorder=6,
                    )
                elif uf_val >= 80.0:
                    ax_tree.scatter(
                        [xn], [yn], s=dot_s_mod, facecolor="#ffffff",
                        edgecolor=palette.moderate_dot_edge, linewidth=0.75, zorder=6,
                    )
            if txt and (
                support_style in ("text", "both")
                or (not dense_mode and uf_val is not None and uf_val >= 70.0)
            ):
                _draw_text(
                    ax_tree,
                    xn - max_depth * 0.010,
                    yn + 0.14,
                    txt,
                    fontsize=max(4.8, label_font * 0.72),
                    color="#1e293b" if (uf_val or 0) >= 95.0 else "#64748b",
                    ha="right",
                    va="bottom",
                    zorder=7,
                )
        for ch in node.children:
            _draw_sup(ch)

    _draw_sup(root)


def _draw_taxon_strip(
    ax_s: plt.Axes,
    leaves: List["PhyloNode"],
    y_pos: Dict[int, float],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    rank_field: str,
    palette: JournalPalette,
    latin_font: str,
    label_font: float,
    dense_mode: bool,
    y_min_lim: float,
    y_max_lim: float,
) -> None:
    """绘制分类单元（属/科）右侧色条轨道。"""
    ax_s.set_ylim(y_min_lim, y_max_lim)
    ax_s.axis("off")
    rank_hdr = "Family" if rank_field == "family" else "Genus"

    def _leaf_label_key(lf: "PhyloNode") -> Tuple[str, str]:
        meta = node_metadata.get(lf.name, {})
        role = str(meta.get("role") or "").lower()
        if role == "query":
            return "Query", palette.query_color
        if role == "outgroup":
            return "Outgroup", palette.outgroup_color
        t_val = str(meta.get(rank_field) or "").strip()
        if t_val in taxon_colors:
            return t_val, taxon_colors[t_val]
        if t_val in other_taxa:
            return t_val, _OTHER_TAXON_COLOR
        return "Unclassified", _UNCLASSIFIED_LIGHT_COLOR

    if dense_mode:
        ax_s.set_xlim(0, 1)
        ax_s.set_title(rank_hdr, fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#0f172a", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            _, col = _leaf_label_key(lf)
            ax_s.add_patch(Rectangle((0.08, y_tip - 0.36), 0.84, 0.72, facecolor=col, edgecolor="white", linewidth=0.25))
        return

    ax_s.set_xlim(0, 1.85)
    ax_s.set_title(rank_hdr, fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#0f172a", pad=4, loc="left")
    runs: List[Tuple[int, int, str, str]] = []
    for idx, lf in enumerate(leaves):
        t_lbl, t_col = _leaf_label_key(lf)
        if runs and runs[-1][2] == t_lbl and runs[-1][3] == t_col:
            runs[-1] = (runs[-1][0], idx, t_lbl, t_col)
        else:
            runs.append((idx, idx, t_lbl, t_col))

    for s_idx, e_idx, t_lbl, t_col in runs:
        y_top_bar = y_pos[id(leaves[s_idx])] + 0.38
        y_bot_bar = y_pos[id(leaves[e_idx])] - 0.38
        ax_s.add_patch(
            Rectangle((0.02, y_bot_bar), 0.15, y_top_bar - y_bot_bar, facecolor=t_col, edgecolor="white", linewidth=0.35)
        )
        _draw_text(
            ax_s,
            0.23,
            (y_top_bar + y_bot_bar) * 0.5,
            t_lbl,
            fontsize=max(5.6, label_font * 0.88),
            fontstyle="italic" if is_formal_taxon_name(t_lbl) else "normal",
            fontweight="bold" if t_lbl == "Query" else "normal",
            color=palette.query_text_color if t_lbl == "Query" else ("#64748b" if t_lbl in ("Unclassified", "Outgroup") else "#1e293b"),
            va="center",
            ha="left",
        )


def _draw_metadata_strips(
    strip_axes: Dict[str, plt.Axes],
    leaves: List["PhyloNode"],
    y_pos: Dict[int, float],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    rank_field: str,
    leaf_phylum: Dict[str, str],
    phylum_colors: Dict[str, str],
    palette: JournalPalette,
    latin_font: str,
    label_font: float,
    dense_mode: bool,
    max_len_kb: float,
    gc_range: Tuple[float, float],
    y_min_lim: float,
    y_max_lim: float,
) -> None:
    """绘制矩形进化树右侧辅助属性轨道（Taxon / Host / GC / Size）。"""
    if "taxon" in strip_axes:
        _draw_taxon_strip(
            strip_axes["taxon"], leaves, y_pos, node_metadata, taxon_colors, other_taxa,
            rank_field, palette, latin_font, label_font, dense_mode, y_min_lim, y_max_lim,
        )

    if "host" in strip_axes:
        ax_h = strip_axes["host"]
        ax_h.set_xlim(0, 1)
        ax_h.set_ylim(y_min_lim, y_max_lim)
        ax_h.axis("off")
        ax_h.set_title("Host", fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#334155", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            phylum = leaf_phylum.get(lf.name, "")
            col = phylum_colors.get(phylum, _UNCLASSIFIED_LIGHT_COLOR) if phylum else "#f8fafc"
            ax_h.add_patch(
                Rectangle((0.10, y_tip - 0.36), 0.80, 0.72, facecolor=col, edgecolor="white", linewidth=0.25 if dense_mode else 0.4)
            )

    if "gc" in strip_axes:
        ax_g = strip_axes["gc"]
        gc_low, gc_high = gc_range
        ax_g.set_xlim(0, 1.0 if dense_mode else 1.55)
        ax_g.set_ylim(y_min_lim, y_max_lim)
        ax_g.axis("off")
        ax_g.set_title("GC (%)", fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#2171B5" if palette.name != "monochrome" else "#374151", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            gc = float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
            col_hex = gc_value_to_hex(gc, gc_low, gc_high, palette.name)
            ax_g.add_patch(
                Rectangle((0.08, y_tip - 0.34), 0.56 if not dense_mode else 0.84, 0.68, facecolor=col_hex, edgecolor="white", linewidth=0.25 if dense_mode else 0.4)
            )
            if not dense_mode and gc > 0:
                _draw_text(ax_g, 0.72, y_tip, f"{gc:.1f}%", fontsize=max(4.8, label_font * 0.72), va="center", color="#334155")

    if "size" in strip_axes:
        ax_l = strip_axes["size"]
        ax_l.set_xlim(0, max_len_kb * (1.12 if dense_mode else 1.45))
        ax_l.set_ylim(y_min_lim, y_max_lim)
        ax_l.axis("off")
        ax_l.set_title("Size (kb)", fontsize=7.5, fontweight="bold", fontfamily=latin_font, color=palette.size_bar_color, pad=4)
        ax_l.axvline(max_len_kb * 0.5, ymin=0.04, ymax=0.98, color="#cbd5e1", linestyle="--", linewidth=0.50, zorder=1)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            kb = float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0
            ax_l.add_patch(Rectangle((0.0, y_tip - 0.26), max_len_kb, 0.52, facecolor="#f8fafc", edgecolor="none", zorder=0.5))
            ax_l.barh(y_tip, kb, height=0.52, color=palette.size_bar_color, edgecolor="none", zorder=2)
            if not dense_mode and kb > 0:
                _draw_text(ax_l, kb + max_len_kb * 0.04, y_tip, f"{kb:.1f}", fontsize=max(4.8, label_font * 0.72), va="center", color="#334155")
        ax_l.plot([0.0, max_len_kb], [-0.62, -0.62], color="#94a3b8", linewidth=0.7)
        _draw_text(ax_l, 0.0, -0.95, "0", fontsize=5.6, ha="left", color="#64748b")
        _draw_text(ax_l, max_len_kb, -0.95, f"{max_len_kb:.0f}", fontsize=5.6, ha="center", color="#64748b")


def _draw_rectangular_on_axes(
    ax_tree: plt.Axes,
    strip_axes: Dict[str, plt.Axes],
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    display_labels: Dict[str, str],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    rank_field: str,
    leaf_phylum: Dict[str, str],
    phylum_colors: Dict[str, str],
    clades: List[MonophyleticClade],
    palette: JournalPalette,
    req: PublicationFigureRequest,
    max_len_kb: float,
    gc_range: Tuple[float, float],
    panel_label: Optional[str] = None,
) -> None:
    """在指定矩形树 Axes 及右侧轨道 Axes 上绘制高清矩形进化树。"""
    n_leaves = len(leaves)
    depths = _compute_node_depths(root, req.use_branch_lengths)
    max_depth = max(depths.values()) or 1.0
    lw_scale = _resolve_lw_scale(req.journal_width)
    dense_mode = n_leaves > 45
    y_pos = _assign_rectangular_y_positions(root, leaves)

    max_chars = max((len(display_labels.get(lf.name, lf.name)) for lf in leaves), default=12)
    label_pad = max_depth * 0.032
    right_margin = max_depth * max(0.45, min(2.05, max_chars * 0.024))
    label_font = 6.2 if dense_mode else max(6.4, min(8.2, 240.0 / max(24, n_leaves)))
    if req.journal_width == "single_col":
        label_font = max(5.2, label_font * 0.88)

    if req.show_clade_shading and clades:
        _draw_clade_shading(
            ax_tree, clades, depths, max_depth, label_pad, right_margin,
            n_leaves, bool(strip_axes), palette, lw_scale, label_font,
        )

    _draw_rectangular_branches(
        ax_tree, root, depths, y_pos, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field
    )
    _draw_rectangular_leaf_tips(
        ax_tree, leaves, depths, y_pos, max_depth, label_pad, label_font, display_labels,
        node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field, req.show_query_star,
    )
    if req.support_style != "none":
        _draw_support_values(
            ax_tree, root, depths, y_pos, max_depth, label_font, dense_mode, lw_scale, palette, req.support_style
        )

    extra_bracket = max_depth * 0.14 if (req.show_clade_shading and clades and not strip_axes) else 0.0
    ax_tree.set_xlim(-max_depth * 0.04, max_depth + label_pad + right_margin + extra_bracket)
    y_min_lim = -1.15
    y_max_lim = n_leaves - 0.15
    ax_tree.set_ylim(y_min_lim, y_max_lim)
    ax_tree.axis("off")

    if panel_label:
        _draw_text(
            ax_tree, -max_depth * 0.035, y_max_lim - 0.05, panel_label,
            fontsize=13.5, fontweight="bold", color="#0f172a", ha="left", va="top", zorder=10,
        )

    if req.use_branch_lengths and max_depth > 0:
        sb_val, sb_text = compute_nice_scale_bar(max_depth)
        ax_tree.plot([0.0, sb_val], [-0.68, -0.68], color="#0f172a", linewidth=1.2 * lw_scale)
        ax_tree.plot([0.0, 0.0], [-0.80, -0.56], color="#0f172a", linewidth=0.95 * lw_scale)
        ax_tree.plot([sb_val, sb_val], [-0.80, -0.56], color="#0f172a", linewidth=0.95 * lw_scale)
        _draw_text(ax_tree, sb_val * 0.5, -0.44, f"{sb_text} substitutions/site", fontsize=6.8, ha="center", color="#334155")

    _draw_metadata_strips(
        strip_axes, leaves, y_pos, node_metadata, taxon_colors, other_taxa, rank_field,
        leaf_phylum, phylum_colors, palette, resolve_latin_font(), label_font, dense_mode,
        max_len_kb, gc_range, y_min_lim, y_max_lim,
    )


def _render_rectangular(
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    display_labels: Dict[str, str],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    other_count: int,
    unclassified_count: int,
    rank_field: str,
    leaf_phylum: Dict[str, str],
    phylum_colors: Dict[str, str],
    clades: List[MonophyleticClade],
    palette: JournalPalette,
    req: PublicationFigureRequest,
    subtitle: str,
) -> plt.Figure:
    n_leaves = len(leaves)
    has_meta = bool(node_metadata)
    dense_mode = n_leaves > 45
    show_strip = has_meta and req.show_genus_strip
    show_host = has_meta and req.show_host_strip and bool(leaf_phylum)
    show_gc = has_meta and req.show_gc_bar
    show_len = has_meta and req.show_genome_length

    row_in = 0.145 if n_leaves > 120 else (0.19 if n_leaves > 60 else 0.24)
    if req.journal_width == "single_col":
        fig_h = max(5.8, 1.8 + n_leaves * (row_in * 0.88))
        fig_w = 11.8 if has_meta else 8.8
    elif req.journal_width == "double_col":
        fig_h = max(6.6, 2.0 + n_leaves * row_in)
        fig_w = 15.4 if has_meta else 11.0
    else:
        fig_h = max(6.8, 2.0 + n_leaves * row_in)
        fig_w = 16.0 if has_meta else 11.4

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")
    col_ratios: List[float] = [4.6]
    strip_names: List[str] = []
    if show_strip:
        col_ratios.append(0.30 if dense_mode else 1.25)
        strip_names.append("taxon")
    if show_host:
        col_ratios.append(0.30)
        strip_names.append("host")
    if show_gc:
        col_ratios.append(0.36 if dense_mode else 0.65)
        strip_names.append("gc")
    if show_len:
        col_ratios.append(0.95)
        strip_names.append("size")
    col_ratios.append(1.85)

    gs = fig.add_gridspec(1, len(col_ratios), width_ratios=col_ratios, wspace=0.05)
    ax_tree = fig.add_subplot(gs[0, 0])
    strip_axes = {name: fig.add_subplot(gs[0, 1 + i]) for i, name in enumerate(strip_names)}
    ax_leg = fig.add_subplot(gs[0, len(col_ratios) - 1])

    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0
    gc_range = _compute_gc_range(leaves, node_metadata)

    _draw_rectangular_on_axes(
        ax_tree,
        strip_axes,
        root,
        leaves,
        node_metadata,
        display_labels,
        taxon_colors,
        other_taxa,
        rank_field,
        leaf_phylum,
        phylum_colors,
        clades,
        palette,
        req,
        max_len_kb,
        gc_range,
    )

    _draw_legend_panel(
        ax_leg,
        leaves,
        node_metadata,
        taxon_colors,
        other_count,
        unclassified_count,
        rank_field,
        leaf_phylum,
        phylum_colors,
        palette,
        req,
        has_meta,
        max_len_kb,
        gc_range,
        subtitle,
        shaded_clades=clades,
        is_composite=False,
        legend_height_scale=min(1.0, 12.0 / max(12.0, fig_h)),
    )

    if req.show_figure_title and req.title:
        fig.suptitle(
            req.title,
            fontsize=11.0 if req.journal_width != "single_col" else 9.6,
            fontweight="bold",
            fontfamily=pick_font_family(req.title),
            color="#0f172a",
            y=0.985,
        )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.94 if (req.show_figure_title and req.title) else 0.97, bottom=0.03)
    return fig


def _render_composite(
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    display_labels: Dict[str, str],
    macro_taxon_colors: Dict[str, str],
    macro_other_taxa: Set[str],
    macro_other_count: int,
    macro_unclass_count: int,
    macro_rank: str,
    leaf_phylum: Dict[str, str],
    phylum_colors: Dict[str, str],
    macro_clades: List[MonophyleticClade],
    palette: JournalPalette,
    req: PublicationFigureRequest,
    subtitle: str,
) -> plt.Figure:
    """
    顶刊复合双拼模式（Panel a 全局多环环形概览 + Panel b Query 局部聚焦高精度矩形详图 + 统一图例）。
    - Panel a 宏观按 ICTV Family（科）着色呈现宏观谱系；
    - Panel b 局部子树独立按 Genus（属）分配 12 色高区分度专属色板 + 合并斜体属条。
    """
    focused_root, focused_names = extract_query_focus_subtree(
        root, node_metadata, max_leaves=req.subtree_max_leaves, min_leaves=12
    )
    if req.ladderize:
        _ladderize(focused_root, ascending=True)
    sub_leaves = _collect_leaves(focused_root)
    sub_labels = {
        lf.name: format_leaf_label(lf.name, node_metadata.get(lf.name), req.label_format)
        for lf in sub_leaves
    }

    # Panel b 局部子树独立采用 genus 专属高区分度配色
    eff_clade_mode = _resolve_effective_clade_mode(req)
    sub_genus_colors, sub_other_genera, _, _ = build_top_taxon_palette(
        sub_leaves, node_metadata, palette, top_k=12, rank_field="genus"
    )
    raw_sub_clades = (
        detect_monophyletic_clades(focused_root, sub_leaves, node_metadata, sub_genus_colors, rank_field="genus")
        if eff_clade_mode != "none"
        else []
    )
    sub_clades = _filter_clades_for_mode(
        raw_sub_clades, focused_root, sub_leaves, node_metadata, palette, eff_clade_mode
    )

    has_meta = bool(node_metadata)
    show_strip = has_meta and req.show_genus_strip
    show_host = has_meta and req.show_host_strip and bool(leaf_phylum)
    show_gc = has_meta and req.show_gc_bar
    show_len = has_meta and req.show_genome_length

    fig_h = max(8.8, min(14.5, 3.0 + len(sub_leaves) * 0.22))
    fig_w = 19.6 if has_meta else 15.6
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")

    col_ratios: List[float] = [4.75, 3.85]
    strip_names: List[str] = []
    if show_strip:
        col_ratios.append(1.22 if len(sub_leaves) <= 45 else 0.30)
        strip_names.append("taxon")
    if show_host:
        col_ratios.append(0.28)
        strip_names.append("host")
    if show_gc:
        col_ratios.append(0.58 if len(sub_leaves) <= 45 else 0.34)
        strip_names.append("gc")
    if show_len:
        col_ratios.append(0.76)
        strip_names.append("size")
    col_ratios.append(1.78)

    gs = fig.add_gridspec(1, len(col_ratios), width_ratios=col_ratios, wspace=0.055)
    ax_circ = fig.add_subplot(gs[0, 0])
    ax_circ.set_aspect("equal")
    ax_circ.axis("off")

    ax_rect = fig.add_subplot(gs[0, 1])
    strip_axes = {name: fig.add_subplot(gs[0, 2 + i]) for i, name in enumerate(strip_names)}
    ax_leg = fig.add_subplot(gs[0, len(col_ratios) - 1])

    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0
    gc_range = _compute_gc_range(leaves, node_metadata)

    # Panel a: 全局环形树（宏观模式 + 标出 Panel b 聚焦区）
    _draw_circular_on_axes(
        ax_circ,
        root,
        leaves,
        node_metadata,
        display_labels,
        macro_taxon_colors,
        macro_other_taxa,
        macro_rank,
        leaf_phylum,
        phylum_colors,
        macro_clades,
        palette,
        req,
        max_len_kb,
        gc_range,
        force_macro=True,
        highlight_names=focused_names if len(leaves) > len(sub_leaves) else None,
        panel_label="a",
    )

    # Panel b: Query 局部聚焦子树高精度矩形详图
    sub_max_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in sub_leaves),
        default=max_len_kb,
    ) or max_len_kb
    sub_gc_range = _compute_gc_range(sub_leaves, node_metadata)
    _draw_rectangular_on_axes(
        ax_rect,
        strip_axes,
        focused_root,
        sub_leaves,
        node_metadata,
        sub_labels,
        sub_genus_colors,
        sub_other_genera,
        "genus",
        leaf_phylum,
        phylum_colors,
        sub_clades,
        palette,
        req,
        sub_max_kb,
        sub_gc_range,
        panel_label="b",
    )

    _draw_legend_panel(
        ax_leg,
        leaves,
        node_metadata,
        macro_taxon_colors,
        macro_other_count,
        macro_unclass_count,
        macro_rank,
        leaf_phylum,
        phylum_colors,
        palette,
        req,
        has_meta,
        max_len_kb,
        gc_range,
        subtitle,
        shaded_clades=macro_clades or sub_clades,
        is_composite=True,
    )

    if req.show_figure_title and req.title:
        fig.suptitle(
            req.title,
            fontsize=11.0,
            fontweight="bold",
            fontfamily=pick_font_family(req.title),
            color="#0f172a",
            y=0.98,
        )
    fig.subplots_adjust(left=0.012, right=0.988, top=0.93 if (req.show_figure_title and req.title) else 0.96, bottom=0.04)
    return fig
