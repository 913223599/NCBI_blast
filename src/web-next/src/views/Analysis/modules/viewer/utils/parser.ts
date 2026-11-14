// -*- coding: utf-8 -*-
/**
 * 序列与特征解析器 (支持 GenBank, GFF3, FASTA)
 */
import { inferCategoryFromText, isHypotheticalName, FUNCTIONAL_CATEGORIES } from "./render";

export function parseGenBank(text: string) {
  const lines = text.split("\n");
  const resultFeatures: any[] = [];
  let currentSeq = "";
  let inFeatures = false;
  let inOrigin = false;
  let currentFeat: any = null;
  let currentKey = "";

  for (let line of lines) {
    if (line.startsWith("FEATURES")) {
      inFeatures = true;
      continue;
    }
    if (line.startsWith("ORIGIN")) {
      inFeatures = false;
      inOrigin = true;
      continue;
    }
    if (line.startsWith("//")) {
      inOrigin = false;
      break;
    }

    if (inFeatures) {
      // 匹配新的特征定义行 (如 '     CDS             complement(3..608)')
      if (line.startsWith("     ") && !line.startsWith("      ")) {
        const trimmed = line.trim();
        const parts = trimmed.split(/\s+/);
        if (parts.length >= 2 && parts[0] && parts[1]) {
          if (currentFeat) {
            // 过滤非基因特征 (如 source, assembly_gap)
            if (isValidFeatureType(currentFeat.type)) {
              finalizeFeature(currentFeat);
              resultFeatures.push(currentFeat);
            }
          }
          const featType = parts[0];
          const location = parts[1];
          const rangeMatch = location.match(/(\d+)\.\.(\d+)/);
          
          if (rangeMatch && rangeMatch[1] && rangeMatch[2]) {
            currentFeat = {
              type: featType,
              start: parseInt(rangeMatch[1], 10),
              end: parseInt(rangeMatch[2], 10),
              strand: location.includes("complement") ? "-" : "+",
              qualifiers: {} as Record<string, string>,
              name: "",
              locus_tag: "",
              gene: "",
              product: "",
              note: "",
              category: "",
              translation: ""
            };
          } else {
            currentFeat = null;
          }
        }
      } else if (line.startsWith("                     /")) {
        // 匹配 Qualifier 首行 (如 '                     /product="polynucleotide kinase"')
        const match = line.trim().match(/\/(\w+)=(.*)/);
        if (match && match[1] && currentFeat) {
          currentKey = match[1];
          let val = match[2] ? match[2].replace(/^"|"$/g, "") : "";
          if (currentFeat.qualifiers) {
            currentFeat.qualifiers[currentKey] = val;
          }
        }
      } else if (line.startsWith("                     ") && currentFeat && currentKey) {
        // 多行文本拼接 (如长 product 或 translation)
        const cont = line.trim().replace(/^"|"$/g, "");
        if (currentFeat.qualifiers && currentFeat.qualifiers[currentKey] !== undefined) {
          currentFeat.qualifiers[currentKey] += (currentKey === "translation" ? "" : " ") + cont;
        }
      }
    }

    if (inOrigin) {
      currentSeq += line.replace(/[\s\d]/g, "");
    }
  }

  if (currentFeat && isValidFeatureType(currentFeat.type)) {
    finalizeFeature(currentFeat);
    resultFeatures.push(currentFeat);
  }

  if (!currentSeq.length && resultFeatures.length > 0) {
    currentSeq = "N".repeat(Math.max(...resultFeatures.map((f) => f.end)));
  }

  return {
    sequence: currentSeq,
    features: normalizeLegacyOverlayFeatures(resultFeatures, currentSeq.length),
  };
}

/**
 * 清洗并兼容历史 PhageDiscovery 导出的 misc_feature 区段标记：
 * - 覆盖整条序列（无宿主侧翼）的贯穿标注直接剔除，防止覆盖正链全部 ORF
 * - 含宿主侧翼的区段标注升级为 prophage_region，走半透明跨链包络层渲染
 */
function normalizeLegacyOverlayFeatures(features: any[], seqLen: number): any[] {
  const cleaned: any[] = [];
  for (const feat of features) {
    const fType = (feat.type || "").toLowerCase();
    const note = feat.note || "";
    const isLegacyProphageMisc =
      fType === "misc_feature" &&
      !feat.product &&
      !feat.gene &&
      /(GlobalCoord=|PeakScore=|Completeness=)/i.test(note);

    if (isLegacyProphageMisc) {
      const span = Math.max(0, Number(feat.end || 0) - Number(feat.start || 0) + 1);
      if (seqLen > 0 && span >= seqLen * 0.98) {
        continue;
      }
      const qLabel = feat.qualifiers?.label || feat.name || "Prophage";
      cleaned.push({
        ...feat,
        type: "prophage_region",
        locus_tag: feat.locus_tag || String(qLabel).split(/\s+/)[0] || "Prophage",
        name: String(qLabel),
        product: `Predicted Prophage (${qLabel})`,
        category: "Other Functional",
      });
      continue;
    }
    cleaned.push(feat);
  }
  return cleaned;
}

function isValidFeatureType(type?: string): boolean {
  if (!type) return false;
  const t = type.toLowerCase();
  // 严格过滤整个序列的元数据 source 与 gap，只保留真正具有生物学意义的基因/调控特征
  return !["source", "assembly_gap", "gap"].includes(t);
}

function finalizeFeature(feat: any) {
  const q = feat.qualifiers || {};
  feat.locus_tag = q.locus_tag || q.ID || "";
  feat.gene = q.gene || q.Name || "";
  feat.product = q.product || q.description || "";
  feat.note = q.note || q.Note || q.inference || "";
  feat.translation = q.translation || "";
  
  // 决定显示主名称 (优先使用 gene -> locus_tag + product -> product -> label -> type)
  if (feat.gene && feat.product) {
    feat.name = `${feat.gene} (${feat.product})`;
  } else if (feat.product) {
    feat.name = feat.product;
  } else if (feat.gene) {
    feat.name = feat.gene;
  } else if (feat.locus_tag) {
    feat.name = feat.locus_tag;
  } else if (q.label) {
    feat.name = q.label;
  } else {
    feat.name = `${feat.type}_${feat.start}_${feat.end}`;
  }

  // 1. product 为假定/未表征蛋白时一律归 Hypothetical，不受文件中旧 /category 影响
  // 2. /category 仅在属于标准功能大类时采信
  // 3. 其余情况 (含原始 PHROG /function 文本) 依据 product 与 note 推断
  const isCds = (feat.type || "").toUpperCase() === "CDS";
  if (isCds && isHypotheticalName(feat.product || "")) {
    feat.category = "Hypothetical";
  } else if (q.category && FUNCTIONAL_CATEGORIES[q.category]) {
    feat.category = q.category;
  } else {
    feat.category = inferCategoryFromText(feat.product, feat.note);
  }
}

export function parseFasta(text: string) {
  const lines = text.split("\n");
  let seq = "";
  for (let line of lines) {
    if (!line.startsWith(">")) seq += line.trim();
  }
  return { sequence: seq, features: [] };
}
