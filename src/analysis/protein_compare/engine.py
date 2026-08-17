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
import csv
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from Bio import SeqIO
from Bio.Align import PairwiseAligner

logger = logging.getLogger("ProteinCompareEngine")

# 预设生物学功能分类关键词映射
PROTEIN_CATEGORIES = {
    "tail_fiber": {
        "label": "尾丝与宿主识别系统 (Tail Fiber & Host Specificity)",
        "keywords": ["tail fiber", "tail", "fiber", "hinge connector", "distal connector", "proximal connector", "collar", "whisker"]
    },
    "lysis": {
        "label": "裂解系统与溶菌酶 (Lysis / Endolysin / Spanin / Holin)",
        "keywords": ["lysin", "lysozyme", "spanin", "holin", "lysis", "peptidase", "endopeptidase", "rz-like", "antiholin"]
    },
    "capsid_head": {
        "label": "衣壳与头部形态发生 (Capsid & Head Morphogenesis)",
        "keywords": ["capsid", "head", "portal", "scaffold", "coat", "vertex", "capsomer", "maturation protease", "prohead"]
    },
    "replication": {
        "label": "DNA 复制与修饰酶 (Replication & Modification)",
        "keywords": ["polymerase", "helicase", "primase", "ligase", "nuclease", "endonuclease", "exonuclease", "rnase", "ssb", "methyltransferase", "topoisomerase", "integrase", "recombinase"]
    },
    "packaging": {
        "label": "基因组包装与末端酶 (Packaging & Terminase)",
        "keywords": ["terminase", "packaging", "large subunit", "small subunit", "pac", "cos"]
    },
    "all": {
        "label": "全部匹配蛋白质 (All Matched CDS)",
        "keywords": []
    }
}


class ProteinItem(BaseModel):
    """单个蛋白质条目"""
    id: str
    locus_tag: str
    product: str
    translation: str
    length_aa: int
    start: int
    end: int
    strand: str
    category: str = "other"


class MutationSite(BaseModel):
    """单处点突变或变异位点"""
    pos: int
    ref_aa: str
    alt_aa: str
    description: str


class ProteinComparisonRow(BaseModel):
    """单对蛋白质比对明细记录"""
    category: str
    category_label: str
    
    # 样本 A 信息
    sample_a_id: str
    sample_a_tag: str
    sample_a_product: str
    sample_a_len: int
    sample_a_range: str
    sample_a_strand: str
    sample_a_seq: str
    
    # 样本 B 信息
    sample_b_id: Optional[str] = None
    sample_b_tag: Optional[str] = None
    sample_b_product: Optional[str] = None
    sample_b_len: Optional[int] = 0
    sample_b_range: Optional[str] = None
    sample_b_strand: Optional[str] = None
    sample_b_seq: Optional[str] = None
    
    # 比对与变异判定
    match_status: str  # 'identical' (100%), 'highly_conserved' (>=98%), 'divergent' (<98%), 'unique_a', 'unique_b'
    identity_pct: float = 0.0
    diff_count: int = 0
    mutations: List[MutationSite] = []
    length_diff: int = 0
    notes: Optional[str] = None


class ProteinComparisonResult(BaseModel):
    """跨样本比对汇总报告"""
    sample_a_name: str
    sample_b_name: str
    sample_a_total_cds: int
    sample_b_total_cds: int
    
    # 统计指标
    total_compared_pairs: int = 0
    identical_count: int = 0
    conserved_count: int = 0
    divergent_count: int = 0
    unique_a_count: int = 0
    unique_b_count: int = 0
    average_identity_pct: float = 0.0
    
    # 分类汇总统计
    category_summary: Dict[str, Dict[str, int]] = {}
    
    # 明细列表
    rows: List[ProteinComparisonRow] = []


