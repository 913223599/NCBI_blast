# -*- coding: utf-8 -*-
"""
基于直接重复序列 (attL / attR Direct Repeat) 与整合酶/核心蛋白护栏的 1 bp 整合断点校准模块。

设计目标：
1. 纯离线毫秒级检索：对最终保留区段左右过渡区 (±flank_pad_bp) 构造 9-mer 种子索引，支持精确匹配与高置信单错配扩展；
2. 统计与结构双防线：
   - 计算 Shannon 熵与低复杂度串联重复过滤，剔除微卫星等简单随机重复碰撞；
   - 严禁切进或丢弃高置信噬菌体核心 CDS 内部；
   - 严禁跨越外部清晰宿主 CDS 向外盲扩，防止跨宿主基因随机碰撞；
   - 依据邻近高置信整合酶 (P4) 与两端基因间区位置自适应动态调整重复长度门槛；
3. 零损耗回退：无满足全部防线的高置信 attL/attR 配对时，原封不动保留双模态精细边界。
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.metrics import PredictedRegion


@dataclass
class AttAlignmentHit:
    """单个前噬菌体区段的 attL / attR 1 bp 精确对齐记录。"""

    contig_id: str
    old_start_bp: int
    old_end_bp: int
    new_start_bp: int
    new_end_bp: int
    dr_len_bp: int
    mismatches: int
    near_integrase: bool
    both_intergenic: bool
    dr_seq: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "att_aligned": True,
            "old_start_bp": self.old_start_bp,
            "old_end_bp": self.old_end_bp,
            "new_start_bp": self.new_start_bp,
            "new_end_bp": self.new_end_bp,
            "att_dr_len_bp": self.dr_len_bp,
            "att_mismatches": self.mismatches,
            "att_near_integrase": self.near_integrase,
            "att_both_intergenic": self.both_intergenic,
            "att_dr_seq": self.dr_seq,
        }


def _shannon_entropy(seq: str) -> float:
    if not seq:
        return 0.0
    n = float(len(seq))
    ent = 0.0
    for base in ("A", "C", "G", "T"):
        cnt = seq.count(base)
        if cnt > 0:
            p = cnt / n
            ent -= p * math.log2(p)
    return ent


_TRNA_TLOOP_FWD = re.compile(r"GTTC[AG]A[AT]C")
_TRNA_TLOOP_REV = re.compile(r"G[AT]T[CT]GAAC")


def _find_trna_3prime_anchors(seq: str, start: int, end: int) -> List[int]:
    """
    轻量局部双链 tRNA TpsiC-loop 保守基序检测（无外置数据库依赖）：
    定位正链 GTTC[AG]A[AT]C + CCA 尾与反链 G[AT]T[CT]GAAC + TGG 端附近的候选整合断点。
    """
    sub = seq[start:end]
    anchors: List[int] = []
    for m in _TRNA_TLOOP_FWD.finditer(sub):
        tail = sub[m.end() + 10 : min(len(sub), m.end() + 26)]
        cca = tail.find("CCA")
        anchors.append(start + m.end() + (10 + cca + 3 if cca >= 0 else 18))
    for m in _TRNA_TLOOP_REV.finditer(sub):
        head = sub[max(0, m.start() - 26) : max(0, m.start() - 10)]
        tgg = head.rfind("TGG")
        anchors.append(start + (max(0, m.start() - 26) + tgg if tgg >= 0 else max(0, m.start() - 18)))
    return anchors


def _search_trna_short_att_hit(
    cid: str,
    seq: str,
    reg: PredictedRegion,
    ls0: int,
    le0: int,
    rs0: int,
    re0: int,
    integrase_intervals: Sequence[Tuple[int, int]],
    violates_guards_fn: Any,
    integrase_prox_fn: Any,
    is_intergenic_fn: Any,
    *,
    anchor_radius_bp: int = 120,
    min_short_dr: int = 11,
    max_short_dr: int = 13,
) -> Optional[AttAlignmentHit]:
    """在整合酶贴邻的 tRNA 3' 锚点窄窗 (±120 bp) 内搜索 11..13 bp 精确短直接重复。"""
    if not integrase_intervals:
        return None
    near_l = any(abs(is0 - reg.start_bp) <= 1500 or abs(ie0 - reg.start_bp) <= 1500 for is0, ie0 in integrase_intervals)
    near_r = any(abs(is0 - reg.end_bp) <= 1500 or abs(ie0 - reg.end_bp) <= 1500 for is0, ie0 in integrase_intervals)
    if not (near_l or near_r):
        return None

    l_anchors = _find_trna_3prime_anchors(seq, ls0, le0)
    r_anchors = _find_trna_3prime_anchors(seq, rs0, re0)
    if not l_anchors and not r_anchors:
        return None

    l_wins = [(max(ls0, a - anchor_radius_bp), min(le0, a + anchor_radius_bp)) for a in l_anchors] if l_anchors else [(ls0, le0)]
    r_wins = [(max(rs0, a - anchor_radius_bp), min(re0, a + anchor_radius_bp)) for a in r_anchors] if r_anchors else [(rs0, re0)]

    for k_len in range(max_short_dr, min_short_dr - 1, -1):
        r_map: Dict[str, List[int]] = defaultdict(list)
        for ws, we in r_wins:
            for pos in range(ws, max(ws, we - k_len + 1)):
                sub = seq[pos : pos + k_len]
                if "N" not in sub:
                    r_map[sub].append(pos)
        best_sc = -1.0
        best_hit: Optional[AttAlignmentHit] = None
        for ws, we in l_wins:
            for lp in range(ws, max(ws, we - k_len + 1)):
                sub = seq[lp : lp + k_len]
                if sub not in r_map:
                    continue
                if _shannon_entropy(sub) < 1.55 or _has_simple_tandem_repeat(sub):
                    continue
                for rp in r_map[sub]:
                    cs, ce = lp, rp + k_len
                    if ce - cs < 3000 or violates_guards_fn(cs, ce):
                        continue
                    ig_b = integrase_prox_fn(cs, ce)
                    both_ig = is_intergenic_fn(cs) and is_intergenic_fn(ce)
                    sc_v = float(k_len) + 2.0 * ig_b + (1.0 if both_ig else 0.0) - (abs(cs - reg.start_bp) + abs(ce - reg.end_bp)) / 1200.0
                    if sc_v > best_sc:
                        best_sc = sc_v
                        best_hit = AttAlignmentHit(
                            contig_id=cid,
                            old_start_bp=reg.start_bp,
                            old_end_bp=reg.end_bp,
                            new_start_bp=cs,
                            new_end_bp=ce,
                            dr_len_bp=k_len,
                            mismatches=0,
                            near_integrase=ig_b > 0.1,
                            both_intergenic=both_ig,
                            dr_seq=sub,
                        )
        if best_hit is not None:
            return best_hit
    return None


