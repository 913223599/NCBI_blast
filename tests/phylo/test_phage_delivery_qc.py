# -*- coding: utf-8 -*-
"""
阶段三/四测试：iTOL 注释套件、第 8 步 6 项质检、交付 ZIP 归档及 API 端点验证
"""
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from src.backend.api_server import app
from src.phylo.delivery.bundle_exporter import DeliveryBundleExporter
from src.phylo.delivery.itol_generator import ItolTemplateGenerator
from src.phylo.delivery.qc_auditor import PhageDeliveryQcAuditor
from src.phylo.models.schemas import (
    AniHitRecord,
    AniScreenResult,
    MarkerExtractionReport,
    ReferenceCandidate,
)
from src.phylo.pipeline.postprocess import compute_tree_metrics


def _sample_candidates() -> list[ReferenceCandidate]:
    return [
        ReferenceCandidate(
            accession="Query_Phage",
            role="query",
            source="workspace",
            genome_length=42500,
            gc_content=55.2,
            selected=True,
        ),
        ReferenceCandidate(
            accession="NC_001",
            role="ictv_rep",
            genus="Warsawvirus",
            family="Autotranscriptaviridae",
            host="Pseudomonas",
            genome_length=40200,
            gc_content=56.4,
            wg_ani=76.8,
            is_ictv_classified=True,
            selected=True,
        ),
        ReferenceCandidate(
            accession="NC_002",
            role="ictv_rep",
            genus="Warsawvirus",
            family="Autotranscriptaviridae",
            host="Pseudomonas",
            genome_length=41100,
            gc_content=56.1,
            wg_ani=75.1,
            is_ictv_classified=True,
            selected=True,
        ),
        ReferenceCandidate(
            accession="NC_OG",
            role="outgroup",
            genus="Teseptimavirus",
            family="Autotranscriptaviridae",
            host="Escherichia",
            genome_length=39800,
            gc_content=48.4,
            wg_ani=28.0,
            is_ictv_classified=True,
            selected=True,
        ),
    ]


def test_itol_qc_and_delivery_bundle(tmp_path: Path):
    cands = _sample_candidates()
    nwk = "((Query_Phage:0.05,(NC_001:0.02,NC_002:0.03)98.4/99:0.02)95.0/97:0.12,NC_OG:0.35);"
    metrics = compute_tree_metrics(nwk, best_model="Q.pfam+F+I+R4", best_model_bic=12345.6)

    itol_dir = tmp_path / "itol"
    itol_files = ItolTemplateGenerator.generate(cands, itol_dir)
    assert len(itol_files) == 6
    assert "TREE_COLORS" in (itol_dir / "itol_branch_colors.txt").read_text(encoding="utf-8")
    assert "DATASET_COLORSTRIP" in (itol_dir / "itol_strip_taxonomy.txt").read_text(encoding="utf-8")
    assert "DATASET_SIMPLEBAR" in (itol_dir / "itol_bars_genome_length.txt").read_text(encoding="utf-8")

    ani_res = AniScreenResult(
        query_ids=["Query_Phage"],
        top_hits=[
            AniHitRecord(
                accession="NC_001",
                wg_ani=76.8,
                aligned_ani=82.5,
                af_query=74.0,
                af_ref=76.0,
                genus="Warsawvirus",
                family="Autotranscriptaviridae",
                classification_call="same_genus_new_species",
            )
        ],
        matrix_labels=["Query_Phage", "NC_001"],
        wgani_matrix=[[100.0, 76.8], [76.8, 100.0]],
        af_matrix=[[100.0, 74.0], [76.0, 100.0]],
        candidate_genera=["Warsawvirus"],
        candidate_families=["Autotranscriptaviridae"],
    )
    marker_rep = MarkerExtractionReport(
        mode="terl", total_genomes=4, extracted_count=4, tool_used="prodigal-gv+hmmsearch"
    )
    trim_stats = {"original_cols": 520, "kept_cols": 460, "parsimony_informative_sites": 180, "tool": "clipkit (-m kpic)"}

    qc = PhageDeliveryQcAuditor.audit(
        newick=nwk,
        metrics=metrics,
        candidates=cands,
        ani_result=ani_res,
        marker_report=marker_rep,
        trim_stats=trim_stats,
        iqtree_cmd="iqtree3 -s trimmed.fasta -m MFP -B 1000 -bnni -alrt 1000 --seed 42",
        best_model="Q.pfam+F+I+R4",
        best_model_bic=12345.6,
        itol_files=itol_files,
    )
    assert qc.overall_status == "pass"
    assert qc.ani_tree_consistent is True
    assert len(qc.checks) == 6
    assert "候选新种" in qc.conclusion_zh
    assert "Warsawvirus" in qc.conclusion_en

    msa_file = tmp_path / "trimmed.fasta"
    msa_file.write_text(">Query_Phage\nMKTL\n>NC_001\nMKTL\n", encoding="utf-8")
    zip_path = DeliveryBundleExporter.write_reports_and_pack(
        job_dir=tmp_path,
        job_id="phylo_test_001",
        title="TestPhage",
        newick=nwk,
        qc_report=qc,
        ani_result=ani_res,
        marker_report=marker_rep,
        trimmed_msa_path=msa_file,
        treefile_path=None,
        itol_dir=itol_dir,
        commands_used=["mash dist ..."],
    )
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        assert {"tree.nwk", "qc_report.md", "qc_report.json", "ani_matrix.csv", "reproduce.sh"}.issubset(names)
        assert "itol/itol_strip_taxonomy.txt" in names


