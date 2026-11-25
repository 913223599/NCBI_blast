# -*- coding: utf-8 -*-
"""出版级进化树环形与 180 度半圆宽幅树布局渲染模块。"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Arc, Wedge

from ..models.schemas import PublicationFigureRequest
from .clade_detector import MonophyleticClade
from .legend_panel import _draw_legend_panel, _resolve_lw_scale
from .publication_palettes import (
    JournalPalette,
    compute_nice_scale_bar,
    compute_ring_elbow_leaders,
    gc_value_to_hex,
    pick_font_family,
)
from .renderer_helpers import (
    _OTHER_TAXON_COLOR,
    _UNCLASSIFIED_LIGHT_COLOR,
    _compute_gc_range,
    _compute_node_depths,
    _deconflict_query_angles,
    _draw_text,
    _format_support_text,
    _resolve_effective_clade_mode,
    _resolve_leaf_style,
    _subtree_branch_style,
)

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode


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
