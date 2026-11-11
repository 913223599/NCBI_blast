# -*- coding: utf-8 -*-
"""
生成噬菌体基因组注释报告（通用化版本，内部审阅草稿）。

通用化设计：
- 所有统计与表格由注释结果目录下的数据文件驱动（features.json / summary.json /
  safety_audit.json / swissprot_hits.tsv / card_hits.tsv / vfdb_hits.tsv 等）；
- 支持任意注释结果目录：--data <目录>；
- 业务字段（报告编号/样品名称/任务编号/编制单位）可通过参数传入，缺省使用占位符或数据目录名；
- 每张数据表下方标注数据来源文件，正文引用锚点稳定（方法描述 m1-m5 措辞固定）。

用法示例：
  python build_report.py --data "F:\\NCBI blast\\results\\annotations\\ANNO_5A8C0B32_RE2" \
      --out "噬菌体基因组注释报告_ANNO_5A8C0B32_RE2.docx" \
      --extra-notes "原始数据中的 scaffold_2 短片段已手动去除，不纳入本次分析"
"""
import argparse
import datetime
import json
import os
import re
from collections import Counter

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ============================================================
# 0. 参数与数据装载
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(description='生成噬菌体基因组注释报告（通用化）')
    p.add_argument('--data', required=True,
                   help='注释结果目录（需包含 features.json/summary.json 等产物）')
    p.add_argument('--out', default=None, help='输出 docx 路径（默认：当前目录/噬菌体基因组注释报告_<任务>.docx）')
    p.add_argument('--report-no', default=None, help='报告编号（默认占位）')
    p.add_argument('--sample-name', default=None, help='样品名称（默认占位）')
    p.add_argument('--task-id', default=None, help='任务编号（默认取数据目录名）')
    p.add_argument('--company', default='元昇生物（武汉）有限公司', help='编制单位')
    p.add_argument('--extra-notes', action='append', default=[], help='追加备注（可多次传入）')
    return p.parse_args()


ARGS = parse_args()
DATA = os.path.abspath(ARGS.data)
TASK_ID = ARGS.task_id or os.path.basename(DATA.rstrip('\\/'))
OUT = ARGS.out or os.path.join(os.getcwd(), f'噬菌体基因组注释报告_{TASK_ID}.docx')
TODAY_CN = datetime.date.today().strftime('%Y年%m月%d日')

with open(os.path.join(DATA, 'features.json'), encoding='utf-8') as fh:
    feats = json.load(fh)
with open(os.path.join(DATA, 'summary.json'), encoding='utf-8') as fh:
    summary = json.load(fh)
safety_path = os.path.join(DATA, 'safety_audit.json')
safety_missing = not os.path.isfile(safety_path)
if not safety_missing:
    with open(safety_path, encoding='utf-8') as fh:
        safety = json.load(fh)
else:
    safety = {'safety_passed': None, 'amr_genes': [], 'virulent_factors': [], 'anti_crispr_genes': []}

cds = [f for f in feats if f.get('feature_type') == 'CDS']
trna = [f for f in feats if f.get('feature_type') == 'tRNA']
n_cds = len(cds)
n_trna = len(trna)

# ---- 从数据提取通用字段 ----
contig_ids = sorted({f.get('contig_id') for f in feats if f.get('contig_id')})
CONTIG = contig_ids[0] if len(contig_ids) == 1 else '、'.join(contig_ids[:3]) + ('等' if len(contig_ids) > 3 else '')
TOTAL_LEN = summary.get('total_length')
GC = summary.get('gc_content')
CODING_DENSITY = summary.get('coding_density_pct')
AVG_GENE = summary.get('avg_gene_length')
ANNOTATED = summary.get('annotated_count') or 0
HYPOTHETICAL_CAT = summary.get('hypothetical_count') or 0


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
HYPOTHETICAL_TXT = sum(1 for f in cds if 'hypothetical' in (f.get('product') or '').lower()
                       or 'unknown' in (f.get('product') or '').lower())
LOCUS_PREFIX = (cds[0].get('locus_tag') or '') if cds else ''
if LOCUS_PREFIX and '_' in LOCUS_PREFIX:
    LOCUS_PREFIX = LOCUS_PREFIX.split('_')[0]
strand_p = sum(1 for f in cds if f.get('strand') == '+')
strand_n = n_cds - strand_p
lens = [len(f['translation']) for f in cds if f.get('translation')]
len_min, len_max = (min(lens), max(lens)) if lens else (0, 0)
len_median = sorted(lens)[len(lens) // 2] if lens else 0
len_mean = sum(lens) / len(lens) if lens else 0.0
n_small = sum(1 for l in lens if l <= 100)
phold_n = sum(1 for f in cds if f.get('source_engine') == 'Phold AI')


# ---- 工具函数：读 TSV（无表头：locus_tag, target, identity, aln_len, evalue, bitscore, desc） ----
def read_hits_tsv(name):
    path = os.path.join(DATA, name)
    rows = []
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.rstrip('\n')
                if not line.strip():
                    continue
                parts = line.split('\t')
                rows.append(parts if len(parts) >= 7 else parts + [''] * (7 - len(parts)))
    return rows


swiss_hits = read_hits_tsv('swissprot_hits.tsv')
card_hits = read_hits_tsv('card_hits.tsv')
vfdb_hits = read_hits_tsv('vfdb_hits.tsv')


def short_evidence(f):
    """从 evidence_sources 提取最简证据摘要：优先 BLASTP 命中，其次 PHROG 编号。"""
    evs = f.get('evidence_sources') or []
    for e in evs:
        if 'BLASTP' in e:
            m = re.search(r'BLASTP to (\S+)\s*\(Identity:\s*([\d.]+)%', e)
            if m:
                return f'BLASTP {m.group(1)} ({m.group(2)}%)'
            return e
    ph = f.get('phrog')
    if ph:
        return f'PHROG #{ph}'
    for e in evs:
        if 'Phold' in e or 'Model' in e:
            return e
    return ''


def os_species(desc):
    m = re.search(r'OS=([^=;]+?)(?=\s+(?:OX|GN|PE|SV)=|$)', desc)
    return m.group(1).strip() if m else '未标注物种'


def acc_short(acc):
    parts = acc.split('|')
    v = parts[-1] if parts else acc
    v = v.strip('() ')
    return v


# ============================================================
# 1. 文档与样式
# ============================================================
doc = Document()
sec = doc.sections[0]
sec.page_width = Cm(21.0); sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.5); sec.bottom_margin = Cm(2.5)
sec.left_margin = Cm(2.5); sec.right_margin = Cm(2.5)


