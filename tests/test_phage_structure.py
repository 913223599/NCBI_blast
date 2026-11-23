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
    analyze_single_tmp,
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
    """验证 Schitoviridae (N4-like)、5类 Non-tailed 与基于上下文/多域机制的假 TMP 通用免疫。"""
    # 0. 验证即使词典不打单点补丁、外部仍传 phrog_2120 且名称写为 tape measure，但只要位于头包装三明治区且无长尾干核心，
    #    通用操纵子语境校验仍能独立将其拦截为 []（不再依赖逐个 phrog_xxxx 补丁）
    # 1. Schitoviridae (N4-like): 巨型 vRNAP + 非收缩鞘 + 374/405aa 通道蛋白不能误判 Sipho/Myo 且禁止用 TMP 估测尾长
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
            locus_tag="N4_CHAN_EXPLICIT_GBK", contig_id="n4", start=12300, end=13515, strand="+", length_aa=374,
            product="tail length tape measure protein", phrog_id="phrog_2120", structural_role="TMP", hmm_score=433.0, translation="M" * 374,
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
    assert n4_tmps == []  # 通用操纵子与头部三明治规则直接在 TMP 选择层拦截，不靠特例补丁
    n4_pred = classify_morphotype(n4_prots, n4_tmps, genome_length_bp=72566)
    assert n4_pred.morphotype_code == "Podoviridae-like"
    assert n4_pred.estimated_tail_length_nm is None
    assert n4_pred.estimated_tail_range_nm == []
    # 若上游强行注入未通过验证的假 TMP，MorphotypeClassifier 也必须兜底压制尾长并输出警告
    fake_injected = [
        analyze_single_tmp(
            StructureProteinItem(
                locus_tag="FAKE_374", contig_id="n4", start=12300, end=13515, strand="+", length_aa=374,
                product="tail length tape measure protein", structural_role="TMP", hmm_score=433.0, translation="M" * 374,
            ),
            evidence_kind="confirmed_tmp",
        )
    ]
    n4_guarded = classify_morphotype(n4_prots, fake_injected, genome_length_bp=72566)
    assert n4_guarded.morphotype_code == "Podoviridae-like"
    assert n4_guarded.estimated_tail_length_nm is None
    assert any("非长尾/肌尾" in w or "无 TMP 分子标尺" in w for w in n4_guarded.warnings)

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


