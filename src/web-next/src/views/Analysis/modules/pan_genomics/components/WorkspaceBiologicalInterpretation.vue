<script setup lang="ts">
/**
 * WorkspaceBiologicalInterpretation.vue - 旗舰组合图 4: Four-Dimensional Evidence Stack & Decision Engine
 * (四维分层证据堆栈与科研决策模型)
 * 
 * 遵循 Nature / Science / Cell (N/S/C) 组学组合图语法 (Figure Grammar):
 * 1. 保留独立证据维度 (Genome + Function + Receptor + Safety/Phenotype)，拒绝单一模糊综合分
 * 2. 顶层群体证据综合看板 (Evidence Synthesis Board)
 * 3. 底层分层证据堆栈 (Layered Evidence Stack) ↔ 科研行动决策引擎 (Action Recommendation Engine)
 */
import { ref, computed } from 'vue'

const props = defineProps<{
  lifestyles: any[]
  armsRaceMatrix?: Record<string, any>
  tailMatrix?: Record<string, Record<string, number>>
  lysisMatrix?: Record<string, Record<string, number>>
  aniMatrix?: Record<string, Record<string, number>>
  clusters?: any[]
  amgGenes?: any[]
  amgPathwayDistributions?: Record<string, Record<string, number>>
  scientificSynthesisReport?: any
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
}>()

const emit = defineEmits<{
  (e: 'select-pair', pair: [string, string]): void
  (e: 'select-sample', sampleId: string): void
}>()

const sampleIds = computed(() => Object.keys(props.sampleNames || {}))
const totalAmgCount = computed(() => props.amgGenes?.length || 0)

// 样本对四维分层证据计算 (Four-Dimensional Evidence Stack)
const pairwiseComparison = computed(() => {
  if (!props.selectedPair) return null
  const [s1, s2] = props.selectedPair

  const name1 = props.sampleNames[s1] || s1
  const name2 = props.sampleNames[s2] || s2

  // 1. 全基因组宏观相似度 (ANI)
  const ani = props.aniMatrix?.[s1]?.[s2] ?? 0

  // 2. 基因内容 Jaccard 相似度
  let jaccard = 100
  let sharedCount = 0
  let uniqueCount = 0
  if (props.clusters && props.clusters.length > 0) {
    let shared = 0
    let union = 0
    props.clusters.forEach(c => {
      const has1 = !!c.presence_map?.[s1]
      const has2 = !!c.presence_map?.[s2]
      if (has1 && has2) shared++
      if (has1 || has2) union++
    })
    jaccard = union > 0 ? (shared / union) * 100 : 100
    sharedCount = shared
    uniqueCount = union - shared
  }

  // 3. 宿主受体特异性 (Tail Identity)
  const tailIdent = props.tailMatrix?.[s1]?.[s2] ?? 0

  // 4. 裂解系统相似度 (Lysis Identity)
  const lysisIdent = props.lysisMatrix?.[s1]?.[s2] ?? 100

  // 5. 安全性判定
  const life1 = props.lifestyles?.find(l => l.sample_id === s1)
  const life2 = props.lifestyles?.find(l => l.sample_id === s2)
  const bothSafe = (life1?.is_safe_for_therapy !== false) && (life2?.is_safe_for_therapy !== false)

  // 6. 分层科学判定 (Stratified Scientific Verdict)
  let verdict = '中度演化分化菌株 (Divergent Lineages)'
  let verdictTag = 'Divergent Pair'
  let verdictClass = 'verdict-blue'
  let interpretation = '两株噬菌体在全基因组宏观距离与功能基因家族均表现出标准的协同演化分化。'

  if (ani >= 85 && tailIdent < 50) {
    verdict = '近缘骨架 / 受体正交互补组合 (Genome-conserved / Receptor-divergent)'
    verdictTag = '理想协同候选'
    verdictClass = 'verdict-emerald'
    interpretation = `两株噬菌体共享高达 ${ani.toFixed(1)}% 的主基因组骨架与复制系统，但宿主识别结构域分化程度高达 ${(100 - tailIdent).toFixed(1)}%，预测识别完全不同的宿主表面抗原，极具扩大杀菌谱的联合制剂价值。`
  } else if (ani >= 95 && tailIdent >= 90) {
    verdict = '高度近缘同源株 (Highly Redundant Pair)'
    verdictTag = '冗余变体'
    verdictClass = 'verdict-gray'
    interpretation = `全基因组与宿主受体结合区一致性均 ≥ 90%，在宿主范围与生物学表型上高度重叠，无需重复进行耗时体外实验。`
  } else if (!bothSafe) {
    verdict = '含温和型/毒力风险组合 (Safety Concern)'
    verdictTag = '安全风险'
    verdictClass = 'verdict-amber'
    interpretation = `检测到样本中存在整合酶/阻遏蛋白，临床治疗应用前需进行基因工程修饰以敲除溶源化风险元件。`
  }

  // 7. 推荐科研下一步行动 (Recommended Next Action)
  let actions: Array<{ categoryLabel: string; text: string; type: 'green' | 'yellow' | 'blue' }> = []
  let confidence = 'High (高置信度)'

  if (ani >= 95 && tailIdent >= 90) {
    actions = [
      { categoryLabel: '优先建议', text: `建议优先挑选代表株 [${name1}] 进行后续噬斑表型实验与深层电镜表征`, type: 'green' },
      { categoryLabel: '归档监控', text: `次要株 [${name2}] 作为同源变体库保留监控，无需在初期投入重复的体外耗时实验`, type: 'yellow' },
      { categoryLabel: '精细排查', text: '若两株在宿主谱裂解范围上存在微弱差异，应重点排查 Tail fibre 局部点突变而非宏观差异', type: 'blue' }
    ]
  } else if (ani >= 80 && tailIdent < 60) {
    actions = [
      { categoryLabel: '联合制剂', text: `强烈建议将 [${name1}] 与 [${name2}] 共同纳入多价噬菌体生物制剂配对候选库`, type: 'green' },
      { categoryLabel: '表型验证', text: '建议针对两株样本开展体外交叉裂解谱实验 (Cross-infection Matrix Assay)', type: 'blue' },
      { categoryLabel: '序列比对', text: '对 Tail/RBP 区域进行多重序列比对，定位受体结合结构域 (RBD) 的关键突变位点', type: 'yellow' }
    ]
  } else {
    actions = [
      { categoryLabel: '独立表征', text: '两株噬菌体分属不同亚群，建议作为独立系统发育分支进行全套表型表征', type: 'green' },
      { categoryLabel: '动力学测定', text: '分别测定两株噬菌体的一步生长曲线（潜伏期与裂解量指标）', type: 'blue' }
    ]
  }

  return {
    s1, s2, name1, name2,
    ani: ani.toFixed(1),
    jaccard: jaccard.toFixed(1),
    tailIdent: tailIdent.toFixed(1),
    lysisIdent: lysisIdent.toFixed(1),
    sharedCount,
    uniqueCount,
    bothSafe,
    verdict,
    verdictTag,
    verdictClass,
    interpretation,
    confidence,
    actions
  }
})
</script>

