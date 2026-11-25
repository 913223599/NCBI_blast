# -*- coding: utf-8 -*-
"""
PublicationTreeRenderer - 方案 C：离线本地科研期刊级多环/矩形/复合进化树矢量渲染器
对标 Nature Communications / Nature Microbiology / MBE / Microbiology Spectrum 发表级美学标准：
- 宏微观自动分层：大树环形内圈按 ICTV Family 呈现演化格局，Panel b 局部聚焦详图独立按 Genus 高清着色；
- 中空圆心与同心参考虚线圆 + 叶端极细引导线直连内环，消除树冠断层与圆心死结；
- GC% 升级为连续学术色阶热图环/热图格，并在图例面板内嵌横向渐变 Colorbar；
- Panel b 合并连续垂直属分类条并直接标注斜体属名，配合关键节点支持率数字与去贴纸化 Query 标红星；
- 开口处水平轨道标引线、非对称紧致包围盒、带标题底线的流式出版图例及 1-2-5 科学比例尺。
"""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Arc, Patch, Rectangle, Wedge

from ..models.schemas import PublicationFigureRequest
from .clade_detector import MonophyleticClade, detect_monophyletic_clades
from .host_taxonomy import get_host_group_color, map_host_to_phylum
from .label_formatter import enrich_node_metadata, format_leaf_label
from .publication_palettes import (
    JournalPalette,
    build_top_taxon_palette,
    choose_macro_taxon_rank,
    compute_nice_scale_bar,
    compute_ring_elbow_leaders,
    gc_value_to_hex,
    get_journal_palette,
    is_formal_taxon_name,
    pick_font_family,
    resolve_latin_font,
)
from .subtree_extractor import extract_query_focus_subtree

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode

_OTHER_TAXON_COLOR = "#CBD5E1"
_UNCLASSIFIED_LIGHT_COLOR = "#E2E8F0"


