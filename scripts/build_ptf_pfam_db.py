# -*- coding: utf-8 -*-
"""
从本地 VirSorter2 / Pfam-A 数据库中抽提构建 PhageTailFinder 专用 Pfam HMM 索引库。

输出路径：database/phage_tail_finder/ptf_pfams.h3m
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assembly.env.wsl_manager import WSLManager  # noqa: E402
from src.workbench.models.tool_config import ToolConfig  # noqa: E402

logger = logging.getLogger("build_ptf_pfam_db")


def build_ptf_hmm_db(force: bool = False) -> Path:
    """
    依据 third_party/PhageTailFinder/hmmmodel/pfam_DICT 所需的 Pfam ID，
    通过 WSL PyHMMER 从本地 Pfam-A HMM 库抽提重建 ptf_pfams.h3m。
    """
    out_dir = ToolConfig.get_db_dir("phage_tail_finder")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ptf_pfams.h3m"

    if out_path.is_file() and out_path.stat().st_size > 50_000_000 and not force:
        return out_path

    pfam_dict_path = ToolConfig.PROJECT_ROOT / "third_party" / "PhageTailFinder" / "hmmmodel" / "pfam_DICT"
    if not pfam_dict_path.is_file():
        raise FileNotFoundError(f"未找到 PhageTailFinder 模型字典: {pfam_dict_path}")

    if not WSLManager.is_available():
        raise RuntimeError("未检测到可用的 WSL 环境，无法执行 Pfam-A 提取建库")

    WSLManager.ensure_project_link()
    wsl_dict = WSLManager.to_wsl_path(str(pfam_dict_path))
    wsl_out = WSLManager.to_wsl_path(str(out_path))
    wsl_tmp = f"{wsl_out}.tmp"

    py_script = (
        "import glob, os, shutil, pyhmmer\n"
        f"need = set(l.split('\\t')[0].strip() for l in open('{wsl_dict}', encoding='utf-8') if l.strip())\n"
        "sources = sorted(glob.glob('/opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm'))\n"
        "if not sources:\n"
        "  raise FileNotFoundError('WSL 中未找到 /opt/virsorter2_db/hmm/pfam/Pfam-A-*.hmm')\n"
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
        "print(f'EXTRACTED={len(seen)}/{len(need)}')\n"
    )
    distro = WSLManager.get_best_distro()
    res = subprocess.run(
        ["wsl", "-d", distro, "bash", "-lc", f"python3 - << 'PY'\n{py_script}PY"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=300,
    )
    logger.info("PhageTailFinder Pfam HMM 库构建成功: %s (%s)", out_path, res.stdout.strip())
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    target = build_ptf_hmm_db(force="--force" in sys.argv)
    print(f"Ready: {target} ({target.stat().st_size / 1024 / 1024:.2f} MB)")