def test_fastapi_batch_import_auto_queue_execution(tmp_path: Path) -> None:
    """校验批量导入 API（多文件顺序入队 + 多条 FASTA 拆分）依次自动排队执行完毕与持久化排序。"""
    from fastapi.testclient import TestClient
    from src.backend.api_server import app

    faa_1 = (
        ">B1_MCP major capsid protein\n" + "A" * 340 + "\n"
        ">B1_TSP tail sheath protein\n" + "M" * 520 + "\n"
        ">B1_BASE baseplate wedge subunit\n" + "V" * 260 + "\n"
    )
    faa_2 = (
        ">B2_PORTAL portal protein\n" + "A" * 420 + "\n"
        ">B2_TTPA tail tubular protein A\n" + "L" * 210 + "\n"
        ">B2_TTPB tail tubular protein B\n" + "K" * 720 + "\n"
    )
    f1 = tmp_path / "batch_myo_sample.faa"
    f2 = tmp_path / "batch_podo_sample.faa"
    f1.write_text(faa_1, encoding="utf-8")
    f2.write_text(faa_2, encoding="utf-8")

    from src.analysis.phage_structure.manager import get_phage_structure_manager
    from src.analysis.phage_structure.types import StructureBatchItemRequest, StructureBatchRunRequest

    mgr = get_phage_structure_manager()
    split_req = StructureBatchRunRequest(
        items=[StructureBatchItemRequest(source_mode="paste", fasta_content=">S1\nATG" + "A" * 120 + "\n>S2\nATG" + "C" * 120 + "\n")],
        split_fasta_records=True,
    )
    expanded = mgr._expand_batch_item_to_runs(split_req.items[0], split_req, 1)
    assert [r.task_name for r in expanded] == ["S1_Structure", "S2_Structure"]

    with TestClient(app) as client:
        batch_resp = client.post(
            "/api/analysis/phage_structure/batch",
            json={
                "items": [
                    {"source_mode": "file", "fasta_path": str(f1)},
                    {"source_mode": "file", "fasta_path": str(f2)},
                ],
                "enable_phagetailfinder": False,
            },
        )
        assert batch_resp.status_code == 200
        payload = batch_resp.json()
        assert payload["batch_count"] == 2
        tids = payload["task_ids"]
        assert len(tids) == 2
        assert payload["tasks"][0]["task_name"] == "batch_myo_sample_Structure"
        assert payload["tasks"][1]["task_name"] == "batch_podo_sample_Structure"

        try:
            finished: dict[str, dict] = {}
            for _ in range(300):
                for tid in tids:
                    if tid in finished:
                        continue
                    r = client.get(f"/api/analysis/phage_structure/{tid}/result")
                    if r.status_code == 200:
                        finished[tid] = r.json()
                if len(finished) == 2:
                    break
                hist_now = client.get("/api/analysis/phage_structure/history?limit=10").json()["tasks"]
                failed_rows = [it for it in hist_now if it["task_id"] in tids and it["status"] == "failed"]
                if failed_rows:
                    raise AssertionError(f"批量任务执行失败: {failed_rows}")
                time.sleep(0.2)

            assert len(finished) == 2
            assert finished[tids[0]]["primary_prediction"]["morphotype_code"] == "Myoviridae-like"
            assert finished[tids[1]]["primary_prediction"]["morphotype_code"] == "Podoviridae-like"

            hist = client.get("/api/analysis/phage_structure/history?limit=10").json()["tasks"]
            hist_ids = [item["task_id"] for item in hist]
            assert tids[1] in hist_ids and tids[0] in hist_ids
            # 确定性逆序（后入队 rowid 更大排前，保证同秒不乱序）
            assert hist_ids.index(tids[1]) < hist_ids.index(tids[0])
        finally:
            for tid in tids:
                client.delete(f"/api/analysis/phage_structure/{tid}")


