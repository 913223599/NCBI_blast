<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioAnnotationSourceItem, StudioPaletteType, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

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
    appStore.showNotification(`加载注释任务失败: ${String(e)}`, 'warning')
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
    appStore.showNotification(`已载入本地 GenBank 文件: ${file.name}`, 'info')
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
    appStore.showNotification('已生成出版级全基因组功能图谱', 'success')
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
        <h3>全基因组功能圈图与多轨图</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        对标 Proksee/CGView 圈图与 NAR 2025 LoVis4u 线性多轨图：整合正负链 CDS、PHROGs 功能模块分类色、GC Content 与 GC Skew 轨道及防重叠关键蛋白引线。
      </p>

      <div class="field">
        <label>数据来源（已完成注释任务）</label>
        <select v-model="selectedTaskId" class="neo-select" @change="useDemo = !selectedTaskId">
          <option value="">内置示范基因组 (或下方上传 GBK)</option>
          <option v-for="t in annoTasks" :key="t.task_id" :value="t.task_id">
            {{ t.task_name }} ({{ t.feature_count }} CDS)
          </option>
        </select>
      </div>

      <div class="field">
        <label>或上传本地 GenBank 文件 (.gbk / .gb)</label>
        <input type="file" accept=".gbk,.gb,.genbank" class="neo-file" @change="handleGbkUpload" />
      </div>

      <div class="field">
        <label>期刊版式</label>
        <select v-model="mode" class="neo-select">
          <option value="circular">圆形全基因组功能圈图 (CGView/pyCirclize)</option>
          <option value="linear_multitrack">线性多轨基因图谱 (LoVis4u 风格)</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>最大关键标注数</label>
          <input type="number" v-model.number="maxLabels" min="6" max="60" class="neo-input" />
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
        <label>自定义图题（留空自动读取样本名）</label>
        <input v-model="title" class="neo-input" placeholder="如 Escherichia phage T5" />
      </div>

      <label class="chk">
        <input type="checkbox" v-model="showLabels" />
        <span>显示防重叠关键蛋白引线标注</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showGcContent" />
        <span>显示 GC Content (%) 轨道</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showGcSkew" />
        <span>显示 GC Skew (G-C)/(G+C) 轨道</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在渲染全基因组图谱...' : '生成全基因组出版级图谱' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="单株全基因组功能图谱预览区"
      empty-desc="直接选用「组装分析」中已完成的 Pharokka/Prokka 注释任务，即可一键产出发表级 Figure 1 圆形圈图与线性多轨图。"
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
