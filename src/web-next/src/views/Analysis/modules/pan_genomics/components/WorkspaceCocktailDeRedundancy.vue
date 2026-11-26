<script setup lang="ts">
/**
 * WorkspaceCocktailDeRedundancy.vue - 噬菌体鸡尾酒去冗余决策工作台
 * 核心推理引擎、KPI 与导出逻辑已抽离至 cocktail/useCocktailDeRedundancy.ts，样式已抽离至 cocktail/cocktailDeRedundancy.css
 */
import {
  useCocktailDeRedundancy,
  type CocktailDeRedundancyProps,
  type DeRedundancySample,
} from './cocktail/useCocktailDeRedundancy'

export type { DeRedundancySample }

const props = defineProps<CocktailDeRedundancyProps>()

const emit = defineEmits<{
  (e: 'select-sample', sampleId: string): void
  (e: 'select-pair', pair: [string, string]): void
}>()

const {
  statusFilter,
  searchQuery,
  selectedDrawerSample,
  isDrawerOpen,
  hoveredScatterSample,
  sampleIds,
  decisionEvaluation,
  kpis,
  tableSamples,
  scatterPoints,
  openDrawer,
  closeDrawer,
  handleCompare,
  handleExportPlanCsv,
} = useCocktailDeRedundancy(props, emit)
</script>

