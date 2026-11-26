<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useBlastStore, type BlastTask } from '../../stores/blast'
import { useI18n } from '../../locales'
import { apiGet, apiDelete } from '../../bridge/electron-bridge'
import { shouldSubmitOnEnter } from '../../utils/ime'
import { useConfirmDialog } from '../../composables/useConfirmDialog'
import { createLogger } from '../../utils/logger'
import type { DiversityHistoryTask } from './diversity/useDiversityModal'

const logger = createLogger('BlastHistoryPanel')

const props = defineProps<{
  editingTaskId: string | null
  editName: string
  activeDiversityTaskId?: string
}>()

const emit = defineEmits<{
  (e: 'selectTask', taskId: string): void
  (e: 'startRename', task: BlastTask, event: Event): void
  (e: 'commitRename', task: BlastTask): void
  (e: 'pauseTask', taskId: string, event: Event): void
  (e: 'resumeTask', taskId: string, event: Event): void
  (e: 'stopTask', taskId: string, event: Event): void
  (e: 'deleteTask', taskId: string, event: Event): void
  (e: 'clearHistory'): void
  (e: 'update:editName', value: string): void
  (e: 'selectDiversityTask', task: DiversityHistoryTask): void
  (e: 'deleteDiversityTask', taskId: string): void
  (e: 'clearDiversityHistory'): void
}>()

const blast = useBlastStore()
const { t } = useI18n()
const confirmDialog = useConfirmDialog()
const renameInputRef = ref<HTMLInputElement | null>(null)

// 多样性历史状态
const isDiversity = computed(() => blast.analysisTarget === 'diversity')
const diversityTasks = ref<DiversityHistoryTask[]>([])
const isLoadingDiversity = ref(false)
const currentDiversityTaskId = ref<string>('')

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    queued: t('blast.status.queued'),
    running: t('blast.status.running'),
    done: t('blast.status.done'),
    completed: t('blast.status.completed'),
    error: t('blast.status.error'),
    failed: t('blast.status.failed'),
    cancelled: t('blast.status.cancelled'),
    paused: t('blast.status.paused'),
  }
  return m[s] || s
}

/** 获取多样性历史任务 */
async function fetchDiversityTasks() {
  isLoadingDiversity.value = true
  try {
    const res = await apiGet('/api/diversity/tasks')
    if (Array.isArray(res)) {
      diversityTasks.value = res as DiversityHistoryTask[]
      if (props.activeDiversityTaskId) {
        currentDiversityTaskId.value = props.activeDiversityTaskId
      }
    }
  } catch (e: unknown) {
    logger.error('Fetch diversity tasks failed:', e)
  } finally {
    isLoadingDiversity.value = false
  }
}

function handleSelectDiversity(task: DiversityHistoryTask) {
  currentDiversityTaskId.value = task.task_id
  emit('selectDiversityTask', task)
}

async function handleDeleteDiversity(task: DiversityHistoryTask, e: Event) {
  e.stopPropagation()
  const ok = await confirmDialog.confirm({
    title: '删除多样性分析归档',
    message: `确定要彻底删除多样性分析归档 "${task.task_name}" 吗？`,
    confirmText: '彻底删除',
    danger: true,
  })
  if (!ok) return
  try {
    const res = await apiDelete(`/api/diversity/task/${task.task_id}`)
    if (res && res.status === 'deleted') {
      emit('deleteDiversityTask', task.task_id)
      void fetchDiversityTasks()
    }
  } catch (err: unknown) {
    logger.error('Delete diversity task failed:', err)
  }
}

async function handleClearDiversity() {
  const ok = await confirmDialog.confirm({
    title: '清空全部多样性历史',
    message: '确定要清空全部多样性历史分析记录吗？此操作将物理删除所有相关 Checkpoint。',
    confirmText: '全部清空',
    danger: true,
  })
  if (!ok) return
  try {
    const res = await apiDelete('/api/diversity/tasks/clear')
    if (res && res.status === 'cleared') {
      diversityTasks.value = []
      emit('clearDiversityHistory')
    }
  } catch (err: unknown) {
    logger.error('Clear diversity tasks failed:', err)
  }
}

watch(() => blast.analysisTarget, (newTarget) => {
  if (newTarget === 'diversity') {
    void fetchDiversityTasks()
  }
})

watch(() => props.activeDiversityTaskId, (newId) => {
  if (newId) {
    currentDiversityTaskId.value = newId
  }
})

onMounted(() => {
  if (isDiversity.value) {
    void fetchDiversityTasks()
  }
})

function onRenameKeydown(event: KeyboardEvent, task: BlastTask) {
  if (shouldSubmitOnEnter(event)) {
    emit('commitRename', task)
  }
}

defineExpose({
  renameInputRef,
  fetchDiversityTasks,
})
</script>

