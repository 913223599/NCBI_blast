# -*- coding: utf-8 -*-
"""
端到端全基因组双阶段扫描器（Student Pro 初筛 + 200bp 精细解码 + 可选蛋白门控复核）

支持：
1. 读取任意多条 contig FASTA（自动保留 CPU 冗余多核提取 185 维窗口特征）；
2. 自动优先采用 PyTorch CUDA 推理（或无缝导出/直跑 Student 模型），正反链双向打分；
3. 解码得到精细区间（200bp 分辨率），输出 raw_regions 与可选蛋白门控后的 verified_regions；
4. 记录逐阶段耗时（feature_sec / student_sec / decode_sec / gate_sec）供严密对照评测。
"""
import concurrent.futures
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..benchmark.metrics import (
    PredictedRegion,
    WindowPrediction,
    assemble_contig_subbin_profile,
    decode_subwindow_probs_to_regions,
)
from ..data.feature_dataset import iter_fasta
from ..experts.expert_c_orf import extract_contig_orf_tokens
from ..experts.seq_dataset import encode_dna, reverse_complement_codes
from ..features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows
from ..student.distilled_student import build_distilled_student
from ..student.distilled_student_v4 import (
    REFINER_STEP_FEAT_DIM,
    _predict_v4_all,
    build_distilled_student_v4,
    build_region_context_refiner,
    group_windows_by_contig,
    predict_with_context_refiner,
)
from ..student.subbin_refiner import (
    extract_per_orf_viral_scores,
    load_subbin_refiner_checkpoint,
    predict_subbin_probs_with_refiner,
    project_orf_to_25bins,
)
from .protein_gate import ProteinGateConfig, RegionGateResult, evaluate_regions_with_protein_gate

logger = logging.getLogger("phage_discovery.inference.scanner")


@dataclass
class ScanResult:
    """全基因组扫描结果与分阶段耗时统计。"""

    contigs_bp: Dict[str, int]
    total_bp: int
    total_windows: int
    raw_regions: List[PredictedRegion]
    verified_regions: List[PredictedRegion]
    gate_details: List[RegionGateResult] = field(default_factory=list)
    timings_sec: Dict[str, float] = field(default_factory=dict)
    region_profiles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    contig_score_tracks: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