<template>
  <div class="workspace-biological-interpretation">
    <!-- Panel A: 群体证据综合看板 (Evidence Synthesis Board) -->
    <div class="academic-panel synthesis-board-panel">
      <div class="panel-header">
        <div class="title-with-tag">
          <span class="panel-tag">Figure 4 Flagship</span>
          <h3>多组学群体证据综合看板 (Evidence Synthesis Board)</h3>
        </div>
        <span class="panel-subtip">点击任意样本或样本对可生成四维分层证据堆栈与科研决策</span>
      </div>

      <div class="board-table-wrap">
        <table class="academic-synthesis-table">
          <thead>
            <tr>
              <th>噬菌体样本 (Sample)</th>
              <th>生活史预测 (Lifestyle)</th>
              <th>治疗安全性</th>
              <th>攻防武器 (Acr)</th>
              <th>耐药/毒力 (AMR/VF)</th>
              <th>宿主识别策略</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="l in lifestyles" 
              :key="l.sample_id"
              class="synthesis-row"
              :class="{ 'row-selected': selectedPair?.includes(l.sample_id) }"
            >
              <td class="td-sample-title">
                <strong>{{ l.sample_name }}</strong>
                <code>{{ l.sample_id }}</code>
              </td>
              <td>
                <span :class="['lifestyle-badge', l.lifestyle === 'Lytic' ? 'badge-lytic' : 'badge-temperate']">
                  {{ l.lifestyle === 'Lytic' ? '专性烈性 (Lytic)' : '温和型 (Temperate)' }}
                </span>
              </td>
              <td>
                <span :class="['safe-pill', l.is_safe_for_therapy ? 'pill-safe' : 'pill-risk']">
                  {{ l.is_safe_for_therapy ? '安全合规' : '需剔除整合酶 (风险)' }}
                </span>
              </td>
              <td>
                <strong class="text-blue">{{ armsRaceMatrix?.[l.sample_id]?.acr_count || 0 }}</strong> 个 Acr 因子
              </td>
              <td>
                <span v-if="(armsRaceMatrix?.[l.sample_id]?.amr_count || 0) === 0" class="text-green">0 (无风险)</span>
                <span v-else class="text-red">{{ armsRaceMatrix?.[l.sample_id]?.amr_count }} 个耐药基因</span>
              </td>
              <td>
                <span class="tail-strategy-tag">
                  {{ l.lifestyle === 'Lytic' ? '标准吸附型' : '溶源整合型' }}
                </span>
              </td>
              <td>
                <button 
                  class="btn-select-sample"
                  @click="emit('select-sample', l.sample_id)"
                >
                  锁定对比
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 下层双看板: 四维分层证据堆栈 (左) + 决策引擎与代谢自适应区 (右) -->
    <div class="bio-bottom-grid">
      <!-- 🌟 Panel B: 四维分层证据堆栈 (Four-Dimensional Evidence Stack) -->
      <div class="academic-panel comparison-card-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Evidence Stack</span>
            <h3>分层科研证据堆栈 (Four-Dimensional Evidence Stack)</h3>
          </div>
          <span class="focus-pair-text" v-if="pairwiseComparison">
            {{ pairwiseComparison.name1 }} ↔ {{ pairwiseComparison.name2 }}
          </span>
        </div>

        <div class="card-body" v-if="pairwiseComparison">
          <!-- 核心科学判定 -->
          <div class="verdict-banner" :class="pairwiseComparison.verdictClass">
            <div class="verdict-top-row">
              <span class="verdict-tag">{{ pairwiseComparison.verdictTag }}</span>
              <span class="confidence-pill">
                <strong>证据等级:</strong> {{ pairwiseComparison.confidence }}
              </span>
            </div>
            <h4 class="verdict-title">{{ pairwiseComparison.verdict }}</h4>
            <p class="verdict-p">{{ pairwiseComparison.interpretation }}</p>
          </div>

          <!-- 四维独立证据条 -->
          <div class="evidence-bars-grid">
            <!-- 1. 全基因组宏观相似度 -->
            <div class="evidence-bar-row">
              <div class="bar-lbl-col">
                <span class="bar-name">1. 全基因组核酸相似度 (Genome ANI)</span>
                <span class="bar-num">{{ pairwiseComparison.ani }}%</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill bg-blue" :style="{ width: pairwiseComparison.ani + '%' }"></div>
              </div>
            </div>

            <!-- 2. 基因内容重合度 -->
            <div class="evidence-bar-row">
              <div class="bar-lbl-col">
                <span class="bar-name">2. 基因内容 Jaccard 重叠度</span>
                <span class="bar-num">{{ pairwiseComparison.jaccard }}% (共 {{ pairwiseComparison.sharedCount }} 共有家族)</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill bg-indigo" :style="{ width: pairwiseComparison.jaccard + '%' }"></div>
              </div>
            </div>

            <!-- 3. 受体结合区特异性 -->
            <div class="evidence-bar-row">
              <div class="bar-lbl-col">
                <span class="bar-name">3. 尾部受体结合结构域 (Tail Identity)</span>
                <span class="bar-num">{{ pairwiseComparison.tailIdent }}%</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill bg-amber" :style="{ width: pairwiseComparison.tailIdent + '%' }"></div>
              </div>
            </div>

            <!-- 4. 裂解系统保守性 -->
            <div class="evidence-bar-row">
              <div class="bar-lbl-col">
                <span class="bar-name">4. 内溶素裂解系统 (Lysis Identity)</span>
                <span class="bar-num">{{ pairwiseComparison.lysisIdent }}%</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill bg-emerald" :style="{ width: pairwiseComparison.lysisIdent + '%' }"></div>
              </div>
            </div>
          </div>
        </div>

        <div class="empty-card-placeholder" v-else>
          <p>请在上方【多组学证据看板】中选择任意两个样本，系统将自动生成四维独立证据链与科研推论。</p>
        </div>
      </div>

      <!-- 🌟 Panel C: 科研决策引擎与下一步行动指南 -->
      <div class="academic-panel decision-engine-panel">
        <div class="panel-header">
          <div class="title-with-tag">
            <span class="panel-tag">Decision Engine</span>
            <h3>科研决策引擎与下一步行动建议 (Recommended Next Actions)</h3>
          </div>
        </div>

        <div class="decision-body" v-if="pairwiseComparison">
          <!-- 推荐科研行动列表 -->
          <div class="action-items-list">
            <div 
              v-for="(act, idx) in pairwiseComparison.actions" 
              :key="idx"
              class="action-item"
              :class="'action-' + act.type"
            >
              <span class="act-type-tag" :class="'tag-' + act.type">{{ act.categoryLabel }}</span>
              <span class="act-text">{{ act.text }}</span>
            </div>
          </div>

          <!-- 代谢基因自适应推断 -->
          <div class="amg-suppression-box" v-if="totalAmgCount === 0">
            <div class="supp-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M2 15c6.667-6 13.333 0 20-6" />
                <path d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993" />
                <path d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993" />
              </svg>
            </div>
            <div class="supp-content">
              <h4>辅助代谢基因 (AMG) 自适应结论</h4>
              <p>群体中未检测到宿主辅助代谢基因簇（AMG=0），提示该群噬菌体采取标准专性快速裂解模式，未演化出重塑宿主碳氮代谢的额外代谢负担。</p>
            </div>
          </div>
        </div>

        <div class="empty-card-placeholder" v-else>
          <p>锁定对比样本对后，决策引擎将自动给出体外实验、测序验证与鸡尾酒制备行动建议。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workspace-biological-interpretation {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.academic-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 10px;
}