def test_adversarial_nonstandard_gbk_immunity(tmp_path: Path) -> None:
    """
    对抗性非标准 GBK 免疫测试：
    1) 内存级验证：未核实文本且夹在头部的假 "tape measure" (385aa) 必须被剔除，
       而隐藏于 MTP->TAP 下游且被错标为 hypothetical / 多域遮蔽的真 960aa TMP 必须被精准挽救；
    2) 端到端真实 GBK 篡改测试：删除 /phrog 标签、将 TerL/Portal 恶意改为 tape measure、将真 TMP 改为未知蛋白并删除 translation，
       验证序列优先 HMM + 多域 Pfam + 上下文验证完全还原真实结构与尾长。
    """
    real_seq = ("MAKL" + "G" * 6 + "ASTKQLRAEG" * 5) * 16
    adv_prots = [
        StructureProteinItem(
            locus_tag="ADV_POR", contig_id="adv1", start=100, end=1600, strand="+", length_aa=500,
            product="portal protein", structural_role="PORTAL", hmm_score=500.0, translation="M" * 500,
        ),
        StructureProteinItem(
            locus_tag="ADV_BOGUS_TMP", contig_id="adv1", start=1700, end=2855, strand="+", length_aa=385,
            product="tail length tape measure protein", raw_product="tail length tape measure protein",
            structural_role="TMP", hmm_score=0.0, evidence_source="unverified_text", translation="M" * 385,
        ),
        StructureProteinItem(
            locus_tag="ADV_MCP", contig_id="adv1", start=2900, end=4100, strand="+", length_aa=400,
            product="major head protein", structural_role="MCP", hmm_score=400.0, translation="M" * 400,
        ),
        StructureProteinItem(
            locus_tag="ADV_MTP", contig_id="adv1", start=6000, end=6600, strand="+", length_aa=200,
            product="major tail protein", structural_role="MTP", hmm_score=220.0, translation="M" * 200,
        ),
        StructureProteinItem(
            locus_tag="ADV_TAP", contig_id="adv1", start=6650, end=7100, strand="+", length_aa=150,
            product="tail assembly chaperone", structural_role="TAP", hmm_score=160.0, translation="M" * 150,
        ),
        StructureProteinItem(
            locus_tag="ADV_REAL_TMP", contig_id="adv1", start=7120, end=7120 + len(real_seq) * 3, strand="+",
            length_aa=len(real_seq), product="uncharacterized protein", raw_product="uncharacterized protein",
            structural_role="OTHER", hmm_score=0.0, evidence_source="genbank",
            ptf_pfam="PF01464", ptf_pfam_desc="SLT", ptf_all_pfams=["PF01464", "PF06791"],
            ptf_is_tail=True, ptf_tail_prob=0.92, translation=real_seq,
        ),
    ]
    tmps = select_and_analyze_tmps(adv_prots, has_tailed_context=True, contig_length_bp=25000)
    assert [t.locus_tag for t in tmps] == ["ADV_REAL_TMP"]
    pred = classify_morphotype(adv_prots, tmps, genome_length_bp=25000)
    assert pred.morphotype_code == "Siphoviridae-like"
    assert pred.estimated_tail_length_nm == round(len(real_seq) * 0.145, 1)

    # 若本地 ANNO_NC_005859 与 WSL PyHMMER 就绪，运行真实完整序列的恶意非标 GBK 还原测试
    anno_gbk = REPO_ROOT / "results" / "annotations" / "ANNO_NC_005859" / "ANNO.gbk"
    if check_wsl_pyhmmer_ready() and resolve_structural_hmm_path() is not None and anno_gbk.is_file():
        from Bio import SeqIO
        from src.analysis.phage_structure.tail_finder_adapter import (
            is_phagetailfinder_ready,
            run_phagetailfinder_on_contigs,
        )

        clean_cmap = parse_input_contigs(fasta_path=str(anno_gbk))
        scan_proteins_with_pyhmmer(clean_cmap, workers=8, verify_annotated=True)
        if is_phagetailfinder_ready():
            run_phagetailfinder_on_contigs(clean_cmap, workers=8)
        clean_prots = list(clean_cmap.values())[0]["proteins"]
        clean_tmps = select_and_analyze_tmps(clean_prots, has_tailed_context=True)
        assert clean_tmps, "基线 NC_005859 应能稳定检出 TMP"
        clean_tmp_len = clean_tmps[0].length_aa
        clean_tmp_lt = clean_tmps[0].locus_tag

        # 构造严重污染的不标准 GBK：清空全部 /phrog、/note，随机互换虚假/未知产物名，并剥除 TMP 的 /translation
        recs = list(SeqIO.parse(str(anno_gbk), "genbank"))
        for rec in recs:
            for feat in rec.features:
                if feat.type != "CDS":
                    continue
                lt = (feat.qualifiers.get("locus_tag") or [""])[0]
                prod = (feat.qualifiers.get("product") or [""])[0].lower()
                feat.qualifiers.pop("phrog", None)
                feat.qualifiers.pop("note", None)
                feat.qualifiers.pop("db_xref", None)
                if lt == clean_tmp_lt or "tape measure" in prod:
                    feat.qualifiers["product"] = ["uncharacterized conserved phage protein"]
                    feat.qualifiers.pop("translation", None)
                elif "terminase large" in prod or "portal" in prod:
                    feat.qualifiers["product"] = ["putative tail length tape measure protein"]

        messy_gbk = tmp_path / "corrupted_nonstandard.gbk"
        with messy_gbk.open("w", encoding="utf-8") as fh:
            SeqIO.write(recs, fh, "genbank")

        adv_cmap = parse_input_contigs(fasta_path=str(messy_gbk))
        scan_proteins_with_pyhmmer(adv_cmap, workers=8, verify_annotated=True)
        if is_phagetailfinder_ready():
            run_phagetailfinder_on_contigs(adv_cmap, workers=8)
        adv_rec_prots = list(adv_cmap.values())[0]["proteins"]
        adv_tmps = select_and_analyze_tmps(adv_rec_prots, has_tailed_context=True)
        adv_pred = classify_morphotype(adv_rec_prots, adv_tmps)
        assert adv_pred.morphotype_code == "Siphoviridae-like"
        assert adv_tmps and adv_tmps[0].length_aa == clean_tmp_len
        assert adv_pred.estimated_tail_length_nm == round(clean_tmp_len * 0.145, 1)


