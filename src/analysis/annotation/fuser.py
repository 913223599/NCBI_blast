# -*- coding: utf-8 -*-
"""
功能注释特征融合与互补引擎 (AnnotationFuser)
负责在多引擎级联流水线中，针对前序引擎未注释或仅有部分特征的 CDS，
执行漏斗式属性互补、证据链整合、功能大类自动归并与置信度审计。
"""
import re
import logging
from typing import Dict, List, Any, Optional, Tuple, Set

from .types import FeatureItem, AnnotationSummary

logger = logging.getLogger("analysis.annotation.fuser")


class AnnotationFuser:
    """注释特征融合与补全器"""

    # 纯占位型假定蛋白描述 (在 clean_product_text 中统一规范化为 "hypothetical protein")
    GENERIC_HYPOTHETICAL_PATTERNS = [
        r"^(?:conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:hypothetical|hyphothetical)(?:\s+(?:phage\s+)?protein)?$",
        r"^(?:conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:uncharacterized|uncharacterised)(?:\s+(?:phage\s+)?protein)?$",
        r"^unknown(?:\s+(?:protein|function))?$",
        r"^(?:putative|predicted|conserved)\s+(?:phage\s+|bacteriophage\s+)?protein$",
        r"^protein\s+of\s+unknown\s+function$",
        r"^phage\s+protein$",
        r"^unnamed(?:\s+protein(?:\s+product)?)?$",
        r"^(?:none|na|unassigned|unsorted)$",
    ]

    # 广义未表征/未知功能蛋白模式 (含 DUF/UPF/PHA/ORF/gp 编号及未知功能家族，归类为 Hypothetical)
    UNANNOTATED_PATTERNS = [
        r"^(?:gp\d+(?:[./_]\d+)?\s+|conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:hypothetical|hyphothetical)\b",
        r"^(?:gp\d+(?:[./_]\d+)?\s+|conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:uncharacterized|uncharacterised)\b",
        r"\b(?:unknown|unkown|unknwon)\s+function\b",
        r"^unknown(?:\s+(?:protein|function))?$",
        r"^(?:putative|predicted|conserved)\s+(?:phage\s+|bacteriophage\s+)?protein$",
        r"^protein\s+conserved\s+in\s+bacteria$",
        r"^protein\s+of\s+(?:unknown|unkown|unknwon)\s+function\b",
        r"\bdomain\s+of\s+(?:unknown|unkown|unknwon)\s+function\b",
        r"\bfamily\s+of\s+(?:unknown|unkown|unknwon)\s+function\b",
        r"^(?:putative\s+|conserved\s+)?phage\s+protein(?:\s+gp\d+(?:[./_]\d+)*)?$",
        r"^bacteriophage\s+[a-z0-9_-]+\s+protein$",
        r"^prophage\s+[a-z0-9_-]+\s+protein\b",
        r"^unnamed(?:\s+protein(?:\s+product)?)?$",
        r"^(?:pfam\s*:\s*)?(?:phage\s+)?(?:protein\s+)?gp\d+(?:[./_\s]\s*(?:gp)?\d+)*(?:\s+(?:domain-containing|family)\s+protein)?$",
        r"^[a-z]+\d*\s+gp\d+(?:\s+family\s+protein)?$",
        r"^[a-z]+\d*gp\d+$",
        r"^orf\s*\d+$",
        r"\bduf\s*\d+\b",
        r"\bupf\s*\d+\b",
        r"^pha\s*\d+(?:\s+domain-containing\s+protein)?$",
        r"^\d+\.\d+\s+domain-containing\s+protein$",
        r"^d\d+\s+protein$",
        r"^protein\s+y[a-z]{2}[a-z0-9]?$",
        r"^tigrfam\s+phage$",
        r"^domain,\s*protein$",
        r"^psort\s+location\b",
        r"^(?:none|na|unassigned|unsorted)$",
    ]

    CATEGORY_RULES = [
        # 1. 尾部与尾丝吸附 (Tail & Host Interaction)
        # 优先捕获以 baseplate / tail 开头的尾部穿刺溶菌酶复合体 (如 baseplate hub subunit and tail lysozyme)，防止被 Lysis 误抓
        ("Tail & Host Interaction", [
            r"^(?:baseplate|tail)\b.*\blysozyme\b",
            r"^(?!.*\bhead\s+fiber\b).*\b(?:tail|baseplate|base\s*plate|tape\s*measure|tail\s*fiber|tail\s*fibre|tailfiber|tail\s*spike|tailspike|tail\s*tube|tail\s*sheath|tail\s*assembly|tail\s*needle|tail\s*protein|major\s*tail|minor\s*tail|tail\s*terminator|tail\s*completion|head-tail|head\s+to\s+tail|adaptor\s*ad\d+|neck\s*protein|neck1|neck\s*whisker|fibritin|collar|receptor-binding|receptor\s*binding|reticulocyte-binding|adhesin|adsorption|host\s*range|host\s*specificity|tail\s*chaperone|tail\s*assembly\s*chaperone|tail\s*fiber\s*assembly|gp37|gp38|pectate\s*lyase|depolymerase|polysaccharide\s*lyase|endosialidase|sialidase|neuraminidase|hyaluronidase|ig\s*domain|ig-like|sh3\s*beta[- ]barrel|fibronectin\s*type|pkd\s*domain|lectin|adaptator|fimbria|fimbrial)\b"
        ]),
        # 2. 头部与衣壳包装 (Head & Packaging)
        # 优先捕获 internal virion protein (含 with endolysin domain)，因为其核心身份是注射通道内部病毒颗粒结构蛋白
        ("Head & Packaging", [
            r"^internal\s+virion\s+protein\b",
            r"\b(?:capsid|capsomer|coat\s*protein|portal|terminase|terminase\s*large\s*subunit|terminase\s*small\s*subunit|head\s*protein|major\s*head|minor\s*head|head\s*fiber|head\s*completion|scaffold|scaffolding|prohead|head\s*closure|head\s*decoration|head\s*maturation|head\s*morphogenesis|head\s*vertex|head\s*portal|maturation\s*protease|head\s*assembly|major\s*capsid|minor\s*capsid|virion\s*structural|virion\s*morphogenesis|internal\s*virion|structural\s*protein|encapsulin|head-tail\s*connector|mu\s*protein\s*f|hoc-like|pmg[bg]-like)\b"
        ]),
        # 3. 宿主裂解系统 (Lysis)
        # 排除脱酰胺酶 (deamidase) 与转酰胺酶 (amidotransferase)
        ("Lysis", [
            r"^(?!.*\b(?:deamidase|amidotransferase)\b).*\b(?:endolysin|lysin|holin|antiholin|anti-holin|pinholin|spanin|i-spanin|o-spanin|rz-like|rz1|[a-z0-9'-]*muramidase|[a-z0-9'-]*amidase|ami\s*2|ami\s*3|nlpc\s*p60|nlp\s*p60|endopeptidase|carboxypeptidase|peptidoglycan\s*hydrolase|peptidoglycan\s*catabolic|murein\s*hydrolase|cell\s*wall\s*hydrolase|lytic\s*transglycosylase|transglycosylase|chitinase|chitin\s*catabolic|lysozyme|lysis\s*inhibition|lysis\s*inhibitor|riia|riib|spackle|lysis)\b"
        ]),
        # 4. 溶原整合与切除 (Integration & Excision)
        ("Integration & Excision", [
            r"\b(?:integrase|dna\s*integration|excisionase|excise|transposase|transposase-like|site-specific\s*recombinase|tyrosine\s*recombinase|tyrosine-type\s*recombinase|serine\s*recombinase|prophage\s*integrase|prophage\s*excisionase|recombination\s*directionality\s*factor|rdf|xis|dna\s*invertase|invertase\s*pin|mobile\s*element|intein|ist[ab](?:-like)?)\b"
        ]),
        # 5. 转录调控与开关 (Transcription & Regulation)
        # 必须在 Replication & Repair 之前捕获 RNA polymerase 及各类转录调控因子
        ("Transcription & Regulation", [
            r"\b(?:rna\s*polymerase|repressor|anti-?repressor|antirepressor|activator|regulator|regulatory\s*protein|regulatory\s*subunit|response\s*regulator|promoter|transcription|transcriptional|transcrition\s*regulator|cro|c1\s*repressor|ci\s*repressor|cii(?:-like)?|ciii|anti-?termination|anti-?terminator|anti-?sigma|sigma\s*factor|sigma[- ]?[a-z0-9]+|modulator|helix[- ]turn[- ]helix|hth|hth-type|csra(?:-like)?|gntr|marr|lysr(?:-like|-type)?|arcr?|arsr\d*|fmdb(?:-like)?|mota(?:-like)?|motb(?:-like)?|dksa(?:-like)?|parb(?:-like)?|para\b|partition\s*protein|plasmid\s*stability|plasmid\s*maintenance|chromosome\s*segregation|whib(?:-like)?|lsr2(?:-like)?|ead|ea22(?:-like)?|eaa|translation\s*repressor|translation\s*inhibitor|translation\s*initiation\s*factor|ribosome[- ]associated\s*(?:translation\s*)?inhibitor|peptide\s*chain\s*release\s*factor|raia)\b"
        ]),
        # 6. DNA 复制与重组修复 (Replication & Repair)
        # 注意排除 anti-restriction nuclease (归属防御互作) 以及代谢中的 CoA ligase / tRNA splicing ligase
        ("Replication & Repair", [
            r"^(?!.*\b(?:anti-?restriction|coenzyme\s*a\s*ligase|coa\s*ligase|trna\s*splicing\s*ligase)\b).*\b(?:dna\s*polymerases?|polymerases?|reverse\s*transcriptase|helicases?|[a-z0-9'-]*helicases?|primases?|primosom(?:al|e)|dna\s*ligases?|rna\s*ligases?|ligase\s*activity|ssb|single-stranded\s*dna|single\s*strand\s*dna|single[- ]strand\s*binding|single[- ]strand\s*annealing|ssdna|topoisomerases?|gyrases?|endonucleases?|exonucleases?|[a-z0-9'-]*nucleases?|giy-yig|vrr[- ]nuc|rnase|dnase|exoribonucleases?|endoribonucleases?|dna\s*repair|dna\s*replication|chromosome\s*replication|dna\s*metabolic\s*process|holliday|rusa(?:-like)?|ruvc(?:-like)?|recu|rece(?:-like)?|reca(?:-like)?|recb|recc|recd|rect(?:-like|\s*family)?|sbcc(?:-like)?|sbcd(?:-like)?|uvsy(?:-like)?|uvsx(?:-like)?|dpra(?:-like)?|dna\s*protecting\s*protein|erf(?:-like)?|sak4(?:-like)?|ninb|ning|rap|ninx|dna[- ]binding|sequence-specific\s*dna\s*binding|primase-helicase|dead\/deah|snf2|ftsk|spoiiie|dnac(?:-like)?|dnab(?:-like)?|dda(?:-like)?|denb(?:-like)?|dna\s*annealing|recombination[- ]mediator|junction\s*specific|replication\s*initiation|replication\s*protein|replication\s*origin|clamp\s*loader|processivity\s*factor|dna-dependent\s*atpase|umuc|umud(?:-like)?|gam(?:-like)?|dna\s*end\s*protector|end\s*protection|dna\s*transfer\s*protein|gene\s*47)\b"
        ]),
        # 7. 宿主防御与互作 (Defense & Host Interaction)
        # 注意将 tRNA methyltransferase 留给 Metabolism & AMG，其余 DNA methyltransferase / methylase 留在此处作为限制修饰逃逸
        ("Defense & Host Interaction", [
            r"\b(?:anti-?crispr|acranker|acr(?:\b|(?:i{1,3}|iv|v|vi|[ef])\d*[a-z0-9]*)|crispr|cas[0-9]+|defensefinder|anti-?defense|anti-?cbass|anti-?dart|nadar|thoeris|darb(?:-like)?|dara|lar(?:-like)?|arda\b|mom-like\s*dna\s*modification|hns\s*inhibition|h-ns\s*inhibition|kil\s*protein|septation\s*inhibition|restriction\s*alleviation|anti-?restriction|antirestriction|restriction\s*enzyme|restriction-modification|mrcbc|superinfection\s*exclusion|superinfection|immunity|abortive\s*infection|abi(?:-like)?|toxin-antitoxin|antitoxin|toxin|leukocidin|leukocicin|hica|hicb(?:-like)?|rele(?:-like)?|colicin|tcib(?:-like)?|tellurite\s*resistance|acridine\s*resistance|arsenite\s*resistance|fosfomycin\s*resistance|beta-lactamase|penicillin\s*binding|oxa-\d+|virulence|pathogenesis|hemolysin|ndd(?:-like)?|nucleoid\s*disruption|dmd|inhibitor\s*of\s*host\s*lon)\b",
            r"^(?!.*\btrna\b).*\b(?:dna\s*methyltransferase|cytosine\s*methyltransferase|cytosine-specific\s*dna\s*methylase|adenine\s*methylase|n-6\s*dna\s*methylase|dna\s*methylase|methylase|sam-dependent\s*methyltransferase)\b"
        ]),
        # 8. 辅助代谢基因 (Metabolism & AMG)
        ("Metabolism & AMG", [
            r"\b(?:phoh(?:-like)?|phosphate\s*starvation|p-starvation\s*inducible|quec(?:-like)?|queuosine|dutpase|produces\s*dump|reductive\s*methylation\s*of\s*2'-deoxyuridine|mazg(?:-like)?|ribonucleotide\s*reductase|ribonucleoside[- ]diphosphate\s*reductase|ribonucleoside\s*reductase|nrdd(?:-like)?|nrd[abefh]|thioredoxin|glutaredoxin|ferredoxin|flavodoxin|plastocyanin\w*|photosystem\s*(?:i|ii)\b|psb[ad]\b|high\s*light\s*inducible|cp12\s*protein|antenna\s*protein|folate|dihydrofolate\s*reductase|thymidylate\s*synthase|thymidine\s*kinase|dcmp\s*deaminase|transketolase|transaldolase(?:-like)?|molybdopterin|porphyrin\s*biosynthe(?:sis|tic)|heme\s*oxygenase|ferrochelatase|chelatase|radical\s*sam|acyl\s*carrier\s*protein|glycyl\s*radical\s*cofactor|grca|sir2|deacetylase|coenzyme\s*a\s*ligase|coa\s*ligase|trna\s*splicing\s*ligase|trna\s*amidotransferase|trna\s*synthetase|trna\b.*methyltransferase|nad\(p\)h-hydrate|desulfurization\s*enzyme|amino\s*acid\s*synthesis|nucleotide\s*biosynthesis|nucleoside\s*metabolic\s*process|glycine\s*cleavage|phenylacetic\s*acid\s*degradation|paaz|paay|auxiliary\s*metabolic|amg)\b",
            r"\b[a-z0-9'-]*(?:kinases?|phosphatases?|phosphoesterases?|phosphodiesterases?|pyrophosphatases?|pyrophosphohydrolases?|phosphohydrolases?|triphosphatases?|diphosphorylases?|phosphorylases?|synthases?|synthetases?|reductases?|dehydrogenases?|oxidoreductases?|hydrolases?|amidohydrolases?|transferases?|transaminases?|aminotransferases?|acyltransferases?|glucosyltransferases?|glycosyltransferases?|formyltransferases?|methyltransferases?|nucleotidyltransferases?|carboxyltransferases?|transacylases?|mutases?|isomerases?|epimerases?|racemases?|decarboxylases?|carboxylases?|dehydratases?|hydratases?|monooxygenases?|dioxygenases?|oxygenases?|oxidases?|peroxidases?|catalases?|desulfurases?|deaminases?|deamidases?|nucleotidases?|esterases?|lipases?|thioesterases?|thiolases?|epoxidases?|lyases?|hydroxylases?|tautomerases?|dextranases?|glutaminases?|asparaginases?)\b"
        ])
    ]

    # 显式结构化分类标签映射 (仅针对 Pharokka/Phold 的结构化分类字段，避免宽泛的 moron / DNA metabolism 误导)
    EXPLICIT_NOTE_CATEGORY_MAP = {
        "head and packaging": "Head & Packaging",
        "tail": "Tail & Host Interaction",
        "connector": "Tail & Host Interaction",
        "lysis": "Lysis",
        "integration and excision": "Integration & Excision",
        "transcription regulation": "Transcription & Regulation",
    }

    @classmethod
    def is_generic_hypothetical(cls, product: Optional[str]) -> bool:
        """判断是否为纯占位型假定蛋白"""
        if not product:
            return True
        p_clean = product.strip().lower()
        if not p_clean:
            return True
        for pat in cls.GENERIC_HYPOTHETICAL_PATTERNS:
            if re.search(pat, p_clean):
                return True
        return False

    @classmethod
    def is_unannotated(cls, product: Optional[str]) -> bool:
        """判断一个功能描述是否为未注释/假定蛋白/未知功能结构域(DUF/UPF/PHA/ORF)"""
        if not product:
            return True
        p_clean = product.strip().lower().replace("_", " ")
        if not p_clean:
            return True
        for pat in cls.UNANNOTATED_PATTERNS:
            if re.search(pat, p_clean):
                return True
        return False

    @classmethod
    def _match_category_rules(cls, text: str) -> Optional[str]:
        """按规则顺序匹配功能大类，未命中返回 None (将下划线与 URL 分号转为空格以确保词边界 \\b 精确生效)"""
        t_norm = text.lower().replace("_", " ").replace("%3b", ";")
        if re.search(r"\brecombinase\b", t_norm) and not re.search(r"\b(?:exonuclease|endonuclease|holliday|rusa|ruvc|recu|uvsx|reca|rad51|homologous)\b", t_norm):
            return "Integration & Excision"
        for cat_name, patterns in cls.CATEGORY_RULES:
            for pat in patterns:
                if re.search(pat, t_norm):
                    return cat_name
        return None

    @classmethod
    def infer_category(cls, product: Optional[str], notes: Optional[str] = None) -> str:
        """
        依据产品描述与结构域特征，自动归类到标准生物学功能模块
        规则: 假定蛋白与未知功能结构域(DUF等)一律归 Hypothetical; 已知功能以 product 为准，
        notes 仅在 product 未命中任何规则时提取显式结构化分类标签，绝不盲目全文匹配 notes
        """
        if cls.is_unannotated(product):
            return "Hypothetical"

        cat = cls._match_category_rules((product or "").strip().lower())
        if cat:
            return cat

        if notes:
            n_lower = notes.lower()
            for m in re.finditer(r"(?:category|phold\s+structure):\s*([a-z\s,_-]+?)(?:;|$)", n_lower):
                raw_tag = m.group(1).strip()
                if raw_tag in cls.EXPLICIT_NOTE_CATEGORY_MAP:
                    return cls.EXPLICIT_NOTE_CATEGORY_MAP[raw_tag]

        return "Other Functional"

    @classmethod
    def clean_product_text(cls, raw_prod: Optional[str]) -> str:
        """清洗并规范化产品名称"""
        if not raw_prod:
            return "hypothetical protein"
        from urllib.parse import unquote
        cleaned = unquote(raw_prod.strip())
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        cleaned = cleaned.replace("%20", " ").replace("%2C", ",").replace("%3B", ";")
        if not cleaned or cls.is_generic_hypothetical(cleaned):
            return "hypothetical protein"
        return cleaned

    @classmethod
    def complement_single_feature(
        cls,
        base_feat: FeatureItem,
        candidate_data: Dict[str, Any],
        engine_name: str
    ) -> bool:
        """
        尝试用新引擎的数据补充单个特征
        返回是否进行了有效补充
        """
        is_updated = False
        new_prod = cls.clean_product_text(candidate_data.get("product"))
        
        # 1. 产物描述补全: 若原先未注释，而新候选有确切功能，则更新
        if cls.is_unannotated(base_feat.product) and not cls.is_unannotated(new_prod):
            base_feat.product = new_prod
            base_feat.source_engine = engine_name
            is_updated = True

        # 2. 基因名称补全
        new_gene = candidate_data.get("gene_name") or candidate_data.get("gene")
        if new_gene and not base_feat.gene_name:
            base_feat.gene_name = str(new_gene).strip()
            is_updated = True

        # 3. EC 酶学编号补全
        new_ec = candidate_data.get("ec_number") or candidate_data.get("ec")
        if new_ec and not base_feat.ec_number:
            base_feat.ec_number = str(new_ec).strip()
            is_updated = True

        # 4. COG 分类补全
        new_cog = candidate_data.get("cog")
        if new_cog and not base_feat.cog:
            base_feat.cog = str(new_cog).strip()
            is_updated = True

        # 5. PHROG 与功能分类大类互补
        if candidate_data.get("phrog") and not base_feat.phrog:
            base_feat.phrog = str(candidate_data["phrog"]).strip()
            is_updated = True
        if candidate_data.get("function") and not base_feat.function:
            base_feat.function = str(candidate_data["function"]).strip()
            is_updated = True
        if candidate_data.get("score") and not base_feat.score:
            base_feat.score = str(candidate_data["score"]).strip()
        if candidate_data.get("inference") and not base_feat.inference:
            base_feat.inference = str(candidate_data["inference"]).strip()

        # 5. 证据链记录与 Notes 追加
        evidence_note = candidate_data.get("evidence") or candidate_data.get("note") or candidate_data.get("notes")
        evidence_tag = f"[{engine_name}]"
        
        if evidence_note:
            note_str = str(evidence_note).strip()
            if note_str not in base_feat.evidence_sources:
                base_feat.evidence_sources.append(f"{evidence_tag} {note_str}")
        elif engine_name not in [e.split()[0].replace("[", "").replace("]", "") for e in base_feat.evidence_sources]:
            base_feat.evidence_sources.append(f"{evidence_tag} Matched")

        # 刷新 Notes 字段
        if base_feat.evidence_sources:
            base_feat.notes = "; ".join(base_feat.evidence_sources)

        # 6. 重新评估功能分类
        base_feat.category = cls.infer_category(base_feat.product, base_feat.notes)

        return is_updated

    @classmethod
    def merge_by_coordinates(
        cls,
        base_features: List[FeatureItem],
        incoming_features: List[FeatureItem],
        engine_name: str,
        overlap_threshold: float = 0.7
    ) -> Tuple[List[FeatureItem], int]:
        """
        基于物理坐标重叠度对两组特征进行流式互补
        """
        updated_count = 0
        
        # 建立按起始位点排序的列表以供快速重叠匹配
        for in_feat in incoming_features:
            if in_feat.feature_type != "CDS" and cls.is_unannotated(in_feat.product):
                continue

            # 寻找在相同链、重叠度 >= overlap_threshold 的匹配特征
            best_match: Optional[FeatureItem] = None
            best_overlap_ratio = 0.0

            for b_feat in base_features:
                if b_feat.feature_type != in_feat.feature_type:
                    continue
                if b_feat.strand != in_feat.strand:
                    continue

                # 计算区间重叠
                overlap_start = max(b_feat.start, in_feat.start)
                overlap_end = min(b_feat.end, in_feat.end)
                if overlap_end >= overlap_start:
                    overlap_len = overlap_end - overlap_start + 1
                    min_len = min(b_feat.length_bp, in_feat.length_bp)
                    ratio = overlap_len / max(1, min_len)
                    if ratio >= overlap_threshold and ratio > best_overlap_ratio:
                        best_overlap_ratio = ratio
                        best_match = b_feat

            if best_match:
                cand_data = {
                    "product": in_feat.product,
                    "gene_name": in_feat.gene_name,
                    "ec_number": in_feat.ec_number,
                    "cog": in_feat.cog,
                    "phrog": in_feat.phrog,
                    "function": in_feat.function,
                    "score": in_feat.score,
                    "inference": in_feat.inference,
                    "evidence": in_feat.notes
                }
                if cls.complement_single_feature(best_match, cand_data, engine_name):
                    updated_count += 1

        return base_features, updated_count

    @classmethod
    def generate_summary(
        cls,
        records_len_dict: Dict[str, int],
        full_seq: str,
        features: List[FeatureItem]
    ) -> AnnotationSummary:
        """统计并生成全套基因组注释指标摘要"""
        from .builtin_annotator import BuiltinAnnotator

        total_len = sum(records_len_dict.values())
        gc_val = BuiltinAnnotator.calculate_gc(full_seq)

        cds_cnt = sum(1 for f in features if f.feature_type == "CDS")
        trna_cnt = sum(1 for f in features if f.feature_type == "tRNA")
        rrna_cnt = sum(1 for f in features if f.feature_type == "rRNA")
        tmrna_cnt = sum(1 for f in features if f.feature_type == "tmRNA")
        crispr_cnt = sum(1 for f in features if f.feature_type == "CRISPR")
        other_cnt = len(features) - (cds_cnt + trna_cnt + rrna_cnt + tmrna_cnt + crispr_cnt)

        annotated_cnt = 0
        hypothetical_cnt = 0
        engine_contrib: Dict[str, int] = {}
        cat_dist: Dict[str, int] = {}

        for f in features:
            if f.feature_type == "CDS":
                if cls.is_unannotated(f.product):
                    hypothetical_cnt += 1
                else:
                    annotated_cnt += 1

                eng = f.source_engine or "Baseline"
                engine_contrib[eng] = engine_contrib.get(eng, 0) + 1

                cat = f.category or cls.infer_category(f.product, f.notes)
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

        total_cds_bp = sum(f.length_bp for f in features if f.feature_type == "CDS")
        coding_density = round((total_cds_bp / max(1, total_len)) * 100.0, 2)
        avg_len = round(total_cds_bp / max(1, cds_cnt), 1)

        return AnnotationSummary(
            total_length=total_len,
            num_contigs=len(records_len_dict),
            gc_content=gc_val,
            cds_count=cds_cnt,
            trna_count=trna_cnt,
            rrna_count=rrna_cnt,
            tmrna_count=tmrna_cnt,
            crispr_count=crispr_cnt,
            other_count=other_cnt,
            total_features=len(features),
            annotated_count=annotated_cnt,
            hypothetical_count=hypothetical_cnt,
            coding_density_pct=coding_density,
            avg_gene_length=avg_len,
            engine_contributions=engine_contrib,
            category_distribution=cat_dist
        )

    @classmethod
    def integrate_safety_audit(cls, features: List[Any], safety_audit: Dict[str, Any]) -> int:
        """
        将生物安全审计与 Anti-CRISPR 逃逸因子深度反向回写融合至各 FeatureItem (兼容对象与字典)，
        把假定蛋白直接升级为明确的生物学功能描述 (如 anti-CRISPR protein)，并在注释记录中保留实验证据。
        """
        if not safety_audit or not features:
            return 0

        feat_map: Dict[str, Any] = {}
        for f in features:
            fid = f.id if isinstance(f, FeatureItem) else f.get("id")
            lt = f.locus_tag if isinstance(f, FeatureItem) else f.get("locus_tag")
            pid = f.protein_id if isinstance(f, FeatureItem) else f.get("protein_id")
            if fid:
                feat_map[fid] = f
            if lt:
                feat_map[lt] = f
            if pid:
                feat_map[pid] = f

        updated_count = 0

        def get_val(item: Any, key: str, default: Any = None) -> Any:
            return getattr(item, key, default) if isinstance(item, FeatureItem) else item.get(key, default)

        def set_val(item: Any, key: str, value: Any):
            if isinstance(item, FeatureItem):
                setattr(item, key, value)
            elif isinstance(item, dict):
                item[key] = value

        # 1. 融合 Anti-CRISPR (Acr) 宿主防御逃逸因子
        for acr in safety_audit.get("anti_crispr_genes", []):
            cid = acr.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue

            acr_source = str(acr.get("source") or "Acrank_er").strip()
            ident = acr.get("identity", 0)
            e_val = acr.get("evalue", "1e-10")
            evidence_note = f"Anti-CRISPR: {acr_source} (Identity: {ident}%, E-value: {e_val})"

            curr_prod = get_val(target_feat, "product", "")
            is_pure_prediction = "acranker" in acr_source.lower()

            # 仅当来源具有明确实验/比对验证依据 (非纯 Acranker 机器学习预测) 且一致性 >= 80% 时，才改写假定蛋白为具体功能
            if cls.is_unannotated(curr_prod) and not is_pure_prediction and ident >= 80.0:
                clean_acr_name = f"anti-CRISPR protein ({acr_source})" if acr_source != "Acr Protein" else "anti-CRISPR protein"
                set_val(target_feat, "product", clean_acr_name)
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "PhageScope")
                updated_count += 1
            
            # 在 notes 与 evidence_sources 中追加审计证据标记
            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "Anti-CRISPR" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {evidence_note}")
            else:
                set_val(target_feat, "notes", evidence_note)

            curr_ev_list = list(get_val(target_feat, "evidence_sources") or [])
            ev_tag = f"[Anti-CRISPR] {acr_source} (Identity: {ident}%, E-value: {e_val})"
            if not any("Anti-CRISPR" in ev for ev in curr_ev_list):
                curr_ev_list.append(ev_tag)
                set_val(target_feat, "evidence_sources", curr_ev_list)

        # 2. 融合 AMR 耐药基因
        for amr in safety_audit.get("amr_genes", []):
            cid = amr.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue
            desc = amr.get("description") or "AMR gene"
            ident = amr.get("identity", 0)
            note_str = f"CARD AMR: {desc} (Identity: {ident}%)"
            
            curr_prod = get_val(target_feat, "product", "")
            if cls.is_unannotated(curr_prod):
                set_val(target_feat, "product", f"antibiotic resistance protein ({desc})")
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "CARD")
                updated_count += 1

            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "CARD AMR" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {note_str}")
            else:
                set_val(target_feat, "notes", note_str)

        # 3. 融合 VFDB 毒力因子
        for vf in safety_audit.get("virulent_factors", []):
            cid = vf.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue
            desc = vf.get("description") or "Virulence Factor"
            ident = vf.get("identity", 0)
            note_str = f"VFDB: {desc} (Identity: {ident}%)"

            curr_prod = get_val(target_feat, "product", "")
            if cls.is_unannotated(curr_prod):
                set_val(target_feat, "product", f"virulence factor ({desc})")
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "VFDB")
                updated_count += 1

            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "VFDB" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {note_str}")
            else:
                set_val(target_feat, "notes", note_str)

        return updated_count
