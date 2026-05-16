/**
 * InstantAlignment Utility
 * Ported from React logic provided by user.
 * Implements K-mer based heuristic alignment for DNA sequences.
 */

export interface DotPlotPoint {
  x: number;
  y: number;
  strand: '+' | '-';
}

export interface Bin {
  x: number;
  score: number;
}

export interface Variant {
  start: number;
  end: number;
  score: number;
  s1_sub: string;
  s2_sub: string;
  s2_start_pos: number;
}

export interface AlignmentResult {
  len1: number;
  len2: number;
  globalSim: number;
  dotplot: DotPlotPoint[];
  bins: Bin[];
  variants: Variant[];
  binSize: number;
  mainStrand: '+' | '-';
  strandRatio: number;
  variantThreshold: number;
}

export function getReverseComplement(seq: string): string {
  const map: Record<string, string> = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' };
  return seq.split('').reverse().map(c => map[c] || c).join('');
}

export function parseFasta(fasta: string): string {
  const lines = fasta.split('\n');
  return lines.filter(l => !l.startsWith('>')).join('').replace(/\s/g, '').toUpperCase();
}

export function analyzeSequences(fasta1: string, fasta2: string): AlignmentResult {
  const s1 = parseFasta(fasta1);
  const s2 = parseFasta(fasta2);

  if (!s1 || !s2) throw new Error("无法解析序列，请确保上传了有效的 FASTA 格式内容。");

  // 算法参数设置
  const K = 15; // K-mer 长度
  const scanStep = Math.max(1, Math.floor(s1.length / 30000)); // 动态采样步长
  const BIN_SIZE = Math.max(500, Math.floor(s1.length / 100)); // 滑动窗口大小
  const len2 = s2.length;
  
  const map2Forward = new Map<string, number[]>();
  const map2Reverse = new Map<string, number[]>();
  const s2_rc = getReverseComplement(s2);

  // 【关键修复】将序列延展一倍，处理环状基因组跨越首尾的 K-mer 索引，消除边界“幽灵变异”
  const s2_double = s2 + s2;
  const s2_rc_double = s2_rc + s2_rc;

  // 1. 为序列2构建正向和反向互补 K-mer 索引 (支持无缝环状连接)
  for (let i = 0; i < len2; i++) {
    const kmerF = s2_double.slice(i, i + K);
    if (!map2Forward.has(kmerF)) map2Forward.set(kmerF, []);
    map2Forward.get(kmerF)!.push(i);

    const kmerR = s2_rc_double.slice(i, i + K);
    if (!map2Reverse.has(kmerR)) map2Reverse.set(kmerR, []);
    map2Reverse.get(kmerR)!.push(i);
  }

  const dotplot: DotPlotPoint[] = [];
  let totalSamples = 0;
  let totalMatches = 0;
  let forwardHits = 0;
  let reverseHits = 0;
  
  const bins: Bin[] = [];
  const offsetsForward: Record<number, number> = {};
  const offsetsReverse: Record<number, number> = {};

  // 2. 扫描序列1进行比对和滑动窗口分析
  for (let binStart = 0; binStart < s1.length; binStart += BIN_SIZE) {
    let binHits = 0;
    let binTotal = 0;
    const binEnd = Math.min(binStart + BIN_SIZE, s1.length);

    for (let i = binStart; i <= binEnd - K; i += scanStep) {
      binTotal++;
      totalSamples++;
      const kmer = s1.slice(i, i + K);
      let hit = false;
      
      if (map2Forward.has(kmer)) {
        hit = true;
        forwardHits++;
        const matches = map2Forward.get(kmer)!;
        for (let m = 0; m < Math.min(matches.length, 3); m++) {
          const matchPos = matches[m] as number;
          dotplot.push({ x: i, y: matchPos, strand: '+' });
        }
        // 记录偏移量用于提取对比序列 (正数取模保证在范围内)
        const firstMatch = matches[0] as number;
        const offset = ((firstMatch - i) % len2 + len2) % len2;
        offsetsForward[offset] = (offsetsForward[offset] || 0) + 1;
      }

      if (map2Reverse.has(kmer)) {
        hit = true;
        reverseHits++;
        const matches = map2Reverse.get(kmer)!;
        for (let m = 0; m < Math.min(matches.length, 3); m++) {
          const matchPos = matches[m] as number;
          dotplot.push({ x: i, y: len2 - matchPos - K, strand: '-' });
        }
        const firstMatch = matches[0] as number;
        const offset = ((firstMatch - i) % len2 + len2) % len2;
        offsetsReverse[offset] = (offsetsReverse[offset] || 0) + 1;
      }

      if (hit) {
        binHits++;
        totalMatches++;
      }
    }

    // 计算该窗口的相似度得分
    const score = binTotal > 0 ? (binHits / binTotal) : 0;
    bins.push({ x: binStart, score });
  }

  const globalSim = totalSamples > 0 ? (totalMatches / totalSamples) : 0;
  const mainStrand = forwardHits >= reverseHits ? '+' : '-';
  const strandRatio = Math.max(forwardHits, reverseHits) / (forwardHits + reverseHits || 1);

  // 提取主要位移量 (Global Mode Offset) 
  const targetOffsets = mainStrand === '+' ? offsetsForward : offsetsReverse;
  let maxGlobalOffsetCount = 0;
  let globalModeOffset = 0;
  for (const [offsetStr, count] of Object.entries(targetOffsets)) {
    if (count > maxGlobalOffsetCount) {
      maxGlobalOffsetCount = count;
      globalModeOffset = parseInt(offsetStr, 10);
    }
  }

  // 动态变异阈值与显著性过滤
  let variantThreshold = globalSim > 0.95 ? 0.99 : 0.60;
  
  // 如果全局相似度低于 1%，这通常是噪音，将变异识别设为 0 (不显示微观差异)
  if (globalSim < 0.01) variantThreshold = 0;
  const rawVariants: { start: number; end: number; score: number }[] = [];
  bins.forEach(b => {
    if (b.score < variantThreshold) {
      rawVariants.push({ start: b.x, end: Math.min(b.x + BIN_SIZE, s1.length), score: b.score });
    }
  });

  // 3. 合并相邻的变异区间
  const mergedVariants: Variant[] = [];
  let currentVar: any = null;
  rawVariants.forEach(v => {
    if (!currentVar) {
      currentVar = { ...v };
    } else {
      if (v.start === currentVar.end) {
        currentVar.end = v.end;
        currentVar.score = (currentVar.score + v.score) / 2;
      } else {
        mergedVariants.push(currentVar);
        currentVar = { ...v };
      }
    }
  });
  if (currentVar) mergedVariants.push(currentVar);

  // 4. 为每个变异区间提取精确的碱基序列进行可视化比对
  const target_s2 = mainStrand === '+' ? s2 : s2_rc;
  mergedVariants.forEach(v => {
    v.s1_sub = s1.substring(v.start, v.end);
    
    let s2_sub = "";
    let s2_start = (v.start + globalModeOffset) % len2;
    
    // 提取对应位置的序列2（支持环状绕回）
    for(let i = 0; i < v.end - v.start; i++) {
      s2_sub += target_s2[(s2_start + i) % len2];
    }
    v.s2_sub = s2_sub;
    v.s2_start_pos = s2_start;

    // 二次校准得分：确保得分与显示的差异碱基数严格一致
    let matchCount = 0;
    for (let i = 0; i < v.s1_sub.length; i++) {
      if (v.s1_sub[i] === v.s2_sub[i]) matchCount++;
    }
    v.score = matchCount / v.s1_sub.length;
  });

  return {
    len1: s1.length,
    len2: s2.length,
    globalSim,
    dotplot,
    bins,
    variants: mergedVariants,
    binSize: BIN_SIZE,
    mainStrand,
    strandRatio,
    variantThreshold
  };
}

