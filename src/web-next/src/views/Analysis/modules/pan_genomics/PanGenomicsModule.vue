<script setup lang="ts">
/**
 * PanGenomicsModule.vue - 问题驱动的比较基因组学工作台 (Comparative Genomics Workspace)
 * 围绕 5 大核心科学问题展开的证据链系统：
 * Q1: Population Landscape (整体进化如何分群？进化与功能是否解耦？)
 * Q2: Pan-genome Architecture (保守核心与可变基因如何构成？)
 * Q3: Functional Divergence (功能模块分化与宿主识别策略？)
 * Q4: Genome Architecture (差异发生在基因组什么空间位置与构型？)
 * Q5: Biological Interpretation (对宿主识别、裂解与安全性意味着什么？)
 */
import { ref, onMounted, computed } from 'vue'
import { getBridge } from '../../../../bridge'
import BatchSampleSelector, { type BatchSampleItem } from '../../../../components/common/BatchSampleSelector.vue'

import WorkspacePopulationLandscape from './components/WorkspacePopulationLandscape.vue'
import WorkspaceCocktailDeRedundancy from './components/WorkspaceCocktailDeRedundancy.vue'
import WorkspaceFunctionalDivergence from './components/WorkspaceFunctionalDivergence.vue'
import WorkspaceGenomeArchitecture from './components/WorkspaceGenomeArchitecture.vue'
import WorkspaceBiologicalInterpretation from './components/WorkspaceBiologicalInterpretation.vue'

const availableSamples = ref<BatchSampleItem[]>([])
const selectedSamples = ref<BatchSampleItem[]>([])
const isLoadingSamples = ref(false)
const isRunning = ref(false)
const errorMessage = ref<string | null>(null)

const identityThreshold = ref<number>(0.5)
const activeWorkspace = ref<string>('population')

// 计算分析结果
const analysisResult = ref<any | null>(null)

// 全局持久化对比上下文状态 (Global Persistent Comparison Context)
const selectedPair = ref<[string, string] | null>(null)

// 选中样本对时的快捷统计计算 (严格区分 Genome / Function / Receptor 三种分化)
const pairSummary = computed(() => {
  if (!selectedPair.value || !analysisResult.value) return null
  const [s1, s2] = selectedPair.value
  const name1 = analysisResult.value.sample_names?.[s1] || s1
  const name2 = analysisResult.value.sample_names?.[s2] || s2

  const ani = analysisResult.value.ani_matrix?.[s1]?.[s2] ?? 0
  const tailSim = analysisResult.value.tail_identity_matrix?.[s1]?.[s2] ?? 0
  const tailDiff = 100 - tailSim

  // 1. 全基因组宏观分化
  let genomeDivergence = '高度相似'
  if (ani < 70) genomeDivergence = '显著分化'
  else if (ani < 90) genomeDivergence = '中度分化'

  // 2. 基因功能内容分化
  let functionDivergence = '功能高度保守'
  if (analysisResult.value.clusters?.length) {
    let shared = 0
    let union = 0
    analysisResult.value.clusters.forEach((c: any) => {
      const has1 = !!c.presence_map?.[s1]
      const has2 = !!c.presence_map?.[s2]
      if (has1 && has2) shared++
      if (has1 || has2) union++
    })
    const jaccard = union > 0 ? (shared / union) * 100 : 100
    if (jaccard < 70) functionDivergence = `功能分化 (${jaccard.toFixed(0)}%)`
    else functionDivergence = `功能保守 (${jaccard.toFixed(0)}%)`
  }

  // 3. 宿主受体识别分化
  let receptorDivergence = '完全一致'
  let receptorClass = ''
  if (tailDiff >= 50) {
    receptorDivergence = '正交 / 显著分化'
    receptorClass = 'c-amber'
  } else if (tailDiff >= 20) {
    receptorDivergence = '受体突变分化'
    receptorClass = 'c-amber'
  }

  const life1 = analysisResult.value.lifestyles?.find((l: any) => l.sample_id === s1)
  const life2 = analysisResult.value.lifestyles?.find((l: any) => l.sample_id === s2)
  const isSafe = (life1?.is_safe_for_therapy !== false) && (life2?.is_safe_for_therapy !== false)
  const safetyStatus = isSafe ? '安全兼容 (裂解型)' : '含潜在风险标记'

  return {
    s1, s2, name1, name2,
    ani: ani.toFixed(1),
    genomeDivergence,
    functionDivergence,
    receptorDivergence,
    receptorClass,
    tailIdent: tailSim.toFixed(0),
    safetyStatus
  }
})

