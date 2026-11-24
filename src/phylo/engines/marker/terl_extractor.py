# -*- coding: utf-8 -*-
"""
TerlExtractor - 第 3 步：大末端酶亚基 (TerL) 标志基因批量精准提取引擎
流程：
1. 动态扫描 database/pharokka_db/phrog_annot_v4.tsv 定位全部 terminase large subunit PHROG 编号（55 家族）；
2. 从 all_phrogs.h3m 一次性抽提并缓存轻量级 results/phylo/cache/terl_phrogs.hmm (+ hmmpress)；
3. 调用多核 prodigal-gv 并发预测所有候选基因组 ORF（结果按内容哈希缓存在 orf_cache/）；
4. 调用多核 hmmsearch --domtblout 精准识别每株最佳 TerL 蛋白，生成 ExtractionReport 与 terl_proteins.faa。
"""
import csv
import hashlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Tuple

from ...core.fasta_io import iter_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...models.schemas import MarkerExtractionReport, MarkerHitItem
from ...runtime.process_runner import ProcessRunner
from ...runtime.resource_guard import get_safe_cpu_budget
from ...runtime.tool_registry import get_project_root, get_tool_registry

logger = logging.getLogger("phylo.terl_extractor")


class TerlExtractor:
    """基于 PHROG Terminase Large Subunit HMM 的批量 TerL 提取引擎。"""

    MIN_TERL_AA_LEN = 150
    MAX_EVALUE = 1e-5

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )
        root = get_project_root()
        self.pharokka_db_dir = root / "database" / "pharokka_db"
        self.cache_root = root / "results" / "phylo" / "cache"
        self.orf_cache_dir = self.cache_root / "orf_cache"
        self.terl_hmm_path = self.cache_root / "terl_phrogs.hmm"

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def load_terl_phrog_names(self) -> set[str]:
        """从 phrog_annot_v4.tsv 中提取全部 terminase large subunit PHROG 模型名。"""
        tsv_path = self.pharokka_db_dir / "phrog_annot_v4.tsv"
        if not tsv_path.is_file():
            raise PhyloError(f"未找到 PHROG 注释表: {tsv_path}")
        names: set[str] = set()
        with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                annot = (row.get("annot") or "").lower()
                phrog_id = (row.get("phrog") or "").strip()
                if phrog_id and "terminase large subunit" in annot:
                    names.add(f"phrog_{phrog_id}")
        return names

    def ensure_terl_hmm_db(self) -> Path:
        """
        构建并缓存轻量级 TerL PHROGs HMM 子库（只抽取一次，不修改原始数据库目录）。
        """
        if (
            self.terl_hmm_path.is_file()
            and self.terl_hmm_path.stat().st_size > 1000
            and self.terl_hmm_path.with_suffix(".hmm.h3i").is_file()
        ):
            return self.terl_hmm_path

        all_h3m = self.pharokka_db_dir / "all_phrogs.h3m"
        if not all_h3m.is_file():
            raise PhyloError(f"未找到 Pharokka HMM 库: {all_h3m}")

        terl_names = self.load_terl_phrog_names()
        if not terl_names:
            raise PhyloError("未在 phrog_annot_v4.tsv 中定位到 terminase large subunit 条目")

        self.cache_root.mkdir(parents=True, exist_ok=True)
        tmp_hmm = self.terl_hmm_path.with_suffix(".hmm.tmp")
        self._log(f"[TerL-DB] 首次使用官方 hmmfetch 从 all_phrogs.h3m 抽提并索引 {len(terl_names)} 个 TerL PHROG HMM 模型...")

        hmmfetch_desc = self.registry.get("hmmfetch")
        hmmsearch_desc = self.registry.get("hmmsearch")
        hmmfetch_bin = (
            hmmfetch_desc.path
            if hmmfetch_desc.available
            else (str(PurePosixPath(hmmsearch_desc.path).with_name("hmmfetch")) if hmmsearch_desc.available else "hmmfetch")
        )
        hmmpress_bin = (
            str(PurePosixPath(hmmfetch_bin).with_name("hmmpress"))
            if "/" in hmmfetch_bin
            else "hmmpress"
        )

        # 写入 TerL 模型名清单至可写缓存目录，通过临时软链接在可写目录建立 .ssi 索引（绝不修改源库目录）
        names_txt = self.cache_root / "terl_phrog_names.txt"
        names_txt.write_text("\n".join(sorted(terl_names)) + "\n", encoding="utf-8", newline="\n")

        from src.assembly.env.wsl_manager import WSLManager
        import shlex

        wsl_src = WSLManager.to_wsl_path(str(all_h3m.resolve()))
        wsl_names = WSLManager.to_wsl_path(str(names_txt.resolve()))
        wsl_out_tmp = WSLManager.to_wsl_path(str(tmp_hmm.resolve()))

        bash_extract = (
            f"TMPD=$(mktemp -d)\n"
            f"trap 'rm -rf \"$TMPD\"' EXIT\n"
            f"ln -s {shlex.quote(wsl_src)} \"$TMPD/all.h3m\"\n"
            f"{shlex.quote(hmmfetch_bin)} --index \"$TMPD/all.h3m\" >/dev/null\n"
            f"hmmstat \"$TMPD/all.h3m\" | awk '!/^#/ && NF>=2 {{print $2}}' | sort -u > \"$TMPD/avail.txt\"\n"
            f"sort -u {shlex.quote(wsl_names)} > \"$TMPD/want.txt\"\n"
            f"comm -12 \"$TMPD/avail.txt\" \"$TMPD/want.txt\" > \"$TMPD/intersect.txt\"\n"
            f"{shlex.quote(hmmfetch_bin)} -f -o {shlex.quote(wsl_out_tmp)} \"$TMPD/all.h3m\" \"$TMPD/intersect.txt\" >/dev/null\n"
        )
        res_fetch = self.runner.run_wsl(["bash", "-c", bash_extract])
        if res_fetch.returncode != 0 or not tmp_hmm.is_file() or tmp_hmm.stat().st_size == 0:
            if tmp_hmm.exists():
                tmp_hmm.unlink()
            raise PhyloError(
                "hmmfetch 抽提 TerL PHROG HMM 子库失败",
                detail=res_fetch.stderr[-800:],
            )

        os.replace(tmp_hmm, self.terl_hmm_path)

        res = self.runner.run_wsl(
            [hmmpress_bin, "-f", WSLManager.to_wsl_path(str(self.terl_hmm_path.resolve()))]
        )
        if res.returncode != 0:
            raise PhyloError("hmmpress 索引 TerL HMM 子库失败", detail=res.stderr[-600:])

        self._log(f"[TerL-DB] 缓存就绪: 共抽取并索引 {len(terl_names)} 个 TerL 家族模型。")
        return self.terl_hmm_path

    def predict_orfs_batch(
        self,
        genome_fastas: Dict[str, Path],
        threads: int = 0,
    ) -> Dict[str, Path]:
        """
        多核并发调用 prodigal-gv 为全部噬菌体基因组预测蛋白序列（内容哈希缓存）。
        """
        prodigal_desc = self.registry.get("prodigal-gv")
        if not prodigal_desc.available:
            raise ToolUnavailableError("prodigal-gv", "prodigal-gv / prodigal 未安装")

        self.orf_cache_dir.mkdir(parents=True, exist_ok=True)
        safe_threads = get_safe_cpu_budget(threads)
        # 限制并发进程数防止 WSL 同时派生过多子进程
        max_workers = max(1, min(safe_threads, 8))

        from src.assembly.env.wsl_manager import WSLManager

        def _predict_one(sample_id: str, fpath: Path) -> Tuple[str, Path]:
            if self.cancel_event.is_set():
                raise PhyloCancelledError("ORF 预测已取消")
            raw_bytes = fpath.read_bytes()
            sha = hashlib.sha256(raw_bytes).hexdigest()[:24]
            cached_faa = self.orf_cache_dir / f"{sha}.faa"
            if cached_faa.is_file() and cached_faa.stat().st_size > 10:
                return sample_id, cached_faa

            tmp_faa = self.orf_cache_dir / f"{sha}.{threading.get_ident()}.tmp.faa"
            # 如果基因组较短 (< 20kb) 使用 -p meta 模式防止 prodigal 训练集不足报错
            seq_len = sum(len(r.seq) if r.seq is not None else 0 for r in iter_fasta_records(fpath))
            mode_flag = "meta" if seq_len < 20000 else "single"
            runner = ProcessRunner(
                cancel_event=self.cancel_event,
                wsl_distro=self.registry.wsl_distro or "Ubuntu",
            )
            cmd = [
                prodigal_desc.path,
                "-i",
                WSLManager.to_wsl_path(str(fpath.resolve())),
                "-a",
                WSLManager.to_wsl_path(str(tmp_faa.resolve())),
                "-p",
                mode_flag,
                "-q",
            ]
            res = runner.run_wsl(cmd)
            # 若 single 模式训练失败自动降级 -p meta 重试一次
            if (res.returncode != 0 or not tmp_faa.is_file() or tmp_faa.stat().st_size == 0) and mode_flag == "single":
                cmd[cmd.index("single")] = "meta"
                res = runner.run_wsl(cmd)
            if res.returncode != 0 or not tmp_faa.is_file():
                raise PhyloError(f"Prodigal-gv 预测 ORF 失败 ({sample_id})", detail=res.stderr[-600:])
            os.replace(tmp_faa, cached_faa)
            return sample_id, cached_faa

        orf_paths: Dict[str, Path] = {}
        self._log(f"[TerL-ORF] 开始批量预测 {len(genome_fastas)} 株基因组的编码蛋白 (并发={max_workers})...")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [pool.submit(_predict_one, sid, fp) for sid, fp in genome_fastas.items()]
            for fut in as_completed(futs):
                sid, faa = fut.result()
                orf_paths[sid] = faa
        return orf_paths

    def extract_terl(
        self,
        genome_fastas: Dict[str, Path],
        work_dir: Path,
        output_faa: Path,
        threads: int = 0,
    ) -> Tuple[Path, MarkerExtractionReport]:
        """
        完整执行 ORF 预测 -> 合并蛋白 -> hmmsearch 搜索 55 个 TerL PHROG -> 提取最佳 TerL 序列。
        """
        if self.cancel_event.is_set():
            raise PhyloCancelledError("TerL 提取前任务已取消")

        hmm_desc = self.registry.get("hmmsearch")
        if not hmm_desc.available:
            raise ToolUnavailableError("hmmsearch", f"hmmsearch 不可用: {hmm_desc.notes}")

        terl_hmm = self.ensure_terl_hmm_db()
        orf_paths = self.predict_orfs_batch(genome_fastas, threads=threads)

        work_dir.mkdir(parents=True, exist_ok=True)
        merged_orfs = work_dir / "all_predicted_orfs.faa"
        # 用纯 ASCII 短键 S0001__ORF_1 重命名头行确保跨基因组/中文 ID 零冲突且可 100% 精准回溯
        prot_seq_map: Dict[str, str] = {}
        key_to_sid: Dict[str, str] = {}
        with open(merged_orfs, "w", encoding="utf-8", newline="\n") as out_fh:
            for s_idx, (sid, faa_path) in enumerate(orf_paths.items(), start=1):
                s_key = f"S{s_idx:04d}"
                key_to_sid[s_key] = sid
                for idx, rec in enumerate(iter_fasta_records(faa_path), start=1):
                    clean_aa = str(rec.seq).replace("*", "").strip()
                    if len(clean_aa) < self.MIN_TERL_AA_LEN:
                        continue
                    uid = f"{s_key}__ORF_{idx}"
                    prot_seq_map[uid] = clean_aa
                    out_fh.write(f">{uid}\n{clean_aa}\n")

        if not prot_seq_map:
            raise PhyloError("未能从候选基因组中预测出有效长度的蛋白序列 (>= 150 aa)")

        tbl_out = work_dir / "terl_hmmsearch.tbl"
        safe_threads = get_safe_cpu_budget(threads)
        from src.assembly.env.wsl_manager import WSLManager

        cmd = [
            hmm_desc.path,
            "--cpu",
            str(safe_threads),
            "-E",
            str(self.MAX_EVALUE),
            "--tblout",
            WSLManager.to_wsl_path(str(tbl_out.resolve())),
            "-o",
            "/dev/null",
            WSLManager.to_wsl_path(str(terl_hmm.resolve())),
            WSLManager.to_wsl_path(str(merged_orfs.resolve())),
        ]
        self._log(f"[TerL-HMM] 启动 hmmsearch 搜索 55 个 TerL 家族 (E <= {self.MAX_EVALUE}, 线程={safe_threads})")
        res = self.runner.run_wsl(cmd)
        if res.returncode != 0 or not tbl_out.is_file():
            raise PhyloError("hmmsearch 搜索 TerL 失败", detail=res.stderr[-800:])

        # 解析 tblout，按 sample_id 分组统计所有命中（选最高 bitscore 作为代表，并标记多拷贝）
        hits_by_sample: Dict[str, List[Tuple[str, str, float, float]]] = {}
        with open(tbl_out, "r", encoding="utf-8", errors="replace") as tfh:
            for line in tfh:
                if not line.strip() or line.startswith("#"):
                    continue
                cols = line.split()
                if len(cols) < 6:
                    continue
                target_uid = cols[0].strip()
                query_phrog = cols[2].strip()
                try:
                    evalue = float(cols[4])
                    bitscore = float(cols[5])
                except ValueError:
                    continue
                if "__ORF_" not in target_uid:
                    continue
                s_key = target_uid.rsplit("__ORF_", 1)[0]
                sid = key_to_sid.get(s_key, s_key)
                hits_by_sample.setdefault(sid, []).append(
                    (target_uid, query_phrog, evalue, bitscore)
                )

        hit_items: List[MarkerHitItem] = []
        missing_ids: List[str] = []
        output_faa.parent.mkdir(parents=True, exist_ok=True)

        extracted_count = 0
        with open(output_faa, "w", encoding="utf-8", newline="\n") as out_fh:
            for sid in genome_fastas:
                cand_hits = hits_by_sample.get(sid, [])
                if not cand_hits:
                    missing_ids.append(sid)
                    hit_items.append(
                        MarkerHitItem(
                            sample_id=sid,
                            status="missing",
                            notes="未检测到满足 E-value 与长度 (>=150 aa) 要求的 TerL 同源蛋白",
                        )
                    )
                    continue

                cand_hits.sort(key=lambda x: (-x[3], x[2]))
                best_uid, best_phrog, best_ev, best_score = cand_hits[0]
                # 统计独立 ORF 命中个数
                distinct_orfs = {h[0] for h in cand_hits}
                status = "multi_copy" if len(distinct_orfs) > 1 else "extracted"
                aa_seq = prot_seq_map[best_uid]

                out_fh.write(f">{sid}\n")
                for pos in range(0, len(aa_seq), 80):
                    out_fh.write(aa_seq[pos : pos + 80] + "\n")
                extracted_count += 1

                hit_items.append(
                    MarkerHitItem(
                        sample_id=sid,
                        protein_id=best_uid,
                        phrog_id=best_phrog,
                        evalue=best_ev,
                        bitscore=round(best_score, 1),
                        aa_length=len(aa_seq),
                        status=status,  # type: ignore[arg-type]
                        notes=f"检测到 {len(distinct_orfs)} 个候选 TerL ORF，已取最高分 {best_phrog}"
                        if len(distinct_orfs) > 1
                        else f"精准匹配 {best_phrog}",
                    )
                )

        prodigal_ver = self.registry.get("prodigal-gv").version
        report = MarkerExtractionReport(
            mode="terl",
            total_genomes=len(genome_fastas),
            extracted_count=extracted_count,
            missing_ids=missing_ids,
            tool_used="prodigal-gv + hmmsearch (PHROGs TerL subset)",
            tool_version=f"{prodigal_ver} | {hmm_desc.version}".strip(" |"),
            hits=hit_items,
        )
        self._log(
            f"[TerL-Extract] 提取完成: {extracted_count}/{len(genome_fastas)} 株成功提取 TerL"
            + (f"，缺失 {len(missing_ids)} 株" if missing_ids else "")
        )
        return output_faa, report
