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
const selectedTaskIds = ref<string[]>([])
const mode = ref<'lovis4u' | 'clinker'>('lovis4u')
const palette = ref<StudioPaletteType>('nature')
const minIdentity = ref<number>(35)
const showIdentityLabels = ref<boolean>(false)
const showLabels = ref<boolean>(true)
const dpi = ref<number>(300)
const title = ref<string>('Comparative Phage Genome Synteny')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

async function loadSources(): Promise<void> {
  try {
    const res = await studioApi.getSources()
    annoTasks.value = res.annotation_tasks.filter((item) => item.sample_type === 'PHAGE' || item.feature_count > 0)
    if (annoTasks.value.length >= 2) {
      selectedTaskIds.value = annoTasks.value.slice(0, 3).map((item) => item.task_id)
    }
  } catch (e) {
    appStore.showNotification(t('studio.common.load_anno_failed', { error: String(e) }), 'warning')
  }
}

function toggleTask(taskId: string): void {
  const idx = selectedTaskIds.value.indexOf(taskId)
  if (idx >= 0) {
    selectedTaskIds.value.splice(idx, 1)
  } else {
    selectedTaskIds.value.push(taskId)
  }
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  if (!forceDemo && selectedTaskIds.value.length > 0 && selectedTaskIds.value.length < 2) {
    appStore.showNotification(t('studio.synteny.notify_need_two'), 'warning')
    return
  }
  loading.value = true
  try {
    renderResult.value = await studioApi.renderSynteny({
      mode: mode.value,
      annotation_task_ids: forceDemo ? [] : selectedTaskIds.value,
      use_demo: forceDemo || selectedTaskIds.value.length < 2,
      min_identity: minIdentity.value,
      show_identity_labels: showIdentityLabels.value,
      show_labels: showLabels.value,
      palette: palette.value,
      title: title.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification(t('studio.synteny.notify_success'), 'success')
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
        <h3>{{ t('studio.synteny.title') }}</h3>
        <button type="button" class="btn-link" @click="handleRender(true)">{{ t('studio.common.load_demo') }}</button>
      </div>
      <p class="sec-desc">
        {{ t('studio.synteny.desc') }}
      </p>

      <div class="field">
        <label>{{ t('studio.synteny.select_label', { count: selectedTaskIds.length }) }}</label>
        <div v-if="annoTasks.length" class="check-list">
          <label v-for="task in annoTasks" :key="task.task_id" class="check-item">
            <input
              type="checkbox"
              :checked="selectedTaskIds.includes(task.task_id)"
              @change="toggleTask(task.task_id)"
            />
            <span class="check-name" :title="task.task_name">{{ task.task_name }}</span>
            <span class="check-meta">{{ task.feature_count }} CDS</span>
          </label>
        </div>
        <div v-else class="empty-mini">{{ t('studio.synteny.empty_tasks') }}</div>
      </div>

      <div class="field">
        <label>{{ t('studio.synteny.style_label') }}</label>
        <select v-model="mode" class="neo-select">
          <option value="lovis4u">{{ t('studio.synteny.mode_lovis4u') }}</option>
          <option value="clinker">{{ t('studio.synteny.mode_clinker') }}</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>{{ t('studio.synteny.min_identity') }}</label>
          <input type="number" v-model.number="minIdentity" min="15" max="95" class="neo-input" />
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
        <input type="checkbox" v-model="showLabels" />
        <span>{{ t('studio.synteny.chk_labels') }}</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showIdentityLabels" />
        <span>{{ t('studio.synteny.chk_identity') }}</span>
      </label>

      <button type="button" class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? t('studio.synteny.btn_rendering') : t('studio.synteny.btn_submit') }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      :empty-title="t('studio.synteny.empty_title')"
      :empty-desc="t('studio.synteny.empty_desc')"
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
.check-list { max-height: 190px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; display: flex; flex-direction: column; gap: 5px; background: #f8fafc; }
.check-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #0f172a; cursor: pointer; }
.check-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.check-meta { font-size: 10px; color: #64748b; flex-shrink: 0; }
.empty-mini { font-size: 11px; color: #64748b; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 8px; }
.neo-select, .neo-input { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; background: #fff; box-sizing: border-box; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
