# -*- coding: utf-8 -*-
"""
PhageTaxonomyWorkflow Stage 7/8 与 postprocess.extract_leaf_names 回归测试。
覆盖：
1. extract_leaf_names 精确叶节点解析（含单引号转义及子串重叠标签防误判）。
2. _select_publication_layouts 叶节点数阈值路由（<=60 vs >60）。
3. PhageTaxonomyWorkflow.execute 在 Stage 8 不再因未定义 leaf_names 触发 NameError。
"""
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 确保可直接以相对方式导入 src.phylo
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.phylo.core.checkpoint import CheckpointManager, StageCache
from src.phylo.delivery.publication_renderer import PublicationTreeRenderer
from src.phylo.engines.marker.proteome_tree import ProteomeTreeEngine
from src.phylo.engines.reference.dereplicator import PhageDereplicator
from src.phylo.engines.reference.ref_curator import PhageReferenceCurator
from src.phylo.engines.reference.treemmer_pruner import TreemmerPruner
from src.phylo.models.schemas import (
    AniHitRecord,
    AniScreenResult,
    DeliveryScopeConfig,
    MarkerExtractionReport,
    PhyloJobConfig,
    PhyloJobRecord,
    PublicationFigureRequest,
    ReferenceCandidate,
)
from src.phylo.pipeline.phage_workflow import (
    PhageTaxonomyWorkflow,
    _select_publication_layouts,
)
from src.phylo.pipeline.postprocess import extract_leaf_names


def test_extract_leaf_names_exact_and_quoted() -> None:
    """精确解析常规标签、单引号转义标签，并避免子串重叠标签误判。"""
    nwk = "('Phage A''1':0.12,P10:0.34,(Ref_2:0.05,Outgroup_1:0.22)98/100:0.10);"
    names = extract_leaf_names(nwk)
    assert names == ["Phage A'1", "P10", "Ref_2", "Outgroup_1"]
    assert "P1" not in names


def test_select_publication_layouts_threshold() -> None:
    """验证 60 叶节点阈值分支：<=60 仅渲染双图，>60 追加 composite 复合图。"""
    assert _select_publication_layouts(40) == ("circular", "rectangular")
    assert _select_publication_layouts(60) == ("circular", "rectangular")
    assert _select_publication_layouts(61) == ("composite", "circular", "rectangular")


def _build_balanced_newick(leaf_ids: List[str]) -> str:
    """将给定叶节点列表构造为合法的有枝长二叉树 Newick 字符串。"""
    if len(leaf_ids) == 1:
        return f"{leaf_ids[0]}:0.10"
    mid = len(leaf_ids) // 2
    left = _build_balanced_newick(leaf_ids[:mid])
    right = _build_balanced_newick(leaf_ids[mid:])
    return f"({left},{right})95/100:0.05"


