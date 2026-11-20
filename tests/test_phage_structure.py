# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测核心引擎单元测试与多形态真实样本验证
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.analysis.phage_structure.morphotype_classifier import (
    build_connector_profile,
    build_module_matrix,
    classify_morphotype,
)
from src.analysis.phage_structure.phrog_catalog import classify_structural_role
from src.analysis.phage_structure.sequence_annotator import (
    check_wsl_pyhmmer_ready,
    parse_input_contigs,
    predict_missing_orfs_parallel,
    resolve_structural_hmm_path,
    scan_proteins_with_pyhmmer,
)
from src.analysis.phage_structure.tmp_analyzer import (
    detect_polyx_regions,
    detect_tandem_repeats,
    select_and_analyze_tmps,
)
from src.analysis.phage_structure.types import StructureProteinItem

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_phrog_catalog_disambiguation() -> None:
    """确保易混蛋白名称 (tail tubular vs tail tube, TMP vs chaperone, T6SS) 精确隔离。"""
    assert classify_structural_role("tail tubular protein")[0] == "TTPA_B"
    assert classify_structural_role("tail tube protein")[0] == "TTP"
    assert classify_structural_role("tail length tape measure protein")[0] == "TMP"
    assert classify_structural_role("tail length tape measure protein chaperone")[0] == "TAP"
    assert classify_structural_role("tail sheath")[0] == "TSP"
    assert classify_structural_role("type VI secretion system contractile sheath large subunit TssC")[0] == "T6SS_CONFOUNDER"
    assert classify_structural_role("internal virion protein with endolysin domain")[0] == "INTERNAL_VIRION"
    assert classify_structural_role("head-tail adaptor Ad3")[0] == "CONN_AD3"
    assert classify_structural_role("head closure Hc3")[0] == "CONN_HC3"
    assert classify_structural_role("tail completion or Neck1 protein")[0] == "CONN_NECK1"
    assert classify_structural_role("assembly (protein IV of M13)")[0] == "NON_TAILED_MARKER"
    assert classify_structural_role("RNA replicase beta subunit")[0] == "NON_TAILED_MARKER"
    assert classify_structural_role("pentameric base spike protein")[0] == "NON_TAILED_MARKER"
    assert classify_structural_role("pilot protein for DNA ejection")[0] == "NON_TAILED_MARKER"
    assert classify_structural_role("tail sheath and receptor binding protein")[0] == "COLLAR_PODO"
    assert classify_structural_role("virion RNA polymerase")[0] == "INTERNAL_VIRION"


def test_tmp_polyx_and_tandem_repeats_quantitative() -> None:
    """验证 TMP polyX 同聚区与 Tandem Repeats 串联重复阵列检测。"""
    unit = "AGSTKLQAAG"
    seq = "MSKL" + ("A" * 8) + "VLRDEK" + (unit * 4) + ("G" * 10) + "YTRN"
    px_regs, px_tot, px_sum = detect_polyx_regions(seq)
    assert len(px_regs) >= 2
    assert px_tot >= 18
    assert "A" in px_sum and "G" in px_sum

    trs, tr_tot = detect_tandem_repeats(seq)
    assert len(trs) >= 1
    assert tr_tot >= 30
    assert any(tr.period_aa == 10 and tr.copy_number >= 3.5 for tr in trs)


def test_t6ss_isolation_no_myovirus_false_positive() -> None:
    """细菌 VI 型分泌系统 T6SS (TssB/TssC/Hcp/VgrG) 绝不能误报为肌尾噬菌体。"""
    prots = [
        StructureProteinItem(
            locus_tag="BAC_001", contig_id="chr1", start=1, end=500, strand="+", length_aa=166,
            product="type VI secretion system contractile sheath small subunit TssB",
            structural_role="T6SS_CONFOUNDER", translation="M" * 166,
        ),
        StructureProteinItem(
            locus_tag="BAC_002", contig_id="chr1", start=520, end=2000, strand="+", length_aa=490,
            product="type VI secretion system contractile sheath large subunit TssC",
            structural_role="T6SS_CONFOUNDER", translation="A" * 490,
        ),
        StructureProteinItem(
            locus_tag="BAC_003", contig_id="chr1", start=2050, end=3500, strand="+", length_aa=480,
            product="type VI secretion system protein VgrG",
            structural_role="T6SS_CONFOUNDER", translation="V" * 480,
        ),
    ]
    mm = build_module_matrix(prots)
    cp = build_connector_profile(prots)
    pred = classify_morphotype(prots, [], mm, cp)
    assert pred.morphotype_code == "Incomplete"
    assert mm.t6ss_confounder_count == 3
    assert mm.tail_sheath_count == 0


