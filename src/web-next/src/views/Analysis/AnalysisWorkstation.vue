<script setup lang="ts">
import { ref, computed } from 'vue';
import WorkstationSidebar from './components/WorkstationSidebar.vue';
import WorkstationHeader from './components/WorkstationHeader.vue';
import AnalysisIntegrator from './modules/setup/AnalysisIntegrator.vue';
import SummaryMetrics from './modules/viewer/SummaryMetrics.vue';
import DotplotCanvas from './components/DotplotCanvas.vue'; 
import AnalysisVariantTable from './components/AnalysisVariantTable.vue';

const isAnalyzing = ref(false);
const sessions = ref<any[]>([]);
const activeSessionIdx = ref(0);
const activeTab = ref<'plot' | 'diff'>('plot');

const currentSession = computed(() => sessions.value[activeSessionIdx.value] || null);

/**
 * 启动新分析
 */
async function handleRun(payload: any) {
  isAnalyzing.value = true;
  try {
    const bridge = (window as any).pybridge;
    let body: any = { 
      mode: payload.mode,
      task_id: `AN_${Math.random().toString(36).substring(2, 9)}` 
    };

    if (payload.mode === 'pairwise') {
      body.target_path = payload.files[0].path;
      body.query_path = payload.files[1].path;
    } else if (payload.mode === 'reference') {
      body.target_path = payload.files[payload.referenceIdx].path;
      body.file_paths = payload.files.filter((_: any, i: number) => i !== payload.referenceIdx).map((f: any) => f.path);
    } else {
      body.file_paths = payload.files.map((f: any) => f.path);
    }

    const data = await bridge.runSequenceAnalysis(body);
    if (data.success && data.results) {
      // 为新结果生成唯一 ID，防止重复
      const processed = data.results.map((r: any) => ({
        ...r,
        id: r.id || `JOB_${Date.now()}_${Math.random().toString(16).slice(2,8)}`
      }));
      sessions.value = [...processed, ...sessions.value];
      activeSessionIdx.value = 0;
    } else if (data.success) {
      alert('比对完成，但未发现高度一致的匹配区域。');
    } else {
      alert('分析失败: ' + data.error);
    }
  } catch (err: any) {
    alert('连接分析引擎失败');
  } finally {
    isAnalyzing.value = false;
  }
}

/**
 * 历史回溯
 */
async function handleSelectHistory(id: number) {
  // 检查是否已经在会话列表中
  const existingIdx = sessions.value.findIndex(s => s.id === id);
  if (existingIdx !== -1) {
    activeSessionIdx.value = existingIdx;
    return;
  }

  isAnalyzing.value = true;
  try {
    const bridge = (window as any).pybridge;
    const detail = await bridge.fetchAnalysisDetail(id);
    if (detail) {
      // 确保从历史加载的记录也有唯一 ID
      const record = { ...detail, id: detail.id || id };
      sessions.value = [record, ...sessions.value];
      activeSessionIdx.value = 0;
    }
  } catch (err) {
    console.error('History load failed');
  } finally {
    isAnalyzing.value = false;
  }
}

function handleReset() {
  sessions.value = [];
}
</script>