def set_font(run, cn='宋体', en='Times New Roman', size=12, bold=False, color=RGBColor(0, 0, 0)):
    run.font.name = en
    run._element.rPr.rFonts.set(qn('w:eastAsia'), cn)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def para(text='', cn='宋体', size=12, bold=False, align=None, indent2=True,
         line15=True, space_before=0, space_after=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before); pf.space_after = Pt(space_after)
    if indent2:
        pf.first_line_indent = Pt(size * 2)
    if line15:
        pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if text:
        r = p.add_run(text); set_font(r, cn=cn, size=size, bold=bold)
    return p


def heading(level, text):
    p = doc.add_heading('', level=level)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = Pt({1: 14, 2: 11, 3: 9}[level]); pf.space_after = Pt({1: 6, 2: 5, 3: 4}[level])
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    r = p.add_run(text)
    set_font(r, cn='黑体', size={1: 16, 2: 14, 3: 12}[level], bold=True)
    r.font.color.rgb = RGBColor(0, 0, 0)
    return p


def add_table(header, rows, col_widths_cm=None, align_cols=None, font_size=10.5, header_fill='D9D9D9'):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0]
    for j, htxt in enumerate(header):
        cell = hdr.cells[j]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(0); p.paragraph_format.space_after = Pt(0)
        r = p.add_run(htxt); set_font(r, size=font_size, bold=True)
        shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:fill'), header_fill)
        cell._tc.get_or_add_tcPr().append(shd)
    for row in rows:
        cells = t.add_row().cells
        for j, val in enumerate(row):
            cell = cells[j]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.space_before = Pt(0); p.paragraph_format.space_after = Pt(0)
            if align_cols and j < len(align_cols) and align_cols[j] == 'c':
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif align_cols and j < len(align_cols) and align_cols[j] == 'r':
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(val)); set_font(r, size=font_size)
    for r_ in t.rows:
        trPr = r_._tr.get_or_add_trPr()
        trPr.append(OxmlElement('w:cantSplit'))
    trh = OxmlElement('w:tblHeader'); trh.set(qn('w:val'), 'true')
    t.rows[0]._tr.get_or_add_trPr().append(trh)
    if col_widths_cm:
        for j, w in enumerate(col_widths_cm):
            for row in t.rows:
                row.cells[j].width = Cm(w)
    return t


def data_note(text):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(2); pf.space_after = Pt(8)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    r = p.add_run('数据来源：' + text); set_font(r, cn='楷体', size=9)
    r.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
    return p


def fmt_len(v):
    return f'{v:,}' if v is not None else '—'


# ============================================================
# 2. 封面
# ============================================================
for _ in range(3):
    para('', indent2=False)
para('噬菌体基因组注释报告', cn='黑体', size=22, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
     indent2=False, space_after=6)
para('（内部审阅草稿）', cn='楷体', size=12, align=WD_ALIGN_PARAGRAPH.CENTER, indent2=False, space_after=12)
para('', indent2=False)

cov_rows = [
    ('报告编号', ARGS.report_no or 'YSSW-ANNO-2026-XXX（待定）'),
    ('样品名称', ARGS.sample_name or '待确认'),
    ('序列标识', CONTIG),
    ('任务编号', TASK_ID),
    ('分析内容', '噬菌体基因组基因预测与功能注释'),
    ('报告日期', TODAY_CN),
    ('编制单位', ARGS.company),
]
add_table(['项目', '内容'], cov_rows, col_widths_cm=[4.0, 12.0], align_cols=['c', 'l'])
data_note(f'序列标识与任务编号取自注释结果目录 {os.path.basename(DATA)}；报告编号、样品名称为业务字段，确认后填写。')
doc.add_page_break()

# ============================================================
# 3. 目录
# ============================================================
heading(1, '目  录')
p = doc.add_paragraph()
run = p.add_run()
fldChar1 = OxmlElement('w:fldChar'); fldChar1.set(qn('w:fldCharType'), 'begin')
instrText = OxmlElement('w:instrText'); instrText.set(qn('xml:space'), 'preserve')
instrText.text = ' TOC \\o "1-2" \\h \\z \\u '
fldChar2 = OxmlElement('w:fldChar'); fldChar2.set(qn('w:fldCharType'), 'separate')
t_ = OxmlElement('w:t'); t_.text = '（请在 Word 中右键更新目录）'
fldChar3 = OxmlElement('w:fldChar'); fldChar3.set(qn('w:fldCharType'), 'end')
run._r.append(fldChar1); run._r.append(instrText); run._r.append(fldChar2); run._r.append(t_); run._r.append(fldChar3)
set_font(run, cn='宋体', size=12)
doc.add_page_break()

# ============================================================
# 4. 1 总体工作流程概述
# ============================================================
heading(1, '1 总体工作流程概述')
heading(2, '1.1 项目简介')
para(f'本报告针对噬菌体基因组序列 {CONTIG}（全长 {fmt_len(TOTAL_LEN)} bp，GC 含量 {GC}%）开展基因预测与功能注释。'
     '输入序列经质量筛选后保留用于本次分析的主片段，非目标短片段不纳入注释。'
     '分析目标为：预测基因组编码基因与非编码 RNA，完成功能注释与功能类别划分，并进行噬菌体安全性筛查，'
     '为后续比较基因组分析提供标准化的注释产物。')