def test_synthetic_myo_sipho_podo_and_tmp_filtering() -> None:
    """验证经典三科判别逻辑及对 <250aa TMP 碎片的过滤保护。"""
    # 1. Podoviridae 即使带一个低分短假 TMP 碎片也不能压过 Type3/TTPA_B/InternalVirion
    podo_prots = [
        StructureProteinItem(
            locus_tag="P_1", contig_id="podo", start=1, end=900, strand="+", length_aa=300,
            product="portal protein", structural_role="PORTAL", hmm_score=200.0, translation="M" * 300,
        ),
        StructureProteinItem(
            locus_tag="P_2", contig_id="podo", start=950, end=2000, strand="+", length_aa=350,
            product="major head protein", structural_role="MCP", hmm_score=310.0, translation="M" * 350,
        ),
        StructureProteinItem(
            locus_tag="P_3", contig_id="podo", start=2050, end=2550, strand="+", length_aa=166,
            product="head-tail adaptor Ad3", structural_role="CONN_AD3", hmm_score=220.0, translation="M" * 166,
        ),
        StructureProteinItem(
            locus_tag="P_4", contig_id="podo", start=2600, end=5000, strand="+", length_aa=800,
            product="internal virion protein", structural_role="INTERNAL_VIRION", hmm_score=900.0, translation="M" * 800,
        ),
        StructureProteinItem(
            locus_tag="P_5", contig_id="podo", start=5100, end=5700, strand="+", length_aa=203,
            product="tail length tape measure protein", structural_role="TMP", hmm_score=14.4,
            evidence_source="pyhmmer_phrog", translation="M" * 203,
        ),
    ]
    tmps = select_and_analyze_tmps(podo_prots, has_tailed_context=True)
    assert len(tmps) == 0  # 203 aa / sc=14.4 碎片被安全屏蔽
    pred_podo = classify_morphotype(podo_prots, tmps)
    assert pred_podo.morphotype_code == "Podoviridae-like"
    assert pred_podo.confidence >= 0.85

    # 2. Siphoviridae: MTP + TAP + 真实 TMP (带 polyX 与 TR)
    tmp_seq = ("MAKL" + "A" * 8 + "SGTA" * 6 + "QRVLE" * 5 + "G" * 7 + "LKA") * 12
    sipho_prots = [
        StructureProteinItem(
            locus_tag="S_1", contig_id="sipho", start=1, end=1000, strand="+", length_aa=333,
            product="major tail protein", structural_role="MTP", hmm_score=400.0, translation="M" * 333,
        ),
        StructureProteinItem(
            locus_tag="S_2", contig_id="sipho", start=1050, end=1500, strand="+", length_aa=150,
            product="tail assembly chaperone", structural_role="TAP", hmm_score=160.0, translation="M" * 150,
        ),
        StructureProteinItem(
            locus_tag="S_3", contig_id="sipho", start=1550, end=1550 + len(tmp_seq) * 3, strand="+", length_aa=len(tmp_seq),
            product="tail length tape measure protein", structural_role="TMP", hmm_score=1100.0, translation=tmp_seq,
        ),
        StructureProteinItem(
            locus_tag="S_4", contig_id="sipho", start=5000, end=5600, strand="+", length_aa=200,
            product="tail completion or Neck1 protein", structural_role="CONN_NECK1", hmm_score=240.0, translation="M" * 200,
        ),
    ]
    s_tmps = select_and_analyze_tmps(sipho_prots, has_tailed_context=True)
    assert len(s_tmps) == 1 and s_tmps[0].polyx_total_aa > 0 and s_tmps[0].tr_total_aa > 0
    pred_sipho = classify_morphotype(sipho_prots, s_tmps)
    assert pred_sipho.morphotype_code == "Siphoviridae-like"
    assert pred_sipho.estimated_tail_length_nm is not None and pred_sipho.estimated_tail_length_nm > 100.0


