/**
 * 预置对照表数据
 *
 * 职责：仅提供静态初始数据，不含任何逻辑。
 * 编码策略：系统预置词条使用顺序分配的 3 字母编码（AAA, AAB, ...），
 *          用户自定义词条由 useCodeLookup 负责分配。
 */
import type { CodeLookupEntry, SourceEntry } from '../types/codeSystem'

/* ========== 工具：批量生成词条 ========== */

function genLevel2(
  categoryCode: string,
  code: string,
  name: string,
  latinName?: string,
  description?: string
): CodeLookupEntry {
  return {
    code,
    level: 2,
    parentPath: categoryCode,
    fullPath: `${categoryCode}${code}`,
    name,
    latinName,
    description,
    isBuiltin: true,
    enabled: true,
  }
}

function genLevel3(
  categoryCode: string,
  genusCode: string,
  code: string,
  name: string,
  latinName?: string,
  description?: string
): CodeLookupEntry {
  const parentPath = `${categoryCode}${genusCode}`
  return {
    code,
    level: 3,
    parentPath,
    fullPath: `${parentPath}${code}`,
    name,
    latinName,
    description,
    isBuiltin: true,
    enabled: true,
  }
}

/* ========== 第一层：大类（由 CATEGORY_MAP 常量提供，不重复定义） ========== */

/* ========== 第二层 + 第三层：属 & 种 ========== */

