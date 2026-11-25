# -*- coding: utf-8 -*-
"""
科研期刊出版级进化树色板、科学比例尺、拉丁斜体判定与中英双字体路由模块。
对齐 Nature (NPG)、The Lancet、Okabe-Ito 色盲安全色板及 MBE 黑白极简印刷规范。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any, Dict, Iterable, List, Set, Tuple

import matplotlib.font_manager as fm

_LATIN_FONT_CANDIDATES = ("Arial", "Helvetica", "Liberation Sans", "DejaVu Sans")
_CJK_FONT_CANDIDATES = ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans")

_CJK_CHAR_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\ufe30-\ufe4f\u3000-\u303f\uff00-\uffef]")
_COUNT_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")

_NON_ITALIC_TAXON_TOKENS = frozenset(
    {
        "",
        "unclassified",
        "unknown",
        "others",
        "other",
        "query",
        "query phage",
        "query_phage",
        "outgroup",
        "ref",
        "na",
        "n/a",
        "none",
        "nan",
        "-",
        "this study",
        "archaea",
    }
)


@dataclass(frozen=True)
class JournalPalette:
    """科研期刊出版级固定配色方案。"""

    name: str
    taxon_colors: Tuple[str, ...]
    backbone_color: str
    query_color: str
    query_text_color: str
    query_bg_color: str
    outgroup_color: str
    unclassified_color: str
    size_bar_color: str
    gc_bar_color: str
    strong_dot_color: str
    moderate_dot_edge: str
    clade_alpha: float


PALETTES: Dict[str, JournalPalette] = {
    "nature": JournalPalette(
        name="nature",
        taxon_colors=(
            "#3C5488",
            "#00A087",
            "#4DBBD5",
            "#F39B7F",
            "#8491B4",
            "#91D1C2",
            "#7E6148",
            "#B09C85",
            "#E64B35",
            "#2E6B9E",
            "#E69F00",
            "#6A4C93",
        ),
        backbone_color="#1E293B",
        query_color="#DC0000",
        query_text_color="#991B1B",
        query_bg_color="#FEE2E2",
        outgroup_color="#64748B",
        unclassified_color="#E2E8F0",
        size_bar_color="#3C5488",
        gc_bar_color="#00A087",
        strong_dot_color="#0F172A",
        moderate_dot_edge="#334155",
        clade_alpha=0.13,
    ),
    "lancet": JournalPalette(
        name="lancet",
        taxon_colors=(
            "#00468B",
            "#42B540",
            "#0099B4",
            "#925E9F",
            "#FDAF91",
            "#AD002A",
            "#ADB6B6",
            "#1B1919",
            "#3B7A9E",
            "#6F99AD",
            "#E18727",
            "#20854E",
        ),
        backbone_color="#1B1919",
        query_color="#ED0000",
        query_text_color="#991B1B",
        query_bg_color="#FEE2E2",
        outgroup_color="#6B7280",
        unclassified_color="#E2E8F0",
        size_bar_color="#00468B",
        gc_bar_color="#0099B4",
        strong_dot_color="#1B1919",
        moderate_dot_edge="#4B5563",
        clade_alpha=0.12,
    ),
    "okabe_ito": JournalPalette(
        name="okabe_ito",
        taxon_colors=(
            "#0072B2",
            "#009E73",
            "#E69F00",
            "#56B4E9",
            "#CC79A7",
            "#D55E00",
            "#F0E442",
            "#332288",
            "#44AA99",
            "#882255",
            "#117733",
            "#999933",
        ),
        backbone_color="#1E293B",
        query_color="#D55E00",
        query_text_color="#9A3412",
        query_bg_color="#FFEDD5",
        outgroup_color="#64748B",
        unclassified_color="#E2E8F0",
        size_bar_color="#0072B2",
        gc_bar_color="#009E73",
        strong_dot_color="#0F172A",
        moderate_dot_edge="#334155",
        clade_alpha=0.13,
    ),
    "monochrome": JournalPalette(
        name="monochrome",
        taxon_colors=(
            "#1F2937",
            "#4B5563",
            "#6B7280",
            "#9CA3AF",
            "#374151",
            "#D1D5DB",
            "#111827",
            "#52525B",
        ),
        backbone_color="#111827",
        query_color="#111827",
        query_text_color="#111827",
        query_bg_color="#E5E7EB",
        outgroup_color="#6B7280",
        unclassified_color="#E5E7EB",
        size_bar_color="#374151",
        gc_bar_color="#6B7280",
        strong_dot_color="#111827",
        moderate_dot_edge="#374151",
        clade_alpha=0.10,
    ),
}


def get_journal_palette(name: str) -> JournalPalette:
    """按名称返回科研期刊配色方案，未知值回退 nature。"""
    return PALETTES.get((name or "nature").strip().lower(), PALETTES["nature"])


def get_available_font_names() -> set[str]:
    """收集当前环境中 Matplotlib 可解析的字体名称集合。"""
    return {entry.name for entry in fm.fontManager.ttflist}


def resolve_latin_font() -> str:
    """优先解析西文无衬线标准字体（Arial -> Helvetica -> DejaVu Sans）。"""
    available = get_available_font_names()
    for candidate in _LATIN_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return "DejaVu Sans"


def resolve_cjk_font() -> str:
    """优先解析支持简体中文的矢量字体（Microsoft YaHei -> SimHei -> Noto Sans CJK SC）。"""
    available = get_available_font_names()
    for candidate in _CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return "DejaVu Sans"


def pick_font_family(text: str) -> str:
    """依据文本内容路由字体：含 CJK 字符使用中文字体，纯西文/数字使用 Arial。"""
    if text and _CJK_CHAR_RE.search(text):
        return resolve_cjk_font()
    return resolve_latin_font()


def is_formal_taxon_name(label: str) -> bool:
    """判断分类标签是否为应以斜体排版的正式拉丁分类单元名称（属、科、菌门等）。"""
    raw = _COUNT_SUFFIX_RE.sub("", (label or "").strip())
    if not raw:
        return False
    low = raw.lower()
    if low in _NON_ITALIC_TAXON_TOKENS or low.startswith("outgroup"):
        return False
    if _CJK_CHAR_RE.search(raw):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9._\-\s]*$", raw))


def compute_nice_scale_bar(max_depth: float, target_ratio: float = 0.20) -> Tuple[float, str]:
    """
    基于标准 1-2-5 x 10^k 科学步长计算演化距离标尺长度与整洁文本。
    保证返回步长严格小于总树深的一半，彻底避免慢演化树标尺过宽的缺陷。
    """
    if not math.isfinite(max_depth) or max_depth <= 0:
        return 0.1, "0.1"

    raw = max_depth * max(0.05, min(0.45, target_ratio))
    exp = math.floor(math.log10(max(1e-12, raw)))

    candidates = []
    for factor_exp in (exp - 1, exp, exp + 1):
        b = 10.0**factor_exp
        for mult in (1.0, 2.0, 5.0):
            candidates.append(mult * b)

    valid = [c for c in candidates if c <= max_depth * 0.45]
    if valid:
        val = min(valid, key=lambda c: abs(c - raw))
    else:
        val = max_depth * 0.25

    decimals = max(0, -math.floor(math.log10(max(1e-12, val))) + 1)
    if val >= 1.0 and abs(val - round(val)) < 1e-9:
        text = str(round(val))
    elif val >= 1e-4:
        text = f"{val:.{min(6, decimals)}f}".rstrip("0").rstrip(".")
        if not text:
            text = "0"
    else:
        text = f"{val:.2e}"
    return val, text


def choose_macro_taxon_rank(
    leaves: Iterable[Any],
    node_metadata: Dict[str, Dict[str, Any]],
) -> str:
    """
    智能选择主分类色带层级：
    当大规模树（> 80 叶）存在 30 个以上分散属、且 >= 15% 的叶具有有效病毒科（family）注释时，
    自动切换至 `family` 层级以对齐 Nature / ViPTree 宏观测序视图，防止 90%+ 区域灰化。
    """
    leaf_list = list(leaves)
    if len(leaf_list) <= 80:
        return "genus"
    genera: Set[str] = set()
    family_hits = 0
    for lf in leaf_list:
        meta = node_metadata.get(lf.name) or {}
        g = str(meta.get("genus") or "").strip()
        if g and g.lower() not in _NON_ITALIC_TAXON_TOKENS:
            genera.add(g)
        fam = str(meta.get("family") or "").strip()
        if fam and fam.lower() not in _NON_ITALIC_TAXON_TOKENS:
            family_hits += 1
    if len(genera) > 30 and family_hits >= max(5, int(len(leaf_list) * 0.15)):
        return "family"
    return "genus"


def build_top_taxon_palette(
    leaves: Iterable[Any],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
    top_k: int = 10,
    rank_field: str = "genus",
) -> Tuple[Dict[str, str], Set[str], int, int]:
    """
    Top-K 分类收敛配色（支持 genus / family 任意层级，彻底避免超多类群循环取模撞色）：
    - 优先保留与 Query 叶位置邻近（前后 4 叶）的类群；
    - 其余名额按叶节点频次降序分配唯一色板色值；
    - 长尾低频类群统一归并为 `other_taxa`，空值计为 `unclassified_leaf_count`。
    """
    leaf_list = list(leaves)
    counts: Counter[str] = Counter()
    min_query_dist: Dict[str, int] = {}
    unclassified_count = 0

    query_indices = [
        idx
        for idx, lf in enumerate(leaf_list)
        if str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower() == "query"
    ]

    for idx, lf in enumerate(leaf_list):
        taxon = str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
        if not taxon or taxon.lower() in _NON_ITALIC_TAXON_TOKENS:
            unclassified_count += 1
            continue
        counts[taxon] += 1
        if query_indices:
            d = min(abs(idx - q_idx) for q_idx in query_indices)
            if d <= 4:
                prev = min_query_dist.get(taxon)
                if prev is None or d < prev:
                    min_query_dist[taxon] = d

    max_colors = min(max(1, top_k), len(palette.taxon_colors))
    ordered_priority = sorted(
        min_query_dist.keys(),
        key=lambda g: (min_query_dist[g], -counts[g], g),
    )
    ordered_all = [g for g, _ in counts.most_common()]

    chosen: list[str] = []
    for g in ordered_priority:
        if len(chosen) < max_colors and g not in chosen:
            chosen.append(g)
    for g in ordered_all:
        if len(chosen) < max_colors and g not in chosen:
            chosen.append(g)

    taxon_colors: Dict[str, str] = {
        g: palette.taxon_colors[i] for i, g in enumerate(chosen)
    }
    other_taxa = {g for g in counts if g not in taxon_colors}
    other_count = sum(counts[g] for g in other_taxa)
    return taxon_colors, other_taxa, other_count, unclassified_count


def build_top_genus_palette(
    leaves: Iterable[Any],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
    top_k: int = 10,
) -> Tuple[Dict[str, str], Set[str], int, int]:
    """向后兼容默认 genus 层的 Top-K 配色包装接口。"""
    return build_top_taxon_palette(leaves, node_metadata, palette, top_k=top_k, rank_field="genus")


def get_gc_colormap_stops(palette_name: str = "nature") -> Tuple[Tuple[int, int, int], ...]:
    """返回连续 GC% 热图的三段学术色阶锚点（低 -> 中 -> 高）。"""
    if (palette_name or "").strip().lower() == "monochrome":
        return (
            (241, 245, 249),
            (148, 163, 184),
            (30, 41, 59),
        )
    return (
        (232, 244, 248),  # 浅清冰蓝 (低 GC)
        (107, 174, 214),  # 天青蓝
        (33, 113, 181),   # 深海蓝
        (8, 48, 107),     # 深夜靛 (高 GC)
    )


def gc_value_to_hex(
    gc: float,
    gc_low: float,
    gc_high: float,
    palette_name: str = "nature",
) -> str:
    """将 GC% 连续映射至学术连续热图色阶 Hex（无值返回极浅灰底）。"""
    if gc <= 0.0:
        return "#F1F5F9"
    span = max(1e-6, gc_high - gc_low)
    t = max(0.0, min(1.0, (gc - gc_low) / span))
    stops = get_gc_colormap_stops(palette_name)
    scaled = t * (len(stops) - 1)
    idx = min(len(stops) - 2, math.floor(scaled))
    frac = scaled - idx
    c0, c1 = stops[idx], stops[idx + 1]
    r = round(c0[0] + (c1[0] - c0[0]) * frac)
    g = round(c0[1] + (c1[1] - c0[1]) * frac)
    b = round(c0[2] + (c1[2] - c0[2]) * frac)
    return f"#{r:02X}{g:02X}{b:02X}"


def compute_ring_elbow_leaders(
    ring_radii: List[float],
    start_deg: float,
    x_label: float,
) -> List[List[Tuple[float, float]]]:
    """
    为环形树右侧开口处的各个轨道标签生成严格零交叉的 3 点正交 L 形折线。
    几何原理：所有轨道从下沿同一射线出发 (r_0 < r_1 < ...)，故 x_0 < x_1 < ... 且 y_0 > y_1 > ...；
    标签按内->外顺序自上而下排布在 y_0 之上的槽位 (slot_y_0 > slot_y_1 > ... > y_0)，
    使每条折线垂直上升后再右拐指向标签，在平面上数学保证零交点。
    """
    if not ring_radii:
        return []

    anchor_rad = -math.radians(max(2.0, start_deg - 0.8))
    cos_a = math.cos(anchor_rad)
    sin_a = math.sin(anchor_rad)

    anchors = [(r * cos_a, r * sin_a) for r in ring_radii]
    y_inner_anchor = anchors[0][1]

    n_rings = len(ring_radii)
    if n_rings == 1:
        slot_ys = [max(0.0, y_inner_anchor + 0.05)]
    else:
        y_bot = y_inner_anchor + 0.045
        y_top = max(
            y_bot + 0.10,
            ring_radii[0] * math.sin(math.radians(max(4.0, start_deg))) * 0.78,
        )
        step = (y_top - y_bot) / (n_rings - 1)
        slot_ys = [y_top - idx * step for idx in range(n_rings)]

    end_x = max(x_label - 0.016, anchors[-1][0] + 0.03)
    return [
        [(ax_x, ax_y), (ax_x, sy), (end_x, sy)]
        for (ax_x, ax_y), sy in zip(anchors, slot_ys, strict=True)
    ]

