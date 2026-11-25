# -*- coding: utf-8 -*-
"""
PhageTaxonomyWorkflow - 第 0-8 步噬菌体分类鉴定与发表级建树科研流水线编排器
串联：
  Step 0-1: INPHARED Mash 初筛 -> VIRIDIC-wgANI 精算矩阵与 ICTV 阈值预判
  Step 2:   参考集策展 (ICTV代表 + 邻近属 + 外群) -> 缓存/NCBI 断点下载 -> 可选 CheckV -> dRep 去冗余 -> Treemmer 降采样
  Step 3:   标志基因 TerL 批量精准提取 (55 PHROGs HMM) 或备选全基因组蛋白质组树 (DIAMOND S_G)
  Step 4:   MAFFT (L-INS-i / E-INS-i / --auto) + ClipKIT (-m kpic) 位点修剪
  Step 5:   IQ-TREE 3/2 (-m MFP -B 1000 -bnni -alrt 1000 --seed 42) + 外群定根 + BIC 追踪
  Step 6-8: 双支持值与 ANI-树拓扑一致性质检 -> iTOL 全套模板生成 -> 交付 ZIP 归档
"""
import hashlib
import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.checkpoint import CheckpointManager, StageCache
from ..core.fasta_io import iter_fasta_records, read_fasta_records
from ..core.id_codec import IdCodec
from ..core.profiler import SequenceProfiler
from ..delivery.bundle_exporter import DeliveryBundleExporter
from ..delivery.itol_generator import ItolTemplateGenerator
from ..delivery.label_formatter import clean_phage_description, enrich_node_metadata
from ..delivery.publication_renderer import PublicationTreeRenderer
from ..delivery.qc_auditor import PhageDeliveryQcAuditor
from ..engines.ani.inphared_index import InpharedRecord
from ..engines.ani.mash_screener import MashScreener
from ..engines.ani.viridic_ani import ViridicAniCalculator
from ..engines.marker.proteome_tree import ProteomeTreeEngine
from ..engines.marker.terl_extractor import TerlExtractor
from ..engines.msa.aligner import MultiSequenceAligner
from ..engines.reference.dereplicator import PhageDereplicator
from ..engines.reference.ref_curator import PhageReferenceCurator
from ..engines.reference.treemmer_pruner import TreemmerPruner
from ..engines.tree.fasttree import FastTreeEngine
from ..engines.tree.iqtree import IQTreeEngine
from ..engines.trimmer import AlignmentTrimmer
from ..models.errors import InvalidInputError, PhyloCancelledError, PhyloError
from ..models.schemas import (
    AniEngineType,
    AniScreenResult,
    DeliveryScopeConfig,
    PhyloJobConfig,
    PhyloJobRecord,
    PublicationFigureRequest,
    ReferenceCandidate,
)
from .postprocess import compute_tree_metrics, extract_leaf_names, reroot_midpoint, reroot_outgroup

logger = logging.getLogger("phylo.phage_workflow")


def _select_publication_layouts(leaf_count: int) -> Tuple[str, ...]:
    """根据真实叶节点数决定自动离线渲染的发表级布局组合。"""
    if leaf_count > 60:
        return ("composite", "circular", "rectangular")
    return ("circular", "rectangular")