/** 细菌 (A=1) 的属和种 */
const BACTERIA_ENTRIES: CodeLookupEntry[] = [
  // ── 属 ──
  genLevel2('1', 'AAA', '埃希氏菌属', 'Escherichia'),
  genLevel2('1', 'AAB', '葡萄球菌属', 'Staphylococcus'),
  genLevel2('1', 'AAC', '假单胞菌属', 'Pseudomonas'),
  genLevel2('1', 'AAD', '克雷伯菌属', 'Klebsiella'),
  genLevel2('1', 'AAE', '不动杆菌属', 'Acinetobacter'),
  genLevel2('1', 'AAF', '芽孢杆菌属', 'Bacillus'),
  genLevel2('1', 'AAG', '沙门氏菌属', 'Salmonella'),
  genLevel2('1', 'AAH', '分枝杆菌属', 'Mycobacterium'),
  genLevel2('1', 'AAI', '肠球菌属', 'Enterococcus'),
  genLevel2('1', 'AAJ', '链球菌属', 'Streptococcus'),
  genLevel2('1', 'AAK', '弧菌属', 'Vibrio'),
  genLevel2('1', 'AAL', '李斯特菌属', 'Listeria'),
  genLevel2('1', 'AAM', '军团菌属', 'Legionella'),
  genLevel2('1', 'AAN', '螺杆菌属', 'Helicobacter'),
  genLevel2('1', 'AAO', '梭菌属', 'Clostridium'),
  genLevel2('1', 'AAP', '奈瑟菌属', 'Neisseria'),
  genLevel2('1', 'AAQ', '布鲁氏菌属', 'Brucella'),
  genLevel2('1', 'AAR', '棒状杆菌属', 'Corynebacterium'),
  genLevel2('1', 'AAS', '伯克霍尔德菌属', 'Burkholderia'),
  genLevel2('1', 'AAT', '沙雷菌属', 'Serratia'),

  // ── 种：埃希氏菌属 (1AAA) ──
  genLevel3('1', 'AAA', 'AAA', '大肠杆菌', 'Escherichia coli'),
  genLevel3('1', 'AAA', 'AAB', '弗格森埃希氏菌', 'Escherichia fergusonii'),
  genLevel3('1', 'AAA', 'AAC', '赫尔曼埃希氏菌', 'Escherichia hermannii'),
  genLevel3('1', 'AAA', 'AAD', '阿尔伯特埃希氏菌', 'Escherichia albertii'),

  // ── 种：葡萄球菌属 (1AAB) ──
  genLevel3('1', 'AAB', 'AAA', '金黄色葡萄球菌', 'Staphylococcus aureus'),
  genLevel3('1', 'AAB', 'AAB', '表皮葡萄球菌', 'Staphylococcus epidermidis'),
  genLevel3('1', 'AAB', 'AAC', '腐生葡萄球菌', 'Staphylococcus saprophyticus'),

  // ── 种：假单胞菌属 (1AAC) ──
  genLevel3('1', 'AAC', 'AAA', '铜绿假单胞菌', 'Pseudomonas aeruginosa'),
  genLevel3('1', 'AAC', 'AAB', '荧光假单胞菌', 'Pseudomonas fluorescens'),

  // ── 种：克雷伯菌属 (1AAD) ──
  genLevel3('1', 'AAD', 'AAA', '肺炎克雷伯菌', 'Klebsiella pneumoniae'),
  genLevel3('1', 'AAD', 'AAB', '产酸克雷伯菌', 'Klebsiella oxytoca'),

  // ── 种：不动杆菌属 (1AAE) ──
  genLevel3('1', 'AAE', 'AAA', '鲍曼不动杆菌', 'Acinetobacter baumannii'),

  // ── 种：芽孢杆菌属 (1AAF) ──
  genLevel3('1', 'AAF', 'AAA', '枯草芽孢杆菌', 'Bacillus subtilis'),
  genLevel3('1', 'AAF', 'AAB', '蜡状芽孢杆菌', 'Bacillus cereus'),

  // ── 种：沙门氏菌属 (1AAG) ──
  genLevel3('1', 'AAG', 'AAA', '伤寒沙门氏菌', 'Salmonella typhi'),
  genLevel3('1', 'AAG', 'AAB', '鼠伤寒沙门氏菌', 'Salmonella typhimurium'),

  // ── 种：分枝杆菌属 (1AAH) ──
  genLevel3('1', 'AAH', 'AAA', '结核分枝杆菌', 'Mycobacterium tuberculosis'),
  genLevel3('1', 'AAH', 'AAB', '牛分枝杆菌', 'Mycobacterium bovis'),

  // ── 种：肠球菌属 (1AAI) ──
  genLevel3('1', 'AAI', 'AAA', '粪肠球菌', 'Enterococcus faecalis'),
  genLevel3('1', 'AAI', 'AAB', '屎肠球菌', 'Enterococcus faecium'),

  // ── 种：链球菌属 (1AAJ) ──
  genLevel3('1', 'AAJ', 'AAA', '肺炎链球菌', 'Streptococcus pneumoniae'),
  genLevel3('1', 'AAJ', 'AAB', '化脓链球菌', 'Streptococcus pyogenes'),
  genLevel3('1', 'AAJ', 'AAC', '变异链球菌', 'Streptococcus mutans'),

  // ── 种：弧菌属 (1AAK) ──
  genLevel3('1', 'AAK', 'AAA', '霍乱弧菌', 'Vibrio cholerae'),
  genLevel3('1', 'AAK', 'AAB', '副溶血弧菌', 'Vibrio parahaemolyticus'),

  // ── 种：李斯特菌属 (1AAL) ──
  genLevel3('1', 'AAL', 'AAA', '单核细胞增生李斯特菌', 'Listeria monocytogenes'),

  // ── 种：军团菌属 (1AAM) ──
  genLevel3('1', 'AAM', 'AAA', '嗜肺军团菌', 'Legionella pneumophila'),

  // ── 种：螺杆菌属 (1AAN) ──
  genLevel3('1', 'AAN', 'AAA', '幽门螺杆菌', 'Helicobacter pylori'),

  // ── 种：梭菌属 (1AAO) ──
  genLevel3('1', 'AAO', 'AAA', '艰难梭菌', 'Clostridioides difficile'),
  genLevel3('1', 'AAO', 'AAB', '肉毒梭菌', 'Clostridium botulinum'),
  genLevel3('1', 'AAO', 'AAC', '产气荚膜梭菌', 'Clostridium perfringens'),

  // ── 种：奈瑟菌属 (1AAP) ──
  genLevel3('1', 'AAP', 'AAA', '脑膜炎奈瑟菌', 'Neisseria meningitidis'),
  genLevel3('1', 'AAP', 'AAB', '淋病奈瑟菌', 'Neisseria gonorrhoeae'),

  // ── 种：布鲁氏菌属 (1AAQ) ──
  genLevel3('1', 'AAQ', 'AAA', '马耳他布鲁氏菌', 'Brucella melitensis'),
  genLevel3('1', 'AAQ', 'AAB', '流产布鲁氏菌', 'Brucella abortus'),

  // ── 种：棒状杆菌属 (1AAR) ──
  genLevel3('1', 'AAR', 'AAA', '白喉棒状杆菌', 'Corynebacterium diphtheriae'),

  // ── 种：伯克霍尔德菌属 (1AAS) ──
  genLevel3('1', 'AAS', 'AAA', '洋葱伯克霍尔德菌', 'Burkholderia cepacia'),

  // ── 种：沙雷菌属 (1AAT) ──
  genLevel3('1', 'AAT', 'AAA', '粘质沙雷菌', 'Serratia marcescens'),
]

