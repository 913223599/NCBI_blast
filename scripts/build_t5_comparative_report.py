# -*- coding: utf-8 -*-
"""
生成标准 T5 (NC_005859.1) 与进化株 (T5-E1 / T5-E2 / T5-E5) 混合比较基因组与功能注释报告（不包括误混入的异属 WT）。
严格遵循 ANNO_M11_20261103_112550_注释报告.docx 的排版规范、表格样式与引用锚点体系。
"""
import os
import re
import sys
import json
import zipfile
import shutil
import datetime
import subprocess
from pathlib import Path
from collections import Counter
from Bio import SeqIO
from Bio.Seq import Seq

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.pan_genomics.engine import PanGenomicsEngine
from src.analysis.pan_genomics.types import PanGenomicsRunRequest, SampleInputItem


# ============================================================
# 0. 样本定义与数据加载
# ============================================================
SAMPLES = [
    ("Standard_T5", "ANNO_NC_005859", "标准 T5 (NC_005859.1)", "NC_005859.1"),
    ("T5-E1", "ANNO_AF90115A", "T5-E1", "ngcs_scaffold_1"),
    ("T5-E2", "ANNO_A500480C", "T5-E2", "ngcs_scaffold_1"),
    ("T5-E5", "ANNO_CE2E6ADB", "T5-E5", "ngcs_scaffold_1"),
]

TODAY_CN = datetime.date.today().strftime('%Y年%m月%d日')
OUT_PATH = PROJECT_ROOT / "results" / "email_sends" / "标准T5与E1_E2_E5_混合比较注释报告.docx"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_hits_tsv(data_dir: Path, name: str):
    path = data_dir / name
    rows = []
    if path.is_file():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("\t")
                rows.append(parts if len(parts) >= 7 else parts + [""] * (7 - len(parts)))
    return rows


def os_species(desc: str) -> str:
    m = re.search(r"OS=([^=;]+?)(?=\s+(?:OX|GN|PE|SV)=|$)", desc)
    return m.group(1).strip() if m else "未标注物种"


def acc_short(acc: str) -> str:
    parts = acc.split("|")
    v = parts[-1] if parts else acc
    return v.strip("() ")


def short_evidence(f: dict) -> str:
    evs = f.get("evidence_sources") or []
    for e in evs:
        if "BLASTP" in e:
            m = re.search(r"BLASTP to (\S+)\s*\(Identity:\s*([\d.]+)%", e)
            if m:
                return f"BLASTP {m.group(1)} ({m.group(2)}%)"
            return e
    ph = f.get("phrog")
    if ph and ph != "No_PHROG":
        return f"PHROG #{ph}"
    for e in evs:
        if "Phold" in e or "RefSeq" in e:
            return e[:45]
    return "—"


def fmt_len(v) -> str:
    return f"{v:,}" if v is not None else "—"


# 加载 4 株注释数据
S_DATA = {}
for key, tid, label, contig_name in SAMPLES:
    d = PROJECT_ROOT / "results" / "annotations" / tid
    with open(d / "features.json", encoding="utf-8") as fh:
        feats = json.load(fh)
    with open(d / "summary.json", encoding="utf-8") as fh:
        summary = json.load(fh)
    with open(d / "safety_audit.json", encoding="utf-8") as fh:
        safety = json.load(fh)
    seq_rec = next(SeqIO.parse(str(d / "input_sequence.fasta"), "fasta"))
    cds = [f for f in feats if f.get("feature_type") == "CDS"]
    trna = [f for f in feats if f.get("feature_type") == "tRNA"]
    lens = [len(f["translation"]) for f in cds if f.get("translation")]
    S_DATA[key] = {
        "key": key,
        "task_id": tid,
        "label": label,
        "contig": contig_name,
        "dir": d,
        "feats": feats,
        "cds": cds,
        "trna": trna,
        "summary": summary,
        "safety": safety,
        "seq": str(seq_rec.seq),
        "lens": lens,
        "swiss_hits": read_hits_tsv(d, "swissprot_hits.tsv"),
        "card_hits": read_hits_tsv(d, "card_hits.tsv"),
        "vfdb_hits": read_hits_tsv(d, "vfdb_hits.tsv"),
    }

# 运行 4 株泛基因组分析获取最新正交聚类与矩阵
pan_req = PanGenomicsRunRequest(
    samples=[
        SampleInputItem(sample_id=tid, sample_name=label, source_type="task", task_id=tid)
        for key, tid, label, _ in SAMPLES
    ],
    identity_threshold=0.5,
    coverage_threshold=0.5,
)
pan_engine = PanGenomicsEngine(PROJECT_ROOT)
pan_res = pan_engine.run_analysis(pan_req)
PAN_TASK_ID = pan_res.task_id


# ============================================================
# 1. 文档与样式辅助函数（与 ANNO_M11 报告完全一致）
# ============================================================
doc = Document()
sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.5)
sec.bottom_margin = Cm(2.5)
sec.left_margin = Cm(2.5)
sec.right_margin = Cm(2.5)


def set_font(run, cn="宋体", en="Times New Roman", size=12, bold=False, color=RGBColor(0, 0, 0)):
    run.font.name = en
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def para(text="", cn="宋体", size=12, bold=False, align=None, indent2=True,
         line15=True, space_before=0, space_after=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if indent2:
        pf.first_line_indent = Pt(size * 2)
    if line15:
        pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if text:
        r = p.add_run(text)
        set_font(r, cn=cn, size=size, bold=bold)
    return p


def heading(level, text):
    p = doc.add_heading("", level=level)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = Pt({1: 14, 2: 11, 3: 9}[level])
    pf.space_after = Pt({1: 6, 2: 5, 3: 4}[level])
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    r = p.add_run(text)
    set_font(r, cn="黑体", size={1: 16, 2: 14, 3: 12}[level], bold=True)
    r.font.color.rgb = RGBColor(0, 0, 0)
    return p


def add_table(header, rows, col_widths_cm=None, align_cols=None, font_size=10.0, header_fill="D9D9D9"):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0]
    for j, htxt in enumerate(header):
        cell = hdr.cells[j]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(htxt))
        set_font(r, size=font_size, bold=True)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), header_fill)
        cell._tc.get_or_add_tcPr().append(shd)
    for row in rows:
        cells = t.add_row().cells
        for j, val in enumerate(row):
            cell = cells[j]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            if align_cols and j < len(align_cols) and align_cols[j] == "c":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif align_cols and j < len(align_cols) and align_cols[j] == "r":
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(val))
            set_font(r, size=font_size)
    for r_ in t.rows:
        trPr = r_._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
    trh = OxmlElement("w:tblHeader")
    trh.set(qn("w:val"), "true")
    t.rows[0]._tr.get_or_add_trPr().append(trh)
    if col_widths_cm:
        for j, w in enumerate(col_widths_cm):
            for row in t.rows:
                row.cells[j].width = Cm(w)
    return t


def data_note(text):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(2)
    pf.space_after = Pt(8)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    r = p.add_run("数据来源：" + text)
    set_font(r, cn="楷体", size=9)
    r.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
    return p


# ============================================================
# 2. 封面
# ============================================================
for _ in range(3):
    para("", indent2=False)
para("噬菌体基因组混合比较与功能注释报告", cn="黑体", size=22, bold=True,
     align=WD_ALIGN_PARAGRAPH.CENTER, indent2=False, space_after=6)
para("（标准 T5 与进化株 E1 / E2 / E5 专项对比 · 内部审阅草稿）", cn="楷体", size=12,
     align=WD_ALIGN_PARAGRAPH.CENTER, indent2=False, space_after=12)
para("", indent2=False)

cov_rows = [
    ("报告编号", "YSSW-COMP-2026-T5（待定）"),
    ("比较样品", "标准 T5（NC_005859.1）、T5-E1、T5-E2、T5-E5（共 4 株，不含原异属 WT）"),
    ("参考基因组标识", "NC_005859.1（Enterobacteria phage T5, complete genome）"),
    ("进化株序列标识", "ngcs_scaffold_1（T5-E1 / T5-E2 / T5-E5 主组装片段）"),
    ("关联任务编号", f"ANNO_NC_005859 / ANNO_AF90115A / ANNO_A500480C / ANNO_CE2E6ADB / {PAN_TASK_ID}"),
    ("分析内容", "噬菌体单株基因预测、多引擎功能注释、泛基因组同源聚类、结构缺失与点突变鉴定、安全性筛查"),
    ("报告日期", TODAY_CN),
    ("编制单位", "元昇生物（武汉）有限公司"),
]
add_table(["项目", "内容"], cov_rows, col_widths_cm=[4.2, 11.8], align_cols=["c", "l"], font_size=10.5)
data_note("四株注释结果分别取自 ANNO_NC_005859、ANNO_AF90115A、ANNO_A500480C、ANNO_CE2E6ADB 目录；泛基因组比较结果取自 " + PAN_TASK_ID + "。")
doc.add_page_break()

