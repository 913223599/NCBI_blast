<script setup lang="ts">
import { ref, computed } from 'vue';
import DotplotCanvas from './DotplotCanvas.vue';
import AnalysisVariantTable from './AnalysisVariantTable.vue';
import AnalysisSidebarManager from './AnalysisSidebarManager.vue';

interface FileItem {
  path: string;
  name: string;
}

const files = ref<FileItem[]>([]);
const isAnalyzing = ref(false);
const results = ref<any[]>([]); // 改为数组，存储多个比对结果
const activeResultIndex = ref(0);
const activeTab = ref<'plot' | 'diff'>('plot');

type AnalysisMode = 'pairwise' | 'reference' | 'matrix';
const analysisMode = ref<AnalysisMode>('pairwise');
const referenceIdx = ref(0); // 在参考模式下使用的参考序列索引

const currentResult = computed(() => results.value[activeResultIndex.value] || null);

async function pickFiles() {
  const bridge = (window as any).electronAPI;
  const paths = await bridge.openFileDialog({
    title: '选择需要比对的序列文件',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Fasta Files', extensions: ['fasta', 'fa', 'fna', 'gbk', 'gb'] }]
  });
  
  if (paths) {
    paths.forEach((p: string) => {
      if (!files.value.find(f => f.path === p)) {
        files.value.push({ path: p, name: p.split(/[\\/]/).pop() || p })
      }
    });
  }
}

