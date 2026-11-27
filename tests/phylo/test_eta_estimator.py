# -*- coding: utf-8 -*-
"""
PhyloEtaEstimator 单元测试：验证各科研子阶段真实日志效率估算、ModelFinder 解析、滑窗响应与阶段重置。
"""
import pytest

from src.phylo.core.eta_estimator import PhyloEtaEstimator

pytestmark = pytest.mark.offline


def test_ref_download_and_orf_rate_eta():
    est = PhyloEtaEstimator(start_ts=100.0)
    est.on_stage("curate_derep", "running", 32, now=100.0)

    # 60/180 耗时 20s -> 3 株/秒，剩余 120 株 -> ETA 约 40s
    changed1, s1 = est.on_log("[RefCurator] 下载进度: 60/180 (累计就绪 660 株)", now=120.0)
    assert changed1 is True
    assert s1.substage_label == "参考基因组下载 (60/180)"
    assert s1.eta_seconds is not None and abs(s1.eta_seconds - 40.0) < 0.2
    assert "3.0 株/秒" in s1.rate_text

    # 120/180 耗时又 20s -> 速率稳定 3 株/秒，剩余 60 株 -> ETA 约 20s
    changed2, s2 = est.on_log("[RefCurator] 下载进度: 120/180 (累计就绪 720 株)", now=140.0)
    assert changed2 is True
    assert s2.eta_seconds is not None and abs(s2.eta_seconds - 20.0) < 0.2

    # 阶段切换必须清空上阶段子进度
    s_next = est.on_stage("marker_extract", "running", 54, now=145.0)
    assert s_next.substage_label == ""
    assert s_next.eta_seconds is None

    # TerL-ORF 进度解析（50/100 耗时 10s -> 5 株/秒 -> 剩余 10s）
    changed3, s3 = est.on_log("[TerL-ORF] ORF 预测进度: 50/100", now=155.0)
    assert changed3 is True
    assert s3.substage_label == "ORF 蛋白预测 (50/100)"
    assert s3.eta_seconds is not None and abs(s3.eta_seconds - 10.0) < 0.2


def test_iqtree_modelfinder_real_log_parsing_and_guard():
    est = PhyloEtaEstimator(start_ts=1000.0)
    est.on_stage("tree", "running", 86, now=1000.0)

    # 前置序列成分行不得触发任何子阶段误解析
    changed_comp, _ = est.on_log(" 462  T000462   85.84%    passed      7.52%", now=1001.0)
    assert changed_comp is False

    # ModelFinder 初始化行（测试 1232 个模型）
    changed_init, s_init = est.on_log(
        "ModelFinder will test up to 1232 protein models (sample size: 3087 epsilon: 0.100) ...",
        now=1002.0,
    )
    assert changed_init is True
    assert s_init.substage_label == "ModelFinder 模型筛选 (0/1232)"
    assert s_init.eta_seconds is None

    # 前 2 个 1 秒极快模型不应过早输出低估 ETA
    _, s_m1 = est.on_log("  1  LG            368326.127   917 738486.254   739262.470   744020.308", now=1003.0)
    assert s_m1.substage_label == "ModelFinder 模型筛选 (1/1232)"
    assert s_m1.eta_seconds is None

    changed_m2, s_m2 = est.on_log("  2  LG+I          368300.000   918 738450.000   739230.000   744000.000", now=1004.0)
    assert changed_m2 is True
    assert s_m2.substage_label == "ModelFinder 模型筛选 (2/1232)"
    assert s_m2.eta_seconds is None

    # 到第 7 个模型（包含 LG+R4 等慢模型）累计耗时 116 秒，使用 0.3 滑窗 + 0.7 全局均速加权
    changed_m7, s_m7 = est.on_log(
        "  7  LG+R4         364808.694   923 731463.388   737033.652",
        now=1118.0,
    )
    assert changed_m7 is True
    assert s_m7.substage_label == "ModelFinder 模型筛选 (7/1232)"
    assert s_m7.eta_seconds is not None and s_m7.eta_seconds > 1000.0
    avg_rate = 7.0 / (1118.0 - 1002.0)
    win_rate = (7.0 - 1.0) / (1118.0 - 1003.0)
    assert s_m7.rate_per_sec == pytest.approx(0.3 * win_rate + 0.7 * avg_rate, rel=1e-3)
    assert s_m7.confidence == "medium"
    assert "模型/分" in s_m7.rate_text

    # 最后一条完成(done == total) 绝不输出虚假 0s，改为返回 None 等待后续阶段
    _, s_mf_end = est.on_log(
        "1232  Q.pfam+R10   364000.000   925 730000.000   735000.000",
        now=2000.0,
    )
    assert s_mf_end.substage_label == "ModelFinder 模型筛选 (1232/1232)"
    assert s_mf_end.eta_seconds is None

    # ModelFinder 结束选出最佳模型后，退出模型筛选子阶段
    changed_best, s_best = est.on_log("[IQ-TREE] 最佳替换模型: Q.pfam+I+R5 (BIC=731000.1)", now=2001.0)
    assert changed_best is True
    assert s_best.substage_label == ""


