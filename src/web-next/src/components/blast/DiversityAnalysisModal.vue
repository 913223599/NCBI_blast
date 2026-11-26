<script setup lang="ts">
/**
 * DiversityAnalysisModal.vue - 16S 扩增子混样多样性还原与 rrnDB 拷贝数归一化分析面板（薄编排外壳）
 * 核心状态机见 ./diversity/useDiversityModal.ts；
 * 各视图区块已拆解至 ./diversity/{DiversityChartTab,DiversityTaxaTab,DiversityMatrixTab,DiversityGroupModal,DiversityHistoryDrawer}.vue。
 */
import { reactive } from 'vue'
import UniversalUpload from '../common/UniversalUpload.vue'
import { useI18n } from '../../locales'
import { useDiversityModal } from './diversity/useDiversityModal'
import DiversityChartTab from './diversity/DiversityChartTab.vue'
import DiversityTaxaTab from './diversity/DiversityTaxaTab.vue'
import DiversityMatrixTab from './diversity/DiversityMatrixTab.vue'
import DiversityGroupModal from './diversity/DiversityGroupModal.vue'
import DiversityHistoryDrawer from './diversity/DiversityHistoryDrawer.vue'

export type { SampleGroupDef } from './diversity/diversityHelpers'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    initialFilePath?: string
    embedded?: boolean
  }>(),
  {
    modelValue: true,
    embedded: false,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
  (e: 'switchToIsolate'): void
  (e: 'taskChanged', taskId: string): void
}>()

const modal = useDiversityModal(props, emit)
const state = reactive(modal)

function applyGroupRules() {
  state.isGroupView = true
  state.showGroupModal = false
}

defineExpose({
  toggleHistoryDrawer: modal.toggleHistoryDrawer,
  startAnalysis: modal.startAnalysis,
  resetToNewAnalysis: modal.resetToNewAnalysis,
  selectHistoryTask: modal.selectHistoryTask,
  fetchHistoryTasks: modal.fetchHistoryTasks,
  taskId: modal.taskId,
  results: modal.results,
})
</script>