@pytest.mark.skipif(
    not (check_wsl_pyhmmer_ready() and resolve_structural_hmm_path() is not None),
    reason="需要 WSL PyHMMER 与 structural_phrogs.h3m 索引库",
)
def test_real_genomes_end_to_end_morphotypes() -> None:
    """使用真机 PHROG HMM 对本地真实标注注释噬菌体样本与对照进行形态校验。"""
    cases = [
        (REPO_ROOT / "results" / "annotations" / "ANNO_NC_005859" / "ANNO.gbk", "Siphoviridae-like", True),
        (REPO_ROOT / "results" / "annotations" / "ANNO_4C84D6BB" / "ANNO.gbk", "Siphoviridae-like", True),
        (REPO_ROOT / "results" / "annotations" / "ANNO_03290961" / "ANNO.gbk", "Myoviridae-like", True),
        (REPO_ROOT / "results" / "annotations" / "ANNO_1418C944" / "ANNO.gbk", "Myoviridae-like", True),
        (REPO_ROOT / "results" / "annotations" / "ANNO_8CFE4CC4" / "ANNO.gbk", "Siphoviridae-like", True),
    ]
    ran = 0
    for gbk_p, expected_morph, expect_tmp in cases:
        if not gbk_p.is_file():
            continue
        ran += 1
        cmap = parse_input_contigs(fasta_path=str(gbk_p))
        predict_missing_orfs_parallel(cmap, workers=8)
        scan_proteins_with_pyhmmer(cmap, workers=12)
        cid = next(iter(cmap))
        prots = cmap[cid]["proteins"]
        mm = build_module_matrix(prots)
        cp = build_connector_profile(prots)
        has_tail = (mm.tail_sheath_count + mm.major_tail_count + mm.tail_assembly_chaperone_count + mm.tape_measure_count) > 0
        tmps = select_and_analyze_tmps(prots, has_tailed_context=has_tail)
        pred = classify_morphotype(prots, tmps, mm, cp)
        assert pred.morphotype_code == expected_morph, f"{gbk_p}: got {pred.morphotype_code} ({pred.class_scores})"
        if expect_tmp:
            assert len(tmps) >= 1 and tmps[0].length_aa >= 500
    assert ran >= 2


