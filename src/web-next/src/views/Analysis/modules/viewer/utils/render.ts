export function polarToCartesian(centerX: number, centerY: number, radius: number, angleInDegrees: number) {
  const angleInRadians = (angleInDegrees - 90) * Math.PI / 180.0;
  return {
    x: centerX + (radius * Math.cos(angleInRadians)),
    y: centerY + (radius * Math.sin(angleInRadians))
  };
}

export function getFeatureColor(type: string) {
  const t = type.toLowerCase();
  if (t === 'cds') return '#3b82f6';
  if (t === 'gene') return '#10b981';
  if (t === 'trna') return '#8b5cf6';
  if (t === 'rrna') return '#f59e0b';
  if (t === 'orf') return '#f43f5e';
  if (t === 'enzyme') return '#14b8a6';
  return '#94a3b8';
}

export function getCircularPath(f: any, sequenceLength: number, bounds: { innerR: number, outerR: number }) {
  if (!sequenceLength || !bounds) return '';
  
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
  
  const arrowAngle = Math.min(2, angleDiff * 0.3);
  const largeArcFlag = angleDiff - arrowAngle <= 180 ? 0 : 1;
  
  if (f.strand === '+') {
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

export function getLinearPath(f: any, sequenceLength: number, linearWidth: number, bounds: { linearY: number, rowHeight: number }) {
  if (!sequenceLength || !bounds) return '';
  const sx = (f.start / sequenceLength) * linearWidth;
  const ex = (f.end / sequenceLength) * linearWidth;
  const w = ex - sx;
  
  const yTop = bounds.linearY;
  const yBot = bounds.linearY + bounds.rowHeight;
  const yMid = (yTop + yBot) / 2;
  
  const aw = Math.min(6, w * 0.3); // arrow width in px
  
  if (w < 2) {
    return `M ${sx} ${yTop} L ${ex} ${yTop} L ${ex} ${yBot} L ${sx} ${yBot} Z`;
  }
  
  if (f.strand === '+') {
    return `M ${sx} ${yTop} L ${ex - aw} ${yTop} L ${ex} ${yMid} L ${ex - aw} ${yBot} L ${sx} ${yBot} Z`;
  } else {
    return `M ${sx} ${yMid} L ${sx + aw} ${yTop} L ${ex} ${yTop} L ${ex} ${yBot} L ${sx + aw} ${yBot} Z`;
  }
}

export function getEnzymeCircularLabel(f: any, sequenceLength: number, baseRadius: number, absoluteOuterBound: number = 0) {
  if (!sequenceLength) return null;
  const angle = ((f.start + f.end) / 2 / sequenceLength) * 360;
  const rad = (angle - 90) * Math.PI / 180;
  
  // 连线起点：紧贴蓝色主轴，允许穿过 CDS 轨道
  const r1 = baseRadius + 10;
  
  // 文字基准面：使用动态引擎提供的最外层边界
  const safeOuterRadius = absoluteOuterBound > 0 ? absoluteOuterBound : baseRadius + 120;
  
  // 应用避让层级 (每级增加 15px 的径向延伸)
  const level = f.labelLevel || 0;
  
  // 确保文字在缩放时也不会过近
  const visualOffset = 40;
  // Use safeOuterRadius gap
  const baseOffset = Math.max(safeOuterRadius - baseRadius, visualOffset);
  const r2 = baseRadius + baseOffset + (level * 15); 
  
  const p1x = Math.cos(rad) * r1;
  const p1y = Math.sin(rad) * r1;
  
  const p2x = Math.cos(rad) * r2;
  const p2y = Math.sin(rad) * r2;
  
  // 工程制图标尺：末端增加水平折线
  const isRightHalf = angle <= 180;
  const hLength = 15;
  const p3x = p2x + (isRightHalf ? hLength : -hLength);
  const p3y = p2y;
  
  return {
    line: `M ${p1x} ${p1y} L ${p2x} ${p2y} L ${p3x} ${p3y}`,
    textX: p3x + (isRightHalf ? 4 : -4),
    textY: p3y,
    angle: 0, // 文字保持水平
    anchor: isRightHalf ? 'start' : 'end'
  };
}

export function getEnzymeLinearLabel(f: any, sequenceLength: number, linearWidth: number) {
  if (!sequenceLength) return null;
  const x = ((f.start + f.end) / 2 / sequenceLength) * linearWidth;
  
  const level = f.labelLevel || 0;
  const yBottom = 0;
  const yTop = -40 - (level * 15);
  
  return {
    line: `M ${x} ${yBottom} L ${x} ${yTop}`,
    textX: x,
    textY: yTop - 5
  };
}

export function formatLength(len: number) {
  if (len >= 1000) return (len / 1000).toFixed(2) + ' kb';
  return len + ' bp';
}
