<template>
  <div class="comparison-history-pro">
    <div class="history-header">
      <div class="header-spacer"></div>
      <button class="btn-refresh" @click="loadHistory" :disabled="loading" title="刷新列表">
        <svg :class="{ 'spin': loading }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
      </button>
    </div>

    <div class="history-body">
      <div v-if="loading && history.length === 0" class="state-msg">
        <div class="mini-spinner"></div>
        <span>正在同步...</span>
      </div>

      <div v-else-if="history.length === 0" class="empty-state">
        <div class="empty-icon">📂</div>
        <p>暂无分析历史</p>
        <span class="hint">新完成的分析将自动保存</span>
      </div>

      <div v-else class="list-container">
        <div 
          v-for="item in history" 
          :key="item.task_id" 
          class="history-card"
          :class="{ active: item.task_id === activeId }"
          @click="$emit('select', item)"
        >
          <div class="card-top">
            <span class="task-tag">#{{ item.task_id.slice(-6) }}</span>
            <button class="btn-delete" @click.stop="deleteItem(item.task_id)" title="删除记录">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path d="M3 6h18m-2 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
              </svg>
            </button>
          </div>
          
          <div class="file-info">
            <div class="name-row">
              <span class="dot ref"></span>
              <span class="file-name" :title="item.ref_name">{{ item.ref_name }}</span>
            </div>
            <div class="name-row">
              <span class="dot qry"></span>
              <span class="file-name" :title="item.query_name">{{ item.query_name }}</span>
            </div>
          </div>

          <div class="card-stats">
            <span class="stat-pill">{{ (item.average_identity || 0).toFixed(1) }}%</span>
            <span class="stat-pill">{{ formatLength(item.ref_length) }}</span>
            <span class="time">{{ formatDate(item.created_at) }}</span>
          </div>
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

defineProps<{ activeId?: string }>();
defineEmits(['select']);

async function loadHistory() {
  loading.value = true;
  try {
    const bridge = getBridge();
    // 兼容异步延迟
    const res = await bridge.get_comparison_history();
    // 后端返回格式适配
    const data = Array.isArray(res) ? res : (res?.data || []);
    history.value = data.sort((a: any, b: any) => 
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  } catch (err) {
    console.warn('[History] 暂无法获取历史记录:', err);
  } finally {
    loading.value = false;
  }
}

async function deleteItem(taskId: string) {
  if (!confirm('确定要从数据库中永久删除这条分析记录吗？')) return;
  try {
    const bridge = getBridge();
    await bridge.delete_comparison_task(taskId);
    await loadHistory();
  } catch (err) {
    console.error('[History] 删除失败:', err);
  }
}

function formatDate(iso: string) {
  if (!iso) return '--:--';
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatLength(len: number) {
  if (!len) return '0 bp';
  if (len > 1000000) return (len / 1000000).toFixed(1) + 'M';
  if (len > 1000) return (len / 1000).toFixed(0) + 'K';
  return len + 'b';
}

function getParsedMeta(item: any) {
  if (!item.metadata) return {};
  if (typeof item.metadata === 'string') {
    try { return JSON.parse(item.metadata); } catch(e) { return {}; }
  }
  return item.metadata;
}

onMounted(() => {
  // 延迟 300ms 加载，确保桥接完全就绪
  setTimeout(loadHistory, 300);
});

defineExpose({ refresh: loadHistory });
</script>

<style scoped>
.comparison-history-pro {
  height: 100%; display: flex; flex-direction: column; background: transparent;
}

.history-header {
  padding: 0 8px 16px; display: flex; justify-content: space-between; align-items: center;
}
.title-group { display: flex; align-items: center; gap: 8px; color: #1e293b; font-weight: 800; font-size: 14px; }

.btn-refresh {
  width: 28px; height: 28px; border-radius: 8px; border: none; background: #f1f5f9;
  color: #64748b; cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
.btn-refresh:hover { background: #e2e8f0; color: #3b82f6; }
.btn-refresh .spin { animation: rotate 1s linear infinite; }

.history-body { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

.list-container { flex: 1; overflow-y: auto; padding: 4px 8px 20px 4px; display: flex; flex-direction: column; gap: 10px; }

.history-card {
  background: white; border: 1px solid #f1f5f9; border-radius: 12px; padding: 12px;
  cursor: pointer; transition: all 0.2s; position: relative;
}
.history-card:hover { border-color: #3b82f6; transform: translateX(2px); box-shadow: 0 4px 12px rgba(0,0,0,0.03); }
.history-card.active { border-color: #3b82f6; background: #f0f7ff; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1); }

.card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.task-tag { font-size: 10px; font-weight: 700; color: #3b82f6; font-family: monospace; text-transform: uppercase; }

.btn-delete {
  width: 24px; height: 24px; border-radius: 6px; border: none; background: transparent;
  color: #94a3b8; cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s; opacity: 0;
}
.history-card:hover .btn-delete { opacity: 1; }
.btn-delete:hover { background: #fee2e2; color: #ef4444; }

.time { font-size: 9px; color: #cbd5e1; margin-left: auto; font-family: monospace; }

.file-info { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.name-row { display: flex; align-items: center; gap: 6px; }
.dot { width: 4px; height: 4px; border-radius: 50%; }
.dot.ref { background: #3b82f6; }
.dot.qry { background: #10b981; }
.file-name { font-size: 11px; color: #475569; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }

.card-stats { display: flex; gap: 6px; align-items: center; }
.stat-pill { font-size: 9px; font-weight: 700; padding: 2px 6px; background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 4px; color: #64748b; }

.state-msg, .empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 20px; text-align: center; }
.empty-icon { font-size: 24px; margin-bottom: 12px; opacity: 0.5; }
.empty-state p { font-size: 13px; font-weight: 700; color: #64748b; margin: 0; }
.empty-state .hint { font-size: 11px; color: #94a3b8; margin-top: 4px; }

.mini-spinner { width: 16px; height: 16px; border: 2px solid #f1f5f9; border-top-color: #3b82f6; border-radius: 50%; animation: rotate 0.8s linear infinite; margin-bottom: 10px; }

@keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
