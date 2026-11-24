# -*- coding: utf-8 -*-
"""
噬菌体分类学叶节点标签统一格式化与历史任务元数据自动补全工具。
发表规范默认格式: `Escherichia phage T5 (AY587007)`（实际名称 + 登录号），
同时支持切换 `仅实际名称` (`name`) 与 `仅登录号` (`accession`)。
"""
import re
from typing import Any, Dict, List, Optional

from ..models.schemas import LabelFormatType

_SUFFIX_RE = re.compile(
    r"(?:,\s*(?:complete|partial)\s+(?:genome|cds|sequence)"
    r"|\b(?:complete|partial)\s+(?:genome|cds|sequence))\s*\.?$",
    re.IGNORECASE,
)


def clean_phage_description(desc: Optional[str]) -> str:
    """清洗 INPHARED/GenBank description 末尾冗余的完整基因组后缀与多余空白。"""
    text = re.sub(r"\s+", " ", (desc or "").strip())
    if not text:
        return ""
    cleaned = _SUFFIX_RE.sub("", text).strip(" ,;.")
    return cleaned or text


def format_leaf_label(
    accession: str,
    meta: Optional[Dict[str, Any]],
    label_format: LabelFormatType = "name_acc",
) -> str:
    """
    依据论文发表规范格式化树叶节点显示文本：
    - `accession`: 仅返回原始登录号 / 样本 ID
    - `query` 角色: 始终保留原始样本名称
    - `name`: 仅返回清洗后的实际噬菌体名称
    - `name_acc` (默认): `实际名称 (登录号)`
    """
    acc = (accession or "").strip()
    if not acc:
        return ""
    if label_format == "accession":
        return acc

    m = meta or {}
    if str(m.get("role") or "").strip().lower() == "query":
        return acc

    desc = clean_phage_description(str(m.get("description") or ""))
    if not desc or desc.lower() == acc.lower():
        return acc

    if label_format == "name":
        return desc

    # name_acc: 若登录号已包含在描述中，避免重复拼接
    if acc in desc:
        return desc
    return f"{desc} ({acc})"


def enrich_node_metadata(
    node_metadata: Optional[Dict[str, Dict[str, Any]]],
    leaf_names: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    从本地 INPHARED SQLite 索引批量回填缺失的 description / genus / host / genome_length / gc_content，
    使已保存的历史任务无需重跑即可展示完整的实际噬菌体名称。
    """
    enriched: Dict[str, Dict[str, Any]] = {
        k: dict(v) for k, v in (node_metadata or {}).items()
    }
    candidate_keys: List[str] = list(enriched.keys())
    if leaf_names:
        seen = set(candidate_keys)
        for lf in leaf_names:
            if lf and lf not in seen:
                candidate_keys.append(lf)
                seen.add(lf)

    missing_accs: List[str] = []
    for acc in candidate_keys:
        meta = enriched.get(acc, {})
        if str(meta.get("role") or "").strip().lower() == "query":
            continue
        if not str(meta.get("description") or "").strip():
            missing_accs.append(acc)

    if not missing_accs:
        return enriched

    try:
        from ..engines.ani.inphared_index import get_inphared_index

        idx = get_inphared_index()
        if not idx.is_available():
            return enriched
        records = idx.get_by_accessions(missing_accs)
    except Exception:
        return enriched

    for acc, rec in records.items():
        cur = dict(enriched.get(acc) or {})
        clean_desc = clean_phage_description(rec.description)
        if clean_desc and not cur.get("description"):
            cur["description"] = clean_desc
        if rec.genus and not cur.get("genus"):
            cur["genus"] = rec.genus
        if rec.family and not cur.get("family"):
            cur["family"] = rec.family
        if rec.host and not cur.get("host"):
            cur["host"] = rec.host
        if rec.genome_length and not cur.get("genome_length"):
            cur["genome_length"] = rec.genome_length
        if rec.gc_content and not cur.get("gc_content"):
            cur["gc_content"] = rec.gc_content
        if "role" not in cur:
            cur["role"] = "ictv_rep" if rec.is_ictv_classified else "neighbor"
        enriched[acc] = cur

    return enriched