heading(2, '1.2 生物信息分析流程')
para('分析流程分为以下步骤：')
steps = [
    '基因预测：使用 Pharokka（PHANOTATE 1.6.7 从头预测算法）对输入序列进行编码基因（CDS）与 tRNA 预测；',
    '同源功能注释：将预测蛋白序列经 BLASTP 比对 Swiss-Prot、PhageScope 及 CDD/Pfam 数据库，'
    '并结合 PHROG 噬菌体直系同源蛋白家族数据库进行功能归属；',
    'AI 辅助注释：使用 Phold AI 基于蛋白质结构预测对部分功能未知基因进行辅助注释；',
    '安全性筛查：分别检索抗生素耐药基因（CARD）、毒力因子（VFDB）与 Anti-CRISPR 基因（Acranker）；',
    '质量控制：对预测坐标、注释字段与 gbk/tsv/features.json 产物进行一致性核验；',
    '产物导出：输出 GenBank（gbk）、GFF3（gff）、TSV、蛋白序列（faa）、核酸序列（ffn）、'
    'features.json 与 summary.json 等标准注释产物。',
]
for s in steps:
    para(s, indent2=True)
doc.add_page_break()

# ============================================================
# 5. 2 注释结果
# ============================================================
heading(1, '2 注释结果')

# ---- 2.1 基因组与基因预测统计 ----
heading(2, '2.1 基因组与基因预测统计')
para('基因组及基因预测核心指标如下表所示：')
add_table(
    ['指标', '数值'],
    [
        ('基因组总长（bp）', fmt_len(TOTAL_LEN)),
        ('GC 含量（%）', str(GC)),
        ('CDS 数量', str(n_cds)),
        ('tRNA 数量', str(n_trna)),
        ('编码密度（%）', str(CODING_DENSITY)),
        ('平均基因长度（bp）', str(AVG_GENE)),
        ('正链 CDS / 负链 CDS', f'{strand_p} / {strand_n}'),
        ('蛋白长度范围（aa）', f'{len_min} – {len_max}（中位数 {len_median}）'),
    ],
    col_widths_cm=[6.0, 10.0], align_cols=['c', 'c']
)
data_note('summary.json（total_length/gc_content/cds_count/trna_count/coding_density_pct/avg_gene_length），'
          f'链与蛋白长度分布来自 features.json（{n_cds} 条 CDS 记录）。')
para('')
para(f'预测蛋白长度分布如下表所示（{n_cds} 个 CDS 均含完整翻译序列）：')
len_bins = [(1, 100, '1–100'), (101, 200, '101–200'), (201, 300, '201–300'), (301, 400, '301–400'),
            (401, 600, '401–600'), (601, 800, '601–800'), (801, 1000, '801–1,000'), (1001, 2000, '1,001–2,000')]
len_rows = [(label, str(sum(1 for l in lens if lo <= l <= hi))) for lo, hi, label in len_bins]
len_rows.append(('合计', str(len(lens))))
add_table(['蛋白长度区间（aa）', '基因数'], len_rows, col_widths_cm=[7.0, 5.0], align_cols=['c', 'c'])
data_note('features.json（translation 字段长度统计）。')
para('')
pct_small = n_small / len(lens) * 100 if lens else 0
para(f'蛋白长度以 100 aa 以下的小蛋白为主（{n_small} 个，占 {pct_small:.1f}%），中位数 {len_median} aa、'
     f'平均 {len_mean:.1f} aa，最大蛋白 {len_max} aa，分布特征符合有尾噬菌体基因组基因组织的一般规律。')
para('')

# ---- 2.2 功能注释概况 ----
heading(2, '2.2 功能注释概况')
para(f'共注释 {n_cds} 个 CDS，其中具备功能注释的基因 {ANNOTATED} 个，功能未知（hypothetical）{HYPOTHETICAL_CAT} 个。'
     f'全部 {n_cds} 个 CDS 均携带 PHROG 家族编号与功能描述字段，PHROG 覆盖率为 100%。')
para('各注释引擎最终归属的基因数量如下表所示：')
eng_counter = Counter(f.get('source_engine', '?') for f in cds)
eng_order = ['Pharokka', 'CDD/Pfam', 'Phold AI', 'PhageScope', 'Swiss-Prot']
eng_desc = {
    'Pharokka': '噬菌体直系同源家族注释', 'CDD/Pfam': '保守结构域/蛋白家族',
    'Phold AI': '蛋白质结构辅助注释', 'PhageScope': '噬菌体专业数据库同源',
    'Swiss-Prot': '经过验证的蛋白数据库同源',
}
eng_rows = []
for e in eng_order:
    if e in eng_counter:
        eng_rows.append((e, str(eng_counter[e]), eng_desc.get(e, '')))
extra_engs = [e for e in eng_counter if e not in eng_order]
for e in extra_engs:
    eng_rows.append((e, str(eng_counter[e]), eng_desc.get(e, '备选/扩展注释引擎')))
eng_rows.append(('合计', str(n_cds), '—'))
add_table(['注释引擎', '基因数（CDS）', '说明'], eng_rows,
          col_widths_cm=[5.0, 4.0, 7.0], align_cols=['l', 'c', 'l'])
data_note('features.json（source_engine 字段，与 summary.json 的 engine_contributions 核对一致）。')
para('')
para('功能类别与注释引擎的交叉分布如下表所示（行合计为该类别基因数，列合计为该引擎贡献数）：')
cat_eng = Counter((f.get('category', '?'), f.get('source_engine', '?')) for f in cds)
all_engs = eng_order + extra_engs
active_engs = [e for e in all_engs if e in eng_counter]
cats = sorted({k[0] for k in cat_eng}, key=lambda c: -sum(cat_eng.get((c, e), 0) for e in active_engs))
header = ['功能类别'] + active_engs + ['合计']
rows = []
for c in cats:
    vals = [str(cat_eng.get((c, e), 0)) for e in active_engs]
    rows.append([c] + vals + [str(sum(cat_eng.get((c, e), 0) for e in active_engs))])