/** 病毒 (A=2) */
const VIRUS_ENTRIES: CodeLookupEntry[] = [
  genLevel2('2', 'AAA', '正黏病毒科', 'Orthomyxoviridae', '流感病毒'),
  genLevel2('2', 'AAB', '冠状病毒科', 'Coronaviridae'),
  genLevel2('2', 'AAC', '嗜肝DNA病毒科', 'Hepadnaviridae', '乙肝'),
  genLevel2('2', 'AAD', '黄病毒科', 'Flaviviridae', '丙肝/登革/寨卡'),
  genLevel2('2', 'AAE', '逆转录病毒科', 'Retroviridae', 'HIV'),
  genLevel2('2', 'AAF', '腺病毒科', 'Adenoviridae'),
  genLevel2('2', 'AAG', '副黏病毒科', 'Paramyxoviridae', 'RSV/新城疫'),
  genLevel2('2', 'AAH', '疱疹病毒科', 'Herpesviridae'),
  genLevel2('2', 'AAI', '痘病毒科', 'Poxviridae'),
  genLevel2('2', 'AAJ', '小RNA病毒科', 'Picornaviridae'),

  genLevel3('2', 'AAA', 'AAA', '甲型流感病毒', 'Influenza A'),
  genLevel3('2', 'AAA', 'AAB', '乙型流感病毒', 'Influenza B'),
  genLevel3('2', 'AAB', 'AAA', 'SARS-CoV-2', 'SARS-CoV-2'),
  genLevel3('2', 'AAB', 'AAB', 'MERS-CoV', 'MERS-CoV'),
  genLevel3('2', 'AAB', 'AAC', 'HCoV-229E', 'HCoV-229E'),
  genLevel3('2', 'AAC', 'AAA', '乙型肝炎病毒', 'Hepatitis B virus'),
  genLevel3('2', 'AAD', 'AAA', '丙型肝炎病毒', 'Hepatitis C virus'),
  genLevel3('2', 'AAD', 'AAB', '登革病毒', 'Dengue virus'),
  genLevel3('2', 'AAD', 'AAC', '寨卡病毒', 'Zika virus'),
  genLevel3('2', 'AAE', 'AAA', 'HIV-1', 'HIV-1'),
  genLevel3('2', 'AAE', 'AAB', 'HIV-2', 'HIV-2'),
  genLevel3('2', 'AAF', 'AAA', '人腺病毒', 'Human adenovirus'),
  genLevel3('2', 'AAG', 'AAA', '呼吸道合胞病毒', 'RSV'),
  genLevel3('2', 'AAG', 'AAB', '新城疫病毒', 'Newcastle disease virus'),
  genLevel3('2', 'AAH', 'AAA', 'HSV-1', 'Herpes simplex virus 1'),
  genLevel3('2', 'AAH', 'AAB', 'HSV-2', 'Herpes simplex virus 2'),
  genLevel3('2', 'AAH', 'AAC', 'EBV', 'Epstein-Barr virus'),
  genLevel3('2', 'AAH', 'AAD', 'CMV', 'Cytomegalovirus'),
]

