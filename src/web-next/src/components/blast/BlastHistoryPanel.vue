<script setup lang="ts">
import { ref } from 'vue'
import { useBlastStore } from '../../stores/blast'
import { useI18n } from '../../locales'

const props = defineProps<{
  editingTaskId: string | null
  editName: string
}>()

const emit = defineEmits<{
  (e: 'selectTask', taskId: string): void
  (e: 'startRename', task: any, event: Event): void
  (e: 'commitRename', task: any): void
  (e: 'pauseTask', taskId: string, event: Event): void
  (e: 'resumeTask', taskId: string, event: Event): void
  (e: 'stopTask', taskId: string, event: Event): void
  (e: 'deleteTask', taskId: string, event: Event): void
  (e: 'clearHistory'): void
  (e: 'update:editName', value: string): void
}>()

const blast = useBlastStore()
const { t } = useI18n()
const renameInputRef = ref<HTMLInputElement | null>(null)

function statusLabel(s: string) { 
  const m: any = { 
    queued: t('blast.status.queued'), 
    running: t('blast.status.running'), 
    done: t('blast.status.done'), 
    completed: t('blast.status.completed'), 
    error: t('blast.status.error'), 
    failed: t('blast.status.failed'), 
    cancelled: t('blast.status.cancelled'), 
    paused: t('blast.status.paused') 
  }
  return m[s] || s
}

defineExpose({
  renameInputRef
})
</script>

<template>
  <div class="panel-section">
    <h3 class="section-title">{{ t('blast.hist.title') }}</h3>
    <div class="history-list">
      <div v-for="t in blast.tasks" :key="t.taskId" class="task-card" :class="{ active: blast.activeTaskId === t.taskId }" @click="emit('selectTask', t.taskId)">
        <div class="title" @dblclick="emit('startRename', t, $event)">
          <span v-if="editingTaskId !== t.taskId">{{ t.fileName }}</span>
          <input 
            v-else 
            :value="editName"
            @input="emit('update:editName', ($event.target as HTMLInputElement).value)"
            class="rename-inp" 
            ref="renameInputRef" 
            @blur="emit('commitRename', t)" 
            @keyup.enter="emit('commitRename', t)" 
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
           <button v-if="t.status === 'running'" title="暂停" @click.stop="emit('pauseTask', t.taskId, $event)">⏸</button>
           <button v-if="['paused', 'error', 'failed', 'cancelled'].includes(t.status)" title="继续" @click.stop="emit('resumeTask', t.taskId, $event)">▶️</button>
           <button v-if="['running', 'paused', 'queued'].includes(t.status)" title="取消" @click.stop="emit('stopTask', t.taskId, $event)">⏹</button>
           <button title="删除" @click.stop="emit('deleteTask', t.taskId, $event)">🗑</button>
        </div>
      </div>
    </div>
    <div v-if="blast.tasks.length > 0" class="history-footer">
      <button class="text-btn-warn" @click="emit('clearHistory')">{{ t('blast.hist.clear') }}</button>
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
.task-card .meta { display: flex; align-items: center; justify-content: space-between; }
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
.card-actions button { background: none; border: none; cursor: pointer; font-size: 0.9rem; padding: 4px; border-radius: 4px; }
.card-actions button:hover { background: rgba(0,0,0,0.05); }

.rename-inp { width: 100%; border: 1px solid #2563eb; border-radius: 4px; padding: 2px 6px; font-size: 0.8rem; outline: none; background: white; }

.history-footer { margin-top: 20px; text-align: center; }
.text-btn-warn { background: none; border: none; color: #ef4444; font-size: 0.75rem; font-weight: 600; cursor: pointer; }
.text-btn-warn:hover { text-decoration: underline; }
</style>