def _configure_matplotlib_fonts() -> None:
    latin = resolve_latin_font()
    plt.rcParams["font.sans-serif"] = [
        latin,
        "Arial",
        "Helvetica",
        "DejaVu Sans",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["pdf.fonttype"] = 42


def _draw_text(ax: plt.Axes, x: float, y: float, text: str, **kwargs: Any) -> Any:
    """按文本字符集自动路由 Arial / 中文字体，彻底规避 PDF Type 42 缺字警告。"""
    kw = dict(kwargs)
    kw.setdefault("fontfamily", pick_font_family(text))
    return ax.text(x, y, text, **kw)


def _ladderize(node: "PhyloNode", ascending: bool = True) -> int:
    if node.is_leaf:
        return 1
    sized = [(ch, _ladderize(ch, ascending=ascending)) for ch in node.children]
    sized.sort(key=lambda item: item[1], reverse=not ascending)
    node.children = [item[0] for item in sized]
    return sum(item[1] for item in sized)


def _collect_leaves(node: "PhyloNode") -> List["PhyloNode"]:
    out: List["PhyloNode"] = []

    def _walk(cur: "PhyloNode") -> None:
        if cur.is_leaf:
            out.append(cur)
        else:
            for ch in cur.children:
                _walk(ch)

    _walk(node)
    return out


def _build_host_phylum_map(
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    leaf_phylum: Dict[str, str] = {}
    phylum_colors: Dict[str, str] = {}
    mono = palette.name == "monochrome"
    mono_shades = ("#374151", "#6B7280", "#9CA3AF", "#4B5563", "#D1D5DB", "#1F2937")

    for lf in leaves:
        host_raw = str((node_metadata.get(lf.name) or {}).get("host") or "").strip()
        phylum = map_host_to_phylum(host_raw)
        if phylum:
            leaf_phylum[lf.name] = phylum
            if phylum not in phylum_colors:
                phylum_colors[phylum] = (
                    mono_shades[len(phylum_colors) % len(mono_shades)]
                    if mono
                    else get_host_group_color(phylum)
                )
    return leaf_phylum, phylum_colors


def _compute_gc_range(
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
) -> Tuple[float, float]:
    vals = [
        float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
        for lf in leaves
    ]
    valid = [v for v in vals if v > 0.0]
    if not valid:
        return 0.0, 100.0
    low = max(0.0, math.floor((min(valid) - 4.0) / 5.0) * 5.0)
    high = min(100.0, math.ceil((max(valid) + 4.0) / 5.0) * 5.0)
    while high - low < 25.0:
        if low > 0.0:
            low = max(0.0, low - 5.0)
        if high - low < 25.0 and high < 100.0:
            high = min(100.0, high + 5.0)
        if low == 0.0 and high == 100.0:
            break
    return low, high


def _resolve_leaf_style(
    name: str,
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str = "genus",
) -> Tuple[str, str, float, str]:
    meta = node_metadata.get(name, {})
    role = str(meta.get("role") or "").strip().lower()
    taxon_val = str(meta.get(rank_field) or "").strip()
    if role == "query":
        return "query", palette.query_color, 1.45 * lw_scale, "-"
    if role == "outgroup":
        return "outgroup", palette.outgroup_color, 0.90 * lw_scale, "--"
    if taxon_val and taxon_val in taxon_colors:
        return "ref", taxon_colors[taxon_val], 0.90 * lw_scale, "-"
    if taxon_val and taxon_val in other_taxa:
        return "ref", palette.backbone_color, 0.80 * lw_scale, "-"
    return "ref", palette.backbone_color, 0.80 * lw_scale, "-"


def _subtree_branch_style(
    node: "PhyloNode",
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str = "genus",
    color_monophyletic_branches: bool = False,
) -> Tuple[str, float, str]:
    if node.is_leaf:
        role, col, lw, ls = _resolve_leaf_style(
            node.name, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field
        )
        if role == "query":
            return palette.query_color, lw, ls
        if role == "outgroup":
            return palette.outgroup_color, lw, ls
        if color_monophyletic_branches and col in taxon_colors.values():
            return col, lw, "-"
        return palette.backbone_color, lw, "-"

    sub_leaves = _collect_leaves(node)
    roles = {
        str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower()
        for lf in sub_leaves
    }
    if roles == {"query"}:
        return palette.query_color, 1.45 * lw_scale, "-"
    if roles == {"outgroup"}:
        return palette.outgroup_color, 0.90 * lw_scale, "--"
    if color_monophyletic_branches and "outgroup" not in roles:
        taxa = {
            str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
            for lf in sub_leaves
            if str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
        }
        if len(taxa) == 1:
            t_name = next(iter(taxa))
            if t_name in taxon_colors:
                return taxon_colors[t_name], 0.92 * lw_scale, "-"
    return palette.backbone_color, 0.82 * lw_scale, "-"


def _compute_node_depths(
    root: "PhyloNode",
    use_branch_lengths: bool,
) -> Dict[int, float]:
    depths: Dict[int, float] = {id(root): 0.0}

    def _walk(cur: "PhyloNode", cur_x: float) -> None:
        for ch in cur.children:
            step = max(0.0, ch.length) if use_branch_lengths else 1.0
            nx = cur_x + step
            depths[id(ch)] = nx
            _walk(ch, nx)

    _walk(root, 0.0)
    return depths


def _format_support_text(label: str) -> Tuple[Optional[str], Optional[float]]:
    from ..pipeline.postprocess import _parse_dual_support

    alrt, ufboot = _parse_dual_support(label)
    if alrt is not None and ufboot is not None:
        a_str = f"{alrt:.0f}" if abs(alrt - round(alrt)) < 0.05 else f"{alrt:.1f}"
        u_str = f"{ufboot:.0f}" if abs(ufboot - round(ufboot)) < 0.05 else f"{ufboot:.1f}"
        return f"{a_str}/{u_str}", ufboot
    if ufboot is not None:
        u_str = f"{ufboot:.0f}" if abs(ufboot - round(ufboot)) < 0.05 else f"{ufboot:.1f}"
        return u_str, ufboot
    return None, None


def _style_legend_entries(legend_obj: Any) -> None:
    for txt in legend_obj.get_texts():
        content = txt.get_text()
        txt.set_fontfamily(pick_font_family(content))
        if is_formal_taxon_name(content):
            txt.set_fontstyle("italic")


def _deconflict_query_angles(
    angles_deg: List[float],
    min_deg: float,
    max_deg: float,
    min_gap_deg: float = 5.4,
) -> List[float]:
    if len(angles_deg) <= 1:
        return list(angles_deg)
    res = list(angles_deg)
    for _ in range(36):
        moved = False
        for i in range(len(res) - 1):
            gap = res[i + 1] - res[i]
            if gap < min_gap_deg:
                shift = (min_gap_deg - gap) * 0.5
                res[i] = max(min_deg, res[i] - shift)
                res[i + 1] = min(max_deg, res[i + 1] + shift)
                moved = True
        if not moved:
            break
    return res


def _draw_section_header(ax: plt.Axes, y_top: float, title: str, line_w: float = 0.72) -> None:
    """绘制出版级带纤细底横线的图例小节标题（仿 Nature Communications Fig. 4a）。"""
    _draw_text(ax, 0.02, y_top, title, fontsize=8.4, fontweight="bold", color="#0f172a", va="top")
    ax.plot([0.02, 0.02 + line_w], [y_top - 0.023, y_top - 0.023], color="#334155", linewidth=0.65)


def _resolve_effective_clade_mode(req: PublicationFigureRequest) -> str:
    if not req.show_clade_shading:
        return "none"
    return req.clade_shading_mode


def _filter_clades_for_mode(
    clades: List[MonophyleticClade],
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
    mode: str,
) -> List[MonophyleticClade]:
    if mode == "none":
        return []
    if mode == "query_clade":
        query_leaves = [
            lf
            for lf in leaves
            if str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower() == "query"
        ]
        if query_leaves:
            matched = [c for c in clades if c.contains_query]
            if matched:
                return matched
            # 若 Query 落在多属混合支系中，回溯寻找包含 Query 的最小非根姐妹簇作为目标支系高亮
            leaf_idx_map = {id(lf): idx for idx, lf in enumerate(leaves)}
            parent_map: Dict[int, Optional["PhyloNode"]] = {id(root): None}

            def _map_parents(cur: "PhyloNode") -> None:
                for ch in cur.children:
                    parent_map[id(ch)] = cur
                    _map_parents(ch)

            _map_parents(root)
            max_span = max(8, min(20, int(len(leaves) * 0.25)))
            fallback_clades: List[MonophyleticClade] = []
            seen_nodes: Set[int] = set()
            for qlf in query_leaves:
                cur = parent_map.get(id(qlf))
                chosen = None
                while cur is not None and cur is not root:
                    sub = _collect_leaves(cur)
                    has_og = any(
                        str((node_metadata.get(x.name) or {}).get("role") or "").strip().lower() == "outgroup"
                        for x in sub
                    )
                    if not has_og and 2 <= len(sub) <= max_span:
                        chosen = cur
                        break
                    if has_og or len(sub) > max_span:
                        break
                    cur = parent_map.get(id(cur))
                if chosen is not None and id(chosen) not in seen_nodes:
                    seen_nodes.add(id(chosen))
                    idxs = [leaf_idx_map[id(x)] for x in _collect_leaves(chosen) if id(x) in leaf_idx_map]
                    if idxs:
                        fallback_clades.append(
                            MonophyleticClade(
                                node=chosen,
                                taxon_name="Target Clade",
                                color=palette.taxon_colors[0],
                                leaf_start_idx=min(idxs),
                                leaf_end_idx=max(idxs),
                                contains_query=True,
                            )
                        )
            return fallback_clades
    return clades


def _draw_legend_panel(
    ax: plt.Axes,
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_count: int,
    unclassified_count: int,
    rank_field: str,
    leaf_phylum: Dict[str, str],
    phylum_colors: Dict[str, str],
    palette: JournalPalette,
    req: PublicationFigureRequest,
    has_meta: bool,
    max_len_kb: float,
    gc_range: Tuple[float, float],
    subtitle: str,
    shaded_clades: Optional[List[MonophyleticClade]] = None,
    is_composite: bool = False,
    legend_height_scale: float = 1.0,
) -> None:
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    latin_font = resolve_latin_font()
    has_query = any(
        str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "query"
        for lf in leaves
    )
    has_og = any(
        str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "outgroup"
        for lf in leaves
    )

    taxon_counts: Counter[str] = Counter()
    for lf in leaves:
        val = str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
        if val in taxon_colors:
            taxon_counts[val] += 1

    y_cursor = 0.975
    rank_title = "ICTV Family / Role" if rank_field == "family" else "ICTV Genus / Role"

    # 1. ICTV Taxonomy / Role
    tax_handles: List[Any] = []
    if has_query:
        if req.show_query_star:
            tax_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker="*",
                    color="none",
                    markerfacecolor=palette.query_color,
                    markeredgecolor="white",
                    markeredgewidth=0.4,
                    markersize=8.2,
                    label="Query Phage (This study)",
                )
            )
        else:
            tax_handles.append(Patch(facecolor=palette.query_color, edgecolor="none", label="Query Phage"))
    if has_og:
        tax_handles.append(
            Line2D([0], [0], color=palette.outgroup_color, linestyle="--", linewidth=1.35, label="Outgroup")
        )
    for t_name, color in taxon_colors.items():
        cnt = taxon_counts.get(t_name, 0)
        lbl = f"{t_name} ({cnt})" if cnt > 0 else t_name
        tax_handles.append(Patch(facecolor=color, edgecolor="none", label=lbl))
    if other_count > 0:
        tax_handles.append(Patch(facecolor=_OTHER_TAXON_COLOR, edgecolor="none", label=f"Others ({other_count})"))
    if unclassified_count > 0:
        tax_handles.append(
            Patch(
                facecolor=_UNCLASSIFIED_LIGHT_COLOR,
                edgecolor="#cbd5e1",
                linewidth=0.35,
                label=f"Unclassified ({unclassified_count})",
            )
        )
    eff_clade_mode = _resolve_effective_clade_mode(req)
    if eff_clade_mode != "none" and shaded_clades:
        shade_col = shaded_clades[0].color
        shade_lbl = (
            "Highlighted Clade (Panel b)"
            if (is_composite and eff_clade_mode == "query_clade")
            else ("Target Clade (Query)" if eff_clade_mode == "query_clade" else "Clade Shading (Monophyletic)")
        )
        tax_handles.append(
            Patch(
                facecolor=shade_col,
                alpha=min(0.45, palette.clade_alpha * 2.2),
                edgecolor=shade_col,
                linewidth=0.5,
                label=shade_lbl,
            )
        )

    if tax_handles:
        _draw_section_header(ax, y_cursor, rank_title)
        ncol = 2 if len(tax_handles) > 10 else 1
        rows = math.ceil(len(tax_handles) / ncol)
        fsize = 7.0 if ncol == 1 else 6.3
        leg1 = ax.legend(
            handles=tax_handles,
            loc="upper left",
            bbox_to_anchor=(0.01, y_cursor - 0.032),
            ncol=ncol,
            columnspacing=0.80,
            frameon=False,
            fontsize=fsize,
            handlelength=1.15,
            handleheight=0.80,
            labelspacing=0.30,
            borderaxespad=0.0,
            prop={"family": latin_font, "size": fsize},
        )
        _style_legend_entries(leg1)
        ax.add_artist(leg1)
        y_cursor -= 0.048 + 0.026 * rows

    # 2. Host Phylum
    if has_meta and req.show_host_strip and phylum_colors and y_cursor > 0.24:
        host_counts = Counter(leaf_phylum.values())
        host_handles: List[Any] = []
        for phylum, cnt in host_counts.most_common(10):
            col = phylum_colors.get(phylum, "#6b7280")
            host_handles.append(Patch(facecolor=col, edgecolor="none", label=f"{phylum} ({cnt})"))
        if host_handles:
            y_cursor -= 0.014
            _draw_section_header(ax, y_cursor, "Host Phylum")
            ncol_h = 2 if len(host_handles) > 7 else 1
            rows_h = math.ceil(len(host_handles) / ncol_h)
            fsize_h = 6.9 if ncol_h == 1 else 6.3
            leg_host = ax.legend(
                handles=host_handles,
                loc="upper left",
                bbox_to_anchor=(0.01, y_cursor - 0.032),
                ncol=ncol_h,
                columnspacing=0.80,
                frameon=False,
                fontsize=fsize_h,
                handlelength=1.15,
                handleheight=0.80,
                labelspacing=0.28,
                borderaxespad=0.0,
                prop={"family": latin_font, "size": fsize_h},
            )
            _style_legend_entries(leg_host)
            ax.add_artist(leg_host)
            y_cursor -= 0.046 + 0.025 * rows_h

    # 3. Branch Support
    if req.support_style != "none" and y_cursor > 0.16:
        y_cursor -= 0.014
        _draw_section_header(ax, y_cursor, "Branch Support")
        sup_handles = [
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=palette.strong_dot_color,
                markeredgecolor="white",
                markeredgewidth=0.5,
                markersize=4.8,
                label="UFBoot >= 95% (Strong)",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="#ffffff",
                markeredgecolor=palette.moderate_dot_edge,
                markeredgewidth=1.0,
                markersize=4.4,
                label="80% <= UFBoot < 95%",
            ),
        ]
        leg2 = ax.legend(
            handles=sup_handles,
            loc="upper left",
            bbox_to_anchor=(0.01, y_cursor - 0.032),
            frameon=False,
            fontsize=6.8,
            labelspacing=0.28,
            borderaxespad=0.0,
            prop={"family": latin_font, "size": 6.8},
        )
        _style_legend_entries(leg2)
        ax.add_artist(leg2)
        y_cursor -= 0.095

    # 4. Genomic Tracks + 平滑横向连续渐变 GC Colorbar
    if has_meta and (req.show_genome_length or req.show_gc_bar) and y_cursor > 0.10:
        # 仅对超长矩形画布按实际纵轴比例缩放矩形图标高度，圆形与复合图保持饱满高度
        h_scale = legend_height_scale
        y_cursor -= 0.012
        _draw_section_header(ax, y_cursor, "Genomic Tracks")
        track_y = y_cursor - 0.034
        if req.show_genome_length:
            patch_h = 0.015 * h_scale
            ax.add_patch(Rectangle((0.02, track_y - patch_h * 0.5), 0.065, patch_h, facecolor=palette.size_bar_color, edgecolor="none"))
            _draw_text(
                ax,
                0.10,
                track_y,
                f"Genome Size (0-{max_len_kb:.0f} kb)",
                fontsize=6.8,
                color="#1e293b",
                va="center",
            )
            track_y -= max(0.016, 0.036 * h_scale)

        if req.show_gc_bar:
            gc_low, gc_high = gc_range
            gc_mid = (gc_low + gc_high) * 0.5
            _draw_text(ax, 0.02, track_y, "GC Content (%)", fontsize=6.8, color="#1e293b", va="top")
            bar_h = 0.017 * h_scale
            bar_y = track_y - max(0.014, 0.022 * h_scale) - bar_h
            bar_x0, bar_w = 0.02, 0.56
            n_bins = 32
            bin_w = bar_w / n_bins
            for idx in range(n_bins):
                val = gc_low + (gc_high - gc_low) * ((idx + 0.5) / n_bins)
                col_hex = gc_value_to_hex(val, gc_low, gc_high, palette.name)
                ax.add_patch(
                    Rectangle(
                        (bar_x0 + idx * bin_w, bar_y),
                        bin_w * 1.04,
                        bar_h,
                        facecolor=col_hex,
                        edgecolor="none",
                    )
                )
            ax.add_patch(Rectangle((bar_x0, bar_y), bar_w, bar_h, facecolor="none", edgecolor="#94a3b8", linewidth=0.45))
            tick_y = bar_y - max(0.004, 0.008 * h_scale)
            _draw_text(ax, bar_x0, tick_y, f"{gc_low:.0f}%", fontsize=6.0, ha="left", va="top", color="#475569")
            _draw_text(ax, bar_x0 + bar_w * 0.5, tick_y, f"{gc_mid:.0f}%", fontsize=6.0, ha="center", va="top", color="#475569")
            _draw_text(ax, bar_x0 + bar_w, tick_y, f"{gc_high:.0f}%", fontsize=6.0, ha="right", va="top", color="#475569")

    if subtitle:
        _draw_text(
            ax,
            0.02,
            0.012,
            subtitle,
            fontsize=6.6,
            color="#64748b",
            va="bottom",
            ha="left",
            wrap=True,
        )


