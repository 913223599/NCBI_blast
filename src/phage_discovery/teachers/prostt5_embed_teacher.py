# -*- coding: utf-8 -*-
"""
WSL2 GPU 本地 ProstT5_fp16 Encoder 三维折叠+进化同源表征离线提取教师模块：
1. 严格从相对路径 database/phold_db 加载本地离线 ProstT5_fp16（禁止联网），并显式绑定 shared.weight 与 encoder.embed_tokens.weight；
2. 采用按长度排序 + 动态残基槽位控批（max_tokens=8192）在 8GB 显卡下稳定维持 ~3.7 GB 显存峰值与 ~40 prot/s 提取速率；
3. 支持高价值序列优先筛选与 5,000 条/片原子级分片 Checkpoint 断点续提，结果以 float16(1024D) 紧凑存储。
"""
from __future__ import annotations

import gzip
import logging
import os
import pickle
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .checkv_teacher import to_wsl_path
from .hmm_adversarial_teacher import _atomic_save_pickle_gz
from .phold_teacher import default_phold_db_dir

logger = logging.getLogger("phage_discovery.teachers.prostt5_embed_teacher")

PROSTT5_EMBED_DIM: int = 1024


def resolve_local_prostt5_dirs(phold_db_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """解析本地离线 ProstT5_fp16 的配置文件目录（含 config.json/spiece.model）与 model.safetensors 路径。"""
    base = Path(phold_db_dir).resolve() if phold_db_dir is not None else default_phold_db_dir().resolve()
    snap_root = base / "models--Rostlab--ProstT5_fp16" / "snapshots"
    if not snap_root.is_dir():
        raise FileNotFoundError(f"本地 ProstT5_fp16 快照目录不存在: {snap_root}")

    cfg_files = sorted(snap_root.glob("*/config.json"))
    sf_files = sorted(snap_root.glob("*/model.safetensors"))
    if not cfg_files:
        raise FileNotFoundError(f"未找到 ProstT5 config.json: {snap_root}")
    if not sf_files:
        raise FileNotFoundError(f"未找到 ProstT5 model.safetensors: {snap_root}")
    return cfg_files[0].parent.resolve(), sf_files[0].resolve()


def select_priority_training_aas(
    candidates: Sequence[Tuple[str, int, bool, bool, bool]],
    *,
    max_count: int = 40000,
) -> List[str]:
    """
    从训练集唯一蛋白候选中按知识密度优先挑选最多 max_count 条进行结构表征提取。
    candidates 每项格式: (aa_seq, train_freq, is_p08_pos, is_p9_pos, is_rare_tier)
      - 优先级 1：is_rare_tier / is_p9_pos（细菌防御岛与转座子/裂解等稀缺类全部优先入选）；
      - 优先级 2：is_p08_pos（其他病毒功能模块）；
      - 优先级 3：高频细菌已知背景蛋白（按 train_freq 降序）。
    """
    if max_count <= 0 or not candidates:
        return []
    ranked = sorted(
        candidates,
        key=lambda item: (
            1 if (item[3] or item[4]) else 0,
            1 if item[2] else 0,
            int(item[1]),
        ),
        reverse=True,
    )
    return [item[0] for item in ranked[: int(max_count)]]


def run_prostt5_wsl_batch(
    aa_items: Sequence[Tuple[str, str]],
    *,
    phold_db_dir: Optional[Path] = None,
    max_aa_len: int = 384,
    max_tokens: int = 8192,
    timeout_sec: int = 3600,
) -> Dict[str, np.ndarray]:
    """
    调用 WSL2 Ubuntu (/usr/bin/python3) 在 GPU 上对一批 (aa_key, aa_seq) 提取 ProstT5 Encoder 1024D 表征。
    返回 {aa_key: float16 ndarray (1024,)}。
    """
    valid_items: List[Tuple[str, str]] = []
    for k, aa in aa_items:
        cleaned = (aa or "").strip().upper().rstrip("*")
        if cleaned and "*" not in cleaned:
            valid_items.append((str(k), cleaned[: int(max_aa_len)]))
    if not valid_items:
        return {}

    cfg_dir, sf_path = resolve_local_prostt5_dirs(phold_db_dir=phold_db_dir)
    wsl_cfg = to_wsl_path(cfg_dir)
    wsl_sf = to_wsl_path(sf_path)

    # 借助磁盘临时 npz 与脚本目录传入 WSL，避免内存字符串或命令行限制
    stage_win = Path(".").resolve() / ".tmp_prostt5_stage"
    stage_win.mkdir(parents=True, exist_ok=True)
    in_pkl = stage_win / f"in_{os.getpid()}.pkl"
    out_npz = stage_win / f"out_{os.getpid()}.npz"
    worker_py = stage_win / f"worker_{os.getpid()}.py"

    with open(in_pkl, "wb") as fh:
        pickle.dump(valid_items, fh, protocol=pickle.HIGHEST_PROTOCOL)

    wsl_in = to_wsl_path(in_pkl)
    wsl_out = to_wsl_path(out_npz)
    wsl_worker = to_wsl_path(worker_py)

    script_src = f"""# -*- coding: utf-8 -*-
import pickle
import re
import numpy as np
import torch
from safetensors.torch import load_file as load_safetensors
from transformers import T5Config, T5EncoderModel, T5Tokenizer

with open({wsl_in!r}, "rb") as fh:
    items = pickle.load(fh)

# 按序列长度降序排列配合动态 token 批大小最大化算力密度
items.sort(key=lambda x: len(x[1]), reverse=True)

tok = T5Tokenizer.from_pretrained({wsl_cfg!r}, do_lower_case=False, legacy=True)
cfg = T5Config.from_pretrained({wsl_cfg!r})
sd = load_safetensors({wsl_sf!r}, device="cpu")
enc_sd = {{k: v for k, v in sd.items() if k.startswith("encoder.") or k == "shared.weight"}}
if "encoder.embed_tokens.weight" not in enc_sd and "shared.weight" in enc_sd:
    enc_sd["encoder.embed_tokens.weight"] = enc_sd["shared.weight"]
enc = T5EncoderModel(cfg)
enc.load_state_dict(enc_sd, strict=True)
del sd, enc_sd
enc = enc.to(dtype=torch.float16, device="cuda").eval()

keys_out = []
embs_out = []
max_tokens = {int(max_tokens)}
idx = 0
with torch.inference_mode():
    while idx < len(items):
        cur_keys = []
        cur_texts = []
        max_l = 0
        while idx < len(items):
            k, raw_seq = items[idx]
            seq = re.sub(r"[UZOB]", "X", raw_seq)
            cand_l = max(max_l, len(seq) + 2)
            if cur_texts and cand_l * (len(cur_texts) + 1) > max_tokens:
                break
            cur_keys.append(k)
            cur_texts.append("<AA2fold> " + " ".join(list(seq)))
            max_l = cand_l
            idx += 1

        inp = tok(cur_texts, add_special_tokens=True, padding="longest", return_tensors="pt").to("cuda")
        out = enc(inp["input_ids"], attention_mask=inp["attention_mask"]).last_hidden_state
        m = inp["attention_mask"].clone()
        m[:, 0] = 0
        last_idx = inp["attention_mask"].sum(dim=1) - 1
        m[torch.arange(len(cur_texts), device=m.device), last_idx] = 0
        m_f = m.unsqueeze(-1).to(out.dtype)
        pooled = (out * m_f).sum(dim=1) / m_f.sum(dim=1).clamp(min=1.0)
        keys_out.extend(cur_keys)
        embs_out.append(pooled.to(torch.float16).cpu().numpy())

mat = np.concatenate(embs_out, axis=0) if embs_out else np.zeros((0, 1024), dtype=np.float16)
np.savez(
    {wsl_out!r},
    keys=np.asarray(keys_out),
    embs=mat,
)
del enc
torch.cuda.empty_cache()
"""
    worker_py.write_text(script_src, encoding="utf-8")

    try:
        cmd = ["wsl", "-d", "Ubuntu", "-e", "bash", "-lc", f"python3 {shlex.quote(wsl_worker)}"]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"WSL ProstT5 提取失败 (exit={proc.returncode}):\n{proc.stderr[-1000:]}")

        with np.load(out_npz, allow_pickle=False) as data:
            keys_arr = data["keys"].copy()
            embs_arr = data["embs"].copy()
        return {str(keys_arr[i]): embs_arr[i].astype(np.float16) for i in range(len(keys_arr))}
    finally:
        for tmp_f in (in_pkl, out_npz, worker_py):
            if tmp_f.exists():
                tmp_f.unlink(missing_ok=True)
        if stage_win.exists() and not any(stage_win.iterdir()):
            stage_win.rmdir()


