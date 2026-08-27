# -*- coding: utf-8 -*-
"""
clustering_tree.py - 论文级生信层次聚类算法 (Hierarchical Clustering / UPGMA) 与受体靶点同源分析
1. 层次聚类: 采用生信标准 UPGMA (Average Linkage) 对相似度/亲缘矩阵重排序并生成树状图 (Dendrogram)
2. 受体靶点分析: 评估尾丝受体结合区两两相似度与同源亚群归类
"""
from typing import Dict, List, Any, Tuple


def upgma_hierarchical_clustering(
    matrix: Dict[str, Dict[str, float]],
    sample_ids: List[str]
) -> Tuple[List[str], Dict[str, Any]]:
    """
    UPGMA (Unweighted Pair Group Method with Arithmetic Mean) 层次聚类算法
    输入:
        matrix: 对称相似度矩阵 (0.0 ~ 100.0)
        sample_ids: 样本 ID 列表
    输出:
        ordered_ids: 聚类树最佳叶子节点排序
        dendrogram_data: 树状图节点拓扑 (包含合并步骤、距离、分支高度)
    """
    n = len(sample_ids)
    if n <= 1:
        return sample_ids, {"nodes": [], "ordered_ids": sample_ids}

    # 1. 初始化距离矩阵 (Distance = 100.0 - Identity)
    dist_matrix = {}
    for s1 in sample_ids:
        dist_matrix[s1] = {}
        for s2 in sample_ids:
            ident = matrix.get(s1, {}).get(s2, 0.0)
            dist = max(0.0, 100.0 - ident)
            dist_matrix[s1][s2] = dist

    # 2. 初始化聚类簇
    clusters = {
        sid: {
            "id": sid,
            "leaves": [sid],
            "height": 0.0,
            "left": None,
            "right": None
        }
        for sid in sample_ids
    }

    merge_steps = []
    cluster_ids = list(sample_ids)
    node_counter = n

    while len(cluster_ids) > 1:
        min_dist = float('inf')
        best_pair = (None, None)

        for i in range(len(cluster_ids)):
            c1_id = cluster_ids[i]
            leaves1 = clusters[c1_id]["leaves"]
            for j in range(i + 1, len(cluster_ids)):
                c2_id = cluster_ids[j]
                leaves2 = clusters[c2_id]["leaves"]

                # 计算平均距离 (Average linkage)
                total_d = sum(dist_matrix[l1][l2] for l1 in leaves1 for l2 in leaves2)
                avg_d = total_d / (len(leaves1) * len(leaves2))

                if avg_d < min_dist:
                    min_dist = avg_d
                    best_pair = (c1_id, c2_id)

        c1_id, c2_id = best_pair
        if c1_id is None or c2_id is None:
            break

        c1 = clusters[c1_id]
        c2 = clusters[c2_id]
        new_height = min_dist / 2.0

        new_cluster_id = f"NODE_{node_counter}"
        node_counter += 1

        new_cluster = {
            "id": new_cluster_id,
            "leaves": c1["leaves"] + c2["leaves"],
            "height": round(new_height, 2),
            "left": c1,
            "right": c2,
            "distance": round(min_dist, 2)
        }

        merge_steps.append({
            "step": len(merge_steps) + 1,
            "cluster_a": c1_id,
            "cluster_b": c2_id,
            "distance": round(min_dist, 2),
            "height": round(new_height, 2),
            "size": len(new_cluster["leaves"])
        })

        clusters[new_cluster_id] = new_cluster
        cluster_ids.remove(c1_id)
        cluster_ids.remove(c2_id)
        cluster_ids.append(new_cluster_id)

    # 3. 递归遍历树以获得最佳叶子排序 (In-order traversal)
    root = clusters[cluster_ids[0]]
    ordered_ids = []

    def traverse(node):
        if node["left"] is None and node["right"] is None:
            ordered_ids.append(node["id"])
            return
        if node["left"]:
            traverse(node["left"])
        if node["right"]:
            traverse(node["right"])

    traverse(root)

    return ordered_ids, {
        "root": root,
        "merge_steps": merge_steps,
        "ordered_ids": ordered_ids
    }


def analyze_receptor_orthology(
    tail_matrix: Dict[str, Dict[str, float]],
    ani_matrix: Dict[str, Dict[str, float]],
    sample_names: Dict[str, str]
) -> Dict[str, Any]:
    """
    分析受体结合蛋白两两相似度与分子靶点正交分类
    """
    sample_ids = list(sample_names.keys())
    orthogonal_pairs = []
    divergent_pairs = []
    overlapping_pairs = []

    for i, s1 in enumerate(sample_ids):
        for j, s2 in enumerate(sample_ids):
            if i >= j:
                continue

            tail_score = tail_matrix.get(s1, {}).get(s2, 0.0)
            ani_score = ani_matrix.get(s1, {}).get(s2, 0.0)
            pair_name = f"{sample_names[s1]} & {sample_names[s2]}"

            if tail_score >= 75.0:
                overlapping_pairs.append({
                    "sample1": s1,
                    "sample2": s2,
                    "pair": pair_name,
                    "tail_identity": tail_score,
                    "ani": ani_score,
                    "type": "高度同源 (High Homology)",
                    "desc": "受体结合结构域序列一致性 ≥75%，预测吸附同类表面受体分子。"
                })
            elif 25.0 <= tail_score < 75.0:
                divergent_pairs.append({
                    "sample1": s1,
                    "sample2": s2,
                    "pair": pair_name,
                    "tail_identity": tail_score,
                    "ani": ani_score,
                    "type": "分化突变 (Divergent)",
                    "desc": f"受体结合域存在中度分化 ({tail_score}%)，可能识别同类受体的不同血清型位点。"
                })
            else:
                orthogonal_pairs.append({
                    "sample1": s1,
                    "sample2": s2,
                    "pair": pair_name,
                    "tail_identity": tail_score,
                    "ani": ani_score,
                    "type": "正交靶点 (Orthogonal)",
                    "desc": f"受体结合域高度分化/完全不同 (相似度 {tail_score}%)，预测识别正交非竞争宿主表面抗原。"
                })

    return {
        "orthogonal_pairs": orthogonal_pairs,
        "divergent_pairs": divergent_pairs,
        "overlapping_pairs": overlapping_pairs,
        "total_evaluated_pairs": len(sample_ids) * (len(sample_ids) - 1) // 2
    }
