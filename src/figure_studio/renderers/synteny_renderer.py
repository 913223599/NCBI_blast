# -*- coding: utf-8 -*-
"""
SyntenyRibbonRenderer - 现代线性比较基因组共线性丝带图渲染器。
支持双模式：
- lovis4u：2025 NAR LoVis4u 风格，保守核心基因为低干扰中性浅灰，特异/变异/尾丝/抗防御基因为高亮彩色，底部配 PHROGs 功能色带条 + 阶梯标注
- clinker：经典曲线贝塞尔同源丝带风格，CDS 按 PHROGs 着色，连带按一致度灰度渐变填充
采用 4-mer 索引预筛 + Bio.Align.PairwiseAligner 并行精算蛋白相似性（多核保留主机安全核心数）。
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import matplotlib.pyplot as plt
from Bio.Align import PairwiseAligner
from matplotlib.patches import Patch, PathPatch, Polygon, Rectangle
from matplotlib.path import Path as MplPath

from ...phylo.runtime.resource_guard import get_safe_cpu_budget
from ..models import ParsedGenomeInput, SyntenyRenderRequest
from ..palette import (
    PHROG_CATEGORY_COLORS,
    PHROG_LEGEND_ORDER,
    apply_journal_rcparams,
    draw_text,
    get_journal_palette,
    normalize_phrog_category,
    save_publication_figure,
)


def _kmers(seq: str, k: int = 4) -> Set[str]:
    s = seq.strip().upper()
    if len(s) < k:
        return {s} if s else set()
    return {s[i : i + k] for i in range(len(s) - k + 1)}


def _compute_pair_homologs(
    g_a: ParsedGenomeInput,
    g_b: ParsedGenomeInput,
    min_identity: float,
) -> List[Tuple[int, int, float]]:
    """计算相邻两条基因组之间的蛋白同源配对 [(idx_a, idx_b, identity_pct)]。"""
    cds_a = [(idx, f) for idx, f in enumerate(g_a.features) if f.translation]
    cds_b = [(idx, f) for idx, f in enumerate(g_b.features) if f.translation]
    if not cds_a or not cds_b:
        return []

    k = 4 if min(len(f.translation) for _, f in cds_a + cds_b) >= 10 else 2
    b_index: Dict[str, List[int]] = {}
    b_kmers: Dict[int, Set[str]] = {}
    for pos_b, (_orig_idx, feat) in enumerate(cds_b):
        ks = _kmers(feat.translation, k=k)
        b_kmers[pos_b] = ks
        for km in ks:
            b_index.setdefault(km, []).append(pos_b)

    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 1.0
    aligner.mismatch_score = 0.0
    aligner.open_gap_score = -0.5
    aligner.extend_gap_score = -0.2

    links: List[Tuple[int, int, float]] = []
    for orig_a, fa in cds_a:
        ka = _kmers(fa.translation, k=k)
        if not ka:
            continue
        hit_counts: Dict[int, int] = {}
        for km in ka:
            for pos_b in b_index.get(km, ()):
                hit_counts[pos_b] = hit_counts.get(pos_b, 0) + 1
        if not hit_counts:
            continue

        # 仅精算 k-mer 交集最高的前 3 个候选
        top_cands = sorted(hit_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        best_idx_b: Optional[int] = None
        best_id = 0.0
        for pos_b, shared in top_cands:
            kb = b_kmers[pos_b]
            jac = shared / max(1, len(ka | kb))
            if jac < 0.08:
                continue
            orig_b, fb = cds_b[pos_b]
            score = aligner.score(fa.translation, fb.translation)
            ident = max(0.0, min(100.0, (score / max(len(fa.translation), len(fb.translation), 1)) * 100.0))
            if ident > best_id:
                best_id = ident
                best_idx_b = orig_b

        if best_idx_b is not None and best_id >= min_identity:
            links.append((orig_a, best_idx_b, round(best_id, 1)))
    return links


def _find_core_features(
    genomes: List[ParsedGenomeInput],
    pair_links: List[List[Tuple[int, int, float]]],
) -> Dict[Tuple[int, int], bool]:
    """标记哪些基因属于跨所有输入株的保守核心基因（用于 LoVis4u 去噪淡化）。"""
    n_g = len(genomes)
    if n_g <= 1:
        return {}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def find(x: Tuple[int, int]) -> Tuple[int, int]:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: Tuple[int, int], b: Tuple[int, int]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for g_idx, links in enumerate(pair_links):
        for ia, ib, _ident in links:
            union((g_idx, ia), (g_idx + 1, ib))

    comp_genomes: Dict[Tuple[int, int], Set[int]] = {}
    for g_idx, g in enumerate(genomes):
        for f_idx in range(len(g.features)):
            root = find((g_idx, f_idx))
            comp_genomes.setdefault(root, set()).add(g_idx)

    is_core: Dict[Tuple[int, int], bool] = {}
    threshold_cnt = max(2, n_g)
    for g_idx, g in enumerate(genomes):
        for f_idx in range(len(g.features)):
            root = find((g_idx, f_idx))
            is_core[(g_idx, f_idx)] = len(comp_genomes.get(root, set())) >= threshold_cnt
    return is_core


class SyntenyRibbonRenderer:
    """LoVis4u / clinker 现代比较基因组共线性丝带图渲染入口。"""

    @staticmethod
    def render(genomes: List[ParsedGenomeInput], out_dir: Path, req: SyntenyRenderRequest) -> List[Path]:
        if len(genomes) < 2:
            raise ValueError("共线性比较图至少需要 2 条含 CDS 注释的噬菌体基因组")

        apply_journal_rcparams()
        pal = get_journal_palette(req.palette)

        # 多核并发计算相邻基因组同源配对（保留 CPU 安全余量）
        pairs = [(genomes[i], genomes[i + 1]) for i in range(len(genomes) - 1)]
        workers = min(len(pairs), max(1, get_safe_cpu_budget() // 2))
        if workers > 1 and len(pairs) > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                pair_links = list(ex.map(lambda ab: _compute_pair_homologs(ab[0], ab[1], req.min_identity), pairs))
        else:
            pair_links = [_compute_pair_homologs(a, b, req.min_identity) for a, b in pairs]

        core_flags = _find_core_features(genomes, pair_links)
        max_len = max((g.length for g in genomes), default=1) or 1
        n_g = len(genomes)

        fig_h = max(4.8, 2.2 + n_g * 1.45)
        fig = plt.figure(figsize=(14.4, fig_h), dpi=req.dpi, facecolor="white")
        gs = fig.add_gridspec(2, 1, height_ratios=[max(3.4, n_g * 1.3), 0.72], hspace=0.08)
        ax = fig.add_subplot(gs[0, 0])
        ax_leg = fig.add_subplot(gs[1, 0])

        ax.set_xlim(-max_len * 0.16, max_len * 1.03)
        y_spacing = 1.65
        top_y = (n_g - 1) * y_spacing
        ax.set_ylim(-0.85, top_y + 1.05)
        ax.axis("off")

        # 1. 先绘制底层同源连接丝带
        for g_idx, links in enumerate(pair_links):
            y_top_row = (n_g - 1 - g_idx) * y_spacing
            y_bot_row = (n_g - 2 - g_idx) * y_spacing
            fa_list = genomes[g_idx].features
            fb_list = genomes[g_idx + 1].features

            for ia, ib, ident in links:
                fa = fa_list[ia]
                fb = fb_list[ib]
                shade = max(0.18, min(0.68, (ident - 25.0) / 110.0))
                if req.mode == "clinker":
                    y1 = y_top_row - 0.16
                    y2 = y_bot_row + 0.16
                    ymid = (y1 + y2) * 0.5
                    verts = [
                        (fa.start, y1),
                        (fa.end, y1),
                        (fa.end, ymid),
                        (fb.end, ymid),
                        (fb.end, y2),
                        (fb.start, y2),
                        (fb.start, ymid),
                        (fa.start, ymid),
                        (fa.start, y1),
                    ]
                    codes = [
                        MplPath.MOVETO,
                        MplPath.LINETO,
                        MplPath.CURVE4,
                        MplPath.CURVE4,
                        MplPath.CURVE4,
                        MplPath.LINETO,
                        MplPath.CURVE4,
                        MplPath.CURVE4,
                        MplPath.CURVE4,
                    ]
                    ax.add_patch(
                        PathPatch(
                            MplPath(verts, codes),
                            facecolor="#334155" if req.palette == "monochrome" else "#475569",
                            edgecolor="none",
                            alpha=shade * 0.72,
                            zorder=1,
                        )
                    )
                    if req.show_identity_labels:
                        draw_text(
                            ax,
                            (fa.start + fa.end + fb.start + fb.end) * 0.25,
                            ymid,
                            f"{ident:.0f}%",
                            fontsize=5.6,
                            ha="center",
                            va="center",
                            color="#0f172a",
                            zorder=4,
                        )
                else:
                    y1 = y_top_row - 0.20
                    y2 = y_bot_row + 0.16
                    poly = [(fa.start, y1), (fa.end, y1), (fb.end, y2), (fb.start, y2)]
                    ax.add_patch(Polygon(poly, closed=True, facecolor="#94a3b8", edgecolor="none", alpha=shade * 0.50, zorder=1))

        # 2. 绘制每条基因组的 CDS 箭头 + PHROGs 底条 + 差异基因高亮 + 防重叠标注
        acc_color_pool = pal.taxon_colors
        acc_idx = 0
        for g_idx, genome in enumerate(genomes):
            y_row = (n_g - 1 - g_idx) * y_spacing
            ax.plot([0, genome.length], [y_row, y_row], color="#475569", linewidth=0.95, zorder=2)

            label_txt = genome.name if len(genome.name) <= 28 else genome.name[:25] + "..."
            draw_text(ax, -max_len * 0.015, y_row + 0.02, label_txt, fontsize=8.0, fontweight="bold", ha="right", va="center", color="#0f172a")
            draw_text(ax, -max_len * 0.015, y_row - 0.22, f"{genome.length:,} bp", fontsize=6.5, ha="right", va="center", color="#64748b")

            key_anno: List[Tuple[float, str]] = []
            for f_idx, f in enumerate(genome.features):
                cat = normalize_phrog_category(f.category, f.function, f.product, f.feature_type)
                phrog_col = PHROG_CATEGORY_COLORS.get(cat, "#94a3b8")
                is_core = core_flags.get((g_idx, f_idx), False)

                if req.mode == "lovis4u":
                    if is_core:
                        arrow_col = "#cbd5e1"
                    elif cat in ("tail", "anti-defence", "lysis"):
                        arrow_col = phrog_col
                    else:
                        arrow_col = acc_color_pool[acc_idx % len(acc_color_pool)]
                        acc_idx += 1
                    # 底部 PHROGs 功能色条
                    ax.add_patch(Rectangle((f.start, y_row - 0.19), max(1.0, f.end - f.start), 0.065, facecolor=phrog_col, edgecolor="none", zorder=3))
                else:
                    arrow_col = phrog_col

                st, en = float(f.start), float(f.end)
                head = min((en - st) * 0.36, max_len * 0.008)
                h = 0.23
                if f.strand != "-":
                    pts = [(st, y_row - h * 0.5), (en - head, y_row - h * 0.5), (en, y_row), (en - head, y_row + h * 0.5), (st, y_row + h * 0.5)]
                else:
                    pts = [(en, y_row - h * 0.5), (st + head, y_row - h * 0.5), (st, y_row), (st + head, y_row + h * 0.5), (en, y_row + h * 0.5)]
                ax.add_patch(Polygon(pts, closed=True, facecolor=arrow_col, edgecolor="#334155", linewidth=0.45, zorder=3))

                low_p = (f.product or "").lower()
                if req.show_labels and not any(k in low_p for k in ("hypothetical", "uncharacterized")):
                    if not is_core or any(k in low_p for k in ("terminase", "capsid", "tail", "holin", "endolysin", "anti-def", "integrase")):
                        short = f.product if len(f.product) <= 26 else f.product[:23] + "..."
                        key_anno.append(((st + en) * 0.5, short))

            # 每条基因组上方两层阶梯标注关键基因
            if req.show_labels and key_anno:
                lane_x = [-1e9, -1e9]
                min_gap = max_len * 0.14
                for mx, txt in key_anno[:14]:
                    ln = 0 if (mx - lane_x[0] >= min_gap or lane_x[0] <= lane_x[1]) else 1
                    if mx - lane_x[ln] < min_gap:
                        continue
                    lane_x[ln] = mx
                    yt = y_row + 0.30 + ln * 0.24
                    ax.plot([mx, mx], [y_row + 0.12, yt - 0.03], color="#64748b", linewidth=0.45, zorder=4)
                    draw_text(ax, mx, yt, txt, fontsize=6.1, ha="center", va="bottom", color="#1e293b", zorder=5)

        # 3. 比例尺 + 图例
        sb_bp = 5000 if max_len <= 40000 else (10000 if max_len <= 100000 else 20000)
        ax.plot([0, sb_bp], [-0.52, -0.52], color="#0f172a", linewidth=1.2)
        ax.plot([0, 0], [-0.57, -0.47], color="#0f172a", linewidth=1.0)
        ax.plot([sb_bp, sb_bp], [-0.57, -0.47], color="#0f172a", linewidth=1.0)
        draw_text(ax, sb_bp * 0.5, -0.62, f"{sb_bp:,} bp", fontsize=7.2, ha="center", va="top", color="#334155")

        ax_leg.axis("off")
        handles = [Patch(facecolor=PHROG_CATEGORY_COLORS[k], edgecolor="none", label=lbl) for k, lbl in PHROG_LEGEND_ORDER]
        if req.mode == "lovis4u":
            handles.insert(0, Patch(facecolor="#cbd5e1", edgecolor="#334155", linewidth=0.5, label="Core conserved gene"))
        ax_leg.legend(handles=handles, loc="center", ncol=6, frameon=False, fontsize=7.0, columnspacing=1.0, handlelength=1.1)

        if req.title:
            fig.suptitle(req.title, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.98)
        fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.03)
        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix=f"synteny_{req.mode}",
            formats=req.formats,
            dpi=req.dpi,
        )