def run_chunked_prostt5_embedding(
    aa_items: Sequence[Tuple[str, str]],
    cache_path: Path,
    *,
    chunk_size: int = 5000,
    batch_runner: Optional[Callable[..., Dict[str, np.ndarray]]] = None,
    **runner_kwargs: Any,
) -> Dict[str, Any]:
    """
    对 aa_items 执行分片离线 ProstT5 表征提取并支持断点恢复。
    落盘结构: {"done_chunks": int, "chunk_size": int, "total_items": int, "embs": {aa_key: float16(1024,)}}。
    """
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    runner = batch_runner or run_prostt5_wsl_batch

    if cache_path.is_file():
        with gzip.open(cache_path, "rb") as fh:
            state = pickle.load(fh)
        done_chunks = int(state.get("done_chunks", 0))
        embs: Dict[str, np.ndarray] = dict(state.get("embs", {}))
    else:
        done_chunks = 0
        embs = {}

    total = len(aa_items)
    n_chunks = (total + chunk_size - 1) // chunk_size if total > 0 else 0
    if done_chunks >= n_chunks:
        return {"done_chunks": done_chunks, "chunk_size": chunk_size, "total_items": total, "embs": embs}

    t0 = time.perf_counter()
    for ci in range(done_chunks, n_chunks):
        st = ci * chunk_size
        ed = min(total, st + chunk_size)
        sub = aa_items[st:ed]
        t_c = time.perf_counter()
        chunk_res = runner(sub, **runner_kwargs)
        embs.update(chunk_res)
        done_chunks = ci + 1
        state = {
            "done_chunks": done_chunks,
            "chunk_size": chunk_size,
            "total_items": total,
            "embs": embs,
        }
        _atomic_save_pickle_gz(cache_path, state)
        logger.info(
            "ProstT5 离线提取分片 [%d/%d] 完成 (%d 条, 分片耗时 %.1fs, 累计耗时 %.1fs)",
            done_chunks,
            n_chunks,
            len(sub),
            time.perf_counter() - t_c,
            time.perf_counter() - t0,
        )

    return state

