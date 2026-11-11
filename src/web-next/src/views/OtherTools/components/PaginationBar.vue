<script setup lang="ts">
/**
 * PaginationBar - 通用表格/列表分页栏组件
 * 职责：展示总数与页码，提供页码跳转、首页/末页及每页条数切换。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    total: number
    page: number
    pageSize: number
    pageSizeOptions?: number[]
    loading?: boolean
  }>(),
  {
    pageSizeOptions: () => [5, 10, 20, 50],
    loading: false
  }
)

const emit = defineEmits<{
  (e: 'update:page', value: number): void
  (e: 'update:pageSize', value: number): void
  (e: 'change', payload: { page: number; pageSize: number }): void
}>()

const totalPages = computed(() => Math.max(1, Math.ceil((props.total || 0) / Math.max(1, props.pageSize || 10))))
const safePage = computed(() => Math.min(Math.max(1, props.page || 1), totalPages.value))

const visiblePages = computed<Array<number | '...'>>(() => {
  const tp = totalPages.value
  const cur = safePage.value
  if (tp <= 7) {
    return Array.from({ length: tp }, (_, i) => i + 1)
  }
  const pages: Array<number | '...'> = [1]
  const left = Math.max(2, cur - 1)
  const right = Math.min(tp - 1, cur + 1)
  if (left > 2) pages.push('...')
  for (let p = left; p <= right; p += 1) {
    pages.push(p)
  }
  if (right < tp - 1) pages.push('...')
  pages.push(tp)
  return pages
})

function goPage(nextPage: number): void {
  if (props.loading) return
  const clamped = Math.min(Math.max(1, nextPage), totalPages.value)
  if (clamped === safePage.value) return
  emit('update:page', clamped)
  emit('change', { page: clamped, pageSize: props.pageSize })
}

function handleSizeChange(ev: Event): void {
  const nextSize = Number((ev.target as HTMLSelectElement).value) || 10
  emit('update:pageSize', nextSize)
  emit('update:page', 1)
  emit('change', { page: 1, pageSize: nextSize })
}
</script>

<template>
  <div class="pagination-bar">
    <div class="pg-info">
      共 <strong>{{ total }}</strong> 条 · 第 {{ safePage }} / {{ totalPages }} 页
    </div>
    <div class="pg-controls">
      <label class="pg-size-label">
        <span>每页</span>
        <select :value="pageSize" :disabled="loading" class="pg-select" @change="handleSizeChange">
          <option v-for="opt in pageSizeOptions" :key="opt" :value="opt">{{ opt }} 条</option>
        </select>
      </label>

      <div class="pg-buttons">
        <button class="pg-btn" :disabled="loading || safePage <= 1" @click="goPage(1)">首页</button>
        <button class="pg-btn" :disabled="loading || safePage <= 1" @click="goPage(safePage - 1)">上一页</button>

        <template v-for="(item, idx) in visiblePages" :key="idx">
          <span v-if="item === '...'" class="pg-ellipsis">...</span>
          <button
            v-else
            :class="['pg-btn', { active: item === safePage }]"
            :disabled="loading"
            @click="goPage(item)"
          >
            {{ item }}
          </button>
        </template>

        <button class="pg-btn" :disabled="loading || safePage >= totalPages" @click="goPage(safePage + 1)">下一页</button>
        <button class="pg-btn" :disabled="loading || safePage >= totalPages" @click="goPage(totalPages)">末页</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 14px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  font-size: 12px;
  color: #475569;
}

.pg-info strong {
  color: #0f172a;
}

.pg-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.pg-size-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pg-select {
  padding: 3px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  background: white;
  font-size: 12px;
  color: #334155;
}

.pg-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

.pg-btn {
  min-width: 28px;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  background: white;
  color: #334155;
  font-size: 12px;
  cursor: pointer;
}

.pg-btn:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #2563eb;
}

.pg-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
  font-weight: 600;
}

.pg-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pg-ellipsis {
  padding: 0 4px;
  color: #94a3b8;
}
</style>
