# -*- coding: utf-8 -*-
"""
R2 升级先导单元测试：
1. 本地 ProstT5_fp16 教师模型路径解析、高价值训练序列选样与分片 Checkpoint 断点续跑；
2. OrfFunctionalJudge (arch="r2") 双尺度序列编码器（保短基序 + 远程自注意力）与特征对齐蒸馏投影头。
"""
from __future__ import annotations

import gzip
import pickle
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import torch

from src.phage_discovery.student.orf_functional_judge import (
    NUM_JUDGE_CLASSES,
    ORF_JUDGE_STAT_DIM,
    build_orf_functional_judge,
)
from src.phage_discovery.teachers.prostt5_embed_teacher import (
    PROSTT5_EMBED_DIM,
    resolve_local_prostt5_dirs,
    run_chunked_prostt5_embedding,
    select_priority_training_aas,
)


def test_resolve_local_prostt5_and_priority_selection(tmp_path: Path) -> None:
    # 验证相对路径解析本地 ProstT5 配置与权重快照
    snap_a = tmp_path / "models--Rostlab--ProstT5_fp16" / "snapshots" / "aaa"
    snap_b = tmp_path / "models--Rostlab--ProstT5_fp16" / "snapshots" / "bbb"
    snap_a.mkdir(parents=True)
    snap_b.mkdir(parents=True)
    (snap_a / "config.json").write_text("{}", encoding="utf-8")
    (snap_b / "model.safetensors").write_text("x", encoding="utf-8")

    cfg_dir, sf_path = resolve_local_prostt5_dirs(phold_db_dir=tmp_path)
    assert cfg_dir == snap_a.resolve()
    assert sf_path == (snap_b / "model.safetensors").resolve()

    # 验证优先选样：P9 宿主对抗与稀有类必须优先入选，再按频次选高频常见类
    candidates = [
        ("aa_common", 100, True, False, False),
        ("aa_bg", 80, False, False, False),
        ("aa_p9", 1, False, True, True),
        ("aa_rare", 1, True, False, True),
    ]
    picked = select_priority_training_aas(candidates, max_count=3)
    assert picked[0] == "aa_p9" or "aa_p9" in picked
    assert "aa_rare" in picked
    assert "aa_common" in picked
    assert len(picked) == 3


def test_chunked_prostt5_checkpoint_resume(tmp_path: Path) -> None:
    cache_path = tmp_path / "prostt5_cache.pkl.gz"
    items = [(f"k{i}", "MKALDLFAGTGWGVACKALGIEEEGVELMPEAVAT") for i in range(5)]
    calls: List[int] = []

    def _fake_runner(sub: List[Tuple[str, str]], **kwargs: Any) -> Dict[str, np.ndarray]:
        calls.append(len(sub))
        return {k: np.full((PROSTT5_EMBED_DIM,), 0.25, dtype=np.float16) for k, _ in sub}

    # 先写入第 1 块完成状态
    init_state = {
        "done_chunks": 1,
        "chunk_size": 3,
        "total_items": 5,
        "embs": {f"k{i}": np.ones((PROSTT5_EMBED_DIM,), dtype=np.float16) for i in range(3)},
    }
    with gzip.open(cache_path, "wb") as fh:
        pickle.dump(init_state, fh)

    res = run_chunked_prostt5_embedding(
        items,
        cache_path,
        chunk_size=3,
        batch_runner=_fake_runner,
    )
    # 应当只补跑剩余的第 2 块（2 条）
    assert calls == [2]
    assert len(res["embs"]) == 5
    assert res["embs"]["k4"].dtype == np.float16
    assert res["embs"]["k4"].shape == (PROSTT5_EMBED_DIM,)


def test_r2_judge_dual_scale_and_distill_projection() -> None:
    torch.manual_seed(31)
    stat_mean = np.zeros(ORF_JUDGE_STAT_DIM, dtype=np.float32)
    stat_std = np.ones(ORF_JUDGE_STAT_DIM, dtype=np.float32)

    model = build_orf_functional_judge(
        stat_mean=stat_mean,
        stat_std=stat_std,
        use_aa_seq=True,
        arch="r2",
        aa_mask_prob=0.10,
        distill_dim=PROSTT5_EMBED_DIM,
    )
    model.eval()
    aa_ids = torch.zeros((2, 6, 64), dtype=torch.long)
    aa_ids[:, :3, :18] = 5
    aa_lens = torch.ones((2, 6), dtype=torch.long) * 18
    stat_feats = torch.randn((2, 6, ORF_JUDGE_STAT_DIM), dtype=torch.float32)
    stat_feats[:, :3, 99] = 1.0
    valid_counts = torch.tensor([3, 3], dtype=torch.long)

    # 污染无效 padding 槽位，确保 R2 双尺度与蒸馏投影也严守 Padding 不变性
    stat_feats[1, :3, :] = stat_feats[0, :3, :]
    aa_ids[1, :3, :] = aa_ids[0, :3, :]
    stat_feats[1, 3:, :] += 99.0
    aa_ids[1, 3:, :] = 17

    with torch.no_grad():
        f_log, p_log = model(aa_ids, aa_lens, stat_feats, valid_counts)
        f_log2, p_log2, d_pred = model(aa_ids, aa_lens, stat_feats, valid_counts, return_seq_distill=True)

    assert f_log.shape == (2, 6, NUM_JUDGE_CLASSES)
    assert p_log.shape == (2, 6)
    assert d_pred.shape == (2, 6, PROSTT5_EMBED_DIM)
    assert torch.allclose(f_log[0, :3], f_log[1, :3], atol=1e-5)
    assert torch.allclose(p_log[0, :3], p_log[1, :3], atol=1e-5)
    assert torch.allclose(d_pred[0, :3], d_pred[1, :3], atol=1e-5)
    assert torch.allclose(f_log, f_log2, atol=1e-6)

    # 校验 train 模式梯度全通
    model.train()
    f_tr, p_tr, d_tr = model(aa_ids, aa_lens, stat_feats, valid_counts, return_seq_distill=True)
    loss = f_tr.square().mean() + p_tr.square().mean() + d_tr.square().mean()
    loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters() if p.requires_grad)

