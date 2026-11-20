# -*- coding: utf-8 -*-
"""
多源序列解析与 PHROGs 结构同源扫描器 (SequenceAnnotator)

职责：
1. 支持从 FASTA / GenBank (.gbk/.gbff) / 蛋白 FAA / 历史功能注释任务 / 前噬菌体发现区段提取 Contig 与蛋白 ORF；
2. 优先复用已有高可信 PHROG / Pharokka / Phold / GenBank 产物注解；对于未知蛋白或裸核酸输入，
   调度 Pyrodigal 多核预测 ORF + WSL PyHMMER 搜索本地精简结构 HMM 库 (structural_phrogs.h3m)；
3. 若缺少 structural_phrogs.h3m 缓存索引，支持从 pharokka_db/all_phrogs.h3m 自动抽取建库并缓存；
4. 支持可选调用 Phold AI (ProstT5 3Di + Foldseek) 对长未知假定蛋白补漏并强制清理 GPU 显存。
"""
from __future__ import annotations

import concurrent.futures
import csv
import gc
import gzip
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, cast

import pyrodigal
from Bio import SeqIO

from ...assembly.env.wsl_manager import WSLManager
from ...workbench.models.tool_config import ToolConfig
from .phrog_catalog import STRUCTURAL_INDEX_VERSION, classify_structural_role, get_phrog_catalog
from .types import StructureProteinItem

logger = logging.getLogger("analysis.phage_structure.annotator")

_GBK_EXTS = (".gbk", ".gb", ".genbank", ".gbff", ".gbk.gz", ".gb.gz", ".gbff.gz")
_FAA_AA_CHARS = set("ACDEFGHIKLMNPQRSTVWYBXZ*")
_UNANNOTATED_RE = re.compile(
    r"^(?:hypothetical|uncharacteri[sz]ed|unknown|phage\s+protein|gp\d+|orf\d+|duf\d+)",
    re.I,
)
_MANIFEST_NAME = "structural_phrogs.manifest.json"


def get_safe_workers(requested: Optional[int] = None) -> int:
    cpu_cnt = os.cpu_count() or 4
    safe_max = max(1, cpu_cnt - 2)
    if requested and requested > 0:
        return min(requested, safe_max)
    return min(14, safe_max)


def resolve_structural_hmm_path() -> Optional[Path]:
    struct_dir = ToolConfig.get_db_dir("phage_structure")
    cand = struct_dir / "structural_phrogs.h3m"
    manifest = struct_dir / _MANIFEST_NAME
    if not (cand.is_file() and cand.stat().st_size > 1_000_000):
        return None
    if manifest.is_file():
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
            if info.get("version") == STRUCTURAL_INDEX_VERSION:
                return cand
        except Exception:
            pass
    # 若存在旧版缓存但本地缺失全库，则保留降级复用；若全库就绪则返回 None 触发平滑增量升级
    if resolve_all_phrogs_hmm_path() is None:
        return cand
    return None


def resolve_all_phrogs_hmm_path() -> Optional[Path]:
    phar_dir = ToolConfig.get_db_dir("pharokka_db")
    cand = phar_dir / "all_phrogs.h3m"
    if cand.is_file() and cand.stat().st_size > 1_000_000:
        return cand
    return None