def test_fastapi_routes_paste_annotation_linkage_and_cleanup() -> None:
    """验证 FastAPI /analysis/phage_structure 全路由、多格式导出、断点分片及注释联动闭环。"""
    from src.backend.api_server import app

    faa_payload = "\n".join([
        ">G1_01 major capsid protein [Phage X]",
        "MSKLVLRDEK" * 35,
        ">G1_02 portal protein [Phage X]",
        "MVTGRKLQSD" * 32,
        ">G1_03 major tail protein [Phage X]",
        "MAGKSTVLQD" * 28,
        ">G1_04 tail assembly chaperone [Phage X]",
        "MDKLQPRSTV" * 16,
        ">G1_05 tail length tape measure protein [Phage X]",
        ("MAKL" + "A" * 7 + "SGTA" * 5 + "QRVLE" * 4 + "G" * 6) * 14,
    ])

    with TestClient(app) as client:
        cap = client.get("/api/analysis/phage_structure/capabilities")
        assert cap.status_code == 200
        cap_json = cap.json()
        assert "wsl_pyhmmer_ready" in cap_json and "phold_ready" in cap_json and "phagetailfinder_ready" in cap_json

        srcs = client.get("/api/analysis/phage_structure/sources")
        assert srcs.status_code == 200
        src_data = srcs.json()
        assert "annotations" in src_data and "phage_discoveries" in src_data

        insp = client.post(
            "/api/analysis/phage_structure/inspect",
            json={"source_mode": "paste", "fasta_content": faa_payload},
        )
        assert insp.status_code == 200
        assert insp.json()["num_contigs"] == 1

        run_resp = client.post(
            "/api/analysis/phage_structure/run",
            json={
                "task_name": "Pytest_Sipho_Paste",
                "source_mode": "paste",
                "fasta_content": faa_payload,
            },
        )
        assert run_resp.status_code == 200
        task_id = run_resp.json()["task_id"]

        result_payload = None
        for _ in range(180):
            res_r = client.get(f"/api/analysis/phage_structure/{task_id}/result")
            if res_r.status_code == 200:
                result_payload = res_r.json()
                break
            time.sleep(0.2)
        try:
            assert result_payload is not None
            assert result_payload["primary_prediction"]["morphotype_code"] == "Siphoviridae-like"
            assert result_payload["summary"]["tmp_count"] >= 1

            # 校验分片 Checkpoint 及三张 TSV 导出
            shard_file = REPO_ROOT / "results" / "phage_structure" / task_id / "checkpoints" / "contig_001.json"
            assert shard_file.is_file()

            for ft in ("json", "summary_tsv", "features_tsv", "tmp_tsv"):
                dl = client.get(f"/api/analysis/phage_structure/{task_id}/download/{ft}")
                assert dl.status_code == 200 and len(dl.content) > 20
        finally:
            del_r = client.delete(f"/api/analysis/phage_structure/{task_id}")
            assert del_r.status_code == 200

        # 如本地存在 ANNO_NC_005859，则顺带验证历史注释任务联动直通
        anno_gbk = REPO_ROOT / "results" / "annotations" / "ANNO_NC_005859" / "ANNO.gbk"
        if anno_gbk.is_file():
            insp_a = client.post(
                "/api/analysis/phage_structure/inspect",
                json={"source_mode": "annotation", "source_task_id": "ANNO_NC_005859"},
            )
            assert insp_a.status_code == 200 and insp_a.json()["num_contigs"] >= 1
            run_a = client.post(
                "/api/analysis/phage_structure/run",
                json={
                    "task_name": "Pytest_Link_NC005859",
                    "source_mode": "annotation",
                    "source_task_id": "ANNO_NC_005859",
                },
            )
            assert run_a.status_code == 200
            tid_a = run_a.json()["task_id"]
            res_a = None
            for _ in range(200):
                r2 = client.get(f"/api/analysis/phage_structure/{tid_a}/result")
                if r2.status_code == 200:
                    res_a = r2.json()
                    break
                time.sleep(0.2)
            try:
                assert res_a is not None
                assert res_a["primary_prediction"]["morphotype_code"] == "Siphoviridae-like"
                assert "ptf_tail_protein_count" in res_a["contigs"][0]
                gbk_r = client.get(f"/api/analysis/phage_structure/{tid_a}/gbk")
                assert gbk_r.status_code == 200 and "LOCUS " in gbk_r.json()["gbkText"]
            finally:
                client.delete(f"/api/analysis/phage_structure/{tid_a}")


def test_phagetailfinder_log_viterbi_collinearity_and_tailocin_warning() -> None:
    """校验 PhageTailFinder 对数 Viterbi 防长序列下溢/共线性挽救及无头收缩尾素预警。"""
    from src.analysis.phage_structure.tail_finder_adapter import decode_tail_sequence, load_ptf_params

    params = load_ptf_params()
    assert len(params.emission_by_pfam) == 3668

    # 模拟 600 个 ORF：前 400 为非尾背景 + 缺失值，第 420~430 嵌入典型尾部 Pfam 簇中间夹 1 个未知 ORF (None)
    obs = ["PF00589" if i % 40 == 0 else None for i in range(600)]
    obs[420] = "PF05135"
    obs[421] = "PF05521"
    obs[422] = None  # 被共线性转移挽救的未知蛋白
    obs[423] = "PF05939"
    obs[424] = "PF05100"

    flags, probs = decode_tail_sequence(obs, params, accurate_mode=False)
    assert len(flags) == 600 and len(probs) == 600
    assert all(0.0 <= pr <= 1.0 for pr in probs)
    assert flags[420] == 1 and flags[424] == 1
    assert probs[422] > probs[10]

    # 校验无头部/包装蛋白但带有 TSP 的基因组触发 Tailocin/eCIS 预警
    headless_myo = [
        StructureProteinItem(
            locus_tag=f"T_{i}", contig_id="contig_x", start=i * 1000 + 1, end=i * 1000 + 900, strand="+",
            length_aa=300, product="tail sheath protein" if i == 0 else "baseplate wedge subunit",
            structural_role="TSP" if i == 0 else "BASEPLATE_MYO", hmm_score=220.0, translation="M" * 300,
        )
        for i in range(14)
    ]
    pred_headless = classify_morphotype(headless_myo, [])
    assert pred_headless.morphotype_code == "Myoviridae-like"
    assert any("Tailocin" in w for w in pred_headless.warnings)


