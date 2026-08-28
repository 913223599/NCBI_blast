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
    label: "头部与衣壳包装 (Head & Capsid)",
    color: "#0284c7", // 经典海蓝
    hoverColor: "#0369a1"
  },
  "Tail & Host Interaction": {
    label: "尾部与尾丝吸附 (Tail & Fiber)",
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
    label: "溶源整合与切除 (Integration)",
    color: "#6366f1", // 亮靛紫
    hoverColor: "#4f46e5"
  },
  "Other Functional": {
    label: "其他功能蛋白 (Other)",
    color: "#64748b", // 中性板岩灰
    hoverColor: "#475569"
  },
  "Hypothetical": {
    label: "假定蛋白与未表征肽 (Hypothetical)",
    color: "#94a3b8", // 冷灰蓝
    hoverColor: "#64748b"
  }
};

/**
 * 依据产物名称 (Product) 进行生物学功能分类推断 (Product 优先原则)
 */
export function inferCategoryFromText(product?: string, notes?: string): string {
  const p = (product || "").trim().toLowerCase();
  
  // 1. 如果有明确的 product 名称且非空，严格优先依据 product 判定
  if (p && !isHypotheticalName(p)) {
    const cat = matchCategoryRules(p);
    if (cat !== "Hypothetical") {
      return cat;
    }
  }

  // 2. 如果 product 为假定蛋白或未匹配到，再 fallback 考察 notes (证据链中的 category 声明)
  if (notes) {
    const n = notes.toLowerCase();
    
    // 优先检查 notes 中明确声明的 Category 标签 (例如 'Category: lysis' 或 'Category: head and packaging')
    const catMatch = n.match(/category:\s*([a-z\s_-]+)/i);
    if (catMatch && catMatch[1]) {
      const explicitCat = matchCategoryRules(catMatch[1]);
      if (explicitCat !== "Hypothetical") {
        return explicitCat;
      }
    }
    
    const catFromNotes = matchCategoryRules(n);
    if (catFromNotes !== "Hypothetical") {
      return catFromNotes;
    }
  }

  // 3. 兜底为假定蛋白
  return "Hypothetical";
}

function isHypotheticalName(text: string): boolean {
  const t = text.trim().toLowerCase();
  return /^(hypothetical protein|uncharacterized protein|unknown function|orf\d+|protein of unknown function)$/i.test(t) ||
         t.startsWith("protein of unknown function") ||
         t.startsWith("duf") ||
         t.startsWith("pha");
}

function matchCategoryRules(text: string): string {
  const t = text.toLowerCase();

  // A. 宿主裂解系统 (优先排查，防止被结构中的 tail/head 证据误伤)
  if (/\b(lysin|endolysin|holin|antiholin|spanin|i-spanin|o-spanin|amidase|endopeptidase|peptidoglycan|murein|cell wall hydrolase|transglycosylase|lysozyme|lysis)\b/i.test(t)) {
    return "Lysis";
  }

  // B. 尾部与尾丝吸附组件 (Tail & Host Recognition - 独立分类)
  if (/\b(tail|baseplate|tape measure|tail fiber|tail spike|tail tube|tail sheath|tail assembly|tail needle|tail protein|neck1|head-tail adaptor|head-tail connector|receptor-binding|reticulocyte-binding|adhesin)\b/i.test(t) || t.includes("chaperone")) {
    return "Tail & Host Interaction";
  }

  // C. 头部与衣壳包装 (Head & Capsid Packaging)
  if (/\b(capsid|portal|terminase|head|scaffold|scaffolding|neck|collar|whisker|virion|structural|major coat|minor coat|prohead|large subunit|small subunit|head closure|head decoration|head maturation|head morphogenesis|maturation protease)\b/i.test(t)) {
    return "Head & Packaging";
  }

  // D. 溶源整合与位点特异性重组 (Integration & Excision)
  if (/\b(integrase|excisionase|transposase|recombinase|site-specific recombinase|tyrosine recombinase|serine recombinase|resolvase|insertion sequence)\b/i.test(t)) {
    // 排除复合修复酶 (如 exonuclease recombination-associated)
    if (!/\b(exonuclease|endonuclease|ribonuclease|nuclease|junction)\b/i.test(t)) {
      return "Integration & Excision";
    }
  }

  // E. 宿主防御与抗防御互作 (精准边界防误伤 helicase)
  if (/\b(anti-crispr|acr[a-z0-9]*|crispr|cas[0-9]+|methyltransferase|methylase|restriction|modification|toxin|antitoxin|darb|dara|lar-like|immunity|defense|anti-restriction|tcib|colicin|tellurite resistance|abortive infection)\b/i.test(t)) {
    return "Defense & Host Interaction";
  }

  // F. DNA 复制、重组与修复 (复合词支持：exoribonuclease, helicase)
  if (/\b(polymerase|helicase|primase|ligase|endonuclease|exonuclease|ssb|single-stranded dna|single-stranded dna-binding|ssdna|topoisomerase|gyrase|nuclease|[a-z]*nuclease|rnase|dnase|dna repair|recombination|dna binding|dntp|primase-helicase|erf|rusa|ninb|ning|rap|ninx|holliday|dead\/deah|replication initiation|replication protein)\b/i.test(t) || t.includes("helicase")) {
    return "Replication & Repair";
  }

  // G. 转录调控与开关
  if (/\b(repressor|activator|regulator|promoter|transcription|cro|c1|ci|cii|ciii|antitermination|anti-terminator|anti-sigma|sigma factor|modulator|transcriptional|helix-turn-helix|hth|csra|gntr|marr|anti-repressor|parb|partition)\b/i.test(t)) {
    return "Transcription & Regulation";
  }

  // H. 辅助代谢与酶学 (AMG - 复合词支持：phosphofructokinase)
  if (/\b(kinase|[a-z]*kinase|phosphatase|pyrophosphatase|mazg|synthase|synthetase|reductase|dehydrogenase|hydrolase|transferase|mutase|isomerase|acyltransferase|metabolism|amg|ribonucleotide|thioredoxin|glutaredoxin|nad|folate|nucleotidyltransferase)\b/i.test(t)) {
    return "Metabolism & AMG";
  }

  if (t.includes("hypothetical") || t.includes("uncharacterized") || t.includes("unknown")) {
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