def check_wsl_pyhmmer_ready() -> bool:
    if not WSLManager.is_available():
        return False
    distro = WSLManager.get_best_distro()
    try:
        res = subprocess.run(
            ["wsl", "-d", distro, "python3", "-c", "import pyhmmer; print(pyhmmer.__version__)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def ensure_structural_hmm_db(
    on_progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """确保 database/phage_structure/structural_phrogs.h3m 索引库就绪；如缺失则从 all_phrogs.h3m 自动抽取。"""
    existing = resolve_structural_hmm_path()
    if existing is not None:
        return existing

    full_hmm = resolve_all_phrogs_hmm_path()
    if full_hmm is None:
        raise FileNotFoundError("未找到 PHROG 模型库: database/pharokka_db/all_phrogs.h3m")
    if not check_wsl_pyhmmer_ready():
        raise RuntimeError("WSL 环境中未就绪 pyhmmer，无法抽取结构 HMM 索引库")

    struct_dir = ToolConfig.get_db_dir("phage_structure")
    struct_dir.mkdir(parents=True, exist_ok=True)
    target_h3m = struct_dir / "structural_phrogs.h3m"

    keep_ids = get_phrog_catalog().structural_phrog_ids()
    if not keep_ids:
        raise RuntimeError("PHROG 注释目录中未检出有效结构类别")

    WSLManager.ensure_project_link()
    wsl_src = WSLManager.to_wsl_path(str(full_hmm))
    wsl_dst = WSLManager.to_wsl_path(str(target_h3m))
    wsl_tmp = f"/tmp/structural_phrogs_{os.getpid()}.h3m"

    if on_progress:
        on_progress(f"首次初始化：正在从 all_phrogs.h3m 抽取 {len(keep_ids)} 个结构/尾部家族建立高速缓存...")

    id_list_txt = ",".join(sorted(keep_ids))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as tf:
        tf.write(id_list_txt)
        win_id_file = Path(tf.name)
    try:
        wsl_id_file = WSLManager.to_wsl_path(str(win_id_file))
        py_script = (
            "import pyhmmer, shutil\n"
            f"keep = set(open('{wsl_id_file}', encoding='utf-8').read().split(','))\n"
            f"with pyhmmer.plan7.HMMFile('{wsl_src}') as src, open('{wsl_tmp}', 'wb') as dst:\n"
            "  for hmm in src:\n"
            "    nm = hmm.name.decode() if isinstance(hmm.name, bytes) else str(hmm.name)\n"
            "    if nm in keep: hmm.write(dst, binary=True)\n"
            f"shutil.move('{wsl_tmp}', '{wsl_dst}')\n"
        )
        distro = WSLManager.get_best_distro()
        subprocess.run(
            ["wsl", "-d", distro, "bash", "-lc", f"python3 - << 'PY'\n{py_script}PY"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
    finally:
        win_id_file.unlink(missing_ok=True)

    (struct_dir / _MANIFEST_NAME).write_text(
        json.dumps({"version": STRUCTURAL_INDEX_VERSION, "hmm_count": len(keep_ids)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target_h3m


def _is_protein_fasta_records(records: Sequence[Any]) -> bool:
    """启发式判断 FASTA 序列是氨基酸 (.faa) 还是核酸 (.fasta/.fna)。"""
    sample = "".join(str(r.seq)[:400].upper() for r in records[:5])
    if not sample:
        return False
    non_nt = sum(1 for ch in sample if ch not in "ACGTUN-")
    return (non_nt / max(1, len(sample))) > 0.12


def _open_maybe_gz(path: Path):
    if str(path).lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return open(path, "r", encoding="utf-8", errors="ignore")


def parse_input_contigs(
    *,
    fasta_path: Optional[str] = None,
    fasta_content: Optional[str] = None,
    selected_contigs: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    统一解析 FASTA / GenBank / 蛋白 FAA 输入，提取 Contig 序列元信息与已有 CDS 注解（如有）。
    返回: {contig_id: {"length_bp": int, "gc_percent": float, "dna_seq": str, "proteins": List[StructureProteinItem], "input_type": str}}
    """
    records = []
    input_type = "fasta"
    is_gbk = False

    if fasta_content and fasta_content.strip():
        raw = fasta_content.strip()
        if raw.startswith("LOCUS "):
            is_gbk = True
            input_type = "genbank"
            records = list(SeqIO.parse(io.StringIO(raw), "genbank"))
        else:
            if not raw.startswith(">"):
                raw = f">Sequence_1\n{raw}"
            records = list(SeqIO.parse(io.StringIO(raw), "fasta"))
    elif fasta_path:
        p = Path(fasta_path)
        if not p.is_file():
            raise FileNotFoundError(f"输入文件不存在: {fasta_path}")
        if p.name.lower().endswith(_GBK_EXTS):
            is_gbk = True
            input_type = "genbank"
            with _open_maybe_gz(p) as fh:
                records = list(SeqIO.parse(fh, "genbank"))
        else:
            with _open_maybe_gz(p) as fh:
                records = list(SeqIO.parse(fh, "fasta"))

    if not records:
        raise ValueError("未解析到有效的 FASTA 或 GenBank 序列记录")

    selected_set = set(selected_contigs) if selected_contigs else None
    out: Dict[str, Dict[str, Any]] = {}

    if not is_gbk and _is_protein_fasta_records(records):
        # 将蛋白多条序列聚合为单虚拟 Contig 供形态预测
        prots: List[StructureProteinItem] = []
        cursor = 1
        for idx, rec in enumerate(records, start=1):
            aa = str(rec.seq).strip().upper().rstrip("*")
            if not aa:
                continue
            desc = rec.description[len(rec.id):].strip() if rec.description.startswith(rec.id) else rec.description
            prod = desc or "hypothetical protein"
            role, role_cn = classify_structural_role(prod)
            end_bp = cursor + len(aa) * 3 - 1
            prots.append(
                StructureProteinItem(
                    locus_tag=rec.id or f"PROT_{idx:04d}",
                    contig_id="Uploaded_Proteins",
                    start=cursor,
                    end=end_bp,
                    strand="+",
                    length_aa=len(aa),
                    product=prod,
                    raw_product=prod,
                    structural_role=role,
                    role_label_cn=role_cn,
                    evidence_source="faa_header",
                    translation=aa,
                )
            )
            cursor = end_bp + 50
        out["Uploaded_Proteins"] = {
            "length_bp": cursor,
            "gc_percent": 0.0,
            "dna_seq": "",
            "proteins": prots,
            "input_type": "faa",
        }
        return out

    for rec in records:
        cid = str(rec.id or f"contig_{len(out) + 1}")
        if selected_set is not None and cid not in selected_set:
            continue
        seq_str = str(rec.seq).upper()
        n_bp = len(seq_str)
        gc_pct = round((seq_str.count("G") + seq_str.count("C")) * 100.0 / max(1, n_bp), 2)
        prots = []
        if is_gbk:
            cds_idx = 0
            seen_loci: set[str] = set()
            for feat in getattr(rec, "features", []):
                if feat.type != "CDS":
                    continue
                cds_idx += 1
                q = feat.qualifiers or {}
                lt_raw = str((q.get("locus_tag") or q.get("protein_id") or q.get("gene") or [f"{cid}_CDS_{cds_idx:04d}"])[0]).strip()
                lt = lt_raw or f"{cid}_CDS_{cds_idx:04d}"
                if lt in seen_loci:
                    lt = f"{lt}_{cds_idx:04d}"
                seen_loci.add(lt)

                prod_vals = [str(x).strip() for x in (q.get("product") or []) if str(x).strip()]
                func_vals = [str(x).strip() for x in (q.get("function") or []) if str(x).strip()]
                prod = prod_vals[0] if prod_vals else (func_vals[0] if func_vals else "hypothetical protein")

                phrog_raw = str((q.get("phrog") or [""])[0]).strip()
                if not phrog_raw:
                    note_blob = " ".join(str(x) for x in (q.get("note", []) + q.get("db_xref", []) + q.get("inference", [])))
                    m_ph = re.search(r"phrog[\s_:#-]*(\d+)", note_blob, re.I)
                    if m_ph:
                        phrog_raw = f"phrog_{m_ph.group(1)}"

                aa = str((q.get("translation") or [""])[0]).strip().upper().replace(" ", "").rstrip("*")
                if not aa and n_bp > 0:
                    try:
                        aa = str(feat.extract(rec.seq).translate(table=11, to_stop=True)).upper()
                    except Exception:
                        try:
                            aa = str(feat.extract(rec.seq).translate(table=11)).split("*")[0].upper()
                        except Exception:
                            aa = ""
                if not aa:
                    continue
                role, role_cn = classify_structural_role(prod, phrog_id=phrog_raw)
                try:
                    start_bp = int(feat.location.start) + 1
                    end_bp = int(feat.location.end)
                except Exception:
                    continue
                prots.append(
                    StructureProteinItem(
                        locus_tag=lt,
                        contig_id=cid,
                        start=start_bp,
                        end=end_bp,
                        strand="+" if (feat.location.strand or 1) >= 0 else "-",
                        length_aa=len(aa),
                        product=prod,
                        raw_product=prod,
                        phrog_id=phrog_raw,
                        structural_role=role,
                        role_label_cn=role_cn,
                        evidence_source="genbank",
                        translation=aa,
                    )
                )
        out[cid] = {
            "length_bp": n_bp,
            "gc_percent": gc_pct,
            "dna_seq": seq_str,
            "proteins": prots,
            "input_type": input_type,
        }

    if not out:
        raise ValueError("所选 Contig 列表为空，无有效输入")
    return out


def _predict_single_contig_orfs(args: Tuple[str, str, int]) -> Tuple[str, List[StructureProteinItem]]:
    cid, seq_str, genetic_code = args
    if len(seq_str) < 200:
        return cid, []
    is_meta = len(seq_str) < 100_000
    if is_meta:
        gf = pyrodigal.GeneFinder(meta=True, mask=True)
    else:
        gf = pyrodigal.GeneFinder(meta=False, mask=True)
        try:
            gf.train(seq_str.encode("ascii", errors="replace"), translation_table=cast(Any, genetic_code))
        except Exception:
            gf = pyrodigal.GeneFinder(meta=True, mask=True)

    genes = gf.find_genes(seq_str.encode("ascii", errors="replace"))
    out: List[StructureProteinItem] = []
    for idx, g in enumerate(genes, start=1):
        aa = g.translate(translation_table=cast(Any, genetic_code), include_stop=False)
        if len(aa) < 25:
            continue
        out.append(
            StructureProteinItem(
                locus_tag=f"{cid}_ORF_{idx:04d}",
                contig_id=cid,
                start=g.begin,
                end=g.end,
                strand="+" if g.strand > 0 else "-",
                length_aa=len(aa),
                product="hypothetical protein",
                evidence_source="pyrodigal",
                translation=aa,
            )
        )
    return cid, out


def predict_missing_orfs_parallel(
    contig_map: Dict[str, Dict[str, Any]],
    *,
    genetic_code: int = 11,
    workers: int = 8,
) -> None:
    """对尚未拥有蛋白集合的裸核酸 Contig 使用多核 Pyrodigal 并发预测 ORF。"""
    tasks = [
        (cid, info["dna_seq"], genetic_code)
        for cid, info in contig_map.items()
        if not info["proteins"] and info["dna_seq"]
    ]
    if not tasks:
        return

    safe_w = max(1, min(workers, len(tasks)))
    if len(tasks) > 1 and safe_w > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=safe_w) as pool:
            for cid, prots in pool.map(_predict_single_contig_orfs, tasks):
                contig_map[cid]["proteins"] = prots
    else:
        for t in tasks:
            cid, prots = _predict_single_contig_orfs(t)
            contig_map[cid]["proteins"] = prots


def _is_low_complexity_repeat_artifact(aa_seq: str) -> bool:
    """识别纯周期人为合成/极端低复杂度重复肽段，防止胶原/纤维类 HMM 出现假性高分漂移。"""
    s = (aa_seq or "").strip().upper().rstrip("*")
    n = len(s)
    if n < 60:
        return False
    kmers = {s[i : i + 4] for i in range(n - 3)}
    return (len(kmers) / max(1, n - 3)) < 0.20


def scan_proteins_with_pyhmmer(
    contig_map: Dict[str, Dict[str, Any]],
    *,
    evalue_cutoff: float = 1e-4,
    score_cutoff: float = 28.0,
    workers: int = 12,
    force_rescan: bool = False,
    verify_annotated: bool = True,
    on_progress: Optional[Callable[[str], None]] = None,
) -> int:
    """
    通过 WSL pyhmmer 对扩展结构与防混淆 HMM 库执行序列优先的权威同源扫描。
    默认会对所有含有效氨基酸翻译 (>=25 aa) 的外部注释蛋白执行独立序列核实，
    防止非标准 GenBank / FAA 自由文本误导结构预测与尾长估算。
    """
    hmm_path = ensure_structural_hmm_db(on_progress=on_progress)
    WSLManager.ensure_project_link()
    wsl_hmm = WSLManager.to_wsl_path(str(hmm_path))

    # 序列优先：默认对全部拥有氨基酸翻译的 ORF 统一提交序列 HMM 验证（不再轻信外部 .gbk /product 字符串）
    query_items: List[Tuple[str, StructureProteinItem]] = []
    for cid, info in contig_map.items():
        for p in info["proteins"]:
            if not p.raw_product:
                p.raw_product = p.product or ""
            is_unannotated = bool(_UNANNOTATED_RE.match(p.product or ""))
            has_phrog_ref = bool(p.phrog_id and str(p.phrog_id).strip().lower().startswith(("phrog_", "1", "2", "3", "4", "5", "6", "7", "8", "9")))
            if force_rescan or verify_annotated or is_unannotated or not has_phrog_ref or p.structural_role == "OTHER":
                if p.translation and len(p.translation) >= 25:
                    qid = f"{cid}||{p.locus_tag}"
                    query_items.append((qid, p))

    if not query_items:
        return 0

    if on_progress:
        on_progress(f"正在通过 WSL PyHMMER ({workers} 核) 对 {len(query_items)} 条蛋白执行独立序列同源校验...")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".faa", newline="\n", delete=False) as tf:
        for qid, p in query_items:
            aa_seq = p.translation.replace("*", "").strip()
            if aa_seq:
                tf.write(f">{qid}\n{aa_seq}\n")
        win_faa = Path(tf.name)

    hits_map: Dict[str, Tuple[str, float, float]] = {}
    try:
        wsl_faa = WSLManager.to_wsl_path(str(win_faa))
        py_code = (
            "import pyhmmer\n"
            f"with pyhmmer.easel.SequenceFile('{wsl_faa}', digital=True, alphabet=pyhmmer.easel.Alphabet.amino()) as sf: seqs = sf.read_block()\n"
            f"with pyhmmer.plan7.HMMFile('{wsl_hmm}') as hf:\n"
            "  best = {}\n"
            f"  for top in pyhmmer.hmmsearch(hf, seqs, cpus={max(1, workers)}, E={evalue_cutoff}, Z=200):\n"
            "    q = top.query.name.decode() if isinstance(top.query.name, bytes) else str(top.query.name)\n"
            "    for h in top:\n"
            f"      if h.included and h.score >= {score_cutoff}:\n"
            "        t = h.name.decode() if isinstance(h.name, bytes) else str(h.name)\n"
            "        prev = best.get(t)\n"
            "        if prev is None or h.score > prev[1]:\n"
            "          best[t] = (q, h.score, h.evalue)\n"
            "for tid, (pid, sc, ev) in best.items():\n"
            "  print(f'{tid}\\t{pid}\\t{sc:.3f}\\t{ev:.3e}')\n"
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
                hits_map[parts[0]] = (parts[1], float(parts[2]), float(parts[3]))
    finally:
        win_faa.unlink(missing_ok=True)

    catalog = get_phrog_catalog()
    matched_count = 0
    for qid, p in query_items:
        hit = hits_map.get(qid)
        is_low_comp = _is_low_complexity_repeat_artifact(p.translation)
        if not hit or (is_low_comp and hit[1] < 250.0):
            # 若外部 .gbk / 注解自封了高影响结构角色但未通过独立 HMM 验证，显式标记为未核实文本声称
            if p.evidence_source not in ("pyrodigal", "pyhmmer_phrog", "phold_3d"):
                p.hmm_score = 0.0
                p.hmm_evalue = 1.0
                p.evidence_source = "unverified_text"
            continue

        ph_id, sc, ev = hit
        cat, ann = catalog.get_phrog_info(ph_id)
        ext_role, _ = classify_structural_role(p.raw_product or p.product)
        hmm_role, hmm_role_cn = classify_structural_role(ann, phrog_id=ph_id, phrog_category=cat)

        role_conflict = (ext_role != "OTHER" and hmm_role != "OTHER" and ext_role != hmm_role)
        # 若外部已给出明确结构角色，弱/中等交叉漂移 (<50分) 不强行改写，避免低特异性重复域误盖真注解
        if role_conflict and sc < 50.0 and not force_rescan:
            if p.evidence_source not in ("pyrodigal", "pyhmmer_phrog", "phold_3d"):
                p.hmm_score = 0.0
                p.hmm_evalue = 1.0
                p.evidence_source = "unverified_text"
            continue

        p.phrog_id = ph_id
        p.phrog_category = cat
        p.hmm_score = round(sc, 2)
        p.hmm_evalue = ev
        p.evidence_source = "pyhmmer_phrog"

        is_unannot = bool(_UNANNOTATED_RE.match(p.product or ""))
        if ann and (force_rescan or is_unannot or p.structural_role == "OTHER" or role_conflict):
            p.product = ann

        if ann or ph_id:
            role, role_cn = classify_structural_role(p.product if not role_conflict else ann, phrog_id=ph_id, phrog_category=cat)
        else:
            role, role_cn = hmm_role, hmm_role_cn
        p.structural_role = role
        p.role_label_cn = role_cn
        matched_count += 1

    return matched_count


def check_phold_ready() -> bool:
    """检查离线 Phold 3D 折叠数据库与 WSL CLI 是否就绪。"""
    phold_db = ToolConfig.get_db_dir("phold_db")
    if not (phold_db.is_dir() and (phold_db / "all_phold_structures").exists()):
        return False
    if not WSLManager.is_available():
        return False
    distro = WSLManager.get_best_distro()
    try:
        res = subprocess.run(
            ["wsl", "-d", distro, "bash", "-lc", "which phold"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def _cleanup_cuda_cache() -> None:
    gc.collect()
    try:
        import importlib
        torch = importlib.import_module("torch")
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


def enhance_with_phold_3d(
    contig_map: Dict[str, Dict[str, Any]],
    *,
    workers: int = 8,
    min_aa: int = 100,
    on_progress: Optional[Callable[[str], None]] = None,
) -> int:
    """
    可选调用 Phold AI (ProstT5 3Di + Foldseek) 对长未知假定蛋白 (>=100 aa) 开展三维构象补漏。
    严格限制 batch_size=1 并在调用前后清理物理显存，防止溢出。
    """
    if not check_phold_ready():
        logger.info("Phold 3D 离线环境未完全就绪，跳过三维结构补漏")
        return 0

    candidates: List[Tuple[str, StructureProteinItem]] = []
    for cid, info in contig_map.items():
        for p in info["proteins"]:
            is_unknown = bool(_UNANNOTATED_RE.match(p.product or "")) or p.structural_role == "OTHER"
            if is_unknown and p.translation and len(p.translation) >= min_aa:
                qid = f"{cid}||{p.locus_tag}"
                candidates.append((qid, p))

    if not candidates:
        return 0

    if on_progress:
        on_progress(f"正在调用 Phold 3D (ProstT5 + Foldseek) 解析 {len(candidates)} 条长暗物质蛋白...")

    _cleanup_cuda_cache()
    WSLManager.ensure_project_link()
    phold_db = ToolConfig.get_db_dir("phold_db")
    wsl_db = WSLManager.to_wsl_path(str(phold_db))

    work_dir = Path(tempfile.mkdtemp(prefix="pstruct_phold_"))
    faa_path = work_dir / "unknown_long.faa"
    pred_dir = work_dir / "pred_out"
    cmp_dir = work_dir / "cmp_out"

    updated_count = 0
    try:
        with faa_path.open("w", encoding="utf-8", newline="\n") as fh:
            for qid, p in candidates:
                fh.write(f">{qid}\n{p.translation}\n")

        wsl_faa = WSLManager.to_wsl_path(str(faa_path))
        wsl_pred = WSLManager.to_wsl_path(str(pred_dir))
        wsl_cmp = WSLManager.to_wsl_path(str(cmp_dir))
        distro = WSLManager.get_best_distro()

        cmd_str = (
            "export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 && "
            f"phold proteins-predict -i '{wsl_faa}' -o '{wsl_pred}' -d '{wsl_db}' -t {max(1, workers)} --batch_size 1 -f && "
            f"phold proteins-compare -i '{wsl_faa}' --predictions_dir '{wsl_pred}' -o '{wsl_cmp}' -d '{wsl_db}' -t {max(1, workers)} -f"
        )
        res = subprocess.run(
            ["wsl", "-d", distro, "bash", "-lc", cmd_str],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
        )
        if res.returncode != 0:
            logger.warning("Phold 3D 执行返回非零状态 (%s): %s", res.returncode, res.stderr[-300:])
            return 0

        pred_tsv = cmp_dir / "phold_per_cds_predictions.tsv"
        if not pred_tsv.is_file():
            # 兼容不同版本前缀
            found = list(cmp_dir.glob("*per_cds_predictions*.tsv"))
            if not found:
                return 0
            pred_tsv = found[0]

        phold_hits: Dict[str, Tuple[str, str, str, float, float]] = {}
        with pred_tsv.open("r", encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                cds_id = (row.get("cds_id") or "").strip()
                prod = (row.get("product") or "").strip()
                func = (row.get("function") or "").strip()
                ph_raw = (row.get("phrog") or "").strip()
                if not cds_id or not prod or _UNANNOTATED_RE.match(prod):
                    continue
                if ph_raw and ph_raw != "No_PHROG" and not ph_raw.startswith("phrog_"):
                    ph_raw = f"phrog_{ph_raw}"
                elif ph_raw == "No_PHROG":
                    ph_raw = ""
                try:
                    sc = float(row.get("bitscore") or 0.0)
                except ValueError:
                    sc = 0.0
                try:
                    ev = float(row.get("evalue") or 1.0)
                except ValueError:
                    ev = 1.0
                phold_hits[cds_id] = (ph_raw, func, prod, sc, ev)

        for qid, p in candidates:
            hit = phold_hits.get(qid)
            if not hit:
                continue
            ph_id, cat, prod, sc, ev = hit
            role, role_cn = classify_structural_role(prod, phrog_id=ph_id, phrog_category=cat)
            p.product = prod
            if ph_id:
                p.phrog_id = ph_id
            if cat:
                p.phrog_category = cat
            if sc > p.hmm_score:
                p.hmm_score = round(sc, 2)
                p.hmm_evalue = ev
            p.structural_role = role
            p.role_label_cn = role_cn
            p.evidence_source = "phold_3d"
            updated_count += 1
    except Exception as exc:
        logger.warning("Phold 3D 增强处理异常，已跳过回退至 PHROG HMM 结果: %s", exc)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        _cleanup_cuda_cache()

    return updated_count
