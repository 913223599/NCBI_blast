<script setup lang="ts">
/**
 * AnalysisView - 组装分析工作台入口
 * 职责：提供组装后的深度分析工具集（全场景共线性分析、序列交互式可视化、全基因组功能注释）
 * 遵循模块化设计，每个工具为一个独立的子组件。
 */
import { ref } from 'vue'
import GenomeViewerModule from './Analysis/modules/viewer/GenomeViewerModule.vue'
import AnnotationModule from './Analysis/modules/annotation/AnnotationModule.vue'
import ProteinCompareModule from './Analysis/modules/protein_compare/ProteinCompareModule.vue'
import PanGenomicsModule from './Analysis/modules/pan_genomics/PanGenomicsModule.vue'

interface AnalysisTool {
  id: string;
  title: string;
  description: string;
  iconType: 'chart' | 'dna' | 'book' | 'compare' | 'pangenome';
  status: 'ready' | 'beta' | 'coming_soon';
}

const tools = ref<AnalysisTool[]>([
  { 
    id: 'annotation', 
    title: '全基因组功能注释', 
    description: '基于 Prokka / Pharokka / 内置高精度引擎进行 CDS、tRNA、rRNA 预测与蛋白功能注释，支持 FASTA 提交与三维圈图联动。', 
    iconType: 'book',
    status: 'ready'
  },
  { 
    id: 'protein_compare', 
    title: '核心蛋白跨样本比对分析', 
    description: '对比两个噬菌体/细菌样本中尾丝、裂解酶、衣壳与复制酶等关键基因的同源性、一致性、氨基酸点突变与变异图谱。', 
    iconType: 'compare',
    status: 'ready'
  },
  { 
    id: 'pan_genomics', 
    title: '多样本泛基因组与深度交叉对比', 
    description: '多样本正交同源聚类(Core/Unique)、宿主识别尾丝受体结构域对比、生活史烈性/温和安全评级与代谢攻防全景图。', 
    iconType: 'pangenome',
    status: 'ready'
  },
  { 
    id: 'viewer', 
    title: '序列交互式可视化', 
    description: '提供类似 SnapGene 的交互式序列与注释查看器，支持环形 (Circular) 与线性 (Linear) 模式，兼容 GenBank/GFF。', 
    iconType: 'dna',
    status: 'ready'
  }
])

const activeTool = ref<string | null>(null)

// 传递给 GenomeViewer 的跨模块数据
const viewerInitialGbk = ref<string>('')
const viewerInitialName = ref<string>('')

function selectTool(tool: AnalysisTool) {
  if (tool.status === 'coming_soon') return
  activeTool.value = tool.id
}

function handleOpenViewerFromAnnotation(payload: { gbkText: string; taskName: string }) {
  viewerInitialGbk.value = payload.gbkText
  viewerInitialName.value = payload.taskName
  activeTool.value = 'viewer'
}
</script>

<template>
  <div class="analysis-container">
    <header class="analysis-header">
      <div class="header-content">
        <h1>组装分析工作台</h1>
        <p>组装后的深度特征挖掘与比较基因组学工作台，支持全基因组功能注释、核心蛋白对比、泛基因组分析与 SnapGene 序列可视化。</p>
      </div>
      <div class="header-stats" v-if="!activeTool">
         <div class="stat-badge">
            <span class="label">可用工具</span>
            <span class="value">{{ tools.length }}</span>
         </div>
      </div>
      <button v-else class="back-btn" @click="activeTool = null">
        &larr; 返回工具列表
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
          <div class="tool-icon-mini">
            <!-- 矢量 SVG 图标：严禁 Emoji -->
            <svg v-if="tool.iconType === 'book'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              <line x1="9" y1="7" x2="15" y2="7" />
              <line x1="9" y1="11" x2="13" y2="11" />
            </svg>
            <svg v-else-if="tool.iconType === 'compare'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ea580c" stroke-width="2.2">
              <path d="M16 3h5v5" />
              <path d="M4 20L21 3" />
              <path d="M21 16v5h-5" />
              <path d="M15 15l6 6" />
              <path d="M4 4l5 5" />
            </svg>
            <svg v-else-if="tool.iconType === 'pangenome'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0284c7" stroke-width="2.2">
              <circle cx="12" cy="12" r="3" />
              <circle cx="4" cy="12" r="2" />
              <circle cx="20" cy="12" r="2" />
              <circle cx="12" cy="4" r="2" />
              <circle cx="12" cy="20" r="2" />
              <line x1="6" y1="12" x2="9" y2="12" />
              <line x1="15" y1="12" x2="18" y2="12" />
              <line x1="12" y1="6" x2="12" y2="9" />
              <line x1="12" y1="15" x2="12" y2="18" />
            </svg>
            <svg v-else-if="tool.iconType === 'dna'" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2.2">
              <path d="M2 15c6.667-6 13.333 0 20-6" />
              <path d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993" />
              <path d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993" />
              <path d="M17 6l-2.5-2.5" />
              <path d="M14 8l-4-4" />
              <path d="M7 18l2.5 2.5" />
              <path d="M3.5 14.5l.5.5" />
              <path d="M20 9.5l.5.5" />
            </svg>
          </div>
          <div class="tool-body">
            <div class="tool-title-row">
              <h3>{{ tool.title }}</h3>
              <span :class="['status-tag-mini', tool.status]">{{ tool.status === 'ready' ? '' : tool.status.toUpperCase() }}</span>
            </div>
            <p class="tool-desc">{{ tool.description }}</p>
          </div>
        </div>
      </div>

      <!-- 具体工具工作区 -->
      <div v-else class="tool-workspace">
        <AnnotationModule 
          v-if="activeTool === 'annotation'" 
          @open-viewer="handleOpenViewerFromAnnotation" 
        />
        <ProteinCompareModule v-else-if="activeTool === 'protein_compare'" />
        <PanGenomicsModule v-else-if="activeTool === 'pan_genomics'" />
        <GenomeViewerModule 
          v-else-if="activeTool === 'viewer'" 
          :initial-gbk="viewerInitialGbk"
          :initial-name="viewerInitialName"
        />
        <div v-else class="workspace-placeholder">
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
  padding: 12px 24px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h1 {
  margin: 0;
  font-size: 18px;
  color: #1e293b;
  letter-spacing: -0.5px;
}

.header-content p {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 12px;
}

.stat-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.stat-badge .label {
  color: #64748b;
}

.stat-badge .value {
  color: #2563eb;
  font-weight: 700;
}

.back-btn {
  background: #f1f5f9;
  border: none;
  padding: 6px 14px;
  border-radius: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.analysis-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  padding: 32px 40px;
  overflow-y: auto;
}

.tool-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px;
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
  transform: translateY(-2px);
}

.tool-icon-mini {
  width: 44px;
  height: 44px;
  background: #f8fafc;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid #e2e8f0;
}

.tool-body {
  flex: 1;
  min-width: 0;
}

.tool-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.tool-title-row h3 {
  margin: 0;
  font-size: 15px;
  color: #1e293b;
  font-weight: 700;
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
  flex-direction: column;
  padding: 0;
  overflow-y: auto;
}

.workspace-placeholder {
  text-align: center;
  max-width: 400px;
  margin: 60px auto;
}

.workspace-placeholder h2 { color: #1e293b; margin: 0 0 12px; }
.workspace-placeholder p { color: #64748b; font-size: 14px; }
</style>
