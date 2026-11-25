# -*- coding: utf-8 -*-
"""
Figure Studio 统一出版级期刊色板、PHROGs 功能色标与字体安全导出辅助工具。
复用 phylo/delivery/publication_palettes 的中英文双字体路由逻辑，确保 PDF 零缺字警告。
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import matplotlib
import matplotlib.text as mtext

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..phylo.delivery.publication_palettes import (  # noqa: E402
    PALETTES,
    get_journal_palette,
    pick_font_family,
    resolve_cjk_font,
    resolve_latin_font,
)

# 参照 LoVis4u / Pharokka / Nature Communications (2024-2026) 顶刊低饱和高区分度 PHROGs 配色
PHROG_CATEGORY_COLORS: Dict[str, str] = {
    "head and packaging": "#4c78a8",
    "connector": "#72b7b2",
    "tail": "#54a24b",
    "lysis": "#e45756",
    "DNA, RNA and nucleotide metabolism": "#eeca3b",
    "transcription regulation": "#b279a2",
    "integration and excision": "#f58518",
    "moron, auxiliary metabolic gene and host takeover": "#ff9da6",
    "anti-defence": "#1f2937",
    "other": "#9d755d",
    "unknown function": "#cbd5e1",
    "tRNA": "#0f172a",
}

PHROG_LEGEND_ORDER: Tuple[Tuple[str, str], ...] = (
    ("head and packaging", "Head and packaging"),
    ("connector", "Connector"),
    ("tail", "Tail"),
    ("lysis", "Lysis"),
    ("DNA, RNA and nucleotide metabolism", "DNA, RNA & metabolism"),
    ("transcription regulation", "Transcription regulation"),
    ("integration and excision", "Integration & excision"),
    ("moron, auxiliary metabolic gene and host takeover", "Moron / AMG / takeover"),
    ("anti-defence", "Anti-defence / defence"),
    ("unknown function", "Unknown / hypothetical"),
    ("tRNA", "tRNA"),
)


def normalize_phrog_category(
    category: str = "",
    function_str: str = "",
    product: str = "",
    feature_type: str = "CDS",
) -> str:
    """将 Pharokka / Prokka / GenBank 产物描述统一归一化至顶刊 PHROGs 功能大类。"""
    if feature_type.strip().lower() == "trna":
        return "tRNA"
    text = f"{category} {function_str} {product}".lower()
    if any(k in text for k in ("anti-def", "anti-crispr", "acr", "defense", "defence", "superinfection")):
        return "anti-defence"
    if any(k in text for k in ("head", "capsid", "terminase", "portal", "packaging", "scaffold", "prohead")):
        return "head and packaging"
    if any(k in text for k in ("connector", "neck", "collar", "adaptor", "stopper", "terminator")):
        return "connector"
    if any(k in text for k in ("tail", "tape measure", "baseplate", "spike", "fiber", "fibre", "sheath", "depolymerase")):
        return "tail"
    if any(k in text for k in ("lysis", "holin", "endolysin", "lysin", "spanin", "muramidase", "rz")):
        return "lysis"
    if any(
        k in text
        for k in (
            "integrase",
            "excision",
            "recombinase",
            "transposase",
            "repressor",
        )
    ):
        if "repressor" in text or "transcription" in text or "regulator" in text:
            return "transcription regulation"
        return "integration and excision"
    if any(k in text for k in ("transcription", "sigma", "regulator", "anti-repressor", "promoter", "rna polymerase")):
        return "transcription regulation"
    if any(
        k in text
        for k in (
            "dna",
            "rna",
            "nucleotide",
            "polymerase",
            "helicase",
            "primase",
            "ligase",
            "exonuclease",
            "endonuclease",
            "methyltransferase",
            "kinase",
            "reductase",
            "metabolism",
            "replication",
        )
    ):
        return "DNA, RNA and nucleotide metabolism"
    if any(k in text for k in ("moron", "auxiliary", "takeover", "toxin", "virulence")):
        return "moron, auxiliary metabolic gene and host takeover"
    if any(k in text for k in ("hypothetical", "unknown", "uncharacterized", "duf")) or not product.strip():
        return "unknown function"
    if category.strip().lower() in PHROG_CATEGORY_COLORS:
        return category.strip().lower()
    return "other"


def apply_journal_rcparams() -> None:
    """配置无衬线期刊字体、矢量嵌入与精简轴线风格，并静音字体子集化库冗长 INFO 日志。"""
    for noisy_name in ("fontTools", "fontTools.subset", "fontTools.ttLib"):
        logging.getLogger(noisy_name).setLevel(logging.WARNING)
    latin = resolve_latin_font()
    cjk = resolve_cjk_font()
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [latin, cjk, "DejaVu Sans"],
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
            "axes.edgecolor": "#cbd5e1",
            "axes.linewidth": 0.7,
        }
    )


def draw_text(ax: Any, x: float, y: float, text: str, **kwargs: Any) -> Any:
    """自动按文本字符集路由 Arial/CJK 字体并安全绘制文本。"""
    if "fontfamily" not in kwargs and "family" not in kwargs:
        kwargs["fontfamily"] = pick_font_family(text)
    return ax.text(x, y, text, **kwargs)


def draw_suptitle(fig: plt.Figure, text: str, **kwargs: Any) -> Any:
    """自动按文本字符集路由字体并绘制居中总标题，彻底消除中文 PDF 缺字告警。"""
    if "fontfamily" not in kwargs and "family" not in kwargs:
        kwargs["fontfamily"] = pick_font_family(text)
    return fig.suptitle(text, **kwargs)


def ensure_figure_text_fonts(fig: plt.Figure) -> int:
    """扫描整张图形中的所有 Text 元素，将含 CJK 字符的刻度、标题与图例自动切换为中文字体。"""
    latin = resolve_latin_font()
    cjk = resolve_cjk_font()
    if cjk == latin:
        return 0
    rebound = 0
    for text_obj in fig.findobj(mtext.Text):
        txt = text_obj.get_text()
        if not txt:
            continue
        if pick_font_family(txt) == cjk:
            text_obj.set_fontfamily(cjk)
            rebound += 1
    return rebound


def save_publication_figure(
    fig: plt.Figure,
    out_dir: Path,
    prefix: str,
    formats: Sequence[str] = ("pdf", "svg", "png"),
    dpi: int = 300,
) -> List[Path]:
    """按出版级规范多格式导出 PDF/SVG/PNG 并强制关闭图形释放内存。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_figure_text_fonts(fig)
    generated: List[Path] = []
    try:
        w_in, h_in = fig.get_size_inches()
        max_side_in = max(float(w_in), float(h_in), 1.0)
        for fmt in dict.fromkeys(f.strip().lower() for f in formats if f):
            if fmt not in ("pdf", "svg", "png", "eps"):
                continue
            fpath = out_dir / f"{prefix}.{fmt}"
            save_kw: Dict[str, Any] = {
                "bbox_inches": "tight",
                "pad_inches": 0.16,
                "facecolor": "white",
            }
            if fmt == "png":
                safe_dpi = min(dpi, max(96, int(11500 / max_side_in)))
                save_kw["dpi"] = safe_dpi
            fig.savefig(fpath, format=fmt, **save_kw)
            generated.append(fpath)
    finally:
        plt.close(fig)
    return generated


__all__ = [
    "PALETTES",
    "PHROG_CATEGORY_COLORS",
    "PHROG_LEGEND_ORDER",
    "apply_journal_rcparams",
    "draw_suptitle",
    "draw_text",
    "ensure_figure_text_fonts",
    "get_journal_palette",
    "normalize_phrog_category",
    "pick_font_family",
    "save_publication_figure",
]
