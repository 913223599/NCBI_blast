/**
 * 3D 蛋白结构可视化辅助工具（纯函数，不直接绑定 WebGL）
 * - 解析用户输入的残基高亮区间（如 "10-35, 60-85"）
 * - 提供 AlphaFold pLDDT 置信度标准色带映射函数
 * - 内置离线可渲染的小型示例多肽 PDB 坐标（供无网络快速自检画布）
 */

export type RenderStyle = 'cartoon' | 'stick' | 'sphere' | 'line'
export type ColorScheme = 'plddt' | 'ss' | 'spectrum'

export interface ResidueRange {
  start: number
  end: number
}

export interface TaskStructureFileItem {
  name: string
  rel_path: string
  format: 'pdb' | 'mmcif'
  size_bytes: number
}

export interface StructurePayload {
  source: string
  filename: string
  format: 'pdb' | 'mmcif'
  size_bytes: number
  content: string
  cached: boolean
  accession?: string
  rel_path?: string
}

/**
 * 解析逗号/空格分隔的残基区间，例如 "5-18, 42-60, 99" -> [{start:5,end:18}, ...]
 */
export function parseResidueRanges(raw: string): ResidueRange[] {
  const clean = String(raw || '').trim()
  if (!clean) return []
  const ranges: ResidueRange[] = []
  for (const token of clean.split(/[,;\s]+/)) {
    const part = token.trim()
    if (!part) continue
    const match = /^(\d+)(?:-(\d+))?$/.exec(part)
    if (!match) continue
    const a = Number(match[1])
    const b = match[2] ? Number(match[2]) : a
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0) continue
    ranges.push({ start: Math.min(a, b), end: Math.max(a, b) })
  }
  return ranges
}

/**
 * 将解析后的残基区间展开为 3Dmol.js 选择器可用的整数数组（最多返回 4000 个残基防误输超大区间卡顿）
 */
export function expandResidueIndices(ranges: ResidueRange[], maxCount = 4000): number[] {
  const out = new Set<number>()
  for (const r of ranges) {
    for (let i = r.start; i <= r.end; i++) {
      out.add(i)
      if (out.size >= maxCount) return Array.from(out)
    }
  }
  return Array.from(out)
}

/**
 * AlphaFold pLDDT 置信度官方色带映射 (0-100)
 * >= 90: 深蓝 (#0053D6) 极高置信
 * 70-90: 天蓝 (#65CBF3) 置信良好
 * 50-70: 亮黄 (#FFDB13) 低置信
 * < 50 : 橙红 (#FF7D45) 极低置信/无序区
 */
export function plddtColorHex(score: number): string {
  if (score >= 90) return '#0053D6'
  if (score >= 70) return '#65CBF3'
  if (score >= 50) return '#FFDB13'
  return '#FF7D45'
}

/**
 * 极简离线示例结构（12 残基右旋 α-螺旋骨架，带合成 pLDDT B-factor 字段）
 */
export const DEMO_HELIX_PDB = [
  'HEADER    DEMO PHAGE HELIX SEGMENT                26-NOV-26   DEMO',
  'TITLE     MINIMAL ALPHA-HELIX DEMO WITH SYNTHETIC PLDDT B-FACTORS',
  'ATOM      1  N   ALA A   1       1.458   0.000   0.000  1.00 94.50           N',
  'ATOM      2  CA  ALA A   1       2.300   0.000   1.200  1.00 94.50           C',
  'ATOM      3  C   ALA A   1       1.520   0.950   2.100  1.00 94.50           C',
  'ATOM      4  O   ALA A   1       1.850   2.130   2.150  1.00 94.50           O',
  'ATOM      5  N   LEU A   2       0.490   0.420   2.760  1.00 92.10           N',
  'ATOM      6  CA  LEU A   2      -0.360   1.210   3.650  1.00 92.10           C',
  'ATOM      7  C   LEU A   2      -1.260   2.120   2.820  1.00 92.10           C',
  'ATOM      8  O   LEU A   2      -1.300   3.330   3.060  1.00 92.10           O',
  'ATOM      9  N   VAL A   3      -1.990   1.540   1.870  1.00 86.40           N',
  'ATOM     10  CA  VAL A   3      -2.880   2.310   1.010  1.00 86.40           C',
  'ATOM     11  C   VAL A   3      -2.120   3.450   0.320  1.00 86.40           C',
  'ATOM     12  O   VAL A   3      -2.550   4.600   0.370  1.00 86.40           O',
  'ATOM     13  N   GLU A   4      -0.980   3.140  -0.300  1.00 82.00           N',
  'ATOM     14  CA  GLU A   4      -0.180   4.140  -1.010  1.00 82.00           C',
  'ATOM     15  C   GLU A   4       0.780   4.860  -0.060  1.00 82.00           C',
  'ATOM     16  O   GLU A   4       0.760   6.090  -0.020  1.00 82.00           O',
  'ATOM     17  N   LYS A   5       1.610   4.090   0.640  1.00 75.80           N',
  'ATOM     18  CA  LYS A   5       2.580   4.650   1.580  1.00 75.80           C',
  'ATOM     19  C   LYS A   5       1.920   5.660   2.520  1.00 75.80           C',
  'ATOM     20  O   LYS A   5       2.340   6.820   2.570  1.00 75.80           O',
  'ATOM     21  N   GLY A   6       0.890   5.210   3.240  1.00 64.20           N',
  'ATOM     22  CA  GLY A   6       0.180   6.080   4.170  1.00 64.20           C',
  'ATOM     23  C   GLY A   6      -0.780   7.010   3.420  1.00 64.20           C',
  'ATOM     24  O   GLY A   6      -0.840   8.220   3.660  1.00 64.20           O',
  'ATOM     25  N   SER A   7      -1.520   6.430   2.480  1.00 58.30           N',
  'ATOM     26  CA  SER A   7      -2.460   7.210   1.670  1.00 58.30           C',
  'ATOM     27  C   SER A   7      -1.740   8.350   0.940  1.00 58.30           C',
  'ATOM     28  O   SER A   7      -2.180   9.500   0.980  1.00 58.30           O',
  'ATOM     29  N   THR A   8      -0.610   8.030   0.310  1.00 46.00           N',
  'ATOM     30  CA  THR A   8       0.170   9.030  -0.420  1.00 46.00           C',
  'ATOM     31  C   THR A   8       1.120   9.760   0.520  1.00 46.00           C',
  'ATOM     32  O   THR A   8       1.110  10.990   0.560  1.00 46.00           O',
  'TER',
  'END',
].join('\n')
