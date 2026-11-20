# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测分析包 (PhageStructure)
"""
from __future__ import annotations

from .manager import PhageStructureManager, get_phage_structure_manager
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
    "is_phagetailfinder_ready",
    "decode_tail_sequence",
    "run_phagetailfinder_on_contigs",
]
