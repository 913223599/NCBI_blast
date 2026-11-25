<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioAnnotationSourceItem, StudioPaletteType, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

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
      compareIds.value = annoTasks.value.slice(1, 5).map((t) => t.task_id)
    }
  } catch (e) {
    appStore.showNotification(`加载注释任务失败: ${String(e)}`, 'warning')
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
    appStore.showNotification('已生成全基因组核苷酸多样性热点图', 'success')
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
        <h3>同种多株系多样性 (Pi) 热点图</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        对标 Nature Communications 2024 Fig. 2c：在同种进化枝枝长极短时，用滑动窗口多样性曲线与基因内部蓝→黄→红热图精准锁定尾丝/RBP 等高变基因。
      </p>

      <div class="field">
        <label>坐标参考注释基因组</label>
        <select v-model="refTaskId" class="neo-select">
          <option value="">内置示范同种序列集</option>
          <option v-for="t in annoTasks" :key="t.task_id" :value="t.task_id">
            {{ t.task_name }} ({{ t.feature_count }} CDS)
          </option>
        </select>
      </div>

      <div v-if="annoTasks.length > 1" class="field">
        <label>加入对比的同种注释任务（已选 {{ compareIds.length }} 个）</label>
        <div class="check-list">
          <label
            v-for="t in annoTasks.filter((x) => x.task_id !== refTaskId)"
            :key="t.task_id"
            class="check-item"
          >
            <input
              type="checkbox"
              :checked="compareIds.includes(t.task_id)"
              @change="toggleCompare(t.task_id)"
            />
            <span class="check-name">{{ t.task_name }}</span>
          </label>
        </div>
      </div>

      <div class="field">
        <label>或补充粘贴多条同种 FASTA 序列（可选）</label>
        <textarea
          v-model="fastaContent"
          rows="3"
          class="neo-textarea"
          placeholder=">Strain_1&#10;ATGCTAGC..."
        ></textarea>
      </div>

      <div class="form-row">
        <div class="field">
          <label>滑动窗口 (bp)</label>
          <input type="number" v-model.number="windowSize" min="50" max="5000" class="neo-input" />
        </div>
        <div class="field">
          <label>步长 (bp)</label>
          <input type="number" v-model.number="stepSize" min="10" max="1000" class="neo-input" />
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>期刊色板</label>
          <select v-model="palette" class="neo-select">
            <option value="nature">Nature / 蓝黄红</option>
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
        <input type="checkbox" v-model="showGeneTable" />
        <span>底部附 4 栏基因编号-功能产物对照表</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在计算滑窗 Pi 多样性...' : '生成核苷酸多样性热点图' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="全基因组核苷酸多样性 (Pi) 热点图预览区"
      empty-desc="选用同一个属/种的多株噬菌体序列，即可量化不同基因窗口的变异速率并用红蓝梯度填入基因箭头内。"
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
