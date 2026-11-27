# -*- coding: utf-8 -*-
"""
PhageReferenceCurator - 第 2 步：噬菌体参考序列集策展与断点续传获取
严格执行：
1. 保留所有查询基因组 (role="query")；
2. 每个候选目标属 & 邻近属至少纳入 1-3 条正式 ICTV 分类代表株 (role="ictv_rep")；
3. 纳入高相似近邻 (role="neighbor") 与明确在目标类群之外的外群 (role="outgroup")；
4. 优先命中本地缓存 results/phylo/ref_cache/ 与自定义目录，缺失株经 NCBI E-utilities 断点续传下载；
5. 支持可选 CheckV (completeness >= 95%) 完整性筛选。
"""
import csv
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from ...core.fasta_io import iter_fasta_records, read_fasta_records
from ...models.errors import PhyloCancelledError
from ...models.schemas import AniScreenResult, DeliveryScopeConfig, ReferenceCandidate
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_project_root, get_tool_registry
from ..ani.inphared_index import InpharedIndex, get_inphared_index

logger = logging.getLogger("phylo.ref_curator")

EUTILS_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
SAFE_ACC_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_acc(acc: str) -> str:
    raw = (acc or "").strip()
    cleaned = SAFE_ACC_RE.sub("_", raw).strip("_")
    if cleaned != raw or not cleaned:
        suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
        return f"{cleaned}_{suffix}" if cleaned else f"seq_{suffix}"
    return cleaned