def _has_simple_tandem_repeat(seq: str) -> bool:
    for unit in (1, 2, 3):
        if len(seq) >= unit * 4:
            sub = seq[:unit]
            if seq.count(sub) * unit >= len(seq) * 0.75:
                return True
    return False


def _extend_dr_match(
    seq: str,
    l_seed: int,
    r_seed: int,
    k_seed: int,
    ls0: int,
    le0: int,
    rs0: int,
    re0: int,
    *,
    allow_mm: int,
    max_dr_len: int,
) -> Tuple[int, int, int, int]:
    """从精确 k-mer 锚点向两侧扩展直接重复，支持 0 或 1 个内部错配。"""
    ll, rr = l_seed, r_seed
    mm = 0
    while ll > ls0 and rr > rs0 and (l_seed + k_seed - ll) < max_dr_len:
        ch_l, ch_r = seq[ll - 1], seq[rr - 1]
        if ch_l == ch_r and ch_l != "N":
            ll -= 1
            rr -= 1
        elif (
            mm < allow_mm
            and ch_l != "N"
            and ch_r != "N"
            and ll - 3 >= ls0
            and rr - 3 >= rs0
            and seq[ll - 2] == seq[rr - 2]
            and seq[ll - 3] == seq[rr - 3]
        ):
            mm += 1
            ll -= 1
            rr -= 1
        else:
            break

    lr, r_r = l_seed + k_seed, r_seed + k_seed
    while lr < le0 and r_r < re0 and (lr - ll) < max_dr_len:
        ch_l, ch_r = seq[lr], seq[r_r]
        if ch_l == ch_r and ch_l != "N":
            lr += 1
            r_r += 1
        elif (
            mm < allow_mm
            and ch_l != "N"
            and ch_r != "N"
            and lr + 2 < le0
            and r_r + 2 < re0
            and seq[lr + 1] == seq[r_r + 1]
            and seq[lr + 2] == seq[r_r + 2]
        ):
            mm += 1
            lr += 1
            r_r += 1
        else:
            break

    return ll, lr, rr, mm


