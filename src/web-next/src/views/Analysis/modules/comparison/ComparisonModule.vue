<script setup lang="ts">
/**
 * ComparisonModule - 共线性分析模块 (Desktop Pro v7.0)
 * 采用经典的 侧边栏-主内容 布局，提升桌面端空间利用率。
 */
import { ref } from 'vue';
import { useComparison } from './composables/useComparison';
import ComparisonSetup from './components/ComparisonSetup.vue';
import ComparisonResults from './components/ComparisonResults.vue';
import ComparisonHistory from './components/ComparisonHistory.vue';

const { isRunning, result, error, runInstantAnalysis, loadHistoryResult } = useComparison();
const activeTaskId = ref<string>('');

async function onRunInstant(payload: { seq1: string; seq2: string; name1: string; name2: string }) {
  await runInstantAnalysis({ 
    seq1: payload.seq1, 
    seq2: payload.seq2, 
    name1: payload.name1, 
    name2: payload.name2 
  });
}

async function onHistorySelect(item: any) {
  activeTaskId.value = item.task_id;
  await loadHistoryResult(item);
}
</script>

<template>
  <div class="comparison-module-v7">
    <div class="desktop-layout">
      <!-- 1. 左侧侧边栏：历史记录 -->
      <aside class="sidebar">
        <div class="sidebar-header">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>历史分析</span>
        </div>
        <div class="history-list-container">
          <ComparisonHistory :active-id="activeTaskId" @select="onHistorySelect" />
        </div>
      </aside>

      <!-- 2. 右侧主内容区 -->
      <main class="main-content">
        <!-- 配置面板 -->
        <section class="section-setup">
          <ComparisonSetup :is-running="isRunning" @run_instant="onRunInstant" />
        </section>

        <!-- 错误提示 -->
        <transition name="slide-fade">
          <div v-if="error" class="error-banner">
            <div class="err-icon">!</div>
            <div class="err-msg">{{ error }}</div>
          </div>
        </transition>

        <!-- 结果展示 -->
        <section class="section-results">
          <div v-if="result" class="results-wrapper">
            <ComparisonResults :result="result" />
          </div>

          <div v-else-if="!isRunning" class="placeholder-ghost">
            <div class="ph-content">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"
                opacity="0.3">
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
              <h3>准备就绪</h3>
              <p>请上传序列或选择历史记录</p>
            </div>
          </div>

          <div v-else class="loading-full">
            <div class="loading-spin"></div>
            <p>正在执行 K-mer 启发式比对...</p>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.comparison-module-v7 {
  width: 100%;
  min-height: calc(100vh - 120px);
}

.desktop-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

/* 侧边栏样式 */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: white;
  border-radius: 16px;
  border: 1px solid #f1f5f9;
  padding: 20px 12px;
  position: sticky;
  top: 10px;
  max-height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  padding-left: 8px;
  font-weight: 800;
  color: #1e293b;
  font-size: 14px;
}

.history-list-container {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}

/* 主区域样式 */
.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.section-setup {
  width: 100%;
}

.error-banner {
  background: #fff1f2;
  border: 1px solid #ffe4e6;
  padding: 12px 20px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: #e11d48;
  font-size: 14px;
}

.err-icon {
  width: 20px;
  height: 20px;
  background: #fb7185;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 900;
}

.placeholder-ghost {
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 120px 0;
  text-align: center;
  color: #94a3b8;
}

.placeholder-ghost h3 {
  margin: 12px 0 4px;
  color: #475569;
  font-weight: 800;
}

.loading-full {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 120px 0;
  color: #64748b;
  font-weight: 700;
}

.loading-spin {
  width: 40px;
  height: 40px;
  border: 3px solid #f1f5f9;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.slide-fade-enter-active {
  transition: all 0.3s ease-out;
}

.slide-fade-enter-from {
  transform: translateY(-10px);
  opacity: 0;
}

@media (max-width: 1200px) {
  .desktop-layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    position: static;
    max-height: 400px;
    order: 2;
  }

  .main-content {
    order: 1;
  }
}
</style>
