// @ts-ignore
import { polarToCartesian } from './render';

export function calculateGC(rawSequence: string, gcBounds: {innerR: number, outerR: number}, skewBounds: {innerR: number, outerR: number}) {
  const seq = rawSequence.toUpperCase();
  const len = seq.length;
  if (!len) return { gcPathData: '', gcSkewPathData: '' };
  
  const segments = Math.min(len, 500); // 采样最多 500 个点
  const window = Math.max(1, Math.floor(len / segments));
  
  const gcPts = [];
  const skewPts = [];
  
  for (let i = 0; i < segments; i++) {
    const start = i * window;
    const end = Math.min(start + window, len);
    const chunk = seq.substring(start, end);
    
    let g = 0, c = 0;
    for (let j = 0; j < chunk.length; j++) {
      if (chunk[j] === 'G') g++;
      if (chunk[j] === 'C') c++;
    }
    
    const gc = (g + c) / chunk.length;
    const skew = (g + c) === 0 ? 0 : (g - c) / (g + c);
    const angle = ((start + chunk.length/2) / len) * 360;
    
    // GC 绘制在 gcBounds 内
    if (gcBounds) {
      const midGC = (gcBounds.innerR + gcBounds.outerR) / 2;
      const rGC = midGC + (gc - 0.5) * (gcBounds.outerR - gcBounds.innerR);
      gcPts.push(polarToCartesian(0, 0, rGC, angle));
    }
    
    // Skew 绘制在 skewBounds 内
    if (skewBounds) {
      const midSkew = (skewBounds.innerR + skewBounds.outerR) / 2;
      const rSkew = midSkew + skew * ((skewBounds.outerR - skewBounds.innerR) / 2);
      skewPts.push(polarToCartesian(0, 0, rSkew, angle));
    }
  }
  
  return {
    gcPathData: gcPts.length ? 'M ' + gcPts.map(p => `${p.x},${p.y}`).join(' L ') + ' Z' : '',
    gcSkewPathData: skewPts.length ? 'M ' + skewPts.map(p => `${p.x},${p.y}`).join(' L ') + ' Z' : ''
  };
}

export function calculateORFs(rawSequence: string, existingFeatures: any[], minLen = 300) {
  const seq = rawSequence.toUpperCase();
  const startCodons = ['ATG', 'GTG', 'TTG'];
  const stopCodons = ['TAA', 'TAG', 'TGA'];
  const orfs: any[] = [];
  
  if (!seq) return orfs;
  
  const cdsFeatures = existingFeatures.filter(f => f.type.toLowerCase() === 'cds');
  
  // Forward frames
  for (let frame = 0; frame < 3; frame++) {
    let startPos = -1;
    for (let i = frame; i < seq.length - 2; i += 3) {
      const codon = seq.substr(i, 3);
      if (startPos === -1 && startCodons.includes(codon)) {
        startPos = i;
      } else if (startPos !== -1 && stopCodons.includes(codon)) {
        if (i - startPos >= minLen) {
          const stopPos = i + 3;
          const isDuplicate = cdsFeatures.some(cds => 
            (cds.strand === '+' && Math.abs(cds.end - stopPos) <= 3) ||
            (Math.abs(cds.start - (startPos + 1)) <= 3 && Math.abs(cds.end - stopPos) <= 3)
          );
          
          if (!isDuplicate) {
            orfs.push({
              name: `ORF (+${frame + 1})`,
              type: 'ORF',
              frame: `+${frame + 1}`,
              start: startPos + 1,
              end: stopPos,
              strand: '+',
              color: '#f43f5e',
              track: -1 - frame
            });
          }
        }
        startPos = -1;
      }
    }
  }

  // Helper for reverse complement
  const complement = (char: string) => {
    switch (char) {
      case 'A': return 'T';
      case 'T': return 'A';
      case 'C': return 'G';
      case 'G': return 'C';
      default: return char;
    }
  };
  const revSeq = seq.split('').reverse().map(complement).join('');

  // Reverse frames
  for (let frame = 0; frame < 3; frame++) {
    let startPos = -1;
    for (let i = frame; i < revSeq.length - 2; i += 3) {
      const codon = revSeq.substr(i, 3);
      if (startPos === -1 && startCodons.includes(codon)) {
        startPos = i;
      } else if (startPos !== -1 && stopCodons.includes(codon)) {
        if (i - startPos >= minLen) {
          const stopPos = i + 3;
          // Map back to original sequence coordinates
          // If revSeq[i] corresponds to seq[seq.length - 1 - i]
          // The ORF is from `stopPos` (in revSeq) back to `startPos`
          const realStart = seq.length - stopPos + 1;
          const realEnd = seq.length - startPos;
          
          const isDuplicate = cdsFeatures.some(cds => 
            (cds.strand === '-' && Math.abs(cds.start - realStart) <= 3) ||
            (Math.abs(cds.start - realStart) <= 3 && Math.abs(cds.end - realEnd) <= 3)
          );
          
          if (!isDuplicate) {
            orfs.push({
              name: `ORF (-${frame + 1})`,
              type: 'ORF',
              frame: `-${frame + 1}`,
              start: realStart,
              end: realEnd,
              strand: '-',
              color: '#f59e0b',
              track: -4 - frame
            });
          }
        }
        startPos = -1;
      }
    }
  }

  return orfs;
}

export function calculateEnzymes(rawSequence: string) {
  const seq = rawSequence.toUpperCase();
  if (!seq) return [];
  
  const ENZYMES: Record<string, string> = {
    'EcoRI': 'GAATTC',
    'BamHI': 'GGATCC',
    'HindIII': 'AAGCTT',
    'XhoI': 'CTCGAG'
  };
  
  const enzymes: any[] = [];
  for (const [name, pattern] of Object.entries(ENZYMES)) {
    let index = seq.indexOf(pattern);
    while (index !== -1) {
      enzymes.push({
        name: `${name} site`,
        type: 'Enzyme',
        start: index + 1,
        end: index + pattern.length,
        strand: '+',
        color: '#14b8a6', // Teal
        track: 9 // 放最外层
      });
      index = seq.indexOf(pattern, index + 1);
    }
  }
  
  // 标签避让算法
  enzymes.sort((a, b) => a.start - b.start);
  let lastAngles: number[] = [-999, -999, -999, -999, -999]; // 记录各个层级的最后占用角度
  enzymes.forEach(enz => {
     const angle = (enz.start / seq.length) * 360;
     let level = 0;
     for (let i = 0; i < 5; i++) {
        const lastAngle = lastAngles[i] as number;
        if (Math.abs(angle - lastAngle) > 3) { // 3度安全距离
           level = i;
           lastAngles[i] = angle;
           break;
        }
     }
     enz.labelLevel = level;
  });
  
  return enzymes;
}
