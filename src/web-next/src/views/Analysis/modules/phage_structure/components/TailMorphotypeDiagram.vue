<script setup lang="ts">
import { computed } from 'vue'
import type { ConnectorProfile, MorphotypeCode, StructuralModuleMatrix, StructureProteinItem } from '../types'
import { summarizeRoleCounts } from '../utils'

const props = defineProps<{
  morphotypeCode: MorphotypeCode
  connectorProfile: ConnectorProfile
  moduleMatrix: StructuralModuleMatrix
  proteins: StructureProteinItem[]
  estimatedLengthNm?: number | null
}>()

const roleMap = computed(() => summarizeRoleCounts(props.proteins))

function topLoci(roles: string[]): string {
  const found: string[] = []
  for (const r of roles) {
    for (const item of roleMap.value[r] || []) {
      found.push(item.locus_tag)
      if (found.length >= 2) return found.join(', ')
    }
  }
  return found.length > 0 ? found.join(', ') : '未显式检出'
}

const isMyo = computed(() => props.morphotypeCode === 'Myoviridae-like')
const isSipho = computed(() => props.morphotypeCode === 'Siphoviridae-like')
const isPodo = computed(() => props.morphotypeCode === 'Podoviridae-like')
const isNonTailed = computed(() => props.morphotypeCode === 'Non-tailed')
</script>

