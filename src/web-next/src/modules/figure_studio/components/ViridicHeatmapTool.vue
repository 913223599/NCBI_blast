<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioPaletteType, StudioPhyloSourceItem, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

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
    appStore.showNotification(`加载历史 ANI 数据源失败: ${String(e)}`, 'warning')
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
    appStore.showNotification('已生成出版级 VIRIDIC / ANI 矩阵图', 'success')
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
        <h3>VIRIDIC 双向热图与 ANI 矩阵</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        对标 ICTV 官方 VIRIDIC Fig.4 与 Nature Communications 进化树联动下三角热图，同步展示两两相似性、对齐覆盖度及基因组长度柱图。
      </p>

      <div class="field">
        <label>数据来源（来自进化树步骤 1 wgANI 矩阵）</label>
        <select v-model="selectedJobId" class="neo-select" @change="useDemo = !selectedJobId">
          <option value="">内置示范数据 (Tequintavirus)</option>
          <option v-for="j in phyloJobs" :key="j.job_id" :value="j.job_id">
            {{ j.title || j.job_id }} ({{ j.top_hits_count }} hits)
          </option>
        </select>
      </div>

      <div class="field">
        <label>期刊版式</label>
        <select v-model="mode" class="neo-select">
          <option value="viridic_dual">VIRIDIC 双三角全信息热图 (推荐)</option>
          <option value="tree_triangle">系统发育树 + 下三角 ANI 联动热图</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>期刊色板</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">Nature / NPG</option>
            <option value="monochrome">黑白印刷</option>
            <option value="lancet">Lancet</option>
            <option value="okabe_ito">Okabe-Ito</option>
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
        <input type="checkbox" v-model="clusterReorder" />
        <span>按层次聚类/拓扑重排行列顺序</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showValues" />
        <span>单元格内标注相似性百分比数值</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在生成 PDF / SVG / PNG...' : '生成 VIRIDIC 出版级矩阵图' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="VIRIDIC 双向相似性热图预览区"
      empty-desc="可选择已完成第 1 步 ANI 计算的历史任务，或点击「载入示例出图」立即生成 ICTV 标准双三角相似性与覆盖度热图。"
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