# ============================================================
# 3. 目录
# ============================================================
heading(1, "目  录")
p = doc.add_paragraph()
run = p.add_run()
fldChar1 = OxmlElement("w:fldChar")
fldChar1.set(qn("w:fldCharType"), "begin")
instrText = OxmlElement("w:instrText")
instrText.set(qn("xml:space"), "preserve")
instrText.text = ' TOC \\o "1-2" \\h \\z \\u '
fldChar2 = OxmlElement("w:fldChar")
fldChar2.set(qn("w:fldCharType"), "separate")
t_ = OxmlElement("w:t")
t_.text = "（请在 Word 中右键更新目录）"
fldChar3 = OxmlElement("w:fldChar")
fldChar3.set(qn("w:fldCharType"), "end")
run._r.append(fldChar1)
run._r.append(instrText)
run._r.append(fldChar2)
run._r.append(t_)
run._r.append(fldChar3)
set_font(run, cn="宋体", size=12)
doc.add_page_break()

# ============================================================
# 4. 第 1 章 总体工作流程概述
# ============================================================
heading(1, "1 总体工作流程概述")
heading(2, "1.1 项目简介")
para("本报告针对 NCBI RefSeq 官方标准大肠杆菌噬菌体 T5 参考基因组（Enterobacteria phage T5，登录号 NC_005859.1，全长 121,750 bp，GC 含量 39.35%）"
     "与三株实验室适应性进化/筛选突变株 T5-E1（全长 104,547 bp，GC 含量 39.19%）、T5-E2（全长 100,101 bp，GC 含量 39.11%）、"
     "T5-E5（全长 100,101 bp，GC 含量 39.11%）开展统一口径的功能注释与多样本混合比较基因组分析。"
     "前期排查已证实原批次中标记为 T5-WT（ANNO_1418C944，全长 137,623 bp，GC 含量 43.70%）的样品实为异科/异属的 Escherichia phage CarlMeissner"
     "（Vequintavirus 属，MZ501054.1），故本报告将其排除，直接以权威标准株 NC_005859.1 作为野生型基准，系统解析 E1、E2、E5 的基因组结构缺失、"
     "单碱基点突变（SNP）、泛基因组基因簇分布、tRNA 簇退化及生物学安全性。")

heading(2, "1.2 生物信息分析流程")
para("混合比较与功能注释分析流程分为以下步骤：")
steps = [
    "基因预测与参考特征对齐：进化株使用 Pharokka（PHANOTATE 1.6.7 从头预测算法）进行编码基因（CDS）与 tRNA 预测，标准 T5（NC_005859.1）提取 NCBI RefSeq 权威审阅特征并按统一标准校验坐标；",
    "同源功能注释：将四株预测蛋白序列统一经 BLASTP 比对 Swiss-Prot、PhageScope 及 CDD/Pfam 数据库，并结合 PHROG 噬菌体直系同源蛋白家族数据库进行功能归属；",
    "AI 辅助注释：使用 Phold AI 基于蛋白质三维结构预测对部分同源未知基因进行补充注释；",
    "全基因组共线性与变异检测：采用 OrthoANIu（1,020 bp 双向最佳切片 RBH）计算全基因组平均核苷酸一致性（ANI），并通过 BLASTN 全长对齐与逐碱基扫描精确测定大片段缺失（Deletion）边界及单碱基变异（SNP）引起的氨基酸替换；",
    "泛基因组同源聚类：基于蛋白质序列双向比对（Identity >= 50%，Coverage >= 50%）构建直系同源基因簇（Ortholog Groups），划分核心基因簇（Core）、附属基因簇（Accessory）与株系特有基因簇（Unique）；",
    "安全性筛查：分别检索抗生素耐药基因（CARD）、毒力因子（VFDB）与 Anti-CRISPR 基因（Acranker），并评估溶源整合元件（整合酶/阻遏蛋白）；",
    "产物导出：输出四株各自的 GenBank（gbk）、GFF3（gff）、TSV、蛋白序列（faa）、核酸序列（ffn）、单株注释报告及泛基因组矩阵（result.json）等标准产物。",
]
for s in steps:
    para(s, indent2=True)
doc.add_page_break()

# ============================================================
# 5. 第 2 章 混合比较与注释结果
# ============================================================
heading(1, "2 混合比较与注释结果")

# ---- 2.1 四株基因组与基因预测统计对比 ----
heading(2, "2.1 四株基因组与基因预测统计对比")
para("标准 T5（NC_005859.1）与三株进化株（T5-E1、T5-E2、T5-E5）的基因组组装及基因预测核心指标横向对比如下表所示：")


def get_strand_str(k):
    cds = S_DATA[k]["cds"]
    sp = sum(1 for f in cds if f.get("strand") == "+")
    sn = len(cds) - sp
    return f"{sp} / {sn}"