def test_unverified_gbk_non_tailed_text_ignored_on_podo() -> None:
    """
    大中型具备经序列验证的 Portal/TerL/MCP 的短尾基因组中，
    未经过 HMM 核实的 unverified_text ("major coat protein") 绝不能劫持判定为 Non-tailed。
    """
    podo_with_coat_text = [
        StructureProteinItem(
            locus_tag="EP_01", contig_id="ep15", start=100, end=1600, strand="+", length_aa=500,
            product="terminase large subunit", structural_role="TERL", hmm_score=173.6,
            evidence_source="pyhmmer_phrog", translation="M" * 500,
        ),
        StructureProteinItem(
            locus_tag="EP_02", contig_id="ep15", start=1650, end=3300, strand="+", length_aa=550,
            product="head-tail adaptor", structural_role="CONN_GENERAL", hmm_score=780.0,
            evidence_source="pyhmmer_phrog", translation="M" * 550,
        ),
        StructureProteinItem(
            locus_tag="EP_03", contig_id="ep15", start=3350, end=4400, strand="+", length_aa=335,
            product="major head protein", structural_role="MCP", hmm_score=305.0,
            evidence_source="pyhmmer_phrog", translation="M" * 335,
        ),
        StructureProteinItem(
            locus_tag="EP_04", contig_id="ep15", start=4500, end=4840, strand="+", length_aa=111,
            product="major coat protein", raw_product="major coat protein",
            structural_role="NON_TAILED_MARKER", hmm_score=0.0,
            evidence_source="unverified_text", translation="M" * 111,
        ),
        StructureProteinItem(
            locus_tag="EP_05", contig_id="ep15", start=5000, end=5600, strand="+", length_aa=180,
            product="internal virion protein", structural_role="INTERNAL_VIRION", hmm_score=230.0,
            evidence_source="pyhmmer_phrog", translation="M" * 180,
        ),
    ]
    pred = classify_morphotype(podo_with_coat_text, [], genome_length_bp=39672)
    assert pred.morphotype_code == "Podoviridae-like"
    assert pred.class_scores["Non-tailed"] == 0.0


def test_isolated_lysozyme2_crass_not_self_authenticated_tmp() -> None:
    """
    CrAss-like 等缺乏长尾干 (MTP/TSP/TTP/TAP/BASEPLATE) 锚点的有头基因组中，
    仅含 PF18013 (Phage_lysozyme2) + 弱 TMP 命中的 <650aa 孤立蛋白不可自我认证为 TMP。
    """
    crass_prots = [
        StructureProteinItem(
            locus_tag="CR_TERL", contig_id="cr1", start=1000, end=3250, strand="+", length_aa=750,
            product="terminase large subunit", structural_role="TERL", hmm_score=327.7,
            evidence_source="pyhmmer_phrog", translation="M" * 750,
        ),
        StructureProteinItem(
            locus_tag="CR_POR", contig_id="cr1", start=3300, end=5700, strand="+", length_aa=800,
            product="portal protein", structural_role="PORTAL", hmm_score=459.0,
            evidence_source="pyhmmer_phrog", translation="M" * 800,
        ),
        StructureProteinItem(
            locus_tag="CR_MCP", contig_id="cr1", start=8000, end=9500, strand="+", length_aa=500,
            product="major head protein", structural_role="MCP", hmm_score=354.0,
            evidence_source="pyhmmer_phrog", translation="M" * 500,
        ),
        StructureProteinItem(
            locus_tag="CR_LYZ2", contig_id="cr1", start=15000, end=16420, strand="+", length_aa=472,
            product="tail length tape measure protein", structural_role="TMP", hmm_score=77.3,
            evidence_source="pyhmmer_phrog", ptf_pfam="PF18013", ptf_all_pfams=["PF18013"],
            ptf_is_tail=True, ptf_tail_prob=0.99, translation="M" * 472,
        ),
    ]
    tmps = select_and_analyze_tmps(crass_prots, has_tailed_context=True, contig_length_bp=99915)
    assert tmps == []
    pred = classify_morphotype(crass_prots, tmps, genome_length_bp=99915)
    assert pred.morphotype_code == "Podoviridae-like"