/**
 * 将散乱的 K-mer 命中点聚合为共线性线段 (Alignments)
 * 用于适配原有 Plotly 交互组件
 */
export function convertToAlignments(result: AlignmentResult): any[] {
  const points = [...result.dotplot].sort((a, b) => a.x - b.x);
  const segments: any[] = [];
  if (points.length === 0) return [];

  let currentSeg: any = null;
  const GAP_THRESHOLD = result.binSize * 2; // 允许的跨度间隙

  points.forEach(pt => {
    if (!currentSeg) {
      currentSeg = { 
        ref_start: pt.x, ref_end: pt.x + 15, 
        query_start: pt.y, query_end: pt.y + 15,
        strand: pt.strand, length: 15, identity: 100,
        ref_id: 'Ref', query_id: 'Query'
      };
    } else {
      const dx = pt.x - currentSeg.ref_end;
      const dy = Math.abs(pt.y - currentSeg.query_end);
      
      // 如果点在同一条线上且距离较近，则合并
      if (pt.strand === currentSeg.strand && dx < GAP_THRESHOLD && dy < GAP_THRESHOLD) {
        currentSeg.ref_end = pt.x + 15;
        currentSeg.query_end = pt.y + 15;
        currentSeg.length = currentSeg.ref_end - currentSeg.ref_start;
      } else {
        segments.push(currentSeg);
        currentSeg = { 
          ref_start: pt.x, ref_end: pt.x + 15, 
          query_start: pt.y, query_end: pt.y + 15,
          strand: pt.strand, length: 15, identity: 100,
          ref_id: 'Ref', query_id: 'Query'
        };
      }
    }
  });
  if (currentSeg) segments.push(currentSeg);
  
  return segments;
}
