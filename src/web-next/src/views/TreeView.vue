<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { useTree } from '../composables/useTree'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge/pyqt-bridge'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseSelect from '../components/ui/BaseSelect.vue'

const appStore = useAppStore()
const { settings, loadNewick, exportSVG, hasTree, isLoading, nodeCount, renderer } = useTree()
const fileInput = ref<HTMLInputElement | null>(null)

// 2.0 Reactive States
const sequenceInput = ref('')
const selectedFiles = ref<File[]>([])
const menuVisible = ref(false)
const menuPos = ref({ x: 0, y: 0 })
const selectedNode = ref<any>(null)
const isSidebarOpen = ref(true)

const activeDrawers = reactive({
    input: true,
    analysis: true,
    display: true
})

// Options from the Remake Report
const layoutModeOptions = [
    { label: '矩形 (Rectangular)', value: 'rect' },
    { label: '圆形 (Circular)', value: 'circular' }
]

const branchStyleOptions = [
    { value: 'square', label: '直角 (Square)' },
    { value: 'slanted', label: '斜线 (Slanted)' },
    { value: 'curved', label: '曲线 (Curved)' }
]

const treeWorkflows = reactive({
    msa: 'none', // none, mafft, muscle
    engine: 'nj', // nj, ml, fast
    model: 'jc',
    bootstrap: 100
})

const msaOptions = [
    { value: 'none', label: '无需比对 (已对齐)' },
    { value: 'mafft', label: 'MAFFT (极速启发式)' },
    { value: 'muscle', label: 'MUSCLE (高精度迭代)' }
]

const engineOptions = [
    { value: 'nj', label: 'Neighbor-Joining (邻接法)' },
    { value: 'ml', label: 'Maximum Likelihood (最大似然)' },
    { value: 'fast', label: 'FastTree (海量序列近似)' }
]

const modelOptions = computed(() => {
    if (treeWorkflows.engine === 'ml' || treeWorkflows.engine === 'fast') {
        return [
            { value: 'jc', label: 'JC (Jukes-Cantor)' },
            { value: 'gtr', label: 'GTR (General Time Reversible)' },
            { value: 'jtt', label: 'JTT (Protein Engine)' }
        ]
    }
    return [{ value: 'identity', label: 'Standard Identity' }]
})

// Logic Methods
function toggleDrawer(key: keyof typeof activeDrawers) {
    activeDrawers[key] = !activeDrawers[key]
}

function handleFileUpload(e: Event) {
    const files = (e.target as HTMLInputElement).files
    if (files) {
        selectedFiles.value = Array.from(files)
        appStore.showNotification(`已添加 ${files.length} 个本地序列文件`, 'info')
    }
}

function importSequences() {
    if (sequenceInput.value.length > 0 || selectedFiles.value.length > 0) {
        appStore.showNotification('序列已载入内核，准备执行 MSA 预处理...', 'success')
        setTimeout(() => { activeDrawers.input = false; activeDrawers.analysis = true }, 800)
    } else {
        appStore.showNotification('请先输入序列或选择文件', 'error')
    }
}

function requestAnalysis() {
    isLoading.value = true
    appStore.showNotification(`正在启动 [${treeWorkflows.engine}] 发育分析管线...`, 'info')
    try {
        const params = {
            ...treeWorkflows,
            mode: treeWorkflows.engine === 'nj' ? 'rapid' : 'standard'
        }
        getBridge().request_tree_analysis(JSON.stringify(params))
    } catch(e) {
        isLoading.value = false
        console.error("Analysis request failed", e)
    }
}

onMounted(() => {
    // @ts-ignore
    window.treeView = {
        loadNewick: (content: string) => { 
            loadNewick(content)
            isLoading.value = false
        },
        setLoading: (val: boolean) => { isLoading.value = val }
    }
    if (renderer) {
        renderer.onNodeClick = (node, e) => {
            selectedNode.value = node
            menuPos.value = { x: e.clientX, y: e.clientY }
            menuVisible.value = true
        }
    }
})

function closeMenu() { menuVisible.value = false }
function handleReroot() {
    if (selectedNode.value && getBridge()) {
        getBridge().request_tree_reroot(selectedNode.value.name)
        closeMenu()
    }
}
function openNCBI() {
    if (selectedNode.value?.name) {
        window.open(`https://www.ncbi.nlm.nih.gov/taxonomy/?term=${encodeURIComponent(selectedNode.value.name)}`, '_blank')
    }
    closeMenu()
}
function clearWorkspace() {
    selectedFiles.value = []
    sequenceInput.value = ''
}
</script>