def _collect_region_profiles(
    win_preds: Sequence[WindowPrediction],
    sub_probs: np.ndarray,
    subbin_profiles: Optional[Dict[str, List[Tuple[int, np.ndarray]]]],
    regions: Sequence[PredictedRegion],
    contigs_bp: Dict[str, int],
    *,
    smooth_profile: bool,
    bin_bp: int = 200,
    flank_bp: int = 2000,
) -> Dict[str, List[Dict[str, Any]]]:
    """仅对命中的前噬菌体区段采集含侧翼的 200bp 置信度剖面（供工作台边界曲线可视化）。"""
    if not regions or not win_preds or len(sub_probs) == 0:
        return {}

    from collections import defaultdict
    by_contig_idx: Dict[str, List[int]] = defaultdict(list)
    for idx, wp in enumerate(win_preds):
        by_contig_idx[wp.contig_id].append(idx)

    by_contig_regs: Dict[str, List[PredictedRegion]] = defaultdict(list)
    for reg in regions:
        by_contig_regs[reg.contig_id].append(reg)

    profiles_out: Dict[str, List[Dict[str, Any]]] = {}
    for cid, c_regs in by_contig_regs.items():
        idxs = by_contig_idx.get(cid, [])
        if not idxs:
            continue
        contig_end = contigs_bp.get(cid, 0)
        prof = assemble_contig_subbin_profile(
            [win_preds[i] for i in idxs],
            [sub_probs[i] for i in idxs],
            contig_end,
            bin_bp=bin_bp,
            precomputed_segments=subbin_profiles.get(cid) if subbin_profiles else None,
            smooth_profile=smooth_profile,
        )
        n_bins = len(prof)
        for reg in c_regs:
            key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
            s_flank = max(0, reg.start_bp - flank_bp)
            e_flank = min(contig_end, reg.end_bp + flank_bp)
            b0 = max(0, s_flank // bin_bp)
            b1 = min(n_bins, max(b0 + 1, (e_flank + bin_bp - 1) // bin_bp))
            bins_list: List[Dict[str, Any]] = []
            for bi in range(b0, b1):
                bs = bi * bin_bp
                be = min(contig_end, bs + bin_bp)
                bins_list.append(
                    {
                        "start_bp": bs,
                        "end_bp": be,
                        "prob": round(float(prof[bi]), 4),
                        "in_region": bs < reg.end_bp and be > reg.start_bp,
                    }
                )
            profiles_out[key] = bins_list
    return profiles_out


def _collect_contig_score_tracks(
    win_preds: Sequence[WindowPrediction],
    contigs_bp: Dict[str, int],
    *,
    num_bins: int = 360,
) -> Dict[str, List[Dict[str, Any]]]:
    """将全 Contig 滑动窗口概率下采样为固定分箱景观波形，用于全基因组叠图浏览。"""
    if not contigs_bp:
        return {}

    from collections import defaultdict

    by_contig: Dict[str, List[WindowPrediction]] = defaultdict(list)
    for wp in win_preds:
        by_contig[wp.contig_id].append(wp)

    tracks: Dict[str, List[Dict[str, Any]]] = {}
    for cid, c_len in contigs_bp.items():
        if c_len <= 0:
            tracks[cid] = []
            continue
        actual_bins = min(max(1, c_len // 200), max(16, num_bins))
        bin_step = max(1.0, float(c_len) / float(actual_bins))
        wps = by_contig.get(cid, [])
        max_scores = np.zeros(actual_bins, dtype=np.float32)
        sum_scores = np.zeros(actual_bins, dtype=np.float32)
        cnt_scores = np.zeros(actual_bins, dtype=np.int32)

        for wp in wps:
            b0 = max(0, min(actual_bins - 1, int(float(wp.start_bp) / bin_step)))
            b1 = max(b0, min(actual_bins - 1, int(float(max(wp.start_bp, wp.end_bp - 1)) / bin_step)))
            sc = float(wp.score)
            for bi in range(b0, b1 + 1):
                if sc > max_scores[bi]:
                    max_scores[bi] = sc
                sum_scores[bi] += sc
                cnt_scores[bi] += 1

        bins_out: List[Dict[str, Any]] = []
        for bi in range(actual_bins):
            sb = round(bi * bin_step)
            eb = min(c_len, round((bi + 1) * bin_step))
            if eb <= sb:
                eb = min(c_len, sb + 1)
            cnt = int(cnt_scores[bi])
            mean_v = float(sum_scores[bi]) / float(cnt) if cnt > 0 else 0.0
            bins_out.append(
                {
                    "start_bp": sb,
                    "end_bp": eb,
                    "max_prob": round(float(max_scores[bi]), 4),
                    "mean_prob": round(mean_v, 4),
                }
            )
        tracks[cid] = bins_out
    return tracks


def _extract_contig_worker(args: Tuple[str, str, int, int, bool]) -> Dict[str, Any]:
    cid, seq, win_size, step_size, extract_orfs = args
    res = extract_contig_windows(cid, seq, win_size=win_size, step_size=step_size, truth_regions=None)
    if extract_orfs:
        tk, cn = extract_contig_orf_tokens(seq, res["starts"], res["ends"])
        res["orf_tokens"] = tk
        res["orf_counts"] = cn
    return res


class GenomeScanner:
    """加载训练好的 Student Pro / Student V4 模型并提供端到端双阶段扫描能力。"""

    def __init__(
        self,
        model_pt_path: Path,
        *,
        seed_threshold: float = 0.85,
        extend_threshold: float = 0.50,
        sub_threshold: float = 0.45,
        merge_gap_bp: int = 3000,
        min_region_bp: int = 3000,
        win_size: int = 5000,
        step_size: int = 2500,
        blast_db: Optional[Path] = None,
        blastp_bin: str = "blastp",
        gate_config: Optional[ProteinGateConfig] = None,
        workers: Optional[int] = None,
        device: Optional[str] = None,
        meta_path: Optional[Path] = None,
        use_context_refiner: Optional[bool] = None,
        use_subbin_refiner: Optional[bool] = None,
        plateau_min_windows: int = 0,
        plateau_second_threshold: Optional[float] = None,
        refine_pad_bp: Optional[int] = None,
        smooth_sub_profile: Optional[bool] = None,
    ):
        import json
        import torch

        self.model_pt_path = Path(model_pt_path).resolve()
        self.seed_threshold = float(seed_threshold)
        self.extend_threshold = float(extend_threshold)
        self.sub_threshold = float(sub_threshold)
        self.merge_gap_bp = merge_gap_bp
        self.min_region_bp = min_region_bp
        self.win_size = win_size
        self.step_size = step_size
        self.plateau_min_windows = plateau_min_windows
        self.plateau_second_threshold = float(plateau_second_threshold) if plateau_second_threshold is not None else None
        self.refine_pad_bp = refine_pad_bp
        self.smooth_sub_profile = smooth_sub_profile
        self.blast_db = Path(blast_db) if blast_db else None
        self.blastp_bin = blastp_bin
        self.gate_config = gate_config or ProteinGateConfig(enabled=(blast_db is not None))
        cpu_cnt = os.cpu_count() or 4
        self.workers = workers if workers is not None else max(1, cpu_cnt - 2)

        if device is not None:
            self.device = torch.device(device)
        else:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        resolved_meta = Path(meta_path).resolve() if meta_path is not None else (self.model_pt_path.parent / "student_v4_meta.json")
        self.model_version = "v3"
        self.model: Any
        self.refiner: Any = None
        self.subbin_refiner: Any = None
        if resolved_meta.exists() or self.model_pt_path.name == "student_v4.pt":
            meta = json.loads(resolved_meta.read_text(encoding="utf-8")) if resolved_meta.exists() else {}
            feat_dim = int(meta.get("feat_dim", len(FEATURE_NAMES)))
            dummy_mean = np.zeros(feat_dim, dtype=np.float32)
            dummy_std = np.ones(feat_dim, dtype=np.float32)
            self.model_version = "v4"
            self.model = build_distilled_student_v4(
                feat_dim,
                dummy_mean,
                dummy_std,
                dna_channels=int(meta.get("dna_channels", 160)),
                orf_d_model=int(meta.get("orf_d_model", 128)),
                orf_nhead=int(meta.get("orf_nhead", 4)),
                orf_num_layers=int(meta.get("orf_num_layers", 3)),
                fusion_dim=int(meta.get("fusion_dim", 256)),
                sem_dim=int(meta.get("sem_dim", 4)),
            ).to(self.device)
            state = torch.load(self.model_pt_path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            self.model.eval()

            want_ref = bool(meta.get("use_context_refiner", False)) if use_context_refiner is None else use_context_refiner
            if want_ref:
                ref_cand = self.model_pt_path.parent / "context_refiner.pt"
                if not ref_cand.exists() and meta.get("refiner_ckpt") and Path(meta["refiner_ckpt"]).exists():
                    ref_cand = Path(meta["refiner_ckpt"])
                if ref_cand.exists():
                    ref_state = torch.load(ref_cand, map_location=self.device, weights_only=True)
                    in_w = ref_state.get("in_proj.0.weight")
                    if in_w is not None and hasattr(in_w, "shape") and len(in_w.shape) == 2:
                        use_ctx = int(in_w.shape[1]) > REFINER_STEP_FEAT_DIM
                    else:
                        use_ctx = str(meta.get("refiner_arch", "v1")).lower() == "v2"
                    self.refiner = build_region_context_refiner(use_context_features=use_ctx).to(self.device)
                    self.refiner.load_state_dict(ref_state)
                    self.refiner.eval()

            want_subbin = bool(meta.get("use_subbin_refiner", False)) if use_subbin_refiner is None else use_subbin_refiner
            sb_local = self.model_pt_path.parent / "subbin_refiner.pt"
            if use_subbin_refiner is None and not want_subbin and sb_local.exists():
                want_subbin = True
            if want_subbin:
                sb_cand = sb_local
                if not sb_cand.exists() and meta.get("subbin_ckpt") and Path(meta["subbin_ckpt"]).exists():
                    sb_cand = Path(meta["subbin_ckpt"])
                if sb_cand.exists():
                    self.subbin_refiner = load_subbin_refiner_checkpoint(sb_cand, self.device)
        else:
            feat_dim = len(FEATURE_NAMES)
            dummy_mean = np.zeros(feat_dim, dtype=np.float32)
            dummy_std = np.ones(feat_dim, dtype=np.float32)
            self.model = build_distilled_student(feat_dim, dummy_mean, dummy_std).to(self.device)
            state = torch.load(self.model_pt_path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            self.model.eval()

    @classmethod
    def from_model_dir(
        cls,
        model_dir: Path,
        *,
        blast_db: Optional[Path] = None,
        blastp_bin: str = "blastp",
        gate_config: Optional[ProteinGateConfig] = None,
        workers: Optional[int] = None,
        device: Optional[str] = None,
        use_context_refiner: Optional[bool] = None,
        use_subbin_refiner: Optional[bool] = None,
        seed_threshold: Optional[float] = None,
        extend_threshold: Optional[float] = None,
        sub_threshold: Optional[float] = None,
        merge_gap_bp: Optional[int] = None,
        min_region_bp: Optional[int] = None,
    ) -> "GenomeScanner":
        """从模型输出目录自动检测 V4/V3/V2 模型权重与 val 标定阈值（支持覆盖核心阈值）。"""
        import json

        root = Path(model_dir).resolve()
        v4_meta = root / "student_v4_meta.json"
        v4_pt = root / "student_v4.pt"
        if v4_meta.exists() and v4_pt.exists():
            rep_path = root / "student_v4_report.json"
            if not rep_path.exists():
                rep_path = root / "student_report.json"
            dec: Dict[str, Any] = {}
            if rep_path.exists():
                rep = json.loads(rep_path.read_text(encoding="utf-8"))
                if use_context_refiner is False and rep.get("decoder_raw_on_val"):
                    dec = rep["decoder_raw_on_val"]
                else:
                    dec = rep.get("decoder_tuned_on_val") or {}
            return cls(
                model_pt_path=v4_pt,
                meta_path=v4_meta,
                use_context_refiner=use_context_refiner,
                use_subbin_refiner=use_subbin_refiner,
                seed_threshold=float(seed_threshold if seed_threshold is not None else dec.get("seed_threshold", 0.85)),
                extend_threshold=float(extend_threshold if extend_threshold is not None else dec.get("extend_threshold", 0.50)),
                sub_threshold=float(sub_threshold if sub_threshold is not None else dec.get("sub_threshold", 0.45)),
                merge_gap_bp=merge_gap_bp if merge_gap_bp is not None else 3000,
                min_region_bp=min_region_bp if min_region_bp is not None else 3000,
                plateau_min_windows=int(dec.get("plateau_min_windows", 0)),
                plateau_second_threshold=dec.get("plateau_second_threshold"),
                refine_pad_bp=dec.get("refine_pad_bp"),
                smooth_sub_profile=dec.get("smooth_profile"),
                blast_db=blast_db,
                blastp_bin=blastp_bin,
                gate_config=gate_config,
                workers=workers,
                device=device,
            )

        rep_path = root / "student_report.json"
        dec = {}
        if rep_path.exists():
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            dec = rep.get("decoder_tuned_on_val") or {}

        return cls(
            model_pt_path=root / "student_distilled.pt",
            seed_threshold=float(seed_threshold if seed_threshold is not None else dec.get("seed_threshold", 0.85)),
            extend_threshold=float(extend_threshold if extend_threshold is not None else dec.get("extend_threshold", 0.50)),
            sub_threshold=float(sub_threshold if sub_threshold is not None else dec.get("sub_threshold", 0.45)),
            merge_gap_bp=merge_gap_bp if merge_gap_bp is not None else 3000,
            min_region_bp=min_region_bp if min_region_bp is not None else 3000,
            blast_db=blast_db,
            blastp_bin=blastp_bin,
            gate_config=gate_config,
            workers=workers,
            device=device,
        )

    def _predict_windows_with_profiles(
        self,
        codes: np.ndarray,
        lengths: np.ndarray,
        feats: np.ndarray,
        batch_size: int = 128,
        orf_tokens: Optional[np.ndarray] = None,
        orf_counts: Optional[np.ndarray] = None,
        contig_ids: Optional[np.ndarray] = None,
        starts: Optional[np.ndarray] = None,
        ends: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray, Optional[Dict[str, List[Tuple[int, np.ndarray]]]]]:
        import torch

        n = len(feats)
        out = np.zeros(n, dtype=np.float32)
        out_sub = np.zeros((n, SUB_BINS), dtype=np.float32)
        if n == 0:
            return out, out_sub, None

        if self.model_version == "v4":
            if orf_tokens is None or orf_counts is None:
                from ..experts.expert_c_orf import MAX_ORFS_PER_WIN, ORF_FEAT_DIM
                orf_tokens = np.zeros((n, MAX_ORFS_PER_WIN, ORF_FEAT_DIM), dtype=np.float32)
                orf_counts = np.zeros(n, dtype=np.int32)
            pred = _predict_v4_all(
                self.model, codes, lengths, feats, orf_tokens, orf_counts, self.device, batch_size=batch_size,
            )
            win_scores = pred["win_probs"]
            if self.refiner is not None and contig_ids is not None and starts is not None:
                win_scores = predict_with_context_refiner(
                    self.refiner,
                    pred["win_logits"],
                    pred["sem_logits"],
                    pred["sub_probs"],
                    lengths,
                    contig_ids,
                    starts,
                    self.device,
                    max_len=codes.shape[1],
                )
            sub_probs = pred["sub_probs"]
            subbin_profiles: Optional[Dict[str, List[Tuple[int, np.ndarray]]]] = None
            if (
                self.subbin_refiner is not None
                and contig_ids is not None
                and starts is not None
                and ends is not None
            ):
                orf_bins = None
                if bool(getattr(self.subbin_refiner, "use_orf_bins", True)):
                    orf_attn = extract_per_orf_viral_scores(self.model, orf_tokens, orf_counts, self.device)
                    orf_bins = project_orf_to_25bins(orf_tokens, orf_counts, orf_attn)
                groups = group_windows_by_contig(contig_ids, starts, max_gap_bp=self.win_size)
                subbin_profiles, sub_probs = predict_subbin_probs_with_refiner(
                    self.subbin_refiner,
                    groups,
                    contig_ids,
                    starts,
                    ends,
                    win_scores,
                    pred["win_probs"],
                    pred["sem_logits"],
                    pred["sub_probs"],
                    self.device,
                    win_orf_25bins=orf_bins,
                    min_windows=2,
                )
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
            return win_scores, sub_probs, subbin_profiles

        rc = reverse_complement_codes(codes, lengths)
        max_len = codes.shape[1]
        with torch.no_grad(), torch.autocast(device_type=self.device.type, dtype=torch.float16, enabled=self.device.type == "cuda"):
            for i in range(0, n, batch_size):
                c1 = torch.from_numpy(codes[i:i + batch_size].astype(np.int64)).to(self.device)
                oh1 = torch.nn.functional.one_hot(c1, num_classes=5)[..., :4].permute(0, 2, 1).float()
                c2 = torch.from_numpy(rc[i:i + batch_size].astype(np.int64)).to(self.device)
                oh2 = torch.nn.functional.one_hot(c2, num_classes=5)[..., :4].permute(0, 2, 1).float()
                tb = torch.from_numpy(feats[i:i + batch_size]).to(self.device)
                ln = torch.from_numpy(lengths[i:i + batch_size]).to(self.device)
                w1, s1 = self.model(oh1, tb)
                w2, s2 = self.model(oh2, tb)
                p1, p2 = torch.sigmoid(w1), torch.sigmoid(w2)
                out[i:i + batch_size] = ((p1 + p2) / 2.0).float().cpu().numpy()
                sp1 = torch.sigmoid(s1)
                sp2 = torch.flip(torch.sigmoid(s2), dims=[1])
                sp = torch.where((ln == max_len).unsqueeze(1), (sp1 + sp2) / 2.0, sp1)
                out_sub[i:i + batch_size] = sp.float().cpu().numpy()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
        return out, out_sub, None

    def _predict_windows(
        self,
        codes: np.ndarray,
        lengths: np.ndarray,
        feats: np.ndarray,
        batch_size: int = 128,
        orf_tokens: Optional[np.ndarray] = None,
        orf_counts: Optional[np.ndarray] = None,
        contig_ids: Optional[np.ndarray] = None,
        starts: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        win_scores, sub_probs, _ = self._predict_windows_with_profiles(
            codes,
            lengths,
            feats,
            batch_size=batch_size,
            orf_tokens=orf_tokens,
            orf_counts=orf_counts,
            contig_ids=contig_ids,
            starts=starts,
            ends=None,
        )
        return win_scores, sub_probs

    def scan_sequences(
        self,
        contig_seqs: Dict[str, str],
        *,
        apply_protein_gate: Optional[bool] = None,
        hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
        collect_profiles: bool = False,
        profile_flank_bp: int = 2000,
    ) -> ScanResult:
        """对内存中给定的 contig 字典执行双阶段扫描。"""
        t_feat0 = time.perf_counter()
        contigs_bp = {cid: len(seq) for cid, seq in contig_seqs.items()}
        total_bp = sum(contigs_bp.values())

        extract_orfs = self.model_version == "v4"
        tasks = [(cid, seq, self.win_size, self.step_size, extract_orfs) for cid, seq in contig_seqs.items()]
        extracted: List[Dict[str, Any]] = []
        if len(tasks) > 1 and self.workers > 1:
            with concurrent.futures.ProcessPoolExecutor(max_workers=min(self.workers, len(tasks))) as ex:
                for res in ex.map(_extract_contig_worker, tasks):
                    extracted.append(res)
        else:
            for t in tasks:
                extracted.append(_extract_contig_worker(t))
        feature_sec = round(time.perf_counter() - t_feat0, 3)

        t_inf0 = time.perf_counter()
        win_preds: List[WindowPrediction] = []
        feats_list: List[np.ndarray] = []
        codes_list: List[np.ndarray] = []
        len_list: List[int] = []
        orf_tk_list: List[np.ndarray] = []
        orf_cn_list: List[np.ndarray] = []
        cid_list: List[str] = []
        start_list: List[int] = []
        end_list: List[int] = []

        for item in extracted:
            cid = item["contig_id"]
            seq_upper = contig_seqs[cid].upper()
            starts = item["starts"]
            ends = item["ends"]
            feats_list.append(item["features"])
            if extract_orfs and "orf_tokens" in item:
                orf_tk_list.append(item["orf_tokens"])
                orf_cn_list.append(item["orf_counts"])
            for s, e in zip(starts, ends):
                sub = seq_upper[int(s):int(e)]
                enc = np.full(self.win_size, 4, dtype=np.uint8)
                raw = encode_dna(sub)[:self.win_size]
                enc[:len(raw)] = raw
                codes_list.append(enc)
                len_list.append(len(raw))
                cid_list.append(cid)
                start_list.append(int(s))
                end_list.append(int(e))
                win_preds.append(
                    WindowPrediction(
                        contig_id=cid,
                        start_bp=int(s),
                        end_bp=int(e),
                        score=0.0,
                    )
                )

        subbin_profiles: Optional[Dict[str, List[Tuple[int, np.ndarray]]]] = None
        if feats_list:
            feats_arr = np.concatenate(feats_list, axis=0)
            codes_arr = np.stack(codes_list, axis=0)
            len_arr = np.asarray(len_list, dtype=np.int64)
            orf_tk_arr = np.concatenate(orf_tk_list, axis=0) if orf_tk_list else None
            orf_cn_arr = np.concatenate(orf_cn_list, axis=0) if orf_cn_list else None
            win_scores, sub_probs, subbin_profiles = self._predict_windows_with_profiles(
                codes_arr,
                len_arr,
                feats_arr,
                orf_tokens=orf_tk_arr,
                orf_counts=orf_cn_arr,
                contig_ids=np.asarray(cid_list),
                starts=np.asarray(start_list, dtype=np.int64),
                ends=np.asarray(end_list, dtype=np.int64),
            )
            for idx, wp in enumerate(win_preds):
                wp.score = float(win_scores[idx])
        else:
            sub_probs = np.zeros((0, SUB_BINS), dtype=np.float32)
        student_sec = round(time.perf_counter() - t_inf0, 3)

        t_dec0 = time.perf_counter()
        has_profiles = bool(subbin_profiles)
        smooth_prof = self.smooth_sub_profile if self.smooth_sub_profile is not None else (not has_profiles)
        refine_pad = self.refine_pad_bp if self.refine_pad_bp is not None else (3000 if has_profiles else 2000)
        raw_regions = decode_subwindow_probs_to_regions(
            win_preds,
            sub_probs,
            seed_threshold=self.seed_threshold,
            extend_threshold=self.extend_threshold,
            sub_threshold=self.sub_threshold,
            merge_gap_bp=self.merge_gap_bp,
            min_region_bp=self.min_region_bp,
            plateau_min_windows=self.plateau_min_windows,
            plateau_second_threshold=self.plateau_second_threshold,
            precomputed_bin_profiles=subbin_profiles,
            smooth_profile=smooth_prof,
            refine_pad_bp=refine_pad,
        )
        decode_sec = round(time.perf_counter() - t_dec0, 3)

        use_gate = self.gate_config.enabled if apply_protein_gate is None else apply_protein_gate
        t_gate0 = time.perf_counter()
        if use_gate:
            verified_regions, gate_details = evaluate_regions_with_protein_gate(
                contig_seqs,
                raw_regions,
                blast_db=self.blast_db,
                config=self.gate_config,
                blastp_bin=self.blastp_bin,
                threads=self.workers,
                hit_fetcher=hit_fetcher,
            )
        else:
            verified_regions = list(raw_regions)
            gate_details = []
        gate_sec = round(time.perf_counter() - t_gate0, 3)

        region_profiles = (
            _collect_region_profiles(
                win_preds,
                sub_probs,
                subbin_profiles,
                raw_regions,
                contigs_bp,
                smooth_profile=smooth_prof,
                flank_bp=profile_flank_bp,
            )
            if collect_profiles
            else {}
        )
        contig_score_tracks = (
            _collect_contig_score_tracks(win_preds, contigs_bp)
            if collect_profiles
            else {}
        )

        return ScanResult(
            contigs_bp=contigs_bp,
            total_bp=total_bp,
            total_windows=len(win_preds),
            raw_regions=raw_regions,
            verified_regions=verified_regions,
            gate_details=gate_details,
            timings_sec={
                "feature_sec": feature_sec,
                "student_sec": student_sec,
                "decode_sec": decode_sec,
                "gate_sec": gate_sec,
                "total_sec": round(feature_sec + student_sec + decode_sec + gate_sec, 3),
            },
            region_profiles=region_profiles,
            contig_score_tracks=contig_score_tracks,
        )

    def scan_fasta(
        self,
        fasta_path: Path,
        *,
        apply_protein_gate: Optional[bool] = None,
        hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
        collect_profiles: bool = False,
        profile_flank_bp: int = 2000,
    ) -> ScanResult:
        """读取 FASTA 文件并执行双阶段扫描。"""
        contig_seqs = {cid: seq for cid, seq in iter_fasta(Path(fasta_path))}
        return self.scan_sequences(
            contig_seqs,
            apply_protein_gate=apply_protein_gate,
            hit_fetcher=hit_fetcher,
            collect_profiles=collect_profiles,
            profile_flank_bp=profile_flank_bp,
        )
