# -*- coding: utf-8 -*-
"""
GenomeMapRenderer - 出版级单株噬菌体全基因组功能图谱渲染器。
支持双版式：
- circular：CGView / Proksee / pyCirclize 风格圆形多环（正负链 CDS + PHROGs 功能色 + GC Skew + GC% + 径向防重叠引线）
- linear_multitrack：NAR 2025 LoVis4u 风格线性多轨图（阶梯防重叠标注 + 正负链 CDS + PHROGs 底条 + GC% + GC Skew）
"""
import math
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Patch, Polygon, Wedge

from ..models import GenomeFeatureItem, GenomeMapRenderRequest, ParsedGenomeInput
from ..palette import (
    PHROG_CATEGORY_COLORS,
    PHROG_LEGEND_ORDER,
    apply_journal_rcparams,
    draw_suptitle,
    draw_text,
    normalize_phrog_category,
    save_publication_figure,
)


def _compute_gc_tracks(sequence: str, genome_len: int, window: int = 0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    seq = sequence.strip().upper()
    if len(seq) < 100:
        # 若缺完整核酸序列，构造中性参考基线以免崩溃
        n_pts = 120
        pos = np.linspace(0, genome_len, n_pts)
        return pos, np.full(n_pts, 45.0), np.zeros(n_pts)

    eff_win = window if window > 0 else max(180, min(1500, len(seq) // 160))
    step = max(30, eff_win // 4)
    centers: List[float] = []
    gcs: List[float] = []
    skews: List[float] = []
    for start in range(0, max(1, len(seq) - eff_win + 1), step):
        sub = seq[start : start + eff_win]
        g = sub.count("G")
        c = sub.count("C")
        atgc = g + c + sub.count("A") + sub.count("T")
        if atgc == 0:
            gc_pct, skew = 45.0, 0.0
        else:
            gc_pct = ((g + c) / atgc) * 100.0
            skew = ((g - c) / (g + c)) if (g + c) > 0 else 0.0
        centers.append(start + eff_win * 0.5)
        gcs.append(gc_pct)
        skews.append(skew)
    return np.array(centers, dtype=float), np.array(gcs, dtype=float), np.array(skews, dtype=float)


def _select_key_labels(features: List[GenomeFeatureItem], genome_len: int, max_labels: int) -> List[Tuple[int, str, str]]:
    """筛选有代表性的功能蛋白用于标注，过滤 hypothetical 并控制密度防重叠。"""
    picked: List[Tuple[int, str, str]] = []
    priority_kw = (
        "terminase",
        "portal",
        "capsid",
        "tail",
        "tape measure",
        "holin",
        "endolysin",
        "lysin",
        "polymerase",
        "helicase",
        "integrase",
        "anti-def",
        "depolymerase",
        "baseplate",
        "spike",
        "trna",
    )
    ranked: List[Tuple[int, int, str, str]] = []
    for f in features:
        prod = (f.product or "").strip()
        low = prod.lower()
        if not prod or "hypothetical" in low or "uncharacterized" in low:
            continue
        score = 2 if any(k in low for k in priority_kw) else 1
        mid = int((f.start + f.end) * 0.5)
        cat = normalize_phrog_category(f.category, f.function, prod, f.feature_type)
        short = prod if len(prod) <= 32 else (prod[:29] + "...")
        ranked.append((score, mid, short, PHROG_CATEGORY_COLORS.get(cat, "#334155")))

    ranked.sort(key=lambda x: (-x[0], x[1]))
    chosen_mids: List[int] = []
    min_dist = max(1, int(genome_len / max(max_labels * 1.3, 8)))
    for _score, mid, txt, col in ranked:
        if any(abs(mid - pm) < min_dist for pm in chosen_mids):
            continue
        chosen_mids.append(mid)
        picked.append((mid, txt, col))
        if len(picked) >= max_labels:
            break
    picked.sort(key=lambda x: x[0])
    return picked


def _draw_circular_map(genome: ParsedGenomeInput, req: GenomeMapRenderRequest) -> plt.Figure:
    g_len = max(1, genome.length)
    pos, gc_vals, skew_vals = _compute_gc_tracks(genome.sequence, g_len, req.gc_window)
    mean_gc = float(np.mean(gc_vals)) if len(gc_vals) else 50.0

    fig = plt.figure(figsize=(12.2, 8.8), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[3.6, 1.25], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    ax_leg = fig.add_subplot(gs[0, 1])
    ax.set_aspect("equal")
    ax.axis("off")

    def bp_to_deg(bp: float) -> float:
        return 90.0 - (bp / g_len) * 360.0

    # 1. 刻度骨架圆环
    r_axis = 0.56
    ax.add_patch(Circle((0, 0), r_axis, facecolor="none", edgecolor="#0f172a", linewidth=0.9))
    tick_step = 5000 if g_len <= 60000 else (10000 if g_len <= 140000 else 20000)
    for bp in range(0, g_len, tick_step):
        ang = math.radians(bp_to_deg(bp))
        ax.plot([(r_axis - 0.015) * math.cos(ang), r_axis * math.cos(ang)], [(r_axis - 0.015) * math.sin(ang), r_axis * math.sin(ang)], color="#0f172a", linewidth=0.7)
        if bp > 0:
            lbl = f"{bp // 1000} kb"
            draw_text(ax, (r_axis - 0.065) * math.cos(ang), (r_axis - 0.065) * math.sin(ang), lbl, fontsize=6.5, ha="center", va="center", color="#334155")

    # 中心基因组信息
    title_str = req.title or genome.name
    draw_text(ax, 0, 0.08, title_str, fontsize=10.0, fontweight="bold", ha="center", va="center", color="#0f172a")
    draw_text(ax, 0, -0.02, f"{g_len:,} bp", fontsize=9.0, ha="center", va="center", color="#334155")
    draw_text(ax, 0, -0.11, f"CDS: {len(genome.features)} | GC: {mean_gc:.1f}%", fontsize=7.6, ha="center", va="center", color="#475569")

    # 2. GC Content (%) 轨道
    if req.show_gc_content and len(pos) >= 3:
        r_gc_mid = 0.65
        ax.add_patch(Circle((0, 0), r_gc_mid, facecolor="none", edgecolor="#cbd5e1", linewidth=0.45, linestyle="--"))
        dev = np.clip((gc_vals - mean_gc) / max(8.0, np.std(gc_vals) * 2.5), -1.0, 1.0) * 0.055
        angs = np.array([math.radians(bp_to_deg(p)) for p in pos])
        r_vals = r_gc_mid + dev
        pts_all = list(zip(np.maximum(r_gc_mid, r_vals) * np.cos(angs), np.maximum(r_gc_mid, r_vals) * np.sin(angs), strict=True))
        pts_base = list(zip(r_gc_mid * np.cos(angs[::-1]), r_gc_mid * np.sin(angs[::-1]), strict=True))
        ax.add_patch(Polygon(pts_all + pts_base, closed=True, facecolor="#1e293b", edgecolor="none", alpha=0.82))
        pts_low = list(zip(np.minimum(r_gc_mid, r_vals) * np.cos(angs), np.minimum(r_gc_mid, r_vals) * np.sin(angs), strict=True))
        ax.add_patch(Polygon(pts_low + pts_base, closed=True, facecolor="#94a3b8", edgecolor="none", alpha=0.65))

    # 3. GC Skew (G-C)/(G+C) 轨道
    if req.show_gc_skew and len(pos) >= 3:
        r_sk_mid = 0.77
        ax.add_patch(Circle((0, 0), r_sk_mid, facecolor="none", edgecolor="#cbd5e1", linewidth=0.45, linestyle="--"))
        max_sk = max(0.15, float(np.max(np.abs(skew_vals))))
        dev_sk = np.clip(skew_vals / max_sk, -1.0, 1.0) * 0.052
        angs = np.array([math.radians(bp_to_deg(p)) for p in pos])
        pts_base = list(zip(r_sk_mid * np.cos(angs[::-1]), r_sk_mid * np.sin(angs[::-1]), strict=True))
        r_pos = np.maximum(r_sk_mid, r_sk_mid + dev_sk)
        r_neg = np.minimum(r_sk_mid, r_sk_mid + dev_sk)
        ax.add_patch(Polygon(list(zip(r_pos * np.cos(angs), r_pos * np.sin(angs), strict=True)) + pts_base, closed=True, facecolor="#16a34a", edgecolor="none", alpha=0.85))
        ax.add_patch(Polygon(list(zip(r_neg * np.cos(angs), r_neg * np.sin(angs), strict=True)) + pts_base, closed=True, facecolor="#7c3aed", edgecolor="none", alpha=0.85))

    # 4. 正链 (+) 与负链 (-) CDS 弧形色带
    r_plus, r_minus, w_cds = 0.92, 0.855, 0.046
    for f in genome.features:
        cat = normalize_phrog_category(f.category, f.function, f.product, f.feature_type)
        col = PHROG_CATEGORY_COLORS.get(cat, "#94a3b8")
        d1 = bp_to_deg(f.end)
        d2 = bp_to_deg(f.start)
        if d2 - d1 < 0.35:
            d1 = d2 - 0.35
        r_in = r_plus if f.strand != "-" else r_minus
        ax.add_patch(Wedge((0, 0), r_in + w_cds, d1, d2, width=w_cds, facecolor=col, edgecolor="white", linewidth=0.25, zorder=4))

    # 5. 径向无碰撞关键基因标注
    max_r = r_plus + w_cds + 0.03
    if req.show_labels:
        picks = _select_key_labels(genome.features, g_len, req.max_labels)
        raw_degs = [bp_to_deg(mid) for mid, _, _ in picks]
        # 按 360 度圆周角度排斥避让（逆时针顺序）
        degs_ordered = list(raw_degs)
        for _ in range(32):
            for idx in range(len(degs_ordered) - 1):
                diff = degs_ordered[idx] - degs_ordered[idx + 1]
                if diff < 7.5:
                    shift = (7.5 - diff) * 0.5
                    degs_ordered[idx] += shift
                    degs_ordered[idx + 1] -= shift
        r_anchor = r_plus + w_cds + 0.01
        r_label = r_plus + w_cds + 0.14
        for (mid, lbl_txt, lbl_col), d_out in zip(picks, degs_ordered, strict=True):
            a_true = math.radians(bp_to_deg(mid))
            a_out = math.radians(d_out)
            ax.plot(
                [r_anchor * math.cos(a_true), r_label * math.cos(a_out)],
                [r_anchor * math.sin(a_true), r_label * math.sin(a_out)],
                color="#64748b",
                linewidth=0.55,
                zorder=5,
            )
            norm_d = d_out % 360.0
            flip = 90.0 < norm_d < 270.0
            rot = norm_d + 180.0 if flip else norm_d
            ha = "right" if flip else "left"
            draw_text(
                ax,
                (r_label + 0.02) * math.cos(a_out),
                (r_label + 0.02) * math.sin(a_out),
                lbl_txt,
                fontsize=6.4,
                color=lbl_col if lbl_col != "#eeca3b" else "#854d0e",
                fontweight="bold",
                rotation=rot,
                rotation_mode="anchor",
                ha=ha,
                va="center",
                zorder=6,
            )
        max_r = r_label + 0.40

    ax.set_xlim(-max_r, max_r)
    ax.set_ylim(-max_r, max_r)

    # 6. 右侧 PHROGs + GC 图例栏
    ax_leg.axis("off")
    handles = [Patch(facecolor=PHROG_CATEGORY_COLORS[k], edgecolor="none", label=lbl) for k, lbl in PHROG_LEGEND_ORDER]
    if req.show_gc_skew:
        handles.append(Patch(facecolor="#16a34a", edgecolor="none", label="GC Skew (+)"))
        handles.append(Patch(facecolor="#7c3aed", edgecolor="none", label="GC Skew (-)"))
    if req.show_gc_content:
        handles.append(Patch(facecolor="#1e293b", edgecolor="none", label="GC Content above mean"))
    leg = ax_leg.legend(handles=handles, loc="center left", frameon=False, fontsize=7.6, handlelength=1.25, labelspacing=0.55)
    for t in leg.get_texts():
        t.set_color("#1e293b")
    draw_text(ax_leg, 0.04, 0.88, "Annotation & Tracks", fontsize=9.0, fontweight="bold", color="#0f172a")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.96, bottom=0.04)
    return fig


def _draw_linear_multitrack(genome: ParsedGenomeInput, req: GenomeMapRenderRequest) -> plt.Figure:
    g_len = max(1, genome.length)
    pos, gc_vals, skew_vals = _compute_gc_tracks(genome.sequence, g_len, req.gc_window)
    mean_gc = float(np.mean(gc_vals)) if len(gc_vals) else 50.0

    rows = [1.85]
    row_names = ["cds"]
    if req.show_gc_content:
        rows.append(0.75)
        row_names.append("gc")
    if req.show_gc_skew:
        rows.append(0.75)
        row_names.append("skew")
    rows.append(0.55)
    row_names.append("legend")

    fig = plt.figure(figsize=(14.0, 2.8 + len(rows) * 1.25), dpi=req.dpi, facecolor="white")
    gs = fig.add_gridspec(len(rows), 1, height_ratios=rows, hspace=0.20)
    ax_map = {name: fig.add_subplot(gs[idx, 0]) for idx, name in enumerate(row_names)}

    # 1. 顶部 CDS 基因箭头 + PHROGs 底条 + 多层阶梯防重叠标注
    ax_cds = ax_map["cds"]
    ax_cds.set_xlim(-g_len * 0.01, g_len * 1.01)
    ax_cds.set_ylim(-0.65, 2.35)
    ax_cds.axis("off")
    ax_cds.plot([0, g_len], [0.18, 0.18], color="#475569", linewidth=0.9, zorder=1)

    for f in genome.features:
        cat = normalize_phrog_category(f.category, f.function, f.product, f.feature_type)
        col = PHROG_CATEGORY_COLORS.get(cat, "#94a3b8")
        st, en = float(f.start), float(f.end)
        head = min((en - st) * 0.35, g_len * 0.008)
        y_mid, h = (0.18, 0.28)
        if f.strand != "-":
            pts = [(st, y_mid - h * 0.5), (en - head, y_mid - h * 0.5), (en, y_mid), (en - head, y_mid + h * 0.5), (st, y_mid + h * 0.5)]
        else:
            pts = [(en, y_mid - h * 0.5), (st + head, y_mid - h * 0.5), (st, y_mid), (st + head, y_mid + h * 0.5), (en, y_mid + h * 0.5)]
        ax_cds.add_patch(Polygon(pts, closed=True, facecolor="#cbd5e1" if cat == "unknown function" else col, edgecolor="#334155", linewidth=0.45, zorder=3))
        # 下贴 PHROGs 功能色带
        ax_cds.add_patch(plt.Rectangle((st, -0.06), max(1.0, en - st), 0.09, facecolor=col, edgecolor="none", zorder=3))

    # 坐标刻度
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        xp = g_len * frac
        ax_cds.plot([xp, xp], [-0.14, -0.08], color="#475569", linewidth=0.7)
        draw_text(ax_cds, xp, -0.22, f"{int(xp):,}", fontsize=6.8, ha="center", va="top", color="#334155")

    if req.show_labels:
        picks = _select_key_labels(genome.features, g_len, min(req.max_labels, 26))
        lane_last_x = [-1e9] * 5
        min_x_gap = g_len * 0.115
        for mid, txt, col in picks:
            chosen_lane = 0
            for ln in range(len(lane_last_x)):
                if mid - lane_last_x[ln] >= min_x_gap:
                    chosen_lane = ln
                    break
                if lane_last_x[ln] < lane_last_x[chosen_lane]:
                    chosen_lane = ln
            lane_last_x[chosen_lane] = mid
            y_lbl = 0.55 + chosen_lane * 0.36
            ax_cds.plot([mid, mid], [0.32, y_lbl - 0.04], color="#64748b", linewidth=0.5, zorder=2)
            draw_text(
                ax_cds,
                mid,
                y_lbl,
                txt,
                fontsize=6.6,
                ha="center",
                va="bottom",
                color=col if col not in ("#eeca3b", "#cbd5e1") else "#334155",
                fontweight="bold",
                zorder=5,
            )

    # 2. GC Content (%) 轨道
    if "gc" in ax_map:
        ax_g = ax_map["gc"]
        ax_g.set_xlim(-g_len * 0.01, g_len * 1.01)
        ax_g.axhline(mean_gc, color="#64748b", linewidth=0.65, linestyle="--")
        ax_g.fill_between(pos, mean_gc, gc_vals, where=(gc_vals >= mean_gc).tolist(), color="#f59e0b", alpha=0.78, interpolate=True)
        ax_g.fill_between(pos, mean_gc, gc_vals, where=(gc_vals < mean_gc).tolist(), color="#fde047", alpha=0.72, interpolate=True)
        ax_g.plot(pos, gc_vals, color="#b45309", linewidth=0.55)
        ax_g.set_ylabel("GC (%)", fontsize=7.5, fontweight="bold", color="#0f172a")
        ax_g.tick_params(axis="x", labelbottom=False, length=0)
        ax_g.tick_params(axis="y", labelsize=6.6, colors="#334155")
        ax_g.spines["top"].set_visible(False)
        ax_g.spines["right"].set_visible(False)
        draw_text(ax_g, g_len * 0.99, float(np.max(gc_vals)), f"Avg: {mean_gc:.2f}% | Range: [{float(np.min(gc_vals)):.1f}, {float(np.max(gc_vals)):.1f}]", fontsize=6.6, ha="right", va="top", color="#78350f")

    # 3. GC Skew 轨道
    if "skew" in ax_map:
        ax_s = ax_map["skew"]
        ax_s.set_xlim(-g_len * 0.01, g_len * 1.01)
        ax_s.axhline(0.0, color="#64748b", linewidth=0.65, linestyle="--")
        ax_s.fill_between(pos, 0.0, skew_vals, where=(skew_vals >= 0).tolist(), color="#16a34a", alpha=0.72, interpolate=True)
        ax_s.fill_between(pos, 0.0, skew_vals, where=(skew_vals < 0).tolist(), color="#9333ea", alpha=0.68, interpolate=True)
        ax_s.set_ylabel("GC skew", fontsize=7.5, fontweight="bold", color="#0f172a")
        ax_s.tick_params(axis="x", labelbottom=False, length=0)
        ax_s.tick_params(axis="y", labelsize=6.6, colors="#334155")
        ax_s.spines["top"].set_visible(False)
        ax_s.spines["right"].set_visible(False)

    # 4. 底部紧凑图例
    ax_lg = ax_map["legend"]
    ax_lg.axis("off")
    handles = [Patch(facecolor=PHROG_CATEGORY_COLORS[k], edgecolor="none", label=lbl) for k, lbl in PHROG_LEGEND_ORDER]
    ax_lg.legend(handles=handles, loc="center", ncol=6, frameon=False, fontsize=7.2, columnspacing=1.0, handlelength=1.1)

    title_str = req.title or f"{genome.name} ({g_len:,} bp)"
    draw_suptitle(fig, title_str, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.975)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.92, bottom=0.03)
    return fig


class GenomeMapRenderer:
    """单株噬菌体全基因组圆形/线性多轨图谱渲染入口。"""

    @staticmethod
    def render(genome: ParsedGenomeInput, out_dir: Path, req: GenomeMapRenderRequest) -> List[Path]:
        apply_journal_rcparams()
        if req.mode == "linear_multitrack":
            fig = _draw_linear_multitrack(genome, req)
        else:
            fig = _draw_circular_map(genome, req)
        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix=f"genome_map_{req.mode}",
            formats=req.formats,
            dpi=req.dpi,
        )