def test_phage_curate_refs_api(tmp_path: Path, monkeypatch):
    from src.backend.routes import phylo as phylo_route
    from src.phylo.pipeline.executor import get_phylo_executor
    from src.phylo.storage.archive_store import PhyloArchiveStore

    store = PhyloArchiveStore(base_dir=tmp_path / "curate_api_store")
    executor = get_phylo_executor()
    orig_store = executor.store
    executor.store = store
    monkeypatch.setattr(phylo_route, "get_phylo_store", lambda: store)

    client = TestClient(app)
    try:
        res_clear = client.delete("/api/phylo/workspace")
        assert res_clear.status_code == 200

        fa = tmp_path / "NewPhage.fasta"
        fa.write_text(">NewPhage\n" + ("ATGCTAGC" * 400) + "\n", encoding="utf-8")
        res_add = client.post("/api/phylo/workspace/add", json={"paths": [str(fa)]})
        assert res_add.status_code == 200

        ani_payload = {
            "query_ids": ["NewPhage"],
            "top_hits": [
                {
                    "accession": "PV620261",
                    "wg_ani": 74.5,
                    "genus": "Warsawvirus",
                    "family": "Autotranscriptaviridae",
                    "classification_call": "genus_boundary_ambiguous",
                }
            ],
            "candidate_genera": ["Warsawvirus"],
            "candidate_families": ["Autotranscriptaviridae"],
            "ambiguous_zone": True,
            "recommended_outgroup_accessions": [],
        }
        res_curate = client.post("/api/phylo/phage/curate-refs", json={"ani_result": ani_payload})
        assert res_curate.status_code == 200
        cands = res_curate.json()
        assert any(c["accession"] == "NewPhage" and c["role"] == "query" for c in cands)
        assert any(c["role"] == "ictv_rep" for c in cands)
    finally:
        executor.store = orig_store


def test_submit_phage_taxonomy_job_with_chinese_filename(tmp_path: Path, monkeypatch):
    from src.backend.routes import phylo as phylo_route
    from src.phylo.engines.ani.viridic_ani import ViridicAniCalculator
    from src.phylo.pipeline.executor import get_phylo_executor
    from src.phylo.storage.archive_store import PhyloArchiveStore

    store = PhyloArchiveStore(base_dir=tmp_path / "phage_submit_store")
    executor = get_phylo_executor()
    orig_store = executor.store
    executor.store = store
    monkeypatch.setattr(phylo_route, "get_phylo_store", lambda: store)
    # 拦截后台计算线程启动，专门验证请求提交与 PhyloJobRecord 校验序列化全链路
    monkeypatch.setattr(executor, "_run_job_worker", lambda *args, **kwargs: None)

    client = TestClient(app)
    try:
        assert client.delete("/api/phylo/workspace").status_code == 200
        cn_fa = tmp_path / "附件2霍氏肠杆菌噬菌体2基因组序列.fasta"
        base = "ATGCTAGCTAGCATCGATCGATCGATAGCATCGATCGTAGCTAGCTA" * 80
        cn_fa.write_text(f">附件2霍氏肠杆菌噬菌体2\n{base}\n", encoding="utf-8", newline="\n")
        assert client.post("/api/phylo/workspace/add", json={"paths": [str(cn_fa)]}).status_code == 200

        res_job = client.post(
            "/api/phylo/jobs",
            json={
                "track": "phage_taxonomy",
                "msa": "mafft",
                "msa_strategy": "linsi",
                "trim_mode": "kpic",
                "engine": "iqtree",
                "model": "MFP",
                "bootstrap": 1000,
                "iqtree_bnni": True,
                "iqtree_alrt": 1000,
                "iqtree_seed": 42,
                "marker_mode": "terl",
                "ani_engine": "viridic_blastn",
                "phage_scope": {"target_rank": "genus"},
            },
        )
        assert res_job.status_code == 200, res_job.text
        job = res_job.json()
        assert job["resolved_track"] == "phage_taxonomy"
        assert len(job["stages"]) == 8
        client.post(f"/api/phylo/jobs/{job['job_id']}/cancel")

        # 验证含中文序列 ID 可直接通过 ViridicAniCalculator 计算并返回真实中文标签
        fa2 = tmp_path / "ref.fasta"
        fa2.write_text(f">Ref_1\n{base[:3000]}" + "GGGG" * 190 + "\n", encoding="utf-8", newline="\n")
        calc = ViridicAniCalculator()
        labels, wg, _af, _det, _v, _cmd = calc.compute_matrix_from_fastas(
            {"附件2霍氏肠杆菌噬菌体2": cn_fa, "Ref_1": fa2},
            work_dir=tmp_path / "cn_viridic",
            engine="viridic_blastn",
            threads=4,
        )
        assert labels == ["附件2霍氏肠杆菌噬菌体2", "Ref_1"]
        assert wg[0][1] > 70.0
    finally:
        with executor._jobs_lock:
            executor._active_jobs.clear()
        executor.store = orig_store
