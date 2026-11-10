// -*- coding: utf-8 -*-
/**
 * 序列可视化几何计算与高级生物学配色渲染工具
 */

export interface ColorScheme {
  primary: string;
  hover: string;
  bg: string;
}

// 国际标准噬菌体与全基因组功能分类配色系统 (SnapGene / Proksee / CGView / PHROG 风格)
export const FUNCTIONAL_CATEGORIES: Record<string, { label: string; color: string; hoverColor: string }> = {
  "Head & Packaging": {
    label: "头部与衣壳包装 (Head & Packaging)",
    color: "#0284c7", // 经典海蓝
    hoverColor: "#0369a1"
  },
  "Tail & Host Interaction": {
    label: "尾部与尾丝吸附 (Tail & Host)",
    color: "#06b6d4", // 鲜亮青碧 (独立专属分类与颜色)
    hoverColor: "#0891b2"
  },
  "Replication & Repair": {
    label: "DNA复制与重组修复 (Replication)",
    color: "#f59e0b", // 活力暖橙
    hoverColor: "#d97706"
  },
  "Lysis": {
    label: "宿主裂解系统 (Lysis System)",
    color: "#f43f5e", // 玫瑰赤红
    hoverColor: "#e11d48"
  },
  "Transcription & Regulation": {
    label: "转录调控与开关 (Regulation)",
    color: "#10b981", // 翡翠薄荷绿
    hoverColor: "#059669"
  },
  "Defense & Host Interaction": {
    label: "宿主防御与互作 (Defense / Acr)",
    color: "#8b5cf6", // 优雅紫罗兰
    hoverColor: "#7c3aed"
  },
  "Metabolism & AMG": {
    label: "辅助代谢基因 (Metabolism & AMG)",
    color: "#eab308", // 暖金黄
    hoverColor: "#ca8a04"
  },
  "Integration & Excision": {
    label: "溶原整合与切除 (Integration)",
    color: "#6366f1", // 亮靛紫
    hoverColor: "#4f46e5"
  },
  "Other Functional": {
    label: "其他功能蛋白 (Other)",
    color: "#64748b", // 中性板岩灰
    hoverColor: "#475569"
  },
  "Hypothetical": {
    label: "假定蛋白与未表征 (Hypothetical)",
    color: "#94a3b8", // 冷灰蓝
    hoverColor: "#64748b"
  }
};

// 显式结构化分类标签映射 (仅针对 Pharokka/Phold 的结构化分类字段，避免宽泛的 moron / DNA metabolism 误导)
const EXPLICIT_NOTE_CATEGORY_MAP: Record<string, string> = {
  "head and packaging": "Head & Packaging",
  "tail": "Tail & Host Interaction",
  "connector": "Tail & Host Interaction",
  "lysis": "Lysis",
  "integration and excision": "Integration & Excision",
  "transcription regulation": "Transcription & Regulation"
};

/**
 * 依据产物名称 (Product) 进行生物学功能分类推断 (与后端 AnnotationFuser.infer_category 1:1 对齐)
 */
export function inferCategoryFromText(product?: string, notes?: string): string {
  const p = (product || "").trim().toLowerCase();

  // 0. 假定/未表征蛋白及未知功能结构域(DUF/UPF/PHA/ORF)直接归 Hypothetical
  if (isHypotheticalName(p)) {
    return "Hypothetical";
  }

  // 1. 已知功能 product 优先判定
  if (p) {
    const cat = matchCategoryRules(p);
    if (cat !== "Hypothetical" && cat !== "Other Functional") {
      return cat;
    }
  }

  // 2. product 未命中具体大类时，仅从 notes 中提取明确的 Pharokka/Phold 结构化分类标签
  // 绝不盲目全文匹配 notes (防止 Acranker 弱预测或 "DNA, RNA and nucleotide metabolism" 污染)
  if (notes) {
    const n = notes.toLowerCase();
    const regex = /(?:category|phold\s+structure):\s*([a-z\s,_-]+?)(?:;|$)/gi;
    let m: RegExpExecArray | null;
    while ((m = regex.exec(n)) !== null) {
      const rawTag = (m[1] || "").trim();
      if (rawTag && EXPLICIT_NOTE_CATEGORY_MAP[rawTag]) {
        return EXPLICIT_NOTE_CATEGORY_MAP[rawTag];
      }
    }
  }

  // 3. 兜底: 有已知 product 归 Other Functional，否则为假定蛋白
  return p ? "Other Functional" : "Hypothetical";
}

