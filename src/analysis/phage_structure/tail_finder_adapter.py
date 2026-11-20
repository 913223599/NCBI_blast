# -*- coding: utf-8 -*-
"""
PhageTailFinder 双状态隐马尔可夫尾部模块适配器 (TailFinderAdapter)

完整加载 third_party/PhageTailFinder 开源参数（start_prob, transition_prob,
emission_prob, pfam_DICT），利用本地构建的 database/phage_tail_finder/ptf_pfams.h3m
通过 WSL PyHMMER 并行提取 Pfam 结构域观测序列，并在对数概率空间执行双状态 Viterbi 解码与
前向-后向后验概率推断，以识别经典及远缘/未知尾部基因簇。
"""
from __future__ import annotations

import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...assembly.env.wsl_manager import WSLManager
from ...workbench.models.tool_config import ToolConfig
from .types import StructureProteinItem, TailFinderCluster

logger = logging.getLogger("analysis.phage_structure.tail_finder")

_LOG_ZERO = -1e18
_SMOOTH_EPS = 1e-7


@dataclass
class PhageTailFinderParams:
    """PhageTailFinder 官方双状态 HMM 对数空间参数。"""

    start_log: Tuple[float, float]
    trans_log: Tuple[Tuple[float, float], Tuple[float, float]]
    emission_by_pfam: Dict[str, Tuple[float, float]]
    miss_log_fast: Tuple[float, float]
    miss_log_accurate: Tuple[float, float]
    tail_dominant_pfams: frozenset[str]


_CACHED_PARAMS: Optional[PhageTailFinderParams] = None


def resolve_ptf_model_dir() -> Path:
    return ToolConfig.PROJECT_ROOT / "third_party" / "PhageTailFinder" / "hmmmodel"


def resolve_ptf_hmm_path() -> Optional[Path]:
    ptf_dir = ToolConfig.get_db_dir("phage_tail_finder")
    cand = ptf_dir / "ptf_pfams.h3m"
    if cand.is_file() and cand.stat().st_size > 50_000_000:
        return cand
    return None


