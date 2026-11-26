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
const selectedTaskId = ref<string>('')
const gbkContent = ref<string>('')
const useDemo = ref<boolean>(false)
const mode = ref<'circular' | 'linear_multitrack'>('circular')
const palette = ref<StudioPaletteType>('nature')
const showLabels = ref<boolean>(true)
const maxLabels = ref<number>(28)
const showGcContent = ref<boolean>(true)
const showGcSkew = ref<boolean>(true)
const dpi = ref<number>(300)
const title = ref<string>('')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

async function loadSources(): Promise<void> {
  try {
    const res = await studioApi.getSources()
    annoTasks.value = res.annotation_tasks
    if (annoTasks.value.length > 0 && !selectedTaskId.value) {
      selectedTaskId.value = annoTasks.value[0]!.task_id
      useDemo.value = false
    } else if (annoTasks.value.length === 0) {
      useDemo.value = true
    }
  } catch (e) {
    useDemo.value = true
    appStore.showNotification(t('studio.common.load_anno_failed', { error: String(e) }), 'warning')
  }
}

function handleGbkUpload(ev: Event): void {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    gbkContent.value = String(reader.result || '')
    selectedTaskId.value = ''
    useDemo.value = false
    appStore.showNotification(t('studio.genome.notify_gbk_loaded', { name: file.name }), 'info')
  }
  reader.readAsText(file, 'utf-8')
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  if (forceDemo) {
    useDemo.value = true
    gbkContent.value = ''
  }
  loading.value = true
  try {
    renderResult.value = await studioApi.renderGenomeMap({
      mode: mode.value,
      annotation_task_id: !useDemo.value && selectedTaskId.value ? selectedTaskId.value : null,
      gbk_content: !useDemo.value && !selectedTaskId.value && gbkContent.value ? gbkContent.value : null,
      use_demo: useDemo.value || (!selectedTaskId.value && !gbkContent.value),
      gc_window: 0,
      show_labels: showLabels.value,
      max_labels: maxLabels.value,
      show_gc_content: showGcContent.value,
      show_gc_skew: showGcSkew.value,
      palette: palette.value,
      title: title.value.trim() || null,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification(t('studio.genome.notify_success'), 'success')
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
        <h3>{{ t('studio.genome.title') }}</h3>
        <button type="button" class="btn-link" @click="handleRender(true)">{{ t('studio.common.load_demo') }}</button>
      </div>
      <p class="sec-desc">
        {{ t('studio.genome.desc') }}
      </p>

      <div class="field">
        <label>{{ t('studio.genome.source_label') }}</label>
        <select v-model="selectedTaskId" class="neo-select" @change="useDemo = !selectedTaskId">
          <option value="">{{ t('studio.genome.source_demo') }}</option>
          <option v-for="task in annoTasks" :key="task.task_id" :value="task.task_id">
            {{ task.task_name }} ({{ task.feature_count }} CDS)
          </option>
        </select>
      </div>

      <div class="field">
        <label>{{ t('studio.genome.upload_label') }}</label>
        <input type="file" accept=".gbk,.gb,.genbank" class="neo-file" @change="handleGbkUpload" />
      </div>

      <div class="field">
        <label>{{ t('studio.common.journal_layout') }}</label>
        <select v-model="mode" class="neo-select">
          <option value="circular">{{ t('studio.genome.mode_circular') }}</option>
          <option value="linear_multitrack">{{ t('studio.genome.mode_linear') }}</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>{{ t('studio.genome.max_labels') }}</label>
          <input type="number" v-model.number="maxLabels" min="6" max="60" class="neo-input" />
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
        <label>{{ t('studio.genome.custom_title_label') }}</label>
        <input v-model="title" class="neo-input" :placeholder="t('studio.genome.custom_title_placeholder')" />
      </div>

      <label class="chk">
        <input type="checkbox" v-model="showLabels" />
        <span>{{ t('studio.genome.chk_labels') }}</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showGcContent" />
        <span>{{ t('studio.genome.chk_gc_content') }}</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showGcSkew" />
        <span>{{ t('studio.genome.chk_gc_skew') }}</span>
      </label>

      <button type="button" class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? t('studio.genome.btn_rendering') : t('studio.genome.btn_submit') }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      :empty-title="t('studio.genome.empty_title')"
      :empty-desc="t('studio.genome.empty_desc')"
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
.neo-select, .neo-input { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; background: #fff; box-sizing: border-box; }
.neo-file { font-size: 11px; color: #475569; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
