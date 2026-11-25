# -*- coding: utf-8 -*-
"""出版级进化树流式图例面板与线宽比例计算模块。"""
from __future__ import annotations

from collections import Counter
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from ..models.schemas import PublicationFigureRequest
from .clade_detector import MonophyleticClade
from .publication_palettes import (
    JournalPalette,
    gc_value_to_hex,
    resolve_latin_font,
)
from .renderer_helpers import (
    _OTHER_TAXON_COLOR,
    _UNCLASSIFIED_LIGHT_COLOR,
    _draw_section_header,
    _draw_text,
    _resolve_effective_clade_mode,
    _style_legend_entries,
)

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode


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
