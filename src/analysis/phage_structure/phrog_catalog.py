# -*- coding: utf-8 -*-
"""
PHROGs 结构角色映射目录与精细形态学词典 (PHROG Structural Catalog)

职责：
1. 从 database/pharokka_db/phrog_annot_v4.tsv 与 phold_annots_updated.tsv 装载全量 PHROG 注解；
2. 精准区分高混淆条目，防止重大生信误分类：
   - 区分短尾 "tail tubular protein" (TTPA_B) 与长/肌尾 "tail tube protein" (TTP)；
   - 区分真卷尺 "tail length tape measure protein" (TMP) 与伴侣 "tail length tape measure protein chaperone" (TAP)；
   - 区分噬菌体收缩鞘 "tail sheath" (TSP) 与宿主 VI 型分泌系统 "T6SS tssB/tssC/hcp/vgrG" (T6SS_CONFOUNDER)；
   - 识别 Virfam 头-颈-尾连接器家族 (Ad1/Ad2/Ad3, Hc1/Hc2/Hc3, Neck1/Ne1, Tail terminator) 与非有尾标记 (Inoviridae/Microviridae)。
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...workbench.models.tool_config import ToolConfig

logger = logging.getLogger("analysis.phage_structure.catalog")

# 结构角色中文显示名称
ROLE_LABELS_CN: Dict[str, str] = {
    "TSP": "尾鞘蛋白 (TSP, 肌尾核心)",
    "TTP": "尾管蛋白 (TTP)",
    "BASEPLATE_MYO": "肌尾/收缩型基板组件",
    "FIBRITIN_COLLAR": "颈须/短尾丝 (T4样辅助)",
    "MTP": "主要尾蛋白 (MTP)",
    "TAP": "尾装配伴侣蛋白 (TAP/Chaperone)",
    "TMP": "卷尺蛋白 (TMP, 分子标尺)",
    "DIT": "远端尾蛋白 / 尾尖 (Dit/Tal)",
    "TTPA_B": "短尾管状蛋白 A/B (TTPA/B, 短尾核心)",
    "INTERNAL_VIRION": "内部病毒粒注射通道蛋白 (短尾特征)",
    "TAIL_NEEDLE": "短尾刺针蛋白 (Tail Needle)",
    "COLLAR_PODO": "项圈/前颈附器蛋白 (Podo特征)",
    "TAIL_FIBER_RBP": "尾丝 / 尾刺 / 受体结合蛋白 (RBP)",
    "TAIL_OTHER": "其他尾部结构/次要尾蛋白",
    "CONN_AD1": "连接适配体 Ad1 (Type 1)",
    "CONN_AD2": "连接适配体 Ad2 (Type 2)",
    "CONN_AD3": "连接适配体 Ad3 (Type 3/短尾)",
    "CONN_HC1": "头部闭合蛋白 Hc1 (Type 1)",
    "CONN_HC2": "头部闭合蛋白 Hc2 (Type 2)",
    "CONN_HC3": "头部闭合蛋白 Hc3 (Type 3/短尾)",
    "CONN_NECK1": "颈部完成蛋白 Neck1/Ne1",
    "CONN_TAIL_TERM": "尾部终止蛋白 (Tr1)",
    "CONN_GENERAL": "通用头-尾连接/颈部蛋白",
    "PORTAL": "头部门户蛋白 (Portal)",
    "TERL": "末端酶大亚基 (TerL)",
    "TERS": "末端酶小亚基 (TerS)",
    "MCP": "主要衣壳蛋白 (MCP)",
    "HEAD_SCAFFOLD_PROTEASE": "衣壳成熟蛋白酶/支架/修饰",
    "LYSIS": "裂解系统 (Endolysin/Holin/Spanin)",
    "INTEGRASE": "溶原整合/切除重组酶",
    "NON_TAILED_MARKER": "非有尾噬菌体特征蛋白 (丝状/微病毒)",
    "NON_TAIL_ENZYME": "非尾部代谢/核酸/调控酶 (护卫屏蔽)",
    "T6SS_CONFOUNDER": "宿主 VI 型分泌系统混淆干扰蛋白",
    "OTHER": "其他辅助或未知蛋白",
}

STRUCTURAL_INDEX_VERSION = "v3_seq_first_multidomain"

STRUCTURAL_PHROG_CATEGORIES = frozenset({
    "head and packaging",
    "connector",
    "tail",
    "lysis",
    "integration and excision",
})

# 将常见混淆酶类与代谢调控蛋白也纳入本地高速验证库，避免在长尾部操纵子内因缺失 HMM 命中伪装成未知大蛋白
NON_TAIL_GUARD_CATEGORIES = frozenset({
    "DNA, RNA and nucleotide metabolism",
    "moron, auxiliary metabolic gene and host takeover",
    "transcription regulation",
})

_EXTRA_INDEX_ANNOT_RE = re.compile(
    r"(?:zot|rna\s+replicase|virion\s+rna\s+polymerase|n4-like\s+rna\s+polymerase|"
    r"membrane\s+dna\s+delivery|genome\s+terminal\s+protein|"
    r"rolling\s+circle\s+dna\s+replication\s+initiation|nicking\s+at\s+origin|"
    r"replication\s+initiation)",
    re.I,
)

_T6SS_RE = re.compile(
    r"\b(?:type\s*(?:vi|6)\s*secretion|t6ss|tss[a-m]\b|icmf|dotu|vgrg|hcp\s+family\s+type\s*vi|evpc|imp[a-m])\b",
    re.I,
)
_NON_TAILED_RE = re.compile(
    r"(?:protein\s+(?:iv|i|ii|iii|v|vi|vii|viii|ix|x)\s+of\s+m13|"
    r"\bzonula\s+occludens\s+toxin\b|\bctxphi\s+zot(?:-like)?\b|\bzot-like\s+toxin\b|\bzot\b|"
    r"\binovirus\b|\bfilamentous\s+phage\b|\bmicrovirus\b|"
    r"\bmajor\s+coat\s+protein\b|\bmajor\s+spike\s+protein\b|\bcoat\s+protein\b|"
    r"\brna\s+replicase(?:\s+beta\s+subunit)?\b|"
    r"\bpilot\s+protein\s+for\s+dna\s+ejection\b|\bdna\s+pilot\b|"
    r"\bpentameric\s+base\s+spike(?:\s+protein)?\b|"
    r"\bmembrane\s+dna\s+delivery\b|"
    r"\bace-like\b)",
    re.I,
)

# 按严格优先级从特定到泛化依次匹配，杜绝包含歧义
_ROLE_RULES: List[Tuple[str, re.Pattern[str]]] = [
    ("T6SS_CONFOUNDER", _T6SS_RE),
    ("NON_TAILED_MARKER", _NON_TAILED_RE),
    # 1. TMP vs Chaperone（必须先把伴侣拆出去！）
    ("TAP", re.compile(r"\b(?:tape\s+measure\s+(?:protein\s+)?chaperone|tail\s+assembly\s+chaperone|tail\s+chaperon(?:e|in)|tail\s+assembly\s+protein|gp[gt]{1,2}\b)", re.I)),
    ("TMP", re.compile(r"\b(?:tail\s+length\s+tape\s+measure\s+protein|tape\s+measure\s+protein|tmps?\b.*phage|tail\s+tape\s+measure)\b", re.I)),
    # 2. 短尾 Podoviridae / Schitoviridae 专有标志（必须在普通 tail tube 和 TSP 之前捕捉！）
    ("TTPA_B", re.compile(r"\b(?:tail\s+tubular\s+protein(?:\s+[ab])?|tubular\s+tail\s+protein)\b", re.I)),
    ("INTERNAL_VIRION", re.compile(r"\binternal\s+virion\s+protein\b|\binternal\s+virion\s+lysozyme\b|\binternal\s+core\s+protein\b|\bvirion\s+rna\s+polymerase\b|\bn4-like\s+rna\s+polymerase\b", re.I)),
    ("TAIL_NEEDLE", re.compile(r"\btail\s+needle(?:\s+protein|\s+knob)?\b", re.I)),
    ("COLLAR_PODO", re.compile(r"\b(?:tail\s+sheath\s+and\s+receptor\s+binding|upper\s+collar\s+connector|pre-neck\s+appendage|tail\s+appendage|appendage(?:\s+protein)?|lower\s+collar)\b", re.I)),
    # 3. 肌尾核心 TSP / TTP / Baseplate / Fibritin
    ("TSP", re.compile(r"\b(?:tail\s+sheath(?:\s+protein|\s+stabilizer)?|contractile\s+tail\s+sheath)\b", re.I)),
    ("FIBRITIN_COLLAR", re.compile(r"\bfibritin(?:\s+neck\s+whisker)?\b|\bshort\s+tail\s+fiber\b", re.I)),
    ("TTP", re.compile(r"\b(?:tail\s+tube(?:\s+protein)?|baseplate\s+tail\s+tube\s+cap|base\s*plate\s+tail\s+tube\s+protein)\b", re.I)),
    ("BASEPLATE_MYO", re.compile(r"\b(?:baseplate\s+wedge|baseplate\s+hub|baseplate\s+spike|baseplate\s+assembly|baseplate\s+protein)\b", re.I)),
    # 4. 长尾核心 MTP / Dit / Central Tail Fiber J
    ("MTP", re.compile(r"\bmajor\s+tail(?:\s+(?:tube\s+)?protein)?\b", re.I)),
    ("DIT", re.compile(r"\b(?:distal\s+tail(?:\s+protein)?(?:\s+dit)?|central\s+tail\s+fiber(?:\s+j)?|tail\s+tip\s+protein(?:\s+tal)?)\b", re.I)),
    # 5. Virfam 头-颈-尾连接器细分
    ("CONN_AD1", re.compile(r"\bhead-tail\s+adaptor\s+ad1\b|\badaptor\s+ad1\b", re.I)),
    ("CONN_AD2", re.compile(r"\bhead-tail\s+adaptor\s+ad2\b|\badaptor\s+ad2\b", re.I)),
    ("CONN_AD3", re.compile(r"\bhead-tail\s+adaptor\s+ad3\b|\badaptor\s+ad3\b", re.I)),
    ("CONN_HC1", re.compile(r"\bhead\s+closure\s+hc1\b", re.I)),
    ("CONN_HC2", re.compile(r"\bhead\s+closure\s+hc2\b", re.I)),
    ("CONN_HC3", re.compile(r"\bhead\s+closure\s+hc3\b", re.I)),
    ("CONN_NECK1", re.compile(r"\btail\s+completion(?:\s+or\s+neck1)?\b|\bneck\s+protein\s+ne1\b|\bneck1\b", re.I)),
    ("CONN_TAIL_TERM", re.compile(r"\btail\s+terminator\b", re.I)),
    ("CONN_GENERAL", re.compile(r"\b(?:head-tail\s+connector|head-tail\s+adaptor|head-tail\s+joining|head\s+closure|neck\s+protein|neck\s+passage\s+structure|adaptor\s+ad4)\b", re.I)),
    # 6. 尾部受体与普通尾蛋白
    ("TAIL_FIBER_RBP", re.compile(r"\b(?:tail\s*fib(?:er|re)|tail\s*spike|tailspike|receptor[- ]binding|rbp\b|depolymerase|endosialidase|sialidase|adhesin|l-shaped\s+tail\s+fib(?:er|re)|tail\s+collar\s+fib(?:er|re)|host\s+specificity|straight\s+fibre\s+tail)\b", re.I)),
    ("TAIL_OTHER", re.compile(r"\b(?:minor\s+tail|tail\s+protein|tail\s+collar\s+protein|tail\s+lysin|tail\s+associated\s+lysin|lytic\s+tail)\b", re.I)),
    # 7. 衣壳与 DNA 包装核心
    ("PORTAL", re.compile(r"\bportal\s+protein\b|\bhead\s+portal\b", re.I)),
    ("TERL", re.compile(r"\bterminase\s+large\s+subunit\b|\bterminase\s+atpase\b", re.I)),
    ("TERS", re.compile(r"\bterminase\s+small\s+subunit\b", re.I)),
    ("MCP", re.compile(r"\bmajor\s+(?:head|capsid)\s+protein\b", re.I)),
    ("HEAD_SCAFFOLD_PROTEASE", re.compile(r"\b(?:head\s+maturation\s+protease|prohead\s+protease|head\s+scaffolding|scaffolding\s+protein|head\s+decoration|hoc-like|minor\s+(?:head|capsid)|head\s+morphogenesis|head\s+closure|virion\s+structural\s+protein)\b", re.I)),
    # 8. 裂解与整合
    ("LYSIS", re.compile(r"\b(?:endolysin|holin|antiholin|spanin|rz-like|rz1|lysozyme|muramidase|amidase)\b", re.I)),
    ("INTEGRASE", re.compile(r"\b(?:integrase|excisionase|site-specific\s+recombinase)\b", re.I)),
    # 9. 非尾部代谢、核酸加工及调控酶类（位于结构/裂解角色之后，杜绝在长尾区伪装成未注释 TMP）
    ("NON_TAIL_ENZYME", re.compile(r"\b(?:homing\s+endonuclease|lipase|acylhydrolase|dna\s+polymerase|rna\s+polymerase|dna\s+helicase|dna\s+methyltransferase|methylase|ribonucleoside[- ]diphosphate\s+reductase|ribonucleotide\s+reductase|exonuclease|endonuclease|topoisomerase|dna\s+ligase|primase|resolvase|helicase|transcriptional\s+(?:regulator|repressor|activator)|anti-?repressor|anti-?crispr|nucleotide\s+kinase|dutpase)\b", re.I)),
]


class PhrogCatalog:
    """加载与缓存本地 PHROG/Phold 注释字典。"""

    def __init__(self, phrog_tsv: Optional[Path] = None, phold_tsv: Optional[Path] = None):
        if phrog_tsv is None or phold_tsv is None:
            pharokka_dir = ToolConfig.get_db_dir("pharokka_db")
            self.phrog_tsv = phrog_tsv or (pharokka_dir / "phrog_annot_v4.tsv")
            self.phold_tsv = phold_tsv or (pharokka_dir / "phold_annots_updated.tsv")
        else:
            self.phrog_tsv = Path(phrog_tsv)
            self.phold_tsv = Path(phold_tsv)
        self._records: Dict[str, Tuple[str, str]] = {}
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.phrog_tsv.is_file():
            with self.phrog_tsv.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    raw_id = str(row.get("phrog") or "").strip()
                    if not raw_id:
                        continue
                    key = raw_id if raw_id.startswith("phrog_") else f"phrog_{raw_id}"
                    cat = str(row.get("category") or "").strip()
                    annot = str(row.get("annot") or "").strip()
                    if annot == "NA":
                        annot = ""
                    self._records[key] = (cat, annot)

        if self.phold_tsv.is_file():
            with self.phold_tsv.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    raw_id = str(row.get("phrog") or "").strip()
                    if not raw_id:
                        continue
                    key = raw_id if raw_id.startswith("phrog_") else f"phrog_{raw_id}"
                    func = str(row.get("function") or "").strip()
                    prod = str(row.get("product") or "").strip()
                    existing_cat, existing_ann = self._records.get(key, ("", ""))
                    if not existing_ann and prod and prod.lower() not in {"na", "hypothetical protein"}:
                        self._records[key] = (existing_cat or func, prod)
        self._loaded = True

    def get_phrog_info(self, phrog_id: str) -> Tuple[str, str]:
        self.ensure_loaded()
        if not phrog_id:
            return ("", "")
        norm = phrog_id.strip()
        if not norm:
            return ("", "")
        if not norm.startswith("phrog_") and norm.isdigit():
            norm = f"phrog_{norm}"
        return self._records.get(norm, ("", ""))

    def structural_phrog_ids(self) -> set[str]:
        """抽取结构相关 PHROG 以及具备明确注释的非尾护卫家族（酶/代谢/调控）供 HMM 高速校验。"""
        self.ensure_loaded()
        out: set[str] = set()
        for pid, (cat, ann) in self._records.items():
            if cat in STRUCTURAL_PHROG_CATEGORIES or bool(_EXTRA_INDEX_ANNOT_RE.search(ann or "")) or cat in NON_TAIL_GUARD_CATEGORIES and ann and ann.lower() not in {"hypothetical protein", "unknown function"}:
                out.add(pid)
        return out


_DEFAULT_CATALOG: Optional[PhrogCatalog] = None


def get_phrog_catalog() -> PhrogCatalog:
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = PhrogCatalog()
    return _DEFAULT_CATALOG


def classify_structural_role(
    product_text: str,
    phrog_id: str = "",
    phrog_category: str = "",
) -> Tuple[str, str]:
    """
    综合 PHROG ID 权威词典和蛋白产物名称，将蛋白映射至精确结构/防混淆角色。
    返回: (role_code, role_label_cn)
    """
    cat = phrog_category
    ann = ""
    if phrog_id:
        c_db, a_db = get_phrog_catalog().get_phrog_info(phrog_id)
        if c_db and not cat:
            cat = c_db
        ann = a_db

    # 先基于精确文本合并探测（先判 PHROG 官方标准名，再结合传入产物描述）
    candidates = [txt.strip() for txt in (ann, product_text) if txt and txt.strip()]
    for txt in candidates:
        for role, pattern in _ROLE_RULES:
            if pattern.search(txt):
                return role, ROLE_LABELS_CN.get(role, role)

    # 再检查类别宽泛兜底
    c_low = (cat or "").strip().lower()
    if "lysis" in c_low:
        return "LYSIS", ROLE_LABELS_CN["LYSIS"]
    if "integration" in c_low:
        return "INTEGRASE", ROLE_LABELS_CN["INTEGRASE"]
    if "connector" in c_low:
        return "CONN_GENERAL", ROLE_LABELS_CN["CONN_GENERAL"]
    if "tail" in c_low:
        return "TAIL_OTHER", ROLE_LABELS_CN["TAIL_OTHER"]
    if "head" in c_low:
        return "HEAD_SCAFFOLD_PROTEASE", ROLE_LABELS_CN["HEAD_SCAFFOLD_PROTEASE"]
    if any(k in c_low for k in ("dna, rna", "nucleotide metabolism", "transcription regulation", "moron, auxiliary metabolic")):
        return "NON_TAIL_ENZYME", ROLE_LABELS_CN["NON_TAIL_ENZYME"]
    return "OTHER", ROLE_LABELS_CN["OTHER"]
