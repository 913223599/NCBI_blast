<script setup lang="ts">
import ContigSelector from '../../annotation/components/ContigSelector.vue'
import type {
  StructureBatchRunPayload,
  StructureCapabilities,
  StructureInitialPayload,
  StructureInspectContig,
  StructureLinkedSources,
  StructureRunForm,
  StructureSourceMode,
} from '../types'
import { formatGenomeBp } from '../utils'
import { useStructureSetup } from '../composables/useStructureSetup'

const props = defineProps<{
  capabilities: StructureCapabilities | null
  linkedSources: StructureLinkedSources
  isCapabilitiesLoading: boolean
  isSourcesLoading: boolean
  isInspecting: boolean
  isSubmitting: boolean
  isQueueBusy: boolean
  inspectedContigs: StructureInspectContig[]
  inspectTotalBp: number
  initialPayload?: StructureInitialPayload | null
}>()

const emit = defineEmits<{
  (e: 'submit', form: StructureRunForm): void
  (e: 'submit-batch', payload: StructureBatchRunPayload): void
  (
    e: 'inspect',
    payload: {
      source_mode: StructureSourceMode
      fasta_path?: string
      fasta_content?: string
      source_task_id?: string
      region_index?: number
    }
  ): void
  (e: 'refresh-sources'): void
}>()

const {
  uiTab,
  uploadedFileName,
  isUploading,
  isDragging,
  showAdvanced,
  fileInputRef,
  uploadNotice,
  batchFiles,
  selectedAnnotationIds,
  selectedDiscoveryIds,
  splitPhageRegions,
  splitFastaRecords,
  form,
  overallGcPercent,
  selectorContigs,
  pastedRecordCount,
  canSplitPastedFasta,
  selectedDiscoveryTotalRegions,
  isBatchSubmission,
  plannedTaskCount,
  canSubmit,
  switchTab,
  triggerFileSelect,
  removeBatchFile,
  clearBatchFiles,
  onBrowserFileChange,
  onDropFile,
  toggleAnnotationSelection,
  selectAllAnnotations,
  toggleDiscoverySelection,
  selectAllDiscoveries,
  triggerLinkedInspect,
  onSubmit,
} = useStructureSetup(props, emit)

void fileInputRef
</script>