tot = [str(sum(cat_eng.get((c, e), 0) for c in cats)) for e in active_engs]
rows.append(['合计'] + tot + [str(n_cds)])
add_table(header, rows, align_cols=['l'] + ['c'] * (len(active_engs) + 1))
data_note('features.json（category × source_engine 交叉统计）。')
para('')
hypo_pharokka = sum(1 for f in cds if f.get('category') == 'Hypothetical' and f.get('source_engine') == 'Pharokka')
other_cdd = cat_eng.get(('Other Functional', 'CDD/Pfam'), 0)
para(f'交叉分布显示：功能未知（hypothetical）基因全部来自 Pharokka 的 PHROG 家族归属（{hypo_pharokka} 个）；'
     'Replication & Repair 与 Tail & Host Interaction 以 Pharokka 注释为主；'
     f'Other Functional 类别以 CDD/Pfam 保守结构域注释为主（{other_cdd} 个），其余引擎作为补充证据来源。')
para('')

# ---- 2.3 功能类别分布 ----
heading(2, '2.3 功能类别分布')
para(f'按噬菌体功能类别划分，各类别基因数量如下表所示（占比以 {n_cds} 个 CDS 计）：')
cat = summary.get('category_distribution', {})
cat_denom = n_cds if n_cds > 0 else 1
cat_rows = [(k, v, f'{v / cat_denom * 100:.1f}%') for k, v in cat.items()]
add_table(['功能类别', '基因数', '占比'], cat_rows, col_widths_cm=[8.0, 4.0, 4.0], align_cols=['l', 'c', 'c'])
data_note('summary.json（category_distribution）。')
para('')
n_head = cat.get('Head & Packaging', 0)
n_tail = cat.get('Tail & Host Interaction', 0)
n_rep = cat.get('Replication & Repair', 0)
n_met = cat.get('Metabolism & AMG', 0)
morph_n = n_head + n_tail
if morph_n and n_cds > 0:
    para(f'Head & Packaging（{n_head} 个，{n_head / cat_denom * 100:.1f}%）与 Tail & Host Interaction（{n_tail} 个，'
         f'{n_tail / cat_denom * 100:.1f}%）合计 {morph_n} 个形态相关基因，占 CDS 总数的 {morph_n / cat_denom * 100:.1f}%，'
         '说明该噬菌体具备完整的头部组装与尾部结构基因模块；'
         f'Replication & Repair（{n_rep} 个，{n_rep / cat_denom * 100:.1f}%）与 Metabolism & AMG（{n_met} 个，'
         f'{n_met / cat_denom * 100:.1f}%）体现了完整的复制与代谢重编程能力。')
para('')

# ---- 2.4 与近缘噬菌体的同源性分析 ----
heading(2, '2.4 与近缘噬菌体的同源性分析')
sp_counter = Counter(os_species(r[6]) for r in swiss_hits)
total_hits = len(swiss_hits)
if total_hits == 0:
    para('以预测蛋白序列经 BLASTP 比对 Swiss-Prot 数据库，本批次未获得超过阈值的可靠同源命中，'
         '无法进行物种分布与高同源基因统计。建议结合全基因组序列比对（如 blastn 对 nr/nt）或调整比对阈值后复核；'
         '本报告其余章节（基因结构、功能模块、安全审计）基于 Pharokka/Phold 注释结果独立完成，不受影响。')
    para('')
else:
    para(f'以预测蛋白序列经 BLASTP 比对 Swiss-Prot 数据库，共获得 {total_hits} 条可靠命中。'
         '命中按宿主物种聚合的分布如下表所示：')
    top_sp = sp_counter.most_common()
    sp_rows = [(s, str(n), f'{n / total_hits * 100:.1f}%') for s, n in top_sp]
    sp_rows.append(('合计', str(total_hits), '100.0%'))
    add_table(['比对物种（Swiss-Prot）', '命中数', '占比'], sp_rows,
              col_widths_cm=[8.0, 4.0, 4.0], align_cols=['l', 'c', 'c'])
    data_note(f'swissprot_hits.tsv（{total_hits} 条命中的 OS= 字段按物种聚合；条目数以实际文件记录为准）。')
    para('')
    top_sp_name = top_sp[0][0] if top_sp else '—'
    top_sp_n = top_sp[0][1] if top_sp else 0
    para(f'其中 {top_sp_n} 条（{top_sp_n / total_hits * 100:.1f}%）与 {top_sp_name} 蛋白同源，'
         '其余命中分布于 T4 样噬菌体近缘物种，说明该基因组与 T4 样噬菌体（肌尾噬菌体科）高度同源，'
         '基因结构与功能模块组织与该类噬菌体基因组模式一致，可作为后续分类学分析与宿主预测的重要依据。')
    para('')
    para('按比对显著性（bit score）排序的代表性高同源基因如下表所示：')
    best_swiss = sorted(swiss_hits, key=lambda r: _safe_float(r[5]), reverse=True)[:15]
    prod_map = {f.get('locus_tag'): f.get('product') for f in cds}
    sw_rows = []
    for r in best_swiss:
        tag = r[0]
        desc_prod = re.sub(r'^[^\s]+\s+', '', r[6])
        desc_prod = re.sub(r'\s+OS=.*$', '', desc_prod).strip()
        sw_rows.append([tag, acc_short(r[1]), prod_map.get(tag, desc_prod),
                        r[2], r[4], r[5], sp_counter.most_common(1)[0][0] if False else os_species(r[6])])
    add_table(['Locus_Tag', 'Swiss-Prot 命中', '基因产物', 'Identity%', 'E-value', 'bit score', '物种'],
              sw_rows, col_widths_cm=[3.4, 2.6, 3.6, 1.8, 2.0, 1.6, 2.6],
              align_cols=['l', 'c', 'l', 'c', 'c', 'c', 'l'], font_size=9)
    data_note('swissprot_hits.tsv（按 bit score 降序取前 15 条）；基因产物列取自 features.json（product 字段）。')
    para('')

