# -*- coding: utf-8 -*-
"""
PublicationTreeRenderer - 方案 C：离线本地发表级多环/矩形进化树矢量渲染器
使用无头 Matplotlib (Agg) 直接产出可直接投稿/导入 Illustrator 的矢量 PDF/SVG 及高分辨率 PNG：
- 环形多环布局 (Circular): 留出扇区开口标注外圈轨道，含 ICTV 属色带环 + 基因组大小柱环 + GC% 环 + 右侧独立科研图例；
- 矩形多轨布局 (Rectangular): 梯形化树 + 虚线对齐引导线 + 标签高亮底色 + 并列 3 轨数值条带 + 演化距离标尺与方法学注脚。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle, Wedge

from ..models.schemas import PublicationFigureRequest
from .itol_generator import _PALETTE
from .label_formatter import enrich_node_metadata, format_leaf_label

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode

_DEFAULT_OUTGROUP_COLOR = "#64748b"
_QUERY_COLOR = "#dc2626"
_QUERY_BG_COLOR = "#fee2e2"
_UNCLASSIFIED_COLOR = "#94a3b8"
_STRONG_DOT_COLOR = "#0f766e"
_MOD_DOT_COLOR = "#60a5fa"


def _configure_matplotlib_fonts() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
        "Arial",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["pdf.fonttype"] = 42


def _ladderize(node: PhyloNode, ascending: bool = True) -> int:
    """原地按子树叶子数量梯形化节点顺序，返回子树叶数。"""
    if node.is_leaf:
        return 1
    sized = [(ch, _ladderize(ch, ascending=ascending)) for ch in node.children]
    sized.sort(key=lambda item: item[1], reverse=not ascending)
    node.children = [item[0] for item in sized]
    return sum(item[1] for item in sized)


def _collect_leaves(node: PhyloNode) -> List[PhyloNode]:
    out: List[PhyloNode] = []

    def _walk(cur: PhyloNode) -> None:
        if cur.is_leaf:
            out.append(cur)
        else:
            for ch in cur.children:
                _walk(ch)

    _walk(node)
    return out


def _build_genus_palette(
    leaves: List[PhyloNode],
    node_metadata: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    genus_colors: Dict[str, str] = {}
    idx = 0
    for leaf in leaves:
        meta = node_metadata.get(leaf.name, {})
        genus = str(meta.get("genus") or "").strip()
        if genus and genus not in genus_colors:
            genus_colors[genus] = _PALETTE[idx % len(_PALETTE)]
            idx += 1
    return genus_colors


def _resolve_leaf_style(
    name: str,
    node_metadata: Dict[str, Dict[str, Any]],
    genus_colors: Dict[str, str],
) -> Tuple[str, str, float, str]:
    """返回 (role, color, linewidth, linestyle)。"""
    meta = node_metadata.get(name, {})
    role = str(meta.get("role") or "").strip().lower()
    genus = str(meta.get("genus") or "").strip()
    if role == "query":
        return "query", _QUERY_COLOR, 1.9, "-"
    if role == "outgroup":
        return "outgroup", _DEFAULT_OUTGROUP_COLOR, 1.15, "--"
    if genus and genus in genus_colors:
        return "ref", genus_colors[genus], 1.2, "-"
    return "ref", "#334155", 1.1, "-"


def _subtree_dominant_branch_style(
    node: PhyloNode,
    node_metadata: Dict[str, Dict[str, Any]],
    genus_colors: Dict[str, str],
) -> Tuple[str, float, str]:
    """若子树全部叶子同属一个分类/角色则返回对应样式，否则返回默认深灰实线。"""
    if node.is_leaf:
        _, color, lw, ls = _resolve_leaf_style(node.name, node_metadata, genus_colors)
        return color, lw, ls

    sub_leaves = _collect_leaves(node)
    styles = {_resolve_leaf_style(lf.name, node_metadata, genus_colors)[1:] for lf in sub_leaves}
    if len(styles) == 1:
        return next(iter(styles))
    return "#334155", 1.05, "-"


def _compute_node_depths(
    root: PhyloNode,
    use_branch_lengths: bool,
) -> Dict[int, float]:
    depths: Dict[int, float] = {id(root): 0.0}

    def _walk(cur: PhyloNode, cur_x: float) -> None:
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


def _draw_legend_panel(
    ax: plt.Axes,
    genus_colors: Dict[str, str],
    has_query: bool,
    has_outgroup: bool,
    support_style: str,
    req: PublicationFigureRequest,
    has_meta: bool,
    max_len_kb: float,
    subtitle: str,
) -> None:
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    handles: List[Any] = []
    if has_query:
        handles.append(Patch(facecolor=_QUERY_COLOR, edgecolor="none", label="Query Phage"))
    if has_outgroup:
        handles.append(Patch(facecolor=_DEFAULT_OUTGROUP_COLOR, edgecolor="none", label="Outgroup"))
    for genus, color in list(genus_colors.items())[:18]:
        handles.append(Patch(facecolor=color, edgecolor="none", label=genus))

    y_cursor = 0.96
    if handles:
        ax.text(0.02, y_cursor, "ICTV Taxonomy / Role", fontsize=9.5, fontweight="bold", color="#0f172a", va="top")
        leg1 = ax.legend(
            handles=handles,
            loc="upper left",
            bbox_to_anchor=(0.0, y_cursor - 0.03),
            frameon=False,
            fontsize=7.8,
            handlelength=1.2,
            handleheight=0.85,
            labelspacing=0.35,
            borderaxespad=0.0,
        )
        ax.add_artist(leg1)
        y_cursor -= 0.06 + 0.032 * len(handles)

    if support_style in ("dots", "both"):
        y_cursor = min(y_cursor, 0.42)
        sup_handles = [
            Line2D([0], [0], marker="o", color="none", markerfacecolor=_STRONG_DOT_COLOR, markersize=5.5, label="UFBoot >= 95% (Strong)"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor=_MOD_DOT_COLOR, markersize=4.8, label="80% <= UFBoot < 95%"),
        ]
        ax.text(0.02, y_cursor, "Branch Support", fontsize=9.2, fontweight="bold", color="#0f172a", va="top")
        leg2 = ax.legend(
            handles=sup_handles,
            loc="upper left",
            bbox_to_anchor=(0.0, y_cursor - 0.03),
            frameon=False,
            fontsize=7.5,
            borderaxespad=0.0,
        )
        ax.add_artist(leg2)
        y_cursor -= 0.13

    if has_meta and (req.show_genome_length or req.show_gc_bar):
        y_cursor = min(y_cursor, 0.25)
        ring_handles: List[Any] = []
        if req.show_genome_length:
            ring_handles.append(Patch(facecolor="#0ea5e9", edgecolor="none", label=f"Genome Size (0 - {max_len_kb:.0f} kb)"))
        if req.show_gc_bar:
            ring_handles.append(Patch(facecolor="#10b981", edgecolor="none", label="GC Content (0 - 100%)"))
        ax.text(0.02, y_cursor, "Annotation Tracks", fontsize=9.2, fontweight="bold", color="#0f172a", va="top")
        leg3 = ax.legend(
            handles=ring_handles,
            loc="upper left",
            bbox_to_anchor=(0.0, y_cursor - 0.03),
            frameon=False,
            fontsize=7.5,
            borderaxespad=0.0,
        )
        ax.add_artist(leg3)

    if subtitle:
        ax.text(
            0.02,
            0.02,
            subtitle,
            fontsize=7.2,
            color="#475569",
            va="bottom",
            ha="left",
            wrap=True,
        )


def _render_circular(
    root: PhyloNode,
    leaves: List[PhyloNode],
    node_metadata: Dict[str, Dict[str, Any]],
    display_labels: Dict[str, str],
    genus_colors: Dict[str, str],
    req: PublicationFigureRequest,
    subtitle: str,
) -> plt.Figure:
    n_leaves = len(leaves)
    depths = _compute_node_depths(root, req.use_branch_lengths)
    max_depth = max(depths.values()) or 1.0

    # 预留右侧 26° 扇区空白以放置多环标题
    gap_deg = 26.0 if n_leaves >= 6 else 18.0
    start_deg = gap_deg * 0.5
    span_deg = 360.0 - gap_deg
    angles: Dict[int, float] = {}
    for idx, leaf in enumerate(leaves):
        deg = start_deg + (idx + 0.5) * (span_deg / max(1, n_leaves))
        angles[id(leaf)] = math.radians(deg)

    def _assign_internal_angles(node: PhyloNode) -> float:
        if node.is_leaf:
            return angles[id(node)]
        child_angs = [_assign_internal_angles(ch) for ch in node.children]
        mean_ang = sum(child_angs) / len(child_angs)
        angles[id(node)] = mean_ang
        return mean_ang

    _assign_internal_angles(root)

    # 径向尺度规范化：树占半径 0.0 ~ 1.0，再向外排列标签与可选外圈环带
    tree_r = 1.0
    norm_r: Dict[int, float] = {
        nid: (d / max_depth) * tree_r for nid, d in depths.items()
    }

    fig_side = max(9.5, min(14.5, 8.2 + n_leaves * 0.08))
    fig = plt.figure(figsize=(fig_side * 1.28, fig_side), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[3.6, 1.18], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    ax_leg = fig.add_subplot(gs[0, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    # 绘制极坐标树枝（径向线段 + 同心圆弧）
    segments: List[List[Tuple[float, float]]] = []
    seg_colors: List[str] = []
    seg_widths: List[float] = []
    seg_styles: List[str] = []

    def _collect_branches(node: PhyloNode) -> None:
        r_p = norm_r[id(node)]
        a_p = angles[id(node)]
        for ch in node.children:
            r_c = norm_r[id(ch)]
            a_c = angles[id(ch)]
            b_col, b_lw, b_ls = _subtree_dominant_branch_style(ch, node_metadata, genus_colors)
            # 圆弧段：沿半径 r_p 从 a_p 连到 a_c
            if abs(a_c - a_p) > 1e-5 and r_p > 1e-6:
                steps = max(4, int(abs(math.degrees(a_c - a_p)) * 1.2))
                arc_thetas = np.linspace(a_p, a_c, steps)
                pts = [(r_p * math.cos(t), r_p * math.sin(t)) for t in arc_thetas]
                for k in range(len(pts) - 1):
                    segments.append([pts[k], pts[k + 1]])
                    seg_colors.append(b_col)
                    seg_widths.append(b_lw)
                    seg_styles.append("-")
            # 径向伸长段：角度 a_c，半径 r_p -> r_c
            segments.append(
                [(r_p * math.cos(a_c), r_p * math.sin(a_c)), (r_c * math.cos(a_c), r_c * math.sin(a_c))]
            )
            seg_colors.append(b_col)
            seg_widths.append(b_lw)
            seg_styles.append(b_ls)
            _collect_branches(ch)

    _collect_branches(root)
    if segments:
        lc = LineCollection(
            segments,
            colors=seg_colors,
            linewidths=seg_widths,
            linestyles=seg_styles,
            capstyle="round",
            zorder=2,
        )
        ax.add_collection(lc)

    # 叶节点引线（到统一半径 1.02）+ 叶子点 + 径向标签
    tip_r = 1.02
    max_label_chars = max((len(display_labels.get(lf.name, lf.name)) for lf in leaves), default=10)
    label_font = max(4.8, min(8.2, 220.0 / max(24, n_leaves)))
    for lf in leaves:
        r_c = norm_r[id(lf)]
        ang = angles[id(lf)]
        disp_text = display_labels.get(lf.name, lf.name)
        role, col, _, _ = _resolve_leaf_style(lf.name, node_metadata, genus_colors)
        if r_c < tip_r - 1e-4:
            ax.plot(
                [r_c * math.cos(ang), tip_r * math.cos(ang)],
                [r_c * math.sin(ang), tip_r * math.sin(ang)],
                color="#cbd5e1",
                linewidth=0.45,
                linestyle=":",
                zorder=1,
            )
        ax.scatter(
            [r_c * math.cos(ang)],
            [r_c * math.sin(ang)],
            s=16 if role == "query" else 9,
            color=col,
            zorder=4,
        )

        # 径向标签排布，左半圆自动翻面保证可读性
        deg = math.degrees(ang) % 360.0
        flip = 90.0 < deg < 270.0
        rot = deg + 180.0 if flip else deg
        ha = "right" if flip else "left"
        txt_r = tip_r + 0.025
        tx, ty = txt_r * math.cos(ang), txt_r * math.sin(ang)
        bbox_kw = (
            {"boxstyle": "round,pad=0.14", "facecolor": _QUERY_BG_COLOR, "edgecolor": "none"}
            if role == "query"
            else None
        )
        ax.text(
            tx,
            ty,
            disp_text,
            fontsize=label_font,
            fontweight="bold" if role == "query" else "normal",
            color="#991b1b" if role == "query" else ("#475569" if role == "outgroup" else "#0f172a"),
            rotation=rot,
            rotation_mode="anchor",
            ha=ha,
            va="center",
            bbox=bbox_kw,
            zorder=5,
        )

    # 绘制内部节点支持率（圆点/文本）
    if req.support_style != "none":
        def _draw_support(node: PhyloNode) -> None:
            if not node.is_leaf and node is not root:
                txt, uf_val = _format_support_text(node.name)
                r_n = norm_r[id(node)]
                ang = angles[id(node)]
                nx, ny = r_n * math.cos(ang), r_n * math.sin(ang)
                if uf_val is not None and req.support_style in ("dots", "both"):
                    if uf_val >= 95.0:
                        ax.scatter([nx], [ny], s=18, color=_STRONG_DOT_COLOR, edgecolor="white", linewidth=0.4, zorder=6)
                    elif uf_val >= 80.0:
                        ax.scatter([nx], [ny], s=13, color=_MOD_DOT_COLOR, edgecolor="white", linewidth=0.35, zorder=6)
                if txt and req.support_style in ("text", "both"):
                    deg = math.degrees(ang) % 360.0
                    flip = 90.0 < deg < 270.0
                    rot = deg + 180.0 if flip else deg
                    ax.text(
                        (r_n - 0.02) * math.cos(ang),
                        (r_n - 0.02) * math.sin(ang),
                        txt,
                        fontsize=max(4.4, label_font * 0.72),
                        color="#0f766e" if (uf_val or 0) >= 95.0 else "#475569",
                        rotation=rot,
                        rotation_mode="anchor",
                        ha="center",
                        va="bottom",
                        zorder=7,
                    )
            for ch in node.children:
                _draw_support(ch)

        _draw_support(root)

    # 动态预留标签宽度，在其外围叠加同心多环轨道
    label_radial_span = min(0.88, max(0.24, max_label_chars * label_font * 0.0021))
    ring_r = tip_r + 0.04 + label_radial_span
    half_ang_deg = (span_deg / max(1, n_leaves)) * 0.44

    has_meta = bool(node_metadata)
    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0

    def _draw_ring_title(radius_mid: float, title_text: str, color: str) -> None:
        ax.text(
            radius_mid,
            0.0,
            title_text,
            fontsize=6.4,
            fontweight="bold",
            color=color,
            rotation=90,
            ha="center",
            va="center",
            zorder=8,
        )

    if has_meta and req.show_genus_strip:
        w = 0.065
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            meta = node_metadata.get(lf.name, {})
            role = str(meta.get("role") or "").lower()
            genus = str(meta.get("genus") or "").strip()
            col = (
                _QUERY_COLOR
                if role == "query"
                else (_DEFAULT_OUTGROUP_COLOR if role == "outgroup" else genus_colors.get(genus, _UNCLASSIFIED_COLOR))
            )
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + w,
                    deg - half_ang_deg,
                    deg + half_ang_deg,
                    width=w,
                    facecolor=col,
                    edgecolor="white",
                    linewidth=0.3,
                    zorder=3,
                )
            )
        _draw_ring_title(ring_r + w * 0.5, "Genus", "#1e293b")
        ring_r += w + 0.02

    if has_meta and req.show_genome_length:
        w_max = 0.13
        # 淡灰底轨
        ax.add_patch(
            Wedge(
                (0.0, 0.0),
                ring_r + w_max,
                start_deg,
                start_deg + span_deg,
                width=w_max,
                facecolor="#f8fafc",
                edgecolor="#e2e8f0",
                linewidth=0.4,
                zorder=2,
            )
        )
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            kb = float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0
            bar_w = max(0.008, (kb / max_len_kb) * w_max)
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + bar_w,
                    deg - half_ang_deg * 0.85,
                    deg + half_ang_deg * 0.85,
                    width=bar_w,
                    facecolor="#0ea5e9",
                    edgecolor="none",
                    zorder=3,
                )
            )
        _draw_ring_title(ring_r + w_max * 0.5, f"Size ({max_len_kb:.0f}kb)", "#0369a1")
        ring_r += w_max + 0.02

    if has_meta and req.show_gc_bar:
        w_max = 0.095
        ax.add_patch(
            Wedge(
                (0.0, 0.0),
                ring_r + w_max,
                start_deg,
                start_deg + span_deg,
                width=w_max,
                facecolor="#f8fafc",
                edgecolor="#e2e8f0",
                linewidth=0.4,
                zorder=2,
            )
        )
        for lf in leaves:
            deg = math.degrees(angles[id(lf)])
            gc = float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
            bar_w = max(0.005, min(1.0, gc / 100.0) * w_max)
            ax.add_patch(
                Wedge(
                    (0.0, 0.0),
                    ring_r + bar_w,
                    deg - half_ang_deg * 0.85,
                    deg + half_ang_deg * 0.85,
                    width=bar_w,
                    facecolor="#10b981",
                    edgecolor="none",
                    zorder=3,
                )
            )
        _draw_ring_title(ring_r + w_max * 0.5, "GC%", "#047857")
        ring_r += w_max + 0.02

    bound = ring_r + 0.06
    ax.set_xlim(-bound, bound)
    ax.set_ylim(-bound, bound)

    if req.title:
        fig.suptitle(req.title, fontsize=12, fontweight="bold", color="#0f172a", y=0.975)

    # 左下角演化距离标尺
    if req.use_branch_lengths and max_depth > 0:
        sb_val = round(max_depth * 0.25, 2) or 0.1
        sb_len = (sb_val / max_depth) * tree_r
        sb_x = -bound + 0.06
        sb_y = -bound + 0.08
        ax.plot([sb_x, sb_x + sb_len], [sb_y, sb_y], color="#0f172a", linewidth=1.6)
        ax.plot([sb_x, sb_x], [sb_y - 0.015, sb_y + 0.015], color="#0f172a", linewidth=1.2)
        ax.plot([sb_x + sb_len, sb_x + sb_len], [sb_y - 0.015, sb_y + 0.015], color="#0f172a", linewidth=1.2)
        ax.text(sb_x + sb_len * 0.5, sb_y + 0.025, f"Tree scale: {sb_val:.2f}", fontsize=7.5, ha="center", color="#334155")

    has_query = any(str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "query" for lf in leaves)
    has_og = any(str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "outgroup" for lf in leaves)
    _draw_legend_panel(ax_leg, genus_colors, has_query, has_og, req.support_style, req, has_meta, max_len_kb, subtitle)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.93 if req.title else 0.97, bottom=0.03)
    return fig


def _render_rectangular(
    root: PhyloNode,
    leaves: List[PhyloNode],
    node_metadata: Dict[str, Dict[str, Any]],
    display_labels: Dict[str, str],
    genus_colors: Dict[str, str],
    req: PublicationFigureRequest,
    subtitle: str,
) -> plt.Figure:
    n_leaves = len(leaves)
    depths = _compute_node_depths(root, req.use_branch_lengths)
    max_depth = max(depths.values()) or 1.0

    y_pos: Dict[int, float] = {}
    for idx, lf in enumerate(leaves):
        y_pos[id(lf)] = float(n_leaves - 1 - idx)

    def _assign_y(node: PhyloNode) -> float:
        if node.is_leaf:
            return y_pos[id(node)]
        ys = [_assign_y(ch) for ch in node.children]
        val = sum(ys) / len(ys)
        y_pos[id(node)] = val
        return val

    _assign_y(root)

    has_meta = bool(node_metadata)
    show_strip = has_meta and req.show_genus_strip
    show_len = has_meta and req.show_genome_length
    show_gc = has_meta and req.show_gc_bar

    fig_h = max(7.0, min(22.0, 2.2 + n_leaves * 0.24))
    fig_w = 15.2 if has_meta else 11.4
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")

    col_ratios: List[float] = [4.6]
    if show_strip:
        col_ratios.append(0.35)
    if show_len:
        col_ratios.append(0.95)
    if show_gc:
        col_ratios.append(0.8)
    col_ratios.append(1.55)

    gs = fig.add_gridspec(1, len(col_ratios), width_ratios=col_ratios, wspace=0.05)
    ax_tree = fig.add_subplot(gs[0, 0])

    # 主树分支绘制
    segments: List[List[Tuple[float, float]]] = []
    seg_cols: List[str] = []
    seg_lws: List[float] = []
    seg_lss: List[str] = []

    def _collect(node: PhyloNode) -> None:
        xp = depths[id(node)]
        yp = y_pos[id(node)]
        for ch in node.children:
            xc = depths[id(ch)]
            yc = y_pos[id(ch)]
            col, lw, ls = _subtree_dominant_branch_style(ch, node_metadata, genus_colors)
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
            LineCollection(segments, colors=seg_cols, linewidths=seg_lws, linestyles=seg_lss, capstyle="round", zorder=2)
        )

    max_chars = max((len(display_labels.get(lf.name, lf.name)) for lf in leaves), default=12)
    label_pad = max_depth * 0.03
    right_margin = max_depth * max(0.32, min(1.15, max_chars * 0.017))
    label_font = max(6.0, min(8.8, 260.0 / max(26, n_leaves)))

    for lf in leaves:
        x_tip = depths[id(lf)]
        y_tip = y_pos[id(lf)]
        disp_text = display_labels.get(lf.name, lf.name)
        role, col, _, _ = _resolve_leaf_style(lf.name, node_metadata, genus_colors)
        if x_tip < max_depth:
            ax_tree.plot([x_tip, max_depth + label_pad * 0.6], [y_tip, y_tip], color="#cbd5e1", linewidth=0.55, linestyle=":", zorder=1)
        ax_tree.scatter([x_tip], [y_tip], s=20 if role == "query" else 10, color=col, zorder=4)
        bbox_kw = {"boxstyle": "round,pad=0.16", "facecolor": _QUERY_BG_COLOR, "edgecolor": "none"} if role == "query" else None
        ax_tree.text(
            max_depth + label_pad,
            y_tip,
            disp_text,
            fontsize=label_font,
            fontweight="bold" if role == "query" else "normal",
            color="#991b1b" if role == "query" else ("#475569" if role == "outgroup" else "#0f172a"),
            va="center",
            ha="left",
            bbox=bbox_kw,
            zorder=5,
        )

    if req.support_style != "none":
        def _draw_sup(node: PhyloNode) -> None:
            if not node.is_leaf and node is not root:
                txt, uf_val = _format_support_text(node.name)
                xn = depths[id(node)]
                yn = y_pos[id(node)]
                if uf_val is not None and req.support_style in ("dots", "both"):
                    if uf_val >= 95.0:
                        ax_tree.scatter([xn], [yn], s=22, color=_STRONG_DOT_COLOR, edgecolor="white", linewidth=0.4, zorder=6)
                    elif uf_val >= 80.0:
                        ax_tree.scatter([xn], [yn], s=15, color=_MOD_DOT_COLOR, edgecolor="white", linewidth=0.35, zorder=6)
                if txt and req.support_style in ("text", "both"):
                    ax_tree.text(
                        xn - max_depth * 0.008,
                        yn + 0.14,
                        txt,
                        fontsize=max(5.0, label_font * 0.78),
                        color="#0f766e" if (uf_val or 0) >= 95.0 else "#475569",
                        ha="right",
                        va="bottom",
                        zorder=7,
                    )
            for ch in node.children:
                _draw_sup(ch)

        _draw_sup(root)

    ax_tree.set_xlim(-max_depth * 0.04, max_depth + label_pad + right_margin)
    ax_tree.set_ylim(-0.8, n_leaves - 0.2)
    ax_tree.axis("off")

    if req.use_branch_lengths and max_depth > 0:
        sb_val = round(max_depth * 0.25, 2) or 0.1
        ax_tree.plot([0.0, sb_val], [-0.55, -0.55], color="#0f172a", linewidth=1.6)
        ax_tree.plot([0.0, 0.0], [-0.66, -0.44], color="#0f172a", linewidth=1.2)
        ax_tree.plot([sb_val, sb_val], [-0.66, -0.44], color="#0f172a", linewidth=1.2)
        ax_tree.text(sb_val * 0.5, -0.35, f"Tree scale: {sb_val:.2f}", fontsize=7.5, ha="center", color="#334155")

    col_idx = 1
    if show_strip:
        ax_s = fig.add_subplot(gs[0, col_idx])
        ax_s.set_xlim(0, 1)
        ax_s.set_ylim(-0.8, n_leaves - 0.2)
        ax_s.axis("off")
        ax_s.set_title("Genus", fontsize=8.0, fontweight="bold", color="#0f172a", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            meta = node_metadata.get(lf.name, {})
            role = str(meta.get("role") or "").lower()
            genus = str(meta.get("genus") or "").strip()
            col = _QUERY_COLOR if role == "query" else (_DEFAULT_OUTGROUP_COLOR if role == "outgroup" else genus_colors.get(genus, _UNCLASSIFIED_COLOR))
            ax_s.add_patch(Rectangle((0.08, y_tip - 0.38), 0.84, 0.76, facecolor=col, edgecolor="white", linewidth=0.4))
        col_idx += 1

    max_len_kb = max(
        (float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0 for lf in leaves),
        default=1.0,
    ) or 1.0

    if show_len:
        ax_l = fig.add_subplot(gs[0, col_idx])
        ax_l.set_xlim(0, max_len_kb * 1.38)
        ax_l.set_ylim(-0.8, n_leaves - 0.2)
        ax_l.axis("off")
        ax_l.set_title("Size (kb)", fontsize=8.0, fontweight="bold", color="#0369a1", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            kb = float((node_metadata.get(lf.name) or {}).get("genome_length") or 0) / 1000.0
            ax_l.barh(y_tip, kb, height=0.68, color="#0ea5e9", edgecolor="none")
            if kb > 0:
                ax_l.text(kb + max_len_kb * 0.04, y_tip, f"{kb:.1f}", fontsize=max(5.0, label_font * 0.75), va="center", color="#334155")
        col_idx += 1

    if show_gc:
        ax_g = fig.add_subplot(gs[0, col_idx])
        ax_g.set_xlim(0, 125.0)
        ax_g.set_ylim(-0.8, n_leaves - 0.2)
        ax_g.axis("off")
        ax_g.set_title("GC (%)", fontsize=8.0, fontweight="bold", color="#047857", pad=4)
        for lf in leaves:
            y_tip = y_pos[id(lf)]
            gc = float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
            ax_g.barh(y_tip, gc, height=0.68, color="#10b981", edgecolor="none")
            if gc > 0:
                ax_g.text(gc + 3.0, y_tip, f"{gc:.1f}%", fontsize=max(5.0, label_font * 0.75), va="center", color="#334155")
        col_idx += 1

    ax_leg = fig.add_subplot(gs[0, col_idx])
    has_query = any(str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "query" for lf in leaves)
    has_og = any(str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "outgroup" for lf in leaves)
    _draw_legend_panel(ax_leg, genus_colors, has_query, has_og, req.support_style, req, has_meta, max_len_kb, subtitle)

    if req.title:
        fig.suptitle(req.title, fontsize=12, fontweight="bold", color="#0f172a", y=0.985)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.92 if req.title else 0.95, bottom=0.04)
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

        meta = enrich_node_metadata(node_metadata, [lf.name for lf in leaves])
        display_labels = {
            lf.name: format_leaf_label(lf.name, meta.get(lf.name), request.label_format)
            for lf in leaves
        }
        genus_colors = _build_genus_palette(leaves, meta)
        fig = (
            _render_circular(root, leaves, meta, display_labels, genus_colors, request, subtitle)
            if request.layout == "circular"
            else _render_rectangular(root, leaves, meta, display_labels, genus_colors, request, subtitle)
        )

        generated: List[Path] = []
        try:
            for fmt in dict.fromkeys(request.formats):
                fname = f"{file_prefix}_{request.layout}.{fmt}"
                fpath = out_dir / fname
                save_kw: Dict[str, Any] = {"bbox_inches": "tight", "pad_inches": 0.2, "facecolor": "white"}
                if fmt == "png":
                    save_kw["dpi"] = request.dpi
                fig.savefig(fpath, format=fmt, **save_kw)
                generated.append(fpath)
        finally:
            plt.close(fig)

        return generated