/**
 * 假定/未表征蛋白判定 (与后端 AnnotationFuser.UNANNOTATED_PATTERNS 保持 1:1 一致)
 */
const HYPOTHETICAL_PATTERNS: RegExp[] = [
  /^(?:conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:hypothetical|hyphothetical)\b/i,
  /^(?:conserved\s+|putative\s+|phage\s+|bacteriophage\s+|predicted\s+)*(?:uncharacterized|uncharacterised)\b/i,
  /\b(?:unknown|unkown|unknwon)\s+function\b/i,
  /^unknown(?:\s+(?:protein|function))?$/i,
  /^(?:putative|predicted|conserved)\s+(?:phage\s+|bacteriophage\s+)?protein$/i,
  /^protein\s+conserved\s+in\s+bacteria$/i,
  /^protein\s+of\s+(?:unknown|unkown|unknwon)\s+function\b/i,
  /\bdomain\s+of\s+(?:unknown|unkown|unknwon)\s+function\b/i,
  /\bfamily\s+of\s+(?:unknown|unkown|unknwon)\s+function\b/i,
  /^(?:putative\s+|conserved\s+)?phage\s+protein(?:\s+gp\d+(?:[./_]\d+)*)?$/i,
  /^bacteriophage\s+[a-z0-9_-]+\s+protein$/i,
  /^prophage\s+[a-z0-9_-]+\s+protein\b/i,
  /^unnamed(?:\s+protein(?:\s+product)?)?$/i,
  /^(?:pfam\s*:\s*)?(?:phage\s+)?(?:protein\s+)?gp\d+(?:[./_\s]\s*(?:gp)?\d+)*(?:\s+(?:domain-containing|family)\s+protein)?$/i,
  /^[a-z]+\d*\s+gp\d+(?:\s+family\s+protein)?$/i,
  /^[a-z]+\d*gp\d+$/i,
  /^orf\s*\d+$/i,
  /\bduf\s*\d+\b/i,
  /\bupf\s*\d+\b/i,
  /^pha\s*\d+(?:\s+domain-containing\s+protein)?$/i,
  /^\d+\.\d+\s+domain-containing\s+protein$/i,
  /^d\d+\s+protein$/i,
  /^protein\s+y[a-z]{2}[a-z0-9]?$/i,
  /^tigrfam\s+phage$/i,
  /^domain,\s*protein$/i,
  /^psort\s+location\b/i,
  /^(?:none|na|unassigned|unsorted)$/i,
];

export function isHypotheticalName(text: string): boolean {
  const t = (text || "").trim().replace(/_/g, " ");
  if (!t) return true;
  return HYPOTHETICAL_PATTERNS.some(re => re.test(t));
}