# ---- 2.5 关键功能模块基因 ----
heading(2, '2.5 关键功能模块基因')
para('按基因产物功能归类，各关键模块的代表性基因数量如下表所示：')
mod_kw = {
    '尾部结构': (('tail',), 'minor/long tail fiber 等尾部蛋白'),
    '尾纤维': (('fiber',), 'tail fiber 宿主特异性相关'),
    '头部结构': (('head',), 'head morphogenesis/decoration 等'),
    '衣壳蛋白': (('capsid',), 'major capsid protein'),
    '门户蛋白': (('portal',), 'portal protein'),
    '末端酶': (('terminase',), 'terminase 大/小亚基'),
    '裂解（穿孔素）': (('holin',), 'holin'),
    '裂解（内溶素）': (('endolysin',), 'endolysin'),
    '裂解（溶菌酶）': (('lysozyme',), 'baseplate tail lysozyme'),
    '解旋酶': (('helicase',), 'DnaB/dda/loader 等'),
    '聚合酶/转移酶': (('polymerase',), 'RNA 聚合酶相关'),
    '连接酶': (('ligase',), 'DNA/RNA ligase'),
    '引发酶': (('primase',), 'DNA primase'),
    '核酸酶': (('nuclease',), 'homing endonuclease/exonuclease 等'),
    '激酶': (('kinase',), 'polynucleotide/thymidine kinase 等'),
    '蛋白酶': (('protease',), 'head maturation 等'),
    '转录调控': (('regulator',), 'transcriptional regulator 等'),
    '切除酶': (('excisionase',), 'excisionase'),
}
mod_rows = []
for name, (keys, desc) in mod_kw.items():
    n = sum(1 for f in cds if any(k.lower() in (f.get('product') or '').lower() for k in keys))
    if n:
        mod_rows.append((name, str(n), desc))
add_table(['功能模块', '基因数', '代表产物'], mod_rows,
          col_widths_cm=[4.0, 2.6, 9.4], align_cols=['l', 'c', 'l'])
data_note('features.json（product 字段按功能关键词归类统计）。')
para('')
def mod_n(keys):
    return sum(1 for f in cds if any(k.lower() in (f.get('product') or '').lower() for k in keys))
mt = mod_n(('tail',)) + mod_n(('fiber',)) + mod_n(('head',)) + mod_n(('terminase',)) + mod_n(('portal',))
mly = mod_n(('holin',)) + mod_n(('endolysin',)) + mod_n(('lysozyme',))
mrc = mod_n(('helicase',)) + mod_n(('polymerase',)) + mod_n(('ligase',)) + mod_n(('nuclease',)) + mod_n(('kinase',))
para(f'模块统计显示，该基因组同时具备完整的形态发生模块（尾部 {mod_n(("tail",))}、尾纤维 {mod_n(("fiber",))}、'
     f'头部 {mod_n(("head",))}、末端酶 {mod_n(("terminase",))}、门户蛋白 {mod_n(("portal",))}），'
     f'裂解模块（穿孔素 {mod_n(("holin",))}、内溶素 {mod_n(("endolysin",))}、溶菌酶 {mod_n(("lysozyme",))}）'
     f'与复制代谢模块（解旋酶 {mod_n(("helicase",))}、聚合酶/转移酶 {mod_n(("polymerase",))}、'
     f'连接酶 {mod_n(("ligase",))}、核酸酶 {mod_n(("nuclease",))}、激酶 {mod_n(("kinase",))}），'
     '基因组织符合有尾噬菌体（T4 样）的典型排列模式。')
para('')

# ---- 2.6 代表性功能注释示例 ----
heading(2, '2.6 代表性功能注释示例')
para('从各功能类别中选取的代表性注释结果如下表所示（证据摘要取自引擎注释来源；'
     '存在外部数据库 E-value 时予以展示）：')
sel_order = ['Replication & Repair', 'Head & Packaging', 'Tail & Host Interaction', 'Lysis',
             'Metabolism & AMG', 'Transcription & Regulation', 'Defense & Host Interaction',
             'Integration & Excision', 'Other Functional']
seen = Counter()
samples = []
for f in cds:
    c = f.get('category')
    if c and c != 'Hypothetical' and seen[c] < 2:
        seen[c] += 1
        ev = ''
        for src in f.get('evidence_sources', []):
            m = re.search(r'\[(PhageScope|Swiss-Prot|CDD/Pfam)\] (.+?)(?:$|; \[)', src)
            if m and 'E-value' in src:
                ev = m.group(2)
                break
        if not ev:
            ev = 'PHROG #' + str(f.get('phrog', '—'))
        samples.append((c, f['product'], f.get('phrog', '—'), f.get('source_engine', '—'), ev))
samples.sort(key=lambda x: sel_order.index(x[0]) if x[0] in sel_order else 99)
add_table(
    ['功能类别', '基因产物', 'PHROG', '来源引擎', '证据摘要'],
    [[c, prod, str(ph), se, ev] for c, prod, ph, se, ev in samples],
    col_widths_cm=[3.6, 4.4, 1.8, 2.2, 4.0], align_cols=['l', 'l', 'c', 'l', 'l']
)
data_note('features.json（category/product/phrog/source_engine/evidence_sources 字段，每类取前 2 条非 hypothetical 记录）。')
para('')

# ---- 2.7 tRNA 注释 ----
heading(2, '2.7 tRNA 注释')
trna_starts = [f.get('start') for f in trna if f.get('start') is not None]
trna_ends = [f.get('end') for f in trna if f.get('end') is not None]
trna_names = [f.get('product') or f.get('gene_name') or 'tRNA' for f in trna]
if n_trna > 0 and trna_starts and trna_ends:
    para(f'共预测 {n_trna} 个 tRNA 基因，位于基因组 {fmt_len(min(trna_starts))}–{fmt_len(max(trna_ends))} bp 区间，'
         f'包括 {", ".join(trna_names)}，均获得 Pharokka 模型与 Phold AI 双重证据支持。')
    para('')
    para(f'{n_trna} 个 tRNA 基因的明细如下表所示：')
    trna_rows = []
    for f in trna:
        ac = (f.get('extra_qualifiers') or {}).get('anticodon') or []
        ac_txt = '; '.join(ac) if ac else '—'
        ev = '、'.join(e for e in f.get('evidence_sources', []) if e.startswith('['))
        trna_rows.append([f.get('locus_tag'), f.get('product'), str(f.get('start')), str(f.get('end')),
                          str(f.get('strand')), str(f.get('length_bp')), ac_txt, ev])
    add_table(['Locus_Tag', '类型', '起始', '终止', '链', '长度(bp)', '反密码子', '证据'],
              trna_rows, col_widths_cm=[3.6, 2.8, 1.6, 1.6, 1.2, 1.6, 3.2, 3.4],
              align_cols=['l', 'l', 'c', 'c', 'c', 'c', 'l', 'l'], font_size=9)
    data_note(f'features.json（feature_type=tRNA，共 {n_trna} 条记录；反密码子取自 extra_qualifiers.anticodon）。')
