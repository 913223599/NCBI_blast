<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from '../../../locales'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioAnnotationSourceItem, StudioPaletteType, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

const { t } = useI18n()
const appStore = useAppStore()
const annoTasks = ref<StudioAnnotationSourceItem[]>([])
const refTaskId = ref<string>('')
const compareIds = ref<string[]>([])
const fastaContent = ref<string>('')
const windowSize = ref<number>(250)
const stepSize = ref<number>(50)
const showGeneTable = ref<boolean>(true)
const palette = ref<StudioPaletteType>('nature')
const dpi = ref<number>(300)
const title = ref<string>('Genome-Wide Nucleotide Diversity (Pi) & Polymorphism Map')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

async function loadSources(): Promise<void> {
  try {
    const res = await studioApi.getSources()
    annoTasks.value = res.annotation_tasks
    if (annoTasks.value.length >= 2) {
      refTaskId.value = annoTasks.value[0]!.task_id
      compareIds.value = annoTasks.value.slice(1, 5).map((item) => item.task_id)
    }
  } catch (e) {
    appStore.showNotification(t('studio.common.load_anno_failed', { error: String(e) }), 'warning')
  }
}

function toggleCompare(taskId: string): void {
  const idx = compareIds.value.indexOf(taskId)
  if (idx >= 0) compareIds.value.splice(idx, 1)
  else compareIds.value.push(taskId)
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const isDemo =
      forceDemo ||
      (!refTaskId.value && !fastaContent.value.trim()) ||
      (!forceDemo && refTaskId.value && compareIds.value.length === 0 && !fastaContent.value.trim())
    renderResult.value = await studioApi.renderDiversity({
      ref_annotation_task_id: isDemo ? null : refTaskId.value || null,
      compare_annotation_task_ids: isDemo ? [] : compareIds.value,
      fasta_content: isDemo ? null : fastaContent.value.trim() || null,
      use_demo: Boolean(isDemo),
      window_size: windowSize.value,
      step_size: stepSize.value,
      show_gene_table: showGeneTable.value,
      palette: palette.value,
      title: title.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification(t('studio.diversity.notify_success'), 'success')
  } catch (e) {
    appStore.showNotification(t('studio.common.render_failed', { error: String(e) }), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadSources()
})
</script>

<template>
  <div class="tool-layout">
    <aside class="tool-sidebar">
      <div class="sec-head">
        <h3>{{ t('studio.diversity.title') }}</h3>
        <button type="button" class="btn-link" @click="handleRender(true)">{{ t('studio.common.load_demo') }}</button>
      </div>
      <p class="sec-desc">
        {{ t('studio.diversity.desc') }}
      </p>

      <div class="field">
        <label>{{ t('studio.diversity.ref_label') }}</label>
        <select v-model="refTaskId" class="neo-select">
          <option value="">{{ t('studio.diversity.ref_demo') }}</option>
          <option v-for="task in annoTasks" :key="task.task_id" :value="task.task_id">
            {{ task.task_name }} ({{ task.feature_count }} CDS)
          </option>
        </select>
      </div>

      <div v-if="annoTasks.length > 1" class="field">
        <label>{{ t('studio.diversity.compare_label', { count: compareIds.length }) }}</label>
        <div class="check-list">
          <label
            v-for="task in annoTasks.filter((x) => x.task_id !== refTaskId)"
            :key="task.task_id"
            class="check-item"
          >
            <input
              type="checkbox"
              :checked="compareIds.includes(task.task_id)"
              @change="toggleCompare(task.task_id)"
            />
            <span class="check-name">{{ task.task_name }}</span>
          </label>
        </div>
      </div>

      <div class="field">
        <label>{{ t('studio.diversity.fasta_label') }}</label>
        <textarea
          v-model="fastaContent"
          rows="3"
          class="neo-textarea"
          placeholder=">Strain_1&#10;ATGCTAGC..."
        ></textarea>
      </div>

      <div class="form-row">
        <div class="field">
          <label>{{ t('studio.diversity.window_size') }}</label>
          <input type="number" v-model.number="windowSize" min="50" max="5000" class="neo-input" />
        </div>
        <div class="field">
          <label>{{ t('studio.diversity.step_size') }}</label>
          <input type="number" v-model.number="stepSize" min="10" max="1000" class="neo-input" />
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>{{ t('studio.common.palette') }}</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">{{ t('studio.common.palette_nature_byr') }}</option>
            <option value="monochrome">{{ t('studio.common.palette_mono_gray') }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('studio.common.dpi') }}</label>
          <select v-model.number="dpi" class="neo-select">
            <option :value="300">300 DPI</option>
            <option :value="600">600 DPI</option>
          </select>
        </div>
      </div>

      <div class="field">
        <label>{{ t('studio.common.figure_title') }}</label>
        <input v-model="title" class="neo-input" />
      </div>

      <label class="chk">
        <input type="checkbox" v-model="showGeneTable" />
        <span>{{ t('studio.diversity.chk_gene_table') }}</span>
      </label>

      <button type="button" class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? t('studio.diversity.btn_rendering') : t('studio.diversity.btn_submit') }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      :empty-title="t('studio.diversity.empty_title')"
      :empty-desc="t('studio.diversity.empty_desc')"
    />
  </div>
</template>

<style scoped>
.tool-layout { display: flex; flex: 1; min-height: 0; height: 100%; overflow: hidden; }
.tool-sidebar { width: 340px; min-width: 340px; background: #fff; border-right: 1px solid #e2e8f0; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.sec-head { display: flex; justify-content: space-between; align-items: center; }
.sec-head h3 { margin: 0; font-size: 14px; color: #0f172a; }
.btn-link { background: none; border: none; color: #2563eb; font-size: 11px; font-weight: 700; cursor: pointer; }
.sec-desc { margin: 0; font-size: 11px; color: #64748b; line-height: 1.5; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 11px; font-weight: 600; color: #475569; }
.check-list { max-height: 140px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; display: flex; flex-direction: column; gap: 4px; background: #f8fafc; }
.check-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #0f172a; cursor: pointer; }
.check-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.neo-select, .neo-input, .neo-textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; background: #fff; box-sizing: border-box; font-family: inherit; }
.neo-textarea { font-family: monospace; font-size: 11px; resize: vertical; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
