# -*- coding: utf-8 -*-
"""
ViridicHeatmapRenderer - 顶刊 VIRIDIC 双向热图与树-下三角 ANI 联动热图渲染器。
借鉴文献：
- Moraru et al., Viruses (2020) PMC7694805 Fig. 4（右上 Similarity + 左下 AF/长度比三层格 + 顶部长度柱）
- Rozwalak et al., Nature Communications (2024) 10.1038/s41467-023-44370-0 Fig. 4c（进化树对齐下三角热图）
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage
from scipy.spatial.distance import squareform

from ..models import ViridicRenderRequest
from ..palette import apply_journal_rcparams, draw_suptitle, draw_text, get_journal_palette, save_publication_figure

_SIM_CMAP_NATURE = LinearSegmentedColormap.from_list(
    "viridic_sim",
    ["#ffffff", "#f5eef8", "#bae6fd", "#38bdf8", "#0284c7", "#065f46"],
)
_SIM_CMAP_MONO = LinearSegmentedColormap.from_list(
    "viridic_mono",
    ["#ffffff", "#e2e8f0", "#94a3b8", "#475569", "#0f172a"],
)
_AF_CMAP = LinearSegmentedColormap.from_list("viridic_af", ["#fff7ed", "#fed7aa", "#fb923c", "#c2410c"])
_LEN_CMAP = LinearSegmentedColormap.from_list("viridic_len", ["#111827", "#6b7280", "#d1d5db", "#f9fafb"])


def _reorder_data(
    labels: List[str],
    wg: np.ndarray,
    af: np.ndarray,
    lengths: List[int],
    cluster_reorder: bool,
    newick: Optional[str] = None,
) -> Tuple[List[str], np.ndarray, np.ndarray, List[int], Optional[Dict[str, Any]]]:
    n = len(labels)
    if n < 2:
        return labels, wg, af, lengths, None

    if newick and newick.strip():
        try:
            from ...phylo.pipeline.postprocess import parse_newick

            root = parse_newick(newick)

            def _leaves(nd: Any) -> List[str]:
                if nd.is_leaf:
                    return [nd.name]
                res: List[str] = []
                for c in nd.children:
                    res.extend(_leaves(c))
                return res

            tree_order = [nm for nm in _leaves(root) if nm in labels]
            missing = [nm for nm in labels if nm not in tree_order]
            final_names = tree_order + missing
            idx_map = {nm: i for i, nm in enumerate(labels)}
            order = [idx_map[nm] for nm in final_names]
            return (
                [labels[i] for i in order],
                wg[np.ix_(order, order)],
                af[np.ix_(order, order)],
                [lengths[i] for i in order],
                None,
            )
        except Exception:
            pass

    dist = np.clip(100.0 - 0.5 * (wg + wg.T), 0.0, 100.0)
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    if cluster_reorder:
        order = list(leaves_list(Z))
        return (
            [labels[i] for i in order],
            wg[np.ix_(order, order)],
            af[np.ix_(order, order)],
            [lengths[i] for i in order],
            {"Z": Z, "order": order},
        )
    return labels, wg, af, lengths, {"Z": Z, "order": list(range(n))}


def _draw_viridic_dual(
    labels: List[str],
    wg: np.ndarray,
    af: np.ndarray,
    lengths: List[int],
    req: ViridicRenderRequest,
) -> plt.Figure:
    n = len(labels)
    sim_cmap = _SIM_CMAP_MONO if req.palette == "monochrome" else _SIM_CMAP_NATURE
    cell_px = max(0.36, min(0.55, 8.8 / max(4, n)))
    side = max(7.2, min(14.5, n * cell_px + 2.8))
    fig = plt.figure(figsize=(side * 1.15, side * 1.18), dpi=req.dpi, facecolor="white")

    gs = fig.add_gridspec(3, 1, height_ratios=[0.92, 0.95, max(4.8, n * 0.44)], hspace=0.10)
    ax_cbar = fig.add_subplot(gs[0, 0])
    ax_len = fig.add_subplot(gs[1, 0])
    ax_mat = fig.add_subplot(gs[2, 0])

    # 1. 顶部 3 条水平渐变色标
    ax_cbar.axis("off")
    ax_cbar.set_xlim(0, 1)
    ax_cbar.set_ylim(0, 1)
    bar_specs = [
        (0.02, 0.44, 0.72, _AF_CMAP, "Aligned genome fraction", ("0", "0.25", "0.5", "0.75", "1")),
        (0.54, 0.44, 0.72, _LEN_CMAP, "Genome length ratio", ("0", "0.25", "0.5", "0.75", "1")),
        (0.02, 0.44, 0.16, sim_cmap, "Intergenomic similarity (%)", ("0", "25", "50", "75", "100")),
    ]
    for x0, bw, y0, cmap, title, ticks in bar_specs:
        draw_text(ax_cbar, x0, y0 + 0.14, title, fontsize=7.6, fontweight="bold", color="#0f172a", va="bottom")
        steps = 40
        sw = bw / steps
        for k in range(steps):
            rgba = cmap((k + 0.5) / steps)
            ax_cbar.add_patch(Rectangle((x0 + k * sw, y0), sw * 1.03, 0.11, facecolor=rgba, edgecolor="none"))
        ax_cbar.add_patch(Rectangle((x0, y0), bw, 0.11, facecolor="none", edgecolor="#64748b", linewidth=0.5))
        for t_idx, t_txt in enumerate(ticks):
            tx = x0 + (t_idx / (len(ticks) - 1)) * bw
            draw_text(ax_cbar, tx, y0 - 0.035, t_txt, fontsize=6.4, ha="center", va="top", color="#334155")

    # 2. 顶部 Genome Length 柱图（与下方网格严格 x 对齐）
    max_kb = max((ln / 1000.0 for ln in lengths), default=50.0) or 50.0
    xs = np.arange(n) + 0.5
    kb_vals = [ln / 1000.0 for ln in lengths]
    bar_col = "#64748b" if req.palette == "monochrome" else "#475569"
    ax_len.bar(xs, kb_vals, width=0.68, color=bar_col, edgecolor="#1e293b", linewidth=0.45)
    ax_len.set_xlim(0, n)
    ax_len.set_ylim(0, max_kb * 1.15)
    ax_len.spines["top"].set_visible(False)
    ax_len.spines["right"].set_visible(False)
    ax_len.tick_params(axis="x", bottom=False, labelbottom=False)
    ax_len.tick_params(axis="y", labelsize=6.8, colors="#334155")
    ax_len.set_ylabel("Length (kb)", fontsize=7.5, fontweight="bold", color="#0f172a")

    # 3. 主矩阵网格：对角线 + 右上相似性 + 左下三层指标格
    ax_mat.set_xlim(0, n)
    ax_mat.set_ylim(n, 0)
    num_fsize = max(4.2, min(7.2, 115.0 / max(8, n)))
    small_fsize = max(3.3, num_fsize * 0.65)
    show_nums = req.show_values and n <= 28

    for i in range(n):
        for j in range(n):
            sim_val = float(wg[i, j])
            if j >= i:
                rgba = sim_cmap(np.clip(sim_val / 100.0, 0.0, 1.0))
                ax_mat.add_patch(Rectangle((j, i), 1.0, 1.0, facecolor=rgba, edgecolor="#e2e8f0", linewidth=0.35))
                if show_nums:
                    t_col = "#ffffff" if sim_val >= 72.0 else "#0f172a"
                    draw_text(
                        ax_mat,
                        j + 0.5,
                        i + 0.5,
                        f"{sim_val:.1f}" if n <= 16 else f"{sim_val:.0f}",
                        fontsize=num_fsize,
                        ha="center",
                        va="center",
                        color=t_col,
                        fontweight="bold" if i == j or sim_val >= 95.0 else "normal",
                    )
            else:
                af_row = float(af[i, j]) / 100.0
                af_col = float(af[j, i]) / 100.0
                li = max(1, lengths[i])
                lj = max(1, lengths[j])
                l_ratio = min(li, lj) / max(li, lj)
                c1 = _AF_CMAP(np.clip(af_row, 0.0, 1.0))
                c2 = _LEN_CMAP(np.clip(l_ratio, 0.0, 1.0))
                c3 = _AF_CMAP(np.clip(af_col, 0.0, 1.0))
                ax_mat.add_patch(Rectangle((j, i), 1.0, 1.0 / 3.0, facecolor=c1, edgecolor="none"))
                ax_mat.add_patch(Rectangle((j, i + 1.0 / 3.0), 1.0, 1.0 / 3.0, facecolor=c2, edgecolor="none"))
                ax_mat.add_patch(Rectangle((j, i + 2.0 / 3.0), 1.0, 1.0 / 3.0, facecolor=c3, edgecolor="none"))
                ax_mat.add_patch(Rectangle((j, i), 1.0, 1.0, facecolor="none", edgecolor="#e2e8f0", linewidth=0.35))
                if show_nums and n <= 18:
                    draw_text(ax_mat, j + 0.5, i + 0.17, f"{af_row:.2f}", fontsize=small_fsize, ha="center", va="center", color="#7c2d12")
                    draw_text(ax_mat, j + 0.5, i + 0.50, f"{l_ratio:.2f}", fontsize=small_fsize, ha="center", va="center", color="#ffffff" if l_ratio < 0.45 else "#0f172a")
                    draw_text(ax_mat, j + 0.5, i + 0.83, f"{af_col:.2f}", fontsize=small_fsize, ha="center", va="center", color="#7c2d12")

    # 对齐轴标签
    ax_mat.yaxis.tick_right()
    ax_mat.set_yticks(np.arange(n) + 0.5)
    ax_mat.set_yticklabels(labels, fontsize=max(5.5, min(8.2, 140.0 / max(6, n))), color="#0f172a")
    ax_mat.set_xticks(np.arange(n) + 0.5)
    ax_mat.set_xticklabels(labels, rotation=90, fontsize=max(5.5, min(8.2, 140.0 / max(6, n))), color="#0f172a")
    ax_mat.tick_params(length=0)
    for sp in ax_mat.spines.values():
        sp.set_edgecolor("#94a3b8")
        sp.set_linewidth(0.7)

    if req.title:
        draw_suptitle(fig, req.title, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.985)
    fig.subplots_adjust(left=0.09, right=0.80, top=0.93, bottom=0.18)
    return fig


def _draw_tree_triangle(
    labels: List[str],
    wg: np.ndarray,
    cluster_info: Optional[Dict[str, Any]],
    req: ViridicRenderRequest,
) -> plt.Figure:
    n = len(labels)
    pal = get_journal_palette(req.palette)
    tri_cmap = LinearSegmentedColormap.from_list(
        "tri_ani",
        ["#f8fafc", "#dcfce7", "#86efac", "#22c55e", "#15803d"] if req.palette != "monochrome" else ["#f8fafc", "#cbd5e1", "#64748b", "#0f172a"],
    )
    h_fig = max(5.8, min(12.5, 2.2 + n * 0.42))
    w_fig = max(9.4, h_fig * 1.45)
    fig = plt.figure(figsize=(w_fig, h_fig), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 3, width_ratios=[1.45, 1.35, 3.2], wspace=0.04)
    ax_tree = fig.add_subplot(gs[0, 0])
    ax_lbl = fig.add_subplot(gs[0, 1])
    ax_tri = fig.add_subplot(gs[0, 2])

    # 左侧 UPGMA 树状图（基于 100 - wgANI）
    ax_tree.set_ylim(-0.5, n - 0.5)
    ax_tree.axis("off")
    if cluster_info is not None and n >= 2:
        dendrogram(
            cluster_info["Z"],
            orientation="left",
            ax=ax_tree,
            no_labels=True,
            color_threshold=0.0,
            above_threshold_color=pal.backbone_color,
        )
        # scipy dendrogram y 从 5 开始每叶步长 10，映射到 [-0.5, n-0.5]
        ax_tree.set_ylim(0, n * 10)
        ax_tree.invert_yaxis()
        for coll in ax_tree.collections:
            coll.set_linewidth(1.1)

    # 中间叶标签 + 虚线对齐引导
    ax_lbl.set_xlim(0, 1)
    ax_lbl.set_ylim(-0.5, n - 0.5)
    ax_lbl.invert_yaxis()
    ax_lbl.axis("off")
    f_lbl = max(6.2, min(8.8, 165.0 / max(8, n)))
    for i, nm in enumerate(labels):
        ax_lbl.plot([0.0, 0.08], [i, i], color="#94a3b8", linewidth=0.6, linestyle=":")
        draw_text(ax_lbl, 0.12, i, nm, fontsize=f_lbl, va="center", ha="left", color="#0f172a")
        ax_lbl.plot([0.92, 1.0], [i, i], color="#cbd5e1", linewidth=0.5, linestyle=":")

    # 右侧严格下三角 ANI 矩阵
    ax_tri.set_xlim(0, n)
    ax_tri.set_ylim(n, 0)
    ax_tri.axis("off")
    num_f = max(4.8, min(7.6, 120.0 / max(6, n)))
    show_nums = req.show_values and n <= 24
    for i in range(n):
        for j in range(0, i + 1):
            val = float(wg[i, j])
            if i == j:
                rgba = "#94a3b8"
            else:
                rgba = tri_cmap(np.clip((val - 40.0) / 60.0, 0.0, 1.0))
            ax_tri.add_patch(Rectangle((j, i), 1.0, 1.0, facecolor=rgba, edgecolor="#ffffff", linewidth=0.7))
            if i > j and show_nums:
                t_col = "#ffffff" if val >= 88.0 else "#0f172a"
                draw_text(
                    ax_tri,
                    j + 0.5,
                    i + 0.5,
                    f"{val:.0f}" if n > 14 else f"{val:.1f}",
                    fontsize=num_f,
                    ha="center",
                    va="center",
                    color=t_col,
                    fontweight="bold" if val >= 95.0 else "normal",
                )

    # 右上方附连续 ANI 图例色条
    cx0, cw, cy0, ch = n * 0.56, n * 0.36, n * 0.16, max(0.32, n * 0.045)
    draw_text(ax_tri, cx0, cy0 - ch * 0.4, "Intergenomic Identity (%)", fontsize=7.6, fontweight="bold", color="#0f172a", va="bottom")
    n_bins = 30
    bw = cw / n_bins
    for b in range(n_bins):
        ax_tri.add_patch(Rectangle((cx0 + b * bw, cy0), bw * 1.03, ch, facecolor=tri_cmap((b + 0.5) / n_bins), edgecolor="none"))
    ax_tri.add_patch(Rectangle((cx0, cy0), cw, ch, facecolor="none", edgecolor="#64748b", linewidth=0.5))
    for lbl_v, frac in (("40", 0.0), ("70", 0.5), ("95", 0.92), ("100", 1.0)):
        draw_text(ax_tri, cx0 + cw * frac, cy0 + ch + 0.18, lbl_v, fontsize=6.6, ha="center", va="top", color="#334155")

    if req.title:
        draw_suptitle(fig, req.title, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.97)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.90, bottom=0.05)
    return fig


class ViridicHeatmapRenderer:
    """VIRIDIC 双向矩阵 & 进化树联动下三角热图渲染入口。"""

    @staticmethod
    def render(out_dir: Path, req: ViridicRenderRequest) -> List[Path]:
        apply_journal_rcparams()
        labels = list(req.labels)
        n = len(labels)
        if n < 2:
            raise ValueError("VIRIDIC 矩阵至少需要 2 个基因组样本")

        wg = np.array(req.wgani_matrix, dtype=float)
        if wg.shape != (n, n):
            raise ValueError(f"wgANI 矩阵维度应为 ({n}, {n})，当前为 {wg.shape}")

        if req.af_matrix and len(req.af_matrix) == n:
            af = np.array(req.af_matrix, dtype=float)
        else:
            af = np.where(wg > 0, np.minimum(100.0, wg * 0.95), 0.0)
            np.fill_diagonal(af, 100.0)

        lengths = list(req.genome_lengths) if len(req.genome_lengths) == n else [50000] * n
        labels_ord, wg_ord, af_ord, len_ord, cinfo = _reorder_data(
            labels, wg, af, lengths, req.cluster_reorder, req.newick
        )

        if req.mode == "tree_triangle":
            fig = _draw_tree_triangle(labels_ord, wg_ord, cinfo, req)
        else:
            fig = _draw_viridic_dual(labels_ord, wg_ord, af_ord, len_ord, req)

        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix=f"viridic_{req.mode}",
            formats=req.formats,
            dpi=req.dpi,
        )