<template>
  <div class="setup-shell">
    <div class="engine-banner">
      <div class="eb-left">
        <h3>尾部形态与结构预测</h3>
      </div>
      <div class="eb-chips">
        <span class="wb-chip" :class="capabilities?.wsl_pyhmmer_ready ? 'ok' : 'warn'">
          {{ isCapabilitiesLoading ? '检测中...' : capabilities?.wsl_pyhmmer_ready ? 'PyHMMER' : 'PyHMMER 不可用' }}
        </span>
        <span class="wb-chip" :class="capabilities?.structural_hmm_cached ? 'ok' : ''">
          {{ capabilities?.structural_hmm_cached ? 'PHROG 索引' : 'PHROG 索引待建' }}
        </span>
        <span class="wb-chip" :class="capabilities?.phagetailfinder_ready ? 'ok' : ''">
          {{ capabilities?.phagetailfinder_ready ? 'PhageTailFinder' : 'PhageTailFinder 未就绪' }}
        </span>
        <span v-if="capabilities?.phold_ready" class="wb-chip ok">Phold 3D</span>
        <span v-if="capabilities?.unified_judge_ready" class="wb-chip ok">UnifiedJudge</span>
        <span v-if="capabilities?.ai_classifier_ready" class="wb-chip ok">AI 分类器</span>
      </div>
    </div>

    <div class="wb-card setup-card">
      <div v-if="!isBatchSubmission" class="field-row">
        <label class="field-label">任务名</label>
        <input v-model="form.task_name" type="text" class="wb-input flex-1" placeholder="Phage_T4" />
      </div>

      <div class="wb-tabs-bar">
        <button type="button" class="wb-tab-btn" :class="{ active: uiTab === 'upload' }" @click="switchTab('upload')">
          文件上传
        </button>
        <button type="button" class="wb-tab-btn" :class="{ active: uiTab === 'paste' }" @click="switchTab('paste')">
          粘贴序列
        </button>
        <button type="button" class="wb-tab-btn" :class="{ active: uiTab === 'annotation' }" @click="switchTab('annotation')">
          注释导入 ({{ linkedSources.annotations.length }})
        </button>
        <button type="button" class="wb-tab-btn" :class="{ active: uiTab === 'phage_discovery' }" @click="switchTab('phage_discovery')">
          前噬菌体导入 ({{ linkedSources.phage_discoveries.length }})
        </button>
      </div>

      <div v-if="uiTab === 'upload'" class="upload-wrap">
        <input
          ref="fileInputRef"
          type="file"
          multiple
          class="hidden-file"
          accept=".fasta,.fa,.fna,.faa,.gbk,.gb,.gbff,.genbank,.gz"
          @change="onBrowserFileChange"
        />
        <div
          class="wb-drop-zone"
          :class="{ dragging: isDragging, compact: batchFiles.length > 0 }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="onDropFile"
          @click="triggerFileSelect(batchFiles.length > 0)"
        >
          <div class="drop-title">
            <template v-if="isUploading">上传中...</template>
            <template v-else-if="batchFiles.length === 1">已选: {{ uploadedFileName }}（点击追加）</template>
            <template v-else-if="batchFiles.length > 1">已导入 {{ batchFiles.length }} 个文件（点击追加）</template>
            <template v-else>点击或拖入 FASTA / GBK / FAA（可多选）</template>
          </div>
        </div>

        <div v-if="uploadNotice" class="notice-line">{{ uploadNotice }}</div>

        <div v-if="batchFiles.length === 1" class="single-file-bar">
          <span class="sf-path" :title="batchFiles[0]?.fasta_path || batchFiles[0]?.file_name">
            {{ batchFiles[0]?.format_label }} · {{ batchFiles[0]?.file_name }}
          </span>
          <div class="sf-actions">
            <button type="button" class="wb-btn-outline" @click="triggerFileSelect(true)">+ 追加</button>
            <button type="button" class="wb-btn-outline danger" @click="clearBatchFiles">移除</button>
          </div>
        </div>

        <div v-if="batchFiles.length > 1" class="batch-list-box">
          <div class="batch-list-head">
            <span>批量队列 ({{ batchFiles.length }})</span>
            <div class="sf-actions">
              <button type="button" class="wb-btn-outline" @click="triggerFileSelect(true)">+ 追加</button>
              <button type="button" class="wb-btn-outline danger" @click="clearBatchFiles">清空</button>
            </div>
          </div>
          <div class="batch-rows">
            <div v-for="(entry, idx) in batchFiles" :key="entry.id" class="batch-row">
              <span class="br-idx">#{{ idx + 1 }}</span>
              <span class="br-fmt">{{ entry.format_label }}</span>
              <input v-model="entry.task_name" type="text" class="wb-input br-name-inp" placeholder="任务名" />
              <span class="br-file" :title="entry.fasta_path || entry.file_name">{{ entry.file_name }}</span>
              <button type="button" class="br-del" title="从批次中移除" @click="removeBatchFile(entry.id)">移除</button>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="uiTab === 'paste'" class="upload-wrap">
        <textarea v-model="form.fasta_content" rows="7" class="wb-textarea" placeholder="粘贴 FASTA / FAA / GenBank 文本"></textarea>
        <label v-if="canSplitPastedFasta" class="split-banner">
          <input v-model="splitFastaRecords" type="checkbox" />
          <span>检测到 <strong>{{ pastedRecordCount }}</strong> 条序列，拆分为独立任务</span>
        </label>
      </div>

      <div v-else-if="uiTab === 'annotation'" class="wb-surface-muted linked-box">
        <div v-if="isSourcesLoading" class="empty-src">读取中...</div>
        <div v-else-if="linkedSources.annotations.length === 0" class="empty-src">无可用注释任务</div>
        <template v-else>
          <div class="linked-toolbar">
            <span>已选 {{ selectedAnnotationIds.length }} / {{ linkedSources.annotations.length }}</span>
            <button type="button" class="wb-btn-outline" @click="selectAllAnnotations">
              {{ selectedAnnotationIds.length === linkedSources.annotations.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div class="src-grid">
            <div
              v-for="a in linkedSources.annotations"
              :key="a.task_id"
              class="src-item"
              :class="{ active: selectedAnnotationIds.includes(a.task_id) }"
              @click="toggleAnnotationSelection(a.task_id)"
            >
              <div class="src-head">
                <span class="src-name">{{ a.task_name }}</span>
                <span class="chk-badge" :class="{ checked: selectedAnnotationIds.includes(a.task_id) }">
                  {{ selectedAnnotationIds.includes(a.task_id) ? '已选' : '选择' }}
                </span>
              </div>
              <div class="src-meta">{{ a.sample_type }} · {{ a.cds_count }} CDS · {{ formatGenomeBp(a.total_length) }}</div>
            </div>
          </div>
        </template>
      </div>

      <div v-else class="wb-surface-muted linked-box">
        <div v-if="isSourcesLoading" class="empty-src">读取中...</div>
        <div v-else-if="linkedSources.phage_discoveries.length === 0" class="empty-src">无前噬菌体扫描任务</div>
        <template v-else>
          <div class="linked-toolbar">
            <span>已选 {{ selectedDiscoveryIds.length }} / {{ linkedSources.phage_discoveries.length }}</span>
            <button type="button" class="wb-btn-outline" @click="selectAllDiscoveries">
              {{ selectedDiscoveryIds.length === linkedSources.phage_discoveries.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <div class="src-grid">
            <div
              v-for="p in linkedSources.phage_discoveries"
              :key="p.task_id"
              class="src-item"
              :class="{ active: selectedDiscoveryIds.includes(p.task_id) }"
              @click="toggleDiscoverySelection(p.task_id)"
            >
              <div class="src-head">
                <span class="src-name">{{ p.task_name }}</span>
                <span class="chk-badge" :class="{ checked: selectedDiscoveryIds.includes(p.task_id) }">
                  {{ selectedDiscoveryIds.includes(p.task_id) ? '已选' : '选择' }}
                </span>
              </div>
              <div class="src-meta">检出 {{ p.region_count }} 区段 · {{ formatGenomeBp(p.total_prophage_bp) }}</div>
            </div>
          </div>
          <div v-if="selectedDiscoveryIds.length > 0" class="discovery-opts">
            <label v-if="selectedDiscoveryTotalRegions > 1 && !(selectedDiscoveryIds.length === 1 && form.region_index)" class="split-banner">
              <input v-model="splitPhageRegions" type="checkbox" />
              <span>按区段拆分为 <strong>{{ selectedDiscoveryTotalRegions }}</strong> 个任务</span>
            </label>
            <div v-if="selectedDiscoveryIds.length === 1 && !splitPhageRegions" class="region-opt">
              <label>指定区段（空=全部）：</label>
              <input v-model.number="form.region_index" type="number" min="1" class="wb-input num-input" placeholder="全部" @change="triggerLinkedInspect" />
            </div>
          </div>
        </template>
      </div>

      <div v-if="!isBatchSubmission && inspectedContigs.length > 0" class="contig-box">
        <ContigSelector
          :contigs="selectorContigs"
          :total-length="inspectTotalBp"
          :overall-gc="overallGcPercent"
          @update:selection="(ids) => (form.selected_contigs = ids)"
        />
      </div>

      <div class="adv-toggle-row">
        <button type="button" class="wb-btn-link" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '收起高级参数' : '高级参数' }}
        </button>
      </div>

      <div v-if="showAdvanced" class="wb-surface-muted adv-grid">
        <div class="adv-field">
          <label>线程数</label>
          <input v-model.number="form.threads" type="number" min="1" max="64" class="wb-input" />
        </div>
        <div class="adv-field">
          <label>密码表</label>
          <select v-model.number="form.genetic_code" class="wb-select">
            <option :value="11">Table 11（标准）</option>
            <option :value="4">Table 4（支原体）</option>
          </select>
        </div>
        <div class="adv-field">
          <label>PHROG Score 下限</label>
          <input v-model.number="form.score_cutoff" type="number" min="15" max="200" step="1" class="wb-input" />
        </div>
        <div class="adv-field">
          <label>E-value 上限</label>
          <input v-model.number="form.evalue_cutoff" type="number" step="0.0001" class="wb-input" />
        </div>
        <label class="chk-row">
          <input v-model="form.force_hmm_rescan" type="checkbox" />
          <span>强制重跑 PHROG HMM</span>
        </label>
        <label class="chk-row" :class="{ disabled: !capabilities?.phagetailfinder_ready }">
          <input v-model="form.enable_phagetailfinder" type="checkbox" :disabled="!capabilities?.phagetailfinder_ready" />
          <span>PhageTailFinder 尾部识别</span>
        </label>
        <label v-if="form.enable_phagetailfinder && capabilities?.phagetailfinder_ready" class="chk-row">
          <input v-model="form.ptf_accurate_mode" type="checkbox" />
          <span>PhageTailFinder 保守模式</span>
        </label>
        <label class="chk-row" :class="{ disabled: !capabilities?.ai_classifier_ready }">
          <input v-model="form.enable_ai_classifier" type="checkbox" :disabled="!capabilities?.ai_classifier_ready" />
          <span>AI 双轨分类</span>
        </label>
        <label class="chk-row" :class="{ disabled: !capabilities?.phold_ready }">
          <input v-model="form.enable_phold_enhance" type="checkbox" :disabled="!capabilities?.phold_ready" />
          <span>Phold 3D 复核</span>
        </label>
        <div v-if="form.enable_phold_enhance && capabilities?.phold_ready" class="adv-field">
          <label>Phold 触发</label>
          <select v-model="form.phold_trigger_mode" class="wb-select">
            <option value="auto">自动（按条件）</option>
            <option value="always">全部复核</option>
            <option value="off">不执行</option>
          </select>
        </div>
      </div>

      <div class="submit-bar">
        <span v-if="isBatchSubmission" class="queue-hint batch">{{ plannedTaskCount }} 个任务待入队</span>
        <span v-else-if="isQueueBusy" class="queue-hint">有任务运行中，提交后排队</span>
        <span v-else class="queue-hint"></span>
        <button type="button" class="wb-btn-primary" :disabled="!canSubmit" @click="onSubmit">
          <template v-if="isSubmitting">提交中...</template>
          <template v-else-if="isUploading">上传中...</template>
          <template v-else-if="!isBatchSubmission && isInspecting">预检中...</template>
          <template v-else-if="isBatchSubmission">批量入队 ({{ plannedTaskCount }})</template>
          <template v-else>开始预测</template>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-shell, .upload-wrap, .linked-box, .discovery-opts { display: flex; flex-direction: column; gap: 10px; }
.engine-banner { background: linear-gradient(135deg, #f8fafc, #eff6ff); border: 1px solid #dbeafe; border-radius: 14px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.eb-left h3 { margin: 0; font-size: 0.98rem; color: #0f172a; }
.eb-chips, .sf-actions { display: flex; gap: 6px; flex-wrap: wrap; flex-shrink: 0; }
.setup-card { border-radius: 14px; padding: 14px; gap: 10px; }
.field-row { display: flex; align-items: center; gap: 8px; }
.flex-1 { flex: 1; }
.field-label { font-size: 0.84rem; font-weight: 600; color: #334155; white-space: nowrap; }
.hidden-file { display: none; }
.wb-drop-zone.compact { padding: 10px 12px; }
.drop-title { font-size: 0.86rem; font-weight: 600; color: #1e293b; }
.notice-line { font-size: 0.78rem; color: #b45309; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 6px 10px; }
.single-file-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 12px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 9px; }
.sf-path { font-size: 0.82rem; font-weight: 600; color: #1e40af; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-list-box { border: 1px solid #dbeafe; background: #f8fafc; border-radius: 11px; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.batch-list-head, .linked-toolbar, .src-head, .submit-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.batch-list-head { font-size: 0.83rem; font-weight: 700; color: #1e293b; }
.batch-rows { display: flex; flex-direction: column; gap: 7px; max-height: 250px; overflow-y: auto; }
.batch-row { display: flex; align-items: center; gap: 8px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 10px; }
.br-idx { font-family: ui-monospace, monospace; font-size: 0.76rem; font-weight: 700; color: #2563eb; min-width: 24px; }
.br-fmt { font-size: 0.7rem; font-weight: 700; padding: 1px 6px; border-radius: 999px; background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; flex-shrink: 0; }
.br-name-inp { flex: 1.1; min-width: 140px; padding: 5px 8px; font-size: 0.81rem; }
.br-file { flex: 1; font-size: 0.77rem; color: #64748b; font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.br-del { padding: 3px 8px; border-radius: 6px; border: 1px solid #fecaca; background: #fff1f2; color: #dc2626; font-size: 0.74rem; font-weight: 600; flex-shrink: 0; cursor: pointer; }
.split-banner { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 9px; background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; font-size: 0.82rem; cursor: pointer; }
.linked-toolbar { font-size: 0.8rem; color: #475569; font-weight: 600; }
.empty-src { text-align: center; color: #64748b; padding: 20px; font-size: 0.85rem; }
.src-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px; max-height: 220px; overflow-y: auto; }
.src-item { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 9px; padding: 7px 9px; cursor: pointer; }
.src-item:hover { border-color: #60a5fa; }
.src-item.active { border-color: #2563eb; background: #eff6ff; }
.src-name { font-size: 0.85rem; font-weight: 600; color: #0f172a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chk-badge { font-size: 0.7rem; font-weight: 700; padding: 1px 7px; border-radius: 999px; background: #f1f5f9; color: #64748b; flex-shrink: 0; }
.chk-badge.checked { background: #2563eb; color: #ffffff; }
.src-meta { margin-top: 3px; font-size: 0.76rem; color: #64748b; }
.region-opt { display: flex; align-items: center; gap: 10px; font-size: 0.82rem; color: #334155; }
.num-input { width: 90px; }
.adv-toggle-row { display: flex; justify-content: flex-start; }
.adv-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }
.adv-field { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: #475569; }
.chk-row { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; font-size: 0.83rem; color: #334155; cursor: pointer; }
.chk-row.disabled { color: #94a3b8; cursor: not-allowed; }
.submit-bar { padding-top: 8px; border-top: 1px solid #f1f5f9; }
.queue-hint { font-size: 0.8rem; color: #64748b; }
.queue-hint.batch { color: #1d4ed8; font-weight: 600; }
</style>
