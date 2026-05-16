<script setup lang="ts">
import { ref, computed } from 'vue';
import InstantFileCard from './InstantFileCard.vue';

const props = defineProps<{ isRunning: boolean }>();
const emit = defineEmits<{
  (e: 'run_instant', payload: { seq1: string; seq2: string; name1: string; name2: string }): void;
  (e: 'run_standard', payload: { engine: string; autoOrientation: boolean }): void;
}>();

const file1Name = ref('');
const file2Name = ref('');
const seq1 = ref('');
const seq2 = ref('');
const engine = ref<'instant' | 'mummer' | 'minimap2'>('instant');
const autoOrientation = ref(true);

const canRun = computed(() => seq1.value && seq2.value && !props.isRunning);

async function handleFileUpload(e: Event, isSeq1: boolean) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  if (files.length === 0) return;

  try {
    if (files.length === 1 && files[0]) {
      const file = files[0];
      if (isSeq1) file1Name.value = file.name; else file2Name.value = file.name;
      const text = await file.text();
      if (isSeq1) seq1.value = text; else seq2.value = text;
    } else {
      const name = `${files.length} 个文件已合并拼接`;
      if (isSeq1) file1Name.value = name; else file2Name.value = name;
      let combined = "";
      for (const file of files) {
        combined += (await file.text()) + "\n";
      }
      if (isSeq1) seq1.value = combined; else seq2.value = combined;
    }
  } catch (err: any) {
    console.error("文件读取失败", err);
  }
}

function handleClear(isSeq1: boolean) {
  if (isSeq1) {
    seq1.value = ''; file1Name.value = '';
  } else {
    seq2.value = ''; file2Name.value = '';
  }
}

function handleRun() {
  if (!canRun.value) return;
  emit('run_instant', {
    seq1: seq1.value, seq2: seq2.value,
    name1: file1Name.value, name2: file2Name.value
  });
}
</script>

<template>
  <div class="comparison-setup-container">
    <!-- 头部装饰 -->
    <div class="setup-header">
      <div class="header-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
      </div>
      <div class="header-text">
        <h3 class="title">基因序列比较分析工具</h3>
        <p class="subtitle">检测两份 FASTA 序列的相似度、共线性和具体变异点位</p>
      </div>
    </div>

    <!-- 文件输入卡片 -->
    <div class="upload-grid">
      <InstantFileCard title="序列 1 (参考序列)" :file-name="file1Name" id="f1_main" @upload="handleFileUpload($event, true)"
        @clear="handleClear(true)" />
      <InstantFileCard title="序列 2 (比对序列)" :file-name="file2Name" id="f2_main" @upload="handleFileUpload($event, false)"
        @clear="handleClear(false)" />
    </div>

    <!-- 控制栏 -->
    <div class="action-bar">
      <div class="engine-params">
        <div class="engine-selector">
          <div :class="{ active: engine === 'instant' }" @click="engine = 'instant'">Instant (极速)</div>
          <div :class="{ active: engine === 'mummer' }" @click="engine = 'mummer'">MUMmer</div>
          <div :class="{ active: engine === 'minimap2' }" @click="engine = 'minimap2'">Minimap2</div>
        </div>
        <label class="auto-orient">
          <input type="checkbox" v-model="autoOrientation" />
          <span>极性自动校正</span>
        </label>
      </div>

      <button @click="handleRun" :disabled="!canRun || isRunning" class="btn-start">
        <svg v-if="!isRunning" class="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2.5">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span v-else class="spinner mr-2"></span>
        {{ isRunning ? '正在分析中...' : '开始分析序列' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.comparison-setup-container {
  background: white;
  border-radius: 16px;
  padding: 20px 24px;
  border: 1px solid #f1f5f9;
  box-shadow: 0 4px 24px -4px rgba(0, 0, 0, 0.04);
}

.setup-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.header-icon {
  width: 36px;
  height: 36px;
  background: #eff6ff;
  color: #3b82f6;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-icon svg {
  width: 20px;
  height: 20px;
}

.title {
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}

.subtitle {
  font-size: 0.78rem;
  color: #64748b;
  margin-top: 2px;
}

.upload-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.engine-params {
  display: flex;
  align-items: center;
  gap: 16px;
}

.engine-selector {
  display: flex;
  background: #f8fafc;
  padding: 3px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.engine-selector div {
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}

.engine-selector div.active {
  background: white;
  color: #3b82f6;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.auto-orient {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  cursor: pointer;
}

.auto-orient input {
  accent-color: #3b82f6;
  width: 14px;
  height: 14px;
}

.btn-start {
  display: flex;
  align-items: center;
  padding: 8px 24px;
  background: #2563eb;
  color: white;
  font-weight: 800;
  font-size: 14px;
  border-radius: 99px;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 12px -2px rgba(37, 99, 235, 0.3);
  transition: all 0.3s;
}

.btn-start:hover:not(:disabled) {
  background: #1d4ed8;
  transform: translateY(-2px);
}

.btn-start:disabled {
  background: #e2e8f0;
  color: #94a3b8;
  box-shadow: none;
  cursor: not-allowed;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .upload-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .action-bar {
    flex-direction: column;
    gap: 16px;
    align-items: stretch;
  }
}
</style>
