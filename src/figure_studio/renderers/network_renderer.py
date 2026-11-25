# -*- coding: utf-8 -*-
"""
GeneNetworkRenderer - 蛋白基因共享网络图 + 10x10 生态/分类构成华夫格图渲染器。
借鉴文献：Rozwalak et al., Nature Communications (2024) 10.1038/s41467-023-44370-0 Fig. 2a-b（vConTACT2 风格）。
"""
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from ..models import NetworkRenderRequest
from ..palette import apply_journal_rcparams, draw_text, get_journal_palette, save_publication_figure


class GeneNetworkRenderer:
    """类 vConTACT2 蛋白共享网络与构成华夫格图渲染入口。"""

    @staticmethod
    def render(
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        out_dir: Path,
        req: NetworkRenderRequest,
    ) -> List[Path]:
        if not nodes:
            raise ValueError("基因共享网络至少需要 1 个基因组节点")

        apply_journal_rcparams()
        pal = get_journal_palette(req.palette)

        G = nx.Graph()
        node_map: Dict[str, Dict[str, Any]] = {}
        for nd in nodes:
            nid = str(nd["id"])
            node_map[nid] = nd
            G.add_node(nid, **nd)

        for ed in edges:
            src, dst = str(ed["source"]), str(ed["target"])
            w = float(ed.get("weight", 1.0))
            if src in G and dst in G and src != dst and w >= req.min_weight:
                G.add_edge(src, dst, weight=w)

        groups = Counter(str(nd.get("group") or "Unclassified") for nd in nodes)
        top_groups = [g for g, _ in groups.most_common(10)]
        group_colors: Dict[str, str] = {}
        for idx, grp in enumerate(top_groups):
            if grp.lower() in ("unclassified", "unknown", ""):
                group_colors[grp] = "#94a3b8"
            else:
                group_colors[grp] = pal.taxon_colors[idx % len(pal.taxon_colors)]

        comps = sorted(nx.connected_components(G), key=len, reverse=True)
        main_nodes: set[str] = set()
        small_comps: List[List[str]] = []
        for comp in comps:
            if len(comp) >= 3 or (len(comps) <= 2 and len(comp) >= 1):
                main_nodes.update(comp)
            else:
                small_comps.append(sorted(comp))

        # 主连通子图力导向布局 + 底部孤立小簇网格排布
        pos: Dict[str, Tuple[float, float]] = {}
        if main_nodes:
            sub_g = G.subgraph(main_nodes)
            raw_pos = nx.spring_layout(sub_g, k=0.65, seed=42, weight="weight")
            for nid, xy in raw_pos.items():
                pos[nid] = (float(xy[0]), float(xy[1]) + 0.35)

        if small_comps:
            cols_per_row = 5
            for c_idx, comp in enumerate(small_comps):
                r_i = c_idx // cols_per_row
                c_i = c_idx % cols_per_row
                cx = -0.85 + c_i * 0.52
                cy = -0.92 - r_i * 0.28
                for k_i, nid in enumerate(comp):
                    dx = (k_i - (len(comp) - 1) * 0.5) * 0.28
                    pos[nid] = (cx + dx, cy)

        fig = plt.figure(figsize=(13.2, 8.0), dpi=req.dpi, facecolor="white")
        gs = fig.add_gridspec(1, 2, width_ratios=[3.6, 1.35], wspace=0.04)
        ax = fig.add_subplot(gs[0, 0])
        ax_side = fig.add_subplot(gs[0, 1])

        ax.set_aspect("equal")
        ax.axis("off")

        # 1. 极淡浅灰连线避免毛线球
        for u, v, d in G.edges(data=True):
            if u in pos and v in pos:
                w = float(d.get("weight", 0.5))
                x1, y1 = pos[u]
                x2, y2 = pos[v]
                ax.plot([x1, x2], [y1, y2], color="#94a3b8", linewidth=0.45 + w * 1.4, alpha=0.25 + min(0.45, w * 0.4), zorder=1)

        # 2. 节点绘制（Query 株用鲜红大圆点+白边高亮）
        for nid, (x, y) in pos.items():
            nd = node_map[nid]
            is_q = bool(nd.get("is_query"))
            grp = str(nd.get("group") or "Unclassified")
            col = pal.query_color if is_q else group_colors.get(grp, "#cbd5e1")
            sz = 135 if is_q else 65
            ax.scatter([x], [y], s=sz, facecolor=col, edgecolor="#0f172a" if not is_q else "#ffffff", linewidth=0.65 if not is_q else 1.0, zorder=4 if is_q else 3)
            if req.show_labels and (is_q or len(nodes) <= 28):
                lbl = str(nd.get("label") or nid)
                draw_text(
                    ax,
                    x,
                    y + 0.055,
                    lbl[:24],
                    fontsize=7.0 if is_q else 5.8,
                    fontweight="bold" if is_q else "normal",
                    color=pal.query_text_color if is_q else "#1e293b",
                    ha="center",
                    va="bottom",
                    zorder=6,
                )

        if pos:
            xs = [p[0] for p in pos.values()]
            ys = [p[1] for p in pos.values()]
            pad = 0.22
            ax.set_xlim(min(xs) - pad, max(xs) + pad)
            ax.set_ylim(min(ys) - pad, max(ys) + pad)

        # 3. 右侧华夫格图 (10x10) + 图例
        ax_side.axis("off")
        ax_side.set_xlim(0, 1)
        ax_side.set_ylim(0, 1)

        y_leg = 0.96
        if req.show_waffle:
            draw_text(ax_side, 0.04, y_leg, "Cluster Composition (10x10)", fontsize=8.4, fontweight="bold", color="#0f172a", va="top")
            total_n = max(1, len(nodes))
            cells: List[str] = []
            for grp, cnt in groups.most_common():
                n_cells = max(1, round((cnt / total_n) * 100)) if cnt > 0 else 0
                col = group_colors.get(grp, "#cbd5e1")
                cells.extend([col] * n_cells)
            cells = (cells + ["#cbd5e1"] * 100)[:100]
            wx0, wy0, cell_s = 0.06, 0.56, 0.031
            for idx, col in enumerate(cells):
                r = 9 - (idx // 10)
                c = idx % 10
                ax_side.add_patch(
                    Rectangle((wx0 + c * (cell_s + 0.005), wy0 + r * (cell_s + 0.005)), cell_s, cell_s, facecolor=col, edgecolor="none")
                )
            y_leg = 0.50

        handles: List[Any] = [
            Line2D([0], [0], marker="o", color="none", markerfacecolor=pal.query_color, markeredgecolor="#ffffff", markersize=8.0, label="Query Phage (This study)")
        ]
        for grp in top_groups:
            handles.append(
                Line2D([0], [0], marker="o", color="none", markerfacecolor=group_colors[grp], markeredgecolor="#0f172a", markeredgewidth=0.5, markersize=6.5, label=f"{grp} ({groups[grp]})")
            )
        ax_side.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, y_leg), frameon=False, fontsize=7.4, labelspacing=0.45)

        if req.title:
            fig.suptitle(req.title, fontsize=10.8, fontweight="bold", color="#0f172a", y=0.975)
        fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.04)
        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix="gene_network",
            formats=req.formats,
            dpi=req.dpi,
        )
