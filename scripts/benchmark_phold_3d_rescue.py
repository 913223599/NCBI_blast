# -*- coding: utf-8 -*-
"""
T1.4 条件触发 Phold 3D（ProstT5 + Foldseek）增强复核定向验证脚本

验证三类场景并客观记录召回增益、额外耗时与显存状态：
1. 远缘巨型肌尾组：phiKZ (NC_004629) 与 PaZh_1 (MN871489)，命中 `tailed_without_tmp`；
2. 高置信对照组：Lambda (NC_001416)、T4 (NC_000866)、T7 (NC_001604)，验证不触发 Phold 3D (额外耗时 0.0s 且结果零改变)；
3. 模拟序列同源失明组：清空 Lambda 与 T7 的 PHROG/PTF 序列命中使其首轮落入 Incomplete (`incomplete_large_contig`)，
   实测条件触发 Phold 3D 能否凭 3D 折叠构象重新挽回完整结构与尾部形态。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import LOCAL_FASTA_DIR, ensure_fasta_for_acc  # noqa: E402
from src.analysis.phage_structure.manager import (  # noqa: E402
    evaluate_single_contig_structure,
    should_trigger_phold_3d,
)
from src.analysis.phage_structure.queue import release_gpu_memory  # noqa: E402
from src.analysis.phage_structure.sequence_annotator import (  # noqa: E402
    check_phold_ready,
    enhance_with_phold_3d,
    get_safe_workers,
    parse_input_contigs,
    predict_missing_orfs_parallel,
    scan_proteins_with_pyhmmer,
)
from src.analysis.phage_structure.tail_finder_adapter import run_phagetailfinder_on_contigs  # noqa: E402
from src.analysis.phage_structure.thresholds import DEFAULT_THRESHOLDS  # noqa: E402
import logging
_s110_logger = logging.getLogger(__name__)

RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure_phold3d"
REPORT_JSON = RESULTS_DIR / "phold_3d_rescue_report.json"


def _query_gpu_free_mb() -> Optional[int]:
    try:
        res = subprocess.run(
            ["wsl", "-d", "Ubuntu", "bash", "-lc", "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            return int(res.stdout.strip().splitlines()[0].strip())
    except Exception as _exc:
        _s110_logger.debug("_query_gpu_free_mb 忽略非致命异常: %s", _exc)
    return None


def _run_conditional_case(
    label: str,
    fasta_path: Path,
    *,
    simulate_hmm_blindness: bool = False,
) -> Dict[str, Any]:
    workers = get_safe_workers(10)
    t_start = time.perf_counter()
    cmap = parse_input_contigs(fasta_path=str(fasta_path))
    cid, info = next(iter(cmap.items()))

    predict_missing_orfs_parallel(cmap, genetic_code=11, auto_select_genetic_code=True, workers=workers)
    if not simulate_hmm_blindness:
        scan_proteins_with_pyhmmer(cmap, workers=workers, hmm_thresholds=DEFAULT_THRESHOLDS.hmm)
        ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers)
        ptf_cnt, ptf_clusters = ptf_map.get(cid, (0, []))
    else:
        for p in info["proteins"]:
            p.product = "hypothetical protein"
            p.raw_product = "hypothetical protein"
            p.phrog_id = ""
            p.phrog_category = ""
            p.structural_role = "OTHER"
            p.role_label_cn = ""
            p.hmm_score = 0.0
            p.hmm_evalue = 1.0
            p.evidence_source = "pyrodigal"
            p.ptf_is_tail = False
            p.ptf_tail_prob = 0.0
            p.ptf_pfam = ""
            p.ptf_pfam_desc = ""
            p.ptf_all_pfams = []
        ptf_cnt, ptf_clusters = 0, []

    first_res = evaluate_single_contig_structure(
        cid,
        info,
        ptf_cnt,
        ptf_clusters,
        workers=workers,
        thresholds=DEFAULT_THRESHOLDS,
    )
    should_run, reason = should_trigger_phold_3d(
        first_res.prediction,
        first_res.tmp_analyses,
        first_res.length_bp,
        thresholds=DEFAULT_THRESHOLDS.classifier,
    )
    t_base = round(time.perf_counter() - t_start, 2)

    gpu_before = _query_gpu_free_mb()
    t_phold = 0.0
    rescued_map: Dict[str, int] = {}
    final_res = first_res
    if should_run:
        release_gpu_memory()
        t_p0 = time.perf_counter()
        enhance_with_phold_3d(
            cmap,
            workers=workers,
            min_aa=DEFAULT_THRESHOLDS.classifier.phold_rescue_min_aa,
            target_contigs=[cid],
            batch_size=1,
            omit_probs=False,
            rescued_by_contig=rescued_map,
        )
        t_phold = round(time.perf_counter() - t_p0, 2)
        release_gpu_memory()
        final_res = evaluate_single_contig_structure(
            cid,
            cmap[cid],
            ptf_cnt,
            ptf_clusters,
            workers=workers,
            thresholds=DEFAULT_THRESHOLDS,
            phold_triggered=True,
            phold_trigger_reason=reason,
            phold_rescued_orfs=rescued_map.get(cid, 0),
        )
    gpu_after = _query_gpu_free_mb()

    phold_roles = {}
    for p in final_res.structural_proteins:
        if p.evidence_source == "phold_3d":
            phold_roles[p.structural_role] = phold_roles.get(p.structural_role, 0) + 1

    return {
        "label": label,
        "fasta_path": str(fasta_path),
        "simulate_hmm_blindness": simulate_hmm_blindness,
        "length_bp": final_res.length_bp,
        "total_orfs": final_res.total_orfs,
        "base_elapsed_sec": t_base,
        "before_morph": first_res.prediction.morphotype_code,
        "before_confidence": first_res.prediction.confidence,
        "before_tmp_count": len(first_res.tmp_analyses),
        "triggered": should_run,
        "trigger_reason": reason,
        "phold_elapsed_sec": t_phold,
        "phold_rescued_orfs": rescued_map.get(cid, 0),
        "phold_structural_roles": phold_roles,
        "after_morph": final_res.prediction.morphotype_code,
        "after_confidence": final_res.prediction.confidence,
        "after_tmp_count": len(final_res.tmp_analyses),
        "after_tmp_aa": final_res.tmp_analyses[0].length_aa if final_res.tmp_analyses else None,
        "gpu_free_before_mb": gpu_before,
        "gpu_free_after_mb": gpu_after,
    }


def main() -> None:
    if not check_phold_ready():
        raise RuntimeError("Phold 3D 环境未就绪，无法运行 T1.4 定向复核基准")

    local_idx = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    cases: List[Dict[str, Any]] = []
    specs = [
        ("phiKZ_giant_tailed_no_tmp", ensure_fasta_for_acc("NC_004629", local_idx), False),
        ("PaZh_1_giant_tailed_no_tmp", PROJECT_ROOT / "data" / "validation" / "external_ncbi" / "fasta" / "MN871489.fasta", False),
        ("Lambda_high_conf_control", ensure_fasta_for_acc("NC_001416", local_idx), False),
        ("T4_high_conf_control", ensure_fasta_for_acc("NC_000866", local_idx), False),
        ("T7_high_conf_control", ensure_fasta_for_acc("NC_001604", local_idx), False),
        ("Lambda_simulated_hmm_blind", ensure_fasta_for_acc("NC_001416", local_idx), True),
        ("T7_simulated_hmm_blind", ensure_fasta_for_acc("NC_001604", local_idx), True),
    ]

    for label, fa_path, blind in specs:
        if fa_path is None or not Path(fa_path).is_file():
            raise FileNotFoundError(f"测试序列缺失: {label} -> {fa_path}")
        print(f"=== [T1.4] 运行场景: {label} (simulate_blind={blind}) ===")
        rec = _run_conditional_case(label, Path(fa_path), simulate_hmm_blindness=blind)
        cases.append(rec)
        print(
            f"  triggered={rec['triggered']} ({rec['trigger_reason']}) | "
            f"{rec['before_morph']} -> {rec['after_morph']} | "
            f"rescued={rec['phold_rescued_orfs']} ORFs | "
            f"phold_time={rec['phold_elapsed_sec']}s | GPU_free={rec['gpu_free_before_mb']}->{rec['gpu_free_after_mb']} MB"
        )

    REPORT_JSON.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"T1.4 定向 3D 复核报告已落盘: {REPORT_JSON}")


if __name__ == "__main__":
    main()