@pytest.mark.parametrize(
    ("total_leaves", "expected_layouts"),
    [
        (40, ["circular", "rectangular"]),
        (65, ["composite", "circular", "rectangular"]),
    ],
)
def test_phage_workflow_stage8_no_name_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    total_leaves: int,
    expected_layouts: List[str],
) -> None:
    """端到端验证 Stage 7-8 完整运行，无 leaf_names NameError 且出图布局正确。"""
    job_dir = tmp_path / f"job_{total_leaves}"
    job_dir.mkdir(parents=True, exist_ok=True)

    query_id = "QueryPhage_1"
    outgroup_id = "Outgroup_Ref"
    ref_ids = [f"Ref_{i:03d}" for i in range(1, total_leaves - 1)]
    all_ids = [query_id] + ref_ids + [outgroup_id]

    fasta_dir = tmp_path / f"fastas_{total_leaves}"
    fasta_dir.mkdir(parents=True, exist_ok=True)
    genome_paths: Dict[str, Path] = {}
    for acc in all_ids:
        fp = fasta_dir / f"{acc}.fasta"
        fp.write_text(f">{acc}\n" + ("ATGC" * 50) + "\n", encoding="utf-8")
        genome_paths[acc] = fp

    candidates: List[ReferenceCandidate] = [
        ReferenceCandidate(
            accession=query_id,
            name=query_id,
            role="query",
            source="workspace",
            selected=True,
            genome_length=200,
            genus="Testvirus",
            family="Testviridae",
            host="Escherichia",
        )
    ]
    for acc in ref_ids:
        candidates.append(
            ReferenceCandidate(
                accession=acc,
                name=acc,
                role="ictv_rep",
                source="inphared_cache",
                selected=True,
                genome_length=200,
                genus="Testvirus",
                family="Testviridae",
                host="Escherichia",
                is_ictv_classified=True,
                wg_ani=82.5,
            )
        )
    candidates.append(
        ReferenceCandidate(
            accession=outgroup_id,
            name=outgroup_id,
            role="outgroup",
            source="inphared_cache",
            selected=True,
            genome_length=200,
            genus="Outvirus",
            family="Otherviridae",
            host="Bacillus",
            is_ictv_classified=True,
            wg_ani=55.0,
        )
    )

    ani_result = AniScreenResult(
        query_ids=[query_id],
        engine_used="mash",
        engine_version="mock-1.0",
        command_preview="mash dist mock",
        top_hits=[
            AniHitRecord(
                accession=ref_ids[0],
                wg_ani=82.5,
                aligned_ani=85.0,
                af_query=72.0,
                af_ref=70.0,
                genus="Testvirus",
                family="Testviridae",
                host="Escherichia",
                classification_call="same_genus_new_species",
            )
        ],
        matrix_labels=[query_id, ref_ids[0]],
        wgani_matrix=[[100.0, 82.5], [82.5, 100.0]],
        af_matrix=[[100.0, 72.0], [70.0, 100.0]],
        candidate_genera=["Testvirus"],
        candidate_families=["Testviridae"],
        summary_call="Mock ANI call",
    )

    monkeypatch.setattr(
        PhageReferenceCurator,
        "fetch_genomes",
        lambda self, **kwargs: (dict(genome_paths), []),
    )
    monkeypatch.setattr(
        PhageDereplicator,
        "dereplicate",
        lambda self, **kwargs: (
            dict(genome_paths),
            {"tool": "mock_drep", "before": len(genome_paths), "after": len(genome_paths)},
        ),
    )
    monkeypatch.setattr(
        TreemmerPruner,
        "prune_if_needed",
        lambda self, **kwargs: (
            dict(genome_paths),
            {
                "tool": "mock_treemmer",
                "before": len(genome_paths),
                "after": len(genome_paths),
                "removed": 0,
            },
        ),
    )

    def _mock_proteome_tree(
        self: ProteomeTreeEngine,
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        output_nwk: Path,
        dist_npy: Path,
        dist_csv: Path,
        **kwargs: Any,
    ) -> Any:
        work_dir.mkdir(parents=True, exist_ok=True)
        nwk_str = f"({outgroup_id}:0.30,{_build_balanced_newick([query_id] + ref_ids)});"
        output_nwk.write_text(nwk_str + "\n", encoding="utf-8")
        dist_csv.write_text("id,a\n", encoding="utf-8")
        report = MarkerExtractionReport(
            mode="proteome",
            total_genomes=len(genome_fastas),
            extracted_count=len(genome_fastas),
            tool_used="mock_diamond",
            tool_version="1.0",
        )
        return output_nwk, report

    monkeypatch.setattr(ProteomeTreeEngine, "build_proteome_tree", _mock_proteome_tree)

    rendered_layouts: List[str] = []

    def _mock_render(
        newick: str,
        node_metadata: Dict[str, Dict[str, Any]],
        out_dir: Path,
        request: PublicationFigureRequest,
        file_prefix: str = "publication",
        subtitle: str = "",
    ) -> List[Path]:
        rendered_layouts.append(request.layout)
        out_dir.mkdir(parents=True, exist_ok=True)
        created: List[Path] = []
        for fmt in request.formats:
            fp = out_dir / f"{file_prefix}_{request.layout}.{fmt}"
            fp.write_text(f"mock {request.layout} {fmt}", encoding="utf-8")
            created.append(fp)
        return created

    monkeypatch.setattr(PublicationTreeRenderer, "render", staticmethod(_mock_render))

    cfg = PhyloJobConfig(
        title=f"Mock Phage {total_leaves}",
        track="phage_taxonomy",
        marker_mode="proteome",
        phage_scope=DeliveryScopeConfig(),
        selected_references=candidates,
        precomputed_ani_result=ani_result,
        outgroup_ids=[outgroup_id],
        use_cache=False,
    )
    record = PhyloJobRecord(
        job_id=f"phylo_test_{total_leaves}",
        title=f"Mock Phage {total_leaves}",
        resolved_track="phage_taxonomy",
        config=cfg,
        created_at=time.time(),
        job_dir=str(job_dir),
    )

    ckp = CheckpointManager(job_dir)
    cache = StageCache(tmp_path / "stage_cache")
    cancel_ev = threading.Event()
    stages_seen: List[str] = []

    PhageTaxonomyWorkflow.execute(
        record=record,
        records=[(query_id, "ATGC" * 50)],
        job_dir=job_dir,
        ckp=ckp,
        cache=cache,
        cancel_ev=cancel_ev,
        log_fn=lambda msg: None,
        stage_fn=lambda name, status, progress, msg, **kw: stages_seen.append(f"{name}:{status}"),
        set_runner=lambda r: None,
    )

    assert rendered_layouts == expected_layouts
    assert record.metrics is not None
    assert record.metrics.leaf_count == total_leaves
    assert Path(record.artifacts["final_nwk"]).is_file()
    assert Path(record.artifacts["delivery_zip"]).is_file()
    assert len(record.artifacts["itol_files"]) > 0
    assert "qc_delivery:completed" in stages_seen