def test_tem_truth_table_and_suite_e_disjoint() -> None:
    """
    校验 T0.2 TEM 标准真值表完整性、DOI 合规性以及 T0.1 Suite E 盲测集零重叠冻结边界。
    """
    import csv
    import json

    truth_tsv = REPO_ROOT / "tests" / "fixtures" / "phage_structure" / "tem_truth.tsv"
    manifest_json = REPO_ROOT / "tests" / "fixtures" / "phage_structure" / "suite_e_manifest.json"
    assert truth_tsv.is_file()
    assert manifest_json.is_file()

    with truth_tsv.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))

    assert len(rows) == 52
    suite_b = [r for r in rows if r["suite"] == "suite_b"]
    suite_d = [r for r in rows if r["suite"] == "suite_d"]
    assert len(suite_b) == 30
    assert len(suite_d) == 22

    accs = [r["accession"] for r in rows]
    assert len(set(accs)) == 52
    verified = [r for r in rows if r["verification_status"] == "verified"]
    assert len(verified) >= 40
    for r in verified:
        assert float(r["tem_nm"]) > 0
        assert r["state"] == "extended"
        assert r["doi"].startswith("10."), f"Invalid DOI in verified row: {r}"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    suite_e_accs = {e["acc"] for e in manifest["entries"]}
    assert len(suite_e_accs) == 224
    assert suite_e_accs.isdisjoint(set(accs))


