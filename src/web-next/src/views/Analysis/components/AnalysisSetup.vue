<script setup lang="ts">
import { ref } from 'vue';

interface FileItem {
  path: string;
  name: string;
}

export type AnalysisMode = 'pairwise' | 'reference' | 'matrix';

const props = defineProps<{
  isAnalyzing: boolean;
}>();

const emit = defineEmits<{
  (e: 'run', payload: { mode: AnalysisMode; files: FileItem[]; referenceIdx: number }): void;
}>();

const files = ref<FileItem[]>([]);
const analysisMode = ref<AnalysisMode>('pairwise');
const referenceIdx = ref(0);

async function pickFiles() {
  const bridge = (window as any).pybridge;
  if (!bridge) {
    alert('系统初始化中，请稍后...');
    return;
  }
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

function removeFile(index: number) {
  files.value.splice(index, 1);
  if (referenceIdx.value >= files.value.length) referenceIdx.value = 0;
}

function handleRun() {
  emit('run', { 
    mode: analysisMode.value, 
    files: [...files.value], 
    referenceIdx: referenceIdx.value 
  });
}
</script>

<template>
  <div class="analysis-setup-card animate-fade-in">
    <div class="setup-header">
      <div class="header-content">
        <div class="badge">Advanced Engine</div>
        <h2>全场景序列验证调度中心</h2>
        <p>基于 Minimap2 核心算法，深度探测基因组差异与结构变异。</p>
      </div>
      <div class="mode-pills">
        <button v-for="m in ([{id:'pairwise', l:'两两比对'}, {id:'reference', l:'参考模式'}, {id:'matrix', l:'矩阵比对'}])" 
                :key="m.id"
                :class="{ active: analysisMode === m.id }"
                @click="analysisMode = m.id as AnalysisMode">
          {{ m.l }}
        </button>
      </div>
    </div>

    <!-- 拖拽/导入区域 -->
    <div class="drop-zone-container">
      <div v-if="files.length === 0" class="empty-drop-zone" @click="pickFiles">
        <div class="lottie-placeholder">📁</div>
        <h3>导入实验样本</h3>
        <p>支持拖拽多个 .fasta, .fna, .gbk 格式文件</p>
        <button class="btn-primary-ghost">立即导入</button>
      </div>

      <div v-else class="file-tray-workspace">
        <div class="tray-header">
          <span class="count-tag">已载入 {{ files.length }} 份样本</span>
          <button class="btn-mini-add" @click="pickFiles">+ 继续添加</button>
        </div>
        <div class="file-flex-grid">
          <div v-for="(file, idx) in files" :key="file.path" 
               class="sample-pill" 
               :class="{ 'is-reference': analysisMode === 'reference' && referenceIdx === idx }"
               @click="analysisMode === 'reference' ? referenceIdx = idx : null">
            <div class="pill-leading">
              <span v-if="analysisMode === 'reference' && referenceIdx === idx" class="ref-dot">REF</span>
              <span v-else class="idx-dot">{{ idx + 1 }}</span>
            </div>
            <span class="pill-name">{{ file.name }}</span>
            <button class="btn-pill-remove" @click.stop="removeFile(idx)">✕</button>
          </div>
        </div>
      </div>
    </div>

    <div class="setup-footer">
      <div class="hint-box" v-if="analysisMode === 'reference'">
        <span class="icon">💡</span>
        <span>已启用参考模式：将以第 <b>{{ referenceIdx + 1 }}</b> 个样本为基准进行 1 对 N 比对。</span>
      </div>
      <button class="btn-execute" :disabled="files.length < 2 || isAnalyzing" @click="handleRun">
        <template v-if="!isAnalyzing">
          <span>提交分析任务</span>
          <span class="arrow">→</span>
        </template>
        <template v-else>
          <span class="spinner-small"></span>
          <span>执行中...</span>
        </template>
      </button>
    </div>
  </div>
</template>

<style scoped>
.analysis-setup-card { background: white; border-radius: 24px; padding: 32px; border: 1px solid #f1f5f9; box-shadow: 0 10px 30px -10px rgba(0,0,0,0.05); }

.setup-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 32px; }
.badge { background: #eff6ff; color: #2563eb; font-size: 10px; font-weight: 800; padding: 4px 10px; border-radius: 20px; text-transform: uppercase; margin-bottom: 12px; display: inline-block; }
.header-content h2 { font-size: 1.5rem; font-weight: 950; color: #0f172a; margin: 0; letter-spacing: -0.03em; }
.header-content p { color: #64748b; margin: 8px 0 0; font-size: 0.9rem; }

.mode-pills { background: #f8fafc; padding: 6px; border-radius: 16px; border: 1px solid #f1f5f9; display: flex; gap: 4px; }
.mode-pills button { border: none; background: none; padding: 10px 20px; border-radius: 12px; font-size: 0.85rem; font-weight: 800; color: #64748b; cursor: pointer; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
.mode-pills button.active { background: white; color: #2563eb; box-shadow: 0 4px 12px rgba(0,0,0,0.06); }

.drop-zone-container { min-height: 240px; }
.empty-drop-zone { height: 240px; border: 2px dashed #e2e8f0; border-radius: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; }
.empty-drop-zone:hover { border-color: #2563eb; background: #f0f7ff; }
.lottie-placeholder { font-size: 3rem; margin-bottom: 16px; }
.empty-drop-zone h3 { font-size: 1.1rem; margin: 0; color: #1e293b; }
.empty-drop-zone p { font-size: 0.85rem; color: #94a3b8; margin: 8px 0 16px; }
.btn-primary-ghost { border: 2px solid #2563eb; color: #2563eb; background: none; padding: 8px 24px; border-radius: 12px; font-weight: 800; font-size: 0.85rem; cursor: pointer; }

.file-tray-workspace { background: #f8fafc; border-radius: 20px; padding: 20px; border: 1px solid #f1f5f9; }
.tray-header { display: flex; justify-content: space-between; margin-bottom: 16px; align-items: center; }
.count-tag { font-size: 0.75rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; }
.btn-mini-add { background: none; border: none; color: #2563eb; font-weight: 800; font-size: 0.8rem; cursor: pointer; }

.file-flex-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.sample-pill { background: white; border: 1px solid #e2e8f0; padding: 8px 12px; border-radius: 14px; display: flex; align-items: center; gap: 10px; cursor: pointer; transition: all 0.2s; }
.sample-pill:hover { transform: translateY(-2px); border-color: #2563eb; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.sample-pill.is-reference { border-color: #2563eb; background: #eff6ff; }

.pill-leading .idx-dot { width: 22px; height: 22px; background: #f1f5f9; color: #64748b; display: flex; align-items: center; justify-content: center; border-radius: 6px; font-size: 10px; font-weight: 900; }
.pill-leading .ref-dot { background: #2563eb; color: white; padding: 2px 6px; border-radius: 6px; font-size: 9px; font-weight: 900; }
.pill-name { font-size: 0.85rem; font-weight: 800; color: #334155; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.btn-pill-remove { border: none; background: none; color: #94a3b8; cursor: pointer; padding: 2px; }
.btn-pill-remove:hover { color: #ef4444; }

.setup-footer { margin-top: 32px; display: flex; justify-content: flex-end; align-items: center; gap: 24px; padding-top: 24px; border-top: 1px solid #f1f5f9; }
.hint-box { flex: 1; background: #fffcf0; border: 1px solid #fffae5; padding: 10px 16px; border-radius: 12px; font-size: 0.85rem; color: #7c4d12; display: flex; gap: 10px; align-items: center; }

.btn-execute { background: #0f172a; color: white; border: none; padding: 14px 40px; border-radius: 16px; font-weight: 900; cursor: pointer; display: flex; align-items: center; gap: 12px; transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275); }
.btn-execute:hover:not(:disabled) { transform: translateY(-4px); box-shadow: 0 12px 24px -6px rgba(15, 23, 42, 0.3); }
.btn-execute:disabled { background: #e2e8f0; color: #94a3b8; cursor: not-allowed; }

.spinner-small { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-top-color: white; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.animate-fade-in { animation: fadeIn 0.4s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
