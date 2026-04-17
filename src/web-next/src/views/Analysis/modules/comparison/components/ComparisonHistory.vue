<template>
  <div class="comparison-history">
    <div class="history-header">
      <h3><i class="fas fa-history"></i> 历史分析结果</h3>
      <button class="btn-refresh" @click="loadHistory" :disabled="loading">
        <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
      </button>
    </div>

    <div v-if="history.length === 0" class="empty-state">
      <i class="fas fa-folder-open"></i>
      <p>暂无分析历史</p>
    </div>

    <div v-else class="history-list">
      <div 
        v-for="item in history" 
        :key="item.task_id" 
        class="history-item"
        :class="{ active: item.task_id === activeId }"
        @click="$emit('select', item)"
      >
        <div class="item-main">
          <div class="item-title">
            <span class="task-id">{{ item.task_id }}</span>
            <span class="timestamp">{{ formatDate(item.created_at) }}</span>
          </div>
          <div class="comparison-info">
            <span class="file-tag ref">{{ item.ref_name }}</span>
            <i class="fas fa-arrows-alt-h mx-2"></i>
            <span class="file-tag query">{{ item.query_name }}</span>
            <span v-if="item.was_flipped" class="rc-badge" title="已自动反向互补校正">RC</span>
          </div>
          <div class="item-stats" v-if="item.total_matches > 0">
            <span class="stat">
              <i class="fas fa-link"></i> {{ item.total_matches }} 匹配
            </span>
            <span class="stat">
              <i class="fas fa-fingerprint"></i> {{ (item.average_identity).toFixed(1) }}% 一致性
            </span>
            <span class="stat">
              <i class="fas fa-ruler-horizontal"></i> {{ formatLength(item.matched_length) }}
            </span>
          </div>
        </div>
        
        <div class="item-actions">
          <button class="btn-action delete" @click.stop="handleDelete(item.task_id)" title="删除结果">
            <i class="fas fa-trash"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { getBridge } from '../../../../../bridge';

const history = ref<any[]>([]);
const loading = ref(false);

const props = defineProps<{
  activeId?: string
}>();

const emit = defineEmits(['select']);

async function loadHistory() {
  loading.value = true;
  try {
    const res = await getBridge().get_comparison_history();
    history.value = Array.isArray(res) ? res : [];
  } catch (err) {
    console.error('Failed to load history:', err);
  } finally {
    loading.value = false;
  }
}

async function handleDelete(taskId: string) {
  if (!confirm('确定要永久删除该比对结果及关联物理文件吗？')) return;
  
  try {
    const res = await getBridge().delete_comparison_task(taskId);
    if (res.status === 'success') {
      await loadHistory();
    }
  } catch (err) {
    console.error('Delete failed:', err);
  }
}

function formatDate(iso: string) {
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatLength(len: number) {
  if (len > 1000000) return (len / 1000000).toFixed(2) + ' Mb';
  if (len > 1000) return (len / 1000).toFixed(1) + ' Kb';
  return len + ' bp';
}

onMounted(loadHistory);

defineExpose({ refresh: loadHistory });
</script>

<style scoped>
.comparison-history {
  background: var(--surface-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.history-header {
  padding: 16px;
  background: rgba(var(--primary-rgb), 0.05);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-header h3 {
  margin: 0;
  font-size: 1.1rem;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-refresh {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.btn-refresh:hover:not(:disabled) {
  background: rgba(0,0,0,0.05);
  color: var(--primary-color);
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.history-item {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  display: flex;
  transition: all 0.2s;
  cursor: pointer;
}

.history-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  border-color: var(--primary-color);
}

.history-item.active {
  border-left: 4px solid var(--primary-color);
  background: rgba(var(--primary-rgb), 0.03);
  border-color: rgba(var(--primary-rgb), 0.2);
  transform: translateX(4px);
}

.item-main {
  flex: 1;
}

.item-title {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 0.85rem;
}

.task-id {
  font-weight: 600;
  color: var(--primary-color);
  font-family: monospace;
}

.timestamp {
  color: var(--text-secondary);
}

.comparison-info {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 4px;
}

.file-tag {
  font-size: 0.8rem;
  padding: 2px 8px;
  border-radius: 4px;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-tag.ref { background: rgba(0, 120, 212, 0.1); color: #0078d4; }
.file-tag.query { background: rgba(16, 124, 16, 0.1); color: #107c10; }

.rc-badge {
  background: #a430ff;
  color: white;
  font-size: 0.65rem;
  font-weight: bold;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
}

.item-stats {
  display: flex;
  gap: 12px;
}

.stat {
  font-size: 0.75rem;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}

.item-actions {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  margin-left: 12px;
  padding-left: 12px;
  border-left: 2px solid rgba(var(--primary-rgb), 0.1); /* 强化隔离线 */
}

.btn-action {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: #f8fafc; /* 增加底色 */
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.btn-action.view { color: var(--primary-color); border-color: rgba(var(--primary-rgb), 0.1); }
.btn-action.view:hover { background: var(--primary-color); color: white; }
.btn-action.delete { color: #ef4444; border-color: rgba(239, 68, 68, 0.1); }
.btn-action.delete:hover { background: #ef4444; color: white; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 0;
  color: var(--text-secondary);
}

.empty-state i {
  font-size: 3rem;
  margin-bottom: 16px;
  opacity: 0.3;
}
</style>
