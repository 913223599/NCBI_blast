<script setup lang="ts">
import { ref } from 'vue';
import { useComparison } from './composables/useComparison';
import { getBridge } from '../../../../bridge';
import ComparisonControl from './components/ComparisonControl.vue';
import CollinearityPlot from './components/CollinearityPlot.vue';
import ComparisonHistory from './components/ComparisonHistory.vue';

const { isRunning, result, error, startAnalysis } = useComparison();
const historyRef = ref<any>(null);
const activeTaskId = ref<string>('');

async function onRun(refFile: string, queryFile: string) {
  await startAnalysis(refFile, queryFile);
  historyRef.value?.refresh();
}

async function onHistorySelect(item: any) {
  activeTaskId.value = item.task_id;
  try {
    const detail = await getBridge().get_comparison_task_results(item.task_id);
    result.value = {
      ...detail,
      summary: {
        total_matches: item.total_matches,
        average_identity: item.average_identity,
        matched_length: item.matched_length
      }
    };
  } catch (err) {
    console.error('Failed to load history detail:', err);
  }
}
</script>

<template>
  <div class="comparison-module">
    <div class="top-section">
      <ComparisonControl :is-running="isRunning" @run="onRun" />
    </div>
    
    <div class="main-layout">
      <!-- 左侧：历史记录 -->
      <aside class="history-sidebar">
        <ComparisonHistory 
          ref="historyRef" 
          :active-id="activeTaskId"
          @select="onHistorySelect" 
        />
      </aside>

      <!-- 右侧：绘图与统计 -->
      <main class="content-area">
        <div v-if="error" class="error-banner">
          <span class="icon">⚠️</span> {{ error }}
        </div>

        <div v-if="result" class="results-viewer card-neo">
          <div class="plot-container">
            <CollinearityPlot 
              :alignments="result.alignments" 
              :metadata="result.metadata" 
            />
          </div>
          
          <div class="results-footer">
            <div class="stats-group">
               <div class="stat-item">
                  <span class="label">Matched Fragments</span>
                  <span class="value">{{ result.summary?.total_matches || 0 }}</span>
               </div>
               <div class="stat-item">
                  <span class="label">Avg. Identity</span>
                  <span class="value">{{ result.summary?.average_identity?.toFixed(1) || 0 }}%</span>
               </div>
            </div>

            <div v-if="result.metadata?.was_flipped" class="auto-fix-pill">
               <i class="fas fa-magic"></i> Auto-Oriented (RC)
            </div>
          </div>
        </div>

        <div v-else-if="!isRunning" class="welcome-placeholder">
           <div class="placeholder-content">
             <i class="fas fa-chart-area"></i>
             <p>Select sequences above or load from history</p>
           </div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.comparison-module { 
  display: flex; 
  flex-direction: column; 
  gap: 16px; 
  padding: 0 10px 20px;
}

.top-section {
  flex-shrink: 0;
}

.main-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.history-sidebar {
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.results-viewer {
  height: 380px; /* 进一步瘦身高 */
  max-width: 850px; /* 限制宽度，防止横向拉伸过快 */
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  box-shadow: 0 4px 12px rgba(0,0,0,0.03);
  overflow: visible;
}

.plot-container {
  flex: 1;
  background: #fbfcfe;
  position: relative;
}

.results-footer {
  padding: 12px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  border-top: 1px solid var(--border-color);
}

.stats-group { display: flex; gap: 24px; }
.stat-item { display: flex; flex-direction: column; }
.stat-item .label { font-size: 0.6rem; color: #94a3b8; font-weight: 700; text-transform: uppercase; }
.stat-item .value { font-size: 1rem; font-weight: 800; color: #0f172a; }

.auto-fix-pill {
  padding: 6px 14px;
  background: #f5f3ff;
  color: #7c3aed;
  border: 1px solid #ddd6fe;
  border-radius: 30px;
  font-size: 0.75rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 6px;
}

.welcome-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8fafc;
  border: 2px dashed #cbd5e1;
  border-radius: 20px;
  margin: 10px;
}

.placeholder-content {
  text-align: center;
  color: #94a3b8;
}

.placeholder-content i { font-size: 4.5rem; margin-bottom: 24px; opacity: 0.2; }
.placeholder-content p { font-size: 1rem; font-weight: 500; }

.error-banner { background: #fef2f2; color: #dc2626; padding: 16px 24px; border-radius: 14px; margin-bottom: 16px; border: 1px solid #fee2e2; display: flex; gap: 12px; align-items: center; font-weight: 600; }
</style>