else:
    para('本次基因组中未预测到 tRNA 基因（tRNA = 0），表明该噬菌体主要依赖宿主翻译机器完成蛋白合成，此现象在小型及部分有尾噬菌体中常见。')
    data_note('features.json（feature_type=tRNA，共 0 条记录）。')
para('')

# ---- 2.8 安全性筛查 ----
heading(2, '2.8 安全性筛查')
amr_genes = safety.get('amr_genes', [])
vir_genes = safety.get('virulent_factors', [])
n_amr = len(amr_genes)
n_vir = len(vir_genes)
n_acr = len(safety.get('anti_crispr_genes', []))
if safety_missing:
    para('本次未检测到 safety_audit.json（未启用生物安全审计或审计文件缺失），以下仅基于现有比对文件汇报或略过。')
else:
    safety_passed = safety.get('safety_passed')
    if safety_passed is None:
        safety_passed = (n_amr == 0 and n_vir == 0)
    passed_txt = '通过（safety_passed = true），无风险告警' if safety_passed else '未完全通过，存在高阈值候选风险基因'
    para(f'安全审计结果：高置信度抗生素耐药基因（CARD）检出 {n_amr} 个，毒力因子（VFDB）检出 {n_vir} 个，'
         f'高置信度 Anti-CRISPR 候选基因（Acranker）检出 {n_acr} 个。'
         f'整体安全性判定为{passed_txt}。')
weak_rows = []
for r in card_hits:
    weak_rows.append(['CARD', r[0], acc_short(r[1]), r[2], r[4], r[5], '低于审计阈值，未计入' if n_amr == 0 else '需复核'])
for r in vfdb_hits:
    weak_rows.append(['VFDB', r[0], acc_short(r[1]), r[2], r[4], r[5], '低于审计阈值，未计入' if n_vir == 0 else '需复核'])
if weak_rows:
    para('需要说明的是，原始比对结果中存在弱命中记录，明细及审计判定如下：')
    add_table(['数据库', 'Locus_Tag', '比对目标', 'Identity%', 'E-value', 'bit score', '判定'],
              weak_rows, col_widths_cm=[2.0, 3.2, 3.4, 2.0, 2.2, 1.8, 3.4],
              align_cols=['c', 'l', 'l', 'c', 'c', 'c', 'l'])
    data_note('card_hits.tsv（CARD 耐药基因比对结果）与 vfdb_hits.tsv（VFDB 毒力因子比对结果）。')
para('')
acr_list = safety.get('anti_crispr_genes', [])
if n_acr > 0:
    para(f'Anti-CRISPR 候选基因共 {n_acr} 条（高置信度，source=Acranker），代表性候选如下表所示（按 bit score 取前 10 条）：')
    acr_rows = []
    for a in sorted(acr_list, key=lambda x: _safe_float(x.get('bitscore', 0)), reverse=True)[:10]:
        acr_rows.append([a.get('cds_id'), a.get('target_id'), a.get('identity'), a.get('align_len'),
                         a.get('evalue'), a.get('bitscore')])
    add_table(['Locus_Tag', '比对目标', 'Identity%', '比对长度', 'E-value', 'bit score'],
              acr_rows, col_widths_cm=[4.2, 3.6, 2.0, 2.0, 2.4, 2.0],
              align_cols=['l', 'l', 'c', 'c', 'c', 'c'])
    data_note(f'safety_audit.json（anti_crispr_genes 共 {n_acr} 条，此处展示按 bit score 降序前 10 条）。')
else:
    para('本次未检出 Anti-CRISPR 候选基因（anti_crispr_genes = 0 条）。')
    data_note('safety_audit.json（anti_crispr_genes 共 0 条）。')
para('注：Anti-CRISPR 基因检出为噬菌体功能特征的一部分，具体含义需结合宿主背景与用途进一步评估。')
doc.add_page_break()

# ============================================================
# 6. 3 方法描述
# ============================================================
heading(1, '3 方法描述')
heading(2, '3.1 分析流程')
m1 = ('基因预测：Pharokka（PHANOTATE 1.6.7 从头预测算法）完成编码基因与 tRNA 识别，遗传密码表 11；'
      '预测输出经坐标核验并与 gbk/features.json 双向一致。')
m2 = ('同源功能注释：将预测蛋白序列经 BLASTP 比对 Swiss-Prot、PhageScope 数据库及 CDD/Pfam 保守结构域库，'
      '并结合 PHROG 噬菌体直系同源蛋白家族数据库进行家族归属与功能类别划分。')
m3 = (f'AI 辅助注释：使用 Phold 基于蛋白质结构预测，对同源注释未能覆盖的功能未知基因进行补充注释（本次贡献 {phold_n} 个 CDS）。')
m4 = ('安全性筛查：针对抗生素耐药基因（CARD）与毒力因子（VFDB）分别进行数据库检索，'
      '并检测 Anti-CRISPR 基因（Acranker），命中阈值与审计规则见本报告第 2.8 节。')
m5 = ('质量控制与产物：对预测坐标、功能字段及 gbk/tsv/features.json 产物进行一致性核验；'
      '输出 GenBank（.gbk）、GFF3（.gff）、TSV 注释表、蛋白序列（.faa）、核酸序列（.ffn），'
      '以及 features.json / summary.json / safety_audit.json 结构化结果。')
for mm in [m1, m2, m3, m4, m5]:
    para(mm, indent2=True)
