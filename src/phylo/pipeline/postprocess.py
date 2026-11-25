# -*- coding: utf-8 -*-
"""
PostProcess - 纯 Python Newick 解析、中点/外群定根、边支持率迁移与拓扑质量统计
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models.schemas import TreeMetrics


@dataclass
class PhyloNode:
    name: str = ""
    length: float = 0.0
    children: List["PhyloNode"] = field(default_factory=list)
    parent: Optional["PhyloNode"] = None

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


def _quote_label(label: str) -> str:
    if not label:
        return ""
    if re.search(r"[():,;\[\]'\s]", label):
        return "'" + label.replace("'", "''") + "'"
    return label


def parse_newick(newick: str) -> PhyloNode:
    """健壮的 Newick 解析器（支持单引号转义、科学计数法枝长、内部节点支持率）。"""
    text = (newick or "").strip()
    if not text:
        raise ValueError("Newick 字符串为空")
    if text.endswith(";"):
        text = text[:-1].strip()

    idx = 0
    n = len(text)

    def _read_label() -> str:
        nonlocal idx
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n:
            return ""
        if text[idx] == "'":
            idx += 1
            chars: List[str] = []
            while idx < n:
                ch = text[idx]
                if ch == "'":
                    if idx + 1 < n and text[idx + 1] == "'":
                        chars.append("'")
                        idx += 2
                        continue
                    idx += 1
                    break
                chars.append(ch)
                idx += 1
            return "".join(chars)
        start = idx
        while idx < n and text[idx] not in "(),:;":
            idx += 1
        return text[start:idx].strip()

    def _parse_node(parent: Optional[PhyloNode]) -> PhyloNode:
        nonlocal idx
        node = PhyloNode(parent=parent)
        while idx < n and text[idx].isspace():
            idx += 1
        if idx < n and text[idx] == "(":
            idx += 1
            while idx < n:
                child = _parse_node(node)
                node.children.append(child)
                while idx < n and text[idx].isspace():
                    idx += 1
                if idx < n and text[idx] == ",":
                    idx += 1
                    continue
                if idx < n and text[idx] == ")":
                    idx += 1
                    break
                break
        node.name = _read_label()
        while idx < n and text[idx].isspace():
            idx += 1
        if idx < n and text[idx] == ":":
            idx += 1
            start = idx
            while idx < n and text[idx] not in "(),;":
                idx += 1
            raw_len = text[start:idx].strip()
            try:
                node.length = max(0.0, float(raw_len))
            except ValueError:
                node.length = 0.0
        return node

    root = _parse_node(None)
    return root


def to_newick(root: PhyloNode, is_root: bool = True) -> str:
    if root.is_leaf:
        lbl = _quote_label(root.name)
        return lbl if is_root else f"{lbl}:{root.length:.6f}"
    inner = ",".join(to_newick(c, is_root=False) for c in root.children)
    lbl = _quote_label(root.name)
    if is_root:
        return f"({inner}){lbl};"
    return f"({inner}){lbl}:{root.length:.6f}"


def _all_nodes(root: PhyloNode) -> List[PhyloNode]:
    res: List[PhyloNode] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        res.append(cur)
        for c in reversed(cur.children):
            stack.append(c)
    return res


def extract_leaf_names(newick: str) -> List[str]:
    """从 Newick 字符串精确提取所有叶节点名称（按遍历顺序）。"""
    root = parse_newick(newick)
    return [n.name for n in _all_nodes(root) if n.is_leaf and n.name]


def _farthest_from(start: PhyloNode) -> Tuple[PhyloNode, float, Dict[int, PhyloNode]]:
    """无向树 BFS/DFS 求距 start 最远节点，并记录父指针映射用于回溯路径。"""
    visited: set[int] = {id(start)}
    dist_map: Dict[int, float] = {id(start): 0.0}
    prev_map: Dict[int, PhyloNode] = {}
    stack: List[PhyloNode] = [start]
    best_node = start
    best_dist = 0.0

    while stack:
        cur = stack.pop()
        cur_d = dist_map[id(cur)]
        if cur_d > best_dist:
            best_dist = cur_d
            best_node = cur
        neighbors: List[Tuple[PhyloNode, float]] = []
        if cur.parent is not None:
            neighbors.append((cur.parent, cur.length))
        for ch in cur.children:
            neighbors.append((ch, ch.length))
        for nb, w in neighbors:
            nid = id(nb)
            if nid not in visited:
                visited.add(nid)
                dist_map[nid] = cur_d + max(0.0, w)
                prev_map[nid] = cur
                stack.append(nb)

    return best_node, best_dist, prev_map


def _reorient_at(target_node: PhyloNode) -> None:
    """将树重新以 target_node 为根定向（翻转其祖先路径上的边方向并迁移支持率）。"""
    path: List[PhyloNode] = []
    cur: Optional[PhyloNode] = target_node
    while cur is not None:
        path.append(cur)
        cur = cur.parent
    # path: [target_node, ..., old_root]
    for i in range(len(path) - 1, 0, -1):
        old_p = path[i]
        child = path[i - 1]
        if child in old_p.children:
            old_p.children.remove(child)
        edge_len = child.length
        child_was_leaf = child.is_leaf
        edge_name = child.name if not child_was_leaf else ""
        child.children.append(old_p)
        old_p.parent = child
        old_p.length = edge_len
        if not old_p.is_leaf and edge_name:
            old_p.name = edge_name
        child.parent = None
        child.length = 0.0
        if not child_was_leaf:
            child.name = ""


def _split_edge_root(u: PhyloNode, v: PhyloNode, dist_from_u: float) -> PhyloNode:
    """将无向边 (u, v) 劈裂并插入新二叉树根，保留边总长与支持率。"""
    if v.parent is u:
        edge_len = max(0.0, v.length)
    elif u.parent is v:
        edge_len = max(0.0, u.length)
    else:
        edge_len = max(0.0, v.length)

    if u.is_leaf and v.is_leaf:
        d_u = max(0.0, min(edge_len, dist_from_u))
        d_v = max(0.0, edge_len - d_u)
        new_root = PhyloNode(name="", length=0.0, parent=None)
        u.parent = new_root
        u.length = d_u
        v.parent = new_root
        v.length = d_v
        new_root.children = [u, v]
        return new_root

    # 绝不以叶子作为 _reorient_at 临时根，保证叶子标签与拓扑结构完全不被污染
    if u.is_leaf and not v.is_leaf:
        u, v = v, u
        dist_from_u = edge_len - dist_from_u

    _reorient_at(u)
    if v in u.children:
        u.children.remove(v)
    edge_len = max(0.0, v.length)
    d_u = max(0.0, min(edge_len, dist_from_u))
    d_v = max(0.0, edge_len - d_u)

    new_root = PhyloNode(name="", length=0.0, parent=None)
    u.parent = new_root
    u.length = d_u
    v.parent = new_root
    v.length = d_v
    new_root.children = [u, v]

    # 若旧根节点退化为仅 1 个子节点且非叶，折叠之
    for side in (u, v):
        if not side.is_leaf and len(side.children) == 1:
            only_child = side.children[0]
            only_child.length += side.length
            only_child.parent = new_root
            idx = new_root.children.index(side)
            new_root.children[idx] = only_child

    return new_root


def reroot_midpoint(newick: str) -> str:
    """中点定根 (Midpoint Rooting)：寻找演化直径并在中点劈裂边。"""
    root = parse_newick(newick)
    leaves = [n for n in _all_nodes(root) if n.is_leaf]
    if len(leaves) < 2:
        return to_newick(root)

    tip_a, _, _ = _farthest_from(leaves[0])
    tip_b, total_dist, prev_map = _farthest_from(tip_a)
    if total_dist <= 0:
        return to_newick(root)

    # 重建 tip_a -> tip_b 路径
    path: List[PhyloNode] = []
    cur: Optional[PhyloNode] = tip_b
    while cur is not None:
        path.append(cur)
        cur = prev_map.get(id(cur))
    path.reverse()

    half = total_dist / 2.0
    acc = 0.0
    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        # 计算 u-v 边长
        if v.parent is u:
            edge_len = v.length
        elif u.parent is v:
            edge_len = u.length
        else:
            edge_len = 0.0
        if acc + edge_len >= half or i == len(path) - 2:
            new_root = _split_edge_root(u, v, half - acc)
            return to_newick(new_root)
        acc += edge_len

    return to_newick(root)


def reroot_outgroup(newick: str, outgroup_name: str) -> str:
    """按指定外群叶子名重定根（在该叶子的入边中点插入新根）。"""
    root = parse_newick(newick)
    target: Optional[PhyloNode] = None
    for node in _all_nodes(root):
        if node.is_leaf and node.name == outgroup_name:
            target = node
            break
    if target is None or target.parent is None:
        raise ValueError(f"未在树中找到外群节点: {outgroup_name}")

    parent = target.parent
    half_len = target.length * 0.5
    new_root = _split_edge_root(parent, target, half_len)
    return to_newick(new_root)


def _parse_dual_support(label: str) -> Tuple[Optional[float], Optional[float]]:
    """
    解析支持率标签：
    - '98.5/100' -> (alrt=98.5, ufboot=100.0)
    - '96' 或 '0.96' -> (alrt=None, ufboot=96.0)
    """
    clean = (label or "").strip()
    if not clean:
        return None, None
    if "/" in clean:
        parts = clean.split("/", 1)
        try:
            a = float(parts[0].strip())
            b = float(parts[1].strip())
            if 0.0 <= a <= 100.0 and 0.0 <= b <= 100.0:
                return a, b
        except ValueError:
            return None, None
    try:
        val = float(clean)
        if 0.0 <= val <= 1.0 and "." in clean:
            val *= 100.0
        if 0.0 <= val <= 100.0:
            return None, val
    except ValueError:
        return None, None
    return None, None


def check_outgroup_placement(newick: str, outgroup_names: List[str]) -> Tuple[bool, str]:
    """
    校验指定外群是否真正位于树基部（未嵌入目标类群内部分支）。
    """
    if not outgroup_names:
        return False, "未指定外群参考基因组。"
    root = parse_newick(newick)
    leaves = [n for n in _all_nodes(root) if n.is_leaf]
    leaf_names = {n.name for n in leaves}
    matched_og = [og for og in outgroup_names if og in leaf_names]
    if not matched_og:
        return False, f"进化树叶节点中未找到指定外群 ({', '.join(outgroup_names)})。"

    og_set = set(matched_og)
    if len(root.children) < 2:
        return False, "树结构仅含单个根节点分支。"

    # 若以某外群定根后，根的至少一个直接子分支全部由外群组成，且另一侧全部非外群，则外群处于规范基部
    basal_pure = False
    for child in root.children:
        sub_leaves = {n.name for n in _all_nodes(child) if n.is_leaf}
        if sub_leaves and sub_leaves.issubset(og_set):
            basal_pure = True
            break

    if basal_pure:
        # 校验是否有其他外群混杂在非外群主分支内部
        other_og = [
            n.name
            for child in root.children
            for n in _all_nodes(child)
            if n.is_leaf and n.name in og_set
            and not {x.name for x in _all_nodes(child) if x.is_leaf}.issubset(og_set)
        ]
        if not other_og:
            return True, f"外群 ({', '.join(matched_og)}) 明确位于系统发育树基部，未嵌入目标类群。"
        return (
            False,
            f"外群存在分离现象 ({', '.join(other_og)} 混入目标类群内部)，建议重新审视外群亲缘远近。",
        )

    return False, f"外群 ({', '.join(matched_og)}) 未处在树基部单系外侧，请检查是否选择了同属内株作为外群。"


def find_sister_taxa(
    newick: str,
    query_name: str,
) -> Tuple[List[str], Optional[float], Optional[float]]:
    """
    定位查询基因组在树上的直接姐妹叶集合，以及最近非零支持率祖先节点的 (alrt, ufboot)。
    """
    root = parse_newick(newick)
    q_node: Optional[PhyloNode] = None
    for node in _all_nodes(root):
        if node.is_leaf and node.name == query_name:
            q_node = node
            break
    if q_node is None or q_node.parent is None:
        return [], None, None

    p = q_node.parent
    sisters: List[str] = []
    for sib in p.children:
        if sib is q_node:
            continue
        sisters.extend(n.name for n in _all_nodes(sib) if n.is_leaf)

    # 向上追溯支持率（优先取直接父节点支持率）
    alrt_val, ufboot_val = _parse_dual_support(p.name)
    if ufboot_val is None and p.parent is not None:
        alrt_val, ufboot_val = _parse_dual_support(p.parent.name)

    return sisters, alrt_val, ufboot_val


def compute_tree_metrics(
    newick: str,
    best_model: Optional[str] = None,
    best_model_bic: Optional[float] = None,
) -> TreeMetrics:
    """计算进化树拓扑与支持率统计指标（支持双支持值 SH-aLRT/UFBoot 及 UFBoot >= 95 比例）。"""
    root = parse_newick(newick)
    nodes = _all_nodes(root)
    leaves = [n for n in nodes if n.is_leaf]
    internals = [n for n in nodes if not n.is_leaf]
    total_len = sum(max(0.0, n.length) for n in nodes if n is not root)

    supports: List[float] = []
    alrts: List[float] = []
    for n in internals:
        if n is root:
            continue
        alrt_val, uf_val = _parse_dual_support(n.name)
        if uf_val is not None:
            supports.append(uf_val)
        if alrt_val is not None:
            alrts.append(alrt_val)

    diameter = 0.0
    if len(leaves) >= 2:
        tip_a, _, _ = _farthest_from(leaves[0])
        _, diameter, _ = _farthest_from(tip_a)

    strong_ratio = (
        round(sum(1 for s in supports if s >= 95.0) / len(supports) * 100.0, 1)
        if supports
        else None
    )

    return TreeMetrics(
        leaf_count=len(leaves),
        internal_count=len(internals),
        total_branch_length=round(total_len, 6),
        diameter=round(diameter, 6),
        mean_support=round(sum(supports) / len(supports), 2) if supports else None,
        min_support=round(min(supports), 2) if supports else None,
        max_support=round(max(supports), 2) if supports else None,
        mean_alrt=round(sum(alrts) / len(alrts), 2) if alrts else None,
        strong_ufboot_ratio=strong_ratio,
        has_dual_support=bool(alrts),
        best_model=best_model,
        best_model_bic=best_model_bic,
        is_rooted=len(root.children) == 2,
    )
