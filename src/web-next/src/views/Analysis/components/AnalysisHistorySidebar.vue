<script setup lang="ts">
import { ref, onMounted } from 'vue';

interface HistoryRecord {
  id: number;
  timestamp: string;
  mode: string;
  query_name: string;
  target_name: string;
  identity: number;
  variant_count: number;
  rotated: boolean;
}

const emit = defineEmits<{
  (e: 'select', recordId: number): void;
}>();

const history = ref<HistoryRecord[]>([]);
const isLoading = ref(false);

async function loadHistory() {
  isLoading.value = true;
  try {
    const res = await (window as any).electronAPI.fetchAnalysisHistory();
    if (res && res.data) {
      history.value = res.data;
    }
  } finally {
    isLoading.value = false;
  }
}

async function removeRecord(id: number) {
  if (confirm('确定要删除这条比对历史吗？')) {
    await (window as any).electronAPI.deleteAnalysisHistory(id);
    await loadHistory();
  }
}

onMounted(loadHistory);
</script>

<template>
  <div class="analysis-history-sidebar">
    <div class="sidebar-header">
      <span>比对审计历史</span>
      <button class="btn-refresh" @click="loadHistory" :disabled="isLoading">
        <span class="icon" :class="{ spinning: isLoading }">🔄</span>
      </button>
    </div>

    <div class="history-list scroll-v">
      <div v-if="history.length === 0" class="empty-state">
        <p>暂无比对记录</p>
      </div>
      
      <div v-for="item in history" :key="item.id" 
           class="history-card" 
           :class="{ 'is-rotated': item.rotated }"
           @click="emit('select', item.id)">
        <div class="card-top">
          <span class="timestamp">{{ item.timestamp }}</span>
          <span class="mode">{{ item.mode }}</span>
        </div>
        <div class="names">
          <div class="name-row">Ref: {{ item.target_name }}</div>
          <div class="name-row">Que: {{ item.query_name }}</div>
        </div>
        <div class="card-footer">
          <div class="stats">
            <span class="stat-item">Identity: <b>{{ item.identity }}%</b></span>
            <span class="stat-item">Variants: <b>{{ item.variant_count }}</b></span>
          </div>
          <button class="btn-del" @click.stop="removeRecord(item.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-history-sidebar { display: flex; flex-direction: column; height: 100%; height: 750px; background: white; border-radius: 20px; border: 1px solid #e2e8f0; overflow: hidden; }
.sidebar-header { padding: 16px 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; font-weight: 800; color: #64748b; text-transform: uppercase; }

.btn-refresh { border: none; background: none; cursor: pointer; color: #2563eb; }
.icon.spinning { display: inline-block; animation: spin 1s linear infinite; }

.history-list { flex: 1; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.history-card { padding: 12px; border-radius: 12px; border: 1px solid #f1f5f9; cursor: pointer; transition: all 0.2s; background: white; }
.history-card:hover { border-color: #2563eb; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.history-card.is-rotated { border-left: 4px solid #22c55e; background: #f0fdf4; }

.card-top { display: flex; justify-content: space-between; font-size: 0.7rem; color: #94a3b8; font-weight: 700; margin-bottom: 8px; }
.mode { text-transform: uppercase; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; color: #64748b; }

.names { margin-bottom: 10px; }
.name-row { font-size: 0.8rem; color: #1e293b; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.5; }

.card-footer { display: flex; justify-content: space-between; align-items: center; padding-top: 8px; border-top: 1px solid #f1f5f9; }
.stats { display: flex; gap: 10px; font-size: 0.75rem; color: #64748b; }
.stats b { color: #1e293b; }

.btn-del { border: none; background: none; color: #ef4444; font-size: 0.7rem; font-weight: 700; cursor: pointer; padding: 4px; border-radius: 4px; }
.btn-del:hover { background: #fee2e2; }

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.empty-state { text-align: center; color: #94a3b8; padding: 40px; font-size: 0.85rem; font-style: italic; }
</style>