<template>
  <div class="diagram-card">
    <div class="diagram-head">
      <div>
        <h4>噬菌体粒子形态与尾部结构模型图</h4>
        <p class="diagram-sub">根据检出特征模块动态映射三维组件归属（点击下方模块矩阵可定位代表基因）</p>
      </div>
      <span class="conn-chip">{{ connectorProfile.type_label_cn }}</span>
    </div>

    <div class="svg-stage">
      <!-- 1. 非有尾噬菌体形态视图 -->
      <svg v-if="isNonTailed" viewBox="0 0 740 165" class="morpho-svg">
        <defs>
          <linearGradient id="ntGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#a855f7" />
            <stop offset="100%" stop-color="#6366f1" />
          </linearGradient>
        </defs>
        <path
          d="M 85 84 Q 180 42 275 84 T 465 84 T 655 84"
          fill="none"
          stroke="url(#ntGrad)"
          stroke-width="18"
          stroke-linecap="round"
        />
        <path
          d="M 85 84 Q 180 42 275 84 T 465 84 T 655 84"
          fill="none"
          stroke="#e9d5ff"
          stroke-width="6"
          stroke-dasharray="8 8"
          stroke-linecap="round"
        />
      </svg>

      <!-- 2. 有尾与不完整形态 SVG 解剖结构图 -->
      <svg v-else viewBox="0 0 740 185" class="morpho-svg">
        <defs>
          <linearGradient id="headGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#38bdf8" />
            <stop offset="100%" stop-color="#0284c7" />
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
            <stop offset="0%" stop-color="#f97316" />
            <stop offset="100%" stop-color="#ea580c" />
          </linearGradient>
        </defs>

        <!-- 二十面体头部 (左置水平横排视图以便展示长尾尺度) -->
        <g transform="translate(55, 22)">
          <polygon
            points="65,10 120,42 120,108 65,140 10,108 10,42"
            :fill="moduleMatrix.head_packaging_count > 0 ? 'url(#headGrad)' : '#cbd5e1'"
            stroke="#0369a1"
            stroke-width="2"
            opacity="0.92"
          />
          <polygon
            points="65,10 120,42 65,75 10,42"
            fill="#ffffff"
            opacity="0.16"
          />
          <text x="65" y="72" text-anchor="middle" class="capsid-txt">头部包装</text>
          <text x="65" y="89" text-anchor="middle" class="capsid-num">
            x{{ moduleMatrix.head_packaging_count }} 蛋白
          </text>
        </g>

        <!-- Portal & 连接器颈部 -->
        <rect
          x="175"
          y="79"
          width="36"
          height="36"
          rx="5"
          :fill="moduleMatrix.connector_count > 0 ? '#8b5cf6' : '#e2e8f0'"
          stroke="#6d28d9"
          stroke-width="1.5"
        />
        <rect x="211" y="73" width="10" height="48" rx="3" fill="#a78bfa" />

        <!-- A. 肌尾型 Myoviridae-like -->
        <template v-if="isMyo">
          <rect x="221" y="91" width="290" height="12" fill="#f59e0b" opacity="0.88" />
          <g v-for="idx in 13" :key="idx">
            <rect
              :x="225 + (idx - 1) * 21"
              y="76"
              width="17"
              height="42"
              rx="3"
              fill="url(#sheathGrad)"
              stroke="#eff6ff"
              stroke-width="1"
            />
          </g>
          <polygon points="505,66 535,74 535,120 505,128" fill="#1e40af" stroke="#93c5fd" stroke-width="1.5" />
          <line x1="535" y1="76" x2="610" y2="42" stroke="#0d9488" stroke-width="3.5" stroke-linecap="round" />
          <line x1="535" y1="87" x2="625" y2="67" stroke="#0d9488" stroke-width="3.5" stroke-linecap="round" />
          <line x1="535" y1="107" x2="625" y2="127" stroke="#0d9488" stroke-width="3.5" stroke-linecap="round" />
          <line x1="535" y1="118" x2="610" y2="152" stroke="#0d9488" stroke-width="3.5" stroke-linecap="round" />
        </template>

        <!-- B. 长尾型 Siphoviridae-like -->
        <template v-else-if="isSipho">
          <path
            d="M 221 97 C 295 80, 345 114, 420 97 C 485 82, 520 107, 565 97"
            fill="none"
            stroke="url(#siphoGrad)"
            stroke-width="24"
            stroke-linecap="round"
          />
          <path
            d="M 221 97 C 295 80, 345 114, 420 97 C 485 82, 520 107, 565 97"
            fill="none"
            stroke="#fbbf24"
            stroke-width="7"
            stroke-dasharray="6 4"
            stroke-linecap="round"
          />
          <polygon points="562,82 584,97 562,112" fill="#0f766e" />
          <line x1="584" y1="97" x2="640" y2="64" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="584" y1="97" x2="646" y2="97" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="584" y1="97" x2="640" y2="130" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
        </template>

        <!-- C. 短尾型 Podoviridae-like -->
        <template v-else-if="isPodo">
          <rect x="221" y="78" width="54" height="38" rx="6" fill="url(#podoGrad)" stroke="#c2410c" stroke-width="1.5" />
          <ellipse cx="145" cy="97" rx="18" ry="11" fill="#fb923c" opacity="0.85" />
          <polygon points="275,90 330,97 275,104" fill="#dc2626" />
          <line x1="255" y1="78" x2="295" y2="47" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
          <line x1="255" y1="116" x2="295" y2="147" stroke="#0d9488" stroke-width="3" stroke-linecap="round" />
        </template>

        <!-- D. 不完整形态 -->
        <template v-else>
          <line x1="221" y1="97" x2="380" y2="97" stroke="#cbd5e1" stroke-width="12" stroke-dasharray="10 8" />
        </template>
      </svg>

      <!-- 自适应 HTML 注释指引卡（彻底防长基因名溢出 SVG 边界） -->
      <div v-if="isNonTailed" class="callout-grid two-col">
        <div class="callout-box purple">
          <div class="c-title">丝状 / 无尾衣壳特征模块 ({{ moduleMatrix.non_tailed_marker_count }})</div>
          <div class="c-sub" :title="topLoci(['NON_TAILED_MARKER'])">
            {{ topLoci(['NON_TAILED_MARKER']) }}
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
          <div class="c-sub" :title="topLoci(['MCP', 'PORTAL', 'TERL'])">
            {{ topLoci(['MCP', 'PORTAL', 'TERL']) }}
          </div>
        </div>
        <div class="callout-box violet">
          <div class="c-title">头-尾连接 ({{ moduleMatrix.connector_count }})</div>
          <div
            class="c-sub"
            :title="topLoci(['CONN_AD1', 'CONN_AD3', 'CONN_NECK1', 'CONN_HC1', 'COLLAR_PODO'])"
          >
            {{ topLoci(['CONN_AD1', 'CONN_AD3', 'CONN_NECK1', 'CONN_HC1', 'COLLAR_PODO']) }}
          </div>
        </div>
        <div class="callout-box amber">
          <div class="c-title">{{ isPodo ? '短尾管状/注射模块' : '核心尾部与 TMP 标尺' }}</div>
          <div
            class="c-sub"
            :title="
              isPodo
                ? topLoci(['TTPA_B', 'INTERNAL_VIRION', 'TAIL_NEEDLE'])
                : topLoci(['TSP', 'MTP', 'TMP', 'TAP'])
            "
          >
            {{
              isPodo
                ? topLoci(['TTPA_B', 'INTERNAL_VIRION', 'TAIL_NEEDLE'])
                : topLoci(['TSP', 'MTP', 'TMP', 'TAP'])
            }}
          </div>
        </div>
        <div class="callout-box teal">
          <div class="c-title">尾丝 / RBP ({{ moduleMatrix.tail_fiber_rbp_count }})</div>
          <div
            class="c-sub"
            :title="estimatedLengthNm != null ? `估算尾长 ${estimatedLengthNm} nm` : topLoci(['TAIL_FIBER_RBP'])"
          >
            {{ estimatedLengthNm != null ? `估算尾长 ${estimatedLengthNm} nm` : topLoci(['TAIL_FIBER_RBP']) }}
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
  padding: 18px 20px;
}

.diagram-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
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
  padding: 10px;
}

.morpho-svg {
  width: 100%;
  height: auto;
  max-height: 205px;
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
  padding: 8px 11px;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.c-sub {
  margin-top: 3px;
  font-size: 0.74rem;
  color: #64748b;
  font-family: ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