<template>
  <div class="tree-view-container">
    <header class="tree-header">
      <div class="left">
        <BaseButton variant="ghost" size="sm" @click="isSidebarOpen = !isSidebarOpen">☰</BaseButton>
        <h2 class="title">NCBI Tree Station 2.0</h2>
        <span v-if="hasTree" class="meta-badge">{{ nodeCount }} Nodes</span>
      </div>
      <div class="right">
        <BaseButton variant="primary" size="md" icon="🚀" @click="requestAnalysis" :disabled="isLoading">启动分析</BaseButton>
        <BaseButton variant="secondary" size="md" icon="💾" @click="exportSVG" :disabled="!hasTree">导出图表</BaseButton>
      </div>
    </header>

    <div class="tree-body">
      <aside v-show="isSidebarOpen" class="tree-sidebar">
        
        <!-- Input Drawer -->
        <div class="drawer" :class="{ open: activeDrawers.input }">
          <div class="drawer-header" @click="toggleDrawer('input')">
            <span class="drawer-icon">📥</span>
            <span class="drawer-title">序列采集 (Input)</span>
            <span class="drawer-arrow">{{ activeDrawers.input ? '▼' : '▶' }}</span>
          </div>
          <div class="drawer-body" v-if="activeDrawers.input">
            <div class="upload-zone" @click="fileInput?.click()">
                <div class="icon">📁</div>
                <div class="txt">{{ selectedFiles.length > 0 ? `已选 ${selectedFiles.length} 个文件` : '上传 FASTA/ALN 文件' }}</div>
                <input type="file" ref="fileInput" hidden multiple @change="handleFileUpload" />
            </div>
            <div class="input-divider">或粘贴文本</div>
            <textarea v-model="sequenceInput" class="fasta-textarea" placeholder=">Seq1\nATCG..."></textarea>
            <div class="actions mt-4">
                <button class="btn-mini-primary w-full" @click="importSequences">载入到分析队列</button>
                <button class="btn-text" @click="clearWorkspace">清空</button>
            </div>
          </div>
        </div>

        <!-- Pipeline Drawer -->
        <div class="drawer" :class="{ open: activeDrawers.analysis }">
          <div class="drawer-header" @click="toggleDrawer('analysis')">
            <span class="drawer-icon">🧬</span>
            <span class="drawer-title">发育分析管线 (Pipeline)</span>
            <span class="drawer-arrow">{{ activeDrawers.analysis ? '▼' : '▶' }}</span>
          </div>
          <div class="drawer-body" v-if="activeDrawers.analysis">
            <BaseSelect label="多序列比对 (MSA)" :options="msaOptions" v-model="treeWorkflows.msa" />
            <BaseSelect label="分析引擎 (Engine)" :options="engineOptions" v-model="treeWorkflows.engine" />
            <BaseSelect label="进化模型 (Model)" :options="modelOptions" v-model="treeWorkflows.model" />
            <div class="control-group">
                <label>Bootstrap: {{ treeWorkflows.bootstrap }}</label>
                <input type="range" v-model.number="treeWorkflows.bootstrap" min="0" max="1000" step="100" />
            </div>
          </div>
        </div>

        <!-- Display Drawer -->
        <div class="drawer" :class="{ open: activeDrawers.display }">
          <div class="drawer-header" @click="toggleDrawer('display')">
            <span class="drawer-icon">💡</span>
            <span class="drawer-title">显示控制 (Display)</span>
            <span class="drawer-arrow">{{ activeDrawers.display ? '▼' : '▶' }}</span>
          </div>
          <div class="drawer-body" v-if="activeDrawers.display">
            <BaseSelect label="拓扑形态" :options="layoutModeOptions" v-model="settings.mode" />
            <BaseSelect label="分支样式" :options="branchStyleOptions" v-model="settings.branchStyle" />
            <div class="checkbox-group">
                <label><input type="checkbox" v-model="settings.showLabels" /> 显示标签</label>
                <label><input type="checkbox" v-model="settings.useBranchLengths" /> 原始长度</label>
            </div>
            <div class="control-group">
                <label>缩放级别: {{ settings.fontSize }}px</label>
                <input type="range" v-model.number="settings.fontSize" min="8" max="24" />
            </div>
          </div>
        </div>
      </aside>

      <main class="tree-main">
        <div ref="containerRef" class="canvas-container"></div>
        <div v-if="!hasTree && !isLoading" class="empty-state">
            <div class="empty-content">
              <span class="icon">🧬</span>
              <h3>NCBI Tree Station 2.0</h3>
              <p>请上传序列文件或粘贴 FASTA，启动专业的系统发育分析管线。</p>
            </div>
        </div>
        <div v-if="isLoading" class="loading-state">
           <div class="spinner"></div>
           <p>核心管线运行中: 执行 MSA 与拓扑推断...</p>
        </div>
        <div v-if="menuVisible" class="node-menu" :style="{ left: menuPos.x + 'px', top: menuPos.y + 'px' }" v-click-outside="closeMenu">
          <div class="menu-header">{{ selectedNode?.name }}</div>
          <div class="menu-item" @click="handleReroot">🎯 重定根 (Reroot)</div>
          <div class="menu-item" @click="openNCBI">🌐 在 NCBI 查看</div>
          <div class="menu-divider"></div>
          <div class="menu-item danger" @click="closeMenu">取消</div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.tree-view-container { display: flex; flex-direction: column; height: 100%; background: #f8fafc; }
.tree-header {
  height: 50px; background: white; border-bottom: 1px solid var(--border-color);
  display: flex; align-items: center; justify-content: space-between; padding: 0 16px;
}
.left, .right { display: flex; align-items: center; gap: 12px; }
.title { font-size: 1rem; font-weight: 600; color: var(--text-primary); margin: 0; }
.meta-badge { background: #e0f2fe; color: #0284c7; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }

.tree-body { flex: 1; display: flex; overflow: hidden; }
.tree-sidebar { width: 290px; background: white; border-right: 1px solid var(--border-color); overflow-y: auto; display: flex; flex-direction: column; }

.drawer { border-bottom: 1px solid var(--border-light); overflow: hidden; }
.drawer-header {
  padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 10px;
  transition: background 0.2s; user-select: none;
}
.drawer-header:hover { background: #f8fafc; }
.drawer-title { flex: 1; font-weight: 600; font-size: 0.85rem; color: var(--text-primary); }
.drawer-body { padding: 16px; background: #fafafa; border-top: 1px solid #f1f5f9; }

.upload-zone {
  border: 2px dashed #e2e8f0; border-radius: 10px; padding: 24px; text-align: center;
  cursor: pointer; transition: all 0.2s; background: white;
}
.upload-zone:hover { border-color: var(--accent-blue); background: #f8fafc; }
.upload-zone .icon { font-size: 2rem; margin-bottom: 8px; }
.upload-zone .txt { font-size: 0.8rem; color: #64748b; }

.input-divider { text-align: center; margin: 16px 0; font-size: 0.7rem; color: #94a3b8; position: relative; }
.input-divider::before, .input-divider::after { content: ''; position: absolute; top: 50%; width: 25%; height: 1px; background: #e2e8f0; }
.input-divider::before { left: 0; } .input-divider::after { right: 0; }

.fasta-textarea {
  width: 100%; height: 120px; padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px;
  font-family: 'Fira Code', monospace; font-size: 0.75rem; resize: vertical; background: #fff;
}

.tree-main { flex: 1; position: relative; background: white; overflow: hidden; }
.canvas-container { width: 100%; height: 100%; }

.empty-state, .loading-state {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.9); z-index: 10; text-align: center;
}
.empty-content .icon { font-size: 3rem; display: block; margin-bottom: 1rem; }
.spinner {
  width: 32px; height: 32px; border: 3px solid var(--primary-color); border-right-color: transparent;
  border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.node-menu {
  position: fixed; z-index: 1000; background: white; border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.15); min-width: 180px; padding: 4px; border: 1px solid var(--border-color);
}
.menu-header { font-size: 0.75rem; color: #94a3b8; padding: 8px 12px; border-bottom: 1px solid #f1f5f9; font-weight: 500; }
.menu-item { padding: 10px 12px; font-size: 0.9rem; color: var(--text-primary); cursor: pointer; border-radius: 6px; }
.menu-item:hover { background: #f1f5f9; }
.menu-item.danger { color: #ef4444; }
.menu-divider { height: 1px; background: #f1f5f9; margin: 4px 0; }
.w-full { width: 100%; }
.mt-4 { margin-top: 16px; }

/* Dashboard Buttons */
.btn-mini-primary {
  background: var(--accent-blue);
  color: white;
  border: none;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-mini-primary:hover { opacity: 0.9; }
.btn-mini-primary:disabled { background: #cbd5e1; cursor: not-allowed; }

.btn-text {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 0.75rem;
  cursor: pointer;
  padding: 8px;
  text-decoration: underline;
}
.btn-text:hover { color: var(--accent-blue); }

.header-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
}
.mt-4 { margin-top: 16px; }
.btn-mini-primary { background: var(--accent-blue); color: white; border: none; padding: 6px 12px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer; }
.btn-text { background: transparent; border: none; color: var(--accent-blue); font-size: 0.75rem; cursor: pointer; padding: 8px; }
.checkbox-group { display: flex; flex-direction: column; gap: 8px; margin: 12px 0; }
.checkbox-group label { display: flex; align-items: center; gap: 8px; font-size: 0.85rem; cursor: pointer; }
.control-group { margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
.control-group label { font-size: 0.8rem; color: var(--text-secondary); }
</style>