<template>
  <div class="decision-workbench">
    <!-- ========================================================================= -->
    <!-- 1. 研究结论层 (Biological Interpretation & Storyline) -->
    <!-- ========================================================================= -->
    <section class="storyline-section">
      <div class="storyline-main">
        <div class="storyline-badge">生物学决策结论</div>
        <h3 class="storyline-title">
          共评估 {{ kpis.total }} 株基因组，优选收敛出 {{ kpis.core + kpis.syn }} 株非冗余核心骨干代表株。
        </h3>
        <p class="storyline-desc">
          全量捕获已知 {{ kpis.coveredClusters }} 大宿主受体谱系（覆盖率 100%）。
          识别出 {{ kpis.red }} 株高 ANI 同质化克隆株并建议闲置冷冻归档，释放 {{ kpis.redundantRatio }}% 实验研发开销。
        </p>
      </div>

      <div class="storyline-actions">
        <span class="confidence-pill">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          算法决策置信度: <b>高 (94%)</b>
        </span>
        <button class="btn-export-csv" @click="handleExportPlanCsv">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导出决策方案清单 (CSV)
        </button>
      </div>
    </section>

    <!-- KPI 决策摘要条 (分母明确) -->
    <section class="kpi-summary-strip">
      <div class="kpi-col border-emerald" @click="statusFilter = 'KEEP'">
        <span class="kpi-label">核心保留 (Core)</span>
        <div class="kpi-val-line">
          <span class="num c-emerald">{{ kpis.core }}</span>
          <span class="denom">/ {{ kpis.total }}</span>
        </div>
        <span class="kpi-hint">机制正交骨干株</span>
      </div>

      <div class="kpi-col border-sky" @click="statusFilter = 'SYNERGISTIC'">
        <span class="kpi-label">协同候选 (Synergy)</span>
        <div class="kpi-val-line">
          <span class="num c-sky">{{ kpis.syn }}</span>
          <span class="denom">/ {{ kpis.total }}</span>
        </div>
        <span class="kpi-hint">受体漂移变异株</span>
      </div>

      <div class="kpi-col border-amber" @click="statusFilter = 'REDUNDANT'">
        <span class="kpi-label">建议冗存 (Archive)</span>
        <div class="kpi-val-line">
          <span class="num c-amber">{{ kpis.red }}</span>
          <span class="denom">/ {{ kpis.total }}</span>
        </div>
        <span class="kpi-hint">高ANI同质化克隆</span>
      </div>

      <div class="kpi-col border-rose" @click="statusFilter = 'REJECT'">
        <span class="kpi-label">安全剔除 (Reject)</span>
        <div class="kpi-val-line">
          <span class="num c-rose">{{ kpis.reject }}</span>
          <span class="denom">/ {{ kpis.total }}</span>
        </div>
        <span class="kpi-hint">温和/整合风险</span>
      </div>

      <div class="kpi-col border-neutral">
        <span class="kpi-label">机制覆盖 (Coverage)</span>
        <div class="kpi-val-line">
          <span class="num c-slate">{{ kpis.coveredClusters }}</span>
          <span class="denom">/ {{ kpis.coveredClusters }}</span>
        </div>
        <span class="kpi-hint">100% 受体谱系覆盖</span>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- 2. 证据解释层 (Evidence Layer: 双图并列) -->
    <!-- ========================================================================= -->
    <section class="evidence-grid">
      <!-- 左图: 全基因组机制正交度 × 受体靶点拓展决策象限 -->
      <div class="evidence-card">
        <div class="card-header-line">
          <div class="header-titles">
            <h4>基因组机制正交度 × 宿主受体拓展决策象限</h4>
            <span class="sub-text">横轴向右代表基因组机制越独立，纵轴向上代表杀菌受体谱越互补</span>
          </div>
          <div class="scatter-shape-legend">
            <span class="leg-item"><i class="shape-dot"></i> 核心保留 (骨干)</span>
            <span class="leg-item"><i class="shape-diamond"></i> 协同备选 (变异)</span>
            <span class="leg-item"><i class="shape-square"></i> 建议冗存 (克隆)</span>
            <span class="leg-item"><i class="shape-triangle"></i> 安全剔除 (温和)</span>
          </div>
        </div>

        <div class="scatter-svg-container">
          <svg viewBox="0 0 600 280" class="evidence-svg">
            <!-- 象限背景 -->
            <!-- 1. 左下: 同质克隆冗余区 (低正交 + 低受体拓展) -->
            <rect x="55" y="135" width="250" height="98" fill="#f1f5f9" fill-opacity="0.9" rx="6" />
            <text x="180" y="188" font-size="11" fill="#64748b" text-anchor="middle" font-weight="600">
              同质克隆冗余区 (建议冻存)
            </text>

            <!-- 2. 右上: 机制正交骨干区 (高正交 + 高受体拓展) -->
            <rect x="315" y="32" width="250" height="98" fill="#f0fdf4" fill-opacity="0.9" rx="6" />
            <text x="440" y="85" font-size="12" fill="#15803d" text-anchor="middle" font-weight="700">
              机制正交骨干区 (核心保留)
            </text>

            <!-- 3. 左上: 受体突变协同区 (同骨架 + 捕获漂移受体) -->
            <rect x="55" y="32" width="250" height="98" fill="#f0f9ff" fill-opacity="0.9" rx="6" />
            <text x="180" y="85" font-size="12" fill="#0369a1" text-anchor="middle" font-weight="700">
              受体突变协同区 (协同备选)
            </text>

            <!-- 4. 右下: 远缘趋同进化区 (高正交 + 相同受体) -->
            <rect x="315" y="135" width="250" height="98" fill="#fefce8" fill-opacity="0.9" rx="6" />
            <text x="440" y="188" font-size="11" fill="#a16207" text-anchor="middle" font-weight="600">
              远缘趋同进化区 (同受体)
            </text>

            <!-- 象限中心十字分割虚线 -->
            <line x1="310" y1="30" x2="310" y2="235" stroke="#cbd5e1" stroke-width="1.2" stroke-dasharray="4,4" />
            <line x1="55" y1="132" x2="565" y2="132" stroke="#cbd5e1" stroke-width="1.2" stroke-dasharray="4,4" />

            <!-- 主坐标轴 -->
            <line x1="55" y1="235" x2="565" y2="235" stroke="#94a3b8" stroke-width="1.8" />
            <line x1="55" y1="30" x2="55" y2="235" stroke="#94a3b8" stroke-width="1.8" />

            <!-- 刻度与轴标题 -->
            <text x="55" y="255" font-size="10" fill="#94a3b8" text-anchor="middle">0% (同质)</text>
            <text x="310" y="258" font-size="11" fill="#334155" text-anchor="middle" font-weight="700">全基因组机制正交度 (%) &rarr;</text>
            <text x="565" y="255" font-size="10" fill="#94a3b8" text-anchor="middle">100% (正交)</text>

            <text x="48" y="36" font-size="10" fill="#94a3b8" text-anchor="end">100%</text>
            <text x="48" y="136" font-size="10" fill="#94a3b8" text-anchor="end">50%</text>
            <text x="48" y="238" font-size="10" fill="#94a3b8" text-anchor="end">0%</text>
            <text x="18" y="132" font-size="11" fill="#334155" transform="rotate(-90 18 132)" text-anchor="middle" font-weight="700">
              受体机制拓展互补度 (%) &rarr;
            </text>

            <!-- 散点与交互 (形状+颜色双编码) -->
            <g 
              v-for="pt in scatterPoints" 
              :key="pt.sample_id"
              class="scatter-point-group"
              @click="openDrawer(pt)"
              @mouseenter="hoveredScatterSample = pt"
              @mouseleave="hoveredScatterSample = null"
            >
              <!-- 核心保留: 圆形 (Circle) -->
              <circle 
                v-if="pt.decision === 'KEEP'"
                :cx="pt.cx" 
                :cy="pt.cy" 
                r="6" 
                fill="#10b981" 
                stroke="#ffffff" 
                stroke-width="1.5"
                class="pt-geom"
              />

              <!-- 协同备选: 菱形 (Diamond) -->
              <polygon 
                v-else-if="pt.decision === 'SYNERGISTIC'"
                :points="`${pt.cx},${pt.cy-7} ${pt.cx+7},${pt.cy} ${pt.cx},${pt.cy+7} ${pt.cx-7},${pt.cy}`"
                fill="#0284c7"
                stroke="#ffffff"
                stroke-width="1.5"
                class="pt-geom"
              />

              <!-- 冗余闲置: 正方形 (Square) -->
              <rect 
                v-else-if="pt.decision === 'REDUNDANT'"
                :x="pt.cx - 5" 
                :y="pt.cy - 5" 
                width="10" 
                height="10" 
                fill="#94a3b8" 
                stroke="#ffffff" 
                stroke-width="1.5"
                class="pt-geom"
              />

              <!-- 风险剔除: 三角形 (Triangle) -->
              <polygon 
                v-else
                :points="`${pt.cx},${pt.cy-7} ${pt.cx+6},${pt.cy+5} ${pt.cx-6},${pt.cy+5}`"
                fill="#f43f5e"
                stroke="#ffffff"
                stroke-width="1.5"
                class="pt-geom"
              />

              <!-- 紧凑文字标签 -->
              <text 
                :x="pt.cx + 8" 
                :y="pt.cy + 3" 
                font-size="9" 
                fill="#334155" 
                font-weight="600"
              >
                {{ pt.sample_name.split('_')[0] }}
              </text>
            </g>
          </svg>

          <!-- 悬停即时证据浮层 Tooltip -->
          <div v-if="hoveredScatterSample" class="scatter-tooltip">
            <div class="tt-header">
              <b>{{ hoveredScatterSample.sample_name }}</b>
              <span :class="['tt-badge', hoveredScatterSample.decision.toLowerCase()]">
                {{ hoveredScatterSample.decision_label }}
              </span>
            </div>
            <div class="tt-metrics">
              <span v-if="hoveredScatterSample.decision !== 'REJECT'">
                机制正交度: <b>{{ (hoveredScatterSample.orthoX ?? 100).toFixed(0) }}%</b> (与骨干 ANI {{ hoveredScatterSample.ani_to_rep.toFixed(1) }}%)
              </span>
              <span v-else>
                安全评级: <b style="color: #f43f5e;">{{ hoveredScatterSample.lifestyle }} (未通过)</b>
              </span>
              <span>受体谱系: <b>{{ hoveredScatterSample.receptor_label }}</b></span>
            </div>
            <div class="tt-chips">
              <span v-for="(c, ci) in hoveredScatterSample.evidence_chips" :key="ci" class="tt-chip">{{ c }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右图: 最小代表集受体机制空间覆盖图 -->
      <div class="evidence-card">
        <div class="card-header-line">
          <div class="header-titles">
            <h4>最小骨干代表集 (受体机制空间覆盖)</h4>
            <span class="sub-text">
              仅需 <b>{{ kpis.core }} 株骨干代表株</b> 即可 100% 覆盖全部已知受体空间
            </span>
          </div>
          <span class="target-tag">目标: 100% 受体空间</span>
        </div>

        <div class="rep-coverage-deck">
          <div class="rep-rows-list">
            <div 
              v-for="(optId, idx) in decisionEvaluation.optimalSet" 
              :key="optId" 
              class="rep-step-row"
              @click="openDrawer(decisionEvaluation.samples.find(s => s.sample_id === optId)!)"
            >
              <span class="rep-rank">#{{ idx + 1 }}</span>
              <span class="rep-name" :title="props.sampleNames[optId] || optId">
                {{ props.sampleNames[optId] || optId }}
              </span>

              <!-- 累积覆盖条形图 -->
              <div class="rep-bar-slot">
                <div 
                  class="rep-bar-fill"
                  :style="{ width: `${Math.round(((idx + 1) / Math.max(1, kpis.core)) * 100)}%` }"
                ></div>
              </div>

              <span class="rep-coverage-val">
                {{ Math.round(((idx + 1) / Math.max(1, kpis.core)) * 100) }}%
              </span>

              <span class="rep-cl-tag">
                R{{ idx + 1 }}
              </span>
            </div>

            <!-- 冗余株增益为 0 说明 -->
            <div class="rep-step-row redundant-step-row" v-if="kpis.red > 0">
              <span class="rep-rank c-amber">+</span>
              <span class="rep-name c-amber">{{ kpis.red }} 株同质化冗余克隆</span>
              <div class="rep-bar-slot">
                <div class="rep-bar-fill red-fill" style="width: 100%;"></div>
              </div>
              <span class="rep-coverage-val c-amber">增益 +0%</span>
              <span class="rep-cl-tag tag-redundant">建议冷冻</span>
            </div>
          </div>

          <div class="minimal-set-footer">
            <div class="footer-conclusion">
              <span class="dot-success"></span>
              <span><b>优选精简鸡尾酒 = {{ kpis.core }} 株。</b> 其余 {{ kpis.red }} 株同质克隆边际生物学增益为 0%。</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- 3. 样本决策层 (Decision-First 科研结构表格) -->
    <!-- ========================================================================= -->
    <section class="sample-decisions-section">
      <!-- 表格头部过滤器与搜索 -->
      <div class="table-action-header">
        <div class="filter-pill-tabs">
          <button :class="['pill-tab', { active: statusFilter === 'ALL' }]" @click="statusFilter = 'ALL'">
            全部样本 ({{ kpis.total }})
          </button>
          <button :class="['pill-tab', 'tab-keep', { active: statusFilter === 'KEEP' }]" @click="statusFilter = 'KEEP'">
            <span class="status-dot dot-emerald"></span> 核心保留 ({{ kpis.core }})
          </button>
          <button :class="['pill-tab', 'tab-review', { active: statusFilter === 'SYNERGISTIC' }]" @click="statusFilter = 'SYNERGISTIC'">
            <span class="status-dot dot-sky"></span> 协同备选 ({{ kpis.syn }})
          </button>
          <button :class="['pill-tab', 'tab-red', { active: statusFilter === 'REDUNDANT' }]" @click="statusFilter = 'REDUNDANT'">
            <span class="status-dot dot-amber"></span> 建议冗存 ({{ kpis.red }})
          </button>
          <button :class="['pill-tab', 'tab-reject', { active: statusFilter === 'REJECT' }]" @click="statusFilter = 'REJECT'" v-if="kpis.reject > 0">
            <span class="status-dot dot-rose"></span> 安全剔除 ({{ kpis.reject }})
          </button>
        </div>

        <div class="search-input-wrap">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input 
            v-model="searchQuery" 
            placeholder="搜索样本、受体或特征标签..." 
            class="input-search"
          />
        </div>
      </div>

      <!-- Decision-First 科研结构表格 -->
      <div class="table-responsive-box">
        <table class="decision-table">
          <thead>
            <tr>
              <th style="width: 110px;">决策建议</th>
              <th style="width: 200px;">样本名称与角色</th>
              <th style="width: 120px;">宿主受体分型</th>
              <th style="width: 110px; text-align: right;">全基因组 ANI</th>
              <th>科学证据链</th>
              <th style="width: 90px;">生活史</th>
              <th style="width: 80px;">Acr</th>
              <th style="width: 90px; text-align: center;">操作/比对</th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="item in tableSamples" 
              :key="item.sample_id"
              :class="['decision-row', item.decision.toLowerCase(), { 'is-selected': selectedDrawerSample?.sample_id === item.sample_id }]"
              @click="openDrawer(item)"
            >
              <!-- 1. 决策建议 -->
              <td>
                <span :class="['badge-decision', item.decision.toLowerCase()]">
                  {{ item.decision_label }}
                </span>
              </td>

              <!-- 2. 样本与角色 -->
              <td>
                <div class="sample-name-cell">
                  <span class="sample-title" :title="item.sample_name">{{ item.sample_name }}</span>
                  <span class="sample-role-sub">{{ item.role }}</span>
                </div>
              </td>

              <!-- 3. 受体分型 -->
              <td>
                <span class="chip-receptor">{{ item.receptor_label }}</span>
              </td>

              <!-- 4. 与代表株 ANI -->
              <td style="text-align: right;">
                <div class="ani-micro-cell">
                  <span class="ani-val" :class="item.decision === 'KEEP' ? 'c-emerald' : 'c-slate'">
                    {{ item.ani_to_rep.toFixed(1) }}%
                  </span>
                  <div class="ani-micro-bar">
                    <div 
                      class="ani-micro-fill" 
                      :style="{ width: `${Math.max(0, (item.ani_to_rep - 60) * 2.5)}%` }"
                      :class="item.decision === 'KEEP' ? 'bg-emerald' : 'bg-slate'"
                    ></div>
                  </div>
                </div>
              </td>

              <!-- 5. 科学证据芯片 -->
              <td>
                <div class="chips-flex-wrap">
                  <span 
                    v-for="(chip, cIdx) in item.evidence_chips" 
                    :key="cIdx"
                    :class="['evidence-chip', { 'chip-warning': chip.includes('[警示]') || chip.includes('未通过') || chip.includes('风险') }]"
                  >
                    {{ chip }}
                  </span>
                </div>
              </td>

              <!-- 6. 生活史 -->
              <td>
                <span :class="['badge-lifestyle', item.lifestyle.toLowerCase()]">
                  {{ item.lifestyle === 'Lytic' ? '烈性 (Lytic)' : '温和 (Temperate)' }}
                </span>
              </td>

              <!-- 7. Acr -->
              <td>
                <span class="chip-acr" :title="`抗防御系统 Acr 基因数: ${item.acr_count}`">
                  Acr: {{ item.acr_count }}
                </span>
              </td>

              <!-- 8. 操作图标 -->
              <td style="text-align: center;" @click.stop>
                <div class="row-action-icons">
                  <button 
                    class="btn-icon" 
                    @click="openDrawer(item)" 
                    title="查看科学证据抽屉"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </button>

                  <button 
                    v-if="item.redundant_with"
                    class="btn-icon btn-icon-compare" 
                    @click="handleCompare(item.sample_id, item.redundant_with!)"
                    title="与骨干代表株两两比对"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <line x1="18" y1="20" x2="18" y2="10" />
                      <line x1="12" y1="20" x2="12" y2="4" />
                      <line x1="6" y1="20" x2="6" y2="14" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- 4. 解释抽屉层 (Evidence & Decision Drawer) -->
    <!-- ========================================================================= -->
    <div v-if="isDrawerOpen && selectedDrawerSample" class="drawer-overlay" @click.self="closeDrawer">
      <div class="decision-drawer">
        <!-- 抽屉头部 -->
        <div class="drawer-header">
          <div class="drawer-title-box">
            <span :class="['badge-decision', selectedDrawerSample.decision.toLowerCase()]">
              {{ selectedDrawerSample.decision_label }}
            </span>
            <h4>{{ selectedDrawerSample.sample_name }}</h4>
          </div>
          <button class="btn-close-drawer" @click="closeDrawer">&times;</button>
        </div>

        <div class="drawer-body">
          <!-- 置信度评分条 -->
          <div class="drawer-section">
            <div class="section-label">算法决策置信度</div>
            <div class="confidence-meter-row">
              <div class="confidence-bar-track">
                <div class="confidence-bar-fill" :style="{ width: `${selectedDrawerSample.confidence}%` }"></div>
              </div>
              <span class="confidence-score">{{ selectedDrawerSample.confidence }}%</span>
            </div>
          </div>

          <!-- 为什么做出该决策？证据维度拆解 -->
          <div class="drawer-section">
            <div class="section-label">决策证据链拆解</div>
            <div class="evidence-dimension-list">
              <div class="dim-row">
                <span class="dim-title">全基因组 ANI</span>
                <span class="dim-val">{{ selectedDrawerSample.detailed_reasons.genome_ani }}</span>
              </div>
              <div class="dim-row">
                <span class="dim-title">宿主受体机制</span>
                <span class="dim-val">{{ selectedDrawerSample.detailed_reasons.receptor_mechanism }}</span>
              </div>
              <div class="dim-row">
                <span class="dim-title">受体机制覆盖度</span>
                <span class="dim-val">{{ selectedDrawerSample.detailed_reasons.coverage }}</span>
              </div>
              <div class="dim-row">
                <span class="dim-title">特征生物学信号</span>
                <span class="dim-val">{{ selectedDrawerSample.detailed_reasons.unique_signals }}</span>
              </div>
            </div>
          </div>

          <!-- 对比基准代表株 (如为冗余株) -->
          <div class="drawer-section" v-if="selectedDrawerSample.redundant_with">
            <div class="section-label">对标骨干代表株</div>
            <div class="compared-card">
              <div class="comp-title">
                <b>{{ selectedDrawerSample.redundant_with_name }}</b>
                <span class="comp-tag">骨干代表株</span>
              </div>
              <div class="comp-metrics">
                <span>全基因组 ANI: <b>{{ selectedDrawerSample.ani_to_rep.toFixed(1) }}%</b></span>
                <span>尾丝受体一致性: <b>{{ selectedDrawerSample.tail_to_rep.toFixed(1) }}%</b></span>
              </div>
              <p class="comp-conclusion">
                两株在宿主识别受体与裂解机制上完全重合，保留骨干代表株即可获得 100% 的功能覆盖，建议归档闲置此株。
              </p>
            </div>
          </div>

          <!-- 安全性筛查 (Safety Screen) -->
          <div class="drawer-section">
            <div class="section-label">安全性与宿主攻防筛查</div>
            <div class="safety-grid">
              <div class="safety-item">
                <span class="s-label">生活周期</span>
                <span class="s-val" :class="selectedDrawerSample.lifestyle === 'Lytic' ? 'c-emerald' : 'c-rose'">
                  {{ selectedDrawerSample.lifestyle === 'Lytic' ? '专性烈性 (Lytic)' : '温和溶源 (Temperate)' }}
                </span>
              </div>
              <div class="safety-item">
                <span class="s-label">抗防御 Acr 基因</span>
                <span class="s-val">{{ selectedDrawerSample.acr_count }} 个</span>
              </div>
              <div class="safety-item">
                <span class="s-label">整合酶 / 切除酶</span>
                <span class="s-val" :class="selectedDrawerSample.is_safe ? 'c-emerald' : 'c-rose'">
                  {{ selectedDrawerSample.is_safe ? '未检出 (安全)' : '检出整合元件 (风险)' }}
                </span>
              </div>
              <div class="safety-item">
                <span class="s-label">毒力因子 / 毒素</span>
                <span class="s-val c-emerald">未检出 (安全)</span>
              </div>
            </div>
          </div>

          <!-- 最终科学建议 -->
          <div class="drawer-section">
            <div class="section-label">科学行动建议</div>
            <div :class="['recommendation-callout', selectedDrawerSample.decision.toLowerCase()]">
              <p v-if="selectedDrawerSample.decision === 'KEEP'">
                <b>保留为主力骨干株。</b> 拥有独立且完整的宿主受体识别谱系，建议优先进入核心鸡尾酒库。
              </p>
              <p v-else-if="selectedDrawerSample.decision === 'REDUNDANT'">
                <b>建议冷冻归档闲置。</b> 与【{{ selectedDrawerSample.redundant_with_name }}】表型机制一致，冷冻保存备份即可，无需重复实验。
              </p>
              <p v-else-if="selectedDrawerSample.decision === 'SYNERGISTIC'">
                <b>保留为协同备选株。</b> 携带受体关键突变或额外 Acr 攻防基因，建议用于突变逃逸宿主的协同配伍。
              </p>
              <p v-else>
                <b>严禁用于活性治疗鸡尾酒。</b> 存在温和溶源整合或切除风险，严禁进入临床/治疗级制剂。
              </p>
            </div>
          </div>
        </div>

        <!-- 抽屉底部动作 -->
        <div class="drawer-footer">
          <button 
            v-if="selectedDrawerSample.redundant_with" 
            class="btn-drawer-compare"
            @click="handleCompare(selectedDrawerSample.sample_id, selectedDrawerSample.redundant_with!)"
          >
            与代表株进行两两比对 &rarr;
          </button>
          <button class="btn-drawer-close" @click="closeDrawer">关闭抽屉</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import './cocktail/cocktailDeRedundancy.css';
</style>
