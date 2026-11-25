<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioPaletteType, StudioPhyloSourceItem, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

const appStore = useAppStore()
const phyloJobs = ref<StudioPhyloSourceItem[]>([])
const selectedJobId = ref<string>('')
const edgesCsv = ref<string>('')
const minWeight = ref<number>(0.25)
const colorBy = ref<'family' | 'host'>('family')
const showWaffle = ref<boolean>(true)
const showLabels = ref<boolean>(true)
const palette = ref<StudioPaletteType>('nature')
const dpi = ref<number>(300)
const title = ref<string>('Gene-Sharing Viral Protein Cluster Network')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

async function loadSources(): Promise<void> {
  try {
    const res = await studioApi.getSources()
    phyloJobs.value = res.phylo_jobs.filter((j) => j.has_ani_matrix)
    if (phyloJobs.value.length > 0) {
      selectedJobId.value = phyloJobs.value[0]!.job_id
    }
  } catch (e) {
    appStore.showNotification(`加载任务失败: ${String(e)}`, 'warning')
  }
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const isDemo = forceDemo || (!selectedJobId.value && !edgesCsv.value.trim())
    renderResult.value = await studioApi.renderNetwork({
      phylo_job_id: isDemo ? null : selectedJobId.value || null,
      edges_csv: isDemo ? null : edgesCsv.value.trim() || null,
      use_demo: Boolean(isDemo),
      min_weight: minWeight.value,
      color_by: colorBy.value,
      show_waffle: showWaffle.value,
      show_labels: showLabels.value,
      palette: palette.value,
      title: title.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification('已生成类 vConTACT2 蛋白共享网络图', 'success')
  } catch (e) {
    appStore.showNotification(`渲染失败: ${String(e)}`, 'error')
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
        <h3>蛋白共享网络与构成华夫格图</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        对标 Nature Communications 2024 Fig. 2 & Nature Biotech vConTACT2：揭示噬菌体嵌合重组与跨科蛋白簇网状联系，右侧配 10×10 华夫格构成图。
      </p>

      <div class="field">
        <label>数据来源（进化树任务或自定义边表）</label>
        <select v-model="selectedJobId" class="neo-select">
          <option value="">内置示范病毒簇网络</option>
          <option v-for="j in phyloJobs" :key="j.job_id" :value="j.job_id">
            {{ j.title || j.job_id }} ({{ j.top_hits_count }} hits)
          </option>
        </select>
      </div>

      <div class="field">
        <label>或粘贴自定义网络边表 (source, target, weight, group)</label>
        <textarea
          v-model="edgesCsv"
          rows="4"
          class="neo-textarea"
          placeholder="Query_01, T5_ref, 0.92, Demerecviridae&#10;T4_ref, RB49, 0.85, Straboviridae"
        ></textarea>
      </div>

      <div class="form-row">
        <div class="field">
          <label>节点着色维度</label>
          <select v-model="colorBy" class="neo-select">
            <option value="family">病毒科 (ICTV Family)</option>
            <option value="host">宿主菌 (Host)</option>
          </select>
        </div>
        <div class="field">
          <label>连线最低权重 (0–1)</label>
          <input type="number" v-model.number="minWeight" step="0.05" min="0" max="0.95" class="neo-input" />
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>期刊色板</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">Nature / NPG</option>
            <option value="lancet">Lancet</option>
            <option value="okabe_ito">Okabe-Ito</option>
            <option value="monochrome">黑白灰阶</option>
          </select>
        </div>
        <div class="field">
          <label>PNG 分辨率</label>
          <select v-model.number="dpi" class="neo-select">
            <option :value="300">300 DPI</option>
            <option :value="600">600 DPI</option>
          </select>
        </div>
      </div>

      <div class="field">
        <label>图件标题</label>
        <input v-model="title" class="neo-input" />
      </div>

      <label class="chk">
        <input type="checkbox" v-model="showWaffle" />
        <span>右侧附 10×10 类别占比华夫格图</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showLabels" />
        <span>高亮标注 Query 及核心节点名</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在计算力导向布局与华夫格...' : '生成基因共享网络出版图' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="蛋白基因共享网络与华夫格图预览区"
      empty-desc="揭示水平基因转移导致的网状亲缘结构，自动分离主连通子图与底部孤立小簇。"
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
.neo-select, .neo-input, .neo-textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; background: #fff; box-sizing: border-box; font-family: inherit; }
.neo-textarea { font-family: monospace; font-size: 11px; resize: vertical; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