// 加载系统内可用样本
async function loadAvailableSamples() {
  isLoadingSamples.value = true
  errorMessage.value = null
  try {
    const bridge = getBridge()
    const res = await bridge.get_pan_genomics_samples()
    if (res?.success && Array.isArray(res.data)) {
      availableSamples.value = res.data.map((item: any) => ({
        sample_id: item.sample_id,
        sample_name: item.sample_name,
        source_type: 'task',
        task_id: item.sample_id,
        cds_count: item.cds_count,
        annotated_count: item.annotated_count,
        sample_type: item.sample_type || 'PHAGE'
      }))

      // 默认选中前 5 个（若存在）
      if (selectedSamples.value.length === 0 && availableSamples.value.length >= 2) {
        selectedSamples.value = availableSamples.value.slice(0, 5)
      }
    }
  } catch (err: any) {
    console.error('加载样本列表失败:', err)
  } finally {
    isLoadingSamples.value = false
  }
}

// 导入外部文件
async function handleImportExternal() {
  try {
    const bridge = getBridge()
    const paths = bridge.request_file_load 
      ? await bridge.request_file_load('annotation', true)
      : (await bridge.show_open_dialog?.({ fileType: 'annotation', multiple: true }))?.filePaths

    if (paths && paths.length > 0) {
      for (const fp of paths) {
        const fname = fp.split(/[\\/]/).pop() || 'External_Sample'
        const ext = fname.split('.').pop()?.toLowerCase() || 'gbk'
        const newSample: BatchSampleItem = {
          sample_id: `EXT_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          sample_name: fname.replace(/\.[^/.]+$/, ''),
          source_type: 'external_file',
          file_path: fp,
          file_type: ext,
          sample_type: 'EXTERNAL'
        }
        availableSamples.value.unshift(newSample)
        selectedSamples.value.push(newSample)
      }
    }
  } catch (err: any) {
    console.error('导入外部文件失败:', err)
  }
}

// 提交分析
async function handleRunPanGenomics() {
  if (selectedSamples.value.length < 2) {
    errorMessage.value = '请至少选择 2 个样本进行比较基因组学分析'
    return
  }

  isRunning.value = true
  errorMessage.value = null
  analysisResult.value = null
  selectedPair.value = null

  try {
    const bridge = getBridge()
    const payload = {
      samples: selectedSamples.value.map(s => ({
        sample_id: s.sample_id,
        sample_name: s.sample_name,
        source_type: s.source_type,
        task_id: s.task_id,
        file_path: s.file_path,
        file_type: s.file_type
      })),
      identity_threshold: identityThreshold.value,
      coverage_threshold: 0.5
    }

    const res = await bridge.run_pan_genomics(payload)
    if (res?.success && res.data) {
      analysisResult.value = res.data
      
      // 默认选择前两个样本作为初始对比对
      const ids = Object.keys(res.data.sample_names || {})
      const id0 = ids[0]
      const id1 = ids[1]
      if (id0 && id1) {
        selectedPair.value = [id0, id1]
      }
    } else {
      errorMessage.value = res?.message || '计算引擎未返回有效分析数据'
    }
  } catch (err: any) {
    errorMessage.value = `分析计算异常: ${err?.message || err}`
  } finally {
    isRunning.value = false
  }
}

// 选择样本对事件
function handleSelectPair(pair: [string, string]) {
  selectedPair.value = pair
}

// 选择单个样本事件 (将其与现有样本或第一样本配对)
function handleSelectSample(sampleId: string) {
  if (selectedPair.value && selectedPair.value[0]) {
    selectedPair.value = [selectedPair.value[0], sampleId]
  } else {
    const ids = Object.keys(analysisResult.value?.sample_names || {})
    const other = ids.find(id => id !== sampleId) || ids[0] || sampleId
    selectedPair.value = [sampleId, other]
  }
}

// 快速选择默认前两株
function handleSelectDefaultPair() {
  const ids = Object.keys(analysisResult.value?.sample_names || {})
  if (ids.length >= 2 && ids[0] && ids[1]) {
    selectedPair.value = [ids[0], ids[1]]
  }
}

// 轮换切换至下一对样本
function handleCyclePair() {
  const ids = Object.keys(analysisResult.value?.sample_names || {})
  if (ids.length < 2) return
  if (!selectedPair.value) {
    handleSelectDefaultPair()
    return
  }
  const [s1, s2] = selectedPair.value
  const idx1 = ids.indexOf(s1)
  const idx2 = ids.indexOf(s2)
  const nextIdx2 = (idx2 + 1) % ids.length
  if (nextIdx2 !== idx1 && ids[nextIdx2]) {
    selectedPair.value = [s1, ids[nextIdx2]!]
  } else {
    const nextIdx1 = (idx1 + 1) % ids.length
    const other = ids[(nextIdx1 + 1) % ids.length] || ids[0]!
    selectedPair.value = [ids[nextIdx1]!, other]
  }
}

// 导出正交矩阵 CSV
function handleExportCsv() {
  if (!analysisResult.value?.task_id) return
  const apiBase =
    typeof window !== 'undefined' && window.location.port !== '5173' && window.location.origin
      ? window.location.origin
      : 'http://127.0.0.1:8765'
  window.open(`${apiBase}/api/analysis/pan_genomics/${analysisResult.value.task_id}/export/csv`)
}

onMounted(() => {
  loadAvailableSamples()
})
</script>

<template>
  <div class="comparative-genomics-workspace">
    <!-- 顶部样本挑选与控制台 -->
    <div class="control-panel-card">
      <div class="panel-top-row">
        <div class="panel-title-area">
          <div class="main-title">比较基因组学分析工作区 (Comparative Genomics Workspace)</div>
          <div class="main-subtitle">
            问题驱动的五步科研证据链：从宏观演化分群 → 泛基因组构成 → 宿主与裂解策略分化 → 空间共线性构型 → 生物学机制与决策。
          </div>
        </div>
      </div>

      <!-- 高通量样本选择工作台 -->
      <BatchSampleSelector
        v-model="selectedSamples"
        :available-samples="availableSamples"
        v-model:identity-threshold="identityThreshold"
        :is-running="isRunning"
        run-button-text="开始全景比较分析"
        :min-selection="2"
        @import="handleImportExternal"
        @run="handleRunPanGenomics"
      />

      <!-- 报错提示 -->
      <div class="error-banner" v-if="errorMessage">
        {{ errorMessage }}
      </div>
    </div>

    <!-- 全局持久化对比上下文提示条 (Persistent Comparison Context - 第二导航层) -->
    <!-- 状态 A: 未选中样本对 -->
    <div class="persistent-context-bar state-inactive" v-if="analysisResult && !pairSummary">
      <div class="context-left">
        <span class="context-tag tag-gray">未选定对比配对</span>
        <span class="context-tip-main">
          未锁定对比样本对。在下方任意视图（Q1 树/热图/解耦散点、Q3 网络、Q5 看板）中点击任意样本，即可启动全工作区联动深度对比。
        </span>
      </div>
      <div class="context-right">
        <button class="btn-quick-pair" @click="handleSelectDefaultPair">快速选择默认样本对</button>
      </div>
    </div>

    <!-- 状态 B: 已锁定样本对 -->
    <div class="persistent-context-bar state-active" v-else-if="analysisResult && pairSummary">
      <div class="context-left">
        <span class="context-tag tag-blue">当前聚焦对比</span>
        <div class="context-pair-names">
          <strong>{{ pairSummary.name1 }}</strong>
          <span class="context-vs">↔</span>
          <strong>{{ pairSummary.name2 }}</strong>
        </div>
        <div class="context-metrics">
          <span class="c-metric"><strong>基因组演化:</strong> {{ pairSummary.genomeDivergence }} (ANI {{ pairSummary.ani }}%)</span>
          <span class="c-metric"><strong>功能谱:</strong> {{ pairSummary.functionDivergence }}</span>
          <span class="c-metric" :class="pairSummary.receptorClass"><strong>受体识别区:</strong> {{ pairSummary.receptorDivergence }} (Tail {{ pairSummary.tailIdent }}%)</span>
          <span class="c-metric c-green"><strong>安全性:</strong> {{ pairSummary.safetyStatus }}</span>
        </div>
      </div>
      <div class="context-right">
        <button class="btn-cycle-pair" @click="handleCyclePair" title="轮换至下一对样本">切换对比对</button>
        <button class="btn-clear-pair" @click="selectedPair = null">清除聚焦</button>
      </div>
    </div>

    <!-- 分析结果工作区 (5 大问题驱动 Workspace) -->
    <div class="results-workspace" v-if="analysisResult">
      <!-- 5 大 Workspace 导航栏 -->
      <div class="workspaces-nav-bar">
        <div class="workspaces-list">
          <button 
            :class="['ws-tab-btn', { active: activeWorkspace === 'population' }]" 
            @click="activeWorkspace = 'population'"
          >
            <span class="step-num">Q1</span>
            <span class="ws-name">进化全景图 (Population)</span>
          </button>
          <button 
            :class="['ws-tab-btn', { active: activeWorkspace === 'pangenome' }]" 
            @click="activeWorkspace = 'pangenome'"
          >
            <span class="step-num">Q2</span>
            <span class="ws-name">克隆去重与优选 (De-redundancy)</span>
          </button>
          <button 
            :class="['ws-tab-btn', { active: activeWorkspace === 'functional' }]" 
            @click="activeWorkspace = 'functional'"
          >
            <span class="step-num">Q3</span>
            <span class="ws-name">功能策略分化 (Divergence)</span>
          </button>
          <button 
            :class="['ws-tab-btn', { active: activeWorkspace === 'genome' }]" 
            @click="activeWorkspace = 'genome'"
          >
            <span class="step-num">Q4</span>
            <span class="ws-name">空间共线性 (Synteny)</span>
          </button>
          <button 
            :class="['ws-tab-btn', { active: activeWorkspace === 'biological' }]" 
            @click="activeWorkspace = 'biological'"
          >
            <span class="step-num">Q5</span>
            <span class="ws-name">综合生物学决策 (Interpretation)</span>
          </button>
        </div>

        <button class="btn-export-csv" @click="handleExportCsv">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导出正交矩阵 CSV
        </button>
      </div>

      <!-- Workspace 视图视口 -->
      <div class="workspace-viewport">
        <!-- Q1: Population Landscape -->
        <WorkspacePopulationLandscape 
          v-if="activeWorkspace === 'population'"
          :ani-matrix="analysisResult.ani_matrix"
          :ani-clustering="analysisResult.ani_clustering"
          :sample-names="analysisResult.sample_names"
          :tail-matrix="analysisResult.tail_identity_matrix"
          :lysis-matrix="analysisResult.lysis_identity_matrix"
          :clusters="analysisResult.clusters"
          :lifestyles="analysisResult.lifestyles"
          :arms-race-matrix="analysisResult.arms_race_matrix"
          :selected-pair="selectedPair"
          @select-pair="handleSelectPair"
          @select-sample="handleSelectSample"
        />

        <!-- Q2: Clonal De-redundancy & Cocktail Pruning -->
        <WorkspaceCocktailDeRedundancy 
          v-else-if="activeWorkspace === 'pangenome'"
          :ani-matrix="analysisResult.ani_matrix"
          :tail-matrix="analysisResult.tail_identity_matrix"
          :lysis-matrix="analysisResult.lysis_identity_matrix"
          :clusters="analysisResult.clusters"
          :lifestyles="analysisResult.lifestyles"
          :arms-race-matrix="analysisResult.arms_race_matrix"
          :sample-names="analysisResult.sample_names"
          :selected-pair="selectedPair"
          @select-sample="handleSelectSample"
          @select-pair="handleSelectPair"
        />

        <!-- Q3: Functional Divergence -->
        <WorkspaceFunctionalDivergence 
          v-else-if="activeWorkspace === 'functional'"
          :category-distributions="analysisResult.category_distributions"
          :tail-matrix="analysisResult.tail_identity_matrix"
          :tail-clustering="analysisResult.tail_clustering"
          :ani-matrix="analysisResult.ani_matrix"
          :ani-clustering="analysisResult.ani_clustering"
          :host-range-prediction="analysisResult.host_range_prediction"
          :sample-names="analysisResult.sample_names"
          :selected-pair="selectedPair"
          @select-pair="handleSelectPair"
          @select-sample="handleSelectSample"
        />

        <!-- Q4: Genome Architecture -->
        <WorkspaceGenomeArchitecture 
          v-else-if="activeWorkspace === 'genome'"
          :clusters="analysisResult.clusters"
          :tail-proteins="analysisResult.tail_proteins"
          :lysis-proteins="analysisResult.lysis_proteins"
          :lysis-matrix="analysisResult.lysis_identity_matrix"
          :sample-names="analysisResult.sample_names"
          :selected-pair="selectedPair"
        />

        <!-- Q5: Biological Interpretation -->
        <WorkspaceBiologicalInterpretation 
          v-else-if="activeWorkspace === 'biological'"
          :lifestyles="analysisResult.lifestyles"
          :arms-race-matrix="analysisResult.arms_race_matrix"
          :tail-matrix="analysisResult.tail_identity_matrix"
          :lysis-matrix="analysisResult.lysis_identity_matrix"
          :ani-matrix="analysisResult.ani_matrix"
          :clusters="analysisResult.clusters"
          :amg-genes="analysisResult.amg_genes"
          :amg-pathway-distributions="analysisResult.amg_pathway_distributions"
          :scientific-synthesis-report="analysisResult.scientific_synthesis_report"
          :sample-names="analysisResult.sample_names"
          :selected-pair="selectedPair"
          @select-pair="handleSelectPair"
          @select-sample="handleSelectSample"
        />
      </div>
    </div>

    <!-- 初始待运行占位提示 -->
    <div class="init-placeholder-card" v-else-if="!isRunning">
      <div class="ph-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      </div>
      <h3>请选择 2 个及以上噬菌体样本，启动比较基因组学分析</h3>
    </div>
  </div>
</template>

<style scoped>
.comparative-genomics-workspace {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 控制台卡片 */
.control-panel-card {
  background: #ffffff;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  padding: 16px 20px;
}

.panel-top-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}

.main-title {
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.main-subtitle {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}

.error-banner {
  margin-top: 10px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 6px;
}

/* 全局持久化对比上下文提示条 (第二导航层) */
.persistent-context-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  transition: all 0.2s ease;
}

.persistent-context-bar.state-active {
  background: #0f172a;
  color: #ffffff;
}

.persistent-context-bar.state-inactive {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  color: #334155;
}

.context-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.context-tag {
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
}

.tag-blue {
  background: #2563eb;
  color: #ffffff;
}

.tag-gray {
  background: #e2e8f0;
  color: #475569;
}

.context-tip-main {
  font-size: 12px;
  color: #64748b;
}

.context-pair-names {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
}

.context-vs {
  color: #94a3b8;
  font-size: 11px;
}

.context-metrics {
  display: flex;
  gap: 12px;
  font-size: 11px;
}

.c-metric {
  background: rgba(255, 255, 255, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

.c-amber {
  background: rgba(245, 158, 11, 0.2);
  color: #fde68a;
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.c-green {
  background: rgba(16, 185, 129, 0.2);
  color: #a7f3d0;
}

.context-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-quick-pair {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #0f172a;
  font-size: 11px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-quick-pair:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-cycle-pair {
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-cycle-pair:hover {
  background: rgba(255, 255, 255, 0.25);
}

.btn-clear-pair {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-clear-pair:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  border-color: rgba(239, 68, 68, 0.4);
}

/* 结果工作区 */
.results-workspace {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.workspaces-nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  padding: 6px 12px;
}

.workspaces-list {
  display: flex;
  gap: 6px;
}

.ws-tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.step-num {
  background: #f1f5f9;
  color: #475569;
  font-size: 10px;
  font-weight: 800;
  padding: 2px 5px;
  border-radius: 4px;
}

.ws-tab-btn:hover {
  color: #0f172a;
  background: #f8fafc;
}

.ws-tab-btn.active {
  color: #2563eb;
  background: #eff6ff;
}

.ws-tab-btn.active .step-num {
  background: #2563eb;
  color: #ffffff;
}

.btn-export-csv {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
}

.btn-export-csv:hover {
  background: #ffffff;
  border-color: #94a3b8;
}

/* 占位卡片 */
.init-placeholder-card {
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  padding: 60px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.init-placeholder-card h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #334155;
}

.init-placeholder-card p {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
  max-width: 500px;
}
</style>
