<script setup lang="ts">
import { ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioPaletteType, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

const DEFAULT_CSV = `Host_or_Serotype,T5_E1,PRD1,PRDmint,PRDjuniper,KP24_gp300,KLEO13_dep,S2_dep
E. coli K12,92,88,76,15,5,12,8
S. enterica LT2,85,94,82,68,8,10,4
C. werkmanii,24,80,79,72,4,6,5
K. pneumoniae K2,6,12,8,10,95,86,18
K. pneumoniae K25,5,8,11,7,91,14,89
P. putida KT2440,12,42,74,93,6,5,10
P. fluorescens,8,35,62,84,4,8,6
S. marcescens,10,18,12,9,12,79,92`

const appStore = useAppStore()
const mode = ref<'dual_tree_heatmap' | 'sparse_specificity'>('dual_tree_heatmap')
const matrixCsv = ref<string>(DEFAULT_CSV)
const clusterRows = ref<boolean>(true)
const clusterCols = ref<boolean>(true)
const showValues = ref<boolean>(true)
const palette = ref<StudioPaletteType>('nature')
const dpi = ref<number>(300)
const title = ref<string>('Phage-Host Interaction & Receptor Specificity Matrix')
const loading = ref<boolean>(false)
const renderResult = ref<StudioRenderResponse | null>(null)

function handleCsvUpload(ev: Event): void {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    matrixCsv.value = String(reader.result || '')
    appStore.showNotification(`已载入表型矩阵: ${file.name}`, 'info')
  }
  reader.readAsText(file, 'utf-8')
}

async function handleRender(forceDemo = false): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    renderResult.value = await studioApi.renderHostMatrix({
      mode: mode.value,
      use_demo: forceDemo || !matrixCsv.value.trim(),
      matrix_csv: forceDemo ? null : matrixCsv.value.trim() || null,
      cluster_rows: clusterRows.value,
      cluster_cols: clusterCols.value,
      show_values: showValues.value,
      palette: palette.value,
      title: title.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: dpi.value,
    })
    appStore.showNotification('已生成出版级宿主谱与特异性矩阵图', 'success')
  } catch (e) {
    appStore.showNotification(`渲染失败: ${String(e)}`, 'error')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="tool-layout">
    <aside class="tool-sidebar">
      <div class="sec-head">
        <h3>双树宿主谱热图与特异性矩阵</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        对标 Nature Communications 2024 Fig. 4 & 2026 DepoCatalog Fig. 2：左挂宿主聚类树 + 底挂噬菌体树 + 连续梯度/对角化特异性矩阵，助力鸡尾酒配伍发表。
      </p>

      <div class="field">
        <label>期刊版式</label>
        <select v-model="mode" class="neo-select">
          <option value="dual_tree_heatmap">双进化树联动连续抑制热图 (EOP / 生长抑制)</option>
          <option value="sparse_specificity">对角化血清型/宿主特异性稀疏矩阵 (鸡尾酒设计)</option>
        </select>
      </div>

      <div class="field">
        <label>粘贴实验 CSV / TSV 矩阵（首行为噬菌体列，首列为菌株行）</label>
        <textarea v-model="matrixCsv" rows="7" class="neo-textarea"></textarea>
      </div>

      <div class="field">
        <label>或上传 CSV / TSV 文件</label>
        <input type="file" accept=".csv,.tsv,.txt" class="neo-file" @change="handleCsvUpload" />
      </div>

      <div class="form-row">
        <div class="field">
          <label>期刊色板</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">Nature / 蓝紫梯度</option>
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
        <input type="checkbox" v-model="clusterRows" />
        <span>自动聚类重排宿主菌株行</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="clusterCols" />
        <span>自动聚类重排噬菌体列</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showValues" />
        <span>单元格内显示裂解/抑制分值</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在聚类排序并渲染...' : '生成宿主谱矩阵出版图' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="双树宿主谱热图与特异性矩阵预览区"
      empty-desc="直接粘贴 EOP 滴度、斑点试验或生长抑制率 CSV 表格，即可生成与左侧宿主树/底部噬菌体树严丝合缝对齐的高清热图。"
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
.neo-file { font-size: 11px; color: #475569; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { margin-top: 4px; width: 100%; padding: 9px; border: none; border-radius: 8px; background: #0f766e; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
