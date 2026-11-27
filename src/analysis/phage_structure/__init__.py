# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测分析包 (PhageStructure)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .thresholds import (
    DEFAULT_THRESHOLDS,
    PhageStructureThresholds,
    list_threshold_keys,
    override_threshold,
)
from .tail_finder_adapter import (
    decode_tail_sequence,
    is_phagetailfinder_ready,
    run_phagetailfinder_on_contigs,
)
from .morphotype_classifier import (
    build_connector_profile,
    build_module_matrix,
    classify_morphotype,
)
from .phrog_catalog import (
    ROLE_LABELS_CN,
    PhrogCatalog,
    classify_structural_role,
    get_phrog_catalog,
)
from .tmp_analyzer import (
    analyze_single_tmp,
    compute_hydropathy_profile,
    detect_polyx_regions,
    detect_tandem_repeats,
    select_and_analyze_tmps,
)
from .types import (
    AiMorphotypePrediction,
    ConnectorProfile,
    ContigStructureResult,
    MorphotypePrediction,
    PhageStructureResult,
    PolyXRegion,
    StructuralModuleMatrix,
    StructureBatchItemRequest,
    StructureBatchRunRequest,
    StructureInspectRequest,
    StructureProteinItem,
    StructureRunRequest,
    TailFinderCluster,
    TandemRepeatUnit,
    TmpAnalysisItem,
)

if TYPE_CHECKING:
    from .ai_morphotype_model import (
        check_ai_classifier_ready,
        check_unified_judge_ready,
        predict_contig_morphotype_ai,
        release_ai_judge_memory,
    )
    from .manager import (
        PhageStructureManager,
        evaluate_single_contig_structure,
        get_phage_structure_manager,
        should_trigger_phold_3d,
    )

_MANAGER_EXPORTS = {
    "PhageStructureManager",
    "evaluate_single_contig_structure",
    "get_phage_structure_manager",
    "should_trigger_phold_3d",
}
_AI_MODEL_EXPORTS = {
    "check_ai_classifier_ready",
    "check_unified_judge_ready",
    "predict_contig_morphotype_ai",
    "release_ai_judge_memory",
}

__all__ = [
    "ROLE_LABELS_CN",
    "PhrogCatalog",
    "get_phrog_catalog",
    "classify_structural_role",
    "detect_polyx_regions",
    "detect_tandem_repeats",
    "compute_hydropathy_profile",
    "analyze_single_tmp",
    "select_and_analyze_tmps",
    "build_module_matrix",
    "build_connector_profile",
    "classify_morphotype",
    "StructureBatchItemRequest",
    "StructureBatchRunRequest",
    "StructureInspectRequest",
    "StructureRunRequest",
    "AiMorphotypePrediction",
    "check_ai_classifier_ready",
    "check_unified_judge_ready",
    "predict_contig_morphotype_ai",
    "release_ai_judge_memory",
    "TailFinderCluster",
    "PolyXRegion",
    "TandemRepeatUnit",
    "TmpAnalysisItem",
    "StructureProteinItem",
    "ConnectorProfile",
    "StructuralModuleMatrix",
    "MorphotypePrediction",
    "ContigStructureResult",
    "PhageStructureResult",
    "PhageStructureManager",
    "get_phage_structure_manager",
    "should_trigger_phold_3d",
    "evaluate_single_contig_structure",
    "DEFAULT_THRESHOLDS",
    "PhageStructureThresholds",
    "override_threshold",
    "list_threshold_keys",
    "is_phagetailfinder_ready",
    "decode_tail_sequence",
    "run_phagetailfinder_on_contigs",
]


def __getattr__(name: str) -> Any:
    if name in _MANAGER_EXPORTS:
        from . import manager

        return getattr(manager, name)
    if name in _AI_MODEL_EXPORTS:
        from . import ai_morphotype_model

        return getattr(ai_morphotype_model, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
