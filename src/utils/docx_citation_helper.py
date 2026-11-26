# -*- coding: utf-8 -*-
"""
Word (.docx) 学术报告自动引文助手 (DocxCitationHelper)

基于单一事实源 `src/resources/citations.json` 与 `src/utils/citations_loader.py`，
为基因组注释/分析类 Word 报告统一生成标准参考文献列表并支持一键写入 `python-docx` 文档。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .citations_loader import load_citations_payload

# 默认标准噬菌体注释报告引文工具顺序（与 scripts/citations_ops.json 书签对齐）
DEFAULT_ANNOTATION_REPORT_TOOL_IDS: Tuple[str, ...] = (
    "pharokka",
    "phanotate",
    "phold",
    "phrog",
    "phagescope",
    "card",
    "vfdb",
    "acranker",
)


def format_single_reference_entry(item: Dict[str, Any]) -> str:
    """将单条 citations.json 记录格式化为规范学术参考文献文本。"""
    authors = str(item.get("authors", "")).strip()
    year = str(item.get("year", "")).strip()
    title = str(item.get("title", "")).strip().rstrip(".")
    journal = str(item.get("journal", "")).strip().rstrip(".")
    doi = str(item.get("doi", "")).strip()
    pmid = str(item.get("pmid", "")).strip()

    parts = [f"{authors} {title}."]
    if journal and year:
        parts.append(f"{journal}. {year}.")
    elif journal:
        parts.append(f"{journal}.")
    elif year:
        parts.append(f"{year}.")
    if doi:
        parts.append(f"doi:{doi}.")
    if pmid:
        parts.append(f"PMID: {pmid}.")
    return " ".join(p for p in parts if p).strip()


def build_report_references_list(
    tool_ids: Optional[Iterable[str]] = None,
    module: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    返回 `[(reference_text, bookmark_name), ...]` 列表。
    当传入 `tool_ids` 时严格保持指定顺序，确保与 Word REF 域书签索引一致。
    """
    payload = load_citations_payload(module=module)
    tools: List[Dict[str, Any]] = payload.get("tools", [])

    if tool_ids is not None:
        by_id = {str(t.get("id", "")).strip().lower(): t for t in tools}
        ordered: List[Dict[str, Any]] = []
        for tid in tool_ids:
            key = str(tid).strip().lower()
            if key in by_id:
                ordered.append(by_id[key])
        tools = ordered

    result: List[Tuple[str, str]] = []
    for item in tools:
        text = format_single_reference_entry(item)
        bookmark = str(item.get("bookmark") or f"Ref_{item.get('id', 'tool')}")
        result.append((text, bookmark))
    return result


def append_citations_section(
    doc: Any,
    *,
    tool_ids: Optional[Iterable[str]] = None,
    module: Optional[str] = None,
    heading_text: str = "Methods & References",
    heading_level: int = 1,
    numbered: bool = True,
) -> List[Tuple[str, str]]:
    """
    向任意 `python-docx` Document 对象追加标准化的参考文献章节。
    返回实际写入的 `(text, bookmark)` 列表。
    """
    refs = build_report_references_list(tool_ids=tool_ids, module=module)
    if not refs:
        return []

    doc.add_heading(heading_text, level=heading_level)
    for idx, (text, _bookmark) in enumerate(refs, 1):
        line = f"[{idx}] {text}" if numbered else text
        doc.add_paragraph(line)
    return refs
