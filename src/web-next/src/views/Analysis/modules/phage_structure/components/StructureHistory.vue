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

function statusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'running':
      return '预测中'
    case 'queued':
      return '排队中'
    case 'cancelled':
      return '已中止'
    case 'failed':
      return '失败'
    default:
      return status
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
        <span class="status-pill" :class="item.status">{{ statusLabel(item.status) }}</span>
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

      <div class="item-foot">
        <span v-if="item.status === 'completed' && item.summary?.estimated_tail_length_nm != null">
          尾长约 {{ item.summary.estimated_tail_length_nm }} nm
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
</style>
