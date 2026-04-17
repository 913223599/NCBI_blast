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

const props = defineProps<{
  currentSessions: any[];
  activeIndex: number;
}>();

const emit = defineEmits<{
  (e: 'selectSession', index: number): void;
  (e: 'selectHistory', recordId: number): void;
  (e: 'newAnalysis'): void;
}>();

const activeTab = ref<'session' | 'history'>('session');
const history = ref<HistoryRecord[]>([]);
const isLoading = ref(false);

async function loadHistory(sync = false) {
  isLoading.value = true;
  try {
    const bridge = (window as any).pybridge;
    if (!bridge) return;
    if (sync) await bridge.syncAnalysisHistory?.();
    const res = await bridge.fetchAnalysisHistory();
    history.value = Array.isArray(res) ? res : (res.data || []);
  } catch (err) {
    console.error('[Sidebar] History failed:', err);
  } finally {
    isLoading.value = false;
  }
}

async function removeRecord(id: number, event: Event) {
  event.stopPropagation();
  if (confirm('彻底删除？这会同时清理磁盘文件夹且不可找回。')) {
    const bridge = (window as any).pybridge;
    await bridge.deleteAnalysisHistory(id);
    await loadHistory();
  }
}

onMounted(() => setTimeout(() => loadHistory(), 300));
</script>

<template>
  <aside class="workstation-sidebar">
    <div class="sidebar-header">
      <div class="branding">ANALYSIS<span>WORKSTATION</span></div>
      <button class="btn-create-task" @click="emit('newAnalysis')">
        <span class="plus">+</span> 发起比对
      </button>
    </div>

    <div class="nav-tabs">
      <div class="tab-pill" :class="{ active: activeTab === 'session' }" @click="activeTab = 'session'">
        当前会话
        <span class="count" v-if="currentSessions.length">{{ currentSessions.length }}</span>
      </div>
      <div class="tab-pill" :class="{ active: activeTab === 'history' }" @click="activeTab = 'history'">
        历史审计
      </div>
    </div>

    <div class="sidebar-content">
      <!-- 当前会话列表 -->
      <div v-if="activeTab === 'session'" class="list-container">
        <div v-if="currentSessions.length === 0" class="empty-state">
          <p>无活跃任务</p>
          <small>点击上方按钮开始</small>
        </div>
        <div v-for="(res, idx) in currentSessions" :key="idx" 
             class="session-item" :class="{ active: activeIndex === idx }"
             @click="emit('selectSession', idx)">
          <div class="dot" :class="{ rotated: res.rotated }"></div>
          <div class="info">
            <div class="title">{{ res.query_name }}</div>
            <div class="meta">{{ res.target_name }} · {{ res.identity }}%</div>
          </div>
        </div>
      </div>

      <!-- 历史记录列表 -->
      <div v-else class="list-container">
        <div class="sync-bar">
          <span class="label">存盘记录</span>
          <button class="btn-sync" :class="{ loading: isLoading }" @click="loadHistory(true)">🔄</button>
        </div>
        <div v-for="item in history" :key="item.id" class="history-item" @click="emit('selectHistory', item.id)">
          <div class="h-header">
            <span class="date">{{ item.timestamp?.split(' ')[0] }}</span>
            <span class="mode">{{ item.mode }}</span>
          </div>
          <div class="h-body">
            <b>Que:</b> {{ item.query_name }}
          </div>
          <div class="h-footer">
            <span>{{ item.identity }}% ID</span>
            <button class="btn-del" @click="removeRecord(item.id, $event)">✕</button>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.workstation-sidebar {
  width: 300px;
  min-width: 300px;
  background: white;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e2e8f0;
  color: #64748b;
  height: 100vh;
}

.sidebar-header { padding: 32px 24px 20px; }
.branding { font-size: 0.85rem; font-weight: 900; color: #1e293b; letter-spacing: 0.05em; margin-bottom: 24px; display: flex; align-items: center; gap: 8px; }
.branding::before { content: '🧬'; font-size: 1.1rem; }
.branding span { color: #2563eb; opacity: 1; margin-left: 4px; }

.btn-create-task {
  width: 100%;
  padding: 11px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(37,99,235,0.15);
}
.btn-create-task:hover { background: #1d4ed8; transform: translateY(-1px); }

.nav-tabs { display: flex; padding: 4px; gap: 4px; background: #f8fafc; margin: 0 20px 24px; border-radius: 10px; border: 1px solid #f1f5f9; }
.tab-pill {
  flex: 1;
  padding: 8px 4px;
  text-align: center;
  font-size: 0.75rem;
  font-weight: 800;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s;
  color: #94a3b8;
  position: relative;
}
.tab-pill.active { background: white; color: #1e293b; box-shadow: 0 2px 6px rgba(0,0,0,0.04); }
.tab-pill .count { margin-left: 4px; background: #ef4444; color: white; font-size: 9px; padding: 1px 5px; border-radius: 8px; vertical-align: middle; }

.sidebar-content { flex: 1; overflow-y: auto; padding: 0 16px 20px; }
.sidebar-content::-webkit-scrollbar { width: 4px; }
.sidebar-content::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 10px; }

.session-item {
  padding: 12px 14px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
  transition: 0.2s;
}
.session-item:hover { background: #f8fafc; }
.session-item.active { background: #eff6ff; border-color: #dbeafe; }
.session-item .dot { width: 8px; height: 8px; border-radius: 50%; background: #e2e8f0; }
.session-item .dot.rotated { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,0.3); }
.session-item .title { font-size: 0.8rem; font-weight: 700; color: #334155; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-item .meta { font-size: 0.7rem; color: #94a3b8; margin-top: 2px; }

.history-item {
  padding: 14px;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 14px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.history-item:hover { border-color: #3b82f6; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.03); }
.h-header { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 0.65rem; color: #94a3b8; }
.mode { padding: 1px 5px; background: #eff6ff; border-radius: 4px; color: #2563eb; font-weight: 800; }
.h-body { font-size: 0.75rem; font-weight: 700; color: #1e293b; margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.h-footer { display: flex; justify-content: space-between; align-items: center; font-size: 0.7rem; color: #64748b; border-top: 1px solid #f8fafc; padding-top: 8px; }

.sync-bar { display: flex; justify-content: space-between; align-items: center; padding: 0 8px 12px; }
.btn-sync { background: none; border: none; color: #94a3b8; cursor: pointer; transition: 0.5s; }
.btn-sync.loading { animation: spin 1s infinite linear; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.btn-del:hover { color: #ef4444; }
.empty-state { text-align: center; padding: 40px 0; color: #94a3b8; }
</style>
