# -*- coding: utf-8 -*-
"""
HostMatrixRenderer - 双进化树联动宿主裂解谱热图 & 对角化稀疏特异性矩阵渲染器。
借鉴文献：
- Quinones-Olvera et al., Nature Communications (2024) 10.1038/s41467-024-47416-z Fig. 4c（双树联动热图）
- DepoCatalog, Nature Communications (2026) 10.1038/s41467-026-73570-7 Fig. 2（对角化血清型×解聚酶/噬菌体稀疏矩阵）
"""
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch, Rectangle
from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage

from ..models import HostMatrixRenderRequest
from ..palette import apply_journal_rcparams, draw_text, get_journal_palette, save_publication_figure

_HEAT_CMAP = LinearSegmentedColormap.from_list(
    "host_lvt",
    ["#f8f6ed", "#e8c4c4", "#b86b91", "#6d326d", "#2c113a"],
)
_HEAT_MONO = LinearSegmentedColormap.from_list(
    "host_mono",
    ["#f8fafc", "#cbd5e1", "#64748b", "#0f172a"],
)


def _draw_dual_tree_heatmap(
    row_labels: List[str],
    col_labels: List[str],
    mat: np.ndarray,
    req: HostMatrixRenderRequest,
) -> plt.Figure:
    nr, nc = mat.shape
    pal = get_journal_palette(req.palette)
    cmap = _HEAT_MONO if req.palette == "monochrome" else _HEAT_CMAP

    r_link = linkage(mat, method="average") if (req.cluster_rows and nr >= 2) else None
    if r_link is not None:
        r_ord = list(leaves_list(r_link))
        row_labels = [row_labels[i] for i in r_ord]
        mat = mat[r_ord, :]

    c_link = linkage(mat.T, method="average") if (req.cluster_cols and nc >= 2) else None
    if c_link is not None:
        c_ord = list(leaves_list(c_link))
        col_labels = [col_labels[i] for i in c_ord]
        mat = mat[:, c_ord]

    fig_w = max(9.6, min(16.0, 4.2 + nc * 0.42))
    fig_h = max(7.2, min(14.0, 4.0 + nr * 0.36))
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(
        3,
        3,
        width_ratios=[1.2, 1.35, max(3.6, nc * 0.34)],
        height_ratios=[max(3.0, nr * 0.30), 0.95, 1.05],
        wspace=0.04,
        hspace=0.04,
    )

    ax_rtree = fig.add_subplot(gs[0, 0])
    ax_rlbl = fig.add_subplot(gs[0, 1])
    ax_mat = fig.add_subplot(gs[0, 2])
    ax_corner1 = fig.add_subplot(gs[1, 0])
    ax_corner2 = fig.add_subplot(gs[1, 1])
    ax_clbl = fig.add_subplot(gs[1, 2])
    ax_corner3 = fig.add_subplot(gs[2, 0])
    ax_cbar = fig.add_subplot(gs[2, 1])
    ax_ctree = fig.add_subplot(gs[2, 2])

    ax_corner1.axis("off")
    ax_corner2.axis("off")
    ax_corner3.axis("off")

    # 1. 左侧宿主树
    ax_rtree.axis("off")
    if r_link is not None:
        dendrogram(r_link, orientation="left", ax=ax_rtree, no_labels=True, color_threshold=0.0, above_threshold_color=pal.backbone_color)
        ax_rtree.set_ylim(0, nr * 10)
        ax_rtree.invert_yaxis()
        for col_obj in ax_rtree.collections:
            col_obj.set_linewidth(1.0)

    # 2. 行名（菌株）
    ax_rlbl.set_xlim(0, 1)
    ax_rlbl.set_ylim(-0.5, nr - 0.5)
    ax_rlbl.invert_yaxis()
    ax_rlbl.axis("off")
    rf = max(6.2, min(8.6, 150.0 / max(6, nr)))
    for i, lbl in enumerate(row_labels):
        draw_text(ax_rlbl, 0.94, i, lbl, fontsize=rf, fontstyle="italic", ha="right", va="center", color="#0f172a")
        ax_rlbl.plot([0.96, 1.0], [i, i], color="#cbd5e1", linewidth=0.5, linestyle=":")

    # 3. 主连续热图
    vmax = float(np.max(mat)) if float(np.max(mat)) > 0 else 100.0
    vmin = float(np.min(mat))
    span = max(1e-6, vmax - vmin)
    ax_mat.set_xlim(0, nc)
    ax_mat.set_ylim(nr, 0)
    ax_mat.axis("off")
    for i in range(nr):
        for j in range(nc):
            v = float(mat[i, j])
            rgba = cmap(np.clip((v - vmin) / span, 0.0, 1.0))
            ax_mat.add_patch(Rectangle((j, i), 1.0, 1.0, facecolor=rgba, edgecolor="#ffffff", linewidth=0.9))
            if req.show_values and nr <= 16 and nc <= 18:
                t_col = "#ffffff" if ((v - vmin) / span) >= 0.55 else "#0f172a"
                draw_text(ax_mat, j + 0.5, i + 0.5, f"{v:.0f}", fontsize=6.2, ha="center", va="center", color=t_col)

    # 4. 列名独立空白带（位于热图与底部噬菌体树之间，彻底零碰撞）
    ax_clbl.set_xlim(0, nc)
    ax_clbl.set_ylim(0, 1)
    ax_clbl.axis("off")
    cf = max(6.2, min(8.2, 160.0 / max(6, nc)))
    for j, clbl in enumerate(col_labels):
        ax_clbl.plot([j + 0.5, j + 0.5], [0.95, 1.0], color="#cbd5e1", linewidth=0.5, linestyle=":")
        draw_text(ax_clbl, j + 0.5, 0.90, clbl, fontsize=cf, rotation=90, ha="center", va="top", color="#0f172a", fontweight="bold")
        ax_clbl.plot([j + 0.5, j + 0.5], [0.0, 0.06], color="#cbd5e1", linewidth=0.5, linestyle=":")

    # 5. 底部噬菌体聚类树（完整保留 scipy bottom 反转方向）
    ax_ctree.axis("off")
    if c_link is not None:
        dendrogram(c_link, orientation="bottom", ax=ax_ctree, no_labels=True, color_threshold=0.0, above_threshold_color=pal.backbone_color)
        ax_ctree.set_xlim(0, nc * 10)
        for col_obj in ax_ctree.collections:
            col_obj.set_linewidth(1.0)

    # 5. 左下渐变 Colorbar
    ax_cbar.axis("off")
    ax_cbar.set_xlim(0, 1)
    ax_cbar.set_ylim(0, 1)
    draw_text(ax_cbar, 0.08, 0.55, "Inhibition / Activity Score", fontsize=7.6, fontweight="bold", color="#0f172a")
    for k in range(36):
        ax_cbar.add_patch(Rectangle((0.08 + (k / 36) * 0.84, 0.36), 0.84 / 35, 0.12, facecolor=cmap((k + 0.5) / 36), edgecolor="none"))
    ax_cbar.add_patch(Rectangle((0.08, 0.36), 0.84, 0.12, facecolor="none", edgecolor="#64748b", linewidth=0.5))
    draw_text(ax_cbar, 0.08, 0.31, f"{vmin:.0f}", fontsize=6.8, ha="left", va="top", color="#334155")
    draw_text(ax_cbar, 0.92, 0.31, f"{vmax:.0f}", fontsize=6.8, ha="right", va="top", color="#334155")

    if req.title:
        fig.suptitle(req.title, fontsize=10.6, fontweight="bold", color="#0f172a", y=0.975)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.91, bottom=0.06)
    return fig