<template>
  <div class="panel-section">
    <h3 class="section-title">
      {{ isDiversity ? '多样性分析历史' : t('blast.hist.title') }}
    </h3>

    <!-- 模式 A: 16S 扩增子多样性历史任务列表 -->
    <div v-if="isDiversity" class="history-list">
      <div 
        v-for="t in diversityTasks" 
        :key="t.task_id" 
        class="task-card" 
        :class="{ active: (currentDiversityTaskId || props.activeDiversityTaskId) === t.task_id }" 
        role="button"
        tabindex="0"
        @click="handleSelectDiversity(t)"
        @keydown.enter.space.prevent="handleSelectDiversity(t)"
      >
        <div class="title" :title="t.task_name">
          <span>{{ t.task_name }}</span>
        </div>
        <div class="meta">
          <span class="status" :class="t.status">{{ statusLabel(t.status) }}</span>
          <span class="meta-sub" v-if="t.total_samples">共 {{ t.total_samples }} 个点位</span>
        </div>
        <div class="progress-bar-container" v-if="['running', 'queued'].includes(t.status)">
          <div class="progress-bar-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
          <span class="progress-text">{{ t.progress || 0 }}%</span>
        </div>
        <div class="card-actions">
          <button type="button" title="删除" @click.stop="handleDeleteDiversity(t, $event)">
            <svg class="action-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </button>
        </div>
      </div>

      <div v-if="diversityTasks.length === 0" class="empty-hint-text">
        暂无多样性历史分析记录
      </div>

      <div v-if="diversityTasks.length > 0" class="history-footer">
        <button type="button" class="text-btn-warn" @click="handleClearDiversity">清空全部历史记录</button>
      </div>
    </div>

    <!-- 模式 B: 单株菌株鉴定历史任务列表 -->
    <div v-else class="history-list">
      <div
        v-for="t in blast.tasks"
        :key="t.taskId"
        class="task-card"
        :class="{ active: blast.activeTaskId === t.taskId }"
        role="button"
        tabindex="0"
        @click="emit('selectTask', t.taskId)"
        @keydown.enter.space.prevent="emit('selectTask', t.taskId)"
      >
        <div class="title" @dblclick="emit('startRename', t, $event)">
          <span v-if="editingTaskId !== t.taskId">{{ t.fileName }}</span>
          <input 
            v-else 
            :value="editName"
            @input="emit('update:editName', ($event.target as HTMLInputElement).value)"
            class="rename-inp" 
            ref="renameInputRef" 
            @blur="emit('commitRename', t)" 
            @keydown="onRenameKeydown($event, t)" 
          />
        </div>
        <div class="meta">
          <span class="status" :class="t.status">{{ statusLabel(t.status) }}</span>
        </div>
        <div class="progress-bar-container" v-if="['running', 'paused', 'queued', 'error', 'failed', 'cancelled'].includes(t.status)">
          <div class="progress-bar-fill" :style="{ width: t.progress + '%' }"></div>
          <span class="progress-text">{{ t.progress }}%</span>
        </div>
        <div class="card-actions">
          <button type="button" v-if="t.status === 'running'" title="暂停" @click.stop="emit('pauseTask', t.taskId, $event)">
            <svg class="action-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </button>
          <button type="button" v-if="['paused', 'error', 'failed', 'cancelled'].includes(t.status)" title="继续" @click.stop="emit('resumeTask', t.taskId, $event)">
            <svg class="action-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"/>
            </svg>
          </button>
          <button type="button" v-if="['running', 'paused', 'queued'].includes(t.status)" title="取消" @click.stop="emit('stopTask', t.taskId, $event)">
            <svg class="action-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z" clip-rule="evenodd"/>
            </svg>
          </button>
          <button type="button" title="删除" @click.stop="emit('deleteTask', t.taskId, $event)">
            <svg class="action-icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </button>
        </div>
      </div>
      <div v-if="blast.tasks.length > 0" class="history-footer">
        <button type="button" class="text-btn-warn" @click="emit('clearHistory')">{{ t('blast.hist.clear') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-section { margin-bottom: 24px; }
.section-title { font-size: 0.9rem; font-weight: 700; color: #1e293b; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }

.history-list { display: flex; flex-direction: column; gap: 10px; }
.task-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; cursor: pointer; transition: all 0.2s; position: relative; }
.task-card:hover { border-color: #cbd5e1; background: #f1f5f9; }
.task-card.active { border-color: #2563eb; background: #eff6ff; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08); }

.task-card .title { font-weight: 600; font-size: 0.82rem; color: #334155; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-card .meta { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.meta-sub { font-size: 0.72rem; color: #64748b; }
.status { font-size: 0.7rem; font-weight: 700; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; }
.status.done, .status.completed { background: #d1fae5; color: #065f46; }
.status.running { background: #dbeafe; color: #1e40af; }
.status.queued { background: #f1f5f9; color: #475569; }
.status.paused { background: #fef3c7; color: #92400e; }
.status.error, .status.failed { background: #fee2e2; color: #991b1b; }

.progress-bar-container { height: 6px; background: #e2e8f0; border-radius: 3px; margin-top: 10px; overflow: hidden; position: relative; }
.progress-bar-fill { height: 100%; background: #3b82f6; transition: width 0.3s ease; }
.progress-text { position: absolute; right: 0; top: -14px; font-size: 0.65rem; color: #64748b; font-weight: 600; }

.card-actions { margin-top: 10px; display: flex; justify-content: flex-end; gap: 8px; opacity: 0.6; }
.task-card:hover .card-actions { opacity: 1; }
.card-actions button { background: none; border: none; cursor: pointer; padding: 4px; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #64748b; }
.card-actions button:hover { background: rgba(0,0,0,0.06); color: #1e293b; }
.action-icon-svg { width: 15px; height: 15px; }

.rename-inp { width: 100%; border: 1px solid #2563eb; border-radius: 4px; padding: 2px 6px; font-size: 0.8rem; outline: none; background: white; }

.empty-hint-text { text-align: center; color: #94a3b8; font-size: 0.78rem; padding: 20px 0; }
.history-footer { margin-top: 20px; text-align: center; }
.text-btn-warn { background: none; border: none; color: #ef4444; font-size: 0.75rem; font-weight: 600; cursor: pointer; }
.text-btn-warn:hover { text-decoration: underline; }
</style>
