# -*- coding: utf-8 -*-
"""
CheckV 教师封装（WSL2）：对 contig 运行 `checkv end_to_end`，解析 contamination.tsv 中
host/viral 区段坐标，转换为统一 PredictedRegion，供教师基线评测与伪标签边界精修。

注意：
- 仅通过 `wsl bash -c` 官方入口调用，不修改 WSL 内任何环境；
- Windows 路径自动转换为 /mnt/<drive>/... 并整体加引号，兼容含空格目录；
- 数据库路径由参数或环境变量 CHECKV_DB 提供，不在代码中写死。
"""
import argparse
import csv
import json
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..benchmark.metrics import PredictedRegion

logger = logging.getLogger("phage_discovery.teachers.checkv_teacher")


def to_wsl_path(win_path: Path) -> str:
    """将 Windows 绝对路径转换为 WSL /mnt 路径。"""
    p = Path(win_path).resolve()
    drive = p.drive.rstrip(":").lower()
    rest = p.as_posix().split(":", 1)[1] if ":" in p.as_posix() else p.as_posix()
    return f"/mnt/{drive}{rest}"


def run_checkv_end_to_end(
    input_fasta: Path,
    out_dir: Path,
    db_dir: Optional[str] = None,
    threads: Optional[int] = None,
    timeout_sec: int = 7200,
) -> Dict[str, Any]:
    """在 WSL 中运行 CheckV end_to_end。"""
    db = db_dir or os.environ.get("CHECKV_DB", "")
    if not db:
        raise ValueError("未提供 CheckV 数据库路径（参数 db_dir 或环境变量 CHECKV_DB）")
    cpu_cnt = os.cpu_count() or 4
    n_threads = threads if threads is not None else max(1, cpu_cnt - 2)

    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    # CheckV 内部以未加引号的 shell 命令调用 prodigal-gv，路径含空格会失败；
    # 因此在 WSL 无空格临时目录中运行，结束后将结果拷回目标目录并清理临时目录。
    stage = f"/tmp/checkv_stage_{os.getpid()}_{int(time.time())}"
    src_q = shlex.quote(to_wsl_path(input_fasta))
    dst_q = shlex.quote(to_wsl_path(out_root))
    cmd = (
        f"set -e; mkdir -p {stage}; cp {src_q} {stage}/input.fna; "
        f"checkv end_to_end {stage}/input.fna {stage}/out -d {shlex.quote(db)} -t {n_threads} --remove_tmp; "
        f"cp -r {stage}/out/. {dst_q}/; rm -rf {stage}"
    )
    t0 = time.perf_counter()
    res = subprocess.run(
        ["wsl", "bash", "-lc", cmd],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_sec,
    )
    elapsed = round(time.perf_counter() - t0, 2)
    log_path = out_root / "teacher_checkv_run.log"
    log_path.write_text(f"$ {cmd}\n[exit={res.returncode}, sec={elapsed}]\n{res.stdout}\n{res.stderr}", encoding="utf-8")
    return {"returncode": res.returncode, "elapsed_sec": elapsed, "log": str(log_path), "out_dir": str(out_root)}


def parse_checkv_viral_regions(contamination_tsv: Path, min_region_bp: int = 3000) -> List[PredictedRegion]:
    """
    解析 contamination.tsv：
    - provirus=Yes 时，按 region_types / region_coords_bp 抽取 viral 区段；
    - provirus=No 且 viral_genes > host_genes 时，视整条 contig 为病毒（独立噬菌体片段）。
    """
    regions: List[PredictedRegion] = []
    with open(contamination_tsv, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cid = row["contig_id"]
            length = int(float(row.get("contig_length") or 0))
            viral_genes = int(float(row.get("viral_genes") or 0))
            host_genes = int(float(row.get("host_genes") or 0))
            if (row.get("provirus") or "").strip().lower() == "yes":
                types = (row.get("region_types") or "").split(",")
                coords = (row.get("region_coords_bp") or "").split(",")
                for rtype, coord in zip(types, coords):
                    if rtype.strip().lower() != "viral" or "-" not in coord:
                        continue
                    s_txt, e_txt = coord.split("-", 1)
                    s_bp = int(s_txt) - 1
                    e_bp = int(e_txt)
                    if e_bp - s_bp >= min_region_bp:
                        regions.append(PredictedRegion(cid, s_bp, e_bp, 1.0, 1.0, 1))
            elif viral_genes > host_genes and viral_genes > 0 and length >= min_region_bp:
                regions.append(PredictedRegion(cid, 0, length, 1.0, 1.0, 1))
    return regions


def write_subset_fasta(src_fasta: Path, contig_ids: Sequence[str], out_fasta: Path) -> int:
    """从 FASTA 流式抽取指定 contig 子集。"""
    wanted = set(contig_ids)
    written = 0
    keep = False
    out_fasta.parent.mkdir(parents=True, exist_ok=True)
    with open(src_fasta, "r", encoding="utf-8", errors="replace") as fin, open(out_fasta, "w", encoding="utf-8") as fout:
        for line in fin:
            if line.startswith(">"):
                keep = line[1:].strip().split()[0] in wanted
                if keep:
                    written += 1
            if keep:
                fout.write(line)
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="在 WSL 中运行 CheckV 教师并输出区域")
    parser.add_argument("--input-fasta", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--db", default="", help="CheckV 数据库（WSL 路径），默认读取环境变量 CHECKV_DB")
    parser.add_argument("--threads", type=int, default=0)
    args = parser.parse_args()
    run = run_checkv_end_to_end(Path(args.input_fasta), Path(args.out_dir), db_dir=args.db or None,
                                threads=args.threads if args.threads > 0 else None)
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0 if run["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