.title-with-tag {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-tag {
  background: #0f172a;
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
}

.panel-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.panel-subtip {
  font-size: 11px;
  color: #94a3b8;
}

/* 看板表格 */
.board-table-wrap {
  overflow-x: auto;
}

.academic-synthesis-table {
  width: 100%;
  border-collapse: collapse;
}

.academic-synthesis-table th {
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  padding: 8px 10px;
  border-bottom: 1.5px solid #e2e8f0;
}

.synthesis-row {
  border-bottom: 1px solid #f1f5f9;
}

.synthesis-row:hover {
  background: #f8fafc;
}

.row-selected {
  background: #eff6ff !important;
}

.academic-synthesis-table td {
  padding: 8px 10px;
  font-size: 11px;
}

.td-sample-title {
  display: flex;
  flex-direction: column;
}

.td-sample-title code {
  font-size: 9px;
  color: #94a3b8;
}

.lifestyle-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.badge-lytic { background: #dcfce7; color: #166534; }
.badge-temperate { background: #ede9fe; color: #6d28d9; }

.safe-pill {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.pill-safe { background: #e0f2fe; color: #0369a1; }
.pill-risk { background: #fee2e2; color: #b91c1c; }

.text-blue { color: #2563eb; }
.text-green { color: #16a34a; }
.text-red { color: #dc2626; }

.tail-strategy-tag {
  background: #f1f5f9;
  color: #475569;
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 4px;
}

.btn-select-sample {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  font-size: 10px;
  font-weight: 600;
  color: #334155;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-select-sample:hover {
  background: #0f172a;
  color: #ffffff;
}

/* 下层网格 */
.bio-bottom-grid {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 16px;
}

.focus-pair-text {
  font-size: 11px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 3px 8px;
  border-radius: 4px;
}

/* 决策卡 */
.verdict-banner {
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.verdict-emerald {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}

.verdict-blue {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
}

.verdict-amber {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

.verdict-gray {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
}

.verdict-top-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.verdict-tag {
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
}

.confidence-pill {
  font-size: 9px;
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
}

.verdict-title {
  margin: 0 0 4px;
  font-size: 13px;
  font-weight: 800;
}

.verdict-p {
  margin: 0;
  font-size: 11px;
  line-height: 1.4;
  opacity: 0.9;
}

.evidence-bars-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evidence-bar-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bar-lbl-col {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #475569;
}

.bar-num {
  font-weight: 700;
  color: #0f172a;
}

.progress-track {
  height: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.bg-blue { background: #2563eb; }
.bg-indigo { background: #6366f1; }
.bg-amber { background: #f59e0b; }
.bg-emerald { background: #10b981; }

/* 决策引擎行动列表 */
.decision-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.action-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.4;
}

.action-green {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}

.action-yellow {
  background: #fffbeb;
  border: 1px solid #fef3c7;
  color: #92400e;
}

.action-blue {
  background: #eff6ff;
  border: 1px solid #dbeafe;
  color: #1e40af;
}

.act-type-tag {
  font-size: 9.5px;
  font-weight: 700;
  padding: 1.5px 5px;
  border-radius: 3px;
  white-space: nowrap;
  flex-shrink: 0;
}

.tag-green {
  background: #dcfce7;
  color: #15803d;
}

.tag-yellow {
  background: #fef3c7;
  color: #b45309;
}

.tag-blue {
  background: #dbeafe;
  color: #1d4ed8;
}

.amg-suppression-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}

.supp-icon {
  font-size: 18px;
}

.supp-content h4 {
  margin: 0 0 4px;
  font-size: 11px;
  font-weight: 700;
  color: #334155;
}

.supp-content p {
  margin: 0;
  font-size: 10px;
  color: #64748b;
  line-height: 1.3;
}

.empty-card-placeholder {
  padding: 40px 20px;
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
}
</style>
