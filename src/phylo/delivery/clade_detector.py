# -*- coding: utf-8 -*-
"""
单系支系（Monophyletic Clade）自动识别器
用于科研期刊风格进化树的背景阴影（Clade Shading）与 iTOL range 高亮文件生成。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode

_UNKNOWN_GENUS = frozenset({"", "unclassified", "unknown", "na", "n/a", "none", "nan", "-"})


@dataclass(frozen=True)
class MonophyleticClade:
    """单个极大同属单系支系的几何定位描述。"""

    node: "PhyloNode"
    taxon_name: str
    color: str
    leaf_start_idx: int
    leaf_end_idx: int
    contains_query: bool


def _collect_subtree_leaves(node: "PhyloNode") -> List["PhyloNode"]:
    out: List["PhyloNode"] = []

    def _walk(cur: "PhyloNode") -> None:
        if cur.is_leaf:
            out.append(cur)
        else:
            for ch in cur.children:
                _walk(ch)

    _walk(node)
    return out


def detect_monophyletic_clades(
    root: "PhyloNode",
    leaves: List["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    taxon_colors: Dict[str, str],
    rank_field: str = "genus",
) -> List[MonophyleticClade]:
    """
    自顶向下扫描非根内部节点，识别互不重叠的极大单系支系：
    - 子树叶子数量 >= 2；
    - 子树内不包含任何 outgroup 角色节点；
    - 所有已知有效分类名（rank_field: genus 或 family）仅唯一属于同一分类单元 T，
      且 T 必须存在于 taxon_colors 专属色板中（未配色归入 Others 的长尾类群绝不涂灰）；
    - 找到极大单系节点后停止向其子树继续下探，确保背景阴影严格不重叠。
    """
    leaf_idx_map = {id(lf): idx for idx, lf in enumerate(leaves)}
    clades: List[MonophyleticClade] = []

    def _inspect(node: "PhyloNode") -> None:
        if node.is_leaf:
            return
        if node is not root:
            sub_leaves = _collect_subtree_leaves(node)
            if len(sub_leaves) >= 2:
                has_outgroup = False
                has_query = False
                taxa: set[str] = set()
                indices: List[int] = []

                for lf in sub_leaves:
                    meta = node_metadata.get(lf.name) or {}
                    role = str(meta.get("role") or "").strip().lower()
                    if role == "outgroup":
                        has_outgroup = True
                        break
                    if role == "query":
                        has_query = True
                    taxon_val = str(meta.get(rank_field) or "").strip()
                    if taxon_val.lower() not in _UNKNOWN_GENUS:
                        taxa.add(taxon_val)
                    idx = leaf_idx_map.get(id(lf))
                    if idx is not None:
                        indices.append(idx)

                if not has_outgroup and len(taxa) == 1 and indices:
                    taxon = next(iter(taxa))
                    color = taxon_colors.get(taxon)
                    if color:
                        clades.append(
                            MonophyleticClade(
                                node=node,
                                taxon_name=taxon,
                                color=color,
                                leaf_start_idx=min(indices),
                                leaf_end_idx=max(indices),
                                contains_query=has_query,
                            )
                        )
                    return

        for ch in node.children:
            _inspect(ch)

    _inspect(root)
    return clades