def _write_query_multifasta(records: List[Tuple[str, str]], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dedup_ids = IdCodec.deduplicate_ids([r[0] for r in records])
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        for qid, (_raw_id, seq) in zip(dedup_ids, records, strict=True):
            clean = seq.replace("*", "").strip().upper()
            fh.write(f">{qid}\n")
            for pos in range(0, len(clean), 80):
                fh.write(clean[pos : pos + 80] + "\n")
    return dest


def run_ani_screening(
    query_records: List[Tuple[str, str]],
    scope: DeliveryScopeConfig,
    ani_engine: AniEngineType,
    work_dir: Path,
    threads: int = 0,
    cancel_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    set_runner: Optional[Callable[[Any], None]] = None,
) -> AniScreenResult:
    """独立执行第 1 步 ANI 预判（Mash 全库初筛 + 下载 Top 近邻精算 VIRIDIC-wgANI/FastANI/skani）。"""
    cancel_ev = cancel_event or threading.Event()
    work_dir.mkdir(parents=True, exist_ok=True)

    dedup_ids = IdCodec.deduplicate_ids([r[0] for r in query_records])
    norm_queries = [(qid, r[1]) for qid, r in zip(dedup_ids, query_records, strict=True)]
    query_fa = _write_query_multifasta(norm_queries, work_dir / "queries.fasta")

    screener = MashScreener(cancel_event=cancel_ev, on_log=on_log)
    if set_runner:
        set_runner(screener)
    mash_hits, mash_cmd = screener.screen_against_inphared(
        query_fasta=query_fa,
        work_dir=work_dir,
        top_k=scope.mash_top_k,
        threads=threads,
    )
    if set_runner:
        set_runner(None)

    mash_map: Dict[str, Tuple[float, float, Optional[InpharedRecord]]] = {
        h.ref_accession: (round(h.distance, 4), h.mash_ani, h.meta) for h in mash_hits
    }

    # 为避免预判阶段一次性下载过多序列耗时过长，选取 Mash Top-15 与当地参考进行精算矩阵
    curator = PhageReferenceCurator(cancel_event=cancel_ev, on_log=on_log)
    screen_cands: List[ReferenceCandidate] = []
    for qid, qseq in norm_queries:
        screen_cands.append(
            ReferenceCandidate(
                accession=qid,
                name=qid,
                role="query",
                source="workspace",
                selected=True,
                genome_length=len(qseq),
            )
        )
    # 若提供本地离线参考目录也纳入预判
    if scope.local_ref_dir and Path(scope.local_ref_dir).is_dir():
        for fp in sorted(Path(scope.local_ref_dir).iterdir())[:20]:
            if fp.is_file() and fp.suffix.lower() in (".fasta", ".fas", ".fa", ".fna"):
                recs = read_fasta_records(fp)
                for rec in recs:
                    raw_id = (rec.id or "").strip()
                    acc = raw_id if (len(recs) > 1 and raw_id) else fp.stem
                    if acc not in {c.accession for c in screen_cands}:
                        screen_cands.append(
                            ReferenceCandidate(
                                accession=acc,
                                name=acc,
                                role="neighbor",
                                source="local_dir",
                                selected=True,
                                genome_length=len(rec.seq) if rec.seq is not None else 0,
                                local_path=str(fp.resolve()),
                            )
                        )

    for h in mash_hits[:15]:
        if h.ref_accession in {c.accession for c in screen_cands}:
            continue
        meta = h.meta
        screen_cands.append(
            ReferenceCandidate(
                accession=h.ref_accession,
                name=h.ref_accession,
                role="ictv_rep" if meta and meta.is_ictv_classified else "neighbor",
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

    genome_paths, fetch_warnings = curator.fetch_genomes(
        candidates=screen_cands,
        query_fasta_dir=work_dir / "query_fastas",
        query_records=norm_queries,
        work_dir=work_dir,
    )

    viridic = ViridicAniCalculator(cancel_event=cancel_ev, on_log=on_log)
    if set_runner:
        set_runner(viridic)

    if len(genome_paths) >= 2 and ani_engine != "mash":
        labels, wgani_mat, af_mat, pair_details, eng_ver, ani_cmd = viridic.compute_matrix_from_fastas(
            genome_fastas=genome_paths,
            work_dir=work_dir,
            engine=ani_engine,
            threads=threads,
        )
        cmd_preview = f"{mash_cmd} && {ani_cmd}".strip(" &")
        actual_eng = ani_engine
    else:
        labels = [c.accession for c in screen_cands if c.accession in genome_paths or c.role == "neighbor"][:16]
        n = len(labels)
        wgani_mat = [[0.0] * n for _ in range(n)]
        af_mat = [[0.0] * n for _ in range(n)]
        pair_details = {}
        for i in range(n):
            wgani_mat[i][i] = 100.0
            af_mat[i][i] = 100.0
            for j in range(i + 1, n):
                a, b = labels[i], labels[j]
                if a in dedup_ids and b in mash_map:
                    mani = mash_map[b][1]
                    wgani_mat[i][j] = wgani_mat[j][i] = mani
                    pair_details[(a, b)] = (mani, mani, 0.0, 0.0)
                elif b in dedup_ids and a in mash_map:
                    mani = mash_map[a][1]
                    wgani_mat[i][j] = wgani_mat[j][i] = mani
                    pair_details[(b, a)] = (mani, mani, 0.0, 0.0)
        eng_ver = "Mash-fallback"
        cmd_preview = mash_cmd
        actual_eng = "mash"

    if set_runner:
        set_runner(None)

    result = viridic.build_screen_result(
        query_ids=dedup_ids,
        mash_hits_map=mash_map,
        matrix_labels=labels,
        wgani_matrix=wgani_mat,
        af_matrix=af_mat,
        pair_details=pair_details,
        scope=scope,
        engine_used=actual_eng,
        engine_version=eng_ver,
        command_preview=cmd_preview,
    )
    if fetch_warnings:
        result.warnings.extend(fetch_warnings)
    return result


class PhageTaxonomyWorkflow:
    """在 PhyloJobExecutor 线程内执行完整 8 步噬菌体分类鉴定与交付。"""

    @staticmethod
    def execute(
        record: PhyloJobRecord,
        records: List[Tuple[str, str]],
        job_dir: Path,
        ckp: CheckpointManager,
        cache: StageCache,
        cancel_ev: threading.Event,
        log_fn: Callable[[str], None],
        stage_fn: Callable[..., None],
        set_runner: Callable[[Any], None],
    ) -> None:
        cfg: PhyloJobConfig = record.config
        scope = cfg.phage_scope or DeliveryScopeConfig()
        dedup_ids = IdCodec.deduplicate_ids([r[0] for r in records])
        norm_queries = [(qid, r[1]) for qid, r in zip(dedup_ids, records, strict=True)]
        commands_used: List[str] = []

        # ─── Stage 1: ANI 快速预判 (若前端已运行预判且查询集一致则直接复用) ─────
        t1 = time.time()
        ani_dir = job_dir / "step1_ani"
        ani_json_path = job_dir / "ani_screen.json"
        pre = cfg.precomputed_ani_result
        if pre is not None and set(pre.query_ids) == set(dedup_ids):
            ani_result = pre
            record.ani_result = ani_result
            if ani_result.command_preview:
                commands_used.append(ani_result.command_preview)
            ani_json_path.write_text(
                json.dumps(ani_result.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            record.artifacts["ani_json"] = str(ani_json_path)
            log_fn("[ANI 复用] 已直接复用第 1 步预判的 Mash + VIRIDIC-wgANI 矩阵，跳过重复全库扫描。")
            stage_fn(
                "ani_screen",
                "cached",
                25,
                "已复用第 1 步 ANI 预判结果",
                cached=True,
                elapsed=time.time() - t1,
                artifact=str(ani_json_path),
            )
        else:
            stage_fn("ani_screen", "running", 12, "第 1 步：执行 INPHARED Mash 初筛与 VIRIDIC-wgANI 预判...")
            ani_result = run_ani_screening(
                query_records=norm_queries,
                scope=scope,
                ani_engine=cfg.ani_engine,
                work_dir=ani_dir,
                threads=cfg.threads,
                cancel_event=cancel_ev,
                on_log=log_fn,
                set_runner=set_runner,
            )
            record.ani_result = ani_result
            if ani_result.command_preview:
                commands_used.append(ani_result.command_preview)
            ani_json_path.write_text(
                json.dumps(ani_result.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            record.artifacts["ani_json"] = str(ani_json_path)
            log_fn(f"[ANI 结论] {ani_result.summary_call}")
            for w in ani_result.warnings:
                log_fn(f"[ANI 提示] {w}")
            stage_fn("ani_screen", "completed", 25, "ANI 预判完成", elapsed=time.time() - t1, artifact=str(ani_json_path))

        if cancel_ev.is_set():
            raise PhyloCancelledError("任务在 ANI 预判后已取消")

        # ─── Stage 2: 构建参考序列集、获取、去冗余与 Treemmer 降采样 ─────────────
        t2 = time.time()
        stage_fn("curate_derep", "running", 32, "第 2 步：组装代表性参考集、去冗余与外群校准...")
        curator = PhageReferenceCurator(cancel_event=cancel_ev, on_log=log_fn)
        candidates = (
            list(cfg.selected_references)
            if cfg.selected_references
            else curator.curate_candidates(norm_queries, ani_result, scope)
        )
        # 确保前端指定外群生效
        for og in cfg.outgroup_ids:
            for c in candidates:
                if c.accession == og:
                    c.role = "outgroup"
                    c.selected = True

        # 回填 ANI top_hits 元数据
        ani_hit_map = {h.accession: h for h in ani_result.top_hits}
        for c in candidates:
            if c.accession in ani_hit_map:
                h = ani_hit_map[c.accession]
                if c.wg_ani is None:
                    c.wg_ani = h.wg_ani or h.mash_ani
                if not c.genus:
                    c.genus = h.genus
                if not c.family:
                    c.family = h.family
                if not c.host:
                    c.host = h.host

        ref_dir = job_dir / "step2_references"
        set_runner(curator)
        genome_paths, fetch_warns = curator.fetch_genomes(
            candidates=candidates,
            query_fasta_dir=ref_dir / "queries",
            query_records=norm_queries,
            work_dir=ref_dir,
        )
        for fw in fetch_warns:
            log_fn(f"[参考获取] {fw}")

        if scope.enable_checkv:
            genome_paths, cv_warns = curator.filter_by_checkv(
                genome_paths=genome_paths,
                candidates=candidates,
                work_dir=ref_dir,
                min_completeness=scope.checkv_min_completeness,
                threads=cfg.threads,
            )
            for cw in cv_warns:
                log_fn(f"[CheckV] {cw}")
        set_runner(None)

        if len(genome_paths) < 3:
            raise InvalidInputError(
                f"有效可用基因组不足 3 条（当前仅获取 {len(genome_paths)} 条），请检查网络、本地参考目录或调整筛选条件。"
            )

        # 去冗余 (dRep / 等效聚类)
        derep = PhageDereplicator(cancel_event=cancel_ev, on_log=log_fn)
        set_runner(derep)
        ani_mat_tuple = (
            (ani_result.matrix_labels, ani_result.wgani_matrix)
            if ani_result.matrix_labels and ani_result.wgani_matrix
            else None
        )
        genome_paths, derep_stats = derep.dereplicate(
            genome_paths=genome_paths,
            candidates=candidates,
            work_dir=ref_dir,
            pa_threshold=scope.derep_ani,
            min_length=scope.derep_min_len,
            threads=cfg.threads,
            ani_matrix=ani_mat_tuple,
        )
        set_runner(None)
        log_fn(f"[去冗余] {derep_stats['tool']}: {derep_stats['before']} -> {derep_stats['after']} 条")

        # Treemmer 系统发育冗余降采样
        pruner = TreemmerPruner(cancel_event=cancel_ev, on_log=log_fn)
        set_runner(pruner)
        genome_paths, trim_ref_stats = pruner.prune_if_needed(
            genome_paths=genome_paths,
            candidates=candidates,
            work_dir=ref_dir,
            target_count=scope.treemmer_target,
            threads=cfg.threads,
        )
        set_runner(None)
        if int(trim_ref_stats.get("removed", 0)) > 0:
            log_fn(f"[Treemmer] {trim_ref_stats['tool']}: {trim_ref_stats['before']} -> {trim_ref_stats['after']} 条")

        stage_fn("curate_derep", "completed", 45, f"参考集最终保留 {len(genome_paths)} 条基因组", elapsed=time.time() - t2)

        if cancel_ev.is_set():
            raise PhyloCancelledError("任务在参考集构建后已取消")

        # 确定外群名称（取第一个有效外群用于 IQ-TREE -o 与定根）
        active_outgroups = [
            c.accession for c in candidates if c.selected and c.role == "outgroup" and c.accession in genome_paths
        ]
        primary_outgroup = active_outgroups[0] if active_outgroups else None

        # ─── Stage 3-5 分流：TerL ML 标准流 vs 备选全基因组蛋白质组树 ───────────
        trim_stats: Optional[Dict[str, Any]] = None
        best_model: Optional[str] = None
        best_model_bic: Optional[float] = None
        iqtree_cmd: Optional[str] = None
        treefile_path: Optional[Path] = None
        trimmed_msa_path: Optional[Path] = None
        raw_nwk_path = job_dir / "tree_raw.nwk"

        # 构造参考集哈希用于 StageCache
        ref_hasher = hashlib.sha256()
        for acc in sorted(genome_paths.keys()):
            ref_hasher.update(acc.encode("utf-8"))
            ref_hasher.update(genome_paths[acc].read_bytes()[:4096])
        dataset_hash = ref_hasher.hexdigest()

        if cfg.marker_mode == "proteome":
            # 备选全基因组蛋白质组树 (DIAMOND S_G + BioNJ/UPGMA)
            t_m = time.time()
            tree_method = scope.proteome_tree_method
            dist_mode = "one_minus_sg" if tree_method == "upgma" else "log_sg"
            stage_fn(
                "marker_extract",
                "running",
                62,
                f"第 3 步 (备选)：计算全基因组共享蛋白质组矩阵 (ViPTree S_G, {tree_method.upper()})...",
            )
            prot_engine = ProteomeTreeEngine(cancel_event=cancel_ev, on_log=log_fn)
            set_runner(prot_engine)
            dist_npy = job_dir / "proteome_dist.npy"
            dist_csv = job_dir / "distance_matrix.csv"
            _, marker_report = prot_engine.build_proteome_tree(
                genome_fastas=genome_paths,
                work_dir=job_dir / "step3_proteome",
                output_nwk=raw_nwk_path,
                dist_npy=dist_npy,
                dist_csv=dist_csv,
                threads=cfg.threads,
                tree_method=tree_method,
                distance_mode=dist_mode,
                use_gpu=cfg.use_gpu,
            )
            set_runner(None)
            record.marker_report = marker_report
            record.artifacts["distance_csv"] = str(dist_csv)
            stage_fn("marker_extract", "completed", 82, "全基因组蛋白质组树构建完成", elapsed=time.time() - t_m, artifact=str(raw_nwk_path))
            stage_fn("msa", "skipped", 84, "蛋白质组树路径已跳过单基因比对")
            stage_fn("trim", "skipped", 86, "蛋白质组树路径无需 MSA 修剪")
            stage_fn("tree", "completed", 90, f"DIAMOND S_G + {tree_method.upper()} 建树完成", artifact=str(raw_nwk_path))
        else:
            # 标准路径：TerL 提取 -> MAFFT (L-INS-i/E-INS-i) -> ClipKIT (kpic) -> IQ-TREE
            t_m = time.time()
            stage_fn("marker_extract", "running", 54, "第 3 步：批量预测 ORF 并精确提取大末端酶亚基 (TerL)...")
            terl_dir = job_dir / "step3_terl"
            terl_faa = terl_dir / "terl_proteins.faa"
            extractor = TerlExtractor(cancel_event=cancel_ev, on_log=log_fn)
            set_runner(extractor)
            _, marker_report = extractor.extract_terl(
                genome_fastas=genome_paths,
                work_dir=terl_dir,
                output_faa=terl_faa,
                threads=cfg.threads,
            )
            set_runner(None)
            record.marker_report = marker_report
            record.artifacts["terl_fasta"] = str(terl_faa)

            if marker_report.extracted_count < 3:
                raise PhyloError(
                    f"成功提取到 TerL 的基因组不足 3 条（仅 {marker_report.extracted_count}/{marker_report.total_genomes} 条），"
                    "建议切换为「全基因组蛋白质组树 (DIAMOND S_G)」进行宏观定位。"
                )
            stage_fn(
                "marker_extract",
                "completed",
                62,
                f"TerL 提取完成 ({marker_report.extracted_count}/{marker_report.total_genomes})",
                elapsed=time.time() - t_m,
                artifact=str(terl_faa),
            )

            # 编解码短 ID 防止外链字符冲突（直接读取纯净 FASTA 记录，避免被通用解析器追加文件名前缀）
            terl_records = [
                (str(rec.id).strip(), str(rec.seq).strip().upper())
                for rec in iter_fasta_records(terl_faa)
                if str(rec.id).strip() and str(rec.seq).strip()
            ]
            sanitized_terl = job_dir / "sanitized_terl.fasta"
            id_map_path = job_dir / "id_map.json"
            _, codec = SequenceProfiler.write_sanitized_fasta(terl_records, sanitized_terl, id_map_path)
            short_outgroup = None
            if primary_outgroup:
                for sid, orig in codec.short_to_orig.items():
                    if orig == primary_outgroup:
                        short_outgroup = sid
                        break

            # Step 4A: MSA (MAFFT L-INS-i / E-INS-i / --auto)
            t_msa = time.time()
            msa_strategy = cfg.msa_strategy
            msa_tool = cfg.msa if cfg.msa != "none" else "mafft"
            stage_fn("msa", "running", 70, f"第 4 步：执行 {msa_tool.upper()} ({msa_strategy}) 蛋白多序列比对...")
            msa_fasta = job_dir / "terl_aligned.fasta"
            msa_key = cache.make_key(dataset_hash, f"phage_msa_{msa_tool}", {"strategy": msa_strategy, "mode": "terl"})
            if cfg.use_cache and cache.restore_files("msa", msa_key, {"terl_aligned.fasta": msa_fasta}):
                log_fn(f"[Cache Hit] 命中 TerL 比对缓存 ({msa_key})")
                stage_fn("msa", "cached", 75, "命中 TerL 比对缓存", cached=True, elapsed=time.time() - t_msa, artifact=str(msa_fasta))
            else:
                aligner = MultiSequenceAligner(cancel_event=cancel_ev, on_log=log_fn)
                set_runner(aligner)
                aligner.align(
                    input_fasta=sanitized_terl,
                    output_fasta=msa_fasta,
                    tool=msa_tool,
                    strategy=msa_strategy,  # type: ignore[arg-type]
                    threads=cfg.threads,
                    max_seq_len=0,  # 蛋白序列不触发长序列降级
                )
                set_runner(None)
                if cfg.use_cache:
                    cache.store_files("msa", msa_key, {"terl_aligned.fasta": msa_fasta})
                stage_fn("msa", "completed", 75, f"{msa_tool.upper()} ({msa_strategy}) 比对完成", elapsed=time.time() - t_msa, artifact=str(msa_fasta))
            record.artifacts["aligned_fasta"] = str(msa_fasta)

            # Step 4B: 比对修剪 (ClipKIT -m kpic 默认首选)
            t_trim = time.time()
            trim_mode = cfg.trim_mode if cfg.trim_mode != "none" else "kpic"
            stage_fn("trim", "running", 78, f"第 4 步：执行比对后修剪 ({trim_mode})...")
            trimmed_msa_path = job_dir / "terl_trimmed.fasta"
            _, trim_stats = AlignmentTrimmer.trim_with_mode(
                input_msa=msa_fasta,
                output_msa=trimmed_msa_path,
                mode=trim_mode,  # type: ignore[arg-type]
                max_gap_ratio=cfg.trim_gap_threshold or 0.5,
                cancel_event=cancel_ev,
                on_log=log_fn,
            )
            record.artifacts["trimmed_fasta"] = str(trimmed_msa_path)
            log_fn(
                f"[Trimmer] ({trim_stats['tool']}) 保留 {trim_stats['kept_cols']}/{trim_stats['original_cols']} 列, "
                f"简约信息位点 PI={trim_stats['parsimony_informative_sites']}"
            )
            stage_fn("trim", "completed", 82, f"比对修剪完成 ({trim_stats['kept_cols']} 列)", elapsed=time.time() - t_trim, artifact=str(trimmed_msa_path))

            # Step 5: IQ-TREE 发表级推断
            t_tree = time.time()
            ufboot = cfg.bootstrap if cfg.bootstrap >= 1000 or cfg.bootstrap == 0 else 1000
            iq_model = cfg.model if cfg.model and cfg.model.lower() not in ("jc69", "k2p", "p-distance") else "MFP"
            if cfg.engine == "fasttree":
                stage_fn("tree", "running", 86, "第 5 步：运行 FastTree 近似最大似然推断...")
                ft = FastTreeEngine(cancel_event=cancel_ev, on_log=log_fn)
                set_runner(ft)
                ft.build(
                    msa_fasta=trimmed_msa_path,
                    output_nwk=raw_nwk_path,
                    mol_type="protein",
                    model=cfg.model or "lg",
                    threads=cfg.threads,
                )
                set_runner(None)
            else:
                model_hint = "MFP 核心蛋白快速集" if iq_model.strip().lower() in ("auto", "mfp") else iq_model
                stage_fn(
                    "tree",
                    "running",
                    86,
                    f"第 5 步：运行 IQ-TREE 最大似然推断 (-m {model_hint} -B {ufboot} -alrt {cfg.iqtree_alrt})...",
                )
                iq = IQTreeEngine(cancel_event=cancel_ev, on_log=log_fn)
                set_runner(iq)
                iq.build(
                    msa_fasta=trimmed_msa_path,
                    output_nwk=raw_nwk_path,
                    work_dir=job_dir,
                    mol_type="protein",
                    model=iq_model,
                    bootstrap=ufboot,
                    threads=cfg.threads,
                    bnni=cfg.iqtree_bnni,
                    alrt=cfg.iqtree_alrt,
                    seed=cfg.iqtree_seed,
                    outgroup=short_outgroup,
                )
                set_runner(None)
                best_model = iq.last_best_model
                best_model_bic = iq.last_best_model_bic
                iqtree_cmd = iq.last_command
                raw_tf = job_dir / "iqtree_run" / "phylo.treefile"
                if raw_tf.is_file():
                    restored_tf = IdCodec.restore_newick(
                        raw_tf.read_text(encoding="utf-8", errors="replace"),
                        codec.short_to_orig,
                    )
                    treefile_path = job_dir / "final.treefile"
                    treefile_path.write_text(restored_tf + "\n", encoding="utf-8")
                    record.artifacts["treefile"] = str(treefile_path)

            raw_restored = IdCodec.restore_newick(
                raw_nwk_path.read_text(encoding="utf-8", errors="replace").strip(),
                codec.short_to_orig,
            )
            raw_nwk_path.write_text(raw_restored + "\n", encoding="utf-8")
            stage_fn("tree", "completed", 92, "最大似然系统发育树构建完成", elapsed=time.time() - t_tree, artifact=str(raw_nwk_path))

        # ─── Stage 6 & 7: 外群定根 + 元数据映射 + iTOL 模板生成 ───────────────────
        t_post = time.time()
        stage_fn("postprocess", "running", 94, "第 7 步：执行外群定根并生成 iTOL 注释模板套件...")
        raw_text = raw_nwk_path.read_text(encoding="utf-8", errors="replace").strip()
        final_nwk = raw_text
        if primary_outgroup and primary_outgroup in raw_text:
            try:
                final_nwk = reroot_outgroup(raw_text, primary_outgroup)
            except Exception as exc:
                log_fn(f"[定根提示] 外群重定根回退中点定根: {exc}")
                final_nwk = reroot_midpoint(raw_text) if cfg.midpoint_root else raw_text
        elif cfg.midpoint_root:
            final_nwk = reroot_midpoint(raw_text)

        final_nwk_path = job_dir / "final_tree.nwk"
        final_nwk_path.write_text(final_nwk + "\n", encoding="utf-8")
        metrics = compute_tree_metrics(
            final_nwk, best_model=best_model, best_model_bic=best_model_bic
        )

        # 生成节点元数据供前端渲染角色/宿主/属色带与发表级叶节点名称
        node_meta: Dict[str, Dict[str, Any]] = {}
        for c in candidates:
            if c.selected:
                node_meta[c.accession] = {
                    "role": c.role,
                    "description": clean_phage_description(c.description),
                    "genus": c.genus,
                    "family": c.family,
                    "host": c.host,
                    "genome_length": c.genome_length,
                    "gc_content": c.gc_content,
                    "wg_ani": c.wg_ani,
                }
        node_meta = enrich_node_metadata(node_meta)
        record.node_metadata = node_meta

        # 精确提取树中真实叶节点名称，避免子串误匹配并供 iTOL 与自动出图复用
        leaf_names = extract_leaf_names(final_nwk)

        # 生成 iTOL 注释模板文件
        itol_dir = job_dir / "itol"
        itol_files = ItolTemplateGenerator.generate(
            candidates=candidates,
            out_dir=itol_dir,
            leaf_names=leaf_names,
        )
        record.artifacts["itol_dir"] = str(itol_dir)
        record.artifacts["itol_files"] = itol_files
        stage_fn("postprocess", "completed", 97, "定根与 iTOL 注释模板生成完成", elapsed=time.time() - t_post, artifact=str(final_nwk_path))

        # ─── Stage 8: 6 项质检审计与交付 ZIP 打包 ────────────────────────────────
        t_qc = time.time()
        stage_fn("qc_delivery", "running", 98, "第 8 步：执行交付前 6 项质检审计并打包交付归档...")
        qc_report = PhageDeliveryQcAuditor.audit(
            newick=final_nwk,
            metrics=metrics,
            candidates=candidates,
            ani_result=ani_result,
            marker_report=record.marker_report,
            trim_stats=trim_stats,
            iqtree_cmd=iqtree_cmd,
            best_model=best_model,
            best_model_bic=best_model_bic,
            itol_files=itol_files,
        )
        record.qc_report = qc_report

        # 若 trimmed_msa 含短 ID，输出可读 ID 版本供交付包使用
        delivery_msa_path: Optional[Path] = None
        if trimmed_msa_path and trimmed_msa_path.is_file():
            id_map_file = job_dir / "id_map.json"
            if id_map_file.is_file():
                s2o = json.loads(id_map_file.read_text(encoding="utf-8"))
                delivery_msa_path = job_dir / "trimmed_alignment_named.fasta"
                with open(delivery_msa_path, "w", encoding="utf-8", newline="\n") as dfh:
                    for r in iter_fasta_records(trimmed_msa_path):
                        rid = r.id or ""
                        orig_name = s2o.get(rid, rid)
                        dfh.write(f">{orig_name}\n{str(r.seq)}\n")
            else:
                delivery_msa_path = trimmed_msa_path

        # 自动离线生成发表级矢量出图 (Circular + Rectangular；超过 60 叶自动追加 Composite)
        figures_dir = job_dir / "figures"
        pub_items: List[Dict[str, Any]] = []
        subtitle_parts: List[str] = []
        if best_model:
            subtitle_parts.append(
                f"Model: {best_model}" + (f" (BIC={best_model_bic})" if best_model_bic is not None else "")
            )
        if trim_stats and trim_stats.get("kept_cols"):
            subtitle_parts.append(f"ClipKIT sites: {trim_stats.get('kept_cols')} (PI={trim_stats.get('parsimony_informative_sites', 0)})")
        fig_subtitle = " | ".join(subtitle_parts)

        layouts_to_render = _select_publication_layouts(len(leaf_names))
        for layout_mode in layouts_to_render:
            try:
                out_paths = PublicationTreeRenderer.render(
                    newick=final_nwk,
                    node_metadata=node_meta,
                    out_dir=figures_dir,
                    request=PublicationFigureRequest(
                        layout=layout_mode,  # type: ignore[arg-type]
                        formats=["pdf", "svg", "png"],
                        dpi=300,
                        support_style="dots",
                        title=record.title,
                    ),
                    file_prefix="publication",
                    subtitle=fig_subtitle,
                )
                for fp in out_paths:
                    pub_items.append(
                        {
                            "filename": fp.name,
                            "format": fp.suffix.lstrip(".").lower(),
                            "layout": layout_mode,
                            "size_bytes": fp.stat().st_size,
                            "download_url": f"/api/phylo/jobs/{record.job_id}/export/figure/{fp.name}",
                        }
                    )
            except Exception as exc:
                log_fn(f"[PublicationFigure] {layout_mode} 离线出图跳过: {exc}")

        if pub_items:
            record.artifacts["figures_dir"] = str(figures_dir)
            record.artifacts["publication_figures"] = pub_items

        zip_path = DeliveryBundleExporter.write_reports_and_pack(
            job_dir=job_dir,
            job_id=record.job_id,
            title=record.title,
            newick=final_nwk,
            qc_report=qc_report,
            ani_result=ani_result,
            marker_report=record.marker_report,
            trimmed_msa_path=delivery_msa_path,
            treefile_path=treefile_path,
            itol_dir=itol_dir,
            commands_used=commands_used,
            figures_dir=figures_dir if pub_items else None,
        )
        record.artifacts["delivery_zip"] = str(zip_path)
        record.artifacts["final_nwk"] = str(final_nwk_path)
        record.newick = final_nwk
        record.metrics = metrics
        if best_model:
            record.artifacts["best_model"] = best_model
        if best_model_bic is not None:
            record.artifacts["best_model_bic"] = best_model_bic

        # 清理阶段大临时文件（保留精选交付物与缓存引用）
        for tmp_sub in (job_dir / "step2_references" / "drep_run" / "inputs",):
            if tmp_sub.is_dir():
                shutil.rmtree(tmp_sub, ignore_errors=True)

        ckp.set_artifact("delivery_zip", str(zip_path))
        stage_fn(
            "qc_delivery",
            "completed",
            100,
            f"质检 ({qc_report.overall_status.upper()}) 与交付包生成完成",
            elapsed=time.time() - t_qc,
            artifact=str(zip_path),
        )