/** 噬菌体 (A=3) */
const PHAGE_ENTRIES: CodeLookupEntry[] = [
  genLevel2('3', 'AAA', 'T系列噬菌体', 'T-series'),
  genLevel2('3', 'AAB', 'λ系列噬菌体', 'Lambda series'),
  genLevel2('3', 'AAC', 'M系列噬菌体', 'M-series'),
  genLevel2('3', 'AAD', 'P系列噬菌体', 'P-series'),
  genLevel2('3', 'AAE', 'Φ系列噬菌体', 'Phi series'),

  genLevel3('3', 'AAA', 'AAA', 'T4噬菌体', 'T4 phage'),
  genLevel3('3', 'AAA', 'AAB', 'T7噬菌体', 'T7 phage'),
  genLevel3('3', 'AAA', 'AAC', 'T2噬菌体', 'T2 phage'),
  genLevel3('3', 'AAB', 'AAA', 'λ野生型', 'Lambda wild-type'),
  genLevel3('3', 'AAB', 'AAB', 'λgt10', 'Lambda gt10'),
  genLevel3('3', 'AAB', 'AAC', 'λgt11', 'Lambda gt11'),
  genLevel3('3', 'AAC', 'AAA', 'M13噬菌体', 'M13 phage'),
  genLevel3('3', 'AAC', 'AAB', 'Mu噬菌体', 'Mu phage'),
  genLevel3('3', 'AAD', 'AAA', 'P1噬菌体', 'P1 phage'),
  genLevel3('3', 'AAD', 'AAB', 'P22噬菌体', 'P22 phage'),
  genLevel3('3', 'AAE', 'AAA', 'ΦX174噬菌体', 'PhiX174'),
]

/** 真菌 (A=4) */
const FUNGI_ENTRIES: CodeLookupEntry[] = [
  genLevel2('4', 'AAA', '酵母属', 'Saccharomyces'),
  genLevel2('4', 'AAB', '念珠菌属', 'Candida'),
  genLevel2('4', 'AAC', '曲霉属', 'Aspergillus'),
  genLevel2('4', 'AAD', '青霉属', 'Penicillium'),
  genLevel2('4', 'AAE', '隐球菌属', 'Cryptococcus'),
  genLevel2('4', 'AAF', '毛霉属', 'Mucor'),
  genLevel2('4', 'AAG', '毛癣菌属', 'Trichophyton'),

  genLevel3('4', 'AAA', 'AAA', '酿酒酵母', 'Saccharomyces cerevisiae'),
  genLevel3('4', 'AAA', 'AAB', '毕赤酵母', 'Pichia pastoris'),
  genLevel3('4', 'AAB', 'AAA', '白色念珠菌', 'Candida albicans'),
  genLevel3('4', 'AAB', 'AAB', '光滑念珠菌', 'Candida glabrata'),
  genLevel3('4', 'AAC', 'AAA', '黑曲霉', 'Aspergillus niger'),
  genLevel3('4', 'AAC', 'AAB', '烟曲霉', 'Aspergillus fumigatus'),
  genLevel3('4', 'AAC', 'AAC', '黄曲霉', 'Aspergillus flavus'),
  genLevel3('4', 'AAD', 'AAA', '产黄青霉菌', 'Penicillium chrysogenum'),
  genLevel3('4', 'AAE', 'AAA', '新型隐球菌', 'Cryptococcus neoformans'),
]