def _resolve_lw_scale(journal_width: str) -> float:
    return 0.78 if journal_width == "single_col" else 1.0


def _draw_circular_on_axes(
    ax: plt.Axes,
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
    force_macro: bool = False,
    highlight_names: Optional[Set[str]] = None,
    panel_label: Optional[str] = None,
    semicircle: bool = False,
) -> None:
    """在指定极坐标投影 Axes 上绘制科研期刊级环形（或 180 度半圆扇形）多环进化树。"""
    n_leaves = len(leaves)
    depths = _compute_node_depths(root, req.use_branch_lengths)
    max_depth = max(depths.values()) or 1.0
    lw_scale = _resolve_lw_scale(req.journal_width)
    if n_leaves > 150:
        lw_scale *= 0.76

    macro_mode = force_macro or (req.label_density == "smart_query") or (
        req.label_density == "auto" and n_leaves > 80
    )

    if semicircle:
        start_deg = 4.0
        span_deg = 172.0
    else:
        gap_deg = 30.0 if n_leaves >= 10 else 20.0
        start_deg = gap_deg * 0.5
        span_deg = 360.0 - gap_deg
    angles: Dict[int, float] = {}
    for idx, leaf in enumerate(leaves):
        deg = start_deg + (idx + 0.5) * (span_deg / max(1, n_leaves))
        angles[id(leaf)] = math.radians(deg)

    def _assign_internal_angles(node: "PhyloNode") -> float:
        if node.is_leaf:
            return angles[id(node)]
        child_angs = [_assign_internal_angles(ch) for ch in node.children]
        mean_ang = sum(child_angs) / len(child_angs)
        angles[id(node)] = mean_ang
        return mean_ang

    _assign_internal_angles(root)

    # 中空圆心设计，舒展深层分支结构
    inner_hole_r = 0.14 if n_leaves > 40 else 0.05
    tree_r = 1.0
    tree_span_r = tree_r - inner_hole_r
    norm_r: Dict[int, float] = {
        nid: inner_hole_r + (d / max_depth) * tree_span_r for nid, d in depths.items()
    }
    tip_r = 1.012

    max_label_chars = max((len(display_labels.get(lf.name, lf.name)) for lf in leaves), default=10)
    base_font = 205.0 / max(24, n_leaves)
    if req.journal_width == "single_col":
        base_font *= 0.86
    label_font = max(4.6, min(8.0, base_font))

    if macro_mode:
        ring_start_r = tip_r + 0.025
    else:
        label_radial_span = min(0.84, max(0.22, max_label_chars * label_font * 0.0021))
        ring_start_r = tip_r + 0.04 + label_radial_span

    # 0. 同心演化距离参考虚线圆（iTOL Internal Tree Scale Rings）
    if req.use_branch_lengths and max_depth > 0 and n_leaves > 24:
        for frac in (0.33, 0.67):
            r_ring = inner_hole_r + frac * tree_span_r
            ax.add_patch(
                Arc(
                    (0.0, 0.0),
                    r_ring * 2,
                    r_ring * 2,
                    angle=0,
                    theta1=start_deg,
                    theta2=start_deg + span_deg,
                    edgecolor="#e2e8f0",
                    linewidth=0.45,
                    linestyle="--",
                    zorder=0.35,
                )
            )

    # 1. 单系支系柔和背景阴影扇区（仅绘制专属有色分类群，不为 Others 涂脏灰）
    if req.show_clade_shading and clades:
        deg_step = span_deg / max(1, n_leaves)
        for cl in clades:
            r_in = max(inner_hole_r + 0.01, norm_r[id(cl.node)] - 0.012)
            r_out = ring_start_r - 0.006
            t1 = start_deg + cl.leaf_start_idx * deg_step + 0.08
            t2 = start_deg + (cl.leaf_end_idx + 1) * deg_step - 0.08
            if t2 > t1 and r_out > r_in:
                ax.add_patch(
                    Wedge(
                        (0.0, 0.0),
                        r_out,
                        t1,
                        t2,
                        width=r_out - r_in,
                        facecolor=cl.color,
                        alpha=palette.clade_alpha,
                        edgecolor="none",
                        zorder=0.6,
                    )
                )

    # 2. 极坐标树枝（query_clade 模式下主干保持干练沉稳深炭黑；all_clades 下对单系科着柔和科色）
    eff_clade_mode = _resolve_effective_clade_mode(req)
    color_mono = macro_mode and eff_clade_mode == "all_clades"
    segments: List[List[Tuple[float, float]]] = []
    seg_colors: List[str] = []
    seg_widths: List[float] = []
    seg_styles: List[str] = []

    def _collect_branches(node: "PhyloNode") -> None:
        r_p = norm_r[id(node)]
        a_p = angles[id(node)]
        for ch in node.children:
            r_c = norm_r[id(ch)]
            a_c = angles[id(ch)]
            b_col, b_lw, b_ls = _subtree_branch_style(
                ch,
                node_metadata,
                taxon_colors,
                other_taxa,
                palette,
                lw_scale,
                rank_field=rank_field,
                color_monophyletic_branches=color_mono,
            )
            if abs(a_c - a_p) > 1e-5 and r_p > 1e-6:
                steps = max(4, int(abs(math.degrees(a_c - a_p)) * 1.15))
                arc_thetas = [a_p + (a_c - a_p) * (k / (steps - 1)) for k in range(steps)]
                pts = [(r_p * math.cos(t), r_p * math.sin(t)) for t in arc_thetas]
                for k in range(len(pts) - 1):
                    segments.append([pts[k], pts[k + 1]])
                    seg_colors.append(b_col)
                    seg_widths.append(b_lw)
                    seg_styles.append("-")
            segments.append(
                [(r_p * math.cos(a_c), r_p * math.sin(a_c)), (r_c * math.cos(a_c), r_c * math.sin(a_c))]
            )
            seg_colors.append(b_col)
            seg_widths.append(b_lw)
            seg_styles.append(b_ls)
            _collect_branches(ch)

    _collect_branches(root)
    if segments:
        ax.add_collection(
            LineCollection(
                segments,
                colors=seg_colors,
                linewidths=seg_widths,
                linestyles=seg_styles,
                capstyle="round",
                zorder=2,
            )
        )

    # 3. 轻柔叶端引导细线直连外环 + 精细标签
    guide_segments: List[List[Tuple[float, float]]] = []
    query_leaves_info: List[Tuple["PhyloNode", float, float]] = []
    for lf in leaves:
        r_c = norm_r[id(lf)]
        ang = angles[id(lf)]
        disp_text = display_labels.get(lf.name, lf.name)
        role, _, _, _ = _resolve_leaf_style(
            lf.name, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field
        )

        if macro_mode and r_c < ring_start_r - 0.008:
            guide_segments.append(
                [
                    (r_c * math.cos(ang), r_c * math.sin(ang)),
                    ((ring_start_r - 0.004) * math.cos(ang), (ring_start_r - 0.004) * math.sin(ang)),
                ]
            )

        if role == "query":
            query_leaves_info.append((lf, r_c, ang))
            if req.show_query_star:
                ax.scatter(
                    [r_c * math.cos(ang)],
                    [r_c * math.sin(ang)],
                    marker="*",
                    s=(36 if macro_mode else 46) * lw_scale,
                    color=palette.query_color,
                    edgecolor="white",
                    linewidth=0.35,
                    zorder=6,
                )

        if not macro_mode:
            if r_c < tip_r - 1e-4:
                ax.plot(
                    [r_c * math.cos(ang), tip_r * math.cos(ang)],
                    [r_c * math.sin(ang), tip_r * math.sin(ang)],
                    color="#cbd5e1",
                    linewidth=0.45 * lw_scale,
                    linestyle=":",
                    zorder=1,
                )
            deg = math.degrees(ang) % 360.0
            flip = 90.0 < deg < 270.0
            rot = deg + 180.0 if flip else deg
            ha = "right" if flip else "left"
            txt_r = tip_r + 0.025
            tx, ty = txt_r * math.cos(ang), txt_r * math.sin(ang)
            _draw_text(
                ax,
                tx,
                ty,
                disp_text,
                fontsize=label_font,
                fontweight="bold" if role == "query" else "normal",
                color=palette.query_text_color if role == "query" else ("#475569" if role == "outgroup" else "#0f172a"),
                rotation=rot,
                rotation_mode="anchor",
                ha=ha,
                va="center",
                zorder=5,
            )

    if guide_segments:
        ax.add_collection(
            LineCollection(
                guide_segments,
                colors="#cbd5e1",
                linewidths=0.28,
                linestyles=":",
                alpha=0.55,
                zorder=1,
            )
        )

    # 4. 内部节点分级支持率点
    if req.support_style != "none":
        dot_s_strong = 6.5 if n_leaves > 120 else 15.0 * lw_scale
        dot_s_mod = 5.2 if n_leaves > 120 else 12.5 * lw_scale
        dot_edge_w = 0.25 if n_leaves > 120 else 0.45
        mod_edge_w = 0.55 if n_leaves > 120 else 0.85

        def _draw_support(node: "PhyloNode") -> None:
            if not node.is_leaf and node is not root:
                txt, uf_val = _format_support_text(node.name)
                r_n = norm_r[id(node)]
                ang = angles[id(node)]
                nx, ny = r_n * math.cos(ang), r_n * math.sin(ang)
                if uf_val is not None and req.support_style in ("dots", "both"):
                    if uf_val >= 95.0:
                        ax.scatter(
                            [nx],
                            [ny],
                            s=dot_s_strong,
                            facecolor=palette.strong_dot_color,
                            edgecolor="white",
                            linewidth=dot_edge_w,
                            zorder=6,
                        )
                    elif uf_val >= 80.0:
                        ax.scatter(
                            [nx],
                            [ny],
                            s=dot_s_mod,
                            facecolor="#ffffff",
                            edgecolor=palette.moderate_dot_edge,
                            linewidth=mod_edge_w,
                            zorder=6,
                        )
                if not macro_mode and txt and req.support_style in ("text", "both"):
                    deg = math.degrees(ang) % 360.0
                    flip = 90.0 < deg < 270.0
                    rot = deg + 180.0 if flip else deg
                    _draw_text(
                        ax,
                        (r_n - 0.02) * math.cos(ang),
                        (r_n - 0.02) * math.sin(ang),
                        txt,
                        fontsize=max(4.2, label_font * 0.70),
                        color="#0f172a" if (uf_val or 0) >= 95.0 else "#475569",
                        rotation=rot,
                        rotation_mode="anchor",
                        ha="center",
                        va="bottom",
                        zorder=7,
                    )
            for ch in node.children:
                _draw_support(ch)

        _draw_support(root)

    # 5. 四层同心环轨道 (Family/Genus -> Host -> GC% Heatmap -> Size)
    ring_r = ring_start_r
    half_ang_deg = (span_deg / max(1, n_leaves)) * (0.50 if n_leaves > 100 else 0.45)
    wedge_ec = "none" if n_leaves > 100 else "white"
    wedge_lw = 0.0 if n_leaves > 100 else 0.35
    has_meta = bool(node_metadata)
    ring_mid_specs: List[Tuple[float, str, str]] = []

    if has_meta and req.show_genus_strip:
        w = 0.062
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            meta = node_metadata.get(lf.name, {})
            role = str(meta.get("role") or "").lower()
            t_val = str(meta.get(rank_field) or "").strip()
            if role == "query":
                col = palette.query_color
            elif role == "outgroup":
                col = palette.outgroup_color
            elif t_val in taxon_colors:
                col = taxon_colors[t_val]
            elif t_val in other_taxa:
                col = _OTHER_TAXON_COLOR
            else:
                col = _UNCLASSIFIED_LIGHT_COLOR
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + w,
                    deg - half_ang_deg,
                    deg + half_ang_deg,
                    width=w,
                    facecolor=col,
                    edgecolor=wedge_ec,
                    linewidth=wedge_lw,
                    zorder=3,
                )
            )
        ring_mid_specs.append((ring_r + w * 0.5, "Family" if rank_field == "family" else "Genus", "#0f172a"))
        ring_r += w + 0.015

    if has_meta and req.show_host_strip and leaf_phylum:
        w = 0.056
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            phylum = leaf_phylum.get(lf.name, "")
            col = phylum_colors.get(phylum, _UNCLASSIFIED_LIGHT_COLOR) if phylum else "#f8fafc"
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + w,
                    deg - half_ang_deg,
                    deg + half_ang_deg,
                    width=w,
                    facecolor=col,
                    edgecolor=wedge_ec,
                    linewidth=wedge_lw,
                    zorder=3,
                )
            )
        ring_mid_specs.append((ring_r + w * 0.5, "Host", "#334155"))
        ring_r += w + 0.015

    if has_meta and req.show_gc_bar:
        w = 0.046
        gc_low, gc_high = gc_range
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            gc = float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
            col_hex = gc_value_to_hex(gc, gc_low, gc_high, palette.name)
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + w,
                    deg - half_ang_deg,
                    deg + half_ang_deg,
                    width=w,
                    facecolor=col_hex,
                    edgecolor=wedge_ec,
                    linewidth=wedge_lw,
                    zorder=3,
                )
            )
        ring_mid_specs.append((ring_r + w * 0.5, "GC%", "#2171B5" if palette.name != "monochrome" else "#374151"))
        ring_r += w + 0.016

    if has_meta and req.show_genome_length:
        w_max = 0.115
        # 去除厚重灰框，仅留纤细基线圆弧与 50% 参考虚线圆弧
        ax.add_patch(
            Arc(
                (0.0, 0.0),
                ring_r * 2,
                ring_r * 2,
                angle=0,
                theta1=start_deg,
                theta2=start_deg + span_deg,
                edgecolor="#94a3b8",
                linewidth=0.5,
                zorder=2.5,
            )
        )
        mid_r = ring_r + w_max * 0.5
        ax.add_patch(
            Arc(
                (0.0, 0.0),
                mid_r * 2,
                mid_r * 2,
                angle=0,
                theta1=start_deg,
                theta2=start_deg + span_deg,
                edgecolor="#cbd5e1",
                linewidth=0.45,
                linestyle="--",
                zorder=2.5,
            )
        )
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            kb = float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0
            bar_w = max(0.006, (kb / max_len_kb) * w_max)
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + bar_w,
                    deg - half_ang_deg * 0.85,
                    deg + half_ang_deg * 0.85,
                    width=bar_w,
                    facecolor=palette.size_bar_color,
                    edgecolor="none",
                    zorder=3,
                )
            )
        ring_mid_specs.append((ring_r + w_max * 0.45, f"Size ({max_len_kb:.0f}kb)", palette.size_bar_color))
        ring_r += w_max + 0.016

    # 右侧开口处采用严格零交叉的正交 L 形阶梯折线 + 环端微锚点 + 水平精排轨道名
    x_label_col = ring_r + 0.11
    if ring_mid_specs:
        ring_radii = [spec[0] for spec in ring_mid_specs]
        elbow_polylines = compute_ring_elbow_leaders(ring_radii, start_deg=start_deg, x_label=x_label_col)
        for (_, r_title, r_col), poly in zip(ring_mid_specs, elbow_polylines, strict=True):
            xs = [pt[0] for pt in poly]
            ys = [pt[1] for pt in poly]
            ax.plot(xs, ys, color="#64748b", linewidth=0.58, solid_joinstyle="miter", zorder=7)
            ax.scatter([xs[0]], [ys[0]], s=5.0, facecolor="#475569", edgecolor="none", zorder=8)
            _draw_text(
                ax,
                x_label_col,
                ys[-1],
                r_title,
                fontsize=5.9,
                fontweight="bold",
                color=r_col,
                ha="left",
                va="center",
                zorder=8,
            )

    # 6. Panel b 局部聚焦扇区标识弧线 + Clade b 标注
    max_focus_arc_r = ring_r
    if highlight_names:
        hi_degs = sorted(
            math.degrees(angles[id(lf)]) for lf in leaves if lf.name in highlight_names
        )
        if hi_degs:
            clusters: List[List[float]] = [[hi_degs[0]]]
            for d in hi_degs[1:]:
                if d - clusters[-1][-1] <= 18.0:
                    clusters[-1].append(d)
                else:
                    clusters.append([d])
            arc_r = ring_r + 0.016
            max_focus_arc_r = arc_r + 0.04
            main_cluster = max(clusters, key=len)
            for cl_degs in clusters:
                t1 = max(start_deg, cl_degs[0] - 1.5)
                t2 = min(start_deg + span_deg, cl_degs[-1] + 1.5)
                if t2 > t1:
                    ax.add_patch(
                        Arc(
                            (0.0, 0.0),
                            arc_r * 2,
                            arc_r * 2,
                            angle=0,
                            theta1=t1,
                            theta2=t2,
                            edgecolor="#1e293b",
                            linewidth=1.5,
                            linestyle="-",
                            zorder=7,
                        )
                    )
            # 放在聚焦弧起点外侧空白区，避开 Query 放射引出线避免交叉
            clade_lbl_r = arc_r + 0.03
            lbl_ang = math.radians(max(start_deg + 1.0, main_cluster[0] - 2.0))
            _draw_text(
                ax,
                clade_lbl_r * math.cos(lbl_ang),
                clade_lbl_r * math.sin(lbl_ang),
                f"Clade b (n={len(highlight_names)})",
                fontsize=6.5,
                fontweight="bold",
                color="#1e293b",
                ha="left" if math.cos(lbl_ang) >= 0 else "right",
                va="bottom" if math.sin(lbl_ang) >= 0 else "top",
                zorder=9,
            )

    # 7. 宏观模式最外圈 Query 株去贴纸防碰撞引出线标注 + 非对称紧致包围盒追踪
    base_pad = 0.07
    x_min = -(ring_r + base_pad)
    x_max = max(ring_r + base_pad, x_label_col + 0.25 if ring_mid_specs else ring_r + base_pad)
    y_min = -0.18 if semicircle else -(ring_r + base_pad)
    y_max = ring_r + base_pad
    if highlight_names:
        y_max = max(y_max, max_focus_arc_r + 0.06)

    if macro_mode and query_leaves_info:
        query_leaves_info.sort(key=lambda item: angles[id(item[0])])
        raw_degs = [math.degrees(item[2]) for item in query_leaves_info]
        nudged_degs = _deconflict_query_angles(
            raw_degs,
            min_deg=start_deg + 1.0,
            max_deg=start_deg + span_deg - 1.0,
            min_gap_deg=4.2 if semicircle else 5.4,
        )
        r_inner_anchor = ring_r + 0.008
        r_callout_end = ring_r + 0.125

        for (qlf, r_leaf, ang_true), deg_out in zip(query_leaves_info, nudged_degs, strict=True):
            ang_out = math.radians(deg_out)
            ax.plot(
                [r_leaf * math.cos(ang_true), r_inner_anchor * math.cos(ang_true)],
                [r_leaf * math.sin(ang_true), r_inner_anchor * math.sin(ang_true)],
                color=palette.query_color,
                linewidth=0.5,
                linestyle=":",
                alpha=0.70,
                zorder=4,
            )
            ax.plot(
                [r_inner_anchor * math.cos(ang_true), r_callout_end * math.cos(ang_out)],
                [r_inner_anchor * math.sin(ang_true), r_callout_end * math.sin(ang_out)],
                color=palette.query_color,
                linewidth=0.85,
                linestyle="-",
                zorder=7,
            )
            if req.show_query_star:
                ax.scatter(
                    [r_inner_anchor * math.cos(ang_true)],
                    [r_inner_anchor * math.sin(ang_true)],
                    marker="*",
                    s=44,
                    color=palette.query_color,
                    edgecolor="white",
                    linewidth=0.35,
                    zorder=8,
                )
            flip = 90.0 < (deg_out % 360.0) < 270.0
            rot = (deg_out + 180.0) if flip else deg_out
            ha = "right" if flip else "left"
            lbl = display_labels.get(qlf.name, qlf.name)
            txt_r = r_callout_end + 0.018
            tx = txt_r * math.cos(ang_out)
            ty = txt_r * math.sin(ang_out)
            _draw_text(
                ax,
                tx,
                ty,
                lbl,
                fontsize=6.7 if panel_label else 7.2,
                fontweight="bold",
                color=palette.query_text_color,
                rotation=rot,
                rotation_mode="anchor",
                ha=ha,
                va="center",
                zorder=8,
            )
            # 精确估算旋转文本末端包络，仅在有引出线的象限扩展画布边界
            est_len = min(0.45, max(0.18, len(lbl) * 0.016))
            end_x = (txt_r + est_len) * math.cos(ang_out)
            end_y = (txt_r + est_len) * math.sin(ang_out)
            x_min = min(x_min, end_x - 0.04)
            x_max = max(x_max, end_x + 0.04)
            y_min = min(y_min, end_y - 0.04)
            y_max = max(y_max, end_y + 0.04)

    # 保持 aspect="equal" 下居中对齐（取最大半跨或非对称紧凑框）
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    if panel_label:
        _draw_text(
            ax,
            x_min + (x_max - x_min) * 0.02,
            y_max - (y_max - y_min) * 0.02,
            panel_label,
            fontsize=13.5,
            fontweight="bold",
            color="#0f172a",
            ha="left",
            va="top",
            zorder=10,
        )

    if req.use_branch_lengths and max_depth > 0:
        sb_val, sb_text = compute_nice_scale_bar(max_depth)
        sb_len = (sb_val / max_depth) * tree_span_r
        sb_x = x_min + 0.06
        sb_y = -0.10 if semicircle else (y_min + 0.07)
        ax.plot([sb_x, sb_x + sb_len], [sb_y, sb_y], color="#0f172a", linewidth=1.15)
        ax.plot([sb_x, sb_x], [sb_y - 0.012, sb_y + 0.012], color="#0f172a", linewidth=0.95)
        ax.plot([sb_x + sb_len, sb_x + sb_len], [sb_y - 0.012, sb_y + 0.012], color="#0f172a", linewidth=0.95)
        _draw_text(
            ax,
            sb_x + sb_len * 0.5,
            sb_y + 0.024,
            f"{sb_text} substitutions/site",
            fontsize=6.7,
            ha="center",
            color="#334155",
        )


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

    y_pos: Dict[int, float] = {}
    for idx, lf in enumerate(leaves):
        y_pos[id(lf)] = float(n_leaves - 1 - idx)

    def _assign_y(node: "PhyloNode") -> float:
        if node.is_leaf:
            return y_pos[id(node)]
        ys = [_assign_y(ch) for ch in node.children]
        val = sum(ys) / len(ys)
        y_pos[id(node)] = val
        return val

    _assign_y(root)

    max_chars = max((len(display_labels.get(lf.name, lf.name)) for lf in leaves), default=12)
    label_pad = max_depth * 0.032
    right_margin = max_depth * max(0.45, min(2.05, max_chars * 0.024))
    label_font = 6.2 if dense_mode else max(6.4, min(8.2, 240.0 / max(24, n_leaves)))
    if req.journal_width == "single_col":
        label_font = max(5.2, label_font * 0.88)

    # 1. 单系支系柔和背景阴影（仅专属有色分类，绝不画脏灰条）
    if req.show_clade_shading and clades:
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
            if not strip_axes:
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

    # 2. 主树分支线段
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

    # 3. 叶节点点线对齐与去贴纸标签
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
        if role == "query" and req.show_query_star:
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

    # 4. 内部节点支持率（非密集模式直接显示 >= 70% 支持率数值与精细圆点）
    if req.support_style != "none":
        dot_s_strong = 10.0 if dense_mode else 12.0 * lw_scale
        dot_s_mod = 8.0 if dense_mode else 10.0 * lw_scale

        def _draw_sup(node: "PhyloNode") -> None:
            if not node.is_leaf and node is not root:
                txt, uf_val = _format_support_text(node.name)
                xn = depths[id(node)]
                yn = y_pos[id(node)]
                if uf_val is not None and req.support_style in ("dots", "both"):
                    if uf_val >= 95.0:
                        ax_tree.scatter(
                            [xn],
                            [yn],
                            s=dot_s_strong,
                            facecolor=palette.strong_dot_color,
                            edgecolor="white",
                            linewidth=0.4,
                            zorder=6,
                        )
                    elif uf_val >= 80.0:
                        ax_tree.scatter(
                            [xn],
                            [yn],
                            s=dot_s_mod,
                            facecolor="#ffffff",
                            edgecolor=palette.moderate_dot_edge,
                            linewidth=0.75,
                            zorder=6,
                        )
                if txt and (
                    req.support_style in ("text", "both")
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

    extra_bracket = max_depth * 0.14 if (req.show_clade_shading and clades and not strip_axes) else 0.0
    ax_tree.set_xlim(-max_depth * 0.04, max_depth + label_pad + right_margin + extra_bracket)
    y_min_lim = -1.15
    y_max_lim = n_leaves - 0.15
    ax_tree.set_ylim(y_min_lim, y_max_lim)
    ax_tree.axis("off")

    if panel_label:
        _draw_text(
            ax_tree,
            -max_depth * 0.035,
            y_max_lim - 0.05,
            panel_label,
            fontsize=13.5,
            fontweight="bold",
            color="#0f172a",
            ha="left",
            va="top",
            zorder=10,
        )

    if req.use_branch_lengths and max_depth > 0:
        sb_val, sb_text = compute_nice_scale_bar(max_depth)
        ax_tree.plot([0.0, sb_val], [-0.68, -0.68], color="#0f172a", linewidth=1.2 * lw_scale)
        ax_tree.plot([0.0, 0.0], [-0.80, -0.56], color="#0f172a", linewidth=0.95 * lw_scale)
        ax_tree.plot([sb_val, sb_val], [-0.80, -0.56], color="#0f172a", linewidth=0.95 * lw_scale)
        _draw_text(
            ax_tree,
            sb_val * 0.5,
            -0.44,
            f"{sb_text} substitutions/site",
            fontsize=6.8,
            ha="center",
            color="#334155",
        )

    latin_font = resolve_latin_font()

    # 5. 右侧轨道：非密集模式下合并垂直属色条 + 直接标注斜体属名
    if "taxon" in strip_axes:
        ax_s = strip_axes["taxon"]
        ax_s.set_ylim(y_min_lim, y_max_lim)
        ax_s.axis("off")
        rank_hdr = "Family" if rank_field == "family" else "Genus"
        if not dense_mode:
            ax_s.set_xlim(0, 1.85)
            ax_s.set_title(rank_hdr, fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#0f172a", pad=4, loc="left")

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

            runs: List[Tuple[int, int, str, str]] = []
            for idx, lf in enumerate(leaves):
                t_lbl, t_col = _leaf_label_key(lf)
                if runs and runs[-1][2] == t_lbl and runs[-1][3] == t_col:
                    prev_s, _, _, _ = runs[-1]
                    runs[-1] = (prev_s, idx, t_lbl, t_col)
                else:
                    runs.append((idx, idx, t_lbl, t_col))

            for s_idx, e_idx, t_lbl, t_col in runs:
                y_top_bar = y_pos[id(leaves[s_idx])] + 0.38
                y_bot_bar = y_pos[id(leaves[e_idx])] - 0.38
                ax_s.add_patch(
                    Rectangle(
                        (0.02, y_bot_bar),
                        0.15,
                        y_top_bar - y_bot_bar,
                        facecolor=t_col,
                        edgecolor="white",
                        linewidth=0.35,
                    )
                )
                is_italic = is_formal_taxon_name(t_lbl)
                _draw_text(
                    ax_s,
                    0.23,
                    (y_top_bar + y_bot_bar) * 0.5,
                    t_lbl,
                    fontsize=max(5.6, label_font * 0.88),
                    fontstyle="italic" if is_italic else "normal",
                    fontweight="bold" if t_lbl == "Query" else "normal",
                    color=palette.query_text_color if t_lbl == "Query" else ("#64748b" if t_lbl in ("Unclassified", "Outgroup") else "#1e293b"),
                    va="center",
                    ha="left",
                )
        else:
            ax_s.set_xlim(0, 1)
            ax_s.set_title(rank_hdr, fontsize=7.5, fontweight="bold", fontfamily=latin_font, color="#0f172a", pad=4)
            for lf in leaves:
                y_tip = y_pos[id(lf)]
                meta = node_metadata.get(lf.name, {})
                role = str(meta.get("role") or "").lower()
                t_val = str(meta.get(rank_field) or "").strip()
                if role == "query":
                    col = palette.query_color
                elif role == "outgroup":
                    col = palette.outgroup_color
                elif t_val in taxon_colors:
                    col = taxon_colors[t_val]
                elif t_val in other_taxa:
                    col = _OTHER_TAXON_COLOR
                else:
                    col = _UNCLASSIFIED_LIGHT_COLOR
                ax_s.add_patch(Rectangle((0.08, y_tip - 0.36), 0.84, 0.72, facecolor=col, edgecolor="white", linewidth=0.25))

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
                _draw_text(
                    ax_g,
                    0.72,
                    y_tip,
                    f"{gc:.1f}%",
                    fontsize=max(4.8, label_font * 0.72),
                    va="center",
                    color="#334155",
                )

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
                _draw_text(
                    ax_l,
                    kb + max_len_kb * 0.04,
                    y_tip,
                    f"{kb:.1f}",
                    fontsize=max(4.8, label_font * 0.72),
                    va="center",
                    color="#334155",
                )
        ax_l.plot([0.0, max_len_kb], [-0.62, -0.62], color="#94a3b8", linewidth=0.7)
        _draw_text(ax_l, 0.0, -0.95, "0", fontsize=5.6, ha="left", color="#64748b")
        _draw_text(ax_l, max_len_kb, -0.95, f"{max_len_kb:.0f}", fontsize=5.6, ha="center", color="#64748b")


def _render_circular(
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
    if req.journal_width == "single_col":
        fig_side = max(7.2, min(9.8, 6.4 + n_leaves * 0.04))
    elif req.journal_width == "double_col":
        fig_side = max(9.6, min(13.8, 8.2 + n_leaves * 0.05))
    else:
        fig_side = max(9.5, min(13.2, 8.4 + n_leaves * 0.02))

    fig = plt.figure(figsize=(fig_side * 1.32, fig_side), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[3.65, 1.25], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    ax_leg = fig.add_subplot(gs[0, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    has_meta = bool(node_metadata)
    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0
    gc_range = _compute_gc_range(leaves, node_metadata)

    _draw_circular_on_axes(
        ax,
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
    )
    if req.show_figure_title and req.title:
        fig.suptitle(
            req.title,
            fontsize=11.0 if req.journal_width != "single_col" else 9.6,
            fontweight="bold",
            fontfamily=pick_font_family(req.title),
            color="#0f172a",
            y=0.975,
        )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.93 if (req.show_figure_title and req.title) else 0.97, bottom=0.03)
    return fig


def _render_half_circular(
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
    """180 度上半圆扇形宏观多环进化树，宽幅双栏排版比例契合顶刊横版版面。"""
    n_leaves = len(leaves)
    if req.journal_width == "single_col":
        fig_w, fig_h = 9.8, 6.2
    elif req.journal_width == "double_col":
        fig_w, fig_h = 15.2, 8.2
    else:
        fig_w = max(13.2, min(15.6, 12.0 + n_leaves * 0.008))
        fig_h = max(6.8, fig_w * 0.52)

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[3.9, 1.25], wspace=0.035)
    ax = fig.add_subplot(gs[0, 0])
    ax_leg = fig.add_subplot(gs[0, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    has_meta = bool(node_metadata)
    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0
    gc_range = _compute_gc_range(leaves, node_metadata)

    _draw_circular_on_axes(
        ax,
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
        semicircle=True,
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
    fig.subplots_adjust(left=0.02, right=0.98, top=0.93 if (req.show_figure_title and req.title) else 0.97, bottom=0.03)
    return fig


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
