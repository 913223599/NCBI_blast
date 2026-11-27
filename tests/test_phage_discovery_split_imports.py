# -*- coding: utf-8 -*-
"""Phase 6C 模块拆解向后兼容与门面重导出一致性测试。"""
from __future__ import annotations
import pytest

pytestmark = pytest.mark.ml


def test_distilled_student_v4_facade_exports():
    from src.phage_discovery.student import (
        distilled_student_v4 as v4,
        v4_arch,
        v4_context_refiner,
        v4_sub_head,
    )

    assert v4.SEMANTIC_DIM == v4_arch.SEMANTIC_DIM
    assert v4.REFINER_STEP_FEAT_DIM == v4_arch.REFINER_STEP_FEAT_DIM
    assert v4.REFINER_CTX_AUG_DIM == v4_arch.REFINER_CTX_AUG_DIM
    assert v4.build_distilled_student_v4 is v4_arch.build_distilled_student_v4
    assert v4.build_region_context_refiner is v4_arch.build_region_context_refiner
    assert v4.extract_refiner_step_features is v4_context_refiner.extract_refiner_step_features
    assert v4.group_windows_by_contig is v4_context_refiner.group_windows_by_contig
    assert v4.predict_with_context_refiner is v4_context_refiner.predict_with_context_refiner
    assert v4.train_context_refiner is v4_context_refiner.train_context_refiner
    assert v4.refine_student_v4_sub_head is v4_sub_head.refine_student_v4_sub_head
    assert "chimeras" in v4.CONTIG_REF_PARTS
    assert callable(v4.train_distilled_student_v4)
    assert callable(v4.main)


def test_judge_region_refiner_facade_exports():
    from src.phage_discovery.inference import (
        judge_boundary_refiner,
        judge_integrase_anchor,
        judge_region_refiner as facade,
        judge_rescue_filter,
        judge_scoring,
    )

    assert facade.extract_contig_orfs_pyrodigal is judge_scoring.extract_contig_orfs_pyrodigal
    assert facade.load_judge_ensemble_bundle is judge_scoring.load_judge_ensemble_bundle
    assert facade.score_contigs_with_judge_bundle is judge_scoring.score_contigs_with_judge_bundle
    assert facade.trim_triggered is judge_scoring.trim_triggered
    assert facade.merge_nearby_regions is judge_boundary_refiner.merge_nearby_regions
    assert facade.refine_region_boundaries_with_judge is judge_boundary_refiner.refine_region_boundaries_with_judge
    assert facade.refine_region_boundaries_bimodal is judge_boundary_refiner.refine_region_boundaries_bimodal
    assert facade.absorb_companion_subbin_peaks is judge_boundary_refiner.absorb_companion_subbin_peaks
    assert facade.snap_split_core_orfs is judge_boundary_refiner.snap_split_core_orfs
    assert facade.close_flanks_to_integrase_anchors is judge_integrase_anchor.close_flanks_to_integrase_anchors
    assert facade.extract_subbin_gray_candidates is judge_integrase_anchor.extract_subbin_gray_candidates
    assert facade.bridge_complementary_phage_fragments is judge_rescue_filter.bridge_complementary_phage_fragments
    assert facade.split_tandem_prophage_regions is judge_rescue_filter.split_tandem_prophage_regions
    assert facade.reconcile_tentative_siblings is judge_rescue_filter.reconcile_tentative_siblings
    assert facade.rescue_and_filter_regions_with_judge is judge_rescue_filter.rescue_and_filter_regions_with_judge
    assert facade.summarize_region_with_judge is judge_rescue_filter.summarize_region_with_judge
