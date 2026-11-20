<script setup lang="ts">
import type { StructureTaskHistoryItem } from '../types'
import { getMorphotypeTheme } from '../utils'

defineProps<{
  tasks: StructureTaskHistoryItem[]
  activeTaskId?: string
}>()

const emit = defineEmits<{
  (e: 'select', task: StructureTaskHistoryItem): void
  (e: 'delete', taskId: string): void
}>()

function statusLabel(item: StructureTaskHistoryItem): string {
  if (item.status === 'queued') {
    return item.queue_position ? `排队 #${item.queue_position}` : '排队中'
  }
  switch (item.status) {
    case 'completed':
      return '已完成'
    case 'running':
      return item.progress > 0 ? `预测中 ${item.progress}%` : '预测中'
    case 'cancelled':
      return '已中止'
    case 'failed':
      return '失败'
    default:
      return item.status
  }
}

function sourceModeText(mode: string): string {
  if (mode === 'annotation') return '注释导入'
  if (mode === 'phage_discovery') return '前噬菌体联动'
  if (mode === 'paste') return '文本粘贴'
  return '本地文件'
}
</script>

<template>
  <div class="history-list">
    <div v-if="tasks.length === 0" class="empty-history">
      暂无结构与形态预测记录
    </div>

    <div
      v-for="item in tasks"
      :key="item.task_id"
      class="history-item"
      :class="{ active: activeTaskId === item.task_id }"
      @click="emit('select', item)"
    >
      <div class="item-head">
        <span class="item-name" :title="item.task_name">{{ item.task_name }}</span>
        <button
          type="button"
          class="del-btn"
          title="删除此预测记录"
          @click.stop="emit('delete', item.task_id)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14H6L5 6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
          </svg>
        </button>
      </div>

      <div class="item-badges">
        <span class="status-pill" :class="item.status">{{ statusLabel(item) }}</span>
        <span
          v-if="item.status === 'completed' && item.summary?.primary_morphotype"
          class="morph-pill"
          :style="{
            backgroundColor: getMorphotypeTheme(item.summary.primary_morphotype).badgeBg,
            color: getMorphotypeTheme(item.summary.primary_morphotype).badgeText,
            borderColor: getMorphotypeTheme(item.summary.primary_morphotype).badgeBorder,
          }"
        >
          {{ getMorphotypeTheme(item.summary.primary_morphotype).shortLabel }}
        </span>
        <span class="src-tag">{{ sourceModeText(item.source_mode) }}</span>
      </div>

      <div v-if="item.status === 'running' || item.status === 'queued'" class="mini-progress-wrap">
        <div class="mini-progress-bar">
          <div
            class="mini-progress-fill"
            :class="item.status"
            :style="{ width: `${item.status === 'running' ? Math.max(8, item.progress || 8) : 12}%` }"
          ></div>
        </div>
        <div v-if="item.current_step" class="item-step" :title="item.current_step">
          {{ item.current_step }}
        </div>
      </div>

      <div class="item-foot">
        <span v-if="item.status === 'completed' && item.summary?.estimated_tail_length_nm != null">
          尾长约 {{ item.summary.estimated_tail_length_nm }} nm
        </span>
        <span v-else-if="item.status === 'completed' && item.summary?.primary_morphotype === 'Podoviridae-like'">
          短尾约 10–25 nm（无 TMP 标尺）
        </span>
        <span v-else-if="item.status === 'completed' && item.summary?.primary_morphotype === 'Non-tailed'">
          无复合尾器 (0 nm)
        </span>
        <span v-else>{{ item.created_at?.slice(5, 16) || '' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-history {
  padding: 28px 12px;
  text-align: center;
  color: #94a3b8;
  font-size: 0.84rem;
}

.history-item {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.16s ease;
}

.history-item:hover {
  border-color: #93c5fd;
  background: #f8fafc;
}

.history-item.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.item-name {
  font-size: 0.86rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del-btn {
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: flex;
  align-items: center;
}

.del-btn:hover {
  color: #ef4444;
  background: #fee2e2;
}

.item-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}

.status-pill,
.morph-pill,
.src-tag {
  font-size: 0.72rem;
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 600;
}

.status-pill.completed {
  background: #dcfce7;
  color: #15803d;
}

.status-pill.running {
  background: #dbeafe;
  color: #1d4ed8;
}

.status-pill.queued {
  background: #fef3c7;
  color: #b45309;
}

.status-pill.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.status-pill.cancelled {
  background: #f1f5f9;
  color: #64748b;
}

.morph-pill {
  border: 1px solid;
}

.src-tag {
  background: #f1f5f9;
  color: #475569;
  font-weight: 500;
}

.item-foot {
  margin-top: 6px;
  font-size: 0.74rem;
  color: #64748b;
}

.mini-progress-wrap {
  margin-top: 7px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.mini-progress-bar {
  height: 4px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}

.mini-progress-fill.running {
  background: linear-gradient(90deg, #2563eb, #0ea5e9);
}

.mini-progress-fill.queued {
  background: #f59e0b;
  opacity: 0.65;
}

.item-step {
  font-size: 0.71rem;
  color: #475569;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
