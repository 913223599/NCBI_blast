# -*- coding: utf-8 -*-
"""
核心蛋白跨样本比对与变异分析引擎 (Protein Cross-Sample Comparer)
职责：
1. 从 2 个样本（已完成的注释任务或外部 GBK/FAA 文件）中提取蛋白质特征；
2. 依据生物学功能（尾丝、裂解酶、衣壳、复制酶等）进行智能化分类聚合；
3. 执行多线程双向氨基酸全局对齐，精确计算一致性 (Identity %)，识别点突变、插入/缺失与长度变化；
4. 导出结构化比对结果与 CSV 报告。
"""
import io
import os
import csv
import json
import logging
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
import numpy as np
from Bio import SeqIO
from Bio.Align import PairwiseAligner

from ..pan_genomics.fast_matcher import get_kmers
from ..pan_genomics.gpu_accelerator import GPUSequenceMatcher
from ..annotation.fuser import AnnotationFuser
from .categories import PROTEIN_CATEGORIES, resolve_domain_names
from .models import (
    ProteinItem,
    MutationSite,
    RegionDomainItem,
    ProteinComparisonRow,
    ProteinComparisonResult,
)

logger = logging.getLogger("ProteinCompareEngine")


class ProteinComparer:
    """蛋白质比对执行器"""

    def __init__(self):
        self._thread_local = threading.local()
        self.aligner = self._create_aligner()

    @staticmethod
    def _create_aligner() -> PairwiseAligner:
        aligner = PairwiseAligner()
        aligner.mode = 'global'
        aligner.match_score = 1.0
        aligner.mismatch_score = 0.0
        aligner.open_gap_score = -1.0
        aligner.extend_gap_score = -0.5
        return aligner

    def _get_thread_aligner(self) -> PairwiseAligner:
        aligner = getattr(self._thread_local, "aligner", None)
        if aligner is None:
            aligner = self._create_aligner()
            self._thread_local.aligner = aligner
        return aligner

    @classmethod
    def is_hypothetical(cls, text: str) -> bool:
        """快速判断是否为未知/假定蛋白 (统一委托给 AnnotationFuser 权威判定器)"""
        return AnnotationFuser.is_unannotated(text)

    @classmethod
    def classify_protein(cls, product: str, direct_cat: Optional[str] = None, notes: Optional[str] = None) -> str:
        """
        依据产品名称、已知分类及证据备注自动归入功能大类
        采用严格带 \\b 词边界正则与排除项消歧机制，并与 AnnotationFuser 协同，杜绝子串误碰撞
        """
        import re

        clean_prod = (product or "").strip()

        # 1. 假定蛋白优先排除，防止 notes 中的技术性说明触发误匹配
        if cls.is_hypothetical(clean_prod):
            return "other"

        # 2. 对 product 本身执行严格正则词边界与优先级语义匹配
        #    注意：必须优先于 direct_cat 执行，因为 AnnotationFuser 的 "Head & Packaging" 合并了
        #    头部衣壳与包装末端酶，需先通过 product 精确区分 "packaging" 与 "capsid_head"
        prod_text = clean_prod.lower().replace("_", " ").replace("%3b", ";")
        priority_order = ["packaging", "tail_fiber", "capsid_head", "lysis", "replication"]

        for cat_key in priority_order:
            cat_info = PROTEIN_CATEGORIES[cat_key]

            excluded = False
            for exc_pat in cat_info.get("exclude", []):
                if re.search(exc_pat, prod_text):
                    excluded = True
                    break
            if excluded:
                continue

            for pat in cat_info["patterns"]:
                if re.search(pat, prod_text):
                    return cat_key

        # 3. 委托给 AnnotationFuser 权威推断器进行兜底映射 (覆盖 105 万条 PhageScope 词库规则)
        fuser_cat = AnnotationFuser.infer_category(clean_prod, None)
        if fuser_cat in ("Tail & Host Interaction", "Tail & Host Recognition"):
            return "tail_fiber"
        if fuser_cat == "Lysis":
            return "lysis"
        if fuser_cat == "Head & Packaging":
            return "capsid_head"
        if fuser_cat in ("Replication & Repair", "Transcription & Regulation", "Integration & Excision"):
            return "replication"

        # 4. 若提供了外部显式分类标签 (如 PHROGs 原始标签) 作为最终参考
        if direct_cat:
            dc_lower = direct_cat.lower()
            if "tail" in dc_lower or "fiber" in dc_lower:
                return "tail_fiber"
            if "lysis" in dc_lower:
                return "lysis"
            if "terminase" in dc_lower:
                return "packaging"
            if "head" in dc_lower or "capsid" in dc_lower or "packaging" in dc_lower:
                return "capsid_head"
            if any(k in dc_lower for k in ("replication", "repair", "transcription", "integration", "excision", "recombination")):
                return "replication"

        return "other"

    @classmethod
    def load_proteins_from_annotation(cls, task_dir_or_features: Any) -> List[ProteinItem]:
        """从注释目录 (features.json/GBK) 或特征列表载入蛋白质"""
        proteins: List[ProteinItem] = []

        if isinstance(task_dir_or_features, list):
            raw_list = task_dir_or_features
        elif isinstance(task_dir_or_features, (str, Path)):
            p = Path(task_dir_or_features)
            feat_json = p / "features.json"
            if feat_json.exists():
                with open(feat_json, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
            else:
                gbk_files = list(p.glob("*.gbk"))
                if not gbk_files:
                    raise FileNotFoundError(f"目录中未检测到 features.json 或 .gbk 文件: {p}")
                raw_list = []
                with open(gbk_files[0], "r", encoding="utf-8", errors="ignore") as f:
                    for rec in SeqIO.parse(f, "genbank"):
                        for feat in rec.features:
                            if feat.type == "CDS":
                                q = feat.qualifiers
                                raw_list.append({
                                    "id": q.get("locus_tag", ["unknown"])[0],
                                    "locus_tag": q.get("locus_tag", ["unknown"])[0],
                                    "product": q.get("product", ["hypothetical protein"])[0],
                                    "translation": q.get("translation", [""])[0],
                                    "start": int(feat.location.start) + 1,
                                    "end": int(feat.location.end),
                                    "strand": "+" if feat.location.strand >= 0 else "-",
                                    "category": q.get("function", q.get("category", [None]))[0],
                                    "notes": q.get("note", [None])[0]
                                })
        else:
            raise ValueError(f"不支持的数据源格式: {type(task_dir_or_features)}")

        for item in raw_list:
            seq = item.get("translation") or item.get("protein_sequence") or ""
            if not seq:
                continue
            prod = item.get("product") or "hypothetical protein"
            direct_cat = item.get("category")
            notes = item.get("notes")
            cat = cls.classify_protein(prod, direct_cat=direct_cat, notes=notes)
            proteins.append(ProteinItem(
                id=item.get("id") or item.get("locus_tag") or "unknown",
                locus_tag=item.get("locus_tag") or item.get("id") or "unknown",
                product=prod,
                translation=seq,
                length_aa=len(seq),
                start=item.get("start", 0),
                end=item.get("end", 0),
                strand=item.get("strand", "+"),
                category=cat
            ))

        return proteins

    @classmethod
    def load_proteins_from_file(cls, file_path: Path) -> Tuple[List[ProteinItem], Dict[str, Any]]:
        """
        直接从单个外部文件中解析蛋白质特征 (全面支持 .gbk, .gb, .genbank, .faa, .fasta, .json)
        返回: (proteins, metadata)
        """
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")

        suffix = p.suffix.lower()
        proteins: List[ProteinItem] = []
        meta: Dict[str, Any] = {
            "file_name": p.name,
            "file_size": p.stat().st_size,
            "file_type": suffix,
            "total_length": 0,
            "cds_count": 0
        }

        # 1. GenBank 文件解析
        if suffix in [".gbk", ".gb", ".genbank"]:
            total_bp = 0
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for rec in SeqIO.parse(f, "genbank"):
                    if rec.seq:
                        total_bp += len(rec.seq)
                    for feat in rec.features:
                        if feat.type == "CDS":
                            q = feat.qualifiers
                            lt = q.get("locus_tag", q.get("protein_id", [f"feat_{len(proteins)+1}"]))[0] if hasattr(q, "get") else f"feat_{len(proteins)+1}"
                            prod = q.get("product", ["hypothetical protein"])[0]
                            trans = q.get("translation", [""])[0]
                            if not trans and feat.location and rec.seq:
                                try:
                                    trans = str(feat.extract(rec.seq).translate(to_stop=True))
                                except Exception:
                                    pass
                            if not trans:
                                continue
                            
                            direct_cat = q.get("function", q.get("category", [None]))[0]
                            notes = q.get("note", [None])[0]
                            cat = cls.classify_protein(prod, direct_cat=direct_cat, notes=notes)
                            f_start = int(feat.location.start) + 1 if feat.location else 0
                            f_end = int(feat.location.end) if feat.location else 0
                            f_strand = "+" if (feat.location and feat.location.strand >= 0) else "-"

                            proteins.append(ProteinItem(
                                id=lt,
                                locus_tag=lt,
                                product=prod,
                                translation=trans,
                                length_aa=len(trans),
                                start=f_start,
                                end=f_end,
                                strand=f_strand,
                                category=cat
                            ))
            meta["total_length"] = total_bp

        # 2. 氨基酸 FASTA 文件 (.faa / .fasta)
        elif suffix in [".faa", ".fasta", ".fa", ".fna"]:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for idx, rec in enumerate(SeqIO.parse(f, "fasta"), start=1):
                    seq = str(rec.seq).strip().upper()
                    if not seq:
                        continue
                    header = rec.description or rec.id
                    prod = "hypothetical protein"
                    if " " in header:
                        prod = header.split(" ", 1)[1].strip()
                    elif "_" in header or "-" in header:
                        prod = header

                    cat = cls.classify_protein(prod)
                    lt = rec.id or f"prot_{idx:05d}"
                    proteins.append(ProteinItem(
                        id=lt,
                        locus_tag=lt,
                        product=prod,
                        translation=seq,
                        length_aa=len(seq),
                        start=0,
                        end=len(seq) * 3,
                        strand="+",
                        category=cat
                    ))

        # 3. JSON 文件
        elif suffix == ".json":
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    proteins = cls.load_proteins_from_annotation(data)
                elif isinstance(data, dict) and "features" in data:
                    proteins = cls.load_proteins_from_annotation(data["features"])

        meta["cds_count"] = len(proteins)
        return proteins, meta

    def compare_two_samples(
        self,
        sample_a_name: str,
        sample_a_proteins: List[ProteinItem],
        sample_b_name: str,
        sample_b_proteins: List[ProteinItem],
        target_category: str = "all"
    ) -> ProteinComparisonResult:
        """执行两个样本间的全量或指定类别蛋白质比对 (多线程并发 + K-mer 预剪枝加速)"""
        rows: List[ProteinComparisonRow] = []
        matched_b_ids = set()

        # 如果指定了具体分类，先做预过滤
        if target_category != "all":
            filtered_a = [p for p in sample_a_proteins if p.category == target_category]
            filtered_b = [p for p in sample_b_proteins if p.category == target_category]
        else:
            filtered_a = sample_a_proteins
            filtered_b = sample_b_proteins

        # 建立样本 B 的快速检索索引 (按序列哈希与按产品名)
        seq_to_b: Dict[str, List[ProteinItem]] = {}
        for b in filtered_b:
            if b.translation not in seq_to_b:
                seq_to_b[b.translation] = []
            seq_to_b[b.translation].append(b)

        # 预先提取样本 B 所有蛋白的整型 K-mer 集合与长度
        b_kmers: Dict[str, Set[int]] = {b.id: get_kmers(b.translation, 3) for b in filtered_b}

        # 完全相同序列按出现次序一一配对：A 中第 k 条某序列对应 B 中第 k 条同序列，
        # 避免多拷贝相同基因全部挤到 B 的第一条上而产生虚假的“独有基因”
        exact_rank_a: Dict[str, int] = {}
        seen_seq_cnt: Dict[str, int] = {}
        for a in filtered_a:
            k = seen_seq_cnt.get(a.translation, 0)
            exact_rank_a[a.id] = k
            seen_seq_cnt[a.translation] = k + 1

        # 3-mer 余弦相似度仅用于候选排序（高相似度优先比对），不剔除任何候选。
        # 实测哈希 3-mer 余弦随序列长度漂移，40% 一致度同源对与无关序列分布重叠，
        # 无法作为硬阈值过滤，否则会丢失远缘同源蛋白。
        rank_mat_a: Optional[np.ndarray] = None
        rank_mat_b: Optional[np.ndarray] = None
        b_index: Dict[str, int] = {b.id: i for i, b in enumerate(filtered_b)}
        if len(filtered_a) * len(filtered_b) >= 400:
            try:
                rank_mat_a = GPUSequenceMatcher._build_normalized_3mer_matrix([a.translation for a in filtered_a])
                rank_mat_b = GPUSequenceMatcher._build_normalized_3mer_matrix([b.translation for b in filtered_b])
            except Exception as e:
                logger.debug(f"3-mer 候选排序不可用，回退原始顺序: {e}")
                rank_mat_a, rank_mat_b = None, None

        # 动态计算安全并发线程数 (保留 2 个核心防止卡死)
        cpu_cnt = os.cpu_count() or 4
        max_workers = max(1, min(cpu_cnt - 2, 30))

        # 内部对单条 pa 的最佳匹配对齐函数
        def align_single_pa(idx_a: int, pa: ProteinItem) -> Tuple[ProteinItem, Optional[ProteinItem], float, List[MutationSite], int, str, str, str, int, int, int, List[RegionDomainItem], str]:
            best_match: Optional[ProteinItem] = None
            best_identity = 0.0
            best_mutations: List[MutationSite] = []
            best_diff_cnt = 0
            best_aln_a: str = pa.translation
            best_markup: str = "|" * len(pa.translation)
            best_aln_b: str = ""
            best_c_cnt: int = 0
            best_r_cnt: int = 0
            best_in_cnt: int = 0
            best_doms: List[RegionDomainItem] = []
            best_concl: str = ""

            # 1. 优先检查 100% 序列完全相同的候选
            if pa.translation in seq_to_b and seq_to_b[pa.translation]:
                same_seq_bs = seq_to_b[pa.translation]
                exact_cand = same_seq_bs[exact_rank_a.get(pa.id, 0) % len(same_seq_bs)]
                best_match = exact_cand
                best_identity = 100.0
                best_mutations = []
                best_diff_cnt = 0
                best_aln_a = pa.translation
                best_markup = "|" * len(pa.translation)
                best_aln_b = exact_cand.translation
                best_c_cnt = 0
                best_r_cnt = 0
                best_in_cnt = 0
                best_doms = self._calculate_domains(len(pa.translation), [], 100.0, category=pa.category, product=pa.product)
                best_concl = "双样本全长氨基酸序列 100% 逐位一致，核心催化与组装结构高度锁定。"
                return pa, best_match, best_identity, best_mutations, best_diff_cnt, best_aln_a, best_markup, best_aln_b, best_c_cnt, best_r_cnt, best_in_cnt, best_doms, best_concl

            # 2. 同名优先检索与高相似度序列对齐
            pa_prod_lower = pa.product.lower()
            pa_kmers = get_kmers(pa.translation, 3)
            len_a = len(pa.translation)

            same_prod_cands = []
            other_cands = []
            for b in filtered_b:
                if b.product.lower() == pa_prod_lower:
                    same_prod_cands.append(b)
                else:
                    other_cands.append(b)

            # 非同名候选按 3-mer 余弦降序排列，使最佳匹配尽早出现以收紧剪枝阈值
            if rank_mat_a is not None and rank_mat_b is not None and len(other_cands) > 1:
                scores = rank_mat_b @ rank_mat_a[idx_a]
                other_cands.sort(key=lambda cand: -float(scores[b_index[cand.id]]))

            search_cands = same_prod_cands + other_cands

            for pb in search_cands:
                len_b = len(pb.translation)
                if len_a == 0 or len_b == 0:
                    continue
                # 长度覆盖度初筛
                if min(len_a, len_b) / max(len_a, len_b) < 0.4:
                    continue

                # K-mer 理论下限快速剪枝
                pb_kset = b_kmers.get(pb.id, set())
                if pa_kmers and pb_kset:
                    inter_cnt = len(pa_kmers & pb_kset)
                    min_k = min(len(pa_kmers), len(pb_kset))
                    if min_k > 0 and (inter_cnt / min_k) < (max(0.35, best_identity / 100.0) * 0.3):
                        continue

                ident, muts, diffs, aln_a, markup, aln_b, c_cnt, r_cnt, in_cnt, doms, concl = self._align_and_diff(
                    pa.translation, pb.translation, category=pa.category, product=pa.product
                )
                if ident > best_identity:
                    best_identity = ident
                    best_match = pb
                    best_mutations = muts
                    best_diff_cnt = diffs
                    best_aln_a = aln_a
                    best_markup = markup
                    best_aln_b = aln_b
                    best_c_cnt = c_cnt
                    best_r_cnt = r_cnt
                    best_in_cnt = in_cnt
                    best_doms = doms
                    best_concl = concl
                if best_identity >= 99.9:
                    break

            return pa, best_match, best_identity, best_mutations, best_diff_cnt, best_aln_a, best_markup, best_aln_b, best_c_cnt, best_r_cnt, best_in_cnt, best_doms, best_concl

        # 并发对所有 pa 执行对齐，按输入顺序确定性收集结果
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(align_single_pa, idx_a, pa) for idx_a, pa in enumerate(filtered_a)]
            for fut in futures:
                pa, best_match, best_identity, best_mutations, best_diff_cnt, best_aln_a, best_markup, best_aln_b, best_c_cnt, best_r_cnt, best_in_cnt, best_doms, best_concl = fut.result()

                # 判定匹配状态
                if best_match and best_identity >= 40.0 and (best_match.id not in matched_b_ids or best_identity >= 99.0):
                    matched_b_ids.add(best_match.id)
                    if best_identity >= 99.99:
                        match_status = "identical"
                    elif best_identity >= 95.0:
                        match_status = "highly_conserved"
                    else:
                        match_status = "divergent"

                    cat_info = PROTEIN_CATEGORIES.get(pa.category, {"label": "其他功能蛋白"})
                    label_str = str(cat_info.get("label", pa.category))
                    rows.append(ProteinComparisonRow(
                        category=pa.category,
                        category_label=label_str,
                        sample_a_id=pa.id,
                        sample_a_tag=pa.locus_tag,
                        sample_a_product=pa.product,
                        sample_a_len=pa.length_aa,
                        sample_a_range=f"{pa.start}-{pa.end}",
                        sample_a_strand=pa.strand,
                        sample_a_seq=pa.translation,
                        sample_b_id=best_match.id,
                        sample_b_tag=best_match.locus_tag,
                        sample_b_product=best_match.product,
                        sample_b_len=best_match.length_aa,
                        sample_b_range=f"{best_match.start}-{best_match.end}",
                        sample_b_strand=best_match.strand,
                        sample_b_seq=best_match.translation,
                        match_status=match_status,
                        identity_pct=round(best_identity, 2),
                        diff_count=best_diff_cnt,
                        mutations=best_mutations,
                        length_diff=abs(pa.length_aa - best_match.length_aa),
                        aligned_seq_a=best_aln_a,
                        aligned_markup=best_markup,
                        aligned_seq_b=best_aln_b if best_aln_b else best_match.translation,
                        conservative_mutation_cnt=best_c_cnt,
                        radical_mutation_cnt=best_r_cnt,
                        indel_cnt=best_in_cnt,
                        hotspot_conclusion=best_concl,
                        region_domains=best_doms
                    ))
                else:
                    # 样本 A 独有
                    cat_info = PROTEIN_CATEGORIES.get(pa.category, {"label": "其他功能蛋白"})
                    label_str = str(cat_info.get("label", pa.category))
                    rows.append(ProteinComparisonRow(
                        category=pa.category,
                        category_label=label_str,
                        sample_a_id=pa.id,
                        sample_a_tag=pa.locus_tag,
                        sample_a_product=pa.product,
                        sample_a_len=pa.length_aa,
                        sample_a_range=f"{pa.start}-{pa.end}",
                        sample_a_strand=pa.strand,
                        sample_a_seq=pa.translation,
                        match_status="unique_a",
                        identity_pct=0.0,
                        diff_count=pa.length_aa,
                        mutations=[],
                        hotspot_conclusion="该基因在目标样本中未检出对应同源序列，属于样本 A 特异性基因。"
                    ))

        # 检查样本 B 中独有的未配对蛋白
        for pb in filtered_b:
            if pb.id not in matched_b_ids:
                cat_info = PROTEIN_CATEGORIES.get(pb.category, {"label": "其他功能蛋白"})
                label_str = str(cat_info.get("label", pb.category))
                rows.append(ProteinComparisonRow(
                    category=pb.category,
                    category_label=label_str,
                    sample_a_id="",
                    sample_a_tag="[样本A缺失]",
                    sample_a_product="未检出匹配同源基因",
                    sample_a_len=0,
                    sample_a_range="-",
                    sample_a_strand="-",
                    sample_a_seq="",
                    sample_b_id=pb.id,
                    sample_b_tag=pb.locus_tag,
                    sample_b_product=pb.product,
                    sample_b_len=pb.length_aa,
                    sample_b_range=f"{pb.start}-{pb.end}",
                    sample_b_strand=pb.strand,
                    sample_b_seq=pb.translation,
                    match_status="unique_b",
                    identity_pct=0.0,
                    diff_count=pb.length_aa,
                    mutations=[],
                    hotspot_conclusion="该基因在基准样本中缺失，属于样本 B 新增特异性基因。"
                ))

        # 汇总统计
        identical_cnt = sum(1 for r in rows if r.match_status == "identical")
        conserved_cnt = sum(1 for r in rows if r.match_status == "highly_conserved")
        divergent_cnt = sum(1 for r in rows if r.match_status == "divergent")
        unique_a_cnt = sum(1 for r in rows if r.match_status == "unique_a")
        unique_b_cnt = sum(1 for r in rows if r.match_status == "unique_b")

        matched_rows = [r for r in rows if r.match_status in ["identical", "highly_conserved", "divergent"]]
        avg_ident = sum(r.identity_pct for r in matched_rows) / max(1, len(matched_rows))

        # 分类汇总统计
        cat_summary: Dict[str, Dict[str, int]] = {}
        for r in rows:
            c = r.category
            if c not in cat_summary:
                cat_summary[c] = {"total": 0, "identical": 0, "conserved": 0, "divergent": 0, "unique": 0}
            cat_summary[c]["total"] += 1
            if r.match_status == "identical":
                cat_summary[c]["identical"] += 1
            elif r.match_status == "highly_conserved":
                cat_summary[c]["conserved"] += 1
            elif r.match_status == "divergent":
                cat_summary[c]["divergent"] += 1
            else:
                cat_summary[c]["unique"] += 1

        return ProteinComparisonResult(
            sample_a_name=sample_a_name,
            sample_b_name=sample_b_name,
            sample_a_total_cds=len(sample_a_proteins),
            sample_b_total_cds=len(sample_b_proteins),
            total_compared_pairs=len(rows),
            identical_count=identical_cnt,
            conserved_count=conserved_cnt,
            divergent_count=divergent_cnt,
            unique_a_count=unique_a_cnt,
            unique_b_count=unique_b_cnt,
            average_identity_pct=round(avg_ident, 2),
            category_summary=cat_summary,
            rows=rows
        )

    @staticmethod
    def _classify_mutation(ref_aa: str, alt_aa: str) -> Tuple[str, str]:
        """判定单点突变的物理化学特性改变"""
        if ref_aa == "-" or alt_aa == "-":
            return "indel", "插入/缺失 (Indel)"
        
        hydrophobic = set("AVLIPMFW")
        polar = set("STCNQY")
        positive = set("KRH")
        negative = set("DE")
        
        r, a = ref_aa.upper(), alt_aa.upper()
        if r == a:
            return "identical", "完全相同"
        
        if (r in positive and a in negative) or (r in negative and a in positive):
            return "charge_flip", "电荷反转 (+/- 颠覆)"
        if (r in positive and a not in positive) or (a in positive and r not in positive) or \
           (r in negative and a not in negative) or (a in negative and r not in negative):
            return "charge_shift", "电荷改变 (酸碱性质增减)"
        if (r in hydrophobic and a in polar) or (r in polar and a in hydrophobic):
            return "polarity_shift", "极性/疏水性转变"
        if (r in hydrophobic and a in hydrophobic) or (r in polar and a in polar) or \
           (r in positive and a in positive) or (r in negative and a in negative):
            return "conservative", "同类保守替换 (理化性质维持)"
        
        return "other_mutation", "理化性质变异"

    @staticmethod
    def _get_domain_names(category: str, product: str) -> Tuple[str, str, str]:
        """依据蛋白质功能分类与产品名称动态推导 N端、中段、C端 结构域名称"""
        return resolve_domain_names(category, product)

    def _align_and_diff(
        self,
        seq_a: str,
        seq_b: str,
        category: str = "other",
        product: str = ""
    ) -> Tuple[
        float, List[MutationSite], int, str, str, str, int, int, int, List[RegionDomainItem], str
    ]:
        """
        执行氨基酸序列全局比对并提取多维度生物学指标：
        1. 一致性与突变位点
        2. BLAST 风格逐位对齐串 (aligned_a, markup, aligned_b)
        3. 理化变异统计 (保守替换、显著变异、Indel)
        4. 结构域三段分段分析 (N端、中段、C端) 与突变富集热点结论
        """
        if not seq_a or not seq_b:
            max_len = max(len(seq_a), len(seq_b))
            return 0.0, [], max_len, seq_a, " " * max_len, seq_b, 0, 0, max_len, [], "序列缺失"
        
        if seq_a == seq_b:
            markup = "|" * len(seq_a)
            doms = self._calculate_domains(len(seq_a), [], 100.0, category=category, product=product)
            return 100.0, [], 0, seq_a, markup, seq_b, 0, 0, 0, doms, "全长序列 100% 严格保守，核心功能完全锁定"

        # 快速模式：若长度相同，直接逐字符比对
        if len(seq_a) == len(seq_b):
            aln_a, aln_b = seq_a, seq_b
            markup_chars = []
            mutations: List[MutationSite] = []
            diff_count = 0
            cons_cnt, rad_cnt, indel_cnt = 0, 0, 0

            for idx, (ca, cb) in enumerate(zip(seq_a, seq_b)):
                if ca == cb:
                    markup_chars.append("|")
                else:
                    diff_count += 1
                    imp_type, imp_label = self._classify_mutation(ca, cb)
                    if imp_type == "conservative":
                        markup_chars.append("+")
                        cons_cnt += 1
                    else:
                        markup_chars.append(" ")
                        rad_cnt += 1

                    mutations.append(MutationSite(
                        pos=idx + 1,
                        ref_aa=ca,
                        alt_aa=cb,
                        impact_type=imp_type,
                        impact_label=imp_label,
                        description=f"位点 {idx + 1}: {ca} -> {cb} ({imp_label})"
                    ))

            ident = round(((len(seq_a) - diff_count) / len(seq_a)) * 100.0, 2)
            aligned_markup = "".join(markup_chars)
            domains = self._calculate_domains(len(seq_a), mutations, ident, category=category, product=product)
            conclusion = self._generate_hotspot_conclusion(domains, mutations, ident, category=category, product=product)

            return ident, mutations, diff_count, aln_a, aligned_markup, aln_b, cons_cnt, rad_cnt, indel_cnt, domains, conclusion

        # 长度不同时：调用线程独立 PairwiseAligner 全局比对
        try:
            aligner = self._get_thread_aligner()
            alignments = aligner.align(seq_a, seq_b)
            best_aln = next(iter(alignments), None)
            if best_aln is None:
                max_len = max(len(seq_a), len(seq_b))
                return 0.0, [], max_len, seq_a, " " * max_len, seq_b, 0, 0, max_len, [], "无有效比对路径"

            aln_a, aln_b = str(best_aln[0]), str(best_aln[1])
            markup_chars = []
            mutations = []
            diff_count = 0
            cons_cnt, rad_cnt, indel_cnt = 0, 0, 0
            real_pos_a = 0
            matches = 0

            for ca, cb in zip(aln_a, aln_b):
                if ca != "-":
                    real_pos_a += 1
                
                if ca == cb and ca != "-":
                    matches += 1
                    markup_chars.append("|")
                else:
                    diff_count += 1
                    imp_type, imp_label = self._classify_mutation(ca, cb)
                    if imp_type == "conservative":
                        markup_chars.append("+")
                        cons_cnt += 1
                    elif imp_type == "indel":
                        markup_chars.append("-")
                        indel_cnt += 1
                    else:
                        markup_chars.append(" ")
                        rad_cnt += 1

                    pos_display = real_pos_a if ca != "-" else max(1, real_pos_a)
                    mutations.append(MutationSite(
                        pos=pos_display,
                        ref_aa=ca,
                        alt_aa=cb,
                        impact_type=imp_type,
                        impact_label=imp_label,
                        description=f"位点 {pos_display}: {ca} -> {cb} ({imp_label})"
                    ))

            ident = round((matches / max(len(seq_a), len(seq_b))) * 100.0, 2)
            aligned_markup = "".join(markup_chars)
            domains = self._calculate_domains(max(len(seq_a), len(seq_b)), mutations, ident, category=category, product=product)
            conclusion = self._generate_hotspot_conclusion(domains, mutations, ident, category=category, product=product)

            return ident, mutations, diff_count, aln_a, aligned_markup, aln_b, cons_cnt, rad_cnt, indel_cnt, domains, conclusion
        except Exception as e:
            logger.warning(f"对齐比对异常: {e}")
            max_len = max(len(seq_a), len(seq_b))
            return 0.0, [], max_len, seq_a, " " * max_len, seq_b, 0, 0, max_len, [], "比对异常"

    @classmethod
    def _calculate_domains(
        cls,
        total_len: int,
        mutations: List[MutationSite],
        global_ident: float,
        category: str = "other",
        product: str = ""
    ) -> List[RegionDomainItem]:
        """将全长划分为 N-端近端、中段骨架区、C-端远端 结构域，结合蛋白大类动态赋予生物学命名"""
        if total_len <= 0:
            return []

        # 划分为 3 段
        part_len = max(1, total_len // 3)
        d1_end = part_len
        d2_end = part_len * 2
        d3_end = total_len

        n_name, m_name, c_name = cls._get_domain_names(category, product)

        ranges = [
            (n_name, 1, d1_end),
            (m_name, d1_end + 1, d2_end),
            (c_name, d2_end + 1, d3_end)
        ]

        results = []
        for name, s, e in ranges:
            l = max(1, e - s + 1)
            # 统计该区间内的突变
            sub_muts = [m for m in mutations if s <= m.pos <= e]
            mut_cnt = len(sub_muts)
            c_cnt = sum(1 for m in sub_muts if m.impact_type == "conservative")
            r_cnt = mut_cnt - c_cnt
            sub_ident = max(0.0, round(((l - mut_cnt) / l) * 100.0, 2))

            status = "conserved" if sub_ident >= 95.0 else ("moderate" if sub_ident >= 80.0 else "hypervariable")
            results.append(RegionDomainItem(
                name=name,
                start=s,
                end=e,
                length=l,
                identity_pct=sub_ident,
                mutation_count=mut_cnt,
                conservative_count=c_cnt,
                radical_count=r_cnt,
                status=status
            ))

        return results

    @staticmethod
    def _generate_hotspot_conclusion(
        domains: List[RegionDomainItem],
        mutations: List[MutationSite],
        global_ident: float,
        category: str = "other",
        product: str = ""
    ) -> str:
        """基于生物学功能类别、结构域拓扑分布与理化突变性质生成综合研判结论"""
        if not mutations:
            return "双样本全长氨基酸序列 100% 严格一致，核心催化与组装结构高度锁定。"

        total_mut = len(mutations)
        cons_cnt = sum(1 for m in mutations if m.impact_type == "conservative")
        rad_cnt = total_mut - cons_cnt
        charge_flips = sum(1 for m in mutations if m.impact_type == "charge_flip")
        indels = sum(1 for m in mutations if m.impact_type == "indel")

        # 微观理化性质点评后缀
        chem_notes = []
        if indels > 0:
            chem_notes.append(f"伴随 {indels} 处插入/缺失(Indel)位移")
        if charge_flips > 0:
            chem_notes.append(f"检出 {charge_flips} 处电荷反转(+/-颠覆)")
        elif rad_cnt > 0:
            chem_notes.append(f"包含 {rad_cnt} 处显著变异(极性/位阻改变)")
        elif rad_cnt == 0:
            chem_notes.append("全部为同类保守替换")

        chem_suffix = f"（{'，'.join(chem_notes)}）" if chem_notes else ""

        # 低频散发变异（置信度保护：<=2 处突变不妄断区域性富集热点）
        if total_mut <= 2:
            return f"全长仅检出 {total_mut} 处散发性单点变异（相似度 {global_ident}%）{chem_suffix}，未形成区域性突变热点，蛋白质整体三维构象与基本活性预期保持一致。"

        if len(domains) == 3:
            d1, d2, d3 = domains[0], domains[1], domains[2]
            d1_pct = round((d1.mutation_count / total_mut) * 100, 1)
            d2_pct = round((d2.mutation_count / total_mut) * 100, 1)
            d3_pct = round((d3.mutation_count / total_mut) * 100, 1)
            p_lower = product.lower()

            # 分支 1: C-端显著富集 (>=60%)
            if d3_pct >= 60.0:
                if any(k in p_lower for k in ["tail tube", "tail sheath", "tube", "sheath", "major tail"]):
                    return f"变异主要富集于 C-端末端对接区 (占全长突变总数的 {d3_pct}%)，而 N-端环状聚合核心保持 {d1.identity_pct}% 严格保守。提示尾管主体通道结构高度稳定，C-端局部变异主要用于适配基板/穿刺界面的微环境协同{chem_suffix}。"
                elif category == "tail_fiber" or any(k in p_lower for k in ["tail fiber", "fiber", "spike", "receptor"]):
                    return f"变异显著富集于 C-端受体结合与纤突区域 (占全长突变总数的 {d3_pct}%)，而 N-端基板锚定域维持 {d1.identity_pct}% 高保守度。此特征提示噬菌体在保持尾部装配连接的同时，通过 C-端纤突分化以实现宿主谱（Host Range）适应性演化{chem_suffix}。"
                elif category == "lysis" or any(k in p_lower for k in ["lysin", "lysozyme", "holin", "peptidase"]):
                    return f"变异主要富集于 C-端细胞壁结合域 (CBD，占比 {d3_pct}%)，催化活性区维持 {d1.identity_pct}% 保守。提示在保持水解活性的同时，可能发生宿主细胞壁吸附特异性的微调{chem_suffix}。"
                else:
                    return f"变异显著富集于 C-端功能区 (占全长突变总数的 {d3_pct}%)，N-端与核心骨架区保持良好保守度{chem_suffix}。"

            # 分支 2: N-端显著富集 (>=60%)
            elif d1_pct >= 60.0:
                return f"变异显著富集于 N-端前导/锚定区 (占比 {d1_pct}%)，而中段与 C-端功能核心维持 {d3.identity_pct}% 保守度。提示可能涉及亚基组装起始界面、前导肽剪切或复合体接口的适配微调{chem_suffix}。"

            # 分支 3: 中段核心区显著富集 (>=60%)
            elif d2_pct >= 60.0:
                return f"变异主要富集于中段核心骨架区 (占比 {d2_pct}%)，两端界面保持相对稳定。需关注中段二次结构单元（α-螺旋束/β-折叠）的侧链堆叠与空间构象刚性{chem_suffix}。"

            # 分支 4: 全长散在均匀分布 (各段均 >= 90%)
            elif d1.identity_pct >= 90.0 and d2.identity_pct >= 90.0 and d3.identity_pct >= 90.0:
                return f"变异在全长序列均匀散在分布（相似度 {global_ident}%）{chem_suffix}，无明显局部突变热点，蛋白质三维折叠构象与核心功能预期保持高度一致。"

        # 兜底：多区域广泛分歧
        return f"全长检出 {total_mut} 处多点分歧变异（平均相似度 {global_ident}%）{chem_suffix}，覆盖多个结构域，提示两样本在该同源蛋白上发生了较显著的序列演化分化。"

    @staticmethod
    def export_to_csv(result: ProteinComparisonResult) -> str:
        """导出比对报告为 CSV 文本"""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入头部元数据
        writer.writerow(["# 跨样本核心蛋白质比对与变异分析报告"])
        writer.writerow(["# 样本 A", result.sample_a_name, f"CDS 总量: {result.sample_a_total_cds}"])
        writer.writerow(["# 样本 B", result.sample_b_name, f"CDS 总量: {result.sample_b_total_cds}"])
        writer.writerow(["# 比对对数", result.total_compared_pairs, f"平均相似度: {result.average_identity_pct}%"])
        writer.writerow(["# 100% 完全相同", result.identical_count, "# 高度保守 (>=95%)", result.conserved_count, "# 显著分歧 (<95%)", result.divergent_count])
        writer.writerow([])

        # 写入列头
        headers = [
            "功能大类",
            "匹配状态",
            "相似度 (%)",
            "变异数",
            "长度差 (aa)",
            "样本A 位点 (Locus Tag)",
            "样本A 产品名称 (Product)",
            "样本A 长度 (aa)",
            "样本A 区间",
            "样本A 链向",
            "样本B 位点 (Locus Tag)",
            "样本B 产品名称 (Product)",
            "样本B 长度 (aa)",
            "样本B 区间",
            "样本B 链向",
            "突变位点详情"
        ]
        writer.writerow(headers)

        status_text_map = {
            "identical": "100% 完全相同",
            "highly_conserved": "高度保守 (>=95%)",
            "divergent": "显著变异 (<95%)",
            "unique_a": "样本A 独有",
            "unique_b": "样本B 独有"
        }

        for r in result.rows:
            mut_desc = "; ".join([m.description for m in r.mutations[:10]])
            if len(r.mutations) > 10:
                mut_desc += f" (等共 {len(r.mutations)} 处)"

            writer.writerow([
                r.category_label,
                status_text_map.get(r.match_status, r.match_status),
                f"{r.identity_pct}%",
                r.diff_count,
                r.length_diff,
                r.sample_a_tag,
                r.sample_a_product,
                r.sample_a_len,
                r.sample_a_range,
                r.sample_a_strand,
                r.sample_b_tag or "-",
                r.sample_b_product or "-",
                r.sample_b_len or "-",
                r.sample_b_range or "-",
                r.sample_b_strand or "-",
                mut_desc or "无差异"
            ])

        return output.getvalue()