def test_schitoviridae_nontailed_and_lytic_tmp_collinearity() -> None:
    """验证 Schitoviridae (N4-like)、5类 Non-tailed 与带溶菌域 TMP 共线性识别（防 DNA 甲基化酶误抓）。"""
    # 1. Schitoviridae (N4-like): 巨型 vRNAP + 非收缩鞘 + 405aa 短通道蛋白不能误判 Sipho/Myo
    n4_prots = [
        StructureProteinItem(
            locus_tag="N4_VRNAP", contig_id="n4", start=100, end=10600, strand="+", length_aa=3500,
            product="virion RNA polymerase", phrog_id="phrog_2206", structural_role="INTERNAL_VIRION", hmm_score=3900.0, translation="M" * 3500,
        ),
        StructureProteinItem(
            locus_tag="N4_MCP", contig_id="n4", start=11000, end=12200, strand="+", length_aa=401,
            product="major head protein", phrog_id="phrog_1357", structural_role="MCP", hmm_score=500.0, translation="M" * 401,
        ),
        StructureProteinItem(
            locus_tag="N4_CHAN", contig_id="n4", start=12300, end=13515, strand="+", length_aa=405,
            product="tail length tape measure protein", phrog_id="phrog_2120", structural_role="TMP", hmm_score=460.0, translation="M" * 405,
        ),
        StructureProteinItem(
            locus_tag="N4_POR", contig_id="n4", start=13600, end=15889, strand="+", length_aa=763,
            product="portal protein", phrog_id="phrog_1216", structural_role="PORTAL", hmm_score=900.0, translation="M" * 763,
        ),
        StructureProteinItem(
            locus_tag="N4_SHEATH", contig_id="n4", start=17000, end=21146, strand="+", length_aa=1382,
            product="tail sheath and receptor binding protein", phrog_id="phrog_15324", structural_role="COLLAR_PODO", hmm_score=2600.0, translation="M" * 1382,
        ),
    ]
    n4_tmps = select_and_analyze_tmps(n4_prots, has_tailed_context=True)
    n4_pred = classify_morphotype(n4_prots, n4_tmps, genome_length_bp=70000)
    assert n4_pred.morphotype_code == "Podoviridae-like"

    # 2. Compact Tectiviridae (缺 Portal/Connector，短 TerL 225aa，带弱跨膜溶菌域) -> Non-tailed
    tecti_prots = [
        StructureProteinItem(
            locus_tag="T_POL", contig_id="tecti", start=100, end=2000, strand="+", length_aa=630,
            product="DNA polymerase", phrog_id="phrog_1907", structural_role="OTHER", hmm_score=345.0, translation="M" * 630,
        ),
        StructureProteinItem(
            locus_tag="T_ATPASE", contig_id="tecti", start=3000, end=3675, strand="+", length_aa=225,
            product="terminase large subunit", phrog_id="phrog_2666", structural_role="TERL", hmm_score=182.0, translation="M" * 225,
        ),
        StructureProteinItem(
            locus_tag="T_VERTEX", contig_id="tecti", start=4000, end=5197, strand="+", length_aa=399,
            product="minor head protein", phrog_id="phrog_5863", structural_role="HEAD_SCAFFOLD_PROTEASE", hmm_score=393.0, translation="M" * 399,
        ),
        StructureProteinItem(
            locus_tag="T_SPIKE", contig_id="tecti", start=6000, end=6520, strand="+", length_aa=173,
            product="pentameric base spike protein", phrog_id="phrog_8240", structural_role="NON_TAILED_MARKER", hmm_score=371.0, translation="M" * 173,
        ),
    ]
    tecti_pred = classify_morphotype(tecti_prots, [], genome_length_bp=16500)
    assert tecti_pred.morphotype_code == "Non-tailed"

    # 3. 融合溶菌域 TMP (如 PF06791 TMP_2 或紧邻 TAP 的 LYSIS 1229aa) 不得误抓远端 DNA 甲基化酶
    tm4_like = [
        StructureProteinItem(
            locus_tag="TM_TAP", contig_id="tm4", start=1000, end=1450, strand="+", length_aa=150,
            product="tail assembly chaperone", structural_role="TAP", hmm_score=160.0, translation="M" * 150,
        ),
        StructureProteinItem(
            locus_tag="TM_REAL_TMP", contig_id="tm4", start=1500, end=5187, strand="+", length_aa=1229,
            product="endolysin", phrog_id="phrog_971", structural_role="LYSIS", hmm_score=1200.0,
            ptf_pfam="PF06791", ptf_pfam_desc="TMP_2", ptf_is_tail=True, ptf_tail_prob=0.99, translation="M" * 1229,
        ),
        StructureProteinItem(
            locus_tag="DIST_METHYL", contig_id="tm4", start=35000, end=37262, strand="+", length_aa=754,
            product="hypothetical protein", structural_role="OTHER", ptf_pfam="PF01555",
            ptf_pfam_desc="Methyltransf_25", translation="M" * 754,
        ),
    ]
    tm4_tmps = select_and_analyze_tmps(tm4_like, has_tailed_context=True)
    assert len(tm4_tmps) == 1 and tm4_tmps[0].locus_tag == "TM_REAL_TMP"
    assert tm4_tmps[0].evidence_kind == "confirmed_tmp"

    # 4. 紧邻 TAP 下游第 1 位的真 TMP 应击败更下游的次要尾蛋白；古菌多基板肌尾不应因缺失细菌 TSP 而错判长尾
    a511_prots = [
        StructureProteinItem(
            locus_tag="A_TAP", contig_id="a511", start=100, end=700, strand="+", length_aa=200,
            product="tail assembly chaperone", structural_role="TAP", hmm_score=140.0, translation="M" * 200,
        ),
        StructureProteinItem(
            locus_tag="A_TMP_1242", contig_id="a511", start=750, end=4475, strand="+", length_aa=1242,
            product="tail associated lysin", structural_role="TAIL_OTHER", hmm_score=1300.0, translation="M" * 1242,
        ),
        StructureProteinItem(
            locus_tag="A_TAIL_795", contig_id="a511", start=4500, end=6885, strand="+", length_aa=795,
            product="tail protein with lysin activity", structural_role="TAIL_OTHER", hmm_score=1000.0, translation="M" * 795,
        ),
    ]
    a511_tmps = select_and_analyze_tmps(a511_prots, has_tailed_context=True)
    assert len(a511_tmps) == 1 and a511_tmps[0].locus_tag == "A_TMP_1242"

    halovirus_myo = [
        StructureProteinItem(locus_tag="V1", contig_id="hv", start=1, end=600, strand="+", length_aa=198, product="head-tail adaptor", structural_role="CONN_GENERAL", hmm_score=110.0, translation="M" * 198),
        StructureProteinItem(locus_tag="V2", contig_id="hv", start=700, end=1150, strand="+", length_aa=145, product="tail completion or Neck1 protein", structural_role="CONN_NECK1", hmm_score=60.0, translation="M" * 145),
        StructureProteinItem(locus_tag="V3", contig_id="hv", start=1200, end=2010, strand="+", length_aa=270, product="tail length tape measure protein", structural_role="TMP", hmm_score=40.6, translation="M" * 270),
        StructureProteinItem(locus_tag="V4", contig_id="hv", start=2100, end=2900, strand="+", length_aa=260, product="baseplate hub", structural_role="BASEPLATE_MYO", hmm_score=95.0, translation="M" * 260),
        StructureProteinItem(locus_tag="V5", contig_id="hv", start=3000, end=4200, strand="+", length_aa=420, product="baseplate wedge subunit", structural_role="BASEPLATE_MYO", hmm_score=165.0, translation="M" * 420),
        StructureProteinItem(locus_tag="V6", contig_id="hv", start=4300, end=4900, strand="+", length_aa=202, product="baseplate protein", structural_role="BASEPLATE_MYO", hmm_score=155.0, translation="M" * 202),
    ]
    hv_pred = classify_morphotype(halovirus_myo, select_and_analyze_tmps(halovirus_myo), genome_length_bp=58000)
    assert hv_pred.morphotype_code == "Myoviridae-like"