class ProteinComparer:
    """蛋白质比对执行器"""

    def __init__(self):
        self.aligner = PairwiseAligner()
        self.aligner.mode = 'global'
        self.aligner.match_score = 1.0
        self.aligner.mismatch_score = 0.0
        self.aligner.open_gap_score = -1.0
        self.aligner.extend_gap_score = -0.5

    @staticmethod
    def classify_protein(product: str) -> str:
        """依据产品名称自动归入功能大类"""
        p_lower = product.lower()
        for cat_key, cat_info in PROTEIN_CATEGORIES.items():
            if cat_key == "all":
                continue
            if any(k in p_lower for k in cat_info["keywords"]):
                return cat_key
        return "other"

    @classmethod
    def load_proteins_from_annotation(cls, task_dir_or_features: Any) -> List[ProteinItem]:
        """从注释目录 (features.json/GBK) 或特征列表载入蛋白质"""
        proteins: List[ProteinItem] = []

        if isinstance(task_dir_or_features, list):
            # 直接传入的字典列表
            raw_list = task_dir_or_features
        elif isinstance(task_dir_or_features, (str, Path)):
            p = Path(task_dir_or_features)
            feat_json = p / "features.json"
            if feat_json.exists():
                with open(feat_json, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
            else:
                # 尝试解析 GBK
                gbk_files = list(p.glob("*.gbk"))
                if not gbk_files:
                    raise FileNotFoundError(f"目录中未检测到 features.json 或 .gbk 文件: {p}")
                raw_list = []
                for rec in SeqIO.parse(str(gbk_files[0]), "genbank"):
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
                                "strand": "+" if feat.location.strand >= 0 else "-"
                            })
        else:
            raise ValueError(f"不支持的数据源格式: {type(task_dir_or_features)}")

        for item in raw_list:
            seq = item.get("translation") or item.get("protein_sequence") or ""
            if not seq:
                continue
            prod = item.get("product") or "hypothetical protein"
            cat = cls.classify_protein(prod)
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

    def compare_two_samples(
        self,
        sample_a_name: str,
        sample_a_proteins: List[ProteinItem],
        sample_b_name: str,
        sample_b_proteins: List[ProteinItem],
        target_category: str = "all"
    ) -> ProteinComparisonResult:
        """执行两个样本间的全量或指定类别蛋白质比对"""
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
        seq_to_b = {}
        for b in filtered_b:
            if b.translation not in seq_to_b:
                seq_to_b[b.translation] = []
            seq_to_b[b.translation].append(b)

        # 逐个比对样本 A
        for pa in filtered_a:
            best_match: Optional[ProteinItem] = None
            best_identity = 0.0
            best_mutations: List[MutationSite] = []
            best_diff_cnt = 0
            
            # 1. 优先检查 100% 序列完全相同的候选
            if pa.translation in seq_to_b and seq_to_b[pa.translation]:
                # 寻找未使用的或同名匹配
                exact_cand = None
                for b_cand in seq_to_b[pa.translation]:
                    if b_cand.id not in matched_b_ids:
                        exact_cand = b_cand
                        break
                if not exact_cand:
                    exact_cand = seq_to_b[pa.translation][0]
                
                best_match = exact_cand
                best_identity = 100.0
                best_mutations = []
                best_diff_cnt = 0
            else:
                # 2. 同名优先检索与高相似度序列对齐
                pa_prod_lower = pa.product.lower()
                candidates = [b for b in filtered_b if b.id not in matched_b_ids]
                
                # 优先比对同名或相同分类的蛋白
                same_prod_cands = [b for b in candidates if b.product.lower() == pa_prod_lower]
                search_cands = same_prod_cands if same_prod_cands else candidates

                for pb in search_cands:
                    ident, muts, diffs = self._align_and_diff(pa.translation, pb.translation)
                    if ident > best_identity:
                        best_identity = ident
                        best_match = pb
                        best_mutations = muts
                        best_diff_cnt = diffs

            # 判定匹配状态
            if best_match and best_identity >= 40.0:
                matched_b_ids.add(best_match.id)
                if best_identity >= 99.99:
                    match_status = "identical"
                elif best_identity >= 95.0:
                    match_status = "highly_conserved"
                else:
                    match_status = "divergent"

                cat_info = PROTEIN_CATEGORIES.get(pa.category, {"label": "其他功能蛋白"})
                rows.append(ProteinComparisonRow(
                    category=pa.category,
                    category_label=cat_info.get("label", pa.category),
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
                    length_diff=abs(pa.length_aa - best_match.length_aa)
                ))
            else:
                # 样本 A 独有
                cat_info = PROTEIN_CATEGORIES.get(pa.category, {"label": "其他功能蛋白"})
                rows.append(ProteinComparisonRow(
                    category=pa.category,
                    category_label=cat_info.get("label", pa.category),
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
                    mutations=[]
                ))

        # 检查样本 B 中独有的未配对蛋白
        for pb in filtered_b:
            if pb.id not in matched_b_ids:
                cat_info = PROTEIN_CATEGORIES.get(pb.category, {"label": "其他功能蛋白"})
                rows.append(ProteinComparisonRow(
                    category=pb.category,
                    category_label=cat_info.get("label", pb.category),
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
                    mutations=[]
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

    def _align_and_diff(self, seq_a: str, seq_b: str) -> Tuple[float, List[MutationSite], int]:
        """执行氨基酸序列全局比对并提取突变详情"""
        if not seq_a or not seq_b:
            return 0.0, [], max(len(seq_a), len(seq_b))
        
        if seq_a == seq_b:
            return 100.0, [], 0

        # 快速模式：若长度相同，直接逐字符比对，极速且无对齐溢出风险
        if len(seq_a) == len(seq_b):
            matches = sum(1 for ca, cb in zip(seq_a, seq_b) if ca == cb)
            diff_count = len(seq_a) - matches
            mutations: List[MutationSite] = []
            for idx, (ca, cb) in enumerate(zip(seq_a, seq_b)):
                if ca != cb:
                    if len(mutations) < 50:
                        mutations.append(MutationSite(
                            pos=idx + 1,
                            ref_aa=ca,
                            alt_aa=cb,
                            description=f"位置 {idx + 1}: {ca} -> {cb}"
                        ))
            ident = (matches / len(seq_a)) * 100.0
            return round(ident, 2), mutations, diff_count

        # 长度不同时：调用 PairwiseAligner 全局比对
        try:
            alignments = self.aligner.align(seq_a, seq_b)
            # 使用 next(iter(...)) 安全获取首个最优比对，避免触发 len() 路径数溢出
            best_aln = next(iter(alignments), None)
            if best_aln is None:
                return 0.0, [], max(len(seq_a), len(seq_b))

            aln_a, aln_b = best_aln[0], best_aln[1]

            matches = 0
            mutations = []
            diff_count = 0
            real_pos_a = 0

            for ca, cb in zip(aln_a, aln_b):
                if ca != "-":
                    real_pos_a += 1
                
                if ca == cb:
                    matches += 1
                else:
                    diff_count += 1
                    if len(mutations) < 50:
                        if ca != "-" and cb != "-":
                            mutations.append(MutationSite(
                                pos=real_pos_a,
                                ref_aa=ca,
                                alt_aa=cb,
                                description=f"位置 {real_pos_a}: {ca} -> {cb}"
                            ))
                        elif ca == "-":
                            mutations.append(MutationSite(
                                pos=real_pos_a,
                                ref_aa="-",
                                alt_aa=cb,
                                description=f"位置 {real_pos_a}: 插入 {cb}"
                            ))
                        else:
                            mutations.append(MutationSite(
                                pos=real_pos_a,
                                ref_aa=ca,
                                alt_aa="-",
                                description=f"位置 {real_pos_a}: 缺失 {ca}"
                            ))

            ident = (matches / max(len(seq_a), len(seq_b))) * 100.0
            return round(ident, 2), mutations, diff_count
        except Exception as e:
            logger.warning(f"对齐比对异常，使用长度估算: {e}")
            return 0.0, [], max(len(seq_a), len(seq_b))

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