class PhageReferenceCurator:
    """噬菌体参考集自动组装与本地缓存/NCBI 断点下载器。"""

    def __init__(
        self,
        index: Optional[InpharedIndex] = None,
        cache_dir: Optional[Path] = None,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.index = index or get_inphared_index()
        root = get_project_root()
        self.cache_dir = cache_dir or (root / "results" / "phylo" / "ref_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception as _exc:
                logger.debug("PhageReferenceCurator 日志回调执行失败: %s", _exc)

    def curate_candidates(
        self,
        query_records: List[Tuple[str, str]],
        ani_result: Optional[AniScreenResult],
        scope: DeliveryScopeConfig,
    ) -> List[ReferenceCandidate]:
        """根据第 1 步 ANI 预判结果和第 0 步边界参数生成带角色标记的候选参考集。"""
        candidates: List[ReferenceCandidate] = []
        seen_acc: set[str] = set()

        # 1. 查询基因组 (不可剔除)
        for qid, qseq in query_records:
            clean_seq = qseq.strip().upper()
            gc = 0.0
            if clean_seq:
                gc = round(((clean_seq.count("G") + clean_seq.count("C")) / len(clean_seq)) * 100.0, 2)
            candidates.append(
                ReferenceCandidate(
                    accession=qid,
                    name=qid,
                    role="query",
                    source="workspace",
                    selected=True,
                    genome_length=len(clean_seq),
                    gc_content=gc,
                    is_ictv_classified=False,
                )
            )
            seen_acc.add(qid)

        manual_og = list(dict.fromkeys(x.strip() for x in scope.outgroup_ids if x and x.strip()))
        manual_og_set = set(manual_og)

        # 2. 扫描本地自定义离线参考目录 (若有)
        if scope.local_ref_dir:
            local_dir = Path(scope.local_ref_dir)
            if local_dir.is_dir():
                for fp in sorted(local_dir.iterdir()):
                    if not fp.is_file() or fp.suffix.lower() not in (".fasta", ".fas", ".fa", ".fna"):
                        continue
                    recs = read_fasta_records(fp)
                    for rec in recs:
                        raw_id = (rec.id or "").strip()
                        acc = raw_id if (len(recs) > 1 and raw_id) else fp.stem
                        if acc in seen_acc:
                            continue
                        seen_acc.add(acc)
                        candidates.append(
                            ReferenceCandidate(
                                accession=acc,
                                name=acc,
                                role="outgroup" if acc in manual_og_set else "neighbor",
                                source="local_dir",
                                selected=True,
                                genome_length=len(rec.seq) if rec.seq is not None else 0,
                                local_path=str(fp.resolve()),
                            )
                        )

        # 3. 纳入外群 (优先用户手动指定，再按 outgroup_count 额度自动补足推荐外群)
        target_genera: List[str] = []
        target_families: List[str] = []
        auto_og_pool: List[str] = []
        if ani_result:
            base_genera = max(1, scope.max_target_genera)
            target_genera = list(ani_result.candidate_genera[:base_genera])
            target_families = list(ani_result.candidate_families[:2])
            if ani_result.ambiguous_zone:
                # 65%-75% 模糊带时扩充至更多邻近属以展示边缘拓扑位置
                target_genera = list(
                    ani_result.candidate_genera[: min(200, max(base_genera, base_genera * 2))]
                )
            auto_og_pool = list(ani_result.recommended_outgroup_accessions)

        need_auto = max(0, scope.outgroup_count - len(manual_og))
        if need_auto > len(auto_og_pool) and self.index.is_available() and (target_genera or target_families):
            extra_ogs = self.index.find_outgroup_candidates(
                target_genera=target_genera[:3],
                target_families=target_families[:2],
                exclude_accessions=[h.accession for h in ani_result.top_hits[:15]] + manual_og if ani_result else manual_og,
                limit=scope.outgroup_count,
            )
            for og in extra_ogs:
                if og.accession not in auto_og_pool:
                    auto_og_pool.append(og.accession)

        outgroup_accs = list(dict.fromkeys(manual_og + auto_og_pool[:need_auto]))
        outgroup_meta = (
            self.index.get_by_accessions(outgroup_accs)
            if outgroup_accs and self.index.is_available()
            else {}
        )
        for og_acc in outgroup_accs:
            if og_acc in seen_acc:
                continue
            seen_acc.add(og_acc)
            meta = outgroup_meta.get(og_acc)
            candidates.append(
                ReferenceCandidate(
                    accession=og_acc,
                    name=f"{og_acc} ({meta.genus})" if meta and meta.genus else og_acc,
                    description=meta.description if meta else "",
                    role="outgroup",
                    source="inphared_cache" if (self.cache_dir / f"{_safe_acc(og_acc)}.fasta").is_file() else "ncbi_download",
                    selected=True,
                    genome_length=meta.genome_length if meta else 0,
                    gc_content=meta.gc_content if meta else 0.0,
                    host=meta.host if meta else "",
                    genus=meta.genus if meta else "",
                    family=meta.family if meta else "",
                    order=meta.order_name if meta else "",
                    is_ictv_classified=bool(meta and meta.is_ictv_classified),
                )
            )

        if ani_result:
            def _append_ictv_reps(per_genus_limit: int, max_rep_cap: int) -> None:
                if len(candidates) >= scope.ref_max_count or max_rep_cap <= 0 or per_genus_limit <= 0:
                    return
                ictv_reps = self.index.find_ictv_representatives(
                    genera=target_genera,
                    families=target_families,
                    exclude_accessions=list(seen_acc),
                    per_genus=per_genus_limit,
                    max_total=max_rep_cap,
                )
                for rep in ictv_reps:
                    if rep.accession in seen_acc or len(candidates) >= scope.ref_max_count:
                        continue
                    seen_acc.add(rep.accession)
                    candidates.append(
                        ReferenceCandidate(
                            accession=rep.accession,
                            name=f"{rep.accession} ({rep.genus})" if rep.genus else rep.accession,
                            description=rep.description,
                            role="ictv_rep",
                            source="inphared_cache" if (self.cache_dir / f"{_safe_acc(rep.accession)}.fasta").is_file() else "ncbi_download",
                            selected=True,
                            genome_length=rep.genome_length,
                            gc_content=rep.gc_content,
                            host=rep.host,
                            genus=rep.genus,
                            family=rep.family,
                            order=rep.order_name,
                            is_ictv_classified=rep.is_ictv_classified,
                        )
                    )

            def _append_top_hits() -> None:
                for hit in ani_result.top_hits:
                    if len(candidates) >= scope.ref_max_count:
                        break
                    if hit.accession in seen_acc:
                        continue
                    seen_acc.add(hit.accession)
                    is_rep = bool(hit.genus)
                    candidates.append(
                        ReferenceCandidate(
                            accession=hit.accession,
                            name=f"{hit.accession} ({hit.genus})" if hit.genus else hit.accession,
                            description=hit.description,
                            role="ictv_rep" if is_rep else "neighbor",
                            source="inphared_cache" if (self.cache_dir / f"{_safe_acc(hit.accession)}.fasta").is_file() else "ncbi_download",
                            selected=True,
                            genome_length=hit.genome_length,
                            gc_content=hit.gc_content,
                            host=hit.host,
                            genus=hit.genus,
                            family=hit.family,
                            order=hit.order,
                            wg_ani=hit.wg_ani if hit.wg_ani > 0 else hit.mash_ani,
                            is_ictv_classified=is_rep,
                        )
                    )

            if scope.target_rank == "species":
                # 种内精细分辨模式：先确保目标属有轻量 ICTV 核心锚点，随后优先倾斜配额给高相似同种与近缘株
                anchor_cap = max(2, int(scope.ref_max_count * 0.25))
                _append_ictv_reps(min(scope.ictv_reps_per_genus, 2), anchor_cap)
                _append_top_hits()
                remaining = scope.ref_max_count - len(candidates)
                if remaining > 0:
                    _append_ictv_reps(scope.ictv_reps_per_genus, remaining)
            else:
                max_rep_total = (
                    max(1, scope.ref_max_count - len(candidates))
                    if scope.ref_max_count < 15
                    else max(10, int(scope.ref_max_count * 0.7))
                )
                _append_ictv_reps(scope.ictv_reps_per_genus, max_rep_total)
                _append_top_hits()

        # 7. 宏观分层抽样模式：补足跨病毒科 × 跨宿主门千株级背景参考集（无 ANI 结果时同样可用）
        if (
            scope.sampling_mode == "macro_family_host"
            and len(candidates) < scope.ref_max_count
            and self.index.is_available()
        ):
            need_macro = scope.ref_max_count - len(candidates)
            macro_min_len = max(5000, min(scope.derep_min_len, 15000))
            macro_recs = self.index.sample_macro_background(
                target_count=need_macro,
                exclude_accessions=list(seen_acc),
                preferred_families=target_families,
                min_genome_length=macro_min_len,
            )
            for rec in macro_recs:
                if rec.accession in seen_acc or len(candidates) >= scope.ref_max_count:
                    continue
                seen_acc.add(rec.accession)
                candidates.append(
                    ReferenceCandidate(
                        accession=rec.accession,
                        name=f"{rec.accession} ({rec.genus})" if rec.genus else rec.accession,
                        description=rec.description,
                        role="ictv_rep" if rec.is_ictv_classified else "neighbor",
                        source=(
                            "inphared_cache"
                            if (self.cache_dir / f"{_safe_acc(rec.accession)}.fasta").is_file()
                            else "ncbi_download"
                        ),
                        selected=True,
                        genome_length=rec.genome_length,
                        gc_content=rec.gc_content,
                        host=rec.host,
                        genus=rec.genus,
                        family=rec.family,
                        order=rec.order_name,
                        is_ictv_classified=rec.is_ictv_classified,
                    )
                )

        return candidates

    def fetch_genomes(
        self,
        candidates: List[ReferenceCandidate],
        query_fasta_dir: Path,
        query_records: List[Tuple[str, str]],
        work_dir: Path,
        batch_size: int = 20,
    ) -> Tuple[Dict[str, Path], List[str]]:
        """
        将勾选的查询株与参考株全基因组 FASTA 汇总为独立单株文件并落盘至 results/phylo/ref_cache/。
        缺失的 INPHARED Accession 自动从 NCBI E-utilities 分批断点下载。
        返回: ({accession: fasta_path}, 告警信息列表)
        """
        genome_paths: Dict[str, Path] = {}
        warnings: List[str] = []
        query_map = {qid: qseq for qid, qseq in query_records}

        query_fasta_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = work_dir / "fetch_checkpoint.json"
        failed_accs: set[str] = set()
        if ckpt_path.is_file():
            try:
                failed_accs = set(json.loads(ckpt_path.read_text(encoding="utf-8")).get("failed", []))
            except Exception:
                failed_accs = set()

        to_download: List[ReferenceCandidate] = []
        for cand in candidates:
            if not cand.selected:
                continue
            if self.cancel_event.is_set():
                raise PhyloCancelledError("参考基因组获取阶段已取消")

            if cand.role == "query" or cand.accession in query_map:
                qseq = query_map.get(cand.accession, "")
                if not qseq:
                    continue
                q_out = query_fasta_dir / f"{_safe_acc(cand.accession)}.fasta"
                self._write_single_fasta(q_out, cand.accession, qseq)
                genome_paths[cand.accession] = q_out
                continue

            if cand.local_path and Path(cand.local_path).is_file():
                genome_paths[cand.accession] = Path(cand.local_path)
                continue

            cached_fa = self.cache_dir / f"{_safe_acc(cand.accession)}.fasta"
            if cached_fa.is_file() and cached_fa.stat().st_size > 100:
                cand.source = "inphared_cache"
                cand.local_path = str(cached_fa)
                genome_paths[cand.accession] = cached_fa
                continue

            if cand.accession not in failed_accs:
                to_download.append(cand)

        if to_download:
            self._log(
                f"[RefCurator] 本地缓存未命中 {len(to_download)} 条参考基因组，开始通过 NCBI E-utilities 分批断点获取..."
            )
            for start in range(0, len(to_download), batch_size):
                if self.cancel_event.is_set():
                    raise PhyloCancelledError("参考基因组下载已取消")
                batch = to_download[start : start + batch_size]
                batch_accs = [c.accession for c in batch]
                fetched = self._efetch_fasta_batch(batch_accs)
                for cand in batch:
                    seq_txt = fetched.get(cand.accession) or fetched.get(cand.accession.split(".")[0])
                    if seq_txt:
                        dest = self.cache_dir / f"{_safe_acc(cand.accession)}.fasta"
                        self._write_single_fasta(dest, cand.accession, seq_txt)
                        cand.source = "ncbi_download"
                        cand.local_path = str(dest)
                        genome_paths[cand.accession] = dest
                    else:
                        failed_accs.add(cand.accession)
                        warnings.append(f"参考株 {cand.accession} 从 NCBI 获取失败，已跳过。")
                ckpt_path.write_text(
                    json.dumps({"failed": sorted(failed_accs)}, ensure_ascii=False),
                    encoding="utf-8",
                )
                done_cnt = min(start + batch_size, len(to_download))
                batch_idx = start // batch_size
                if len(to_download) <= 40 or batch_idx % 3 == 2 or done_cnt == len(to_download):
                    self._log(
                        f"[RefCurator] 下载进度: {done_cnt}/{len(to_download)} (累计就绪 {len(genome_paths)} 株)"
                    )
                if start + batch_size < len(to_download):
                    time.sleep(0.4)

        return genome_paths, warnings

    def filter_by_checkv(
        self,
        genome_paths: Dict[str, Path],
        candidates: List[ReferenceCandidate],
        work_dir: Path,
        min_completeness: float = 95.0,
        threads: int = 0,
    ) -> Tuple[Dict[str, Path], List[str]]:
        """可选运行 CheckV 过滤不完整参考基因组（查询株和明确外群豁免过滤）。"""
        desc = self.registry.get("checkv")
        root = get_project_root()
        checkv_db = root / "database" / "checkv_db"
        if not desc.available or not checkv_db.is_dir():
            return genome_paths, ["CheckV 或数据库未就绪，已跳过完整性检查。"]

        # 查找包含 checkv_db 内部版本子目录
        db_target = checkv_db
        for sub in checkv_db.iterdir():
            if sub.is_dir() and (sub / "hmm_db").is_dir():
                db_target = sub
                break

        protected = {c.accession for c in candidates if c.role in ("query", "outgroup")}
        check_targets = [acc for acc in genome_paths if acc not in protected]
        if not check_targets:
            return genome_paths, []

        from src.assembly.env.wsl_manager import WSLManager

        cv_dir = work_dir / "checkv_run"
        cv_dir.mkdir(parents=True, exist_ok=True)
        combined = cv_dir / "refs_for_checkv.fasta"
        # 为 check_targets 建立纯 ASCII 临时键映射，避免本地中文/特殊字符样本名干扰 CheckV TSV 解析
        target_to_ascii: Dict[str, str] = {acc: f"CV{idx:04d}" for idx, acc in enumerate(check_targets, start=1)}
        ascii_to_target: Dict[str, str] = {v: k for k, v in target_to_ascii.items()}
        with open(combined, "w", encoding="utf-8", newline="\n") as out_fh:
            for acc in check_targets:
                ascii_id = target_to_ascii[acc]
                for rec in iter_fasta_records(genome_paths[acc]):
                    out_fh.write(f">{ascii_id}\n{str(rec.seq)}\n")
                    break

        safe_threads = get_safe_cpu_budget(threads)
        cmd = [
            desc.path,
            "end_to_end",
            WSLManager.to_wsl_path(str(combined.resolve())),
            WSLManager.to_wsl_path(str(cv_dir.resolve())),
            "-d",
            WSLManager.to_wsl_path(str(db_target.resolve())),
            "-t",
            str(safe_threads),
        ]
        self._log(f"[CheckV] 执行基因组完整性评估 (阈值 >= {min_completeness}%), 线程={safe_threads}")
        res = self.runner.run_wsl(cmd, stream_stdout_to_log=True)
        quality_tsv = cv_dir / "quality_summary.tsv"
        if res.returncode != 0 or not quality_tsv.is_file():
            return genome_paths, ["CheckV 执行异常或未生成报告，已保留当前参考集继续执行。"]

        comp_map: Dict[str, float] = {}
        with open(quality_tsv, "r", encoding="utf-8", errors="replace") as qfh:
            reader = csv.DictReader(qfh, delimiter="\t")
            for row in reader:
                cid = (row.get("contig_id") or "").strip()
                try:
                    comp = float(row.get("completeness") or 0.0)
                except ValueError:
                    comp = 0.0
                if cid:
                    orig_acc = ascii_to_target.get(cid, cid)
                    comp_map[orig_acc] = comp

        filtered = dict(genome_paths)
        dropped: List[str] = []
        cand_map = {c.accession: c for c in candidates}
        for acc in check_targets:
            comp = comp_map.get(acc)
            if acc in cand_map and comp is not None:
                cand_map[acc].completeness = round(comp, 1)
            if comp is not None and comp < min_completeness:
                filtered.pop(acc, None)
                if acc in cand_map:
                    cand_map[acc].selected = False
                dropped.append(f"{acc} ({comp:.1f}%)")

        warns = []
        if dropped:
            warns.append(
                f"CheckV 过滤了 {len(dropped)} 条完整度低于 {min_completeness}% 的参考基因组: "
                + ", ".join(dropped[:8])
            )
        return filtered, warns

    @staticmethod
    def _write_single_fasta(dest: Path, header: str, seq: str) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".fasta.tmp")
        clean = seq.replace("\n", "").replace("\r", "").strip().upper()
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f">{header}\n")
            for pos in range(0, len(clean), 80):
                fh.write(clean[pos : pos + 80] + "\n")
        tmp.replace(dest)

    def _efetch_fasta_batch(self, accessions: List[str], retries: int = 3) -> Dict[str, str]:
        if not accessions:
            return {}
        params = {
            "db": "nuccore",
            "id": ",".join(accessions),
            "rettype": "fasta",
            "retmode": "text",
        }
        for attempt in range(retries):
            if self.cancel_event.is_set():
                raise PhyloCancelledError("NCBI 下载已取消")
            try:
                resp = requests.get(EUTILS_EFETCH, params=params, timeout=30)
                if resp.status_code == 200 and ">" in resp.text:
                    return self._parse_multifasta_text(resp.text)
            except Exception as exc:
                logger.warning(f"NCBI efetch 尝试 {attempt + 1}/{retries} 失败: {exc}")
            time.sleep(1.0 * (2**attempt))
        return {}

    @staticmethod
    def _parse_multifasta_text(text: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        cur_id: Optional[str] = None
        chunks: List[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_id and chunks:
                    seq = "".join(chunks)
                    out[cur_id] = seq
                    out[cur_id.split(".")[0]] = seq
                cur_id = line[1:].split()[0]
                chunks = []
            else:
                chunks.append(line)
        if cur_id and chunks:
            seq = "".join(chunks)
            out[cur_id] = seq
            out[cur_id.split(".")[0]] = seq
        return out
