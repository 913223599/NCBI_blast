<script setup lang="ts">
import { ref } from 'vue';
import AnalysisHistorySidebar from './AnalysisHistorySidebar.vue';

const props = defineProps<{
  currentResults: any[];
  activeIndex: number;
}>();

const emit = defineEmits<{
  (e: 'selectSession', index: number): void;
  (e: 'selectHistory', recordId: number): void;
}>();

const activeTab = ref<'session' | 'history'>('session');
</script>

<template>
  <div class="analysis-sidebar-manager shadow-sm">
    <div class="sidebar-tabs">
      <button :class="{ active: activeTab === 'session' }" @click="activeTab = 'session'">当前比对</button>
      <button :class="{ active: activeTab === 'history' }" @click="activeTab = 'history'">往期历史</button>
    </div>

    <div class="sidebar-body">
      <!-- 当前会话列表 -->
      <div v-if="activeTab === 'session'" class="session-list">
        <div class="sidebar-header">比对结果 ({{ currentResults.length }})</div>
        <div class="result-items scroll-v">
           <div v-for="(res, idx) in currentResults" :key="idx" 
                class="res-item" 
                :class="{ active: activeIndex === idx, 'is-rotated': res.rotated }"
                @click="emit('selectSession', idx)">
              <div class="res-header">
                 <span class="res-title">{{ res.target_name }} vs {{ res.query_name }}</span>
                 <span class="res-badge" v-if="res.rotated">旋转变体</span>
              </div>
              <div class="res-sub">Identity: {{ res.identity }}% | Variants: {{ res.variant_count }}</div>
           </div>
        </div>
      </div>

      <!-- 历史记录列表 -->
      <AnalysisHistorySidebar 
        v-else 
        @select="(id) => emit('selectHistory', id)" 
      />
    </div>
  </div>
</template>

<style scoped>
.analysis-sidebar-manager { 
  background: white; 
  border-radius: 20px; 
  border: 1px solid #e2e8f0; 
  display: flex; 
  flex-direction: column; 
  height: 750px; 
  overflow: hidden; 
}

.sidebar-tabs { 
  display: flex; 
  background: #f8fafc; 
  border-bottom: 1px solid #e2e8f0; 
  padding: 4px;
}
.sidebar-tabs button { 
  flex: 1; 
  border: none; 
  background: none; 
  padding: 10px; 
  font-size: 0.8rem; 
  font-weight: 800; 
  color: #64748b; 
  cursor: pointer; 
  border-radius: 12px;
  transition: all 0.2s;
}
.sidebar-tabs button.active { 
  background: white; 
  color: #2563eb; 
  box-shadow: 0 2px 4px rgba(0,0,0,0.05); 
}

.sidebar-body { flex: 1; overflow: hidden; position: relative; }
.sidebar-header { padding: 14px 20px; background: #fff; border-bottom: 1px solid #f1f5f9; font-size: 0.75rem; font-weight: 800; color: #64748b; text-transform: uppercase; }

.result-items { flex: 1; padding: 10px; display: flex; flex-direction: column; gap: 8px; max-height: 680px; }
.res-item { padding: 12px; border-radius: 12px; border: 1px solid #f1f5f9; cursor: pointer; transition: all 0.2s; display: flex; flex-direction: column; gap: 4px; background: white; }
.res-item:hover { background: #f8fafc; border-color: #cbd5e1; }
.res-item.active { border-color: #2563eb; background: #eff6ff; box-shadow: 0 4px 12px rgba(37,99,235,0.06); }
.res-item.is-rotated { border-left: 4px solid #22c55e; }
.res-item.is-rotated.active { border-color: #22c55e; }

.res-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
.res-title { font-size: 0.8rem; font-weight: 700; color: #1e293b; line-height: 1.4; flex: 1; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.res-sub { font-size: 0.7rem; color: #94a3b8; font-weight: 600; }
.res-badge { font-size: 9px; color: #16a34a; background: white; padding: 1px 4px; border-radius: 4px; border: 1px solid #bcf0da; font-weight: 800; white-space: nowrap; flex-shrink: 0; }
</style>
