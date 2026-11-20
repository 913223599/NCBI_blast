<script setup lang="ts">
import { computed } from 'vue'
import type { ConnectorProfile, MorphotypeCode, StructuralModuleMatrix, StructureProteinItem } from '../types'
import { compactLocusLabel, summarizeRoleCounts } from '../utils'

const props = defineProps<{
  morphotypeCode: MorphotypeCode
  connectorProfile: ConnectorProfile
  moduleMatrix: StructuralModuleMatrix
  proteins: StructureProteinItem[]
  estimatedLengthNm?: number | null
}>()

const roleMap = computed(() => summarizeRoleCounts(props.proteins))

function collectLoci(roles: string[]): string[] {
  const found: string[] = []
  for (const r of roles) {
    for (const item of roleMap.value[r] || []) {
      if (item.locus_tag && !found.includes(item.locus_tag)) {
        found.push(item.locus_tag)
      }
      if (found.length >= 2) return found
    }
  }
  return found
}

function topLociFull(roles: string[]): string {
  const found = collectLoci(roles)
  return found.length > 0 ? found.join(', ') : '未显式检出'
}

function topLociCompact(roles: string[]): string {
  const found = collectLoci(roles)
  return found.length > 0 ? found.map((loc) => compactLocusLabel(loc, 19)).join(', ') : '未显式检出'
}

const isMyo = computed(() => props.morphotypeCode === 'Myoviridae-like')
const isSipho = computed(() => props.morphotypeCode === 'Siphoviridae-like')
const isPodo = computed(() => props.morphotypeCode === 'Podoviridae-like')
const isNonTailed = computed(() => props.morphotypeCode === 'Non-tailed')
const hasConnector = computed(() => props.moduleMatrix.connector_count > 0)
const hasHead = computed(() => props.moduleMatrix.head_packaging_count > 0)
const coreTailDisplay = computed(() => {
  const roles = isPodo.value ? ['TTPA_B', 'INTERNAL_VIRION', 'TAIL_NEEDLE'] : ['TSP', 'MTP', 'TMP', 'TAP']
  const compact = topLociCompact(roles)
  if (!isPodo.value && props.estimatedLengthNm != null) {
    return compact === '未显式检出'
      ? `标尺约 ${props.estimatedLengthNm} nm`
      : `${compact} (约 ${props.estimatedLengthNm} nm)`
  }
  return compact
})
const coreTailTitle = computed(() => {
  const roles = isPodo.value ? ['TTPA_B', 'INTERNAL_VIRION', 'TAIL_NEEDLE'] : ['TSP', 'MTP', 'TMP', 'TAP']
  const full = topLociFull(roles)
  if (!isPodo.value && props.estimatedLengthNm != null) {
    return `${full} | 理论 TMP 尾长约 ${props.estimatedLengthNm} nm`
  }
  return full
})
</script>

