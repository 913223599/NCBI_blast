# -*- coding: utf-8 -*-
"""出版级进化树渲染基础拓扑、配色与样式解析辅助模块。"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..models.schemas import PublicationFigureRequest
from .clade_detector import MonophyleticClade
from .host_taxonomy import get_host_group_color, map_host_to_phylum
from .publication_palettes import (
    JournalPalette,
    is_formal_taxon_name,
    pick_font_family,
    resolve_latin_font,
)

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode

_OTHER_TAXON_COLOR = "#CBD5E1"
_UNCLASSIFIED_LIGHT_COLOR = "#E2E8F0"


def _configure_matplotlib_fonts() -> None:
    latin = resolve_latin_font()
    plt.rcParams["font.sans-serif"] = [
        latin,
        "Arial",
        "Helvetica",
        "DejaVu Sans",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["pdf.fonttype"] = 42


def _draw_text(ax: plt.Axes, x: float, y: float, text: str, **kwargs: Any) -> Any:
    """按文本字符集自动路由 Arial / 中文字体，彻底规避 PDF Type 42 缺字警告。"""
    kw = dict(kwargs)
    kw.setdefault("fontfamily", pick_font_family(text))
    return ax.text(x, y, text, **kw)


def _ladderize(node: "PhyloNode", ascending: bool = True) -> int:
    if node.is_leaf:
        return 1
    sized = [(ch, _ladderize(ch, ascending=ascending)) for ch in node.children]
    sized.sort(key=lambda item: item[1], reverse=not ascending)
    node.children = [item[0] for item in sized]
    return sum(item[1] for item in sized)


def _collect_leaves(node: "PhyloNode") -> List["PhyloNode"]:
    out: List["PhyloNode"] = []

    def _walk(cur: "PhyloNode") -> None:
        if cur.is_leaf:
            out.append(cur)
        else:
            for ch in cur.children:
                _walk(ch)

    _walk(node)
    return out


def _build_host_phylum_map(
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    leaf_phylum: Dict[str, str] = {}
    phylum_colors: Dict[str, str] = {}
    mono = palette.name == "monochrome"
    mono_shades = ("#374151", "#6B7280", "#9CA3AF", "#4B5563", "#D1D5DB", "#1F2937")

    for lf in leaves:
        host_raw = str((node_metadata.get(lf.name) or {}).get("host") or "").strip()
        phylum = map_host_to_phylum(host_raw)
        if phylum:
            leaf_phylum[lf.name] = phylum
            if phylum not in phylum_colors:
                phylum_colors[phylum] = (
                    mono_shades[len(phylum_colors) % len(mono_shades)]
                    if mono
                    else get_host_group_color(phylum)
                )
    return leaf_phylum, phylum_colors


def _compute_gc_range(
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
) -> Tuple[float, float]:
    vals = [
        float((node_metadata.get(lf.name) or {}).get("gc_content") or 0.0)
        for lf in leaves
    ]
    valid = [v for v in vals if v > 0.0]
    if not valid:
        return 0.0, 100.0
    low = max(0.0, math.floor((min(valid) - 4.0) / 5.0) * 5.0)
    high = min(100.0, math.ceil((max(valid) + 4.0) / 5.0) * 5.0)
    while high - low < 25.0:
        if low > 0.0:
            low = max(0.0, low - 5.0)
        if high - low < 25.0 and high < 100.0:
            high = min(100.0, high + 5.0)
        if low == 0.0 and high == 100.0:
            break
    return low, high


def _resolve_leaf_style(
    name: str,
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str = "genus",
) -> Tuple[str, str, float, str]:
    meta = node_metadata.get(name, {})
    role = str(meta.get("role") or "").strip().lower()
    taxon_val = str(meta.get(rank_field) or "").strip()
    if role == "query":
        return "query", palette.query_color, 1.45 * lw_scale, "-"
    if role == "outgroup":
        return "outgroup", palette.outgroup_color, 0.90 * lw_scale, "--"
    if taxon_val and taxon_val in taxon_colors:
        return "ref", taxon_colors[taxon_val], 0.90 * lw_scale, "-"
    if taxon_val and taxon_val in other_taxa:
        return "ref", palette.backbone_color, 0.80 * lw_scale, "-"
    return "ref", palette.backbone_color, 0.80 * lw_scale, "-"


def _subtree_branch_style(
    node: "PhyloNode",
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    other_taxa: Set[str],
    palette: JournalPalette,
    lw_scale: float,
    rank_field: str = "genus",
    color_monophyletic_branches: bool = False,
) -> Tuple[str, float, str]:
    if node.is_leaf:
        role, col, lw, ls = _resolve_leaf_style(
            node.name, node_metadata, taxon_colors, other_taxa, palette, lw_scale, rank_field
        )
        if role == "query":
            return palette.query_color, lw, ls
        if role == "outgroup":
            return palette.outgroup_color, lw, ls
        if color_monophyletic_branches and col in taxon_colors.values():
            return col, lw, "-"
        return palette.backbone_color, lw, "-"

    sub_leaves = _collect_leaves(node)
    roles = {
        str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower()
        for lf in sub_leaves
    }
    if roles == {"query"}:
        return palette.query_color, 1.45 * lw_scale, "-"
    if roles == {"outgroup"}:
        return palette.outgroup_color, 0.90 * lw_scale, "--"
    if color_monophyletic_branches and "outgroup" not in roles:
        taxa = {
            str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
            for lf in sub_leaves
            if str((node_metadata.get(lf.name) or {}).get(rank_field) or "").strip()
        }
        if len(taxa) == 1:
            t_name = next(iter(taxa))
            if t_name in taxon_colors:
                return taxon_colors[t_name], 0.92 * lw_scale, "-"
    return palette.backbone_color, 0.82 * lw_scale, "-"


def _compute_node_depths(
    root: "PhyloNode",
    use_branch_lengths: bool,
) -> Dict[int, float]:
    depths: Dict[int, float] = {id(root): 0.0}

    def _walk(cur: "PhyloNode", cur_x: float) -> None:
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


def _style_legend_entries(legend_obj: Any) -> None:
    for txt in legend_obj.get_texts():
        content = txt.get_text()
        txt.set_fontfamily(pick_font_family(content))
        if is_formal_taxon_name(content):
            txt.set_fontstyle("italic")


def _deconflict_query_angles(
    angles_deg: List[float],
    min_deg: float,
    max_deg: float,
    min_gap_deg: float = 5.4,
) -> List[float]:
    if len(angles_deg) <= 1:
        return list(angles_deg)
    res = list(angles_deg)
    for _ in range(36):
        moved = False
        for i in range(len(res) - 1):
            gap = res[i + 1] - res[i]
            if gap < min_gap_deg:
                shift = (min_gap_deg - gap) * 0.5
                res[i] = max(min_deg, res[i] - shift)
                res[i + 1] = min(max_deg, res[i + 1] + shift)
                moved = True
        if not moved:
            break
    return res


def _draw_section_header(ax: plt.Axes, y_top: float, title: str, line_w: float = 0.72) -> None:
    """绘制出版级带纤细底横线的图例小节标题（仿 Nature Communications Fig. 4a）。"""
    _draw_text(ax, 0.02, y_top, title, fontsize=8.4, fontweight="bold", color="#0f172a", va="top")
    ax.plot([0.02, 0.02 + line_w], [y_top - 0.023, y_top - 0.023], color="#334155", linewidth=0.65)


def _resolve_effective_clade_mode(req: PublicationFigureRequest) -> str:
    if not req.show_clade_shading:
        return "none"
    return req.clade_shading_mode


def _filter_clades_for_mode(
    clades: List[MonophyleticClade],
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    palette: JournalPalette,
    mode: str,
) -> List[MonophyleticClade]:
    if mode == "none":
        return []
    if mode == "query_clade":
        query_leaves = [
            lf
            for lf in leaves
            if str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower() == "query"
        ]
        if query_leaves:
            matched = [c for c in clades if c.contains_query]
            if matched:
                return matched
            # 若 Query 落在多属混合支系中，回溯寻找包含 Query 的最小非根姐妹簇作为目标支系高亮
            leaf_idx_map = {id(lf): idx for idx, lf in enumerate(leaves)}
            parent_map: Dict[int, Optional["PhyloNode"]] = {id(root): None}

            def _map_parents(cur: "PhyloNode") -> None:
                for ch in cur.children:
                    parent_map[id(ch)] = cur
                    _map_parents(ch)

            _map_parents(root)
            max_span = max(8, min(20, int(len(leaves) * 0.25)))
            fallback_clades: List[MonophyleticClade] = []
            seen_nodes: Set[int] = set()
            for qlf in query_leaves:
                cur = parent_map.get(id(qlf))
                chosen = None
                while cur is not None and cur is not root:
                    sub = _collect_leaves(cur)
                    has_og = any(
                        str((node_metadata.get(x.name) or {}).get("role") or "").strip().lower() == "outgroup"
                        for x in sub
                    )
                    if not has_og and 2 <= len(sub) <= max_span:
                        chosen = cur
                        break
                    if has_og or len(sub) > max_span:
                        break
                    cur = parent_map.get(id(cur))
                if chosen is not None and id(chosen) not in seen_nodes:
                    seen_nodes.add(id(chosen))
                    idxs = [leaf_idx_map[id(x)] for x in _collect_leaves(chosen) if id(x) in leaf_idx_map]
                    if idxs:
                        fallback_clades.append(
                            MonophyleticClade(
                                node=chosen,
                                taxon_name="Target Clade",
                                color=palette.taxon_colors[0],
                                leaf_start_idx=min(idxs),
                                leaf_end_idx=max(idxs),
                                contains_query=True,
                            )
                        )
            return fallback_clades
    return clades