def refine_regions_with_att_sites(
    regions: Sequence[PredictedRegion],
    contig_seqs: Mapping[str, str],
    orfs_by_contig: Mapping[str, Sequence[Tuple[int, int, int, str]]],
    scored_by_contig: Mapping[str, Mapping[str, np.ndarray]],
    *,
    flank_pad_bp: int = 2100,
    enable_trna_short_dr: bool = False,
    min_exact_len: int = 14,
    min_mm1_len: int = 18,
    max_dr_len: int = 55,
    k_seed: int = 9,
    details_out: Optional[Dict[str, AttAlignmentHit]] = None,
) -> Tuple[List[PredictedRegion], int]:
    """
    在最终区段左右边界附近搜索高质量直接重复 (attL / attR)，执行 1 bp 精密边界校准。
    未命中满足全套统计及宿主/核心防线的重复序列时保持原边界不变。
    """
    if not regions or not contig_seqs:
        return list(regions), 0

    out: List[PredictedRegion] = []
    aligned_cnt = 0

    for reg in regions:
        cid = reg.contig_id
        raw_seq = contig_seqs.get(cid)
        if not raw_seq:
            out.append(reg)
            continue
        seq = raw_seq.upper()
        seq_len = len(seq)
        orfs = orfs_by_contig.get(cid, ())
        sc = scored_by_contig.get(cid)

        ls0 = max(0, reg.start_bp - flank_pad_bp)
        le0 = min(seq_len, reg.start_bp + flank_pad_bp)
        rs0 = max(0, reg.end_bp - flank_pad_bp)
        re0 = min(seq_len, reg.end_bp + flank_pad_bp)
        if le0 <= ls0 + 20 or re0 <= rs0 + 20 or le0 >= rs0:
            out.append(reg)
            continue

        integrase_intervals: List[Tuple[int, int]] = []
        protected_core_intervals: List[Tuple[int, int]] = []
        phage_cds_intervals: List[Tuple[int, int]] = []
        clear_host_intervals: List[Tuple[int, int]] = []

        if orfs and sc is not None and len(sc.get("phage_probs", ())) == len(orfs):
            ph = sc["phage_probs"]
            f10 = sc["func10_probs"]
            for idx, (gs, ge, _, _) in enumerate(orfs):
                if ge < ls0 - 200 or gs > re0 + 200:
                    continue
                p_val = float(ph[idx])
                p4 = float(f10[idx, 4])
                p9 = float(f10[idx, 9])
                core_max = float(np.max(f10[idx, :5]))
                if p4 >= 0.40 and p_val >= 0.45:
                    integrase_intervals.append((gs, ge))
                if p9 < 0.65:
                    if p_val >= 0.60 or core_max >= 0.45:
                        protected_core_intervals.append((gs, ge))
                    if p_val >= 0.45:
                        phage_cds_intervals.append((gs, ge))
                if (p_val < 0.22 and p4 < 0.22 and core_max < 0.25) or (p9 >= 0.62 and p_val < 0.40):
                    clear_host_intervals.append((gs, ge))

        def _violates_biological_guards(cand_s: int, cand_e: int) -> bool:
            for cs, ce in protected_core_intervals:
                if reg.start_bp <= 0.5 * (cs + ce) <= reg.end_bp:
                    if cand_s > cs + 18 or cand_e < ce - 18:
                        return True
                if cs + 22 < cand_s < ce - 22 or cs + 22 < cand_e < ce - 22:
                    return True

            # 防越宿主向外盲扩：不允许跨过边界外侧已明确判定的宿主完整基因
            if cand_s < reg.start_bp:
                for hs, he in clear_host_intervals:
                    if he <= reg.start_bp + 20 and hs >= cand_s - 20:
                        return True
            if cand_e > reg.end_bp:
                for hs, he in clear_host_intervals:
                    if hs >= reg.end_bp - 20 and he <= cand_e + 20:
                        return True
            return False

        def _integrase_proximity(pos_l: int, pos_r: int) -> float:
            best = 0.0
            for is0, ie0 in integrase_intervals:
                dmin = min(abs(pos_l - is0), abs(pos_l - ie0), abs(pos_r - is0), abs(pos_r - ie0))
                if dmin <= 1200:
                    best = max(best, 1.0 - float(dmin) / 1500.0)
            return best

        def _is_intergenic(pos: int) -> bool:
            return not any(gs + 12 < pos < ge - 12 for gs, ge in phage_cds_intervals)

        r_seq = seq[rs0:re0]
        r_index: Dict[str, List[int]] = defaultdict(list)
        for j in range(0, len(r_seq) - k_seed + 1):
            sub = r_seq[j : j + k_seed]
            if "N" in sub:
                continue
            r_index[sub].append(rs0 + j)

        l_seq = seq[ls0:le0]
        seen_pairs = set()
        best_score = -1.0
        best_hit: Optional[AttAlignmentHit] = None

        for i in range(0, len(l_seq) - k_seed + 1):
            seed = l_seq[i : i + k_seed]
            r_locs = r_index.get(seed)
            if not r_locs:
                continue
            l_seed = ls0 + i
            for r_seed in r_locs:
                for allow_mm in (0, 1):
                    ll, lr, rr, mm = _extend_dr_match(
                        seq,
                        l_seed,
                        r_seed,
                        k_seed,
                        ls0,
                        le0,
                        rs0,
                        re0,
                        allow_mm=allow_mm,
                        max_dr_len=max_dr_len,
                    )
                    ext = lr - ll
                    if mm == 0 and ext < min_exact_len:
                        continue
                    if mm == 1 and ext < min_mm1_len:
                        continue
                    cand_s, cand_e = ll, rr + ext
                    if cand_e - cand_s < 3000 or (cand_s, cand_e) in seen_pairs:
                        continue
                    seen_pairs.add((cand_s, cand_e))

                    dr_seq = seq[ll:lr]
                    if _shannon_entropy(dr_seq) < 1.55 or _has_simple_tandem_repeat(dr_seq):
                        continue
                    if _violates_biological_guards(cand_s, cand_e):
                        continue

                    ig_bonus = _integrase_proximity(cand_s, cand_e)
                    both_intergenic = _is_intergenic(cand_s) and _is_intergenic(cand_e)
                    if mm == 0:
                        req_len = 14 if (ig_bonus > 0.1 and both_intergenic) else 16
                        if ext < req_len:
                            continue
                    else:
                        req_mm1 = 18 if ig_bonus > 0.1 else 21
                        if ext < req_mm1:
                            continue

                    inter_bonus = 1.5 if both_intergenic else 0.0
                    dist_pen = (abs(cand_s - reg.start_bp) + abs(cand_e - reg.end_bp)) / 1800.0
                    score = float(ext - 4 * mm) + 3.0 * ig_bonus + inter_bonus - 1.8 * dist_pen
                    if score > best_score:
                        best_score = score
                        best_hit = AttAlignmentHit(
                            contig_id=cid,
                            old_start_bp=reg.start_bp,
                            old_end_bp=reg.end_bp,
                            new_start_bp=cand_s,
                            new_end_bp=cand_e,
                            dr_len_bp=ext,
                            mismatches=mm,
                            near_integrase=ig_bonus > 0.1,
                            both_intergenic=both_intergenic,
                            dr_seq=dr_seq,
                        )

        if best_hit is None and enable_trna_short_dr:
            best_hit = _search_trna_short_att_hit(
                cid,
                seq,
                reg,
                ls0,
                le0,
                rs0,
                re0,
                integrase_intervals,
                _violates_biological_guards,
                _integrase_proximity,
                _is_intergenic,
            )

        if best_hit is not None:
            if best_hit.new_start_bp != reg.start_bp or best_hit.new_end_bp != reg.end_bp:
                aligned_cnt += 1
            if details_out is not None:
                details_out[f"{cid}:{best_hit.new_start_bp}-{best_hit.new_end_bp}"] = best_hit
            out.append(
                PredictedRegion(
                    contig_id=cid,
                    start_bp=best_hit.new_start_bp,
                    end_bp=best_hit.new_end_bp,
                    peak_score=reg.peak_score,
                    mean_score=reg.mean_score,
                    window_count=reg.window_count,
                )
            )
        else:
            out.append(reg)

    return out, aligned_cnt