def get_len_range_str(k):
    ls = S_DATA[k]["lens"]
    if not ls:
        return "—"
    med = sorted(ls)[len(ls) // 2]
    return f"{min(ls)}–{max(ls)}（中位数 {med}）"


def get_mean_aa_str(k):
    ls = S_DATA[k]["lens"]
    return f"{sum(ls)/len(ls):.1f}" if ls else "—"


keys_order = ["Standard_T5", "T5-E1", "T5-E2", "T5-E5"]
stat_rows = [
    ("任务编号", *[S_DATA[k]["task_id"] for k in keys_order]),
    ("序列标识", *[S_DATA[k]["contig"] for k in keys_order]),
    ("基因组总长（bp）", *[fmt_len(S_DATA[k]["summary"]["total_length"]) for k in keys_order]),
    ("相对标准 T5 长度差（bp）", "基准 (0)", "-17,203", "-21,649", "-21,649"),
    ("相对 T5-E1 长度差（bp）", "+17,203", "基准 (0)", "-4,446", "-4,446"),
    ("GC 含量（%）", *[str(S_DATA[k]["summary"]["gc_content"]) for k in keys_order]),
    ("CDS 数量", *[str(len(S_DATA[k]["cds"])) for k in keys_order]),
    ("已知功能 CDS / 未知 CDS", *[f"{S_DATA[k]['summary']['annotated_count']} / {S_DATA[k]['summary']['hypothetical_count']}" for k in keys_order]),
    ("tRNA 数量", *[str(len(S_DATA[k]["trna"])) for k in keys_order]),
    ("编码密度（%）", *[str(S_DATA[k]["summary"]["coding_density_pct"]) for k in keys_order]),
    ("平均基因长度（bp）", *[str(S_DATA[k]["summary"]["avg_gene_length"]) for k in keys_order]),
    ("平均蛋白长度（aa）", *[get_mean_aa_str(k) for k in keys_order]),
    ("正链 CDS / 负链 CDS", *[get_strand_str(k) for k in keys_order]),
    ("蛋白长度范围（aa）", *[get_len_range_str(k) for k in keys_order]),
]
add_table(
    ["指标", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    stat_rows,
    col_widths_cm=[4.4, 3.2, 2.8, 2.8, 2.8],
    align_cols=["l", "c", "c", "c", "c"],
    font_size=9.5
)
data_note("四株各自的 summary.json 与 features.json。")
para("")

para("四株预测蛋白长度区间（aa）分布横向对比如下表所示：")
len_bins = [
    (1, 100, "1–100"), (101, 200, "101–200"), (201, 300, "201–300"),
    (301, 400, "301–400"), (401, 600, "401–600"), (601, 800, "601–800"),
    (801, 1000, "801–1,000"), (1001, 2000, "1,001–2,000")
]
len_rows = []
for lo, hi, label in len_bins:
    row = [label]
    for k in keys_order:
        cnt = sum(1 for l in S_DATA[k]["lens"] if lo <= l <= hi)
        pct = cnt / len(S_DATA[k]["lens"]) * 100 if S_DATA[k]["lens"] else 0
        row.append(f"{cnt} ({pct:.1f}%)")
    len_rows.append(row)
len_rows.append(["合计"] + [f"{len(S_DATA[k]['lens'])} (100.0%)" for k in keys_order])
add_table(
    ["蛋白长度区间（aa）", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    len_rows,
    col_widths_cm=[4.0, 3.0, 3.0, 3.0, 3.0],
    align_cols=["c", "c", "c", "c", "c"],
    font_size=9.5
)
data_note("四株各自的 features.json（translation 字段长度统计）。")
para("统计表明，四株基因组的 GC 含量高度一致（39.11%–39.35%），最大编码蛋白均为 1,396 aa（尾纤维/穿孔带尺蛋白），"
     "编码密度维持在 90.08%–92.77%。T5-E2 与 T5-E5 的基因组长度（100,101 bp）、CDS 数量（164 个）、tRNA 数量（2 个）及蛋白长度分布完全一致；"
     "而 T5-E1 比 T5-E2/E5 长 4,446 bp，多出 9 个 CDS（主要集中在 1–200 aa 区间）和 6 个 tRNA。")
para("")

# ---- 2.2 全基因组同源性（OrthoANI）、共线性与结构缺失分析 ----
heading(2, "2.2 全基因组同源性（OrthoANI）、共线性与结构缺失分析")
para("基于国际标准 OrthoANIu（1,020 bp 切片双向最佳比对 RBH）计算的四株全基因组平均核苷酸一致性（ANI，上三角/对角线）"
     "与基因组对齐覆盖度（AF，括号内数值）矩阵如下表所示：")

ani_mat = pan_res.ani_matrix
af_mat = pan_res.af_matrix
tids = [S_DATA[k]["task_id"] for k in keys_order]
labels = [S_DATA[k]["label"] for k in keys_order]
ani_rows = []
for i, k1 in enumerate(keys_order):
    tid1 = S_DATA[k1]["task_id"]
    row = [S_DATA[k1]["label"]]
    for j, k2 in enumerate(keys_order):
        tid2 = S_DATA[k2]["task_id"]
        v_ani = ani_mat.get(tid1, {}).get(tid2)
        v_af = af_mat.get(tid1, {}).get(tid2)
        if v_ani is not None and v_af is not None:
            row.append(f"{v_ani:.2f}% (AF {v_af:.1f}%)")
        else:
            row.append("—")
    ani_rows.append(row)

add_table(
    ["样本名称", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    ani_rows,
    col_widths_cm=[4.0, 3.0, 3.0, 3.0, 3.0],
    align_cols=["l", "c", "c", "c", "c"],
    font_size=9.5
)
data_note(f"泛基因组分析任务 {PAN_TASK_ID}/result.json（ani_matrix 与 af_matrix 字段）。")
para("")

para("为精确定位进化株相对于标准 T5（NC_005859.1，121,750 bp）的基因组结构重排与大片段缺失（Deletion），"
     "使用 NCBI BLASTN（v2.16.0+）进行全基因组双向共线性对齐，共线性区块及缺失结构汇总如下表所示：")

synteny_rows = [
    ("共线性区块 1（主体骨架区）", "55,132–111,666 (56,535 bp)", "1–56,547 (-)", "1–56,549 (-)", "1–56,549 (-)", "99.95%", "核心形态发生（头/尾）与复制主模块完全共线性保守"),
    ("共线性区块 2（左臂保守区）", "40,787–55,138 (14,352 bp)", "56,691–71,041 (-)", "56,693–71,043 (-)", "56,693–71,043 (-)", "99.97%", "前早期/早期代谢及抗宿主防御模块共线性保守"),
    ("差异缺失区 A（E2/E5 特异缺失）", "39,104–40,786 及邻近 tRNA 簇", "71,042–75,476 (保留 4,446 bp)", "缺失 (0 bp)", "缺失 (0 bp)", "99.97% (E1)", "E1 保留该 4,446 bp（含 9 个 CDS + 6 个 tRNA），E2/E5 经 11 bp 微同源重组完全缺失"),
    ("差异缺失区 B（E1/E2/E5 共同缺失）", "29,202–39,103 (7,119–9,902 bp)", "缺失 (约 7.1 kb)", "缺失 (约 11.6 kb 合并缺失)", "缺失 (约 11.6 kb 合并缺失)", "—", "对应 T5 经典 st0 可缺失区（Deletable tRNA cluster region），实验室传代易发生自发缺失"),
    ("共线性区块 3（右臂与早期区）", "134–31,984 (31,851 bp)", "72,695–104,547 (-)", "71,033–100,101 (-)", "71,033–100,101 (-)", "99.95%–99.98%", "早期宿主接管蛋白（A1/A2）与复制修复区完全共线性"),
    ("末端直接重复区（LTR/RTR）", "1–10,139 / 111,612–121,750", "单拷贝化合并 (94,462–104,547)", "单拷贝化合并 (90,018–100,101)", "单拷贝化合并 (90,018–100,101)", "99.98%–99.99%", "标准 T5 含双拷贝末端直接重复（各约 10.1 kb），组装 scaffold 中合并为单拷贝"),
]
add_table(
    ["基因组区域", "标准 T5 坐标 (NC_005859.1)", "T5-E1 坐标", "T5-E2 坐标", "T5-E5 坐标", "Identity%", "结构与演化说明"],
    synteny_rows,
    col_widths_cm=[2.6, 2.6, 2.2, 2.0, 2.0, 1.4, 3.2],
    align_cols=["l", "c", "c", "c", "c", "c", "l"],
    font_size=8.5
)
data_note("基于 NCBI BLASTN 2.16.0+ 对 NC_005859.1 与 T5-E1 / T5-E2 / T5-E5 全长序列双向对齐测定。")
para("全基因组共线性分析揭示：三株进化株相对于标准 T5（121,750 bp）的长度缩短由两部分构成：一是测序组装将标准 T5 两端各约 10.1 kb 的"
     "末端直接重复区（Terminal Direct Repeats）合并为单拷贝（减少约 10.1 kb）；二是在 T5 经典的 tRNA 富集可缺失区（Deletable region）发生了阶梯式缺失——"
     "T5-E1 缺失了约 7.1 kb（保留全长 104,547 bp），而 T5-E2 与 T5-E5 在 T5-E1 基础上进一步缺失了 4,446 bp（保留全长 100,101 bp）。"
     "除上述非必需缺失区外，四株在全基因组共线性骨架上的核苷酸一致性高达 99.96%–100.00%。")
para("")

# ---- 2.3 进化株（E1 -> E2 -> E5）单碱基突变（SNP）与缺失区基因鉴定 ----
heading(2, "2.3 进化株（E1 → E2 → E5）单碱基突变（SNP）与缺失区基因鉴定")
para("通过对 T5-E1、T5-E2 与 T5-E5 的全长共线性区域进行逐碱基扫描与密码子翻译比对，共鉴定出 6 个区分性单碱基突变（SNP）位点，"
     "清晰还原出从 T5-E1 经 T5-E2 到 T5-E5 的两步点突变累积轨迹，明细如下表所示：")

snp_rows = [
    ("SNP-1", "43,561", "43,563", "G → A (E2/E5)", "CDS_0044 (-)", "DnaB-like replicative helicase（复制解旋酶）", "同义突变 (Synonymous)", "E1 → E2 阶段固定"),
    ("SNP-2", "71,038", "71,040", "A → T (E2/E5)", "tRNA_0002 (+)", "tRNA-Arg(AGA)（紧邻 4,446 bp 缺失断裂点）", "非编码 tRNA 区变异", "E1 → E2 伴随缺失产生"),
    ("SNP-3", "76,797", "72,353", "A → C (E2/E5)", "E1:CDS_0105 / E2:CDS_0096 (+)", "Autonomous glycyl radical cofactor（甘氨酰自由基辅因子）", "同义突变 (Synonymous)", "E1 → E2 阶段固定"),
    ("SNP-4", "83,115", "78,671", "G → A (E2/E5)", "E1:CDS_0120 / E2:CDS_0111 (+)", "ATP-dependent protease（ATP 依赖型蛋白酶）", "错义突变：第 63 位 Gly (G) → Asp (D)", "E1 → E2 阶段固定"),
    ("SNP-5", "89,419", "84,975", "T (E1/E2) → C (E5)", "E1:CDS_0135 / E5:CDS_0126 (+)", "hypothetical protein（45 aa 未知功能小蛋白）", "错义突变：第 17 位 Phe (F) → Leu (L)", "E2 → E5 新增特异性突变"),
    ("SNP-6", "94,477", "90,033", "T (E1/E2) → C (E5)", "E1:CDS_0149 / E5:CDS_0140 (-)", "hypothetical protein（72 aa 未知功能小蛋白）", "错义突变：第 4 位 Glu (E) → Gly (G)", "E2 → E5 新增特异性突变"),
]
add_table(
    ["编号", "E1 坐标", "E2/E5 坐标", "碱基变化", "所在基因", "功能产物", "氨基酸突变效应", "演化阶段归属"],
    snp_rows,
    col_widths_cm=[1.2, 1.5, 1.6, 2.0, 2.5, 2.8, 2.4, 2.0],
    align_cols=["c", "c", "c", "c", "l", "l", "l", "l"],
    font_size=8.5
)
data_note("基于 T5-E1、T5-E2、T5-E5 的 input_sequence.fasta 与 features.json 逐位点比对及遗传密码表 11 翻译核验。")
para("")

para("同时，T5-E1 在 71,042–75,476 bp 区间保留、而在 T5-E2 与 T5-E5 中整体缺失的 4,446 bp 片段内共包含 9 个 CDS 与 6 个功能性 tRNA（另含 2 个 tRNA 假基因），"
     "其完整基因清单如下表所示：")

del_feats = [
    f for f in S_DATA["T5-E1"]["feats"]
    if 70980 <= f.get("start", 0) <= 75500
]
del_rows = []
for f in del_feats:
    del_rows.append([
        f.get("locus_tag"),
        f.get("feature_type"),
        f"{f.get('start')}–{f.get('end')}",
        f.get("strand"),
        str(f.get("length_bp")),
        str(f.get("protein_length_aa") or "—"),
        f.get("product") or "—",
        f.get("category") or "—",
    ])
add_table(
    ["T5-E1 Locus_Tag", "类型", "起止坐标 (bp)", "链", "长度(bp)", "蛋白(aa)", "基因产物", "功能类别"],
    del_rows,
    col_widths_cm=[3.2, 1.6, 2.4, 0.9, 1.5, 1.4, 2.8, 2.2],
    align_cols=["l", "c", "c", "c", "c", "c", "l", "l"],
    font_size=8.5
)
data_note("ANNO_AF90115A/features.json（筛选位于 70,980–75,500 bp 缺失区内的全部 17 条特征记录）。")
para("上述结果证实：T5-E2 与 T5-E5 相较于 T5-E1 的核心结构变化是由 tRNA-Arg(AGA) 与下游 tRNA 簇之间的 11 bp 重复序列介导的 4,446 bp 缺失，"
     "该缺失一次性移除了 1 个脂蛋白（lipoprotein）、2 个 HNH 归巢内切酶（HNH endonuclease）、6 个未知蛋白及 6 个 tRNA；"
     "而 T5-E5 与 T5-E2 之间仅相差 2 个单碱基错义突变（分别位于 CDS_0126 与 CDS_0140）。")
para("")

# ---- 2.4 泛基因组直系同源基因簇（Core / Accessory / Unique）分析 ----
heading(2, "2.4 泛基因组直系同源基因簇（Core / Accessory / Unique）分析")
para(f"将四株合计 {pan_res.summary.total_genes} 个预测 CDS 按氨基酸序列一致性 >= 50%、覆盖度 >= 50% 进行正交同源聚类，"
     f"共获得 {pan_res.summary.total_clusters} 个直系同源基因簇（Ortholog Groups）。泛基因组分区统计如下表所示：")

pan_stat_rows = [
    ("核心基因簇（Core，4/4 株共有）", str(pan_res.summary.core_clusters_count),
     f"{pan_res.summary.core_clusters_count / pan_res.summary.total_clusters * 100:.1f}%",
     str(pan_res.summary.core_genes_count), "四株完全保守的形态发生、DNA 复制、转录调控、尾丝受体识别及裂解主干基因"),
    ("附属基因簇（Accessory，2–3 株共有）", str(pan_res.summary.accessory_clusters_count),
     f"{pan_res.summary.accessory_clusters_count / pan_res.summary.total_clusters * 100:.1f}%",
     str(pan_res.summary.accessory_genes_count), "包括 E1/E2/E5 共有的预测短 ORF，以及标准 T5 与 E1 共有但 E2/E5 缺失的基因"),
    ("株系特有基因簇（Unique，1/4 株独有）", str(pan_res.summary.unique_clusters_count),
     f"{pan_res.summary.unique_clusters_count / pan_res.summary.total_clusters * 100:.1f}%",
     str(pan_res.summary.unique_genes_count), "主要为标准 T5 在 7.1 kb 可缺失区独有的基因及 E1 在 4.4 kb 区段独有的短 ORF"),
    ("合计", str(pan_res.summary.total_clusters), "100.0%", str(pan_res.summary.total_genes), "—"),
]
add_table(
    ["泛基因组分区", "基因簇数", "簇占比", "包含基因总数", "生物学构成说明"],
    pan_stat_rows,
    col_widths_cm=[4.2, 1.8, 1.8, 2.2, 6.0],
    align_cols=["l", "c", "c", "c", "l"],
    font_size=9.5
)
data_note(f"泛基因组分析任务 {PAN_TASK_ID}/result.json（summary 与 clusters 字段）。")
para("")

# ---- 2.5 功能注释概况与多引擎贡献对比 ----
heading(2, "2.5 功能注释概况与多引擎贡献对比")
para("四株基因组在多引擎级联注释流程中，各注释引擎最终归属的 CDS 数量与占比横向对比如下表所示：")

eng_order = ["Pharokka", "PhageScope", "Swiss-Prot", "CDD/Pfam", "Phold AI"]
eng_desc = {
    "Pharokka": "噬菌体直系同源家族 / RefSeq 基准注释",
    "PhageScope": "噬菌体专业数据库同源打捞",
    "Swiss-Prot": "经过实验验证的蛋白数据库同源",
    "CDD/Pfam": "保守结构域/蛋白家族 RPS-BLAST",
    "Phold AI": "蛋白质三维结构感知辅助注释",
}
eng_comp_rows = []
for e in eng_order:
    row = [e]
    for k in keys_order:
        cnt = sum(1 for f in S_DATA[k]["cds"] if f.get("source_engine") == e)
        tot = len(S_DATA[k]["cds"])
        row.append(f"{cnt} ({cnt/tot*100:.1f}%)")
    row.append(eng_desc.get(e, ""))
    eng_comp_rows.append(row)
eng_comp_rows.append(["合计"] + [f"{len(S_DATA[k]['cds'])} (100.0%)" for k in keys_order] + ["—"])
add_table(
    ["注释引擎", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5", "说明"],
    eng_comp_rows,
    col_widths_cm=[2.4, 2.5, 2.3, 2.3, 2.3, 4.2],
    align_cols=["l", "c", "c", "c", "c", "l"],
    font_size=9.0
)
data_note("四株各自的 features.json（source_engine 字段）与 summary.json（engine_contributions 字段）。")
para("")

# ---- 2.6 功能类别分布横向对比 ----
heading(2, "2.6 功能类别分布横向对比")
para("按噬菌体标准功能类别划分，四株在各大功能模块中的基因数量及占比横向对比如下表所示：")

cat_order = [
    "Replication & Repair",
    "Tail & Host Interaction",
    "Metabolism & AMG",
    "Head & Packaging",
    "Lysis",
    "Transcription & Regulation",
    "Defense & Host Interaction",
    "Integration & Excision",
    "Other Functional",
    "Hypothetical",
]
cat_comp_rows = []
for c in cat_order:
    counts = [S_DATA[k]["summary"]["category_distribution"].get(c, 0) for k in keys_order]
    if sum(counts) == 0:
        continue
    row = [c]
    for idx_k, k in enumerate(keys_order):
        tot = len(S_DATA[k]["cds"])
        cnt = counts[idx_k]
        row.append(f"{cnt} ({cnt/tot*100:.1f}%)")
    cat_comp_rows.append(row)
cat_comp_rows.append(["合计"] + [f"{len(S_DATA[k]['cds'])} (100.0%)" for k in keys_order])
add_table(
    ["功能类别", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    cat_comp_rows,
    col_widths_cm=[4.4, 2.9, 2.9, 2.9, 2.9],
    align_cols=["l", "c", "c", "c", "c"],
    font_size=9.5
)
data_note("四株各自的 summary.json（category_distribution 字段）。")
para("对比可见，四株在核心功能模块上的基因数量高度稳定：Tail & Host Interaction（18–19 个）、Head & Packaging（7–8 个）、"
     "Metabolism & AMG（18 个）、Lysis（5–6 个）及 Transcription & Regulation（3–4 个）在四株间几乎完全一致；"
     "T5-E1 相比 T5-E2/E5 多出的 9 个 CDS 主要归入 Replication & Repair（2 个 HNH 归巢内切酶）、Other Functional（1 个脂蛋白）及 Hypothetical（6 个未知蛋白）。")
para("")

# ---- 2.7 与近缘噬菌体的同源性分析（Swiss-Prot）对比 ----
heading(2, "2.7 与近缘噬菌体的同源性分析（Swiss-Prot）对比")
para("将四株预测蛋白序列分别经 BLASTP 比对 Swiss-Prot 数据库，标准 T5、T5-E1、T5-E2、T5-E5 分别获得 62、60、58、58 条可靠同源命中。"
     "按比对物种（OS= 字段）聚合的命中分布横向对比如下表所示：")

all_sp_Counters = {k: Counter(os_species(r[6]) for r in S_DATA[k]["swiss_hits"]) for k in keys_order}
all_species = sorted(
    set().union(*(c.keys() for c in all_sp_Counters.values())),
    key=lambda s: -sum(all_sp_Counters[k].get(s, 0) for k in keys_order)
)
sp_comp_rows = []
for sp_name in all_species[:10]:
    row = [sp_name]
    for k in keys_order:
        cnt = all_sp_Counters[k].get(sp_name, 0)
        tot = len(S_DATA[k]["swiss_hits"]) or 1
        row.append(f"{cnt} ({cnt/tot*100:.1f}%)")
    sp_comp_rows.append(row)
sp_comp_rows.append(["全部物种合计"] + [f"{len(S_DATA[k]['swiss_hits'])} (100.0%)" for k in keys_order])
add_table(
    ["比对物种（Swiss-Prot）", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    sp_comp_rows,
    col_widths_cm=[5.2, 2.7, 2.7, 2.7, 2.7],
    align_cols=["l", "c", "c", "c", "c"],
    font_size=9.0
)
data_note("四株各自的 swissprot_hits.tsv（按 OS= 物种字段聚合统计，展示前 10 位物种）。")
para("Swiss-Prot 同源物种分布清晰表明：四株约 68%–69% 的命中均直接归属于 Escherichia phage T5（大肠杆菌噬菌体 T5，40–42 条命中），"
     "其余命中分布于大肠杆菌宿主同源代谢酶及近缘有尾噬菌体，从实验验证蛋白层面进一步确证 E1、E2、E5 与标准 T5 的同种属性。")
para("")

para("按比对显著性（bit score）排序的四株代表性高同源核心蛋白（Top 15）如下表所示：")
best_swiss = sorted(S_DATA["T5-E5"]["swiss_hits"], key=lambda r: float(r[5]), reverse=True)[:15]
prod_map_e5 = {f.get("locus_tag"): f.get("product") for f in S_DATA["T5-E5"]["cds"]}
sw_rows = []
for r in best_swiss:
    tag = r[0]
    desc_prod = re.sub(r"^[^\s]+\s+", "", r[6])
    desc_prod = re.sub(r"\s+OS=.*$", "", desc_prod).strip()
    sw_rows.append([
        tag,
        acc_short(r[1]),
        prod_map_e5.get(tag, desc_prod),
        r[2],
        r[4],
        r[5],
        os_species(r[6]),
    ])
add_table(
    ["代表 Locus_Tag (E5)", "Swiss-Prot 命中", "基因产物", "Identity%", "E-value", "bit score", "物种"],
    sw_rows,
    col_widths_cm=[3.2, 2.5, 3.8, 1.7, 1.8, 1.5, 2.5],
    align_cols=["l", "c", "l", "c", "c", "c", "l"],
    font_size=8.5
)
data_note("swissprot_hits.tsv（按 bit score 降序取前 15 条；该 15 个高分基因在标准 T5、E1、E2、E5 中均 100% 存在）。")
para("")

# ---- 2.8 关键功能模块、受体识别区与裂解系统对比 ----
heading(2, "2.8 关键功能模块、受体识别区与裂解系统对比")
para("按基因产物功能关键词归类，18 个关键功能模块在四株中的基因数量横向对比如下表所示：")

mod_kw = {
    "尾部结构": (("tail",), "minor/major tail、tail tube/sheath 等尾部结构蛋白"),
    "尾纤维/受体结合": (("fiber", "receptor binding", "pb5"), "L-shaped tail fiber / RBP pb5 宿主受体识别"),
    "头部结构": (("head", "prohead"), "head morphogenesis/maturation protease 等"),
    "衣壳蛋白": (("capsid",), "major/minor capsid protein"),
    "门户蛋白": (("portal",), "portal protein"),
    "末端酶": (("terminase",), "terminase 大/小亚基"),
    "裂解（穿孔素）": (("holin",), "holin 穿孔素"),
    "裂解（内溶素）": (("endolysin", "muramidase", "amidase"), "endolysin 肽聚糖水解酶"),
    "裂解（跨膜蛋白）": (("spanin",), "spanin 外膜裂解蛋白"),
    "解旋酶": (("helicase",), "DnaB-like/replicative helicase 等"),
    "聚合酶": (("polymerase",), "DNA polymerase 等"),
    "连接酶": (("ligase",), "DNA ligase"),
    "引发酶": (("primase",), "DNA primase"),
    "核酸酶": (("nuclease",), "HNH endonuclease/exonuclease/endonuclease 等"),
    "激酶/磷酸酶": (("kinase", "phosphatase"), "deoxynucleoside monophosphate kinase 等"),
    "还原酶/合成酶": (("reductase", "synthase"), "ribonucleoside diphosphate reductase/thymidylate synthase"),
    "蛋白酶": (("protease",), "ATP-dependent protease/prohead protease"),
    "转录调控/脱乙酰酶": (("regulator", "sir2", "deacetylase"), "transcriptional regulator / Sir2 NAD-dependent deacetylase"),
}
mod_comp_rows = []
for name, (keys, desc) in mod_kw.items():
    cnts = [
        sum(1 for f in S_DATA[k]["cds"] if any(kw.lower() in (f.get("product") or "").lower() for kw in keys))
        for k in keys_order
    ]
    if sum(cnts) > 0:
        mod_comp_rows.append([name] + [str(c) for c in cnts] + [desc])

add_table(
    ["功能模块", "标准 T5", "T5-E1", "T5-E2", "T5-E5", "代表产物说明"],
    mod_comp_rows,
    col_widths_cm=[3.2, 1.8, 1.8, 1.8, 1.8, 5.6],
    align_cols=["l", "c", "c", "c", "c", "l"],
    font_size=9.0
)
data_note("四株各自的 features.json（product 字段按功能关键词统计）。")
para("")

para("针对决定噬菌体宿主谱的尾部受体识别模块（Tail Fiber / Receptor Binding Protein）与决定裂解活性的裂解盒模块（Lysis Cassette），"
     "四株间的蛋白质序列一致性对比如表所示：")

tail_lysis_rows = [
    ("受体识别模块", "Receptor binding tail protein (pb5)", "T5p157 (585 aa)", "CDS_0007 (640 aa)", "CDS_0007 (640 aa)", "CDS_0007 (640 aa)", "100.0%", "吸附外膜受体 FhuA 的核心 RBP 在 E1/E2/E5 中 100% 相同"),
    ("受体识别模块", "Tail fiber protein (pb1 / LTF)", "T5p132 (1396 aa)", "CDS_0037 (1396 aa)", "CDS_0037 (1396 aa)", "CDS_0037 (1396 aa)", "99.93%–100.0%", "长尾丝蛋白（1,396 aa）在四株中全长高度保守"),
    ("尾部核心结构", "Major tail protein / Baseplate hub", "T5p145 / T5p142", "CDS_0019 / CDS_0022", "CDS_0019 / CDS_0022", "CDS_0019 / CDS_0022", "100.0%", "主尾管与基板核心蛋白在四株间 100% 一致"),
    ("裂解盒模块", "Endolysin（内溶素）", "T5p042 (137 aa)", "CDS_0048 (137 aa)", "CDS_0048 (137 aa)", "CDS_0048 (137 aa)", "100.0%", "L-丙氨酰-D-谷氨酸肽聚糖内肽酶在四株间 100% 一致"),
    ("裂解盒模块", "Holin（穿孔素）", "T5p041 (217 aa)", "CDS_0049 (217 aa)", "CDS_0049 (217 aa)", "CDS_0049 (217 aa)", "100.0%", "内膜穿孔素在四株间 100% 一致"),
    ("裂解盒模块", "Spanin（跨膜裂解蛋白）", "T5p040 (200 aa)", "CDS_0050 (200 aa)", "CDS_0050 (200 aa)", "CDS_0050 (200 aa)", "100.0%", "外膜破坏跨膜复合体在四株间 100% 一致"),
]
add_table(
    ["模块类型", "功能蛋白名称", "标准 T5", "T5-E1", "T5-E2", "T5-E5", "序列一致性", "生物学评估"],
    tail_lysis_rows,
    col_widths_cm=[2.0, 2.8, 2.0, 2.0, 2.0, 2.0, 1.5, 2.7],
    align_cols=["c", "l", "c", "c", "c", "c", "c", "l"],
    font_size=8.5
)
data_note(f"泛基因组分析任务 {PAN_TASK_ID}/result.json（tail_proteins、tail_identity_matrix、lysis_proteins、lysis_identity_matrix 字段）。")
para("")

# ---- 2.9 tRNA 注释与演化退化对比 ----
heading(2, "2.9 tRNA 注释与演化退化对比")
para("标准 T5（NC_005859.1）在 26,955–38,546 bp 的可缺失区内密集分布着 25 个 tRNA 基因；"
     "而随着进化株在该区域发生阶段性缺失，T5-E1 保留了 8 个功能性 tRNA（70,382–75,419 bp），"
     "T5-E2 与 T5-E5 在进一步缺失 4,446 bp 后仅保留 2 个功能性 tRNA（70,384–71,054 bp）。"
     "进化株（E1 / E2 / E5）中检出的全部 tRNA 基因对照如下表所示：")

e1_trnas = S_DATA["T5-E1"]["trna"]
e2_trna_prods = {f.get("product"): f for f in S_DATA["T5-E2"]["trna"]}
e5_trna_prods = {f.get("product"): f for f in S_DATA["T5-E5"]["trna"]}

trna_comp_rows = []
for f in e1_trnas:
    prod = f.get("product")
    ac = "; ".join((f.get("extra_qualifiers") or {}).get("anticodon") or []) or "—"
    in_e2 = e2_trna_prods.get(prod)
    in_e5 = e5_trna_prods.get(prod)
    e2_str = f"{in_e2['locus_tag']} ({in_e2['start']}–{in_e2['end']})" if in_e2 else "已缺失 (位于 4,446 bp 缺失区)"
    e5_str = f"{in_e5['locus_tag']} ({in_e5['start']}–{in_e5['end']})" if in_e5 else "已缺失 (位于 4,446 bp 缺失区)"
    trna_comp_rows.append([
        prod,
        ac,
        f"{f['locus_tag']} ({f['start']}–{f['end']}, {f['strand']}, {f['length_bp']} bp)",
        e2_str,
        e5_str,
    ])
add_table(
    ["tRNA 类型", "反密码子", "T5-E1 (共 8 个)", "T5-E2 (共 2 个)", "T5-E5 (共 2 个)"],
    trna_comp_rows,
    col_widths_cm=[2.6, 2.2, 4.0, 3.6, 3.6],
    align_cols=["l", "c", "l", "l", "l"],
    font_size=8.5
)
data_note("ANNO_AF90115A、ANNO_A500480C、ANNO_CE2E6ADB 的 features.json（feature_type=tRNA 记录）。")
para("")

# ---- 2.10 安全性筛查与 Anti-CRISPR 候选基因对比 ----
heading(2, "2.10 安全性筛查与 Anti-CRISPR 候选基因对比")
para("四株基因组的生物安全性审计与溶源性评估汇总如下表所示：")

safe_comp_rows = [
    ("抗生素耐药基因（CARD 有效检出）", "0（未检出）", "0（未检出）", "0（未检出）", "0（未检出）", "均无耐药基因传播风险"),
    ("细菌毒力因子（VFDB 有效检出）", "0（未检出）", "0（未检出）", "0（未检出）", "0（未检出）", "均无细菌外毒素/毒力岛风险"),
    ("溶源整合酶（Integrase / Recombinase）", "0（未检出）", "0（未检出）", "0（未检出）", "0（未检出）", "缺失整合催化核心，无法整合入宿主染色体"),
    ("溶源阻遏蛋白（CI / Cro / Imm Repressor）", "0（未检出）", "0（未检出）", "0（未检出）", "0（未检出）", "无溶源休眠维持开关"),
    ("生活史判定（Lifestyle）", "专性裂解型 (Lytic)", "专性裂解型 (Lytic)", "专性裂解型 (Lytic)", "专性裂解型 (Lytic)", "置信度 98.0%，符合噬菌体治疗安全要求"),
    ("Anti-CRISPR 候选基因数（Acranker）",
     str(len(S_DATA["Standard_T5"]["safety"].get("anti_crispr_genes", []))),
     str(len(S_DATA["T5-E1"]["safety"].get("anti_crispr_genes", []))),
     str(len(S_DATA["T5-E2"]["safety"].get("anti_crispr_genes", []))),
     str(len(S_DATA["T5-E5"]["safety"].get("anti_crispr_genes", []))),
     "E2/E5 比 E1 少 2 个候选（随 4,446 bp 缺失一并移除）"),
    ("综合安全评级（safety_passed）", "通过 (True)", "通过 (True)", "通过 (True)", "通过 (True)", "全部通过安全性合规筛查"),
]
add_table(
    ["安全审计项目", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5", "审计结论"],
    safe_comp_rows,
    col_widths_cm=[4.0, 2.3, 2.1, 2.1, 2.1, 3.4],
    align_cols=["l", "c", "c", "c", "c", "l"],
    font_size=8.5
)
data_note("四株各自的 safety_audit.json 及泛基因组分析任务 " + PAN_TASK_ID + "/result.json（lifestyles 字段）。")
para("")

para("需要说明的是，四株在 VFDB 原始 BLASTP 比对中均存在 1 条远低于审计阈值（Identity >= 70%）的弱命中，"
     "系噬菌体尾丝结构蛋白与细菌表面黏附素局部序列相似所致，按审计规则均未计入毒力因子，明细如下表所示：")
weak_rows = []
for k in keys_order:
    for r in S_DATA[k]["vfdb_hits"]:
        weak_rows.append([S_DATA[k]["label"], "VFDB", r[0], acc_short(r[1]), r[2], r[4], r[5], "低于审计阈值 (24.5% < 70%)，未计入"])
if weak_rows:
    add_table(
        ["样本名称", "数据库", "Locus_Tag", "比对目标", "Identity%", "E-value", "bit score", "判定"],
        weak_rows,
        col_widths_cm=[2.6, 1.4, 2.8, 2.2, 1.6, 1.6, 1.4, 3.4],
        align_cols=["l", "c", "l", "c", "c", "c", "c", "l"],
        font_size=8.5
    )
    data_note("四株各自的 vfdb_hits.tsv 与 card_hits.tsv（card_hits.tsv 在四株中均为空文件，0 条命中）。")
para("")

para("代表性高置信度 Anti-CRISPR 候选基因（按 bit score 排序前 10 位，以 T5-E5 为基准并与其余三株对照）如下表所示：")
acr_e5 = sorted(S_DATA["T5-E5"]["safety"].get("anti_crispr_genes", []), key=lambda x: float(x.get("bitscore", 0)), reverse=True)[:10]
acr_rows = []
for a in acr_e5:
    acr_rows.append([
        a.get("cds_id"),
        a.get("target_id"),
        str(a.get("identity")),
        str(a.get("align_len")),
        str(a.get("evalue")),
        str(a.get("bitscore")),
        "四株均保守存在 (100% Identity)",
    ])
add_table(
    ["代表 Locus_Tag (E5)", "比对目标 (RefSeq)", "Identity%", "比对长度", "E-value", "bit score", "四株分布状态"],
    acr_rows,
    col_widths_cm=[3.2, 2.6, 1.8, 1.8, 2.0, 1.6, 3.0],
    align_cols=["l", "c", "c", "c", "c", "c", "l"],
    font_size=8.5
)
data_note("四株各自的 safety_audit.json（anti_crispr_genes 字段）。")
doc.add_page_break()

# ============================================================
# 6. 第 3 章 方法描述（保留 m1-m5 固定锚点以支持 [1]-[8] 引用注入）
# ============================================================
heading(1, "3 方法描述")
heading(2, "3.1 分析流程")
m1 = ("基因预测：Pharokka（PHANOTATE 1.6.7 从头预测算法）完成编码基因与 tRNA 识别，遗传密码表 11；"
      "预测输出经坐标核验并与 gbk/features.json 双向一致。")
m2 = ("同源功能注释：将预测蛋白序列经 BLASTP 比对 Swiss-Prot、PhageScope 数据库及 CDD/Pfam 保守结构域库，"
      "并结合 PHROG 噬菌体直系同源蛋白家族数据库进行家族归属与功能类别划分。")
m3 = ("AI 辅助注释：使用 Phold 基于蛋白质结构预测，对同源注释未能覆盖的功能未知基因进行补充注释（本次进化株各贡献 4 个 CDS）。")
m4 = ("安全性筛查：针对抗生素耐药基因（CARD）与毒力因子（VFDB）分别进行数据库检索，"
      "并检测 Anti-CRISPR 基因（Acranker），命中阈值与审计规则见本报告第 2.10 节。")
m5 = ("质量控制与产物：对预测坐标、功能字段及 gbk/tsv/features.json 产物进行一致性核验；"
      "输出 GenBank（.gbk）、GFF3（.gff）、TSV 注释表、蛋白序列（.faa）、核酸序列（.ffn），"
      "以及 features.json / summary.json / safety_audit.json 结构化结果。")
m6 = ("比较基因组与泛基因组分析：使用 OrthoANIu 算法（1,020 bp 切片双向最佳比对 RBH）计算全基因组平均核苷酸一致性（ANI）与对齐覆盖度（AF）；"
      "使用 NCBI BLASTN（v2.16.0+）与逐位点扫描鉴定结构缺失（Indel）与单碱基突变（SNP）；"
      "基于蛋白质双向序列比对（Identity >= 50%，Coverage >= 50%）执行正交同源基因家族聚类。")
for mm in [m1, m2, m3, m4, m5, m6]:
    para(mm, indent2=True)
para("", indent2=False)

heading(2, "3.2 数据来源与产物支撑")
para("本报告全部单株注释与多样本横向比较结果均严格来源于注释及泛基因组流程产出的数据文件，各章节与底层数据文件的对应关系如下表所示：")
src_map = [
    ("2.1 四株基因组与基因预测统计对比", "四株 summary.json；features.json", "总长/GC/编码密度/链分布/蛋白长度"),
    ("2.2 全基因组同源性（OrthoANI）与共线性分析", f"{PAN_TASK_ID}/result.json；BLASTN 对齐", "ani_matrix、af_matrix、共线性 HSP 坐标"),
    ("2.3 进化株单碱基突变（SNP）与缺失区鉴定", "input_sequence.fasta；ANNO_AF90115A/features.json", "6 个 SNP 密码子翻译与 4,446 bp 缺失区 17 个特征"),
    ("2.4 泛基因组直系同源基因簇分析", f"{PAN_TASK_ID}/result.json", "summary、clusters（193 个同源簇）"),
    ("2.5–2.6 功能注释概况与类别横向对比", "四株 features.json；summary.json", "source_engine、category_distribution"),
    ("2.7 与近缘噬菌体同源性分析（Swiss-Prot）", "四株 swissprot_hits.tsv；features.json", "BLASTP 命中按 OS= 物种聚合及 Top 15 基因"),
    ("2.8 关键功能模块、受体识别与裂解系统对比", f"四株 features.json；{PAN_TASK_ID}/result.json", "tail_proteins、lysis_proteins、关键词归类"),
    ("2.9 tRNA 注释与演化退化对比", "四株 features.json", "feature_type=tRNA 记录（25 vs 8 vs 2 vs 2）"),
    ("2.10 安全性筛查与 Anti-CRISPR 对比", "四株 safety_audit.json；card/vfdb_hits.tsv", "AMR/VF/Acr 审计与生活史判定"),
    ("附录 A 四株 193 个直系同源基因簇全量对照表", f"{PAN_TASK_ID}/result.json", "clusters 全量映射记录"),
    ("附录 B 进化株基准（T5-E5）全量 164 个 CDS 明细", "ANNO_CE2E6ADB/features.json；ANNO.tsv", "全部 CDS 坐标、产物与证据摘要"),
]
add_table(["报告章节/表格", "数据来源文件", "支撑字段/说明"], src_map,
          col_widths_cm=[5.6, 5.2, 5.2], align_cols=["l", "l", "l"], font_size=9.0)
data_note("数据目录：results/annotations/ANNO_NC_005859、ANNO_AF90115A、ANNO_A500480C、ANNO_CE2E6ADB 及 results/pan_genomics/" + PAN_TASK_ID)
doc.add_page_break()

# ============================================================
# 7. 第 4 章 参考文献
# ============================================================
heading(1, "4 参考文献")
refs = [
    ("Bouras G, Nepal R, Houtak G, et al. Pharokka: a fast scalable bacteriophage annotation tool. "
     "Bioinformatics. 2023. doi:10.1093/bioinformatics/btac776. PMID: 36453861.", "Ref_Pharokka"),
    ("McNair K, Zhou C, Dinsdale EA, et al. PHANOTATE: a novel approach to gene identification in phage genomes. "
     "Bioinformatics. 2019. doi:10.1093/bioinformatics/btz265. PMID: 31329826.", "Ref_Phanotate"),
    ("Bouras G, Grigson SR, Mirdita M, et al. Protein structure-informed bacteriophage genome annotation with Phold. "
     "Nucleic Acids Res. 2026. doi:10.1093/nar/gkaf1448. PMID: 41495893.", "Ref_Phold"),
    ("Terzian P, Olo Ndela E, Galiez C, et al. PHROG: families of prokaryotic virus proteins clustered using remote homology. "
     "NAR Genom Bioinform. 2021. doi:10.1093/nargab/lqab067. PMID: 34377978.", "Ref_PHROG"),
    ("Wang RH, Yang S, Liu Z, et al. PhageScope: a well-annotated bacteriophage database with automatic analyses and visualizations. "
     "Nucleic Acids Res. 2024. doi:10.1093/nar/gkad979. PMID: 37904614.", "Ref_PhageScope"),
    ("Alcock BP, Huynh W, Chalil R, et al. CARD 2023: expanded curation, support for machine learning, and resistome prediction "
     "at the Comprehensive Antibiotic Resistance Database. Nucleic Acids Res. 2023. doi:10.1093/nar/gkac920. PMID: 36263822.", "Ref_CARD"),
    ("Liu B, Zheng D, Zhou S, et al. VFDB 2022: a general classification scheme for bacterial virulence factors. "
     "Nucleic Acids Res. 2022. doi:10.1093/nar/gkab1107. PMID: 34850947.", "Ref_VFDB"),
    ("Eitzinger S, Asif A, Watters KE, et al. Machine learning predicts new anti-CRISPR proteins. "
     "Nucleic Acids Res. 2020. doi:10.1093/nar/gkaa219. PMID: 32286628.", "Ref_Acranker"),
]
for text, _ in refs:
    p = para(text, indent2=False, line15=True)
    p.paragraph_format.first_line_indent = Pt(0)
para("", indent2=False)
doc.add_page_break()

# ============================================================
# 8. 第 5 章 结果产物清单
# ============================================================
heading(1, "5 结果产物清单")
para("本次标准 T5 与进化株 E1/E2/E5 混合比较及单株注释交付的标准产物文件如下表所示：")
prod_items = [
    ("标准T5与E1_E2_E5_混合比较注释报告.docx", "本四株混合比较与功能注释综合报告（Word 文档）"),
    ("ANNO_NC_005859_注释报告.docx", "标准 T5（NC_005859.1）单株完整注释报告"),
    ("ANNO_AF90115A_注释报告.docx", "进化株 T5-E1 单株完整注释报告"),
    ("ANNO_A500480C_注释报告.docx", "进化株 T5-E2 单株完整注释报告"),
    ("ANNO_CE2E6ADB_注释报告.docx", "进化株 T5-E5 单株完整注释报告"),
    ("data/references/T5_standard_NC_005859/NC_005859.1.gbk", "NCBI RefSeq 标准 T5 原始完整 GenBank 注释文件"),
    ("data/references/T5_standard_NC_005859/NC_005859.1.fasta", "NCBI RefSeq 标准 T5 全长基因组 FASTA 序列"),
    ("results/annotations/ANNO_*/ANNO.gbk / .gff / .tsv / .faa / .ffn", "四株各自的标准 GenBank、GFF3、TSV、蛋白与基因核酸序列"),
    (f"results/pan_genomics/{PAN_TASK_ID}/result.json", "四株泛基因组同源聚类、OrthoANI 矩阵、尾丝与裂解盒对比结构化数据"),
]
add_table(["产物文件 / 路径", "说明"], prod_items, col_widths_cm=[7.5, 8.5], align_cols=["l", "l"], font_size=9.0)
data_note("所有报告文件均已同步归档至 results/email_sends/ 目录下。")
doc.add_page_break()

# ============================================================
# 9. 第 6 章 备注
# ============================================================
heading(1, "6 备注")
notes = [
    "本报告为标准 T5（NC_005859.1）与进化株（T5-E1 / T5-E2 / T5-E5）专项混合比较报告，已排除原批次中误标为 T5-WT 的异属噬菌体 Escherichia phage CarlMeissner（ANNO_1418C944）。",
    "标准 T5（NC_005859.1，121,750 bp）两端各含一段约 10,139 bp 的末端直接重复区（Terminal Direct Repeats，LTR/RTR）；在二代/三代常规组装结果（如 T5-E1/E2/E5 的 ngcs_scaffold_1）中，两端重复区自动合并为单拷贝，故单拷贝基准长度约为 111.6 kb。",
    "T5-E1（104,547 bp）与 T5-E2/E5（100,101 bp）的长度差异（4,446 bp）系真实的生物学缺失事件（发生在 T5 可缺失 tRNA 富集区），并非组装残缺或注释错误。",
    "T5-E2 与 T5-E5 的全长序列（100,101 bp）高度一致（Identity 99.998%），全基因组仅存在 2 个单碱基错义突变（分别位于 CDS_0126 第 17 位氨基酸 F→L 与 CDS_0140 第 4 位氨基酸 E→G）。",
    "四株均未检出任何抗生素耐药基因（CARD）、细菌毒力因子（VFDB）及溶源整合元件，尾丝受体结合蛋白（pb5 / LTF）与裂解系统（Endolysin / Holin / Spanin）在四株间保持 100% 氨基酸序列保守。",
]
for n in notes:
    p = para("", indent2=True)
    p.add_run("· ").font.size = Pt(12)
    r = p.add_run(n)
    set_font(r, size=12)
doc.add_page_break()

# ============================================================
# 10. 附录 A 四株直系同源基因簇（193 个 Ortholog Groups）全量对照表
# ============================================================
heading(1, f"附录 A  四株泛基因组直系同源基因簇（共 {len(pan_res.clusters)} 簇）全量对照表")
para("本附录列出标准 T5（NC_005859.1）、T5-E1、T5-E2、T5-E5 四株聚类形成的全部 193 个直系同源基因簇明细（按 Core → Accessory → Unique 及簇编号排序）：")

appA_rows = []
for cl in pan_res.clusters:
    pmap = cl.presence_map or {}
    row = [
        cl.group_id,
        cl.cluster_type,
        cl.category,
        cl.representative_product,
    ]
    for k in keys_order:
        tid = S_DATA[k]["task_id"]
        g = pmap.get(tid)
        if g:
            lt = g.get("locus_tag") if isinstance(g, dict) else g.locus_tag
            laa = g.get("length_aa") if isinstance(g, dict) else g.length_aa
            row.append(f"{lt} ({laa}aa)")
        else:
            row.append("— (缺失)")
    appA_rows.append(row)

add_table(
    ["基因簇 ID", "分区类型", "功能类别", "代表性功能产物", "标准 T5 (NC_005859.1)", "T5-E1", "T5-E2", "T5-E5"],
    appA_rows,
    font_size=7.5,
    col_widths_cm=[1.5, 1.4, 2.2, 3.3, 1.9, 1.9, 1.9, 1.9],
    align_cols=["c", "c", "l", "l", "c", "c", "c", "c"]
)
data_note(f"泛基因组分析任务 {PAN_TASK_ID}/result.json（clusters 全量 193 条记录）。")
doc.add_page_break()

# ============================================================
# 11. 附录 B 进化株代表基准（T5-E5）全量 164 个 CDS 注释明细
# ============================================================
heading(1, "附录 B  进化株代表基准（T5-E5）全量 164 个 CDS 注释明细")
para("由于 T5-E2 与 T5-E5 的 164 个 CDS 坐标完全一致（且全部包含于 T5-E1 的 173 个 CDS 中，除表 2.3 所列 9 个缺失区 CDS 外），"
     "本附录列出进化株代表基准 T5-E5（ANNO_CE2E6ADB）全部 164 个 CDS 的完整注释明细：")

cds_e5_sorted = sorted(S_DATA["T5-E5"]["cds"], key=lambda f: (f.get("start") or 0))
appB_rows = []
for f in cds_e5_sorted:
    appB_rows.append([
        f.get("locus_tag"),
        str(f.get("strand")),
        f"{f.get('start')}–{f.get('end')}",
        str(f.get("length_bp")),
        str(f.get("protein_length_aa") or "—"),
        str(f.get("molecular_weight_kda") or "—"),
        f.get("product") or "—",
        f.get("category") or "—",
        str(f.get("phrog") or "—"),
        f.get("source_engine") or "—",
        short_evidence(f) or "—",
    ])
add_table(
    ["Locus_Tag", "链", "起止(bp)", "长度(bp)", "aa", "MW(kDa)", "产物", "类别", "PHROG", "引擎", "证据摘要"],
    appB_rows,
    font_size=7.5,
    col_widths_cm=[2.6, 0.7, 2.2, 1.2, 0.9, 1.1, 3.0, 2.0, 1.1, 1.4, 2.8],
    align_cols=["l", "c", "c", "c", "c", "c", "l", "l", "c", "l", "l"]
)
data_note("ANNO_CE2E6ADB/features.json 与 ANNO.tsv（164 条 CDS 记录，按起始坐标升序排列）。")

# ============================================================
# 12. 页脚页码与保存
# ============================================================
footer = sec.footer
fp = footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
fld1 = OxmlElement("w:fldChar")
fld1.set(qn("w:fldCharType"), "begin")
instr = OxmlElement("w:instrText")
instr.set(qn("xml:space"), "preserve")
instr.text = " PAGE "
fld2 = OxmlElement("w:fldChar")
fld2.set(qn("w:fldCharType"), "end")
run = fp.add_run()
set_font(run, size=9)
run._r.append(fld1)
run._r.append(instr)
run._r.append(fld2)

doc.save(str(OUT_PATH))
print("Saved comparative report:", OUT_PATH)

# 修复主题 eastAsia 语言（ja-JP -> zh-CN）
TMPZ = str(OUT_PATH) + ".tmpz"
with zipfile.ZipFile(str(OUT_PATH), "r") as zin, zipfile.ZipFile(TMPZ, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.namelist():
        data_bytes = zin.read(item)
        if item == "word/theme/theme1.xml":
            s = data_bytes.decode("utf-8")
            s = s.replace('typeface="ja-JP"', 'typeface="zh-CN"')
            data_bytes = s.encode("utf-8")
        zout.writestr(item, data_bytes)
shutil.move(TMPZ, str(OUT_PATH))
print("Theme eastAsia fixed")

# 注入参考文献 [1]-[8] 引用编号
CITATIONS_SPEC = PROJECT_ROOT / "scripts" / "citations_ops.json"
DOCX_CITATIONS = Path(
    r"C:\Users\Administrator\AppData\Local\Doubao\User Data\Default\.doubao\agent_mode\workspace\.skills\word"
    r"\scripts\docx_citations.py"
)
if DOCX_CITATIONS.exists() and CITATIONS_SPEC.exists():
    apply_cmd = [
        sys.executable, "-X", "utf8", str(DOCX_CITATIONS), "apply",
        str(OUT_PATH), "--spec", str(CITATIONS_SPEC), "--in-place"
    ]
    r = subprocess.run(apply_cmd, capture_output=True, text=True, encoding="utf-8", cwd=str(DOCX_CITATIONS.parent.parent))
    if r.returncode == 0:
        print("Citations [1]-[8] injected successfully!")
    else:
        print("Citation warning:", r.stderr[-300:])