def _draw_sparse_specificity(
    row_labels: List[str],
    col_labels: List[str],
    mat: np.ndarray,
    col_groups: List[str],
    req: HostMatrixRenderRequest,
) -> plt.Figure:
    nr, nc = mat.shape
    pal = get_journal_palette(req.palette)

    # 计算每列的非零质心行并按对角线阶梯重排
    centroids: List[Tuple[float, int]] = []
    for j in range(nc):
        nz = np.where(mat[:, j] > 0)[0]
        cent = float(np.mean(nz)) if len(nz) else float(nr + j)
        centroids.append((cent, j))
    col_ord = [j for _, j in sorted(centroids, key=lambda x: x[0])]
    col_labels = [col_labels[j] for j in col_ord]
    col_groups = [col_groups[j] for j in col_ord]
    mat = mat[:, col_ord]

    uniq_groups = list(dict.fromkeys(g for g in col_groups if g))
    grp_colors: Dict[str, str] = {
        g: pal.taxon_colors[i % len(pal.taxon_colors)] for i, g in enumerate(uniq_groups)
    }

    fig_w = max(9.6, min(16.0, 3.6 + nc * 0.34))
    fig_h = max(5.6, min(12.5, 2.4 + nr * 0.30))
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[4.2, 1.15], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    ax_leg = fig.add_subplot(gs[0, 1])

    ax.set_xlim(0, nc)
    ax.set_ylim(nr, 0)
    for i in range(nr):
        for j in range(nc):
            v = float(mat[i, j])
            grp = col_groups[j]
            if v > 0:
                fc = grp_colors.get(grp, pal.taxon_colors[0])
                alpha = 1.0 if v >= 1 else 0.7
            else:
                fc = "#f8fafc"
                alpha = 1.0
            ax.add_patch(Rectangle((j, i), 1.0, 1.0, facecolor=fc, alpha=alpha, edgecolor="#e2e8f0", linewidth=0.45))

    ax.set_yticks(np.arange(nr) + 0.5)
    ax.set_yticklabels(row_labels, fontsize=max(6.0, min(8.2, 150.0 / max(6, nr))), color="#0f172a")
    ax.set_xticks(np.arange(nc) + 0.5)
    ax.set_xticklabels(col_labels, rotation=90, fontsize=max(5.8, min(8.0, 160.0 / max(6, nc))), color="#0f172a")
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_edgecolor("#cbd5e1")
        sp.set_linewidth(0.7)

    ax_leg.axis("off")
    handles = [Patch(facecolor=grp_colors[g], edgecolor="none", label=g) for g in uniq_groups]
    if not handles:
        handles = [Patch(facecolor=pal.taxon_colors[0], edgecolor="none", label="Active Lysis / Activity")]
    handles.append(Patch(facecolor="#f8fafc", edgecolor="#cbd5e1", label="No activity / Negative"))
    ax_leg.legend(handles=handles, loc="upper left", frameon=False, fontsize=7.8, title="Morphotype / Group", title_fontsize=8.4)

    if req.title:
        fig.suptitle(req.title, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.975)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.91, bottom=0.18)
    return fig


class HostMatrixRenderer:
    """双树联动宿主裂解谱热图 & 对角化稀疏特异性矩阵渲染入口。"""

    @staticmethod
    def render(out_dir: Path, req: HostMatrixRenderRequest) -> List[Path]:
        apply_journal_rcparams()
        nr = len(req.row_labels)
        nc = len(req.col_labels)
        if nr == 0 or nc == 0:
            raise ValueError("宿主/特异性矩阵行列不能为空")
        mat = np.array(req.values, dtype=float)
        if mat.shape != (nr, nc):
            raise ValueError(f"矩阵维度应为 ({nr}, {nc})，当前为 {mat.shape}")

        col_groups = list(req.col_groups) if len(req.col_groups) == nc else ["Phage / Enzyme"] * nc
        if req.mode == "sparse_specificity":
            fig = _draw_sparse_specificity(list(req.row_labels), list(req.col_labels), mat, col_groups, req)
        else:
            fig = _draw_dual_tree_heatmap(list(req.row_labels), list(req.col_labels), mat, req)

        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix=f"host_matrix_{req.mode}",
            formats=req.formats,
            dpi=req.dpi,
        )
