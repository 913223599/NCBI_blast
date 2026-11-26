<script setup lang="ts">
import type { DiversityHistoryTask } from './useDiversityModal'

defineProps<{
  visible: boolean
  isLoadingHistory: boolean
  historyTasks: DiversityHistoryTask[]
  activeTaskId: string
  formatTime: (timestamp: number | string | undefined) => string
  formatReadsCount: (num: number | undefined) => string
  getStatusLabel: (s: string) => string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'selectTask', task: DiversityHistoryTask): void
  (e: 'deleteTask', task: DiversityHistoryTask, event: Event): void
  (e: 'clearAllHistory'): void
}>()
</script>

<template>
  <transition name="drawer-fade">
    <div v-if="visible" class="history-drawer-backdrop" @click.self="emit('close')">
      <div class="history-drawer-neo">
        <div class="drawer-header-neo">
          <div class="drawer-title-group">
            <div class="drawer-icon-wrap">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <circle cx="12" cy="12" r="9" stroke-width="2" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 7v5l3 3" />
              </svg>
            </div>
            <div>
              <h3 class="drawer-title">历史多样性分析任务</h3>
              <span class="drawer-subtitle">共 {{ historyTasks.length }} 条分析归档</span>
            </div>
          </div>
          <button type="button" class="btn-drawer-close" @click="emit('close')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div class="drawer-list-wrap scroll-v">
          <div v-if="isLoadingHistory" class="drawer-empty-hint">
            <span>正在同步历史分析记录...</span>
          </div>
          <div v-else-if="historyTasks.length === 0" class="drawer-empty-hint">
            <span>暂无已归档的历史分析记录</span>
          </div>
          <div v-else class="drawer-task-list">
            <div
              v-for="item in historyTasks"
              :key="item.task_id"
              class="drawer-task-card"
              :class="{ active: activeTaskId === item.task_id }"
              @click="emit('selectTask', item)"
            >
              <div class="card-top-row">
                <span class="task-file-title" :title="item.task_name">{{ item.task_name }}</span>
                <span class="task-status-tag" :class="item.status">{{ getStatusLabel(item.status) }}</span>
              </div>
              <div class="card-time-row">
                {{ formatTime(item.completed_at || item.created_at) }}
              </div>
              <div class="card-stats-row">
                <span class="stat-pill">{{ item.total_samples }} 点位</span>
                <span class="stat-pill">{{ formatReadsCount(item.total_reads) }} Reads</span>
                <span v-if="item.species_count" class="stat-pill highlight">{{ item.species_count }} 物种</span>
              </div>
              <div class="card-action-bar">
                <button
                  type="button"
                  class="btn-card-del"
                  title="彻底删除此任务"
                  @click.stop="emit('deleteTask', item, $event)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-if="historyTasks.length > 0" class="drawer-footer-neo">
          <button type="button" class="btn-clear-history-warn" @click="emit('clearAllHistory')">
            清空全部历史记录
          </button>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped src="./styles/history-drawer.css"></style>
