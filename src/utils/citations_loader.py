# -*- coding: utf-8 -*-
"""
生信工具学术引文库统一加载器 (CitationsLoader)
从 src/resources/citations.json 读取标准化工具文献元数据，
供核心 API 路由与分析/Word 报告生成模块复用，输出 Methods & Citations 段落或 BibTeX。
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("utils.citations_loader")

CITATIONS_FILE = Path(__file__).resolve().parent.parent / "resources" / "citations.json"


def load_citations_payload(module: Optional[str] = None) -> Dict[str, Any]:
    """读取 citations.json 并可选按 module 字段过滤。"""
    if not CITATIONS_FILE.is_file():
        return {"schema_version": "1.0", "description": "", "count": 0, "tools": []}
    try:
        payload = json.loads(CITATIONS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to load citations.json: %s", exc)
        return {"schema_version": "1.0", "description": "", "count": 0, "tools": []}

    tools: List[Dict[str, Any]] = payload.get("tools", [])
    if module and module.strip() and module.strip().lower() != "all":
        mod_key = module.strip().lower()
        tools = [item for item in tools if str(item.get("module", "")).lower() == mod_key]
    return {
        "schema_version": payload.get("schema_version", "1.0"),
        "description": payload.get("description", ""),
        "count": len(tools),
        "tools": tools,
    }


def format_methods_citations_text(
    tool_ids: Optional[Iterable[str]] = None,
    module: Optional[str] = None,
) -> str:
    """
    生成标准纯文本 Methods & Citations 参考文献段落，可直接嵌入分析报告或 Word 附录。
    """
    payload = load_citations_payload(module=module)
    tools = payload["tools"]
    if tool_ids is not None:
        wanted = {str(tid).strip().lower() for tid in tool_ids if str(tid).strip()}
        tools = [t for t in tools if str(t.get("id", "")).lower() in wanted]

    lines: List[str] = []
    for idx, item in enumerate(tools, 1):
        authors = item.get("authors", "")
        year = item.get("year", "")
        title = item.get("title", "")
        journal = item.get("journal", "")
        doi = item.get("doi", "")
        doi_part = f" https://doi.org/{doi}" if doi else ""
        lines.append(f"[{idx}] {authors} ({year}). {title}. {journal}.{doi_part}".strip())
    return "\n".join(lines)


def format_bibtex_entries(
    tool_ids: Optional[Iterable[str]] = None,
    module: Optional[str] = None,
) -> str:
    """生成标准 BibTeX 文献条目字符串。"""
    payload = load_citations_payload(module=module)
    tools = payload["tools"]
    if tool_ids is not None:
        wanted = {str(tid).strip().lower() for tid in tool_ids if str(tid).strip()}
        tools = [t for t in tools if str(t.get("id", "")).lower() in wanted]

    blocks: List[str] = []
    for item in tools:
        raw_key = f"{item.get('id', 'tool')}_{item.get('year', '0000')}"
        key = re.sub(r"[^a-zA-Z0-9_]", "_", raw_key)
        blocks.append(
            "\n".join(
                [
                    f"@article{{{key},",
                    f"  author  = {{{item.get('authors', '')}}},",
                    f"  title   = {{{item.get('title', '')}}},",
                    f"  journal = {{{item.get('journal', '')}}},",
                    f"  year    = {{{item.get('year', '')}}},",
                    f"  doi     = {{{item.get('doi', '')}}}",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks)
