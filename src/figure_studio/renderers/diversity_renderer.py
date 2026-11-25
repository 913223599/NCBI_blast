# -*- coding: utf-8 -*-
"""
DiversityWindowRenderer - 同种/近缘种全基因组滑动窗口核苷酸多样性 (Pi) + 基因内部热图着色渲染器。
借鉴文献：Quinones-Olvera et al., Nature Communications (2024) 10.1038/s41467-024-47416-z Fig. 2c。
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from Bio.Align import PairwiseAligner
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Polygon, Rectangle

from ...phylo.runtime.resource_guard import get_safe_cpu_budget
from ..models import DiversityRenderRequest, GenomeFeatureItem, ParsedGenomeInput
from ..palette import apply_journal_rcparams, draw_text, save_publication_figure

_PI_CMAP_NATURE = LinearSegmentedColormap.from_list(
    "pi_div",
    ["#2b6cb0", "#7fb3d5", "#fef3c7", "#f97316", "#b91c1c"],
)
_PI_CMAP_MONO = LinearSegmentedColormap.from_list(
    "pi_mono",
    ["#e2e8f0", "#94a3b8", "#475569", "#0f172a"],
)


def _compute_window_pi_aligned(seqs: List[str], win: int, step: int) -> Tuple[np.ndarray, np.ndarray]:
    min_len = min(len(s) for s in seqs)
    centers: List[float] = []
    pis: List[float] = []
    for start in range(0, max(1, min_len - win + 1), step):
        end = min(min_len, start + win)
        col_pis: List[float] = []
        for pos in range(start, end):
            bases = [s[pos] for s in seqs if s[pos] in ("A", "C", "G", "T")]
            m = len(bases)
            if m <= 1:
                col_pis.append(0.0)
                continue
            cnt = Counter(bases)
            homo = sum((c / m) ** 2 for c in cnt.values())
            col_pis.append(max(0.0, (1.0 - homo) * (m / (m - 1))))
        centers.append((start + end) * 0.5)
        pis.append(float(np.mean(col_pis)) if col_pis else 0.0)
    return np.array(centers, dtype=float), np.array(pis, dtype=float)


def _kmers_pos(seq: str, k: int = 11) -> Dict[str, List[int]]:
    idx: Dict[str, List[int]] = {}
    for i in range(0, max(0, len(seq) - k + 1), 3):
        km = seq[i : i + k]
        idx.setdefault(km, []).append(i)
    return idx


def _compute_window_pi_unaligned(ref_seq: str, other_seqs: List[str], win: int, step: int) -> Tuple[np.ndarray, np.ndarray]:
    k = 11 if len(ref_seq) >= 100 else 6
    other_maps = [(_kmers_pos(s, k=k), s) for s in other_seqs if len(s) >= k]
    starts = list(range(0, max(1, len(ref_seq) - win + 1), step))

    def _eval_win(st: int) -> Tuple[float, float]:
        en = min(len(ref_seq), st + win)
        frag = ref_seq[st:en]
        if len(frag) < k or not other_maps:
            return (st + en) * 0.5, 0.0
        aligner = PairwiseAligner()
        aligner.mode = "global"
        aligner.match_score = 1.0
        aligner.mismatch_score = 0.0
        aligner.open_gap_score = -1.0
        aligner.extend_gap_score = -0.3

        divs: List[float] = []
        probe_kmers = [frag[p : p + k] for p in range(0, max(1, len(frag) - k + 1), max(4, k))]
        for kmap, oseq in other_maps:
            cand_starts: List[int] = []
            for p_idx, km in enumerate(probe_kmers):
                for hit in kmap.get(km, ())[:3]:
                    cand_starts.append(max(0, hit - p_idx * max(4, k)))
            if not cand_starts:
                divs.append(0.35)
                continue
            med_st = int(np.median(cand_starts))
            sub = oseq[med_st : min(len(oseq), med_st + len(frag) + 20)]
            if not sub:
                divs.append(0.35)
                continue
            sc = aligner.score(frag, sub)
            ident = max(0.0, min(1.0, sc / max(1, len(frag))))
            divs.append(max(0.0, 1.0 - ident))
        return (st + en) * 0.5, float(np.mean(divs)) if divs else 0.0

    workers = max(1, get_safe_cpu_budget() // 2)
    if workers > 1 and len(starts) > 12:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(_eval_win, starts))
    else:
        res = [_eval_win(s) for s in starts]
    return np.array([r[0] for r in res], dtype=float), np.array([r[1] for r in res], dtype=float)


def _short_gene_code(feat: GenomeFeatureItem, idx: int) -> str:
    tag = (feat.locus_tag or "").strip()
    if tag and len(tag) <= 8:
        return tag
    return f"P{idx + 1}"


class DiversityWindowRenderer:
    """全基因组核苷酸多样性 (Pi) 滑窗曲线 + 基因热图着色 + 功能对照表渲染器。"""

    @staticmethod
    def render(
        ref_genome: ParsedGenomeInput,
        sequences: List[Tuple[str, str]],
        out_dir: Path,
        req: DiversityRenderRequest,
    ) -> List[Path]:
        apply_journal_rcparams()
        clean_seqs = [s.strip().upper() for _, s in sequences if s and len(s.strip()) >= 50]
        if ref_genome.sequence and (not clean_seqs or clean_seqs[0] != ref_genome.sequence.upper()):
            clean_seqs = [ref_genome.sequence.upper()] + clean_seqs
        if len(clean_seqs) < 2:
            raise ValueError("核苷酸多样性图至少需要 2 条比较序列")

        ref_seq = clean_seqs[0]
        g_len = max(ref_genome.length, len(ref_seq), 1)
        win = min(req.window_size, max(50, g_len // 5))
        step = min(req.step_size, win)

        same_len = len({len(s) for s in clean_seqs}) == 1
        if same_len:
            centers, pi_vals = _compute_window_pi_aligned(clean_seqs, win, step)
        else:
            centers, pi_vals = _compute_window_pi_unaligned(ref_seq, clean_seqs[1:], win, step)

        max_pi = max(0.05, float(np.max(pi_vals)) * 1.15) if len(pi_vals) else 0.2
        pi_scale_max = max(0.05, float(np.percentile(pi_vals, 96)) * 1.1) if len(pi_vals) else 0.2
        cmap = _PI_CMAP_MONO if req.palette == "monochrome" else _PI_CMAP_NATURE

        show_table = bool(req.show_gene_table and ref_genome.features)
        fig_h = 6.4 if show_table else 4.2
        fig = plt.figure(figsize=(14.0, fig_h), dpi=req.dpi, facecolor="white")
        if show_table:
            gs = fig.add_gridspec(3, 1, height_ratios=[1.55, 1.15, 1.55], hspace=0.14)
            ax_pi = fig.add_subplot(gs[0, 0])
            ax_gene = fig.add_subplot(gs[1, 0])
            ax_tbl = fig.add_subplot(gs[2, 0])
        else:
            gs = fig.add_gridspec(2, 1, height_ratios=[1.55, 1.15], hspace=0.14)
            ax_pi = fig.add_subplot(gs[0, 0])
            ax_gene = fig.add_subplot(gs[1, 0])
            ax_tbl = None

        # 1. 上轨：滑动窗口核苷酸多样性面积图
        ax_pi.fill_between(centers, 0, pi_vals, color="#94a3b8" if req.palette == "monochrome" else "#cbd5e1", alpha=0.88)
        ax_pi.plot(centers, pi_vals, color="#334155", linewidth=0.85)
        ax_pi.set_xlim(0, g_len)
        ax_pi.set_ylim(0, max_pi)
        ax_pi.set_ylabel("Nucleotide diversity (Pi)", fontsize=8.0, fontweight="bold", color="#0f172a")
        ax_pi.spines["top"].set_visible(False)
        ax_pi.spines["right"].set_visible(False)
        ax_pi.tick_params(axis="x", labelbottom=False, length=0)
        ax_pi.tick_params(axis="y", labelsize=7.2, colors="#334155")

        # 2. 中轨：基因箭头内部裁剪逐窗口热图
        ax_gene.set_xlim(0, g_len)
        ax_gene.set_ylim(-0.65, 0.72)
        ax_gene.axis("off")
        ax_gene.plot([0, g_len], [0.0, 0.0], color="#334155", linewidth=1.0, zorder=1)

        half_step = max(20.0, step * 0.55)
        table_entries: List[Tuple[str, str]] = []
        for idx, feat in enumerate(ref_genome.features):
            st, en = float(feat.start), float(feat.end)
            head = min((en - st) * 0.35, g_len * 0.008)
            h = 0.34
            if feat.strand != "-":
                pts = [(st, -h * 0.5), (en - head, -h * 0.5), (en, 0.0), (en - head, h * 0.5), (st, h * 0.5)]
            else:
                pts = [(en, -h * 0.5), (st + head, -h * 0.5), (st, 0.0), (st + head, h * 0.5), (en, h * 0.5)]
            clip_poly = Polygon(pts, closed=True, facecolor="none", edgecolor="#0f172a", linewidth=0.65, zorder=5)
            ax_gene.add_patch(clip_poly)

            # 找出落入该基因内的窗口并用 clip_poly 裁剪填充热图细片
            mask = (centers >= st - half_step) & (centers <= en + half_step)
            sub_c = centers[mask]
            sub_p = pi_vals[mask]
            if len(sub_c) == 0 and len(centers) > 0:
                nearest = int(np.argmin(np.abs(centers - (st + en) * 0.5)))
                sub_c = np.array([(st + en) * 0.5])
                sub_p = np.array([pi_vals[nearest]])

            for wc, wp in zip(sub_c, sub_p, strict=True):
                rgba = cmap(float(np.clip(wp / pi_scale_max, 0.0, 1.0)))
                slice_rect = Rectangle((wc - half_step, -h * 0.6), half_step * 2.05, h * 1.2, facecolor=rgba, edgecolor="none", zorder=3)
                ax_gene.add_patch(slice_rect)
                slice_rect.set_clip_path(clip_poly)

            code = _short_gene_code(feat, idx)
            y_lbl = 0.27 if idx % 2 == 0 else -0.28
            va_lbl = "bottom" if idx % 2 == 0 else "top"
            if len(ref_genome.features) <= 36 or idx % 2 == 0:
                draw_text(ax_gene, (st + en) * 0.5, y_lbl, code, fontsize=6.4, fontweight="bold", ha="center", va=va_lbl, color="#0f172a", zorder=6)
            if feat.product and "hypothetical" not in feat.product.lower():
                table_entries.append((code, feat.product[:36]))

        # 坐标尺 + 右上渐变图例
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            xp = g_len * frac
            ax_gene.plot([xp, xp], [-0.46, -0.40], color="#475569", linewidth=0.7)
            draw_text(ax_gene, xp, -0.48, f"{xp / 1000.0:.1f} kb", fontsize=7.0, ha="center", va="top", color="#334155")

        # Pi 热图渐变图例放置于 ax_pi 右上角
        cb_x0, cb_w, cb_y0, cb_h = g_len * 0.78, g_len * 0.20, max_pi * 0.80, max_pi * 0.09
        for k in range(30):
            ax_pi.add_patch(Rectangle((cb_x0 + (k / 30) * cb_w, cb_y0), cb_w / 29, cb_h, facecolor=cmap((k + 0.5) / 30), edgecolor="none"))
        ax_pi.add_patch(Rectangle((cb_x0, cb_y0), cb_w, cb_h, facecolor="none", edgecolor="#64748b", linewidth=0.5))
        draw_text(ax_pi, cb_x0, cb_y0 + cb_h * 1.15, "Low divergence", fontsize=6.2, ha="left", va="bottom", color="#334155")
        draw_text(ax_pi, cb_x0 + cb_w, cb_y0 + cb_h * 1.15, "High hotspot", fontsize=6.2, ha="right", va="bottom", color="#991b1b")

        # 3. 底轨：4 列紧凑基因功能对照表
        if ax_tbl is not None:
            ax_tbl.axis("off")
            ax_tbl.set_xlim(0, 1)
            ax_tbl.set_ylim(0, 1)
            entries = table_entries[:24]
            if entries:
                ncols = 4
                nrows = max(1, int(np.ceil(len(entries) / ncols)))
                col_w = 0.24
                row_h = min(0.16, 0.88 / nrows)
                for idx, (code, prod) in enumerate(entries):
                    c = idx // nrows
                    r = idx % nrows
                    x0 = 0.01 + c * (col_w + 0.01)
                    y0 = 0.90 - (r + 1) * row_h
                    bg = "#f1f5f9" if r % 2 == 0 else "#ffffff"
                    ax_tbl.add_patch(Rectangle((x0, y0), col_w, row_h * 0.92, facecolor=bg, edgecolor="#e2e8f0", linewidth=0.35))
                    draw_text(ax_tbl, x0 + 0.008, y0 + row_h * 0.46, code, fontsize=6.6, fontweight="bold", va="center", color="#0f172a")
                    draw_text(ax_tbl, x0 + 0.048, y0 + row_h * 0.46, prod, fontsize=6.3, va="center", color="#334155")

        sub_info = f"{req.title}  (n = {len(clean_seqs)} genomes, window = {win} bp)" if req.title else f"n = {len(clean_seqs)} genomes"
        fig.suptitle(sub_info, fontsize=10.5, fontweight="bold", color="#0f172a", y=0.975)
        fig.subplots_adjust(left=0.06, right=0.98, top=0.90, bottom=0.04)
        return save_publication_figure(
            fig,
            out_dir=out_dir,
            prefix="diversity_window",
            formats=req.formats,
            dpi=req.dpi,
        )