/** 质粒/载体 (A=5) */
const PLASMID_ENTRIES: CodeLookupEntry[] = [
  genLevel2('5', 'AAA', 'pET系列', 'pET series', '原核表达载体'),
  genLevel2('5', 'AAB', 'pUC系列', 'pUC series', '克隆载体'),
  genLevel2('5', 'AAC', 'pBR系列', 'pBR series', '经典克隆载体'),
  genLevel2('5', 'AAD', 'pGEX系列', 'pGEX series', 'GST融合表达'),
  genLevel2('5', 'AAE', 'pcDNA系列', 'pcDNA series', '哺乳动物表达'),
  genLevel2('5', 'AAF', '慢病毒载体', 'Lentiviral vector'),
  genLevel2('5', 'AAG', '腺病毒载体', 'Adenoviral vector'),
  genLevel2('5', 'AAH', 'AAV载体', 'AAV vector'),
  genLevel2('5', 'AAI', 'CRISPR载体', 'CRISPR vector'),
  genLevel2('5', 'AAJ', '穿梭载体', 'Shuttle vector'),

  genLevel3('5', 'AAA', 'AAA', 'pET-28a(+)', 'pET-28a(+)', 'His-tag, Kan抗性'),
  genLevel3('5', 'AAA', 'AAB', 'pET-21b(+)', 'pET-21b(+)', 'C端His, Amp抗性'),
  genLevel3('5', 'AAA', 'AAC', 'pET-32a(+)', 'pET-32a(+)', 'Trx融合, Amp抗性'),
  genLevel3('5', 'AAA', 'AAD', 'pET-SUMO', 'pET-SUMO', 'SUMO融合表达'),
  genLevel3('5', 'AAB', 'AAA', 'pUC18', 'pUC18'),
  genLevel3('5', 'AAB', 'AAB', 'pUC19', 'pUC19'),
  genLevel3('5', 'AAC', 'AAA', 'pBR322', 'pBR322'),
  genLevel3('5', 'AAD', 'AAA', 'pGEX-4T-1', 'pGEX-4T-1'),
  genLevel3('5', 'AAD', 'AAB', 'pGEX-6P-1', 'pGEX-6P-1'),
  genLevel3('5', 'AAE', 'AAA', 'pcDNA3.1', 'pcDNA3.1'),
  genLevel3('5', 'AAE', 'AAB', 'pcDNA5', 'pcDNA5'),
  genLevel3('5', 'AAI', 'AAA', 'pX330', 'pX330', 'SpCas9+sgRNA'),
  genLevel3('5', 'AAI', 'AAB', 'pX459', 'pX459', 'SpCas9+sgRNA+Puro'),
  genLevel3('5', 'AAI', 'AAC', 'lentiCRISPR v2', 'lentiCRISPR v2'),
]

/** 细胞 (A=6) */
const CELL_ENTRIES: CodeLookupEntry[] = [
  genLevel2('6', 'AAA', '人源细胞', 'Human'),
  genLevel2('6', 'AAB', '鼠源细胞', 'Mouse/Rat'),
  genLevel2('6', 'AAC', '猴源细胞', 'Monkey'),
  genLevel2('6', 'AAD', '仓鼠源细胞', 'Hamster'),
  genLevel2('6', 'AAE', '犬源细胞', 'Canine'),
  genLevel2('6', 'AAF', '昆虫细胞', 'Insect'),
  genLevel2('6', 'AAG', '原代细胞', 'Primary cell'),
  genLevel2('6', 'AAH', '感受态细胞', 'Competent cell'),

  genLevel3('6', 'AAA', 'AAA', 'HEK293', 'HEK293', '人胚肾细胞'),
  genLevel3('6', 'AAA', 'AAB', 'HEK293T', 'HEK293T', 'SV40 T抗原'),
  genLevel3('6', 'AAA', 'AAC', 'HeLa', 'HeLa', '宫颈癌细胞系'),
  genLevel3('6', 'AAA', 'AAD', 'THP-1', 'THP-1', '人单核细胞'),
  genLevel3('6', 'AAA', 'AAE', 'Jurkat', 'Jurkat', 'T淋巴细胞'),
  genLevel3('6', 'AAA', 'AAF', 'A549', 'A549', '肺腺癌'),
  genLevel3('6', 'AAA', 'AAG', 'MCF-7', 'MCF-7', '乳腺癌'),
  genLevel3('6', 'AAA', 'AAH', 'U937', 'U937', '组织细胞淋巴瘤'),
  genLevel3('6', 'AAB', 'AAA', 'NIH3T3', 'NIH3T3', '小鼠胚胎成纤维'),
  genLevel3('6', 'AAB', 'AAB', 'RAW264.7', 'RAW264.7', '小鼠巨噬细胞'),
  genLevel3('6', 'AAC', 'AAA', 'Vero', 'Vero', '非洲绿猴肾'),
  genLevel3('6', 'AAC', 'AAB', 'COS-7', 'COS-7'),
  genLevel3('6', 'AAD', 'AAA', 'CHO', 'CHO', '中华仓鼠卵巢'),
  genLevel3('6', 'AAD', 'AAB', 'BHK-21', 'BHK-21'),
  genLevel3('6', 'AAE', 'AAA', 'MDCK', 'MDCK', '犬肾细胞'),
  genLevel3('6', 'AAF', 'AAA', 'Sf9', 'Sf9'),
  genLevel3('6', 'AAF', 'AAB', 'Sf21', 'Sf21'),
  genLevel3('6', 'AAF', 'AAC', 'High Five', 'High Five'),
]

