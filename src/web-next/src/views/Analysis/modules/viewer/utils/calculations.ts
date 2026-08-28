// -*- coding: utf-8 -*-
/**
 * 序列生物信息学计算工具 (GC 含量、GC Skew 偏斜度、ORF、限制性内切酶)
 */
import { polarToCartesian } from "./render";

export interface GCPathsResult {
  gcPathData: string;
  gcHighPathData: string;
  gcLowPathData: string;
  gcSkewPosPathData: string;
  gcSkewNegPathData: string;
  gcBaselineRadius: number;
  skewBaselineRadius: number;
}

export function calculateGC(
  rawSequence: string, 
  gcBounds: { innerR: number; outerR: number }, 
  skewBounds: { innerR: number; outerR: number }
): GCPathsResult {
  const seq = rawSequence.toUpperCase();
  const len = seq.length;
  
  const midGC = (gcBounds.innerR + gcBounds.outerR) / 2;
  const midSkew = (skewBounds.innerR + skewBounds.outerR) / 2;
  
  if (!len) {
    return {
      gcPathData: "",
      gcHighPathData: "",
      gcLowPathData: "",
      gcSkewPosPathData: "",
      gcSkewNegPathData: "",
      gcBaselineRadius: midGC,
      skewBaselineRadius: midSkew
    };
  }

  // 1. 先计算全局平均 GC
  let totalG = 0;
  let totalC = 0;
  for (let i = 0; i < len; i++) {
    if (seq[i] === "G") totalG++;
    if (seq[i] === "C") totalC++;
  }
  const avgGC = (totalG + totalC) / Math.max(1, len);

  // 2. 窗口采样 (采样 300 ~ 600 个点)
  const segments = Math.min(len, 400);
  const windowSize = Math.max(1, Math.floor(len / segments));

  const gcHighSegments: Array<{ p1: { x: number; y: number }; p2: { x: number; y: number }; base1: { x: number; y: number }; base2: { x: number; y: number } }> = [];
  const gcLowSegments: Array<{ p1: { x: number; y: number }; p2: { x: number; y: number }; base1: { x: number; y: number }; base2: { x: number; y: number } }> = [];

  const skewPosSegments: Array<{ p1: { x: number; y: number }; p2: { x: number; y: number }; base1: { x: number; y: number }; base2: { x: number; y: number } }> = [];
  const skewNegSegments: Array<{ p1: { x: number; y: number }; p2: { x: number; y: number }; base1: { x: number; y: number }; base2: { x: number; y: number } }> = [];

  const gcLinePts: Array<{ x: number; y: number }> = [];

  for (let i = 0; i < segments; i++) {
    const start = i * windowSize;
    const end = Math.min(start + windowSize, len);
    const chunk = seq.substring(start, end);

    let g = 0;
    let c = 0;
    for (let j = 0; j < chunk.length; j++) {
      if (chunk[j] === "G") g++;
      if (chunk[j] === "C") c++;
    }

    const localGC = (g + c) / Math.max(1, chunk.length);
    const localSkew = (g + c) === 0 ? 0 : (g - c) / (g + c);

    const startAngle = (start / len) * 360;
    const endAngle = (end / len) * 360;
    const midAngle = ((start + end) / 2 / len) * 360;

    // GC 偏离平均值的径向距离
    const gcDiff = localGC - avgGC; // 正为高于平均，负为低于平均
    const gcMaxDiff = 0.35; // 最大偏离容差
    const gcRadius = midGC + (gcDiff / gcMaxDiff) * ((gcBounds.outerR - gcBounds.innerR) / 2);
    const clampedGCRadius = Math.max(gcBounds.innerR, Math.min(gcBounds.outerR, gcRadius));

    const gcPt = polarToCartesian(0, 0, clampedGCRadius, midAngle);
    gcLinePts.push(gcPt);

    const basePt1 = polarToCartesian(0, 0, midGC, startAngle);
    const basePt2 = polarToCartesian(0, 0, midGC, endAngle);
    const gcValPt1 = polarToCartesian(0, 0, clampedGCRadius, startAngle);
    const gcValPt2 = polarToCartesian(0, 0, clampedGCRadius, endAngle);

    if (gcDiff >= 0) {
      gcHighSegments.push({ p1: gcValPt1, p2: gcValPt2, base1: basePt1, base2: basePt2 });
    } else {
      gcLowSegments.push({ p1: gcValPt1, p2: gcValPt2, base1: basePt1, base2: basePt2 });
    }

    // Skew 偏离 0 轴的径向距离
    const skewRadius = midSkew + localSkew * ((skewBounds.outerR - skewBounds.innerR) / 2);
    const clampedSkewRadius = Math.max(skewBounds.innerR, Math.min(skewBounds.outerR, skewRadius));

    const skewBasePt1 = polarToCartesian(0, 0, midSkew, startAngle);
    const skewBasePt2 = polarToCartesian(0, 0, midSkew, endAngle);
    const skewValPt1 = polarToCartesian(0, 0, clampedSkewRadius, startAngle);
    const skewValPt2 = polarToCartesian(0, 0, clampedSkewRadius, endAngle);

    if (localSkew >= 0) {
      skewPosSegments.push({ p1: skewValPt1, p2: skewValPt2, base1: skewBasePt1, base2: skewBasePt2 });
    } else {
      skewNegSegments.push({ p1: skewValPt1, p2: skewValPt2, base1: skewBasePt1, base2: skewBasePt2 });
    }
  }

  // 构建闭合填充多边形路径
  function buildPathFromSegments(segs: typeof gcHighSegments): string {
    if (!segs.length) return "";
    return segs
      .map((s) => `M ${s.base1.x},${s.base1.y} L ${s.p1.x},${s.p1.y} L ${s.p2.x},${s.p2.y} L ${s.base2.x},${s.base2.y} Z`)
      .join(" ");
  }

  return {
    gcPathData: gcLinePts.length ? "M " + gcLinePts.map((p) => `${p.x},${p.y}`).join(" L ") + " Z" : "",
    gcHighPathData: buildPathFromSegments(gcHighSegments),
    gcLowPathData: buildPathFromSegments(gcLowSegments),
    gcSkewPosPathData: buildPathFromSegments(skewPosSegments),
    gcSkewNegPathData: buildPathFromSegments(skewNegSegments),
    gcBaselineRadius: midGC,
    skewBaselineRadius: midSkew
  };
}

export function calculateEnzymes(rawSequence: string) {
  const seq = rawSequence.toUpperCase();
  const enzymesList = [
    { name: "EcoRI", site: "GAATTC", color: "#ef4444" },
    { name: "BamHI", site: "GGATCC", color: "#f97316" },
    { name: "HindIII", site: "AAGCTT", color: "#eab308" },
    { name: "NotI", site: "GCGGCCGC", color: "#10b981" },
    { name: "XhoI", site: "CTCGAG", color: "#06b6d4" },
    { name: "NcoI", site: "CCATGG", color: "#3b82f6" },
    { name: "PstI", site: "CTGCAG", color: "#8b5cf6" },
    { name: "SalI", site: "GTCGAC", color: "#ec4899" }
  ];

  const results: any[] = [];
  for (const enz of enzymesList) {
    let pos = seq.indexOf(enz.site);
    let count = 0;
    while (pos !== -1 && count < 20) {
      results.push({
        name: enz.name,
        type: "Enzyme",
        start: pos + 1,
        end: pos + enz.site.length,
        color: enz.color,
        strand: "+"
      });
      pos = seq.indexOf(enz.site, pos + 1);
      count++;
    }
  }
  return results.sort((a, b) => a.start - b.start);
}