<template>
  <div class="diagram-card">
    <div class="diagram-head">
      <div>
        <h4>噬菌体粒子形态与尾部结构模型图</h4>
        <p class="diagram-sub">根据检出特征模块动态映射三维组件归属（悬停基因编号可查看完整 Locus Tag）</p>
      </div>
      <span class="conn-chip">{{ connectorProfile.type_label_cn }}</span>
    </div>

    <div class="svg-stage">
      <!-- 1. 非有尾噬菌体形态视图 -->
      <svg v-if="isNonTailed" viewBox="0 0 740 156" class="morpho-svg">
        <defs>
          <linearGradient id="ntGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#a855f7" />
            <stop offset="100%" stop-color="#6366f1" />
          </linearGradient>
          <linearGradient id="ntCapsidGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#c084fc" />
            <stop offset="100%" stop-color="#7e22ce" />
          </linearGradient>
        </defs>
        <!-- 紧凑二十面体无尾颗粒示意图 -->
        <g transform="translate(88, 22)">
          <polygon
            points="54,6 100,32 100,84 54,110 8,84 8,32"
            fill="url(#ntCapsidGrad)"
            stroke="#6b21a8"
            stroke-width="2"
            opacity="0.92"
          />
          <polygon points="54,6 100,32 54,58 8,32" fill="#ffffff" opacity="0.16" />
          <text x="54" y="54" text-anchor="middle" class="capsid-txt">无尾衣壳</text>
          <text x="54" y="71" text-anchor="middle" class="capsid-num">
            x{{ moduleMatrix.non_tailed_marker_count || moduleMatrix.head_packaging_count }} 核心
          </text>
        </g>
        <!-- 分隔示意丝状 / 基因组螺旋波纹 -->
        <text x="236" y="83" class="nt-divider">/</text>
        <path
          d="M 278 78 Q 350 42 422 78 T 566 78 T 668 78"
          fill="none"
          stroke="url(#ntGrad)"
          stroke-width="14"
          stroke-linecap="round"
        />
        <path
          d="M 278 78 Q 350 42 422 78 T 566 78 T 668 78"
          fill="none"
          stroke="#f3e8ff"
          stroke-width="4.5"
          stroke-dasharray="7 7"
          stroke-linecap="round"
        />
        <text x="472" y="132" text-anchor="middle" class="svg-caption">
          丝状纤毛 (Inoviridae) 或二十面体无尾基因组构型（缺乏 Portal-Tail 复合尾器）
        </text>
      </svg>

      <!-- 2. 有尾与不完整形态 SVG 解剖结构图 -->
      <svg v-else viewBox="0 0 740 164" class="morpho-svg">
        <defs>
          <linearGradient id="headGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#38bdf8" />
            <stop offset="100%" stop-color="#0284c7" />
          </linearGradient>
          <linearGradient id="connGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#8b5cf6" />
            <stop offset="100%" stop-color="#7c3aed" />
          </linearGradient>
          <linearGradient id="sheathGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2563eb" />
            <stop offset="100%" stop-color="#1d4ed8" />
          </linearGradient>
          <linearGradient id="siphoGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#16a34a" />
            <stop offset="100%" stop-color="#15803d" />
          </linearGradient>
          <linearGradient id="podoGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#fb923c" />
            <stop offset="100%" stop-color="#ea580c" />
          </linearGradient>
          <linearGradient id="podoCoreGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#fde68a" />
            <stop offset="100%" stop-color="#f59e0b" />
          </linearGradient>
        </defs>

        <!-- 二十面体头部 (水平横排左置) -->
        <g transform="translate(55, 16)">
          <polygon
            points="65,8 120,38 120,96 65,126 10,96 10,38"
            :fill="hasHead ? 'url(#headGrad)' : '#cbd5e1'"
            :stroke="hasHead ? '#0369a1' : '#94a3b8'"
            stroke-width="2"
            opacity="0.94"
          />
          <polygon points="65,8 120,38 65,68 10,38" fill="#ffffff" opacity="0.16" />
          <text x="65" y="64" text-anchor="middle" class="capsid-txt">头部包装</text>
          <text x="65" y="81" text-anchor="middle" class="capsid-num">
            x{{ moduleMatrix.head_packaging_count }} 蛋白
          </text>
        </g>

        <!-- Portal & 连接器颈部 (严格贴合头部右顶点 x=175, y=83) -->
        <rect
          x="175"
          y="67"
          width="32"
          height="32"
          rx="5"
          :fill="hasConnector ? 'url(#connGrad)' : '#f1f5f9'"
          :stroke="hasConnector ? '#6d28d9' : '#94a3b8'"
          :stroke-dasharray="hasConnector ? undefined : '4 3'"
          stroke-width="1.5"
        />
        <rect
          x="207"
          y="62"
          width="10"
          height="42"
          rx="3"
          :fill="hasConnector ? '#a78bfa' : '#cbd5e1'"
          :stroke="hasConnector ? '#7c3aed' : '#94a3b8'"
          stroke-width="1"
        />

        <!-- A. 肌尾型 Myoviridae-like -->
        <template v-if="isMyo">
          <rect x="217" y="77" width="294" height="12" fill="#f59e0b" opacity="0.9" />
          <g v-for="idx in 13" :key="idx">
            <rect
              :x="222 + (idx - 1) * 21"
              y="62"
              width="17"
              height="42"
              rx="3"
              fill="url(#sheathGrad)"
              stroke="#eff6ff"
              stroke-width="1"
            />
          </g>
          <polygon points="505,54 536,62 536,104 505,112" fill="#1e40af" stroke="#93c5fd" stroke-width="1.5" />
          <line x1="536" y1="64" x2="612" y2="30" stroke="#0d9488" stroke-width="3.2" stroke-linecap="round" />
          <line x1="536" y1="74" x2="628" y2="55" stroke="#0d9488" stroke-width="3.2" stroke-linecap="round" />
          <line x1="536" y1="92" x2="628" y2="111" stroke="#0d9488" stroke-width="3.2" stroke-linecap="round" />
          <line x1="536" y1="102" x2="612" y2="136" stroke="#0d9488" stroke-width="3.2" stroke-linecap="round" />
        </template>

        <!-- B. 长尾型 Siphoviridae-like -->
        <template v-else-if="isSipho">
          <path
            d="M 217 83 C 295 67, 345 99, 422 83 C 488 69, 524 93, 568 83"
            fill="none"
            stroke="url(#siphoGrad)"
            stroke-width="22"
            stroke-linecap="round"
          />
          <path
            d="M 217 83 C 295 67, 345 99, 422 83 C 488 69, 524 93, 568 83"
            fill="none"
            stroke="#fbbf24"
            stroke-width="6.5"
            stroke-dasharray="6 4"
            stroke-linecap="round"
          />
          <polygon points="565,69 587,83 565,97" fill="#0f766e" />
          <line x1="587" y1="83" x2="644" y2="50" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="587" y1="83" x2="650" y2="83" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="587" y1="83" x2="644" y2="116" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
        </template>

        <!-- C. 短尾型 Podoviridae-like (紧凑圆锥短尾 + 内部通道核心 + 尾刺针 + 对称尾丝，绝不遮挡头部文字) -->
        <template v-else-if="isPodo">
          <!-- 对称短尾尾丝 / 吸附突刺 -->
          <line x1="252" y1="67" x2="294" y2="36" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="258" y1="73" x2="306" y2="53" stroke="#14b8a6" stroke-width="2.4" stroke-linecap="round" />
          <line x1="258" y1="93" x2="306" y2="113" stroke="#14b8a6" stroke-width="2.4" stroke-linecap="round" />
          <line x1="252" y1="99" x2="294" y2="130" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <!-- TTPA/B 紧凑圆锥短尾壳 -->
          <polygon
            points="217,64 268,72 268,94 217,102"
            fill="url(#podoGrad)"
            stroke="#c2410c"
            stroke-width="1.5"
          />
          <!-- 内部 DNA 注射核心 (位于 Portal 与短尾管中轴通道，零文字穿模) -->
          <rect x="200" y="78" width="58" height="10" rx="5" fill="url(#podoCoreGrad)" stroke="#d97706" stroke-width="1" />
          <!-- 末端尾刺针 (Tail Needle) -->
          <polygon points="268,76 312,83 268,90" fill="#dc2626" stroke="#b91c1c" stroke-width="1" />
          <!-- 短尾部件示意引导字样 -->
          <text x="262" y="142" text-anchor="middle" class="svg-caption">
            紧凑短尾管 (TTPA/B) · 内部注射通道 · 末端刺针与吸附尾丝
          </text>
        </template>

        <!-- D. 不完整形态 -->
        <template v-else>
          <line x1="217" y1="83" x2="380" y2="83" stroke="#cbd5e1" stroke-width="12" stroke-dasharray="10 8" />
          <text x="300" y="138" text-anchor="middle" class="svg-caption">
            未检出完整尾型模块，可能为截断 Contig 或极度分异噬菌体片段
          </text>
        </template>
      </svg>

      <!-- 自适应 HTML 注释指引卡（防溢出/防裁切/紧凑基因编号） -->
      <div v-if="isNonTailed" class="callout-grid two-col">
        <div class="callout-box purple">
          <div class="c-title">丝状 / 无尾衣壳特征模块 ({{ moduleMatrix.non_tailed_marker_count }})</div>
          <div class="c-sub" :title="topLociFull(['NON_TAILED_MARKER'])">
            {{ topLociCompact(['NON_TAILED_MARKER']) }}
          </div>
        </div>
        <div class="callout-box slate">
          <div class="c-title">无有尾噬菌体复合尾器</div>
          <div class="c-sub">缺乏 TSP / MTP / TMP 典型尾部模块</div>
        </div>
      </div>

      <div v-else class="callout-grid four-col">
        <div class="callout-box sky">
          <div class="c-title">头部与包装 ({{ moduleMatrix.head_packaging_count }})</div>
          <div class="c-sub" :title="topLociFull(['MCP', 'PORTAL', 'TERL'])">
            {{ topLociCompact(['MCP', 'PORTAL', 'TERL']) }}
          </div>
        </div>
        <div class="callout-box violet">
          <div class="c-title">头-尾连接 ({{ moduleMatrix.connector_count }})</div>
          <div
            class="c-sub"
            :title="topLociFull(['CONN_AD1', 'CONN_AD2', 'CONN_AD3', 'CONN_HC1', 'CONN_HC2', 'CONN_HC3', 'CONN_NECK1', 'CONN_GENERAL', 'COLLAR_PODO'])"
          >
            {{ topLociCompact(['CONN_AD1', 'CONN_AD2', 'CONN_AD3', 'CONN_HC1', 'CONN_HC2', 'CONN_HC3', 'CONN_NECK1', 'CONN_GENERAL', 'COLLAR_PODO']) }}
          </div>
        </div>
        <div class="callout-box amber">
          <div class="c-title">{{ isPodo ? '短尾管状 / 注射模块' : '核心尾部与 TMP 标尺' }}</div>
          <div class="c-sub" :title="coreTailTitle">
            {{ coreTailDisplay }}
          </div>
        </div>
        <div class="callout-box teal">
          <div class="c-title">尾丝 / RBP ({{ moduleMatrix.tail_fiber_rbp_count }})</div>
          <div class="c-sub" :title="topLociFull(['TAIL_FIBER_RBP', 'FIBRITIN_COLLAR'])">
            {{ topLociCompact(['TAIL_FIBER_RBP', 'FIBRITIN_COLLAR']) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diagram-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px 20px 18px 20px;
}

.diagram-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}

