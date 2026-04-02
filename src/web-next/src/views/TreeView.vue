<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useTree } from '../composables/useTree'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge/pyqt-bridge'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSelect from '../components/ui/BaseSelect.vue'
import BaseCard from '../components/ui/BaseCard.vue'

const appStore = useAppStore()
const { containerRef, settings, loadNewick, exportSVG, hasTree, isLoading, nodeCount } = useTree()

const isSidebarOpen = ref(true)

// Layout Options
const layoutModeOptions = [
  { label: '矩形 (Rectangular)', value: 'rect' },
  { label: '圆形 (Circular)', value: 'circular' },
  { label: '无根 (Unrooted)', value: 'unrooted', disabled: true }
]

const branchStyleOptions = [
  { label: '直角 (Square)', value: 'square' },
  { label: '斜线 (Slanted)', value: 'slanted' },
  { label: '曲线 (Curved)', value: 'curved' }
]

function handleFileSelect() {
  // In real app, bridge calls back with file content
  // For demo/dev, we can load a sample
  const sampleTree = "((A:0.1,B:0.2,(C:0.3,D:0.4)E:0.5)F:0.1)Root;"
  loadNewick(sampleTree)
}

// Window callback for python bridge to push data
onMounted(() => {
    // @ts-ignore
    window.treeView = {
        loadNewick: (content: string) => {
            loadNewick(content)
        }
    }
})

function requestAnalysis() {
    appStore.showNotification('正在请求后端分析...', 'info')
    try {
       getBridge().request_tree_analysis('standard')
    } catch(e) {
       // Mock
       setTimeout(() => handleFileSelect(), 1000)
    }
}
</script>

<template>
  <div class="tree-view-container">
    <!-- Header -->
    <header class="tree-header">
      <div class="left">
        <BaseButton variant="ghost" size="sm" @click="isSidebarOpen = !isSidebarOpen">
          <span class="icon">☰</span>
        </BaseButton>
        <h2 class="title">Evolutionary Tree Explorer</h2>
        <span v-if="hasTree" class="meta-badge">{{ nodeCount }} Nodes</span>
      </div>
      <div class="right">
        <BaseButton variant="primary" size="sm" icon="+" @click="requestAnalysis">New Analysis</BaseButton>
        <BaseButton variant="secondary" size="sm" icon="⬇" @click="exportSVG" :disabled="!hasTree">Export SVG</BaseButton>
      </div>
    </header>

    <div class="tree-body">
      <!-- Sidebar -->
      <aside v-show="isSidebarOpen" class="tree-sidebar">
        <BaseCard title="Layout">
           <BaseSelect 
             label="Mode" 
             v-model="settings.mode" 
             :options="layoutModeOptions" 
           />
           <BaseSelect 
             label="Branch Style" 
             v-model="settings.branchStyle" 
             :options="branchStyleOptions" 
           />
           
           <div class="control-group" v-if="settings.mode === 'circular'">
              <label>Rotation: {{ settings.rotation }}°</label>
              <input type="range" v-model.number="settings.rotation" min="0" max="360" />
              
              <label>Arc: {{ settings.arc }}°</label>
              <input type="range" v-model.number="settings.arc" min="10" max="360" />
           </div>

            <div class="control-group">
              <label>Vertical Scale</label>
              <input type="range" v-model.number="settings.scaleY" min="0.1" max="5" step="0.1" />
            </div>
        </BaseCard>

        <BaseCard title="Display" class="mt-4">
           <div class="checkbox-row">
             <input type="checkbox" id="cb-labels" v-model="settings.showLabels">
             <label for="cb-labels">Show Labels</label>
           </div>
           <div class="checkbox-row">
             <input type="checkbox" id="cb-bl" v-model="settings.useBranchLengths">
             <label for="cb-bl">Use Branch Lengths</label>
           </div>
           <BaseInput label="Font Size" type="number" v-model.number="settings.fontSize" :min="8" :max="24" />
        </BaseCard>
      </aside>

      <!-- Canvas Area -->
      <main class="tree-main">
        <div ref="containerRef" class="canvas-container"></div>
        
        <div v-if="!hasTree && !isLoading" class="empty-state">
           <div class="empty-content">
             <span class="icon">🌳</span>
             <h3>No Tree Loaded</h3>
             <p>Run an analysis or load a file to view the evolutionary tree.</p>
             <BaseButton variant="primary" @click="handleFileSelect">Load Sample Tree</BaseButton>
           </div>
        </div>

        <div v-if="isLoading" class="loading-state">
           <div class="spinner"></div>
           <p>Rendering Tree...</p>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.tree-view-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f8fafc;
}

.tree-header {
  height: 50px;
  background: white;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}
.left, .right { display: flex; align-items: center; gap: 12px; }
.title { font-size: 1rem; font-weight: 600; color: var(--text-primary); margin: 0; }
.meta-badge { background: #e0f2fe; color: #0284c7; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }

.tree-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.tree-sidebar {
  width: 280px;
  background: white;
  border-right: 1px solid var(--border-color);
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tree-main {
  flex: 1;
  position: relative;
  background: white;
  overflow: hidden;
}

.canvas-container {
  width: 100%;
  height: 100%;
}

.mt-4 { margin-top: 16px; }

.control-group {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.control-group label { font-size: 0.8rem; color: var(--text-secondary); }
.control-group input[type="range"] { width: 100%; }

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.checkbox-row label { font-size: 0.85rem; user-select: none; }

.empty-state, .loading-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.9);
  z-index: 10;
}
.empty-content { text-align: center; }
.empty-content .icon { font-size: 3rem; display: block; margin-bottom: 1rem; }
.empty-content h3 { margin-bottom: 0.5rem; color: var(--text-primary); }
.empty-content p { margin-bottom: 1.5rem; color: var(--text-secondary); font-size: 0.9rem; }

.spinner {
  width: 32px; height: 32px;
  border: 3px solid var(--primary-color);
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