<template>
  <div class="analysis-workstation">
    <!-- 侧边栏：浅色系 -->
    <WorkstationSidebar 
      :currentSessions="sessions"
      :activeIndex="activeSessionIdx"
      @selectSession="(i: number) => activeSessionIdx = i"
      @selectHistory="handleSelectHistory"
      @newAnalysis="handleReset"
    />

    <!-- 主工作区 -->
    <main class="workstation-main">
      <!-- 初始配置界面 -->
      <div v-if="sessions.length === 0" class="setup-overlay">
        <div class="setup-card">
          <AnalysisIntegrator :is-analyzing="isAnalyzing" @run="handleRun" />
        </div>
      </div>

      <!-- 结果分析界面 -->
      <template v-else>
        <WorkstationHeader 
          :title="currentSession.rotated ? '旋转核准完成' : '序列共线深度审计'"
          :subtitle="`${currentSession.target_name} ↔ ${currentSession.query_name}`"
          :isIdentity="currentSession.rotated"
          @back="handleReset"
        />

        <div class="workstation-viewport">
          <div class="scroll-container">
            <div class="content-limit">
              <!-- 数据看板 -->
              <SummaryMetrics 
                :id="currentSession.identity"
                :vars="currentSession.variant_count"
                :rotation="currentSession.rotated"
              />

              <!-- 可视化面板 -->
              <div class="visual-panel">
                <div class="panel-header">
                  <div class="tab-switcher">
                    <button :class="{ active: activeTab === 'plot' }" @click="activeTab = 'plot'">
                      🔍 共线性散点图 (Dotplot)
                    </button>
                    <button :class="{ active: activeTab === 'diff' }" @click="activeTab = 'diff'">
                      📋 变异位点审计 ({{ currentSession.variant_count }})
                    </button>
                  </div>
                  <div class="panel-info">
                    <span class="legend-dot forward"></span> 正向匹配 
                    <span class="legend-dot reverse"></span> 反向互补
                  </div>
                </div>

                <div class="panel-body">
                  <div v-if="activeTab === 'plot'" class="viz-stage animate-fade-in">
                    <!-- 修正长度字段名：q_len, t_len -->
                    <DotplotCanvas 
                      :blocks="currentSession.blocks || []" 
                      :qLen="currentSession.q_len || 0" 
                      :tLen="currentSession.t_len || 0" 
                    />
                    <div class="viz-controls">
                      <span>🖱️ 滚轮缩放 / 拖拽平移 · 双击还原</span>
                    </div>
                  </div>
                  <div v-else class="table-stage animate-slide-up">
                    <AnalysisVariantTable 
                      :variants="currentSession.variants || []" 
                      :totalCount="currentSession.variant_count || 0"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.analysis-workstation {
  display: flex;
  width: 100vw;
  height: 100vh;
  background: white;
  overflow: hidden;
}

.workstation-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  overflow: hidden;
}

.setup-overlay { flex: 1; display: flex; align-items: center; justify-content: center; background: white; }
.setup-card { width: 850px; }

.workstation-viewport {
  flex: 1;
  overflow: hidden;
  position: relative;
}

.scroll-container {
  height: 100%;
  overflow-y: auto;
  padding: 32px;
}
.scroll-container::-webkit-scrollbar { width: 6px; }
.scroll-container::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 10px; }

.content-limit { max-width: 1300px; margin: 0 auto; }

.visual-panel {
  background: white;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 20px rgba(0,0,0,0.02);
  margin-bottom: 40px;
}

.panel-header {
  padding: 8px 16px;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fafbfd;
}

.tab-switcher { display: flex; gap: 4px; }
.tab-switcher button {
  padding: 8px 16px;
  border: none;
  background: none;
  font-size: 0.8rem;
  font-weight: 800;
  color: #64748b;
  cursor: pointer;
  border-radius: 10px;
}
.tab-switcher button.active { background: white; color: #2563eb; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }

.panel-info { font-size: 0.7rem; color: #94a3b8; font-weight: 700; display: flex; align-items: center; gap: 12px; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.legend-dot.forward { background: #3b82f6; }
.legend-dot.reverse { background: #f59e0b; }

.panel-body { padding: 24px; min-height: 550px; }

.viz-stage { height: 600px; display: flex; flex-direction: column; gap: 12px; }
.viz-controls { text-align: center; color: #cbd5e1; font-size: 0.7rem; font-weight: 700; padding: 10px; background: #f8fafc; border-radius: 10px; }

.table-stage { min-height: 500px; }

@keyframes zoomIn { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: scale(1); } }
.animate-fade-in { animation: fadeIn 0.3s ease-out; }
.animate-slide-up { animation: slideUp 0.3s ease-out; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