h4 {
  margin: 0;
  font-size: 0.98rem;
  color: #0f172a;
}

.diagram-sub {
  margin: 3px 0 0 0;
  font-size: 0.8rem;
  color: #64748b;
}

.conn-chip {
  font-size: 0.76rem;
  font-weight: 600;
  color: #6d28d9;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  padding: 4px 10px;
  border-radius: 999px;
  white-space: nowrap;
}

.svg-stage {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px 12px 12px;
}

.morpho-svg {
  width: 100%;
  height: auto;
  max-height: 174px;
  display: block;
}

.capsid-txt {
  fill: #ffffff;
  font-size: 12px;
  font-weight: 700;
}

.capsid-num {
  fill: #e0f2fe;
  font-size: 11px;
  font-weight: 600;
}

.nt-divider {
  fill: #cbd5e1;
  font-size: 28px;
  font-weight: 300;
}

.svg-caption {
  fill: #64748b;
  font-size: 11px;
  font-weight: 500;
}

.callout-grid {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.callout-grid.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.callout-grid.four-col {
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}

.callout-box {
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  padding: 9px 11px;
  min-width: 0;
}

.callout-box.sky {
  background: #f0f9ff;
  border-color: #bae6fd;
}

.callout-box.violet {
  background: #f5f3ff;
  border-color: #ddd6fe;
}

.callout-box.amber {
  background: #fffbeb;
  border-color: #fde68a;
}

.callout-box.teal {
  background: #f0fdfa;
  border-color: #99f6e4;
}

.callout-box.purple {
  background: #faf5ff;
  border-color: #d8b4fe;
}

.callout-box.slate {
  background: #ffffff;
  border-color: #cbd5e1;
}

.c-title {
  font-size: 0.78rem;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.c-sub {
  margin-top: 4px;
  font-size: 0.73rem;
  line-height: 1.45;
  color: #475569;
  font-family: ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