def test_t1_1_completeness_gate_and_sparse_gbk_rescue(tmp_path: Path) -> None:
    """
    验证 T1.1：
    1. 仅含头部核心+Type 1连接器残骸（无长尾主干与正短尾标记）的截断 Contig 严禁误判 Podoviridae-like，应输出 Incomplete；
    2. 具备完整 Portal+TerL+MCP 且无 Type 1 残骸的远缘完整短尾（CrAss 样）正常判为 Podoviridae-like；
    3. 稀疏/半截漏标 .gbk（仅保留少数 CDS 且存在 >15 kb 大空缺）经 Pyrodigal 间隙回补后恢复尾部完整识别。
    """
    from Bio import SeqIO
    from src.analysis.phage_structure.completeness_gate import (
        assess_sparse_gbk_annotation,
        detect_terminal_repeats,
    )

    repeat_edge = "ATGCGTAAGCTTAGCTAGGCTAACGTAGCTTACCGATCGTAGCTAGCTAG"
    fake_genome = repeat_edge + ("A" * 5000) + repeat_edge
    has_dtr, dtr_len, _ = detect_terminal_repeats(fake_genome)
    assert has_dtr and dtr_len >= len(repeat_edge)

    truncated_tailed_prots = [
        StructureProteinItem(
            locus_tag="TR_POR", contig_id="frag1", start=100, end=1700, strand="+", length_aa=530,
            product="portal protein", structural_role="PORTAL", hmm_score=320.0,
            evidence_source="pyhmmer_phrog", translation="M" * 530,
        ),
        StructureProteinItem(
            locus_tag="TR_TERL", contig_id="frag1", start=1750, end=3300, strand="+", length_aa=515,
            product="terminase large subunit", structural_role="TERL", hmm_score=280.0,
            evidence_source="pyhmmer_phrog", translation="M" * 515,
        ),
        StructureProteinItem(
            locus_tag="TR_MCP", contig_id="frag1", start=3400, end=4500, strand="+", length_aa=360,
            product="major head protein", structural_role="MCP", hmm_score=310.0,
            evidence_source="pyhmmer_phrog", translation="M" * 360,
        ),
        StructureProteinItem(
            locus_tag="TR_AD1", contig_id="frag1", start=4600, end=5100, strand="+", length_aa=160,
            product="head-tail adaptor Ad1", structural_role="CONN_AD1", hmm_score=140.0,
            evidence_source="pyhmmer_phrog", translation="M" * 160,
        ),
    ]
    trunc_pred = classify_morphotype(truncated_tailed_prots, [], genome_length_bp=28_000)
    assert trunc_pred.morphotype_code == "Incomplete"
    assert any("截断" in w or "短尾" in w for w in trunc_pred.warnings)

    complete_podo_prots = [
        p for p in truncated_tailed_prots if p.structural_role != "CONN_AD1"
    ] + [
        StructureProteinItem(
            locus_tag="PO_TO", contig_id="frag2", start=6000, end=7200, strand="+", length_aa=390,
            product="tail protein", structural_role="TAIL_OTHER", hmm_score=150.0,
            evidence_source="pyhmmer_phrog", translation="M" * 390,
        ),
    ]
    podo_pred = classify_morphotype(complete_podo_prots, [], genome_length_bp=75_000)
    assert podo_pred.morphotype_code == "Podoviridae-like"

    lambda_gbk = Path(r"F:\Phage data\gbk\NC_001416.1.gbk")
    if lambda_gbk.is_file():
        recs = list(SeqIO.parse(str(lambda_gbk), "genbank"))
        kept = []
        cds_seen = 0
        for feat in recs[0].features:
            if feat.type != "CDS":
                kept.append(feat)
            elif cds_seen < 6:
                kept.append(feat)
                cds_seen += 1
        recs[0].features = kept
        sparse_gbk = tmp_path / "sparse_lambda.gbk"
        with sparse_gbk.open("w", encoding="utf-8") as fh:
            SeqIO.write(recs, fh, "genbank")

        cmap = parse_input_contigs(fasta_path=str(sparse_gbk))
        cid, info = next(iter(cmap.items()))
        is_sparse, cov, gap = assess_sparse_gbk_annotation(info["length_bp"], info["proteins"])
        assert is_sparse and cov < 0.30 and gap > 20_000
        predict_missing_orfs_parallel(cmap, genetic_code=11, workers=4)
        assert info["sparse_rescued_orfs"] >= 35
        scan_proteins_with_pyhmmer(cmap, workers=4, verify_annotated=True)
        tmps = select_and_analyze_tmps(info["proteins"], has_tailed_context=True, contig_length_bp=info["length_bp"])
        pred = classify_morphotype(
            info["proteins"],
            tmps,
            genome_length_bp=info["length_bp"],
            dna_seq=info["dna_seq"],
            sparse_rescued_orfs=info["sparse_rescued_orfs"],
        )
        assert pred.morphotype_code == "Siphoviridae-like"
        assert tmps and tmps[0].length_aa >= 800