/** 核酸 (A=7) */
const NUCLEIC_ACID_ENTRIES: CodeLookupEntry[] = [
  genLevel2('7', 'AAA', '基因组DNA', 'Genomic DNA'),
  genLevel2('7', 'AAB', 'cDNA', 'cDNA'),
  genLevel2('7', 'AAC', '总RNA', 'Total RNA'),
  genLevel2('7', 'AAD', 'mRNA', 'mRNA'),
  genLevel2('7', 'AAE', '引物/寡核苷酸', 'Primers/Oligo'),
  genLevel2('7', 'AAF', '文库', 'Library'),
  genLevel2('7', 'AAG', 'siRNA/shRNA', 'siRNA/shRNA'),
]

/** 蛋白/抗体 (A=8) */
const PROTEIN_ENTRIES: CodeLookupEntry[] = [
  genLevel2('8', 'AAA', '限制性内切酶', 'Restriction enzyme'),
  genLevel2('8', 'AAB', '聚合酶', 'Polymerase'),
  genLevel2('8', 'AAC', '连接酶', 'Ligase'),
  genLevel2('8', 'AAD', '单克隆抗体', 'Monoclonal Ab'),
  genLevel2('8', 'AAE', '多克隆抗体', 'Polyclonal Ab'),
  genLevel2('8', 'AAF', '重组蛋白', 'Recombinant protein'),
  genLevel2('8', 'AAG', '细胞因子', 'Cytokine'),
]

/** 样本/其他 (A=9) */
const SAMPLE_ENTRIES: CodeLookupEntry[] = [
  genLevel2('9', 'AAA', '血液/血清', 'Blood/Serum'),
  genLevel2('9', 'AAB', '分泌物/排泄物', 'Excreta'),
  genLevel2('9', 'AAC', '组织', 'Tissue'),
  genLevel2('9', 'AAD', '环境样本', 'Environmental'),
  genLevel2('9', 'AAE', '食品样本', 'Food'),
  genLevel2('9', 'AAF', '试剂/培养基', 'Reagent/Media'),
]

/* ========== 汇总导出 ========== */

/** 全部预置对照表词条 */
export const BUILTIN_LOOKUP_ENTRIES: CodeLookupEntry[] = [
  ...BACTERIA_ENTRIES,
  ...VIRUS_ENTRIES,
  ...PHAGE_ENTRIES,
  ...FUNGI_ENTRIES,
  ...PLASMID_ENTRIES,
  ...CELL_ENTRIES,
  ...NUCLEIC_ACID_ENTRIES,
  ...PROTEIN_ENTRIES,
  ...SAMPLE_ENTRIES,
]

/** 预置来源词条（留空，完全由用户定义） */
export const BUILTIN_SOURCE_ENTRIES: SourceEntry[] = []

/** 默认编码系统配置 */
export const DEFAULT_CODE_CONFIG: {
  assignMode: 'random' | 'sequential'
  serialDigits: number
  version: string
} = {
  assignMode: 'sequential',
  serialDigits: 4,
  version: '1.0.0',
}
