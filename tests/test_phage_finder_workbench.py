# -*- coding: utf-8 -*-
"""
前噬菌体发现工作台 (Student V4.2) 后端模块、导出器与 FastAPI 路由闭环测试
"""
import json
import time
from pathlib import Path
from typing import Dict

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord
from fastapi.testclient import TestClient

from src.analysis.phage_finder.db import PhageDiscoveryDB
from src.analysis.phage_finder.exporter import (
    _classify_completeness,
    build_contig_overlay_gbk,
    export_scan_artifacts,
    inspect_sequences,
    load_sequences_with_annotations,
    load_sequences_with_meta,
)
from src.analysis.phage_finder.manager import PhageDiscoveryManager
from src.analysis.phage_finder.model_registry import (
    discover_available_models,
    get_safe_workers,
    resolve_model_dir,
)
from src.analysis.phage_finder.queue import PhageDiscoveryQueue
from src.phage_discovery.inference.protein_gate import RegionGateResult
from src.phage_discovery.inference.scanner import (
    PredictedRegion,
    ScanResult,
    WindowPrediction,
    _collect_contig_score_tracks,
)


def _create_mock_v4_2_dir(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "student_v4.pt").write_bytes(b"mock_v4_2_weights")
    (model_dir / "context_refiner.pt").write_bytes(b"mock_ctx")
    (model_dir / "subbin_refiner.pt").write_bytes(b"mock_subbin")
    (model_dir / "student_v4_meta.json").write_text(
        json.dumps(
            {
                "params": 146850,
                "use_context_refiner": True,
                "use_subbin_refiner": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (model_dir / "student_v4_report.json").write_text(
        json.dumps(
            {
                "decoder_tuned_on_val": {
                    "seed_threshold": 0.95,
                    "extend_threshold": 0.30,
                    "sub_threshold": 0.45,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _synth_dna(length: int, seed_seq: str = "ATGCGTACGTAGCTAGCTAG") -> str:
    rep = (length // len(seed_seq)) + 1
    return (seed_seq * rep)[:length]


def test_model_registry_only_keeps_v4_2_and_filters_legacy_versions(tmp_path: Path):
    models_root = tmp_path / "models"
    # 放入旧版 V2 / V3.1 / V4.1 目录，校验均被忽略
    v2_dir = models_root / "full_v2" / "student"
    v2_dir.mkdir(parents=True, exist_ok=True)
    (v2_dir / "student_distilled.pt").write_bytes(b"v2")

    v3_dir = models_root / "full_v3_1" / "student"
    v3_dir.mkdir(parents=True, exist_ok=True)
    (v3_dir / "student_distilled.pt").write_bytes(b"v3")

    v4_1_dir = models_root / "full_v4" / "student_v4_1"
    v4_1_dir.mkdir(parents=True, exist_ok=True)
    (v4_1_dir / "student_v4.pt").write_bytes(b"v4_1")
    (v4_1_dir / "context_refiner.pt").write_bytes(b"ctx")
    (v4_1_dir / "student_v4_meta.json").write_text(
        json.dumps({"use_context_refiner": True, "use_subbin_refiner": False}),
        encoding="utf-8",
    )

    # 仅完整 V4.2 (含 subbin_refiner) 应被识别
    v4_2_dir = models_root / "full_v4" / "student_v4_2"
    _create_mock_v4_2_dir(v4_2_dir)

    found = discover_available_models(project_root=tmp_path)
    assert len(found) == 1
    assert found[0]["model_id"] == "student_v4_2"
    assert found[0]["version"] == "V4.2"
    assert found[0]["has_subbin_refiner"] is True
    assert Path(found[0]["path"]).resolve() == v4_2_dir.resolve()

    # 若自定义传入非 V4.2 的 V4.1 目录应明确拒绝
    try:
        resolve_model_dir(custom_model_dir=str(v4_1_dir), project_root=tmp_path)
        raised = False
    except FileNotFoundError as exc:
        raised = True
        assert "V4.2" in str(exc)
    assert raised is True

    # 安全核数永远预留核心且 >= 1
    assert get_safe_workers(9999) >= 1


def test_exporter_inspect_and_multi_format_artifacts(tmp_path: Path):
    seq1 = _synth_dna(24000, "ATGAAATTGCATGGCTAGCTAGCTAGCTAG")
    fasta_path = tmp_path / "sample.fasta"
    fasta_path.write_text(f">chr_test sample genome\n{seq1}\n", encoding="utf-8")

    insp = inspect_sequences(fasta_path=str(fasta_path), project_root=tmp_path)
    assert insp["total_contigs"] == 1
    assert insp["total_bp"] == 24000
    assert insp["contigs"][0]["id"] == "chr_test"

    seqs, _ = load_sequences_with_meta(fasta_path=str(fasta_path), project_root=tmp_path)
    region = PredictedRegion(
        contig_id="chr_test",
        start_bp=6000,
        end_bp=15000,
        peak_score=0.97,
        mean_score=0.88,
        window_count=5,
    )
    scan_res = ScanResult(
        contigs_bp={"chr_test": 24000},
        total_bp=24000,
        total_windows=11,
        raw_regions=[region],
        verified_regions=[region],
        gate_details=[],
        timings_sec={"total_sec": 0.42},
        region_profiles={
            "chr_test:6000-15000": [
                {"start_bp": 4000 + i * 200, "end_bp": 4200 + i * 200, "prob": 0.9 if 6000 <= 4000 + i * 200 < 15000 else 0.1, "in_region": 6000 <= 4000 + i * 200 < 15000}
                for i in range(60)
            ]
        },
    )

    out_dir = tmp_path / "results" / "phage_discovery" / "phage_test_01"
    exported = export_scan_artifacts(
        task_id="phage_test_01",
        task_name="Test_Sample",
        model_info={"model_id": "student_v4_2", "version": "V4.2", "label": "Student V4.2"},
        device_used="cpu",
        apply_protein_gate=False,
        sequences=seqs,
        scan_result=scan_res,
        out_dir=out_dir,
        flank_bp=2000,
        project_root=tmp_path,
    )

    assert exported["summary"]["region_count"] == 1
    assert exported["files"]["fasta"] == "results/phage_discovery/phage_test_01/phage_test_01_prophages.fasta"

    flanked_gbk = out_dir / "regions" / "region_1.gbk"
    assert flanked_gbk.exists()
    parsed_gbk = SeqIO.read(str(flanked_gbk), "genbank")
    assert len(parsed_gbk.seq) == 13000  # 9000bp region + 2000bp left + 2000bp right
    assert any(feat.type == "prophage_region" for feat in parsed_gbk.features)
    assert not any(feat.type == "misc_feature" for feat in parsed_gbk.features)

    # 核心 GenBank 同样能回读
    core_gbk = out_dir / "phage_test_01_prophages.gbk"
    core_recs = list(SeqIO.parse(str(core_gbk), "genbank"))
    assert len(core_recs) == 1
    assert len(core_recs[0].seq) == 9000
    assert not any(feat.type in {"misc_feature", "prophage_region"} for feat in core_recs[0].features)


def test_exporter_full_length_region_omits_spanning_feature(tmp_path: Path):
    """整条序列被预测为一个前噬菌体（无宿主侧翼）时，region_1.gbk 不得生成贯穿头尾的区段覆盖特征。"""
    seq1 = _synth_dna(15000, "ATGAAATTGCATGGCTAGCTAGCTAGCTAG")
    region = PredictedRegion(
        contig_id="phage_full",
        start_bp=0,
        end_bp=15000,
        peak_score=0.9977,
        mean_score=0.9650,
        window_count=6,
    )
    scan_res = ScanResult(
        contigs_bp={"phage_full": 15000},
        total_bp=15000,
        total_windows=6,
        raw_regions=[region],
        verified_regions=[region],
        gate_details=[],
        timings_sec={"total_sec": 0.25},
        region_profiles={},
    )
    out_dir = tmp_path / "results" / "phage_discovery" / "phage_full_01"
    export_scan_artifacts(
        task_id="phage_full_01",
        task_name="Full_Phage",
        model_info={"model_id": "student_v4_2", "version": "V4.2", "label": "Student V4.2"},
        device_used="cpu",
        apply_protein_gate=False,
        sequences={"phage_full": seq1},
        scan_result=scan_res,
        out_dir=out_dir,
        flank_bp=3000,
        project_root=tmp_path,
    )

    region_gbk = out_dir / "regions" / "region_1.gbk"
    assert region_gbk.exists()
    parsed = SeqIO.read(str(region_gbk), "genbank")
    assert len(parsed.seq) == 15000
    assert not any(feat.type in {"misc_feature", "prophage_region"} for feat in parsed.features)


def test_fastapi_phage_discovery_end_to_end_and_protein_compare_removed(tmp_path: Path, monkeypatch):
    # 构建隔离的工作台测试管理器（不污染生产 database/phage_discovery.db）
    _create_mock_v4_2_dir(tmp_path / "models" / "full_v4" / "student_v4_2")
    isolated_db = PhageDiscoveryDB(db_path=tmp_path / "db" / "phage_discovery.db")
    isolated_queue = PhageDiscoveryQueue(max_workers=1, db=isolated_db)

    mgr = PhageDiscoveryManager(project_root=tmp_path)
    mgr.db = isolated_db
    mgr.queue = isolated_queue
    mgr.queue.set_executor(mgr.execute_pipeline_task)

    class _MockScanner:
        @classmethod
        def from_model_dir(cls, model_dir, **kwargs):
            return cls()

        def scan_sequences(self, contig_seqs: Dict[str, str], **kwargs) -> ScanResult:
            cid, seq = next(iter(contig_seqs.items()))
            reg = PredictedRegion(
                contig_id=cid,
                start_bp=1000,
                end_bp=min(len(seq), 7000),
                peak_score=0.96,
                mean_score=0.84,
                window_count=3,
            )
            return ScanResult(
                contigs_bp={k: len(v) for k, v in contig_seqs.items()},
                total_bp=sum(len(v) for v in contig_seqs.values()),
                total_windows=4,
                raw_regions=[reg],
                verified_regions=[reg],
                gate_details=[],
                timings_sec={"total_sec": 0.05},
                contig_score_tracks={
                    cid: [
                        {
                            "start_bp": i * 2500,
                            "end_bp": min(len(seq), (i + 1) * 2500),
                            "max_prob": 0.96 if i in {1, 2} else 0.08,
                            "mean_prob": 0.84 if i in {1, 2} else 0.05,
                        }
                        for i in range(4)
                    ]
                },
                region_profiles={
                    f"{cid}:{reg.start_bp}-{reg.end_bp}": [
                        {"start_bp": 800, "end_bp": 1000, "prob": 0.12, "in_region": False},
                        {"start_bp": 1000, "end_bp": 1200, "prob": 0.91, "in_region": True},
                    ]
                },
            )

    monkeypatch.setattr("src.analysis.phage_finder.manager.GenomeScanner", _MockScanner)
    monkeypatch.setattr("src.analysis.phage_finder.manager.get_phage_discovery_manager", lambda: mgr)
    monkeypatch.setattr("src.backend.routes.phage_discovery.get_phage_discovery_manager", lambda: mgr)

    from src.backend.api_server import app

    with TestClient(app) as client:
        # 1. 确认旧核心蛋白比对路由已彻底移除
        old_resp = client.get("/api/analysis/protein_compare/categories")
        assert old_resp.status_code == 404

        # 2. 模型能力探测仅返回 V4.2
        caps = client.get("/api/analysis/phage_discovery/models")
        assert caps.status_code == 200
        caps_json = caps.json()
        assert caps_json["has_model"] is True
        assert len(caps_json["models"]) == 1
        assert caps_json["models"][0]["version"] == "V4.2"

        # 3. FASTA 预检
        fasta_body = f">contig_a test\n{_synth_dna(10000)}\n"
        insp = client.post(
            "/api/analysis/phage_discovery/inspect",
            json={"fasta_content": fasta_body},
        )
        assert insp.status_code == 200
        assert insp.json()["total_contigs"] == 1
        assert insp.json()["total_bp"] == 10000

        # 4. 提交任务并等待异步队列完成
        run_resp = client.post(
            "/api/analysis/phage_discovery/run",
            json={
                "task_name": "Demo_V42_Scan",
                "fasta_content": fasta_body,
                "selected_contigs": ["contig_a"],
                "device": "cpu",
                "apply_protein_gate": False,
                "min_region_bp": 3000,
            },
        )
        assert run_resp.status_code == 200
        task_id = run_resp.json()["task_id"]

        deadline = time.time() + 10.0
        final_status = ""
        while time.time() < deadline:
            res_resp = client.get(f"/api/analysis/phage_discovery/{task_id}/result")
            if res_resp.status_code == 200:
                task_info = res_resp.json()["task"]
                final_status = task_info["status"]
                if final_status in {"completed", "failed", "cancelled"}:
                    break
            time.sleep(0.1)

        assert final_status == "completed"

        # 5. 验证结果接口、单区 GBK、FASTA 文本提取与下载端点
        res_data = client.get(f"/api/analysis/phage_discovery/{task_id}/result").json()
        assert res_data["result"]["summary"]["region_count"] == 1
        assert len(res_data["result"]["regions"][0]["profile"]) == 2

        gbk_resp = client.get(f"/api/analysis/phage_discovery/{task_id}/region/1/gbk")
        assert gbk_resp.status_code == 200
        assert "LOCUS" in gbk_resp.json()["gbk_text"]

        fa_text_resp = client.get(f"/api/analysis/phage_discovery/{task_id}/fasta-text?region_index=1")
        assert fa_text_resp.status_code == 200
        assert ">Phage_001|contig_a:1001-7000" in fa_text_resp.json()["fasta_text"]

        for fmt in ("fasta", "tsv", "gff3", "gbk"):
            dl = client.get(f"/api/analysis/phage_discovery/{task_id}/download/{fmt}")
            assert dl.status_code == 200

        # 5b. 验证叠图 JSON 分片接口与全基因组叠图 GenBank 接口
        ov_resp = client.get(f"/api/analysis/phage_discovery/{task_id}/overlay?contig_id=contig_a")
        assert ov_resp.status_code == 200
        ov_json = ov_resp.json()
        assert ov_json["contig_id"] == "contig_a"
        assert ov_json["length_bp"] == 10000
        assert len(ov_json["score_tracks"]) == 4
        assert len(ov_json["base_tracks"]) > 0
        assert len(ov_json["regions"]) == 1

        ov_gbk_resp = client.get(f"/api/analysis/phage_discovery/{task_id}/overlay-gbk?contig_id=contig_a")
        assert ov_gbk_resp.status_code == 200
        ov_gbk_json = ov_gbk_resp.json()
        assert ov_gbk_json["contig_id"] == "contig_a"
        assert "prophage_region" in ov_gbk_json["gbk_text"]

        # 6. 历史记录与删除清理
        hist = client.get("/api/analysis/phage_discovery/history")
        assert hist.status_code == 200
        assert any(t["task_id"] == task_id for t in hist.json()["tasks"])

        del_resp = client.delete(f"/api/analysis/phage_discovery/{task_id}")
        assert del_resp.status_code == 200
        assert not (tmp_path / "results" / "phage_discovery" / task_id).exists()


def test_genbank_base_overlay_preservation_and_score_tracks(tmp_path: Path):
    seq_str = _synth_dna(18000, "ATGCGTACGTAGCTAGCTAAGGCTAGC")
    rec = SeqRecord(
        Seq(seq_str),
        id="host_chr1",
        name="host_chr1",
        description="Host genome with annotated CDS and tRNA",
        annotations={"molecule_type": "DNA", "topology": "circular", "data_file_division": "BCT"},
    )
    rec.features.append(
        SeqFeature(
            FeatureLocation(200, 1400, strand=1),
            type="CDS",
            qualifiers={"locus_tag": ["HOST_0001"], "gene": ["dnaA"], "product": ["chromosomal replication initiator"]},
        )
    )
    rec.features.append(
        SeqFeature(
            FeatureLocation(4500, 4580, strand=1),
            type="tRNA",
            qualifiers={"locus_tag": ["HOST_tRNA_1"], "product": ["tRNA-Arg"]},
        )
    )
    rec.features.append(
        SeqFeature(
            FeatureLocation(6200, 7400, strand=-1),
            type="CDS",
            qualifiers={"locus_tag": ["HOST_0002"], "gene": ["int"], "product": ["phage integrase family protein"]},
        )
    )
    gbk_in = tmp_path / "host_input.gbk"
    with open(gbk_in, "w", encoding="utf-8") as fh:
        SeqIO.write([rec], fh, "genbank")

    seqs, _, base_feats_map, fmt = load_sequences_with_annotations(fasta_path=str(gbk_in), project_root=tmp_path)
    assert fmt == "genbank"
    assert "host_chr1" in seqs
    assert len(base_feats_map["host_chr1"]) == 3
    assert base_feats_map["host_chr1"][1]["type"] == "tRNA"
    assert "integrase" in base_feats_map["host_chr1"][2]["product"]

    score_tracks = _collect_contig_score_tracks(
        [
            WindowPrediction(contig_id="host_chr1", start_bp=0, end_bp=5000, score=0.05),
            WindowPrediction(contig_id="host_chr1", start_bp=5000, end_bp=12000, score=0.94),
            WindowPrediction(contig_id="host_chr1", start_bp=12000, end_bp=18000, score=0.07),
        ],
        {"host_chr1": 18000},
        num_bins=60,
    )
    assert len(score_tracks["host_chr1"]) == 60

    region = PredictedRegion(
        contig_id="host_chr1",
        start_bp=5000,
        end_bp=12000,
        peak_score=0.94,
        mean_score=0.90,
        window_count=3,
    )
    scan_res = ScanResult(
        contigs_bp={"host_chr1": 18000},
        total_bp=18000,
        total_windows=3,
        raw_regions=[region],
        verified_regions=[region],
        gate_details=[],
        timings_sec={"total_sec": 0.1},
        contig_score_tracks=score_tracks,
    )
    out_dir = tmp_path / "results" / "phage_discovery" / "phage_gbk_ov"
    exported = export_scan_artifacts(
        task_id="phage_gbk_ov",
        task_name="GBK_Overlay_Test",
        model_info={"model_id": "student_v4_2", "version": "V4.2", "label": "Student V4.2"},
        device_used="cpu",
        apply_protein_gate=False,
        sequences=seqs,
        scan_result=scan_res,
        out_dir=out_dir,
        base_features_by_contig=base_feats_map,
        source_format=fmt,
        input_source_path=str(gbk_in),
        project_root=tmp_path,
    )
    assert exported["summary"]["source_format"] == "genbank"
    ov_file = tmp_path / exported["payload"]["contigs"][0]["overlay_file"]
    assert ov_file.exists()
    ov_payload = json.loads(ov_file.read_text(encoding="utf-8"))
    feats = ov_payload["base_features"]
    assert len(feats) == 3
    assert feats[0]["in_prophage"] is False
    assert feats[2]["in_prophage"] is True
    assert feats[2]["overlay_region_id"] == "Phage_001"

    gbk_overlay_text = build_contig_overlay_gbk(
        contig_id="host_chr1",
        contig_seq=seqs["host_chr1"],
        base_features=feats,
        regions=exported["payload"]["regions"],
        source_format="genbank",
    )
    assert "prophage_region" in gbk_overlay_text
    assert "HOST_0001" in gbk_overlay_text
    assert "tRNA-Arg" in gbk_overlay_text


def test_completeness_classification_with_protein_gate_tiers():
    dummy_region = PredictedRegion(
        contig_id="NC_003197.2",
        start_bp=962600,
        end_bp=1005200,
        peak_score=0.992,
        mean_score=0.929,
        window_count=12,
    )

    def _make_gate(decision: str, tier: str, hallmark: int = 0, non_amg: int = 0) -> RegionGateResult:
        return RegionGateResult(
            region=dummy_region,
            decision=decision,
            tier=tier,
            gc_ratio=0.516,
            region_len_bp=42600,
            orf_count=56,
            coding_density=0.91,
            hallmark_hits=hallmark,
            non_amg_hits=non_amg,
            transposase_hits=0,
            amg_hits=0,
            total_hits=non_amg,
        )

    # 1. ProteinGate hallmark_confirmed 长区间与高 Hallmark 必须评定为 high（绝不能降级为 low）
    k_hallmark_high, lbl_hallmark_high = _classify_completeness(
        42600, 0.992, _make_gate("keep", "hallmark_confirmed", hallmark=17, non_amg=20)
    )
    assert k_hallmark_high == "high"
    assert "完整" in lbl_hallmark_high or "高可信" in lbl_hallmark_high

    # 2. 短区间但有少数 hallmark 标志蛋白应定为 medium
    k_hallmark_med, _ = _classify_completeness(
        11000, 0.91, _make_gate("keep", "hallmark_confirmed", hallmark=2, non_amg=3)
    )
    assert k_hallmark_med == "medium"

    # 3. 噬菌体蛋白簇支持（长区间强证据 -> high，否则 -> medium）
    k_cluster_high, _ = _classify_completeness(
        30000, 0.92, _make_gate("keep", "phage_cluster_confirmed", hallmark=0, non_amg=8)
    )
    assert k_cluster_high == "high"
    k_cluster_med, _ = _classify_completeness(
        15000, 0.88, _make_gate("keep", "phage_cluster_confirmed", hallmark=0, non_amg=4)
    )
    assert k_cluster_med == "medium"

    # 4. dark_matter_fallback 不得被硬编码折为 low，应按长度与模型分评价
    k_dm, _ = _classify_completeness(32000, 0.96, _make_gate("keep", "dark_matter_fallback"))
    assert k_dm == "intact_like"

    # 5. reject 归入 rejected；无门控或 gate_disabled 维持原神经评价规则
    k_rej, _ = _classify_completeness(42600, 0.99, _make_gate("reject", "rejected_high_gc_no_evidence"))
    assert k_rej == "rejected"
    k_no_gate, _ = _classify_completeness(42600, 0.992, None)
    assert k_no_gate == "intact_like"
    k_dis, _ = _classify_completeness(42600, 0.992, _make_gate("keep", "gate_disabled"))
    assert k_dis == "intact_like"


def test_phage_queue_strict_serial_cancel_and_snapshot_metadata(tmp_path: Path):
    import asyncio

    async def _scenario() -> None:
        db = PhageDiscoveryDB(tmp_path / "queue_serial.db")
        q = PhageDiscoveryQueue(max_workers=1, db=db)

        first_started = asyncio.Event()
        release_first = asyncio.Event()
        executed_order = []
        active_now = 0
        max_active_seen = 0

        async def _fake_executor(task_id: str, req, context):
            nonlocal active_now, max_active_seen
            active_now += 1
            max_active_seen = max(max_active_seen, active_now)
            executed_order.append(task_id)
            if task_id == "t1":
                first_started.set()
                await release_first.wait()
            db.mark_completed(task_id, {"region_count": 0}, {}, "")
            active_now -= 1

        q.set_executor(_fake_executor)
        await q.start()

        for tid, name in (("t1", "Genome_Alpha"), ("t2", "Genome_Beta"), ("t3", "Genome_Gamma")):
            db.create_task(tid, name, "student_v4_2", "V4.2", "cpu", False, status="queued")
            await q.enqueue(tid, None, {})

        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        snap = q.get_queue_snapshot()
        assert max_active_seen == 1
        assert snap["running"] == ["t1"]
        assert snap["queued"] == ["t2", "t3"]
        assert snap["is_busy"] is True
        assert snap["running_tasks"][0]["task_id"] == "t1"
        assert snap["running_tasks"][0]["task_name"] == "Genome_Alpha"
        assert [w["task_id"] for w in snap["waiting_tasks"]] == ["t2", "t3"]
        assert [w["position"] for w in snap["waiting_tasks"]] == [1, 2]

        # 取消排队中的 t2：必须立刻从 queued 与 waiting_tasks 剔除，且 t3 位次前移为 #1
        cancel_res = await q.cancel_task("t2")
        assert cancel_res["status"] == "cancelled"
        snap_after_cancel = q.get_queue_snapshot()
        assert snap_after_cancel["queued"] == ["t3"]
        assert snap_after_cancel["queued_count"] == 1
        assert [w["task_id"] for w in snap_after_cancel["waiting_tasks"]] == ["t3"]
        assert snap_after_cancel["waiting_tasks"][0]["position"] == 1
        t2_row = db.get_task("t2")
        assert t2_row is not None and t2_row["status"] == "cancelled"

        # 释放 t1 后，仅 t3 按序执行，max_active_seen 始终为 1
        release_first.set()
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            s = q.get_queue_snapshot()
            if s["running_count"] == 0 and s["queued_count"] == 0:
                break
            await asyncio.sleep(0.02)

        assert max_active_seen == 1
        assert executed_order == ["t1", "t3"]
        t3_row = db.get_task("t3")
        assert t3_row is not None and t3_row["status"] == "completed"

        for w in q._workers:
            w.cancel()
        await asyncio.gather(*q._workers, return_exceptions=True)

    asyncio.run(_scenario())


def test_manager_rapid_concurrent_submit_and_delete_queued(tmp_path: Path, monkeypatch):
    import asyncio
    from src.analysis.phage_finder.types import PhageScanRunRequest

    model_dir = tmp_path / "models" / "full_v4" / "student_v4_2"
    _create_mock_v4_2_dir(model_dir)

    async def _scenario() -> None:
        db = PhageDiscoveryDB(tmp_path / "rapid_submit.db")
        mgr = PhageDiscoveryManager(project_root=tmp_path)
        mgr.db = db
        mgr.queue = PhageDiscoveryQueue(max_workers=1, db=db)

        t1_entered = asyncio.Event()
        release_t1 = asyncio.Event()
        executed = []

        async def _fake_exec(task_id: str, req, context):
            executed.append(task_id)
            if len(executed) == 1:
                t1_entered.set()
                await release_t1.wait()
            db.mark_completed(task_id, {"region_count": 0}, {}, "")

        mgr.queue.set_executor(_fake_exec)
        await mgr.initialize_queue_worker()

        monkeypatch.setattr(
            "src.analysis.phage_finder.manager.detect_compute_environment",
            lambda: {"default_device": "cpu", "cuda_available": False, "cpu_count": 4, "safe_workers": 2},
        )

        fasta_body = f">c1\n{_synth_dna(4000)}\n"
        req1 = PhageScanRunRequest(task_name="Rapid_1", fasta_content=fasta_body, device="cpu")
        req2 = PhageScanRunRequest(task_name="Rapid_2", fasta_content=fasta_body, device="cpu")
        req3 = PhageScanRunRequest(task_name="Rapid_3", fasta_content=fasta_body, device="cpu")

        res1, res2, res3 = await asyncio.gather(
            mgr.submit_task(req1),
            mgr.submit_task(req2),
            mgr.submit_task(req3),
        )
        assert len({res1["task_id"], res2["task_id"], res3["task_id"]}) == 3
        assert res1["status"] == "queued"
        assert "queue_position" in res2 and res2["queue_position"] >= 1
        assert res3["is_busy"] is True or res3["queued_count"] >= 2

        await asyncio.wait_for(t1_entered.wait(), timeout=2.0)

        # 删除尚在排队的第 2 个任务后，它绝不应被调度执行
        mgr.delete_task(res2["task_id"])
        assert db.get_task(res2["task_id"]) is None
        assert res2["task_id"] not in mgr.queue.get_queue_snapshot()["queued"]

        release_t1.set()
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            s = mgr.queue.get_queue_snapshot()
            if s["running_count"] == 0 and s["queued_count"] == 0:
                break
            await asyncio.sleep(0.02)

        assert res1["task_id"] in executed
        assert res2["task_id"] not in executed
        assert res3["task_id"] in executed

        for w in mgr.queue._workers:
            w.cancel()
        await asyncio.gather(*mgr.queue._workers, return_exceptions=True)

    asyncio.run(_scenario())


def test_model_registry_exposes_stage1_2_plateau_and_func_metadata(tmp_path: Path):
    models_root = tmp_path / "models"
    v4_2_dir = models_root / "full_v4" / "student_v4_2"
    _create_mock_v4_2_dir(v4_2_dir)
    (v4_2_dir / "student_v4_meta.json").write_text(
        json.dumps(
            {
                "params": 152947,
                "feature_profile": "stage1",
                "func_dim": 9,
                "use_context_refiner": True,
                "use_subbin_refiner": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (v4_2_dir / "student_v4_report.json").write_text(
        json.dumps(
            {
                "decoder_tuned_on_val": {
                    "seed_threshold": 0.95,
                    "extend_threshold": 0.30,
                    "sub_threshold": 0.35,
                    "plateau_min_windows": 4,
                    "plateau_second_threshold": 0.90,
                    "refine_pad_bp": 3000,
                    "smooth_profile": False,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    found = discover_available_models(project_root=tmp_path)
    assert len(found) == 1
    info = found[0]
    assert "Stage 1.2" in info["label"]
    assert info["feature_profile"] == "stage1"
    assert info["func_dim"] == 9
    dec = info["decoder_defaults"]
    assert dec["plateau_min_windows"] == 4
    assert dec["plateau_second_threshold"] == 0.90
    assert dec["refine_pad_bp"] == 3000
    assert dec["smooth_profile"] is False


def test_scanner_from_model_dir_propagates_and_overrides_plateau(tmp_path: Path, monkeypatch):
    from src.phage_discovery.inference.scanner import GenomeScanner

    model_dir = tmp_path / "stage1_2_mock"
    _create_mock_v4_2_dir(model_dir)
    (model_dir / "student_v4_report.json").write_text(
        json.dumps(
            {
                "decoder_tuned_on_val": {
                    "seed_threshold": 0.95,
                    "extend_threshold": 0.30,
                    "sub_threshold": 0.35,
                    "plateau_min_windows": 4,
                    "plateau_second_threshold": 0.90,
                    "refine_pad_bp": 3000,
                    "smooth_profile": False,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    captured_kwargs = []

    def _fake_init(self, **kwargs):
        captured_kwargs.append(kwargs)

    monkeypatch.setattr(GenomeScanner, "__init__", _fake_init)

    GenomeScanner.from_model_dir(model_dir)
    assert captured_kwargs[-1]["plateau_min_windows"] == 4
    assert captured_kwargs[-1]["plateau_second_threshold"] == 0.90
    assert captured_kwargs[-1]["refine_pad_bp"] == 3000
    assert captured_kwargs[-1]["smooth_sub_profile"] is False

    GenomeScanner.from_model_dir(model_dir, plateau_min_windows=2, plateau_second_threshold=0.88)
    assert captured_kwargs[-1]["plateau_min_windows"] == 2
    assert captured_kwargs[-1]["plateau_second_threshold"] == 0.88

    GenomeScanner.from_model_dir(model_dir, plateau_min_windows=0, plateau_second_threshold=None)
    assert captured_kwargs[-1]["plateau_min_windows"] == 0
    assert captured_kwargs[-1]["plateau_second_threshold"] is None


def test_manager_execute_forwards_plateau_and_functional_partitions(tmp_path: Path, monkeypatch):
    import asyncio
    from src.analysis.phage_finder.types import PhageScanRunRequest

    model_dir = tmp_path / "models" / "full_v4" / "student_v4_2"
    _create_mock_v4_2_dir(model_dir)
    (model_dir / "student_v4_meta.json").write_text(
        json.dumps(
            {
                "params": 152947,
                "feature_profile": "stage1",
                "func_dim": 9,
                "use_context_refiner": True,
                "use_subbin_refiner": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (model_dir / "student_v4_report.json").write_text(
        json.dumps(
            {
                "decoder_tuned_on_val": {
                    "seed_threshold": 0.95,
                    "extend_threshold": 0.30,
                    "sub_threshold": 0.35,
                    "plateau_min_windows": 4,
                    "plateau_second_threshold": 0.90,
                    "refine_pad_bp": 3000,
                    "smooth_profile": False,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from_dir_calls = []
    scan_seq_calls = []

    class _SpyScanner:
        @classmethod
        def from_model_dir(cls, model_path, **kwargs):
            from_dir_calls.append(kwargs)
            return cls()

        def scan_sequences(self, contig_seqs: Dict[str, str], **kwargs) -> ScanResult:
            scan_seq_calls.append(kwargs)
            return ScanResult(
                contigs_bp={k: len(v) for k, v in contig_seqs.items()},
                total_bp=sum(len(v) for v in contig_seqs.values()),
                total_windows=2,
                raw_regions=[],
                verified_regions=[],
                gate_details=[],
                timings_sec={"total_sec": 0.01},
            )

    monkeypatch.setattr("src.analysis.phage_finder.manager.GenomeScanner", _SpyScanner)
    monkeypatch.setattr(
        "src.analysis.phage_finder.manager.detect_compute_environment",
        lambda: {"default_device": "cpu", "cuda_available": False, "cpu_count": 4, "safe_workers": 2},
    )

    fasta_path = tmp_path / "test.fasta"
    fasta_path.write_text(f">ctg1\n{_synth_dna(8000)}\n", encoding="utf-8")

    isolated_db = PhageDiscoveryDB(db_path=tmp_path / "db" / "spy_phage_discovery.db")

    async def _run_case(req_overrides: Dict[str, object]) -> None:
        mgr = PhageDiscoveryManager(project_root=tmp_path)
        mgr.db = isolated_db
        mgr.queue = PhageDiscoveryQueue(max_workers=1, db=isolated_db)
        model_info = resolve_model_dir(project_root=tmp_path)
        task_id = f"spy_{len(from_dir_calls)}"
        task_dir = tmp_path / "results" / "phage_discovery" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        mgr.db.create_task(
            task_id=task_id,
            task_name="Spy",
            model_id=str(model_info["model_id"]),
            model_version="V4.2",
            device="cpu",
            apply_protein_gate=False,
            status="queued",
        )
        req = PhageScanRunRequest(
            task_name="Spy",
            fasta_path=str(fasta_path),
            device="cpu",
            apply_protein_gate=False,
            **req_overrides,
        )
        ctx = {
            "task_dir": str(task_dir),
            "staged_fasta_path": str(fasta_path),
            "model_info": model_info,
            "resolved_device": "cpu",
            "workers": 1,
            "gate_resources": {},
            "device_fallback": False,
        }
        await mgr.execute_pipeline_task(task_id, req, ctx)

    asyncio.run(_run_case({}))
    assert from_dir_calls[-1]["plateau_min_windows"] == 4
    assert from_dir_calls[-1]["plateau_second_threshold"] == 0.90
    assert scan_seq_calls[-1]["collect_functional_partitions"] is True

    asyncio.run(_run_case({"plateau_min_windows": 0}))
    assert from_dir_calls[-1]["plateau_min_windows"] == 0
    assert from_dir_calls[-1]["plateau_second_threshold"] is None


def test_exporter_attaches_optional_functional_modules(tmp_path: Path):
    seq1 = _synth_dna(18000, "ATGAAATTGCATGGCTAGCTAGCTAGCTAG")
    reg = PredictedRegion("chr_func", 4000, 12000, 0.96, 0.89, 4)
    scan_res = ScanResult(
        contigs_bp={"chr_func": 18000},
        total_bp=18000,
        total_windows=7,
        raw_regions=[reg],
        verified_regions=[reg],
        gate_details=[],
        timings_sec={"total_sec": 0.1},
        region_functional_modules={
            "chr_func:4000-12000": {
                "module_scores": {"head_packaging": 0.82, "tail": 0.78},
                "active_modules": ["head_packaging", "tail"],
                "orf_module_counts": {"head_packaging": 2, "tail": 3},
                "has_structural_core": True,
                "has_lysis_module": False,
                "structural_completeness_hint": "complete_structural_core",
                "lifestyle_hint": "lytic_or_cryptic",
                "mge_contamination_score": 0.02,
                "orf_count": 8,
                "orfs": [{"start_bp": 4100, "end_bp": 4700}],
            }
        },
    )
    out_dir = tmp_path / "out_func"
    exported = export_scan_artifacts(
        task_id="func_export_01",
        task_name="FuncExport",
        model_info={"model_id": "student_v4_2", "version": "V4.2", "label": "Stage 1.2"},
        device_used="cpu",
        apply_protein_gate=False,
        sequences={"chr_func": seq1},
        scan_result=scan_res,
        out_dir=out_dir,
        flank_bp=2000,
        project_root=tmp_path,
    )
    reg_out = exported["payload"]["regions"][0]
    assert "functional_modules" in reg_out
    assert reg_out["functional_modules"]["structural_completeness_hint"] == "complete_structural_core"
    assert reg_out["functional_modules"]["active_modules"] == ["head_packaging", "tail"]


def test_protein_gate_prefers_phage_refseq_over_generic_swissprot(tmp_path: Path, monkeypatch):
    from src.analysis.phage_finder.model_registry import resolve_protein_gate_resources

    ws_root = tmp_path / "workspace"
    swiss_dir = ws_root / "database" / "swissprot"
    swiss_dir.mkdir(parents=True, exist_ok=True)
    (swiss_dir / "swissprot.pin").write_bytes(b"mock_swissprot")

    sibling_db_dir = tmp_path / "Phage data" / "blastdb"
    sibling_db_dir.mkdir(parents=True, exist_ok=True)
    (sibling_db_dir / "phage_refseq_prot.pin").write_bytes(b"mock_phage_db")

    monkeypatch.delenv("PHAGE_DISCOVERY_BLAST_DB", raising=False)
    monkeypatch.setattr("src.analysis.phage_finder.model_registry._get_phage_config", lambda: {})
    monkeypatch.setattr("src.workbench.models.tool_config.ToolConfig.resolve_bio_tool", lambda name: "blastp")

    res = resolve_protein_gate_resources(project_root=ws_root)
    assert res["ready"] is True
    assert Path(res["blast_db"]).name == "phage_refseq_prot"


def test_model_registry_and_scanner_prefer_stage1_2_directory_and_filenames(tmp_path: Path, monkeypatch):
    from src.phage_discovery.inference.scanner import GenomeScanner

    ws_root = tmp_path / "workspace"
    models_root = ws_root / "models" / "full_v4"
    _create_mock_v4_2_dir(models_root / "student_v4_2")

    s12_dir = models_root / "stage1_2"
    s12_dir.mkdir(parents=True, exist_ok=True)
    (s12_dir / "stage1_2.pt").write_bytes(b"mock_stage1_2_weights")
    (s12_dir / "context_refiner.pt").write_bytes(b"mock_ctx")
    (s12_dir / "subbin_refiner.pt").write_bytes(b"mock_subbin")
    (s12_dir / "stage1_2_meta.json").write_text(
        json.dumps(
            {
                "params": 3715879,
                "feature_profile": "stage1",
                "func_dim": 9,
                "use_context_refiner": True,
                "use_subbin_refiner": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (s12_dir / "stage1_2_report.json").write_text(
        json.dumps(
            {
                "decoder_tuned_on_val": {
                    "seed_threshold": 0.95,
                    "extend_threshold": 0.30,
                    "sub_threshold": 0.35,
                    "plateau_min_windows": 4,
                    "plateau_second_threshold": 0.90,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PHAGE_DISCOVERY_MODEL_DIR", raising=False)
    monkeypatch.delenv("PHAGE_DISCOVERY_MODELS_ROOT", raising=False)
    monkeypatch.setattr("src.analysis.phage_finder.model_registry._get_phage_config", lambda: {})

    found = discover_available_models(project_root=ws_root)
    assert len(found) == 2
    assert found[0]["model_id"] == "stage1_2"
    assert Path(found[0]["path"]).resolve() == s12_dir.resolve()
    assert Path(found[0]["weights_file"]).name == "stage1_2.pt"
    assert "Stage 1.2" in found[0]["label"]
    assert found[0]["version"] == "Stage 1.2"
    assert found[0]["decoder_defaults"]["plateau_min_windows"] == 4

    import asyncio
    from src.analysis.phage_finder.types import PhageScanRunRequest

    mgr = PhageDiscoveryManager(project_root=ws_root)

    async def _noop_enqueue(task_id: str, req, ctx):
        return {"queue_position": 1, "is_busy": False, "running_count": 0, "queued_count": 1}

    monkeypatch.setattr(mgr.queue, "enqueue", _noop_enqueue)
    sub_res = asyncio.run(
        mgr.submit_task(PhageScanRunRequest(task_name="s12_run_check", fasta_content=">c1\n" + ("ATGC" * 100)))
    )
    row = mgr.db.get_task(sub_res["task_id"])
    assert row is not None
    assert row["model_version"] == "Stage 1.2"

    captured: Dict[str, object] = {}

    def _fake_init(self, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(GenomeScanner, "__init__", _fake_init)
    GenomeScanner.from_model_dir(s12_dir)
    assert Path(str(captured["model_pt_path"])).name == "stage1_2.pt"
    assert Path(str(captured["meta_path"])).name == "stage1_2_meta.json"
    assert captured["plateau_min_windows"] == 4
    assert captured["plateau_second_threshold"] == 0.90


def test_model_registry_promotes_unified_model_over_stage1_2_when_present(tmp_path: Path, monkeypatch):
    ws_root = tmp_path / "workspace"
    models_v4 = ws_root / "models" / "full_v4"
    s12_dir = models_v4 / "stage1_2"
    s12_dir.mkdir(parents=True, exist_ok=True)
    (s12_dir / "stage1_2.pt").write_bytes(b"mock_s12")
    (s12_dir / "context_refiner.pt").write_bytes(b"mock_ctx")
    (s12_dir / "subbin_refiner.pt").write_bytes(b"mock_sub")
    (s12_dir / "stage1_2_meta.json").write_text(
        json.dumps({"params": 3715879, "feature_profile": "stage1", "func_dim": 9, "use_subbin_refiner": True}),
        encoding="utf-8",
    )

    uni_dir = models_v4 / "orf_judge_unified"
    uni_dir.mkdir(parents=True, exist_ok=True)
    (uni_dir / "unified_judge_seq.pt").write_bytes(b"mock_uni")
    (uni_dir / "orf_judge_statonly.pt").write_bytes(b"mock_stat")
    (uni_dir / "unified_summary.json").write_text(json.dumps({"total_params": 1684718}), encoding="utf-8")

    monkeypatch.delenv("PHAGE_DISCOVERY_MODEL_DIR", raising=False)
    monkeypatch.delenv("PHAGE_DISCOVERY_MODELS_ROOT", raising=False)
    monkeypatch.setattr("src.analysis.phage_finder.model_registry._get_phage_config", lambda: {})

    found = discover_available_models(project_root=ws_root)
    assert len(found) >= 2
    assert found[0]["model_id"] == "unified"
    assert found[0]["version"] == "Unified V4"
    assert found[0]["has_unified_judge"] is True
    assert Path(found[0]["unified_judge_dir"]).resolve() == uni_dir.resolve()
    assert found[1]["model_id"] == "stage1_2"

    # 当升级为 unified_v4_3 时应准确上报 Unified V4.3 版本标识
    (uni_dir / "unified_summary.json").write_text(
        json.dumps({"arch": "unified_v4_3", "total_params": 1747664}),
        encoding="utf-8",
    )
    found_v43 = discover_available_models(project_root=ws_root)
    assert found_v43[0]["version"] == "Unified V4.3"
    assert found_v43[0]["params"] == 3715879 + 1747664


def test_manager_executes_unified_phage_model_and_exports_unified_artifacts(tmp_path: Path, monkeypatch):
    import asyncio
    from src.analysis.phage_finder.types import PhageScanRunRequest
    from src.phage_discovery.inference.unified_model import UnifiedScanResult

    ws_root = tmp_path / "workspace"
    models_v4 = ws_root / "models" / "full_v4"
    s12_dir = models_v4 / "stage1_2"
    s12_dir.mkdir(parents=True, exist_ok=True)
    (s12_dir / "stage1_2.pt").write_bytes(b"mock_s12")
    (s12_dir / "subbin_refiner.pt").write_bytes(b"mock_sub")
    (s12_dir / "stage1_2_meta.json").write_text(
        json.dumps({"params": 3715879, "feature_profile": "stage1", "func_dim": 9, "use_subbin_refiner": True}),
        encoding="utf-8",
    )
    uni_dir = models_v4 / "orf_judge_unified"
    uni_dir.mkdir(parents=True, exist_ok=True)
    (uni_dir / "unified_judge_seq.pt").write_bytes(b"mock_uni")
    (uni_dir / "orf_judge_statonly.pt").write_bytes(b"mock_stat")

    class _MockScanner:
        workers = 1

        @classmethod
        def from_model_dir(cls, model_path, **kwargs):
            return cls()

    class _MockUnifiedModel:
        def __init__(self, dna_scanner, judge_bundle=None, **kwargs):
            self.dna_scanner = dna_scanner
            self.judge_bundle = judge_bundle

        def scan_sequences(self, contig_seqs: Dict[str, str], **kwargs) -> UnifiedScanResult:
            cid, seq = next(iter(contig_seqs.items()))
            reg = PredictedRegion(cid, 1000, 9000, peak_score=0.95, mean_score=0.88, window_count=4)
            key = f"{cid}:1000-9000"
            return UnifiedScanResult(
                contigs_bp={cid: len(seq)},
                total_bp=len(seq),
                total_windows=5,
                base_regions=[],
                regions=[reg],
                region_annotations={
                    key: {
                        "n_orfs": 9,
                        "mean_phage_prob": 0.91,
                        "max_p9_defense_prob": 0.18,
                        "r2_core_completeness_sum": 4.2,
                        "r2_core_active_count": 4,
                        "completeness_class": "complete_structural_core",
                        "active_modules": ["head_packaging", "connector", "tail", "lysis"],
                    }
                },
                routing_stats={"total_contigs": 1, "protein_activated_contigs": 1, "protein_skip_ratio": 0.0, "unified_judge_mode": True},
                timings_sec={"dna_feature_sec": 0.02, "protein_judge_sec": 0.01, "total_sec": 0.03},
                suppressed_candidates=[{"contig_id": cid, "start_bp": 12000, "end_bp": 18000, "reason": "base_veto", "mean_phage_prob": 0.21, "max_p9": 0.85}],
                region_profiles={key: [{"start_bp": 800, "end_bp": 1000, "prob": 0.1, "in_region": False}, {"start_bp": 1000, "end_bp": 1200, "prob": 0.92, "in_region": True}]},
                contig_score_tracks={cid: [{"start_bp": 0, "end_bp": len(seq), "max_prob": 0.95, "mean_prob": 0.5}]},
            )

    monkeypatch.setattr("src.analysis.phage_finder.manager.GenomeScanner", _MockScanner)
    monkeypatch.setattr("src.analysis.phage_finder.manager.load_judge_ensemble_bundle", lambda *a, **kw: {"unified_mode": True})
    monkeypatch.setattr("src.analysis.phage_finder.manager.UnifiedPhageModel", _MockUnifiedModel)
    monkeypatch.setattr("src.analysis.phage_finder.model_registry._get_phage_config", lambda: {})
    monkeypatch.setattr(
        "src.analysis.phage_finder.manager.detect_compute_environment",
        lambda: {"default_device": "cpu", "cuda_available": False, "cpu_cores": 4, "safe_workers": 2},
    )

    fa_path = ws_root / "test_unified.fasta"
    fa_path.write_text(f">ctg_u1\n{_synth_dna(20000)}\n", encoding="utf-8")

    isolated_db = PhageDiscoveryDB(db_path=tmp_path / "db" / "uni_wb.db")
    mgr = PhageDiscoveryManager(project_root=ws_root)
    mgr.db = isolated_db
    mgr.queue = PhageDiscoveryQueue(max_workers=1, db=isolated_db)
    model_info = resolve_model_dir(project_root=ws_root)
    assert model_info["model_id"] == "unified"

    task_id = "uni_wb_01"
    task_dir = ws_root / "results" / "phage_discovery" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    mgr.db.create_task(task_id, "Unified_Test", "unified", "Unified V4", "cpu", False, status="queued")
    req = PhageScanRunRequest(task_name="Unified_Test", fasta_path=str(fa_path), device="cpu", apply_protein_gate=False)
    ctx = {
        "task_dir": str(task_dir),
        "staged_fasta_path": str(fa_path),
        "model_info": model_info,
        "resolved_device": "cpu",
        "workers": 1,
        "gate_resources": {},
        "device_fallback": False,
    }
    asyncio.run(mgr.execute_pipeline_task(task_id, req, ctx))
    exported = json.loads((task_dir / f"{task_id}_result.json").read_text(encoding="utf-8"))
    assert exported["summary"]["model_id"] == "unified"
    assert exported["summary"]["model_version"] == "Unified V4"
    assert exported["summary"]["region_count"] == 1
    assert exported["regions"][0]["completeness_key"] == "high"
    assert "head_packaging" in exported["regions"][0]["functional_modules"]["active_modules"]
    assert len(exported["rejected_candidates"]) == 1




