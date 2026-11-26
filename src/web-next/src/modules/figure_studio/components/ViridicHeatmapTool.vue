<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from '../../../locales'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioPaletteType, StudioPhyloSourceItem, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

const { t } = useI18n()
const appStore = useAppStore()
const phyloJobs = ref<StudioPhyloSourceItem[]>([])
const selectedJobId = ref<string>('')
const useDemo = ref<boolean>(false)
const mode = ref<'viridic_dual' | 'tree_triangle'>('viridic_dual')
const palette = ref<StudioPaletteType>('nature')
const clusterReorder = ref<boolean>(true)
const showValues = ref<boolean>(true)
const dpi = ref<number>(300)
const title = ref<string>('VIRIDIC Intergenomic Similarity & Alignment Matrix')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

async function loadSources(): Promise<void> {
  try {
    const res = await studioApi.getSources()
    phyloJobs.value = res.phylo_jobs.filter((j) => j.has_ani_matrix)
    if (phyloJobs.value.length > 0 && !selectedJobId.value) {
      selectedJobId.value = phyloJobs.value[0]!.job_id
      useDemo.value = false
    } else if (phyloJobs.value.length === 0) {
      useDemo.value = true
    }
  } catch (e) {
    useDemo.value = true
    appStore.showNotification(t('studio.viridic.notify_load_fail', { error: String(e) }), 'warning')
  }
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  if (forceDemo) useDemo.value = true
  loading.value = true
  try {
    renderResult.value = await studioApi.renderViridic({
      mode: mode.value,
      phylo_job_id: useDemo.value ? null : selectedJobId.value || null,
      use_demo: useDemo.value || !selectedJobId.value,
      cluster_reorder: clusterReorder.value,
      show_values: showValues.value,
      palette: palette.value,
      title: title.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification(t('studio.viridic.notify_success'), 'success')
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
        <h3>{{ t('studio.viridic.title') }}</h3>
        <button type="button" class="btn-link" @click="handleRender(true)">{{ t('studio.common.load_demo') }}</button>
      </div>
      <p class="sec-desc">
        {{ t('studio.viridic.desc') }}
      </p>

      <div class="field">
        <label>{{ t('studio.viridic.source_label') }}</label>
        <select v-model="selectedJobId" class="neo-select" @change="useDemo = !selectedJobId">
          <option value="">{{ t('studio.viridic.source_demo') }}</option>
          <option v-for="j in phyloJobs" :key="j.job_id" :value="j.job_id">
            {{ j.title || j.job_id }} ({{ j.top_hits_count }} hits)
          </option>
        </select>
      </div>

      <div class="field">
        <label>{{ t('studio.common.journal_layout') }}</label>
        <select v-model="mode" class="neo-select">
          <option value="viridic_dual">{{ t('studio.viridic.mode_dual') }}</option>
          <option value="tree_triangle">{{ t('studio.viridic.mode_triangle') }}</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>{{ t('studio.common.palette') }}</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">{{ t('studio.common.palette_nature') }}</option>
            <option value="monochrome">{{ t('studio.common.palette_monochrome') }}</option>
            <option value="lancet">{{ t('studio.common.palette_lancet') }}</option>
            <option value="okabe_ito">{{ t('studio.common.palette_okabe') }}</option>
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
        <input type="checkbox" v-model="clusterReorder" />
        <span>{{ t('studio.viridic.chk_reorder') }}</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showValues" />
        <span>{{ t('studio.viridic.chk_values') }}</span>
      </label>

      <button type="button" class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? t('studio.viridic.btn_rendering') : t('studio.viridic.btn_submit') }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      :empty-title="t('studio.viridic.empty_title')"
      :empty-desc="t('studio.viridic.empty_desc')"
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
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