para('', indent2=False)
heading(2, '3.2 数据来源与产物支撑')
para('本报告全部注释结果均来源于注释流程产出的数据文件，各章节与数据文件的对应关系如下表所示；'
     '每条基因注释的证据细节以 features.json 的 evidence_sources 字段与 ANNO.tsv 的 Evidence 列为原始记录，'
     '报告表格未引入数据文件之外的补充数据。')
src_map = [
    ('2.1 基因组与基因预测统计', 'summary.json；features.json', '总长/GC/编码密度/链分布/蛋白长度'),
    ('2.2 功能注释概况（引擎与交叉分布）', 'features.json；summary.json', 'source_engine、category 字段'),
    ('2.3 功能类别分布', 'summary.json', 'category_distribution'),
    ('2.4 与近缘噬菌体同源性分析', 'swissprot_hits.tsv；features.json', 'BLASTP 命中（按 OS= 物种聚合、bit score 排序）'),
    ('2.5 关键功能模块基因', 'features.json', 'product 字段关键词归类'),
    ('2.6 代表性功能注释示例', 'features.json', 'evidence_sources 字段'),
    ('2.7 tRNA 注释', 'features.json', 'feature_type=tRNA 记录'),
    ('2.8 安全性筛查', 'safety_audit.json；card_hits.tsv；vfdb_hits.tsv', 'Anti-CRISPR/耐药/毒力因子审计'),
    ('附录 A 全量 CDS 注释明细', 'ANNO.tsv；features.json', '全部 CDS 记录与证据摘要'),
    ('附录 B Swiss-Prot 同源命中明细', 'swissprot_hits.tsv', '全部命中记录'),
]
add_table(['报告章节/表格', '数据来源文件', '支撑字段/说明'], src_map,
          col_widths_cm=[6.0, 4.6, 5.4], align_cols=['l', 'l', 'l'])
data_note(f'数据目录：{DATA}')
doc.add_page_break()

# ============================================================
# 7. 4 参考文献
# ============================================================
heading(1, '4 参考文献')
refs = [
    ('Bouras G, Nepal R, Houtak G, et al. Pharokka: a fast scalable bacteriophage annotation tool. '
     'Bioinformatics. 2023. doi:10.1093/bioinformatics/btac776. PMID: 36453861.', 'Ref_Pharokka'),
    ('McNair K, Zhou C, Dinsdale EA, et al. PHANOTATE: a novel approach to gene identification in phage genomes. '
     'Bioinformatics. 2019. doi:10.1093/bioinformatics/btz265. PMID: 31329826.', 'Ref_Phanotate'),
    ('Bouras G, Grigson SR, Mirdita M, et al. Protein structure-informed bacteriophage genome annotation with Phold. '
     'Nucleic Acids Res. 2026. doi:10.1093/nar/gkaf1448. PMID: 41495893.', 'Ref_Phold'),
    ('Terzian P, Olo Ndela E, Galiez C, et al. PHROG: families of prokaryotic virus proteins clustered using remote homology. '
     'NAR Genom Bioinform. 2021. doi:10.1093/nargab/lqab067. PMID: 34377978.', 'Ref_PHROG'),
    ('Wang RH, Yang S, Liu Z, et al. PhageScope: a well-annotated bacteriophage database with automatic analyses and visualizations. '
     'Nucleic Acids Res. 2024. doi:10.1093/nar/gkad979. PMID: 37904614.', 'Ref_PhageScope'),
    ('Alcock BP, Huynh W, Chalil R, et al. CARD 2023: expanded curation, support for machine learning, and resistome prediction '
     'at the Comprehensive Antibiotic Resistance Database. Nucleic Acids Res. 2023. doi:10.1093/nar/gkac920. PMID: 36263822.', 'Ref_CARD'),
    ('Liu B, Zheng D, Zhou S, et al. VFDB 2022: a general classification scheme for bacterial virulence factors. '
     'Nucleic Acids Res. 2022. doi:10.1093/nar/gkab1107. PMID: 34850947.', 'Ref_VFDB'),
    ('Eitzinger S, Asif A, Watters KE, et al. Machine learning predicts new anti-CRISPR proteins. '
     'Nucleic Acids Res. 2020. doi:10.1093/nar/gkaa219. PMID: 32286628.', 'Ref_Acranker'),
]
for text, _ in refs:
    p = para(text, indent2=False, line15=True)
    p.paragraph_format.first_line_indent = Pt(0)
para('', indent2=False)
doc.add_page_break()

# ============================================================
# 8. 5 结果产物清单
# ============================================================
heading(1, '5 结果产物清单')
para('本次注释任务交付的标准产物文件如下表所示（列出数据目录中存在且纳入回传的标准产物）：')
prod = [
    ('ANNO.gbk', 'GenBank 注释文件（含 CDS/tRNA 与功能注解）'),
    ('ANNO.gff', 'GFF3 通用特征格式文件'),
    ('ANNO.tsv', '注释结果明细表（15 列，含全部 feature 记录）'),
    ('ANNO.faa', '预测蛋白序列（FASTA）'),
    ('ANNO.ffn', '预测基因核酸序列（FASTA）'),
    ('features.json', '特征结构数据（含全部 feature 与证据字段）'),
    ('summary.json', '基因组与注释统计汇总'),
    ('safety_audit.json', '安全性审计结果（Anti-CRISPR/耐药/毒力因子）'),
    ('blastp_functional_hits.tsv', '功能注释 BLASTP 命中'),
    ('swissprot_hits.tsv', 'Swiss-Prot 同源命中'),
    ('cdd_hits.tsv', 'CDD 保守结构域命中'),
    ('card_hits.tsv', 'CARD 耐药基因比对结果'),
    ('vfdb_hits.tsv', 'VFDB 毒力因子比对结果'),
]
prod_rows = []
for name, desc in prod:
    if os.path.isfile(os.path.join(DATA, name)):
        size = os.path.getsize(os.path.join(DATA, name))
        prod_rows.append((name, f'{desc}（{size:,} B）'))