async function runAnalysis() {
  if (files.value.length < 2) return;
  isAnalyzing.value = true;
  results.value = [];
  activeResultIndex.value = 0;
  
  try {
    const bridge = (window as any).electronAPI;
    const apiPort = await bridge.getApiPort();
    
    let payload: any = { mode: analysisMode.value };

    if (analysisMode.value === 'pairwise') {
      const f0 = files.value[0];
      const f1 = files.value[1];
      if (!f0 || !f1) return;
      payload.target_path = f0.path;
      payload.query_path = f1.path;
    } else if (analysisMode.value === 'reference') {
      const refFile = files.value[referenceIdx.value];
      if (!refFile) return;
      payload.target_path = refFile.path;
      payload.file_paths = files.value.filter((_, i) => i !== referenceIdx.value).map(f => f.path);
    } else {
      payload.file_paths = files.value.map(f => f.path);
    }

    const response = await fetch(`http://127.0.0.1:${apiPort}/api/analysis/align`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const data = await response.json();
    if (data.success) {
      results.value = data.results;
    } else {
      alert('分析失败: ' + (data.error || '未知错误'));
    }
  } catch (err) {
    console.error('Analysis failed:', err);
    alert('请求失败，请检查后端服务');
  } finally {
    isAnalyzing.value = false;
  }
}

function removeFile(index: number) {
  files.value.splice(index, 1);
  if (referenceIdx.value >= files.value.length) referenceIdx.value = 0;
}

async function loadHistoryRecord(id: number) {
  isAnalyzing.value = true;
  try {
    const detail = await (window as any).electronAPI.fetchAnalysisDetail(id);
    if (detail) {
      // 注入历史记录到当前视图
      results.value = [detail];
      activeResultIndex.value = 0;
    }
  } catch (err) {
    console.error('Failed to load history record:', err);
  } finally {
    isAnalyzing.value = false;
  }
}
</script>

<template>
  <div class="dotplot-workspace">
    <div class="results-layout">
       <!-- 侧边栏常驻：方便点击“往期历史”拉取历史记录 -->
       <AnalysisSidebarManager 
         :current-results="results" 
         :active-index="activeResultIndex"
         @select-session="(idx) => activeResultIndex = idx"
         @select-history="loadHistoryRecord"
       />

       <div class="main-display scroll-v">
          <!-- 任务准备模式 (无结果时显示) -->
          <div class="setup-panel shadow-sm" v-if="results.length === 0 && !isAnalyzing">
            <div class="panel-header">
              <div class="title-wrap">
                <h2>全场景序列验证调度中心</h2>
                <p>支持多模式交叉验证，深度探测环状序列旋转一致性与结构变异。</p>
              </div>
              <div class="mode-selector">
                <button 
                  v-for="m in ([{id:'pairwise', l:'两两比对'}, {id:'reference', l:'参考模式'}, {id:'matrix', l:'矩阵比对'}])" 
                  :key="m.id"
                  :class="{ active: analysisMode === m.id }"
                  @click="analysisMode = m.id as AnalysisMode"
                >
                  {{ m.l }}
                </button>
              </div>
            </div>

            <div class="file-tray">
              <div class="tray-header">
                 <span>待分析序列 ({{ files.length }})</span>
                 <button class="btn-text-add" @click="pickFiles">+ 批量导入</button>
              </div>
              <div v-if="files.length === 0" class="empty-state" @click="pickFiles">
                 <div class="empty-icon">📂</div>
                 <p>请导入至少两份序列文件进行比对分析</p>
              </div>
              <div v-else class="file-grid">
                 <div v-for="(file, idx) in files" :key="file.path" 
                      class="file-card" 
                      :class="{ 'is-ref': analysisMode === 'reference' && referenceIdx === idx }"
                      @click="analysisMode === 'reference' ? referenceIdx = idx : null">
                    <div class="card-info">
                      <span class="ref-badge" v-if="analysisMode === 'reference' && referenceIdx === idx">REF</span>
                      <span class="idx" v-else>{{ idx + 1 }}</span>
                      <span class="name">{{ file.name }}</span>
                    </div>
                    <button class="btn-remove" @click.stop="removeFile(idx)">×</button>
                 </div>
              </div>
            </div>

            <div class="action-footer">
              <div class="mode-tip" v-if="analysisMode === 'reference'">💡 提示：已选定上图中标记为 <b>REF</b> 的序列作为唯一参考。</div>
              <div class="mode-tip" v-if="analysisMode === 'matrix'">💡 提示：所有序列将进行全两两交叉比对 (n*(n-1)/2)。</div>
              <button 
                class="btn-primary-run" 
                :disabled="files.length < 2 || isAnalyzing"
                @click="runAnalysis"
              >
                <span v-if="isAnalyzing" class="loader"></span>
                {{ isAnalyzing ? '正在计算中...' : '提交分析任务' }}
              </button>
            </div>
          </div>

          <!-- 分析展示模式 (有结果或分析中) -->
          <div class="workspace-views" v-else>
            <div class="workspace-header" v-if="results.length > 0">
               <button class="btn-back-setup" @click="results = []">← 返回设置界面 (重新发起比对)</button>
            </div>

            <!-- 分析汇总卡片 -->
            <div class="summary-shelf" v-if="currentResult" :class="{ 'is-rotated': currentResult.rotated }">
              <div class="shelf-stat">
                  <div class="val">{{ currentResult.identity }}<span class="pct">%</span></div>
                  <div class="label">一致度</div>
              </div>
              <div class="shelf-content">
                  <div class="shelf-title">
                    <h3>{{ currentResult.rotated ? '确认为同一环状基因组' : '发现局部序列差异' }}</h3>
                    <div class="comp-label">{{ currentResult.target_name }} vs {{ currentResult.query_name }}</div>
                  </div>
                  <p class="shelf-description">{{ currentResult.message }}</p>
              </div>
            </div>

            <!-- 核心数据看板 -->
            <div class="visual-shelf shadow-sm" v-if="currentResult">
              <div class="shelf-header">
                <div class="tab-group">
                  <button class="tab-btn" :class="{active: activeTab === 'plot'}" @click="activeTab = 'plot'">共线性点图</button>
                  <button class="tab-btn" :class="{active: activeTab === 'diff'}" @click="activeTab = 'diff'">
                    差异位点详情 <span class="v-count" v-if="currentResult.variant_count">{{ currentResult.variant_count }}</span>
                  </button>
                </div>
                <div class="controls" v-if="activeTab === 'plot'">
                  <span class="legend-item"><span class="dot p"></span> 正向</span>
                  <span class="legend-item"><span class="dot m"></span> 反向</span>
                </div>
              </div>
              
              <div class="canvas-box" v-if="activeTab === 'plot'">
                  <DotplotCanvas 
                    :blocks="currentResult.blocks" 
                    :q-len="currentResult.q_len" 
                    :t-len="currentResult.t_len" 
                  />
              </div>

              <div class="diff-box scroll-v" v-else>
                  <AnalysisVariantTable 
                    :variants="currentResult.variants" 
                    :total-count="currentResult.variant_count" 
                  />
              </div>
            </div>

            <div v-if="isAnalyzing && results.length === 0" class="global-loading">
               <div class="loading-spinner"></div>
               <p>正在执行高精度 Minimap2 比对，并评估环状旋转差异，请稍候...</p>
            </div>
          </div>
       </div>
    </div>
  </div>
</template>

<style scoped>
.dotplot-workspace { height: 100%; display: flex; flex-direction: column; overflow: hidden; background: #f8fafc; }
.shadow-sm { box-shadow: 0 1px 4px rgba(0,0,0,0.08); }

.results-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 20px; height: 100%; padding: 20px; overflow: hidden; }

.main-display { display: flex; flex-direction: column; gap: 20px; min-width: 0; }

/* 设置面板 */
.setup-panel { background: white; border-radius: 20px; padding: 24px 28px; border: 1px solid #e2e8f0; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.title-wrap h2 { margin: 0; font-size: 1.25rem; color: #0f172a; font-weight: 800; letter-spacing: -0.02em; }
.title-wrap p { margin: 6px 0 0; font-size: 0.85rem; color: #64748b; }

.mode-selector { display: flex; background: #f1f5f9; padding: 4px; border-radius: 12px; }
.mode-selector button { border: none; background: none; padding: 8px 16px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; color: #64748b; cursor: pointer; transition: all 0.2s; }
.mode-selector button.active { background: white; color: #2563eb; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }

.file-tray { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 16px; }
.tray-header { display: flex; justify-content: space-between; font-size: 0.7rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 0.05em; }
.btn-text-add { background: none; border: none; color: #2563eb; font-weight: 800; cursor: pointer; font-size: 0.75rem; }

.empty-state { padding: 40px; text-align: center; border: 2px dashed #e2e8f0; border-radius: 12px; cursor: pointer; }
.empty-icon { font-size: 2rem; margin-bottom: 10px; }

.file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.file-card { background: white; border: 1px solid #e2e8f0; padding: 8px 12px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.2s; }
.file-card.is-ref { border-color: #2563eb; background: #eff6ff; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.05); }

.card-info { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ref-badge { background: #2563eb; color: white; padding: 1px 4px; border-radius: 3px; font-size: 9px; font-weight: 900; }
.idx { background: #f1f5f9; color: #64748b; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; border-radius: 4px; font-size: 9px; font-weight: 800; }
.name { font-size: 0.75rem; color: #334155; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn-remove { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 1.1rem; line-height: 1; }

.action-footer { display: flex; justify-content: flex-end; align-items: center; gap: 20px; margin-top: 20px; padding-top: 16px; border-top: 1px solid #f1f5f9; }
.mode-tip { font-size: 0.8rem; color: #64748b; background: #fffcf0; padding: 4px 12px; border-radius: 6px; border: 1px solid #fffae5; }
.btn-primary-run { background: #0f172a; color: white; border: none; padding: 12px 36px; border-radius: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 10px; font-size: 0.9rem; }
.btn-primary-run:hover:not(:disabled) { background: #1e293b; transform: scale(1.02); }

/* 工作区展示 */
.workspace-views { display: flex; flex-direction: column; gap: 20px; }
.workspace-header { display: flex; margin-bottom: -10px; }
.btn-back-setup { border: none; background: #fff; border: 1px solid #e2e8f0; color: #64748b; padding: 8px 16px; border-radius: 10px; font-size: 0.8rem; font-weight: 800; cursor: pointer; }
.btn-back-setup:hover { color: #2563eb; border-color: #2563eb; }

.summary-shelf { background: white; border-radius: 20px; border: 1px solid #e2e8f0; padding: 24px 32px; display: flex; align-items: center; gap: 40px; position: relative; overflow: hidden; }
.summary-shelf::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: #e2e8f0; }
.is-rotated .summary-shelf::before { background: #22c55e; }

.shelf-stat { text-align: center; min-width: 120px; }
.shelf-stat .val { font-size: 3.2rem; font-weight: 900; color: #0f172a; line-height: 0.9; letter-spacing: -0.04em; }
.shelf-stat .pct { font-size: 1rem; color: #94a3b8; margin-left: 2px; }
.shelf-stat .label { font-size: 0.65rem; color: #94a3b8; font-weight: 800; text-transform: uppercase; margin-top: 8px; letter-spacing: 0.05em; }

.shelf-title { margin-bottom: 6px; }
.shelf-title h3 { margin: 0 0 4px; font-size: 1.1rem; color: #0f172a; font-weight: 800; }
.comp-label { font-size: 0.7rem; color: #64748b; font-weight: 600; padding: 2px 8px; background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 6px; width: fit-content; }
.shelf-description { margin: 8px 0 0; font-size: 0.9rem; color: #475569; line-height: 1.6; }

.visual-shelf { background: white; border-radius: 20px; border: 1px solid #e2e8f0; overflow: hidden; }
.shelf-header { padding: 14px 24px; border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; background: #fff; }
.tab-group { display: flex; gap: 4px; }
.tab-btn { background: none; border: none; padding: 8px 16px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; color: #64748b; cursor: pointer; transition: all 0.2s; }
.tab-btn.active { background: #f1f5f9; color: #1e293b; }
.v-count { background: #fee2e2; color: #ef4444; padding: 1px 6px; border-radius: 10px; font-size: 10px; margin-left: 4px; }

.canvas-box { min-height: 500px; padding: 12px; display: flex; align-items: center; justify-content: center; }
.diff-box { height: 500px; padding: 0; background: white; overflow-x: auto; }

.controls { display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 0.75rem; color: #64748b; font-weight: 600; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot.p { background: #2563eb; }
.dot.m { background: #ef4444; }

.global-loading { height: 500px; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #64748b; gap: 16px; font-size: 0.9rem; }
.loading-spinner { width: 40px; height: 40px; border: 4px solid #f1f5f9; border-top-color: #2563eb; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.loader { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 1s linear infinite; }
</style>