function matchCategoryRules(text: string): string {
  const t = text.toLowerCase().replace(/_/g, " ").replace(/%3b/g, ";");

  // 特殊修正: recombinase 若不含 DNA 修复核酸酶及同源重组酶关键词，则归入 Integration & Excision
  if (/\brecombinase\b/i.test(t) && !/\b(exonuclease|endonuclease|holliday|rusa|ruvc|recu|uvsx|reca|rad51|homologous)\b/i.test(t)) {
    return "Integration & Excision";
  }

  // 1. 尾部与尾丝吸附 (Tail & Host Interaction)
  if (
    /^(?:baseplate|tail)\b.*\blysozyme\b/i.test(t) ||
    (!/\bhead\s+fiber\b/i.test(t) && /\b(tail|baseplate|base\s*plate|tape\s*measure|tail\s*fiber|tail\s*fibre|tailfiber|tail\s*spike|tailspike|tail\s*tube|tail\s*sheath|tail\s*assembly|tail\s*needle|tail\s*protein|major\s*tail|minor\s*tail|tail\s*terminator|tail\s*completion|head-tail|head\s+to\s+tail|adaptor\s*ad\d+|neck\s*protein|neck1|neck\s*whisker|fibritin|collar|receptor-binding|receptor\s*binding|reticulocyte-binding|adhesin|adsorption|host\s*range|host\s*specificity|tail\s*chaperone|tail\s*assembly\s*chaperone|tail\s*fiber\s*assembly|gp37|gp38|pectate\s*lyase|depolymerase|polysaccharide\s*lyase|endosialidase|sialidase|neuraminidase|hyaluronidase|ig\s*domain|ig-like|sh3\s*beta[- ]barrel|fibronectin\s*type|pkd\s*domain|lectin|adaptator|fimbria|fimbrial)\b/i.test(t))
  ) {
    return "Tail & Host Interaction";
  }

  // 2. 头部与衣壳包装 (Head & Packaging)
  if (
    /^internal\s+virion\s+protein\b/i.test(t) ||
    /\b(capsid|capsomer|coat\s*protein|portal|terminase|terminase\s*large\s*subunit|terminase\s*small\s*subunit|head\s*protein|major\s*head|minor\s*head|head\s*fiber|head\s*completion|scaffold|scaffolding|prohead|head\s*closure|head\s*decoration|head\s*maturation|head\s*morphogenesis|head\s*vertex|head\s*portal|maturation\s*protease|head\s*assembly|major\s*capsid|minor\s*capsid|virion\s*structural|virion\s*morphogenesis|internal\s*virion|structural\s*protein|encapsulin|head-tail\s*connector|mu\s*protein\s*f|hoc-like|pmg[bg]-like)\b/i.test(t)
  ) {
    return "Head & Packaging";
  }

  // 3. 宿主裂解系统 (Lysis)
  if (
    !/\b(deamidase|amidotransferase)\b/i.test(t) &&
    /\b(endolysin|lysin|holin|antiholin|anti-holin|pinholin|spanin|i-spanin|o-spanin|rz-like|rz1|[a-z0-9'-]*muramidase|[a-z0-9'-]*amidase|ami\s*2|ami\s*3|nlpc\s*p60|nlp\s*p60|endopeptidase|carboxypeptidase|peptidoglycan\s*hydrolase|peptidoglycan\s*catabolic|murein\s*hydrolase|cell\s*wall\s*hydrolase|lytic\s*transglycosylase|transglycosylase|chitinase|chitin\s*catabolic|lysozyme|lysis\s*inhibition|lysis\s*inhibitor|riia|riib|spackle|lysis)\b/i.test(t)
  ) {
    return "Lysis";
  }

  // 4. 溶原整合与切除 (Integration & Excision)
  if (/\b(integrase|dna\s*integration|excisionase|excise|transposase|transposase-like|site-specific\s*recombinase|tyrosine\s*recombinase|tyrosine-type\s*recombinase|serine\s*recombinase|prophage\s*integrase|prophage\s*excisionase|recombination\s*directionality\s*factor|rdf|xis|dna\s*invertase|invertase\s*pin|mobile\s*element|intein|ist[ab](?:-like)?)\b/i.test(t)) {
    return "Integration & Excision";
  }

  // 5. 转录调控与开关 (Transcription & Regulation)
  if (/\b(rna\s*polymerase|repressor|anti-?repressor|antirepressor|activator|regulator|regulatory\s*protein|regulatory\s*subunit|response\s*regulator|promoter|transcription|transcriptional|transcrition\s*regulator|cro|c1\s*repressor|ci\s*repressor|cii(?:-like)?|ciii|anti-?termination|anti-?terminator|anti-?sigma|sigma\s*factor|sigma[- ]?[a-z0-9]+|modulator|helix[- ]turn[- ]helix|hth|hth-type|csra(?:-like)?|gntr|marr|lysr(?:-like|-type)?|arcr?|arsr\d*|fmdb(?:-like)?|mota(?:-like)?|motb(?:-like)?|dksa(?:-like)?|parb(?:-like)?|para\b|partition\s*protein|plasmid\s*stability|plasmid\s*maintenance|chromosome\s*segregation|whib(?:-like)?|lsr2(?:-like)?|ead|ea22(?:-like)?|eaa|translation\s*repressor|translation\s*inhibitor|translation\s*initiation\s*factor|ribosome[- ]associated\s*(?:translation\s*)?inhibitor|peptide\s*chain\s*release\s*factor|raia)\b/i.test(t)) {
    return "Transcription & Regulation";
  }

  // 6. DNA 复制与重组修复 (Replication & Repair)
  if (
    !/\b(anti-?restriction|coenzyme\s*a\s*ligase|coa\s*ligase|trna\s*splicing\s*ligase)\b/i.test(t) &&
    /\b(dna\s*polymerases?|polymerases?|reverse\s*transcriptase|helicases?|[a-z0-9'-]*helicases?|primases?|primosom(?:al|e)|dna\s*ligases?|rna\s*ligases?|ligase\s*activity|ssb|single-stranded\s*dna|single\s*strand\s*dna|single[- ]strand\s*binding|single[- ]strand\s*annealing|ssdna|topoisomerases?|gyrases?|endonucleases?|exonucleases?|[a-z0-9'-]*nucleases?|giy-yig|vrr[- ]nuc|rnase|dnase|exoribonucleases?|endoribonucleases?|dna\s*repair|dna\s*replication|chromosome\s*replication|dna\s*metabolic\s*process|holliday|rusa(?:-like)?|ruvc(?:-like)?|recu|rece(?:-like)?|reca(?:-like)?|recb|recc|recd|rect(?:-like|\s*family)?|sbcc(?:-like)?|sbcd(?:-like)?|uvsy(?:-like)?|uvsx(?:-like)?|dpra(?:-like)?|dna\s*protecting\s*protein|erf(?:-like)?|sak4(?:-like)?|ninb|ning|rap|ninx|dna[- ]binding|sequence-specific\s*dna\s*binding|primase-helicase|dead\/deah|snf2|ftsk|spoiiie|dnac(?:-like)?|dnab(?:-like)?|dda(?:-like)?|denb(?:-like)?|dna\s*annealing|recombination[- ]mediator|junction\s*specific|replication\s*initiation|replication\s*protein|replication\s*origin|clamp\s*loader|processivity\s*factor|dna-dependent\s*atpase|umuc|umud(?:-like)?|gam(?:-like)?|dna\s*end\s*protector|end\s*protection|dna\s*transfer\s*protein|gene\s*47)\b/i.test(t)
  ) {
    return "Replication & Repair";
  }

  // 7. 宿主防御与互作 (Defense & Host Interaction)
  if (
    /\b(anti-?crispr|acranker|acr(?:\b|(?:i{1,3}|iv|v|vi|[ef])\d*[a-z0-9]*)|crispr|cas[0-9]+|defensefinder|anti-?defense|anti-?cbass|anti-?dart|nadar|thoeris|darb(?:-like)?|dara|lar(?:-like)?|arda\b|mom-like\s*dna\s*modification|hns\s*inhibition|h-ns\s*inhibition|kil\s*protein|septation\s*inhibition|restriction\s*alleviation|anti-?restriction|antirestriction|restriction\s*enzyme|restriction-modification|mrcbc|superinfection\s*exclusion|superinfection|immunity|abortive\s*infection|abi(?:-like)?|toxin-antitoxin|antitoxin|toxin|leukocidin|leukocicin|hica|hicb(?:-like)?|rele(?:-like)?|colicin|tcib(?:-like)?|tellurite\s*resistance|acridine\s*resistance|arsenite\s*resistance|fosfomycin\s*resistance|beta-lactamase|penicillin\s*binding|oxa-\d+|virulence|pathogenesis|hemolysin|ndd(?:-like)?|nucleoid\s*disruption|dmd|inhibitor\s*of\s*host\s*lon)\b/i.test(t) ||
    (!/\btrna\b/i.test(t) && /\b(dna\s*methyltransferase|cytosine\s*methyltransferase|cytosine-specific\s*dna\s*methylase|adenine\s*methylase|n-6\s*dna\s*methylase|dna\s*methylase|methylase|sam-dependent\s*methyltransferase)\b/i.test(t))
  ) {
    return "Defense & Host Interaction";
  }

  // 8. 辅助代谢基因 (Metabolism & AMG)
  if (
    /\b(phoh(?:-like)?|phosphate\s*starvation|p-starvation\s*inducible|quec(?:-like)?|queuosine|dutpase|produces\s*dump|reductive\s*methylation\s*of\s*2'-deoxyuridine|mazg(?:-like)?|ribonucleotide\s*reductase|ribonucleoside[- ]diphosphate\s*reductase|ribonucleoside\s*reductase|nrdd(?:-like)?|nrd[abefh]|thioredoxin|glutaredoxin|ferredoxin|flavodoxin|plastocyanin\w*|photosystem\s*(?:i|ii)\b|psb[ad]\b|high\s*light\s*inducible|cp12\s*protein|antenna\s*protein|folate|dihydrofolate\s*reductase|thymidylate\s*synthase|thymidine\s*kinase|dcmp\s*deaminase|transketolase|transaldolase(?:-like)?|molybdopterin|porphyrin\s*biosynthe(?:sis|tic)|heme\s*oxygenase|ferrochelatase|chelatase|radical\s*sam|acyl\s*carrier\s*protein|glycyl\s*radical\s*cofactor|grca|sir2|deacetylase|coenzyme\s*a\s*ligase|coa\s*ligase|trna\s*splicing\s*ligase|trna\s*amidotransferase|trna\s*synthetase|trna\b.*methyltransferase|nad\(p\)h-hydrate|desulfurization\s*enzyme|amino\s*acid\s*synthesis|nucleotide\s*biosynthesis|nucleoside\s*metabolic\s*process|glycine\s*cleavage|phenylacetic\s*acid\s*degradation|paaz|paay|auxiliary\s*metabolic|amg)\b/i.test(t) ||
    /\b[a-z0-9'-]*(?:kinases?|phosphatases?|phosphoesterases?|phosphodiesterases?|pyrophosphatases?|pyrophosphohydrolases?|phosphohydrolases?|triphosphatases?|diphosphorylases?|phosphorylases?|synthases?|synthetases?|reductases?|dehydrogenases?|oxidoreductases?|hydrolases?|amidohydrolases?|transferases?|transaminases?|aminotransferases?|acyltransferases?|glucosyltransferases?|glycosyltransferases?|formyltransferases?|methyltransferases?|nucleotidyltransferases?|carboxyltransferases?|transacylases?|mutases?|isomerases?|epimerases?|racemases?|decarboxylases?|carboxylases?|dehydratases?|hydratases?|monooxygenases?|dioxygenases?|oxygenases?|oxidases?|peroxidases?|catalases?|desulfurases?|deaminases?|deamidases?|nucleotidases?|esterases?|lipases?|thioesterases?|thiolases?|epoxidases?|lyases?|hydroxylases?|tautomerases?|dextranases?|glutaminases?|asparaginases?)\b/i.test(t)
  ) {
    return "Metabolism & AMG";
  }

  if (isHypotheticalName(t)) {
    return "Hypothetical";
  }

  return "Other Functional";
}

export function getFeatureColor(type: string, category?: string, product?: string): string {
  const t = (type || "").toLowerCase();
  
  if (t === "trna") return "#14b8a6"; // 蓝绿
  if (t === "rrna") return "#6366f1"; // 靛青
  if (t === "tmrna") return "#a855f7"; // 粉紫
  if (t === "crispr") return "#ec4899"; // 洋红
  if (t === "orf") return "#f43f5e"; // 鲜红
  if (t === "enzyme") return "#06b6d4"; // 亮青
  
  // 针对 CDS 依据功能大类着色
  const cat = category || inferCategoryFromText(product);
  if (FUNCTIONAL_CATEGORIES[cat]) {
    return FUNCTIONAL_CATEGORIES[cat].color;
  }
  return "#64748b";
}

export function polarToCartesian(centerX: number, centerY: number, radius: number, angleInDegrees: number) {
  const angleInRadians = (angleInDegrees - 90) * Math.PI / 180.0;
  return {
    x: centerX + (radius * Math.cos(angleInRadians)),
    y: centerY + (radius * Math.sin(angleInRadians))
  };
}

export function getCircularPath(f: any, sequenceLength: number, bounds: { innerR: number; outerR: number }) {
  if (!sequenceLength || !bounds) return "";
  
  const startAngle = (f.start / sequenceLength) * 360;
  const endAngle = (f.end / sequenceLength) * 360;
  const angleDiff = endAngle - startAngle;
  
  const { innerR, outerR } = bounds;
  const midR = (innerR + outerR) / 2;
  
  if (angleDiff < 0.5) {
    const p1 = polarToCartesian(0, 0, outerR, startAngle);
    const p2 = polarToCartesian(0, 0, outerR, endAngle);
    const p3 = polarToCartesian(0, 0, innerR, endAngle);
    const p4 = polarToCartesian(0, 0, innerR, startAngle);
    return `M ${p1.x} ${p1.y} A ${outerR} ${outerR} 0 0 1 ${p2.x} ${p2.y} L ${p3.x} ${p3.y} A ${innerR} ${innerR} 0 0 0 ${p4.x} ${p4.y} Z`;
  }
  
  const arrowAngle = Math.min(2.5, angleDiff * 0.35);
  const largeArcFlag = angleDiff - arrowAngle <= 180 ? 0 : 1;
  
  if (f.strand === "+" || f.strand === 1) {
    const p1 = polarToCartesian(0, 0, outerR, startAngle);
    const p2 = polarToCartesian(0, 0, outerR, endAngle - arrowAngle);
    const pTip = polarToCartesian(0, 0, midR, endAngle);
    const p3 = polarToCartesian(0, 0, innerR, endAngle - arrowAngle);
    const p4 = polarToCartesian(0, 0, innerR, startAngle);
    return `M ${p1.x} ${p1.y} A ${outerR} ${outerR} 0 ${largeArcFlag} 1 ${p2.x} ${p2.y} L ${pTip.x} ${pTip.y} L ${p3.x} ${p3.y} A ${innerR} ${innerR} 0 ${largeArcFlag} 0 ${p4.x} ${p4.y} Z`;
  } else {
    const pTip = polarToCartesian(0, 0, midR, startAngle);
    const p1 = polarToCartesian(0, 0, outerR, startAngle + arrowAngle);
    const p2 = polarToCartesian(0, 0, outerR, endAngle);
    const p3 = polarToCartesian(0, 0, innerR, endAngle);
    const p4 = polarToCartesian(0, 0, innerR, startAngle + arrowAngle);
    return `M ${pTip.x} ${pTip.y} L ${p1.x} ${p1.y} A ${outerR} ${outerR} 0 ${largeArcFlag} 1 ${p2.x} ${p2.y} L ${p3.x} ${p3.y} A ${innerR} ${innerR} 0 ${largeArcFlag} 0 ${p4.x} ${p4.y} Z`;
  }
}

export function getLinearPath(f: any, sequenceLength: number, linearWidth: number, bounds: { linearY: number; rowHeight: number }) {
  if (!sequenceLength || !bounds) return "";
  const sx = (f.start / sequenceLength) * linearWidth;
  const ex = (f.end / sequenceLength) * linearWidth;
  const w = ex - sx;
  
  const yTop = bounds.linearY;
  const yBot = bounds.linearY + bounds.rowHeight;
  const yMid = (yTop + yBot) / 2;
  
  const aw = Math.min(8, w * 0.35); // arrow width in px
  
  if (w < 3) {
    return `M ${sx} ${yTop} L ${ex} ${yTop} L ${ex} ${yBot} L ${sx} ${yBot} Z`;
  }
  
  if (f.strand === "+" || f.strand === 1) {
    return `M ${sx} ${yTop} L ${ex - aw} ${yTop} L ${ex} ${yMid} L ${ex - aw} ${yBot} L ${sx} ${yBot} Z`;
  } else {
    return `M ${sx} ${yMid} L ${sx + aw} ${yTop} L ${ex} ${yTop} L ${ex} ${yBot} L ${sx + aw} ${yBot} Z`;
  }
}

export function getEnzymeCircularLabel(f: any, sequenceLength: number, baseRadius: number, absoluteOuterBound: number = 0) {
  if (!sequenceLength) return null;
  const angle = ((f.start + f.end) / 2 / sequenceLength) * 360;
  const rad = (angle - 90) * Math.PI / 180;
  
  const r1 = baseRadius + 8;
  const safeOuterRadius = absoluteOuterBound > 0 ? absoluteOuterBound : baseRadius + 110;
  const level = f.labelLevel || 0;
  const visualOffset = 36;
  const baseOffset = Math.max(safeOuterRadius - baseRadius, visualOffset);
  const r2 = baseRadius + baseOffset + (level * 14); 
  
  const p1x = Math.cos(rad) * r1;
  const p1y = Math.sin(rad) * r1;
  const p2x = Math.cos(rad) * r2;
  const p2y = Math.sin(rad) * r2;
  
  const isRightHalf = angle <= 180;
  const hLength = 14;
  const p3x = p2x + (isRightHalf ? hLength : -hLength);
  const p3y = p2y;
  
  return {
    line: `M ${p1x} ${p1y} L ${p2x} ${p2y} L ${p3x} ${p3y}`,
    textX: p3x + (isRightHalf ? 4 : -4),
    textY: p3y,
    angle: 0,
    anchor: isRightHalf ? "start" : "end"
  };
}

export function getEnzymeLinearLabel(f: any, sequenceLength: number, linearWidth: number) {
  if (!sequenceLength) return null;
  const x = ((f.start + f.end) / 2 / sequenceLength) * linearWidth;
  const level = f.labelLevel || 0;
  const yBottom = 0;
  const yTop = -35 - (level * 14);
  
  return {
    line: `M ${x} ${yBottom} L ${x} ${yTop}`,
    textX: x,
    textY: yTop - 4
  };
}

export function formatLength(len: number) {
  if (!len) return "0 bp";
  if (len >= 1000000) return (len / 1000000).toFixed(2) + " Mb";
  if (len >= 1000) return (len / 1000).toFixed(2) + " kb";
  return len + " bp";
}

export function formatTickLabel(pos: number): string {
  if (pos === 0) return "0 bp";
  if (pos >= 1000000) {
    const mb = pos / 1000000;
    return Number.isInteger(mb) ? `${mb} Mb` : `${mb.toFixed(1)} Mb`;
  }
  if (pos >= 1000) {
    const kb = pos / 1000;
    return Number.isInteger(kb) ? `${kb} kb` : `${kb.toFixed(1)} kb`;
  }
  return `${pos} bp`;
}