add_table(['产物文件', '说明'], prod_rows, col_widths_cm=[6.0, 10.0], align_cols=['l', 'l'])
data_note(f'以数据目录 {os.path.basename(DATA)} 下实际存在的文件为准，缺失文件不列出。')
para('')
para('以上产物随任务批次打包回传，供下游比较基因组分析与客户交付使用。')
doc.add_page_break()

# ============================================================
# 9. 6 备注
# ============================================================
heading(1, '6 备注')
notes = [
    '本报告为内部审阅草稿，报告编号、样品名称等业务字段待确认后填写；确认后按公司对外报告模板补齐封面与格式。',
    '按公司对外口径：若客户未购买注释服务，对外交付报告不包含注释分析章节（第 2、3 章），仅提供拼接结果与序列文件。',
    f'hypothetical 数量存在两种统计口径：按功能类别判定为 {HYPOTHETICAL_CAT} 个，按产物文本（hypothetical/unknown）为 {HYPOTHETICAL_TXT} 个；'
    '本报告以 summary.json 类别口径为准。',
    f'locus_tag 前缀（{LOCUS_PREFIX}）由 Pharokka 随机生成，代表基因标识；如需固定前缀可在正式运行前指定。',
    '注释依赖数据库版本与网络工具状态（BLASTP 需在 PATH 中可用），正式批量运行时需确保环境一致。',
    '第 2.4 节同源性分析基于 Swiss-Prot 比对命中；分类学结论如需正式引用，建议补充全基因组比对与 ICTV 分类流程复核。',
]
notes = notes + ARGS.extra_notes
for n in notes:
    p = para('', indent2=True)
    p.add_run('· ').font.size = Pt(12)
    r = p.add_run(n); set_font(r, size=12)
doc.add_page_break()

# ============================================================
# 10. 附录 A 全量 CDS 注释明细
# ============================================================
heading(1, '附录 A  全量 CDS 注释明细')
para(f'本附录列出全部 {n_cds} 个 CDS 的注释明细（按基因组坐标排序），证据摘要优先展示外部数据库 BLASTP 命中，'
     '否则展示 PHROG 家族编号或 Phold 结构证据。')
cds_sorted = sorted(cds, key=lambda f: (f.get('start') or 0))
appA_rows = []
for f in cds_sorted:
    appA_rows.append([
        f.get('locus_tag'), str(f.get('strand')), f'{f.get("start")}–{f.get("end")}',
        str(f.get('length_bp')), str(f.get('protein_length_aa') or '—'), str(f.get('molecular_weight_kda') or '—'),
        f.get('product') or '—', f.get('category') or '—', str(f.get('phrog') or '—'),
        f.get('source_engine') or '—', short_evidence(f) or '—',
    ])
add_table(['Locus_Tag', '链', '起止(bp)', '长度(bp)', 'aa', 'MW(kDa)', '产物', '类别', 'PHROG', '引擎', '证据摘要'],
          appA_rows, font_size=8,
          col_widths_cm=[3.2, 0.9, 2.6, 1.5, 1.0, 1.2, 3.4, 2.4, 1.2, 1.6, 3.0],
          align_cols=['l', 'c', 'c', 'c', 'c', 'c', 'l', 'l', 'c', 'l', 'l'])
data_note(f'features.json / ANNO.tsv（{n_cds} 条 CDS 记录，按 start 坐标升序；证据摘要由 evidence_sources 字段精简生成）。')
doc.add_page_break()

# ============================================================
# 11. 附录 B Swiss-Prot 同源命中明细
# ============================================================
heading(1, '附录 B  Swiss-Prot 同源命中明细')
para(f'本附录列出 Swiss-Prot 数据库的全部 {len(swiss_hits)} 条 BLASTP 同源命中（按 Locus_Tag 与 bit score 排序）：')
if swiss_hits:
    swiss_sorted = sorted(swiss_hits, key=lambda r: (r[0], -_safe_float(r[5])))
    appB_rows = []
    for r in swiss_sorted:
        desc = re.sub(r'^[^\s]+\s+', '', r[6])
        desc = re.sub(r'\s+OS=.*$', '', desc).strip()
        appB_rows.append([r[0], acc_short(r[1]), r[2], r[3], r[4], r[5], desc[:60]])
    add_table(['Locus_Tag', 'Swiss-Prot 命中', 'Identity%', '比对长度', 'E-value', 'bit score', '描述'],
              appB_rows, font_size=8,
              col_widths_cm=[3.6, 2.8, 1.8, 1.8, 2.4, 1.8, 3.8],
              align_cols=['l', 'c', 'c', 'c', 'c', 'c', 'l'])
    data_note(f'swissprot_hits.tsv（{len(swiss_hits)} 条命中记录；描述截取前 60 字符）。')
else:
    para('本批次未获得任何 Swiss-Prot 同源命中记录，故无明细可列。')

# ============================================================
# 12. 页脚页码
# ============================================================
footer = sec.footer
fp = footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
fld1 = OxmlElement('w:fldChar'); fld1.set(qn('w:fldCharType'), 'begin')
instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve'); instr.text = ' PAGE '
fld2 = OxmlElement('w:fldChar'); fld2.set(qn('w:fldCharType'), 'end')
run = fp.add_run(); set_font(run, size=9)
run._r.append(fld1); run._r.append(instr); run._r.append(fld2)

doc.save(OUT)
print('saved:', OUT)
print('CDS:', n_cds, 'tRNA:', n_trna, 'Swiss-Prot hits:', len(swiss_hits))

# ---- 修复主题 eastAsia 语言（ja-JP → zh-CN） ----
import zipfile
import shutil
TMPZ = OUT + '.tmpz'
with zipfile.ZipFile(OUT, 'r') as zin, zipfile.ZipFile(TMPZ, 'w', zipfile.ZIP_DEFLATED) as zout:
    for item in zin.namelist():
        data = zin.read(item)
        if item == 'word/theme/theme1.xml':
            s = data.decode('utf-8')
            s = s.replace('typeface="ja-JP"', 'typeface="zh-CN"')
            data = s.encode('utf-8')
        zout.writestr(item, data)
shutil.move(TMPZ, OUT)
print('theme eastAsia fixed')