def _wsl_virsorter_pfam_exists() -> bool:
    if not WSLManager.is_available():
        return False
    distro = WSLManager.get_best_distro()
    try:
        res = subprocess.run(
            ["wsl", "-d", distro, "bash", "-lc", "ls /opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm >/dev/null 2>&1"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=8,
        )
        return res.returncode == 0
    except Exception:
        return False


def is_phagetailfinder_ready() -> bool:
    """判断 PhageTailFinder 模型参数与 Pfam HMM 索引是否就绪（含自动可重建源检查）。"""
    mdir = resolve_ptf_model_dir()
    required = ("start_prob", "transition_prob", "emission_prob", "pfam_DICT")
    if not all((mdir / fn).is_file() for fn in required):
        return False
    if resolve_ptf_hmm_path() is not None:
        return True
    return WSLManager.is_available() and _wsl_virsorter_pfam_exists()


def ensure_ptf_hmm_db(on_progress: Optional[Callable[[str], None]] = None) -> Path:
    existing = resolve_ptf_hmm_path()
    if existing is not None:
        return existing

    if on_progress:
        on_progress("正在从本地 Pfam-A 库初始化 PhageTailFinder 3,668 家族 HMM 索引...")

    ptf_dir = ToolConfig.get_db_dir("phage_tail_finder")
    ptf_dir.mkdir(parents=True, exist_ok=True)
    target_path = ptf_dir / "ptf_pfams.h3m"
    pfam_dict_path = resolve_ptf_model_dir() / "pfam_DICT"

    WSLManager.ensure_project_link()
    wsl_dict = WSLManager.to_wsl_path(str(pfam_dict_path))
    wsl_out = WSLManager.to_wsl_path(str(target_path))
    wsl_tmp = f"{wsl_out}.tmp"

    py_script = (
        "import glob, os, shutil, pyhmmer\n"
        f"need = set(l.split('\\t')[0].strip() for l in open('{wsl_dict}', encoding='utf-8') if l.strip())\n"
        "sources = sorted(glob.glob('/opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm'))\n"
        "if not sources:\n"
        "  raise FileNotFoundError('未在 WSL 找到 /opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm')\n"
        "seen = set()\n"
        f"with open('{wsl_tmp}', 'wb') as dst:\n"
        "  for hp in sources:\n"
        "    with pyhmmer.plan7.HMMFile(hp) as hf:\n"
        "      for h in hf:\n"
        "        acc = (h.accession.decode() if isinstance(h.accession, bytes) else str(h.accession or '')).split('.')[0]\n"
        "        if acc in need and acc not in seen:\n"
        "          seen.add(acc)\n"
        "          h.write(dst, binary=True)\n"
        f"shutil.move('{wsl_tmp}', '{wsl_out}')\n"
    )
    distro = WSLManager.get_best_distro()
    subprocess.run(
        ["wsl", "-d", distro, "bash", "-lc", f"python3 - << 'PY'\n{py_script}PY"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=300,
    )
    return target_path


def load_ptf_params() -> PhageTailFinderParams:
    """加载并将 PhageTailFinder 模型参数转入安全的对数概率空间。"""
    global _CACHED_PARAMS
    if _CACHED_PARAMS is not None:
        return _CACHED_PARAMS

    mdir = resolve_ptf_model_dir()
    sp_vals = [float(x) for x in (mdir / "start_prob").read_text(encoding="utf-8").strip().split()]
    start_log = (math.log(max(sp_vals[0], _SMOOTH_EPS)), math.log(max(sp_vals[1], _SMOOTH_EPS)))

    tr_lines = [ln.strip().split() for ln in (mdir / "transition_prob").read_text(encoding="utf-8").splitlines() if ln.strip()]
    t00, t01 = float(tr_lines[0][0]), float(tr_lines[0][1])
    t10, t11 = float(tr_lines[1][0]), float(tr_lines[1][1])
    trans_log = (
        (math.log(max(t00, _SMOOTH_EPS)), math.log(max(t01, _SMOOTH_EPS))),
        (math.log(max(t10, _SMOOTH_EPS)), math.log(max(t11, _SMOOTH_EPS))),
    )

    # 原 emission_prob 中 0..839 行记录 P(pfam|Tail)，840..4255 行记录 P(pfam|NonTail)，其中 588 个家族两处兼有；
    # 在同一 Pfam 键下合并其双向真实条件似然，彻底修复单索引覆写导致的零概率锁死。
    raw_pair: Dict[str, List[float]] = {}
    tail_dom: set[str] = set()
    for line in (mdir / "emission_prob").read_text(encoding="utf-8").splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 3:
            continue
        pf = parts[0].strip()
        p_tail = float(parts[1])
        p_nontail = float(parts[2])
        cur = raw_pair.setdefault(pf, [0.0, 0.0])
        cur[0] = max(cur[0], p_tail)
        cur[1] = max(cur[1], p_nontail)
        if p_tail > p_nontail:
            tail_dom.add(pf)

    emission_by_pfam: Dict[str, Tuple[float, float]] = {
        pf: (math.log(max(v[0], _SMOOTH_EPS)), math.log(max(v[1], _SMOOTH_EPS)))
        for pf, v in raw_pair.items()
    }

    _CACHED_PARAMS = PhageTailFinderParams(
        start_log=start_log,
        trans_log=trans_log,
        emission_by_pfam=emission_by_pfam,
        miss_log_fast=(0.0, 0.0),
        miss_log_accurate=(math.log(0.25), math.log(0.75)),
        tail_dominant_pfams=frozenset(tail_dom),
    )
    return _CACHED_PARAMS


def _logsumexp2(a: float, b: float) -> float:
    m = a if a >= b else b
    if m <= _LOG_ZERO / 2:
        return _LOG_ZERO
    return m + math.log1p(math.exp(-abs(a - b)))


def decode_tail_sequence(
    pfam_obs: Sequence[Optional[str]],
    params: Optional[PhageTailFinderParams] = None,
    *,
    accurate_mode: bool = False,
) -> Tuple[List[int], List[float]]:
    """
    在连续 ORF 序列上运行对数域双状态 Viterbi 与 Forward-Backward 后验推断。
    状态 0 = Tail, 状态 1 = Non-Tail。
    返回: (viterbi_is_tail[0/1] 列表, posterior_tail_prob[0..1] 列表)
    """
    n = len(pfam_obs)
    if n == 0:
        return [], []

    p = params or load_ptf_params()
    miss_e = p.miss_log_accurate if accurate_mode else p.miss_log_fast
    emit: List[Tuple[float, float]] = [
        p.emission_by_pfam.get(acc, miss_e) if acc else miss_e
        for acc in pfam_obs
    ]

    # 1. 对数 Viterbi 精确最可能路径（无任何长链浮点下溢风险）
    dp = [[0.0, 0.0] for _ in range(n)]
    back = [[0, 0] for _ in range(n)]
    dp[0][0] = p.start_log[0] + emit[0][0]
    dp[0][1] = p.start_log[1] + emit[0][1]

    for t in range(1, n):
        for s in (0, 1):
            c0 = dp[t - 1][0] + p.trans_log[0][s]
            c1 = dp[t - 1][1] + p.trans_log[1][s]
            if c0 >= c1:
                dp[t][s] = c0 + emit[t][s]
                back[t][s] = 0
            else:
                dp[t][s] = c1 + emit[t][s]
                back[t][s] = 1

    states = [0] * n
    states[n - 1] = 0 if dp[n - 1][0] >= dp[n - 1][1] else 1
    for t in range(n - 1, 0, -1):
        states[t - 1] = back[t][states[t]]

    # 2. Forward-Backward 计算每个 ORF 属于尾部状态的后验概率 P(S_t = Tail | obs)
    alpha = [[0.0, 0.0] for _ in range(n)]
    alpha[0][0] = p.start_log[0] + emit[0][0]
    alpha[0][1] = p.start_log[1] + emit[0][1]
    for t in range(1, n):
        for s in (0, 1):
            alpha[t][s] = _logsumexp2(alpha[t - 1][0] + p.trans_log[0][s], alpha[t - 1][1] + p.trans_log[1][s]) + emit[t][s]

    beta = [[0.0, 0.0] for _ in range(n)]
    for t in range(n - 2, -1, -1):
        for s in (0, 1):
            beta[t][s] = _logsumexp2(
                p.trans_log[s][0] + emit[t + 1][0] + beta[t + 1][0],
                p.trans_log[s][1] + emit[t + 1][1] + beta[t + 1][1],
            )

    probs: List[float] = []
    for t in range(n):
        l0 = alpha[t][0] + beta[t][0]
        l1 = alpha[t][1] + beta[t][1]
        denom = _logsumexp2(l0, l1)
        probs.append(round(max(0.0, min(1.0, math.exp(l0 - denom))), 4))

    is_tail_flags = [1 if st == 0 else 0 for st in states]
    return is_tail_flags, probs


def _cluster_tail_orfs(
    ordered_proteins: Sequence[StructureProteinItem],
    tail_flags: Sequence[int],
    tail_probs: Sequence[float],
    *,
    max_gap_orfs: int = 2,
) -> List[TailFinderCluster]:
    """根据共线性坐标将预测为 Tail (state=1) 的相邻 ORF 聚合成连续尾部模块簇。"""
    tail_indices = [idx for idx, flag in enumerate(tail_flags) if flag == 1]
    if not tail_indices:
        return []

    groups: List[List[int]] = [[tail_indices[0]]]
    for idx in tail_indices[1:]:
        if idx - groups[-1][-1] <= max_gap_orfs + 1:
            groups[-1].append(idx)
        else:
            groups.append([idx])

    clusters: List[TailFinderCluster] = []
    for cid_idx, grp in enumerate(groups, start=1):
        sub_prots = [ordered_proteins[i] for i in grp]
        sub_probs = [tail_probs[i] for i in grp]
        novel_loci = [
            p.locus_tag
            for p in sub_prots
            if p.structural_role == "OTHER" or p.structural_role == "TAIL_OTHER"
        ]
        pfam_hits = sorted({p.ptf_pfam for p in sub_prots if p.ptf_pfam})
        mean_p = round(sum(sub_probs) / max(1, len(sub_probs)), 4)
        # 过滤仅含 1 个弱未知 ORF 的孤立抖动假点
        if len(sub_prots) == 1 and mean_p < 0.72:
            continue
        clusters.append(
            TailFinderCluster(
                cluster_id=f"PTF_Cluster_{cid_idx}",
                start_bp=min(p.start for p in sub_prots),
                end_bp=max(p.end for p in sub_prots),
                orf_count=len(sub_prots),
                novel_orf_count=len(novel_loci),
                mean_tail_prob=mean_p,
                loci=[p.locus_tag for p in sub_prots],
                pfam_hits=pfam_hits,
            )
        )
    return clusters


def run_phagetailfinder_on_contigs(
    contig_map: Dict[str, Dict[str, Any]],
    *,
    evalue_cutoff: float = 1e-3,
    workers: int = 12,
    accurate_mode: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Tuple[int, List[TailFinderCluster]]]:
    """
    批量调度 WSL PyHMMER 扫描 Pfam HMM 并在每个 Contig 上执行 PhageTailFinder HMM 解码。
    返回: {contig_id: (预测尾蛋白总数, 尾部基因簇列表)}
    """
    if not is_phagetailfinder_ready():
        logger.info("PhageTailFinder HMM 环境未就绪，已跳过双状态 HMM 扫描")
        return {}

    hmm_path = ensure_ptf_hmm_db(on_progress=on_progress)
    params = load_ptf_params()
    WSLManager.ensure_project_link()
    wsl_hmm = WSLManager.to_wsl_path(str(hmm_path))

    query_items: List[Tuple[str, StructureProteinItem]] = []
    for cid, info in contig_map.items():
        for p in info["proteins"]:
            if p.translation and len(p.translation) >= 25:
                query_items.append((f"{cid}||{p.locus_tag}", p))

    if not query_items:
        return {}

    if on_progress:
        on_progress(f"正在运行 PhageTailFinder Pfam HMM 扫描 ({len(query_items)} ORF, {workers} 核)...")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".faa", newline="\n", delete=False) as tf:
        for qid, p in query_items:
            tf.write(f">{qid}\n{p.translation}\n")
        win_faa = Path(tf.name)

    pfam_hits: Dict[str, Tuple[str, str, float]] = {}
    try:
        wsl_faa = WSLManager.to_wsl_path(str(win_faa))
        py_code = (
            "import pyhmmer\n"
            f"with pyhmmer.easel.SequenceFile('{wsl_faa}', digital=True) as sf: seqs = sf.read_block()\n"
            f"with pyhmmer.plan7.HMMFile('{wsl_hmm}') as hf:\n"
            "  best = {}\n"
            f"  for top in pyhmmer.hmmsearch(hf, seqs, cpus={max(1, workers)}, E={evalue_cutoff}):\n"
            "    acc = (top.query.accession.decode() if isinstance(top.query.accession, bytes) else str(top.query.accession or '')).split('.')[0]\n"
            "    qname = top.query.name.decode() if isinstance(top.query.name, bytes) else str(top.query.name or '')\n"
            "    for h in top:\n"
            "      if h.included:\n"
            "        t = h.name.decode() if isinstance(h.name, bytes) else str(h.name)\n"
            "        prev = best.get(t)\n"
            "        if prev is None or h.score > prev[2]:\n"
            "          best[t] = (acc, qname, h.score)\n"
            "for tid, (acc, qnm, sc) in best.items():\n"
            "  print(f'{tid}\\t{acc}\\t{qnm}\\t{sc:.3f}')\n"
        )
        distro = WSLManager.get_best_distro()
        res = subprocess.run(
            ["wsl", "-d", distro, "bash", "-lc", f"python3 - << 'PY'\n{py_code}PY"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=600,
        )
        for line in res.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 4:
                pfam_hits[parts[0]] = (parts[1], parts[2], float(parts[3]))
    finally:
        win_faa.unlink(missing_ok=True)

    summary_by_contig: Dict[str, Tuple[int, List[TailFinderCluster]]] = {}
    for cid, info in contig_map.items():
        ordered: List[StructureProteinItem] = sorted(info["proteins"], key=lambda x: x.start)
        obs_seq: List[Optional[str]] = []
        for p in ordered:
            hit = pfam_hits.get(f"{cid}||{p.locus_tag}")
            if hit:
                acc, qname, _sc = hit
                p.ptf_pfam = acc
                p.ptf_pfam_desc = qname
                obs_seq.append(acc)
            else:
                obs_seq.append(None)

        flags, probs = decode_tail_sequence(obs_seq, params, accurate_mode=accurate_mode)
        tail_cnt = 0
        for p, flg, prb in zip(ordered, flags, probs):
            p.ptf_tail_prob = prb
            p.ptf_is_tail = flg == 1 and (prb >= 0.55 or p.ptf_pfam in params.tail_dominant_pfams)
            if p.ptf_is_tail:
                tail_cnt += 1

        clusters = _cluster_tail_orfs(ordered, [1 if p.ptf_is_tail else 0 for p in ordered], probs)
        summary_by_contig[cid] = (tail_cnt, clusters)

    return summary_by_contig
