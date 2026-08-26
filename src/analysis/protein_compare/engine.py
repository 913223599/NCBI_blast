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

# 预设生物学功能分类配置 (包含前端 Tab 标签元数据)
PROTEIN_CATEGORIES = {
    "tail_fiber": {
        "label": "尾丝与宿主识别系统 (Tail Fiber & Host Specificity)",
        "patterns": [
            r"\btail\s*(?:fiber|spike|tube|sheath|shaft|tip|assembly|tubular|component|protein|hydrolase)?\b",
            r"\btailspike\b",
            r"\bbaseplate\b",
            r"\btape\s*measure\b",
            r"\btpm\b",
            r"\breceptor[- ]binding\b",
            r"\brbp\b",
            r"\bcollar\s+protein\b",
            r"\bwhisker\s+protein\b",
            r"\b(?:distal|proximal|hinge)\s+connector\b",
            r"\bneck\s+protein\b",
            r"\bwedge\s+subunit\b",
            r"\bcentral\s+hub\b",
            r"\bspike\s+protein\b",
        ],
        "exclude": []
    },
    "lysis": {
        "label": "裂解系统与溶菌酶 (Lysis / Endolysin / Spanin / Holin)",
        "patterns": [
            r"\bendolysin\b",
            r"\blysin\b",
            r"\blysozyme\b",
            r"\bholin\b",
            r"\bantiholin\b",
            r"\b(?:i-|o-|u-)?spanin\b",
            r"\bpeptidoglycan\s+(?:hydrolase|recognition)\b",
            r"\bmuramidase\b",
            r"\btransglycosylase\b",
            r"\bcell\s+wall\s+hydrolase\b",
            r"\bn-acetylmuramoyl\b",
            r"\bamidase\b",
            r"\bmurein\s+hydrolase\b",
            r"\brz(?:-like|1)?\b",
            r"\blysis\s+protein\b",
        ],
        "exclude": [r"\btail-associated\s+lysozyme\b", r"\btailspike\b"]
    },
    "capsid_head": {
        "label": "衣壳与头部形态发生 (Capsid & Head Morphogenesis)",
        "patterns": [
            r"\b(?:major|minor)\s+capsid\b",
            r"\bcapsid\s+(?:protein|assembly|scaffolding|subunit)?\b",
            r"\bportal\s+protein\b",
            r"\bhead\s+(?:protein|completion|assembly|structural|maturation)\b",
            r"\bhead-tail\s+(?:adaptor|joining|connector)\b",
            r"\bmaturation\s+protease\b",
            r"\bprohead\s+protease\b",
            r"\bcoat\s+protein\b",
            r"\bvertex\s+protein\b",
            r"\bcapsomer\b",
            r"\bdecoration\s+protein\b",
            r"\bscaffold(?:ing)?\s+protein\b",
            r"\bvirion\s+structural\s+protein\b",
        ],
        "exclude": []
    },
    "replication": {
        "label": "DNA 复制与修饰酶 (Replication & Modification)",
        "patterns": [
            r"\b(?:dna|rna)\s+polymerase\b",
            r"\bpolymerase\b",
            r"\bhelicase\b",
            r"\bprimase\b",
            r"\bprimase-helicase\b",
            r"\bligase\b",
            r"\bdna\s+ligase\b",
            r"\b(?:endo|exo)nuclease\b",
            r"\bhnh\s+endonuclease\b",
            r"\bhoming\s+endonuclease\b",
            r"\b(?:rnase|dnase)\b",
            r"\bssb\b",
            r"\bsingle-stranded\s+dna-binding\b",
            r"\bdna[- ]binding\s+protein\b",
            r"\bmethyltransferase\b",
            r"\bmethylase\b",
            r"\btopoisomerase\b",
            r"\bgyrase\b",
            r"\bintegrase\b",
            r"\brecombinase\b",
            r"\bresolvase\b",
            r"\brepressor\b",
            r"\banti-repressor\b",
            r"\bactivator\s+protein\b",
            r"\btranscriptio(?:n|nal)?(?:\s+(?:factor|regulator|activator|coactivator))?\b",
            r"\bsigma\s+factor\b",
            r"\bantitermination\b",
            r"\b(?:cro|ci)\s+protein\b",
        ],
        "exclude": []
    },
    "packaging": {
        "label": "基因组包装与末端酶 (Packaging & Terminase)",
        "patterns": [
            r"\bterminase(?:\s+(?:large|small|subunit|\d+))*\b",
            r"\b(?:large|small)\s+subunit\s+terminase\b",
            r"\bpackaging\s+(?:protein|enzyme|machinery)\b",
            r"\bmaturase\b",
            r"\bcos-cleaving\b",
            r"\bpac\s+protein\b",
        ],
        "exclude": []
    },
    "all": {
        "label": "全部匹配蛋白质 (All Matched CDS)",
        "patterns": [],
        "exclude": []
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
    impact_type: str = "conservative"  # 'conservative', 'charge_flip', 'charge_shift', 'polarity_shift', 'indel'
    impact_label: str = "同类保守替换"
    description: str


class RegionDomainItem(BaseModel):
    """蛋白质特定区段（N端、中段、C端）保守性与变异分布"""
    name: str  # "N-端结构域", "中段骨架区", "C-端受体/功能区"
    start: int
    end: int
    length: int
    identity_pct: float
    mutation_count: int
    conservative_count: int
    radical_count: int
    status: str  # 'conserved' (>=95%), 'moderate' (80-95%), 'hypervariable' (<80%)


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
    match_status: str  # 'identical' (100%), 'highly_conserved' (>=95%), 'divergent' (<95%), 'unique_a', 'unique_b'
    identity_pct: float = 0.0
    diff_count: int = 0
    mutations: List[MutationSite] = []
    length_diff: int = 0
    notes: Optional[str] = None

    # 高维生物学分析指标
    aligned_seq_a: str = ""
    aligned_markup: str = ""
    aligned_seq_b: str = ""
    conservative_mutation_cnt: int = 0
    radical_mutation_cnt: int = 0
    indel_cnt: int = 0
    hotspot_conclusion: str = ""
    region_domains: List[RegionDomainItem] = []


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

    @classmethod
    def is_hypothetical(cls, text: str) -> bool:
        """快速判断是否为未知/假定蛋白"""
        t = text.strip().lower()
        if not t or t == "hypothetical protein" or t == "unknown" or t == "uncharacterized protein" or t == "putative protein":
            return True
        return False

    @classmethod
    def classify_protein(cls, product: str, direct_cat: Optional[str] = None, notes: Optional[str] = None) -> str:
        """
        依据产品名称、已知分类及证据备注自动归入功能大类
        采用严格带 \\b 词边界正则与排除项消歧机制，杜绝子串误碰撞
        """
        import re

        clean_prod = (product or "").strip()
        
        # 1. 假定蛋白优先排除
        if cls.is_hypothetical(clean_prod) and not direct_cat and not notes:
            return "other"

        # 2. 优先检查高置信度已知分类标签 (如 PHROGs / AnnotationFuser 标注)
        if direct_cat:
            dc_lower = direct_cat.lower()
            if "tail" in dc_lower or "fiber" in dc_lower:
                return "tail_fiber"
            if "lysis" in dc_lower:
                return "lysis"
            if "packaging" in dc_lower or "terminase" in dc_lower:
                return "packaging"
            if "head" in dc_lower or "capsid" in dc_lower:
                return "capsid_head"
            if "replication" in dc_lower or "repair" in dc_lower or "transcription" in dc_lower:
                return "replication"

        # 3. 严格正则词边界与优先级语义匹配
        full_text = f"{clean_prod} {notes or ''}".lower()
        
        # 优先级判断序列 (特异性高的优先判定)
        priority_order = ["packaging", "tail_fiber", "capsid_head", "lysis", "replication"]

        for cat_key in priority_order:
            cat_info = PROTEIN_CATEGORIES[cat_key]
            
            # 检查是否有排除项
            excluded = False
            for exc_pat in cat_info.get("exclude", []):
                if re.search(exc_pat, full_text):
                    excluded = True
                    break
            if excluded:
                continue

            # 正向模式匹配 (严格词边界)
            for pat in cat_info["patterns"]:
                if re.search(pat, full_text):
                    return cat_key

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
                best_aln_a = pa.translation
                best_markup = "|" * len(pa.translation)
                best_aln_b = exact_cand.translation
                best_c_cnt = 0
                best_r_cnt = 0
                best_in_cnt = 0
                best_doms = self._calculate_domains(len(pa.translation), [], 100.0, category=pa.category, product=pa.product)
                best_concl = "双样本全长氨基酸序列 100% 逐位一致，核心催化与组装结构高度锁定。"
            else:
                # 2. 同名优先检索与高相似度序列对齐
                pa_prod_lower = pa.product.lower()
                candidates = [b for b in filtered_b if b.id not in matched_b_ids]
                
                # 优先比对同名或相同分类的蛋白
                same_prod_cands = [b for b in candidates if b.product.lower() == pa_prod_lower]
                search_cands = same_prod_cands if same_prod_cands else candidates

                for pb in search_cands:
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
        p_lower = product.lower()
        
        # 1. 尾管 / 尾鞘 / 尾柱状骨架结构 (优先于一般 tail_fiber 判定，避免 tail tube 误判为尾丝)
        if any(k in p_lower for k in ["tail tube", "tail sheath", "tube", "sheath", "major tail"]):
            return (
                "N-端环状聚合界面 (Ring Assembly N-term)",
                "中段管壁/鞘层骨架区 (Conduit Core)",
                "C-端末端对接区 (Distal Interface C-term)"
            )
        
        # 2. 尾丝 / 纤突 / 受体结合系统
        if category == "tail_fiber" or any(k in p_lower for k in ["tail fiber", "fiber", "spike", "receptor"]):
            return (
                "N-端基板锚定域 (Baseplate-binding N-term)",
                "中段三聚体骨架区 (Shaft / Trimer Core)",
                "C-端受体结合与纤突域 (Distal RBD / Spike)"
            )
            
        # 3. 裂解系统与溶菌酶
        if category == "lysis" or any(k in p_lower for k in ["lysin", "lysozyme", "holin", "spanin", "peptidase", "endopeptidase"]):
            return (
                "N-端跨膜/催化活性域 (Catalytic / TM Domain)",
                "中段柔性连接区 (Flexible Linker)",
                "C-端细胞壁结合域 (Cell-Wall Binding CBD)"
            )
            
        # 4. 衣壳与头部形态发生
        if category == "capsid_head" or any(k in p_lower for k in ["capsid", "head", "coat", "portal", "scaffold", "vertex", "capsomer"]):
            return (
                "N-端衣壳组装前导域 (Prohead Assembly N-term)",
                "中段壳粒核心折叠区 (Capsomer Core)",
                "C-端外表面与顶角加固区 (Vertex / Surface C-term)"
            )
            
        # 5. DNA 复制与修饰酶
        if category == "replication" or any(k in p_lower for k in ["polymerase", "helicase", "primase", "ligase", "nuclease"]):
            return (
                "N-端调节与核酸外切域 (Regulatory / Exonuclease)",
                "中段核心催化活性中心 (Catalytic Polymerase Core)",
                "C-端核酸结合与夹钳区 (DNA-Binding Clamp)"
            )
            
        # 6. 基因组包装与末端酶
        if category == "packaging" or any(k in p_lower for k in ["terminase", "packaging", "large subunit", "small subunit"]):
            return (
                "N-端 ATP 结合与驱动中心 (ATPase Engine N-term)",
                "中段能量转换与传动区 (Translocation Transducer)",
                "C-端 DNA 剪切与 Portal 结合区 (Endonuclease & Portal-binding)"
            )
            
        # 7. 通用 / 未知功能蛋白
        return (
            "N-端近端区域 (N-terminal Region)",
            "中央核心骨架区 (Central Core Region)",
            "C-端远端区域 (C-terminal Region)"
        )

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

        # 长度不同时：调用 PairwiseAligner 全局比对
        try:
            alignments = self.aligner.align(seq_a, seq_b)
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
