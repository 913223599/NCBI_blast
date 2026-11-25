<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { studioApi } from '../api/studioApi'
import type { StudioAnnotationSourceItem, StudioPaletteType, StudioRenderResponse } from '../types/studio'
import StudioPreviewStage from './StudioPreviewStage.vue'

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
    annoTasks.value = res.annotation_tasks.filter((t) => t.sample_type === 'PHAGE' || t.feature_count > 0)
    if (annoTasks.value.length >= 2) {
      selectedTaskIds.value = annoTasks.value.slice(0, 3).map((t) => t.task_id)
    }
  } catch (e) {
    appStore.showNotification(`加载注释任务失败: ${String(e)}`, 'warning')
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
    appStore.showNotification('请至少勾选 2 个已注释噬菌体基因组进行比较，或点击「载入示例出图」', 'warning')
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
    appStore.showNotification('已生成出版级比较基因组共线性丝带图', 'success')
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
        <h3>比较基因组共线性丝带图</h3>
        <button class="btn-link" @click="handleRender(true)">载入示例出图</button>
      </div>
      <p class="sec-desc">
        提供 LoVis4u 现代去噪风格（核心基因淡灰 + 尾丝/抗防御高亮 + PHROGs 底条）与 clinker 贝塞尔曲线丝带风格，清晰呈现同源模块保守与变异重排。
      </p>

      <div class="field">
        <label>选择 2–8 个已注释噬菌体样本（已选 {{ selectedTaskIds.length }} 个）</label>
        <div v-if="annoTasks.length" class="check-list">
          <label v-for="t in annoTasks" :key="t.task_id" class="check-item">
            <input
              type="checkbox"
              :checked="selectedTaskIds.includes(t.task_id)"
              @change="toggleTask(t.task_id)"
            />
            <span class="check-name" :title="t.task_name">{{ t.task_name }}</span>
            <span class="check-meta">{{ t.feature_count }} CDS</span>
          </label>
        </div>
        <div v-else class="empty-mini">暂无已完成的注释任务，可直接点击右上角「载入示例出图」。</div>
      </div>

      <div class="field">
        <label>视觉风格</label>
        <select v-model="mode" class="neo-select">
          <option value="lovis4u">LoVis4u 现代去噪风格 (推荐)</option>
          <option value="clinker">clinker 曲线同源丝带风格</option>
        </select>
      </div>

      <div class="form-row">
        <div class="field">
          <label>最低蛋白一致度 (%)</label>
          <input type="number" v-model.number="minIdentity" min="15" max="95" class="neo-input" />
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
        <input type="checkbox" v-model="showLabels" />
        <span>显示关键基因阶梯防重叠标注</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="showIdentityLabels" />
        <span>丝带中央显示蛋白一致度百分比 (clinker)</span>
      </label>

      <button class="btn-primary" :disabled="loading" @click="handleRender(false)">
        {{ loading ? '正在计算蛋白同源并渲染...' : '生成共线性丝带比较图' }}
      </button>
    </aside>

    <StudioPreviewStage
      :result="renderResult"
      :loading="loading"
      empty-title="LoVis4u / clinker 共线性丝带图预览区"
      empty-desc="在左侧勾选多个噬菌体注释任务后点击生成，自动并行比对同源蛋白并渲染核心/变异模块共线性。"
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