<template>
  <div
    v-if="embedded || modelValue"
    :class="[embedded ? 'diversity-embedded-container' : 'modal-overlay']"
    @click.self="!embedded && modal.close()"
  >
    <div class="modal-container-neo" :class="{ 'is-embedded': embedded }">
      <div class="modal-header-neo">
        <div class="header-left">
          <div class="icon-wrap">
            <svg class="header-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7c3 0 5 5 8 5s5-5 8-5M4 17c3 0 5-5 8-5s5 5 8 5M7 8.5v7M17 8.5v7" />
            </svg>
          </div>
          <div>
            <h2 class="title">{{ t('blast.diversity_modal.title') }}</h2>
            <p class="subtitle">{{ t('blast.diversity_modal.subtitle') }}</p>
          </div>
        </div>
        <div class="header-right">
          <button
            type="button"
            v-if="state.results && !state.isRunning"
            class="btn-tool-neo"
            @click="modal.resetToNewAnalysis()"
            :title="t('blast.diversity_modal.new_title')"
          >
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            <span>{{ t('blast.diversity_modal.new_btn') }}</span>
          </button>

          <button
            type="button"
            class="btn-tool-neo"
            :class="{ active: state.showHistoryDrawer }"
            @click="modal.toggleHistoryDrawer()"
            :title="t('blast.diversity_modal.history_title')"
          >
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <circle cx="12" cy="12" r="9" stroke-width="2" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 7v5l3 3" />
            </svg>
            <span>{{ t('blast.diversity_modal.history_btn', { count: state.historyTasks.length }) }}</span>
          </button>

          <button
            type="button"
            v-if="state.results && !state.isRunning"
            class="btn-tool-neo"
            :class="{ 'is-loading': state.isTranslating }"
            @click="modal.translateAllTaxa()"
            :title="t('blast.diversity_modal.translate_title')"
          >
            <svg class="btn-icon-svg" :class="{ 'spin-anim': state.isTranslating }" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
            </svg>
            <span>{{ state.isTranslating ? t('blast.diversity_modal.translating') : t('blast.diversity_modal.translate_btn') }}</span>
          </button>

          <button type="button" v-if="state.results" class="btn-export-neo" @click="modal.exportExcel()">
            <svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>{{ t('blast.diversity_modal.export_excel') }}</span>
          </button>

          <button type="button" v-if="!embedded" class="btn-close-neo" @click="modal.close()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <!-- 载入与控制区 -->
      <div v-if="!state.results && !state.isRunning" class="import-section-neo">
        <div class="upload-box-wrapper">
          <UniversalUpload
            type="fasta"
            accept=".zip,.fastq,.fastq.gz"
            :label="t('blast.diversity_modal.upload_label')"
            @success="modal.handleUploadSuccess"
          />
        </div>

        <div v-if="state.detectedPackage" class="detect-badge-card">
          <div class="badge-status-tag">{{ t('blast.diversity_modal.detected_badge') }}</div>
          <div class="detect-info">
            <span class="name">{{ state.detectedPackage.file_name }}</span>
            <span class="desc">
              {{ t('blast.diversity_modal.detected_desc', { count: state.detectedPackage.fastq_count }) }}
            </span>
          </div>
          <button type="button" class="btn-start-action" @click="modal.startAnalysis()">
            {{ t('blast.diversity_modal.start_now') }}
          </button>
        </div>
        <div v-else-if="state.currentFilePath" class="fallback-launch">
          <button type="button" class="btn-start-action" @click="modal.startAnalysis()">
            {{ t('blast.diversity_modal.start_file') }}
          </button>
        </div>

        <div v-if="!state.detectedPackage && state.historyTasks.length > 0" class="recent-history-section">
          <div class="recent-header">
            <span class="recent-title">{{ t('blast.diversity_modal.recent_title') }}</span>
            <button type="button" class="recent-all-btn" @click="state.showHistoryDrawer = true">
              {{ t('blast.diversity_modal.view_all_history', { count: state.historyTasks.length }) }}
            </button>
          </div>
          <div class="recent-task-grid">
            <div
              v-for="task in state.historyTasks.slice(0, 3)"
              :key="task.task_id"
              class="recent-task-item"
              role="button"
              tabindex="0"
              @click="modal.selectHistoryTask(task)"
              @keydown.enter.prevent="modal.selectHistoryTask(task)"
              @keydown.space.prevent="modal.selectHistoryTask(task)"
            >
              <div class="recent-item-top">
                <span class="item-name" :title="task.task_name">{{ task.task_name }}</span>
                <span class="item-status" :class="task.status">{{ modal.getStatusLabel(task.status) }}</span>
              </div>
              <div class="recent-item-meta">
                <span>{{ modal.formatTime(task.completed_at || task.created_at) }}</span>
                <span>{{ task.total_samples }} · {{ modal.formatReadsCount(task.total_reads) }} Reads</span>
              </div>
              <div class="recent-item-actions">
                <button
                  type="button"
                  class="btn-item-del"
                  :title="t('blast.diversity_modal.delete_task_title')"
                  @click.stop="modal.deleteHistoryTask(task, $event)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 运行进度展示 -->
      <div v-if="state.isRunning" class="progress-section-neo">
        <div class="progress-card-neo">
          <div class="pulse-icon-svg">
            <svg class="exec-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div class="progress-info">
            <div class="step-text">{{ state.currentStep }}</div>
            <div class="sample-hint" v-if="state.currentSample">
              正在处理点位: <strong>{{ state.currentSample }}</strong>
            </div>
          </div>
          <div class="progress-bar-wrap">
            <div class="bar-fill" :style="{ width: `${state.progress}%` }"></div>
          </div>
          <div class="progress-meta-row">
            <div class="progress-percent-val">{{ state.progress }}%</div>
            <div class="progress-counter-badge" v-if="state.totalReads > 0">
              <span class="counter-label">序列比对:</span>
              <span class="counter-num">{{ state.processedReads.toLocaleString() }} / {{ state.totalReads.toLocaleString() }} Reads</span>
            </div>
            <div class="progress-counter-badge samples-badge" v-if="state.totalSamples > 0">
              <span class="counter-label">样本点位:</span>
              <span class="counter-num">{{ state.processedSamples }} / {{ state.totalSamples }}</span>
            </div>
          </div>
          <div class="checkpoint-tip">
            <svg class="shield-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 1.944A11.954 11.954 0 012.166 5C2.056 5.649 2 6.319 2 7c0 5.225 3.34 9.67 8 11.317C14.66 16.67 18 12.225 18 7c0-.682-.057-1.35-.166-2.001A11.954 11.954 0 0110 1.944zM11 14a1 1 0 11-2 0 1 1 0 012 0zm0-7a1 1 0 10-2 0v3a1 1 0 102 0V7z" clip-rule="evenodd" />
            </svg>
            <span>分片落盘与断点保护 (Checkpoint) 生效中，防止大规模数据 OOM 崩溃</span>
          </div>
        </div>
      </div>

      <!-- 分析结果面板 -->
      <div v-if="state.results" class="results-dashboard-neo">
        <div class="stats-overview-bar">
          <div class="stat-pill-group">
            <div class="stat-pill stat-pill-primary">
              <span class="label">{{ state.isGroupView ? '当前展示分组:' : '测序点位数:' }}</span>
              <span class="val">{{ state.activeSamples.length }} {{ state.isGroupView ? '个聚合组' : '个采样点' }}</span>
              <span v-if="state.isGroupView" class="sub-label">(覆盖 {{ state.results?.total_samples || 0 }} 个测序点)</span>
            </div>
            <div class="stat-pill">
              <span class="label">有效 Reads:</span>
              <span class="val">{{ (state.results?.total_classified_reads ?? state.results?.total_reads ?? 0).toLocaleString() }} 条</span>
            </div>
            <div class="stat-pill">
              <span class="label">确证菌种:</span>
              <span class="val">{{ state.confirmedSpeciesCount }} 种</span>
            </div>
            <div class="stat-pill pill-rrndb" title="基于 rrnDB v5.10 消除 16S 多拷贝菌株的丰度假阳性放大，还原真实细胞丰度">
              <svg class="pill-shield-svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 1.944A11.954 11.954 0 012.166 5C2.056 5.649 2 6.319 2 7c0 5.225 3.34 9.67 8 11.317C14.66 16.67 18 12.225 18 7c0-.682-.057-1.35-.166-2.001A11.954 11.954 0 0110 1.944zM11 14a1 1 0 11-2 0 1 1 0 012 0zm0-7a1 1 0 10-2 0v3a1 1 0 102 0V7z" clip-rule="evenodd" />
              </svg>
              <span class="label">校正状态:</span>
              <span class="val">rrnDB v5.10 已归一化</span>
            </div>
            <div
              v-if="state.results?.qc_summary"
              class="stat-pill pill-qc"
              :title="`前置质控过滤: 原始 ${state.results.qc_summary.total_raw_reads} 条，剔除 ${state.results.qc_summary.total_dropped_reads} 条异常读段 (读长/质量值未达标)`"
            >
              <svg class="pill-shield-svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
              </svg>
              <span class="label">测序质控 (QC):</span>
              <span class="val">{{ state.results.qc_summary.overall_pass_rate_pct }}% 通过</span>
            </div>
          </div>

          <div class="group-control-bar">
            <button
              type="button"
              class="group-toggle-btn"
              :class="{ active: state.isGroupView }"
              @click="state.isGroupView = !state.isGroupView"
              :title="state.isGroupView ? '点击切换回原始各个采样点位视图' : '点击按规则合并点位（如 1-5 为一组）'"
            >
              <svg class="group-svg" viewBox="0 0 20 20" fill="currentColor">
                <path d="M7 3a1 1 0 000 2h6a1 1 0 100-2H7zM4 7a1 1 0 011-1h10a1 1 0 110 2H5a1 1 0 01-1-1zM2 11a2 2 0 012-2h12a2 2 0 012 2v4a2 2 0 01-2 2H4a2 2 0 01-2-2v-4z" />
              </svg>
              <span>{{ state.isGroupView ? '分组聚合模式 (已启用)' : '合并样本点位' }}</span>
              <span v-if="state.isGroupView" class="btn-group-counter">{{ state.activeSamples.length }} 组</span>
            </button>
            <button
              type="button"
              class="group-config-btn"
              @click="state.showGroupModal = true"
              title="配置合并分组规则 (例如 1-5 合并为对照组，6-9 合并为实验组)"
            >
              <svg class="group-svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M11.49 3.17c-.38-1.56-2.6-1.56-2.98 0a1.532 1.532 0 01-2.286.948c-1.372-.836-2.942.734-2.106 2.106.54.886.061 2.042-.947 2.287-1.561.379-1.561 2.6 0 2.978a1.532 1.532 0 01.947 2.287c-.836 1.372.734 2.942 2.106 2.106a1.532 1.532 0 012.287.947c.379 1.561 2.6 1.561 2.978 0a1.533 1.533 0 012.287-.947c1.372.836 2.942-.734 2.106-2.106a1.533 1.533 0 01.947-2.287c1.561-.379 1.561-2.6 0-2.978a1.532 1.532 0 01-.947-2.287c.836-1.372-.734-2.942-2.106-2.106a1.532 1.532 0 01-2.287-.947zM10 13a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd" />
              </svg>
              <span>分组规则 ({{ state.sampleGroups.length }})</span>
            </button>
          </div>

          <div class="abundance-mode-toggle">
            <button
              type="button"
              class="toggle-btn"
              :class="{ active: state.abundanceMode === 'norm' }"
              @click="state.abundanceMode = 'norm'"
              title="消除 16S 基因拷贝数偏好，真实还原微生物细胞相对丰度"
            >
              rrnDB 拷贝数归一化丰度
            </button>
            <button
              type="button"
              class="toggle-btn"
              :class="{ active: state.abundanceMode === 'raw' }"
              @click="state.abundanceMode = 'raw'"
              title="原始测序下机 Reads 物理计数占比"
            >
              原始 Reads 占比
            </button>
          </div>
        </div>

        <div class="sub-tabs-neo">
          <button type="button" class="tab-item" :class="{ active: state.activeTab === 'chart' }" @click="state.activeTab = 'chart'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span>物种丰度分布图</span>
          </button>
          <button type="button" class="tab-item" :class="{ active: state.activeTab === 'taxa' }" @click="state.activeTab = 'taxa'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <span>检出物种总览与排行榜 (有什么菌)</span>
          </button>
          <button type="button" class="tab-item" :class="{ active: state.activeTab === 'matrix' }" @click="state.activeTab = 'matrix'">
            <svg class="tab-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M3 14h18m-9-4v8m-7 4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span>样本 / 分组明细大表</span>
          </button>
        </div>

        <DiversityChartTab
          v-show="state.activeTab === 'chart'"
          :is-group-view="state.isGroupView"
          :active-sample-count="state.activeSamples.length"
          :top-taxa-count="state.topTaxaCount"
          :top-taxa-list="state.topTaxaList"
          :stacked-bar-data="state.stackedBarData"
          :get-taxon-color="modal.getTaxonColor"
          @update:top-taxa-count="state.topTaxaCount = $event"
          @show-tooltip="modal.showSegmentTooltip"
          @hide-tooltip="modal.hideTooltip"
        />

        <DiversityTaxaTab
          v-show="state.activeTab === 'taxa'"
          :taxa-search-query="state.taxaSearchQuery"
          :confirmed-species-count="state.confirmedSpeciesCount"
          :filtered-taxa-overview="state.filteredTaxaOverview"
          :is-noise-taxon="modal.isNoiseTaxon"
          :get-real-taxon-rank="modal.getRealTaxonRank"
          :get-taxon-color="modal.getTaxonColor"
          :get-taxon-zh="modal.getTaxonZh"
          @update:taxa-search-query="state.taxaSearchQuery = $event"
          @export-excel="modal.exportExcel()"
        />

        <DiversityMatrixTab
          v-show="state.activeTab === 'matrix'"
          :detail-search-query="state.detailSearchQuery"
          :detail-view-mode="state.detailViewMode"
          :is-group-view="state.isGroupView"
          :abundance-mode="state.abundanceMode"
          :active-sample-count="state.activeSamples.length"
          :filtered-active-samples="state.filteredActiveSamples"
          :is-sample-collapsed="modal.isSampleCollapsed"
          :get-dominant-taxon="modal.getDominantTaxon"
          :get-taxon-color="modal.getTaxonColor"
          :get-taxon-zh="modal.getTaxonZh"
          :is-noise-taxon="modal.isNoiseTaxon"
          :format-pct="modal.formatPct"
          @update:detail-search-query="state.detailSearchQuery = $event"
          @update:detail-view-mode="state.detailViewMode = $event"
          @toggle-sample-collapse="modal.toggleSampleCollapse"
          @expand-all-samples="modal.expandAllSamples()"
          @collapse-all-samples="modal.collapseAllSamples()"
        />
      </div>

      <DiversityGroupModal
        :visible="state.showGroupModal"
        :group-chunk-size="state.groupChunkSize"
        :all-sample-names="state.allSampleNames"
        :sample-groups="state.sampleGroups"
        :unassigned-samples="state.unassignedSamples"
        :parse-sample-pattern="modal.parseSamplePattern"
        @close="state.showGroupModal = false"
        @apply="applyGroupRules"
        @update:group-chunk-size="state.groupChunkSize = $event"
        @generate-consecutive-groups="modal.generateConsecutiveGroups"
        @set-chunk-size-and-generate="modal.setChunkSizeAndGenerate"
        @add-group="modal.addGroup()"
        @remove-group="modal.removeGroup"
        @clear-all-groups="modal.clearAllGroups()"
      />

      <div
        v-if="state.tooltip.visible"
        class="floating-tooltip"
        :style="{ left: `${state.tooltip.x}px`, top: `${state.tooltip.y}px` }"
      >
        <div class="tt-sample">{{ state.tooltip.sample }}</div>
        <div class="tt-taxon">{{ state.tooltip.taxon }}</div>
        <div class="tt-divider"></div>
        <div class="tt-row">
          <span>原始 Reads:</span>
          <strong>{{ state.tooltip.rawCount }} 条 ({{ state.tooltip.rawPct }}%)</strong>
        </div>
        <div class="tt-row">
          <span>16S 基因拷贝数 (GCN):</span>
          <strong>{{ state.tooltip.gcn }}</strong>
        </div>
        <div class="tt-row tt-highlight">
          <span>rrnDB 校正相对丰度:</span>
          <strong>{{ state.tooltip.normPct }}%</strong>
        </div>
      </div>

      <DiversityHistoryDrawer
        :visible="state.showHistoryDrawer"
        :is-loading-history="state.isLoadingHistory"
        :history-tasks="state.historyTasks"
        :active-task-id="state.taskId"
        :format-time="modal.formatTime"
        :format-reads-count="modal.formatReadsCount"
        :get-status-label="modal.getStatusLabel"
        @close="state.showHistoryDrawer = false"
        @select-task="modal.selectHistoryTask"
        @delete-task="modal.deleteHistoryTask"
        @clear-all-history="modal.clearAllHistory()"
      />
    </div>
  </div>
</template>

<style scoped src="./diversity/styles/shell.css"></style>
