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

from ..benchmark.metrics import PredictedRegion, WindowPrediction, decode_subwindow_probs_to_regions
from ..data.feature_dataset import iter_fasta
from ..experts.seq_dataset import encode_dna, reverse_complement_codes
from ..features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows
from ..student.distilled_student import build_distilled_student
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


def _extract_contig_worker(args: Tuple[str, str, int, int]) -> Dict[str, Any]:
    cid, seq, win_size, step_size = args
    return extract_contig_windows(cid, seq, win_size=win_size, step_size=step_size, truth_regions=None)


class GenomeScanner:
    """加载训练好的 Student Pro 模型并提供端到端双阶段扫描能力。"""

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
        gate_config: Optional[ProteinGateConfig] = None,
        workers: Optional[int] = None,
        device: Optional[str] = None,
    ):
        import torch

        self.model_pt_path = Path(model_pt_path).resolve()
        self.seed_threshold = float(seed_threshold)
        self.extend_threshold = float(extend_threshold)
        self.sub_threshold = float(sub_threshold)
        self.merge_gap_bp = int(merge_gap_bp)
        self.min_region_bp = int(min_region_bp)
        self.win_size = int(win_size)
        self.step_size = int(step_size)
        self.blast_db = Path(blast_db) if blast_db else None
        self.gate_config = gate_config or ProteinGateConfig(enabled=(blast_db is not None))
        cpu_cnt = os.cpu_count() or 4
        self.workers = workers if workers is not None else max(1, cpu_cnt - 2)

        if device is not None:
            self.device = torch.device(device)
        else:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

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
        gate_config: Optional[ProteinGateConfig] = None,
        workers: Optional[int] = None,
        device: Optional[str] = None,
    ) -> "GenomeScanner":
        """从模型输出目录自动读取 student_distilled.pt 与 student_report.json 中 val 标定阈值。"""
        import json

        root = Path(model_dir).resolve()
        rep_path = root / "student_report.json"
        dec: Dict[str, Any] = {}
        if rep_path.exists():
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            dec = rep.get("decoder_tuned_on_val") or {}

        return cls(
            model_pt_path=root / "student_distilled.pt",
            seed_threshold=float(dec.get("seed_threshold", 0.85)),
            extend_threshold=float(dec.get("extend_threshold", 0.50)),
            sub_threshold=float(dec.get("sub_threshold", 0.45)),
            blast_db=blast_db,
            gate_config=gate_config,
            workers=workers,
            device=device,
        )

    def _predict_windows(
        self,
        codes: np.ndarray,
        lengths: np.ndarray,
        feats: np.ndarray,
        batch_size: int = 128,
    ) -> Tuple[np.ndarray, np.ndarray]:
        import torch

        n = len(feats)
        out = np.zeros(n, dtype=np.float32)
        out_sub = np.zeros((n, SUB_BINS), dtype=np.float32)
        if n == 0:
            return out, out_sub

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
        return out, out_sub

    def scan_sequences(
        self,
        contig_seqs: Dict[str, str],
        *,
        apply_protein_gate: Optional[bool] = None,
        hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
    ) -> ScanResult:
        """对内存中给定的 contig 字典执行双阶段扫描。"""
        t_feat0 = time.perf_counter()
        contigs_bp = {cid: len(seq) for cid, seq in contig_seqs.items()}
        total_bp = sum(contigs_bp.values())

        tasks = [(cid, seq, self.win_size, self.step_size) for cid, seq in contig_seqs.items()]
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

        for item in extracted:
            cid = item["contig_id"]
            seq_upper = contig_seqs[cid].upper()
            starts = item["starts"]
            ends = item["ends"]
            feats_list.append(item["features"])
            for s, e in zip(starts, ends):
                sub = seq_upper[int(s):int(e)]
                enc = np.full(self.win_size, 4, dtype=np.uint8)
                raw = encode_dna(sub)[:self.win_size]
                enc[:len(raw)] = raw
                codes_list.append(enc)
                len_list.append(len(raw))
                win_preds.append(
                    WindowPrediction(
                        contig_id=cid,
                        start_bp=int(s),
                        end_bp=int(e),
                        score=0.0,
                    )
                )

        if feats_list:
            feats_arr = np.concatenate(feats_list, axis=0)
            codes_arr = np.stack(codes_list, axis=0)
            len_arr = np.asarray(len_list, dtype=np.int64)
            win_scores, sub_probs = self._predict_windows(codes_arr, len_arr, feats_arr)
            for idx, wp in enumerate(win_preds):
                wp.score = float(win_scores[idx])
        else:
            sub_probs = np.zeros((0, SUB_BINS), dtype=np.float32)
        student_sec = round(time.perf_counter() - t_inf0, 3)

        t_dec0 = time.perf_counter()
        raw_regions = decode_subwindow_probs_to_regions(
            win_preds,
            sub_probs,
            seed_threshold=self.seed_threshold,
            extend_threshold=self.extend_threshold,
            sub_threshold=self.sub_threshold,
            merge_gap_bp=self.merge_gap_bp,
            min_region_bp=self.min_region_bp,
        )
        decode_sec = round(time.perf_counter() - t_dec0, 3)

        use_gate = self.gate_config.enabled if apply_protein_gate is None else bool(apply_protein_gate)
        t_gate0 = time.perf_counter()
        if use_gate:
            verified_regions, gate_details = evaluate_regions_with_protein_gate(
                contig_seqs,
                raw_regions,
                blast_db=self.blast_db,
                config=self.gate_config,
                threads=self.workers,
                hit_fetcher=hit_fetcher,
            )
        else:
            verified_regions = list(raw_regions)
            gate_details = []
        gate_sec = round(time.perf_counter() - t_gate0, 3)

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
        )

    def scan_fasta(
        self,
        fasta_path: Path,
        *,
        apply_protein_gate: Optional[bool] = None,
        hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
    ) -> ScanResult:
        """读取 FASTA 文件并执行双阶段扫描。"""
        contig_seqs = {cid: seq for cid, seq in iter_fasta(Path(fasta_path))}
        return self.scan_sequences(
            contig_seqs,
            apply_protein_gate=apply_protein_gate,
            hit_fetcher=hit_fetcher,
        )