def test_sliding_window_adapts_to_speedup_and_slowdown():
    est = PhyloEtaEstimator(start_ts=0.0)
    est.on_stage("tree", "running", 80, now=0.0)

    # 先慢后快（0->10 用了 10s = 1/s；10->50 用了 4s = 10/s）
    est.on_log("已完成 10/100 次", now=10.0)
    _, s_fast = est.on_log("已完成 50/100 次", now=14.0)
    # 混合速率 = 0.6 * 10 + 0.4 * (50/14) = 7.428/s -> 剩余 50 次约 6.7s（远低于纯平均的 14s）
    assert s_fast.rate_per_sec == pytest.approx(0.6 * 10.0 + 0.4 * (50.0 / 14.0), rel=1e-3)
    assert s_fast.eta_seconds is not None and s_fast.eta_seconds < 8.0


def test_heavy_stage_never_uses_cross_stage_linear_extrapolation():
    est = PhyloEtaEstimator(start_ts=0.0)
    s_cached = est.on_stage("ani_screen", "cached", 20, now=1.0)
    assert s_cached.eta_seconds is None

    est.on_stage("curate_derep", "completed", 40, now=35.0)
    est.on_stage("marker_extract", "completed", 62, now=55.0)
    est.on_stage("msa", "completed", 75, now=70.0)
    est.on_stage("trim", "completed", 82, now=71.0)

    # 进入重型 IQ-TREE 阶段尚无 ModelFinder 子计数时，严禁用前面轻步骤进度外推出虚假 ~16s
    s_tree = est.on_stage("tree", "running", 86, now=71.2)
    assert s_tree.eta_seconds is None
    assert s_tree.substage_label == ""


def test_active_job_handle_returns_live_eta_snapshot(tmp_path):
    import threading
    import time
    from src.phylo.models.schemas import PhyloJobConfig, PhyloJobRecord
    from src.phylo.pipeline.executor import PhyloJobExecutor, _ActiveJobHandle
    from src.phylo.storage.archive_store import PhyloArchiveStore

    store = PhyloArchiveStore(base_dir=tmp_path)
    executor = PhyloJobExecutor(store=store)
    job_id = "phylo_live_eta_test"
    rec = PhyloJobRecord(
        job_id=job_id,
        title="Live ETA Test",
        status="running",
        resolved_track="phage_taxonomy",
        config=PhyloJobConfig(),
        created_at=time.time() - 35.0,
        started_at=time.time() - 30.0,
        job_dir=str(tmp_path / job_id),
        eta_seconds=None,
    )
    store.save_job(rec)

    live_rec = rec.model_copy(deep=True)
    live_rec.eta_seconds = 1234.5
    live_rec.substage_label = "ModelFinder 模型筛选 (6/100)"
    live_rec.rate_text = "3.2 模型/分"

    handle = _ActiveJobHandle(job_id=job_id, cancel_event=threading.Event())
    handle.live_record = live_rec

    with executor._jobs_lock:
        executor._active_jobs[job_id] = handle
    try:
        active = executor.get_active_jobs()
        matched = [j for j in active if j.job_id == job_id]
        assert len(matched) == 1
        assert matched[0].eta_seconds == 1234.5
        assert matched[0].substage_label == "ModelFinder 模型筛选 (6/100)"
        assert matched[0].rate_text == "3.2 模型/分"
        assert matched[0].elapsed_sec >= 29.0
    finally:
        with executor._jobs_lock:
            executor._active_jobs.pop(job_id, None)