def test_t1_2_genetic_code_selector_11_4_15() -> None:
    """
    验证 T1.2：对 10+ 株重编码样本（Table 4 真实基因组与真实噬菌体基因组按天然阅读框重编码的 Table 4 UGA->Trp / Table 15 UAG->Gln）
    及多株标准 Table 11 基因组，遗传密码自动选择准确无误且彻底消除 Pyrodigal 混用警告。
    """
    import warnings
    import pyrodigal
    from src.analysis.phage_structure.genetic_code_selector import select_optimal_genetic_code

    def recode_real_phage(seq_s: str, mode: str, tag_stride: int = 3) -> str:
        # 基于真实噬菌体基因阅读框将 Trp(TGG/CCA)->TGA/TCA 或 Gln(CAA,CAG/TTG,CTG)->TAG/CTA，保留天然密码子偏置与反链终止分布
        gf = pyrodigal.GeneFinder(meta=False)
        tb = (seq_s * ((100_000 // len(seq_s)) + 1)).encode("ascii") if len(seq_s) < 100_000 else seq_s.encode("ascii")
        gf.train(tb, translation_table=11)
        genes = [g for g in gf.find_genes(seq_s.encode("ascii")) if (g.end - g.begin + 1) >= 450]
        arr = list(seq_s)
        for g in genes:
            step = 0
            for pos in range(g.begin - 1 + 3, g.end - 3, 3):
                cod = "".join(arr[pos : pos + 3])
                if g.strand == 1:
                    if mode == "TGA" and cod == "TGG":
                        arr[pos : pos + 3] = list("TGA")
                    elif mode == "TAG" and cod in ("CAG", "CAA") and step % tag_stride == 0:
                        arr[pos : pos + 3] = list("TAG")
                else:
                    if mode == "TGA" and cod == "CCA":
                        arr[pos : pos + 3] = list("TCA")
                    elif mode == "TAG" and cod in ("CTG", "TTG") and step % tag_stride == 0:
                        arr[pos : pos + 3] = list("CTA")
                step += 1
        return "".join(arr)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # 1) 真实 Table 4 噬菌体基因组 (2 株)
        for fn in ("NC_002515.1.fasta", "NC_003438.1.fasta"):
            fp = Path(r"F:\Phage data\fasta") / fn
            if fp.is_file():
                info = next(iter(parse_input_contigs(fasta_path=str(fp)).values()))
                code, switched, _ = select_optimal_genetic_code(info["dna_seq"])
                assert code == 4 and switched

        # 2) 基于真实完整噬菌体基因组 (Lambda / T7 / T4片段) 构建完整重编码基因组，并模拟重编码基因组碎片切片 (共 9 株，含真实 Table 4 共 11 株)
        seq_lambda = next(iter(parse_input_contigs(fasta_path=str(Path(r"F:\Phage data\fasta\NC_001416.1.fasta"))).values()))["dna_seq"]
        seq_t7 = next(iter(parse_input_contigs(fasta_path=str(Path(r"F:\Phage data\fasta\NC_001604.1.fasta"))).values()))["dna_seq"]
        seq_t4_60k = next(iter(parse_input_contigs(fasta_path=str(Path(r"F:\Phage data\fasta\NC_000866.4.fasta"))).values()))["dna_seq"][:60000]

        recoded_lambda_4 = recode_real_phage(seq_lambda, "TGA")
        table4_cases = [
            recoded_lambda_4,
            recoded_lambda_4[0:12000],
            recode_real_phage(seq_t7, "TGA"),
            recode_real_phage(seq_t4_60k, "TGA"),
        ]
        for s4_rec in table4_cases:
            c4, sw4, _ = select_optimal_genetic_code(s4_rec)
            assert c4 == 4 and sw4

        recoded_lambda_15 = recode_real_phage(seq_lambda, "TAG", tag_stride=3)
        table15_cases = [
            recoded_lambda_15,
            recoded_lambda_15[12000:24000],
            recoded_lambda_15[36000:48502],
            recode_real_phage(seq_t7, "TAG", tag_stride=2),
            recode_real_phage(seq_t4_60k, "TAG", tag_stride=2),
        ]
        for s15_rec in table15_cases:
            c15, sw15, _ = select_optimal_genetic_code(s15_rec)
            assert c15 == 15 and sw15

        # 3) 标准 Table 11 噬菌体绝不误漂移且 Pyrodigal 不抛 STOP codon mismatch 警告
        for std_fn in ("NC_001416.1.fasta", "NC_001604.1.fasta", "NC_001422.1.fasta"):
            std_cmap = parse_input_contigs(fasta_path=str(Path(r"F:\Phage data\fasta") / std_fn))
            std_info = next(iter(std_cmap.values()))
            std_code, std_sw, _ = select_optimal_genetic_code(std_info["dna_seq"])
            assert std_code == 11 and not std_sw

        lambda_cmap = parse_input_contigs(fasta_path=str(Path(r"F:\Phage data\fasta\NC_001416.1.fasta")))
        lambda_info = next(iter(lambda_cmap.values()))
        predict_missing_orfs_parallel(lambda_cmap, genetic_code=11, auto_select_genetic_code=True, workers=2)
        assert lambda_info["genetic_code_used"] == 11

    stop_warnings = [str(w.message) for w in caught if "STOP codons" in str(w.message)]
    assert stop_warnings == []


def test_t1_3_split_tmp_merger_positive_and_negatives() -> None:
    """
    验证 T1.3：
    1. 正例：D3112 型相邻移码拆分 TMP（PF06791 + PF09718 重叠分裂）精准合并为 merged_split_tmp，消除两端起始差；
    2. 负例 1：TAP + TMP 相邻绝不误合并；
    3. 负例 2：间隔 >120 bp 或非 TMP 长蛋白绝不误合并。
    """
    from src.analysis.phage_structure.tmp_split_merger import find_and_merge_split_tmps

    # 正例 (D3112 坐标: 25274..26818 与 26767..28833 -> 物理跨度 1185 aa)
    p_mtp = StructureProteinItem(
        locus_tag="D_MTP", contig_id="d3112", start=23884, end=24654, strand="+", length_aa=256,
        product="major tail protein", structural_role="MTP", hmm_score=311.0,
        evidence_source="pyhmmer_phrog", translation="M" * 256,
    )
    p_tap = StructureProteinItem(
        locus_tag="D_TAP", contig_id="d3112", start=24658, end=25143, strand="+", length_aa=161,
        product="tail assembly chaperone", structural_role="TAP", hmm_score=194.5,
        evidence_source="pyhmmer_phrog", translation="M" * 161,
    )
    p_tmp_n = StructureProteinItem(
        locus_tag="D_TMP_N", contig_id="d3112", start=25274, end=26818, strand="+", length_aa=514,
        product="tail length tape measure protein", structural_role="TMP", hmm_score=407.0,
        evidence_source="pyhmmer_phrog", ptf_pfam="PF06791", ptf_all_pfams=["PF06791"],
        ptf_is_tail=True, ptf_tail_prob=0.98, translation="M" * 514,
    )
    p_tmp_c = StructureProteinItem(
        locus_tag="D_TMP_C", contig_id="d3112", start=26767, end=28833, strand="+", length_aa=688,
        product="tail length tape measure protein", structural_role="TMP", hmm_score=370.3,
        evidence_source="pyhmmer_phrog", ptf_pfam="PF09718", ptf_all_pfams=["PF09718"],
        ptf_is_tail=True, ptf_tail_prob=0.99, translation="A" * 688,
    )
    merged = find_and_merge_split_tmps([p_mtp, p_tap, p_tmp_n, p_tmp_c])
    assert len(merged) == 1
    assert merged[0].protein.length_aa == 1185
    assert merged[0].source_loci == ["D_TMP_N", "D_TMP_C"]

    tmps = select_and_analyze_tmps([p_mtp, p_tap, p_tmp_n, p_tmp_c], has_tailed_context=True, contig_length_bp=37_611)
    assert len(tmps) == 1
    assert tmps[0].evidence_kind == "merged_split_tmp"
    assert tmps[0].length_aa == 1185
    assert tmps[0].est_tail_length_nm == round(1185 * 0.145, 1)
    assert tmps[0].merged_loci == ["D_TMP_N", "D_TMP_C"]

    # 负例 1: TAP 与单一完整 TMP 重叠不得合并 (即便 TAP 被误打上某些域标签，只要 role=TAP 就拒绝)
    p_tap_large = p_tap.model_copy(update={"length_aa": 210, "end": 25290})
    assert find_and_merge_split_tmps([p_mtp, p_tap_large, p_tmp_n]) == []

    # 负例 2: 两段间相距超过 120 bp 或非 TMP 角色不合并
    p_far_c = p_tmp_c.model_copy(update={"start": 27050, "end": 29110})
    assert find_and_merge_split_tmps([p_mtp, p_tmp_n, p_far_c]) == []
    p_other_c = p_tmp_c.model_copy(update={"structural_role": "TAIL_FIBER_RBP"})
    assert find_and_merge_split_tmps([p_mtp, p_tmp_n, p_other_c]) == []



