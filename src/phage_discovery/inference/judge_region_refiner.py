# -*- coding: utf-8 -*-
"""
基于 OrfFunctionalJudge (R2/R3) 的后置区段境界精修、灰区碎段挽救与防御岛排雷模块。

单一职责设计：
1. 不改动 Stage 1.2 边界主干权重，以标准 PredictedRegion 与 ORF 坐标流接入扫描流水线；
2. 单变量组件 1 (`refine_region_boundaries_with_judge`)：利用 R3 ORF 级精判向左右侧翼安全延展被过早切断的噬菌体尾巴（如 Fels-2 断尾），并温和剔除边缘纯宿主/防御 ORF；
3. 单变量组件 2 (`rescue_and_filter_regions_with_judge`)：对放宽门槛召回的灰区弱峰区段执行 R3 严格二审，在死守高 GC/质粒零误报前提下挽救极碎裂隐蔽前噬菌体；
4. 完整度拆分评估：R3 主导 `is_phage`、10 类功能分区与 `P9` 排雷；R2 未校准核心结构分支主导区段完整度打分。
"""

from __future__ import annotations

from .judge_boundary_refiner import (
    _can_absorb_companion_peak,
    _extract_active_subbin_segments,
    _is_phage_extension_orf,
    _is_strong_host_edge_orf,
    _should_snap_core_orf,
    _subbin_interval_stats,
    absorb_companion_subbin_peaks,
    merge_nearby_regions,
    refine_region_boundaries_bimodal,
    refine_region_boundaries_with_judge,
    snap_split_core_orfs,
)
from .judge_integrase_anchor import (
    _has_unannotated_dead_moat,
    _is_true_integrase_orf,
    _passes_integrase_span_quality,
    _search_directional_integrase_anchor,
    close_flanks_to_integrase_anchors,
    extract_subbin_gray_candidates,
)
from .judge_rescue_filter import (
    _is_gray_tailocin_like,
    _passes_gray_rescue_criteria,
    _region_overlaps_any,
    _should_veto_base_region,
    bridge_complementary_phage_fragments,
    reconcile_tentative_siblings,
    rescue_and_filter_regions_with_judge,
    split_tandem_prophage_regions,
    summarize_region_with_judge,
)
from .judge_scoring import (
    _extract_single_contig_orfs,
    _get_r2_core_probs,
    _load_judge_ckpt,
    extract_contig_orfs_pyrodigal,
    load_judge_ensemble_bundle,
    logger,
    resolve_unified_version_tag,
    score_contigs_with_judge_bundle,
    trim_triggered,
)

__all__ = [
    "logger",
    "_extract_single_contig_orfs",
    "extract_contig_orfs_pyrodigal",
    "_load_judge_ckpt",
    "resolve_unified_version_tag",
    "load_judge_ensemble_bundle",
    "score_contigs_with_judge_bundle",
    "_is_phage_extension_orf",
    "_is_strong_host_edge_orf",
    "merge_nearby_regions",
    "refine_region_boundaries_with_judge",
    "_subbin_interval_stats",
    "refine_region_boundaries_bimodal",
    "_extract_active_subbin_segments",
    "_can_absorb_companion_peak",
    "absorb_companion_subbin_peaks",
    "_should_snap_core_orf",
    "snap_split_core_orfs",
    "_is_true_integrase_orf",
    "_has_unannotated_dead_moat",
    "_passes_integrase_span_quality",
    "_search_directional_integrase_anchor",
    "close_flanks_to_integrase_anchors",
    "extract_subbin_gray_candidates",
    "trim_triggered",
    "_region_overlaps_any",
    "_get_r2_core_probs",
    "_should_veto_base_region",
    "_is_gray_tailocin_like",
    "_passes_gray_rescue_criteria",
    "bridge_complementary_phage_fragments",
    "split_tandem_prophage_regions",
    "reconcile_tentative_siblings",
    "rescue_and_filter_regions_with_judge",
    "summarize_region_with_judge",
]
