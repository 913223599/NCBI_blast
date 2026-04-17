
<script setup lang="ts">
/**
 * AnalysisView - 组装分析模块入口
 * 职责：提供组装后的深度分析工具集（质控、共线性、清理）
 * 遵循模块化设计，每个工具为一个独立的子组件。
 */
import { ref } from 'vue'
import DotplotWorkspace from './Analysis/components/DotplotWorkspace.vue'

interface AnalysisTool {
  id: string;
  title: string;
  description: string;
  icon: string;
  status: 'ready' | 'beta' | 'coming_soon';
}

const tools = ref<AnalysisTool[]>([
  { 
    id: 'quast', 
    title: '组装质量评估', 
    description: '集成 QUAST，分析 N50、GC 含量、基因特征覆盖度等关键指标。', 
    icon: '📊',
    status: 'ready'
  },
  { 
    id: 'dotplot', 
    title: '共线性散点图', 
    description: '使用 Minimap2 进行序列比对，可视化基因组结构变异与重排。', 
    icon: '📈',
    status: 'ready'
  },
  { 
    id: 'cleaner', 
    title: '接头/引物清理', 
    description: '检测并切除组装序列末端的接头、引物残留，确保引物库洁净。', 
    icon: '✂️',
    status: 'beta'
  },
  { 
    id: 'circular', 
    title: '环化验证', 
    description: '针对噬菌体/质粒，验证序列首尾重合度以确认成环状态。', 
    icon: '🔄',
    status: 'coming_soon'
  }
])

const activeTool = ref<string | null>(null)

function selectTool(tool: AnalysisTool) {
  if (tool.status === 'coming_soon') return
  activeTool.value = tool.id
}
</script>

<template>
  <div class="analysis-container">
    <header class="analysis-header">
      <div class="header-content">
        <h1>组装分析工作台</h1>
        <p>组装后的深度验证与特征挖掘，支持 QUAST、Minimap2 等核心算法。</p>
      </div>
      <div class="header-stats" v-if="!activeTool">
         <div class="stat-badge">
            <span class="label">可用工具</span>
            <span class="value">{{ tools.length }}</span>
         </div>
      </div>
      <button v-else class="back-btn" @click="activeTool = null">
        ← 返回工具列表
      </button>
    </header>

    <main class="analysis-content">
      <!-- 紧凑型工具网格 -->
      <div v-if="!activeTool" class="tools-grid">
        <div 
          v-for="tool in tools" 
          :key="tool.id" 
          :class="['tool-card', tool.status]"
          @click="selectTool(tool)"
        >
          <div class="tool-icon-mini">{{ tool.icon }}</div>
          <div class="tool-body">
            <div class="tool-title-row">
              <h3>{{ tool.title }}</h3>
              <span :class="['status-tag-mini', tool.status]">{{ tool.status === 'ready' ? '' : tool.status.toUpperCase() }}</span>
            </div>
            <p class="tool-desc">{{ tool.description }}</p>
          </div>
        </div>
      </div>

      <!-- 具体工具占位符 -->
      <div v-else class="tool-workspace">
        <DotplotWorkspace v-if="activeTool === 'dotplot'" />
        <div v-else class="workspace-placeholder">
           <div class="empty-icon">{{ tools.find(t => t.id === activeTool)?.icon }}</div>
           <h2>{{ tools.find(t => t.id === activeTool)?.title }} 模块开发中</h2>
           <p>正在拉取 {{ activeTool }} 算法引擎，请稍候...</p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.analysis-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
}

.analysis-header {
  padding: 32px 40px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h1 {
  margin: 0;
  font-size: 24px;
  color: #1e293b;
  letter-spacing: -0.5px;
}

.header-content p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 14px;
}

.back-btn {
  background: #f1f5f9;
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  padding: 32px 40px;
}

.tool-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  position: relative;
}

.tool-card:hover:not(.coming_soon) {
  border-color: #3b82f6;
  background: #f0f7ff;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
}

.tool-icon-mini {
  font-size: 24px;
  width: 44px;
  height: 44px;
  background: #f8fafc;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.tool-body {
  flex: 1;
  min-width: 0;
}

.tool-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.tool-title-row h3 {
  margin: 0;
  font-size: 15px;
  color: #1e293b;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-tag-mini {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 700;
}

.status-tag-mini.ready { display: none; }
.status-tag-mini.beta { background: #fff7ed; color: #ea580c; }
.status-tag-mini.coming_soon { background: #f1f5f9; color: #94a3b8; }

.tool-desc {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tool-card.coming_soon {
  opacity: 0.6;
  cursor: not-allowed;
  background: #f8fafc;
}

.tool-workspace {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.workspace-placeholder {
  text-align: center;
  max-width: 400px;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 24px;
  opacity: 0.8;
}

.workspace-placeholder h2 { color: #1e293b; margin: 0 0 12px; }
.workspace-placeholder p { color: #64748b; font-size: 14px; }
</style>
