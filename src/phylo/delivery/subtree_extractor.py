# -*- coding: utf-8 -*-
"""
Query 邻域局部聚焦子树提取器（Subtree Extractor）
用于从数百至上千叶的宏观进化树中自动截取包含全部待鉴定 Query 株及近缘 ICTV 参考株、
局部外群的高可读性聚焦子树（20–35 叶），支撑顶刊常见 Panel a (全局) + Panel b (局部详图) 复合出版出图。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

if TYPE_CHECKING:
    from ..pipeline.postprocess import PhyloNode


def _clone_node(node: "PhyloNode", parent: Optional["PhyloNode"] = None) -> "PhyloNode":
    """深拷贝 PhyloNode 子树并重建 parent 引用，确保绝不污染原树对象。"""
    from ..pipeline.postprocess import PhyloNode

    cloned = PhyloNode(name=node.name, length=node.length, children=[], parent=parent)
    for ch in node.children:
        cloned.children.append(_clone_node(ch, parent=cloned))
    return cloned


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


def _build_parent_and_leaf_maps(
    root: "PhyloNode",
) -> Tuple[Dict[int, Optional["PhyloNode"]], Dict[int, int]]:
    parent_map: Dict[int, Optional["PhyloNode"]] = {id(root): None}
    leaf_count_map: Dict[int, int] = {}

    def _walk(cur: "PhyloNode") -> int:
        if cur.is_leaf:
            leaf_count_map[id(cur)] = 1
            return 1
        cnt = 0
        for ch in cur.children:
            parent_map[id(ch)] = cur
            cnt += _walk(ch)
        leaf_count_map[id(cur)] = cnt
        return cnt

    _walk(root)
    return parent_map, leaf_count_map


def _find_mrca(
    nodes: List["PhyloNode"],
    parent_map: Dict[int, Optional["PhyloNode"]],
) -> "PhyloNode":
    if len(nodes) == 1:
        return nodes[0]

    def _ancestors(node: "PhyloNode") -> List["PhyloNode"]:
        chain: List["PhyloNode"] = []
        cur: Optional["PhyloNode"] = node
        while cur is not None:
            chain.append(cur)
            cur = parent_map.get(id(cur))
        return chain

    common = _ancestors(nodes[0])
    common_set = {id(n) for n in common}
    for n in nodes[1:]:
        anc_set = {id(a) for a in _ancestors(n)}
        common_set &= anc_set
    for candidate in common:
        if id(candidate) in common_set:
            return candidate
    return common[-1]


def _is_ancestor(
    cand: "PhyloNode",
    target: "PhyloNode",
    parent_map: Dict[int, Optional["PhyloNode"]],
) -> bool:
    cur: Optional["PhyloNode"] = target
    while cur is not None:
        if cur is cand:
            return True
        cur = parent_map.get(id(cur))
    return False


def _extract_single_cluster_subtree(
    mrca: "PhyloNode",
    parent_map: Dict[int, Optional["PhyloNode"]],
    leaf_count_map: Dict[int, int],
    max_leaves: int,
    min_leaves: int,
) -> Tuple["PhyloNode", Set[str]]:
    from ..pipeline.postprocess import PhyloNode

    chosen = mrca
    while True:
        p = parent_map.get(id(chosen))
        if p is None or leaf_count_map[id(p)] > max_leaves:
            break
        chosen = p

    cloned_chosen = _clone_node(chosen)
    chosen_names = {lf.name for lf in _collect_leaves(cloned_chosen)}

    if len(chosen_names) < min_leaves:
        p = parent_map.get(id(chosen))
        if p is not None and p.children:
            sibling_leaves: List["PhyloNode"] = []
            for sib in p.children:
                if sib is not chosen:
                    sibling_leaves.extend(_collect_leaves(sib))
            need = max(1, min(max_leaves - len(chosen_names), min_leaves - len(chosen_names)))
            sampled = sibling_leaves[:need]
            if sampled:
                wrapper = PhyloNode(name=p.name, length=0.0)
                cloned_chosen.parent = wrapper
                wrapper.children.append(cloned_chosen)
                for slf in sampled:
                    wrapper.children.append(
                        PhyloNode(name=slf.name, length=max(0.02, slf.length), parent=wrapper)
                    )
                    chosen_names.add(slf.name)
                cloned_chosen = wrapper

    return cloned_chosen, chosen_names


def _collect_dispersed_anchors(
    query_leaves: Sequence["PhyloNode"],
    parent_map: Dict[int, Optional["PhyloNode"]],
    leaf_count_map: Dict[int, int],
    per_quota: int,
) -> List["PhyloNode"]:
    anchor_nodes: List["PhyloNode"] = []
    for qlf in query_leaves:
        cur = qlf
        while True:
            p = parent_map.get(id(cur))
            if p is None or leaf_count_map[id(p)] > per_quota:
                break
            cur = p
        if cur.is_leaf:
            p = parent_map.get(id(cur))
            if p is not None and leaf_count_map[id(p)] <= max(per_quota + 4, 10):
                cur = p
        anchor_nodes.append(cur)

    unique_anchors: List["PhyloNode"] = []
    for cand in anchor_nodes:
        if any(a is not cand and _is_ancestor(a, cand, parent_map) for a in anchor_nodes):
            continue
        if all(u is not cand for u in unique_anchors):
            unique_anchors.append(cand)
    return unique_anchors


def _assemble_dispersed_subtree(
    unique_anchors: Sequence["PhyloNode"],
    outgroup_leaves: Sequence["PhyloNode"],
    node_metadata: Dict[str, Dict[str, Any]],
    max_leaves: int,
) -> Tuple["PhyloNode", Set[str]]:
    from ..pipeline.postprocess import PhyloNode

    composite_root = PhyloNode(name="", length=0.0)
    focused_names: Set[str] = set()
    budget = max_leaves - min(2, len(outgroup_leaves))

    for anc in unique_anchors:
        sub_leaves = _collect_leaves(anc)
        if len(focused_names) + len(sub_leaves) <= budget or not focused_names:
            sub_clone = _clone_node(anc, parent=composite_root)
            if sub_clone.length <= 0:
                sub_clone.length = 0.05
            composite_root.children.append(sub_clone)
            focused_names.update(lf.name for lf in sub_leaves)
            continue
        for lf in sub_leaves:
            if str((node_metadata.get(lf.name) or {}).get("role") or "").lower() == "query":
                composite_root.children.append(
                    PhyloNode(name=lf.name, length=max(0.02, lf.length), parent=composite_root)
                )
                focused_names.add(lf.name)

    for og in outgroup_leaves[:2]:
        if og.name not in focused_names:
            composite_root.children.append(
                PhyloNode(name=og.name, length=max(0.05, og.length), parent=composite_root)
            )
            focused_names.add(og.name)

    if len(composite_root.children) == 1:
        only = composite_root.children[0]
        only.parent = None
        return only, focused_names

    return composite_root, focused_names


def extract_query_focus_subtree(
    root: "PhyloNode",
    node_metadata: Dict[str, Dict[str, Any]],
    max_leaves: int = 32,
    min_leaves: int = 12,
) -> Tuple["PhyloNode", Set[str]]:
    """
    围绕待鉴定 Query 节点向上回溯提取可读性最优的聚焦局部子树：
    - 若全树叶数 <= max_leaves，直接深拷贝整棵树返回；
    - 若 Query 集中在单个大支系（MRCA 叶数 <= max_leaves），从 MRCA 向上扩展到不超过 max_leaves 的最高祖先；
    - 若多个 Query 分散在远缘支系，为每个 Query 聚类独立截取近缘微支并挂接局部外群，保证所有 Query 全部入镜。
    """
    all_leaves = _collect_leaves(root)
    if len(all_leaves) <= max_leaves:
        return _clone_node(root), {lf.name for lf in all_leaves}

    parent_map, leaf_count_map = _build_parent_and_leaf_maps(root)
    query_leaves = [
        lf
        for lf in all_leaves
        if str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower() == "query"
    ] or [all_leaves[0]]
    outgroup_leaves = [
        lf
        for lf in all_leaves
        if str((node_metadata.get(lf.name) or {}).get("role") or "").strip().lower() == "outgroup"
    ]

    mrca = _find_mrca(query_leaves, parent_map)
    if leaf_count_map.get(id(mrca), 0) <= max_leaves:
        return _extract_single_cluster_subtree(mrca, parent_map, leaf_count_map, max_leaves, min_leaves)

    per_quota = max(5, (max_leaves - min(2, len(outgroup_leaves))) // max(1, len(query_leaves)))
    unique_anchors = _collect_dispersed_anchors(query_leaves, parent_map, leaf_count_map, per_quota)
    return _assemble_dispersed_subtree(unique_anchors, outgroup_leaves, node_metadata, max_leaves)
