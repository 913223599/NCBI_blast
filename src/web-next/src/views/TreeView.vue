<script setup lang="ts">
/**
 * TreeView - 进化树分析视图 (Station 2.0)
 * 采用 3 板块架构：顶栏菜单 / 动态侧栏工具 / 全屏渲染区
 */
import { ref, onMounted, reactive, computed } from 'vue'
import { useTree } from '../composables/useTree'
import { useAppStore } from '../stores/app'
import { getBridge, initBridge } from '../bridge/pyqt-bridge'
import PhylotreeWidget from '../components/PhylotreeWidget.vue'

const appStore = useAppStore()
const { settings, loadNewick, midpointRooting, exportSVG, hasTree, isLoading, renderer, containerRef, rawNewick } = useTree()

/* -------- 核心状态 -------- */
const renderEngine = ref<'hybrid'|'phylotree'>('hybrid')
// 进化树渲染引擎切换监听
import { watch } from 'vue'
watch(renderEngine, (val) => {
  console.info(`[Engine] Switched to: ${val}`)
})


const isSidebarOpen = ref(true)
const activeSideTool = ref<'input' | 'analysis' | 'display'>('input')
const workspaceFiles = ref<string[]>([])
const selectedFiles = ref<any[]>([]) 
const menuVisible = ref(false)
const menuPos = ref({ x: 0, y: 0 })
const selectedNode = ref<any>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const openDropdown = ref<string | null>(null)
const loadingMsg = ref('正在处理分析管线...')
const loadingProgress = ref(0)

const treeWorkflows = reactive({
    msa: 'none',
    engine: 'nj',
    model: 'jc',
    bootstrap: 100
})

/* -------- 选项数据 -------- */
const layoutModeOptions = [
    { label: '矩形 (Rectangular)', value: 'rect' },
    { label: '圆形 (Circular)', value: 'circular' }
]

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
    return [
        { value: 'jc', label: 'JC (Jukes-Cantor)' },
        { value: 'gtr', label: 'GTR (General Time Reversible)' },
        { value: 'jtt', label: 'JTT (Protein Engine)' },
        { value: 'identity', label: 'Standard Identity' }
    ]
})

/* -------- 交互逻辑 -------- */
async function loadPrecomputedTree(fileName: string) {
    try {
        const bridge = await initBridge()
        if (bridge && typeof bridge.get_tree_content === 'function') {
            bridge.get_tree_content(fileName, (nwk: string) => {
                if (nwk && nwk.startsWith('(')) {
                    loadNewick(nwk)
                    appStore.showNotification(`成功加载进化树: ${fileName}`, 'success')
                } else {
                    appStore.showNotification('树文件内容无效，请重新生成', 'error')
                }
            })
        }
    } catch(e) {}
}

async function refreshWorkspace() {
    try {
        const bridge = await initBridge()
        if (bridge && typeof bridge.list_tree_sequences === 'function') {
            bridge.list_tree_sequences((res: string) => {
                try {
                    workspaceFiles.value = JSON.parse(res) || []
                } catch (e) {
                    console.error("Failed to parse workspace files", e)
                }
            })
        }
    } catch(e) {
        console.warn("Bridge not ready for list_tree_sequences", e)
    }
}

async function clearWorkspace() {
    selectedFiles.value = []
    workspaceFiles.value = []
    try {
        const bridge = await initBridge()
        // @ts-ignore
        if (bridge && typeof bridge.clear_tree_workspace === 'function') {
            // @ts-ignore
            bridge.clear_tree_workspace((res: boolean) => {
                workspaceFiles.value = [] // 立即同步前端列表
                if (res) {
                    appStore.showNotification('工作区已清空', 'success')
                } else {
                    appStore.showNotification('部分文件被占用，无法完全清空', 'warning')
                }
                refreshWorkspace()
            })
        } else {
            workspaceFiles.value = []
            appStore.showNotification('清理完成 (仅前端)', 'info')
        }
    } catch(e) {}
}

function toggleSideTool(tool: 'input' | 'analysis' | 'display') {
  if (activeSideTool.value === tool && isSidebarOpen.value) {
    isSidebarOpen.value = false
  } else {
    activeSideTool.value = tool
    isSidebarOpen.value = true
  }
}

/* -------- 自定义下拉栏逻辑 (与 BLAST 同步) -------- */
function toggleTreeDropdown(name: string, event: MouseEvent) {
  event.stopPropagation()
  openDropdown.value = openDropdown.value === name ? null : name
}
function selectTreeOption(field: string, value: string) {
  if (field === 'msa') treeWorkflows.msa = value
  else if (field === 'engine') treeWorkflows.engine = value
  else if (field === 'model') treeWorkflows.model = value
  else if (field === 'mode') settings.mode = value as any
  openDropdown.value = null
}
function getMsaLabel() { return msaOptions.find(o => o.value === treeWorkflows.msa)?.label || treeWorkflows.msa }
function getEngineLabel() { return engineOptions.find(o => o.value === treeWorkflows.engine)?.label || treeWorkflows.engine }
function getModelLabel() { return modelOptions.value.find(o => o.value === treeWorkflows.model)?.label || treeWorkflows.model }
function getLayoutLabel() { return layoutModeOptions.find(o => o.value === settings.mode)?.label || settings.mode }

// 全局点击关闭
if (typeof document !== 'undefined') {
  document.addEventListener('click', () => { openDropdown.value = null })
}

function handleFileUpload(e: Event) {
    const files = (e.target as HTMLInputElement).files
    if (files) {
        selectedFiles.value = Array.from(files)
        appStore.showNotification(`已添加 ${files.length} 个本地序列文件`, 'info')
    }
}

async function importSequences() {
    if (selectedFiles.value.length > 0) {
        appStore.showNotification('正在预处理并上传本地序列...', 'info')
        isLoading.value = true
        
        try {
            let combinedContent = ''
            for (const file of selectedFiles.value) {
                const text = await file.text()
                if (!text.trim().startsWith('>')) {
                    combinedContent += `>${file.name}\n${text}\n`
                } else {
                    combinedContent += `\n${text}\n`
                }
            }
            
        try {
            const bridge = await initBridge()
            if (bridge && typeof bridge.save_tree_sequences === 'function') {
                bridge.save_tree_sequences(combinedContent)
            }
        } catch(err) {}
            
            selectedFiles.value = []
            appStore.showNotification('序列已完全载入内核，准备执行 MSA 预处理...', 'success')
            activeSideTool.value = 'analysis'
            refreshWorkspace()
        } catch(e) {
            console.error("Import failed", e)
            appStore.showNotification('读取序列文件失败', 'error')
        } finally {
            isLoading.value = false
        }
    } else if (workspaceFiles.value.length > 0) {
        appStore.showNotification('序列已载入内核，准备执行 MSA 预处理...', 'success')
        activeSideTool.value = 'analysis'
    } else {
        appStore.showNotification('请先添加序列文件', 'error')
    }
}

async function requestAnalysis() {
    isLoading.value = true
    appStore.showNotification(`正在启动 [${treeWorkflows.engine}] 发育分析管线...`, 'info')
    try {
        const params = {
            ...treeWorkflows,
            // 只有在明确不对比对时，才使用快速(k-mer)模式；否则应进入标准比对管线
            mode: treeWorkflows.msa === 'none' ? 'rapid' : 'standard'
        }
        const bridge = await initBridge()
        bridge.request_tree_analysis(JSON.stringify(params))
    } catch(e) {
        isLoading.value = false
        console.error("Analysis request failed", e)
    }
}

async function handleReroot() {
    if (selectedNode.value) {
        try {
            const bridge = await initBridge()
            bridge.request_tree_reroot(selectedNode.value.name)
            menuVisible.value = false
        } catch(e) {}
    }
}

function openNCBI() {
    if (selectedNode.value?.name) {
        window.open(`https://www.ncbi.nlm.nih.gov/taxonomy/?term=${encodeURIComponent(selectedNode.value.name)}`, '_blank')
    }
    menuVisible.value = false
}

function closeMenu() {
    menuVisible.value = false
}

onMounted(() => {
    appStore.setPageTitle('进化树分析')
    refreshWorkspace()
    
    // @ts-ignore
    window.treeView = {
        loadNewick: (content: string) => { 
            loadNewick(content)
            isLoading.value = false
        },
        setLoading: (val: boolean, msg?: string, percent?: number) => { 
            isLoading.value = val 
            if (msg) loadingMsg.value = msg
            if (percent !== undefined) loadingProgress.value = percent
        },
        handleExternalFiles: (paths: string[]) => {
            if (!paths || paths.length === 0) return
            
            const firstPath = paths[0]
            if (paths.length === 1 && firstPath && (firstPath.endsWith('.nwk') || firstPath.endsWith('.newick') || firstPath.endsWith('.tree'))) {
                appStore.showNotification(`正在加载树文件...`, 'info')
                const bridge = getBridge()
                // @ts-ignore
                if (bridge && typeof bridge.read_result_file === 'function') {
                    // @ts-ignore
                    bridge.read_result_file(firstPath).then((content: string) => {
                        if (content) loadNewick(content)
                    })
                }
            } else {
                appStore.showNotification(`正在将 ${paths.length} 个文件载入工作区...`, 'info')
                initBridge().then(bridge => {
                    // @ts-ignore
                    if (bridge && typeof bridge.add_tree_workspace_files === 'function') {
                        // @ts-ignore
                        bridge.add_tree_workspace_files(JSON.stringify(paths))
                        setTimeout(() => refreshWorkspace(), 500)
                    }
                    appStore.showNotification('序列已添加，请点击“载入并预处理”进入下一步', 'success')
                })
            }
        }

    }

    if (renderer) {
        renderer.onNodeClick = (node: any, e: MouseEvent) => {
            selectedNode.value = node
            menuPos.value = { x: e.clientX, y: e.clientY }
            menuVisible.value = true
        }
    }
})
</script>

<template>
  <div v-if="activeSideTool" class="tree-workspace-container">
    <!-- 顶部工具菜单栏 (板块1) -->
    <header class="tree-toolbar-top">
      <div class="tool-items">
        <div class="tool-btn" :class="{ active: activeSideTool === 'input' && isSidebarOpen }" @click="toggleSideTool('input')">
          <span class="icon">📥</span>
          <span class="label">数据采集</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'analysis' && isSidebarOpen }" @click="toggleSideTool('analysis')">
          <span class="icon">🧬</span>
          <span class="label">分析分析</span>
        </div>
        <div class="tool-divider"></div>
        <div class="tool-btn" :class="{ active: activeSideTool === 'display' && isSidebarOpen }" @click="toggleSideTool('display')">
          <span class="icon">💡</span>
          <span class="label">视图控制</span>
        </div>
      </div>
    </header>

    <div class="tree-main-area">
      <!-- 左侧工具展开栏 (板块2) -->
      <aside class="tree-sidebar" :class="{ collapsed: !isSidebarOpen }">
        <div class="sidebar-content scroll-v">
          
          <!-- 采集面板 -->
          <div v-if="activeSideTool === 'input'" class="panel-section">
            <h3 class="section-title">▶ 数据采集</h3>
            <div class="upload-zone-neo" @click="fileInput?.click()">
              <span class="dz-icon">📁</span>
              <span class="dz-text">{{ (selectedFiles?.length || 0) > 0 ? `已选 ${selectedFiles.length} 个文件` : '上传 FASTA/SEQ' }}</span>
              <input type="file" ref="fileInput" hidden multiple @change="handleFileUpload" />
            </div>
            
            <div class="input-divider">待分析清单 (Workspace)</div>
            
            <!-- 文件清单列表 -->
            <div class="workspace-list-neo scroll-v">
              <div v-if="(!workspaceFiles || workspaceFiles.length === 0) && (!selectedFiles || selectedFiles.length === 0)" class="empty-list-hint">
                 暂无导入文件
              </div>
              <div v-for="file in workspaceFiles" :key="'ws-'+file" 
                   class="workspace-item" 
                   :class="{ 'selectable-result': file.toLowerCase().endsWith('.nwk') }"
                   @click="file.toLowerCase().endsWith('.nwk') ? loadPrecomputedTree(file) : null">
                 <span class="file-icon">{{ file.toLowerCase().endsWith('.nwk') ? '🌲' : '📄' }}</span>
                 <span class="file-name" :title="file">{{ file }}</span>
                 <span class="file-badge" :class="{ 'badge-result': file.toLowerCase().endsWith('.nwk') }">
                   {{ file.toLowerCase().endsWith('.nwk') ? 'Result' : 'Staged' }}
                 </span>
                 <button v-if="file.toLowerCase().endsWith('.nwk')" class="btn-mini-load">查看</button>
              </div>
              <div v-for="(file, idx) in selectedFiles" :key="'sel-'+(file?.name || idx)" class="workspace-item new-item">
                 <span class="file-icon">🆕</span>
                 <span class="file-name">{{ file?.name || 'Unknown' }}</span>
              </div>
            </div>

            <div class="actions-footer">
               <button class="btn-block-primary" @click="importSequences">载入并预处理</button>
               <div style="display: flex; justify-content: space-between; margin-top: 10px;">
                   <button class="btn-text-link" @click="refreshWorkspace">刷新工作区</button>
                   <button class="btn-text-link" style="color: #ff4d4f;" @click="clearWorkspace">清空列表</button>
               </div>
            </div>
          </div>

          <!-- 分析参数 -->
          <div v-if="activeSideTool === 'analysis'" class="panel-section">
            <h3 class="section-title">🧬 分析管线配置</h3>
            <div class="form-group">
              <label>多序列比对 (MSA)</label>
              <div class="select-box-neo" @click.stop="toggleTreeDropdown('msa', $event)">
                {{ getMsaLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'msa'" class="dropdown-list">
                  <div v-for="o in msaOptions" :key="o.value" class="opt" :class="{ selected: treeWorkflows.msa === o.value }" @click.stop="selectTreeOption('msa', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>分析引擎 (ENGINE)</label>
              <div class="select-box-neo" @click.stop="toggleTreeDropdown('engine', $event)">
                {{ getEngineLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'engine'" class="dropdown-list">
                  <div v-for="o in engineOptions" :key="o.value" class="opt" :class="{ selected: treeWorkflows.engine === o.value }" @click.stop="selectTreeOption('engine', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>进化模型 (MODEL)</label>
              <div class="select-box-neo" @click.stop="toggleTreeDropdown('model', $event)">
                {{ getModelLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'model'" class="dropdown-list">
                  <div v-for="o in modelOptions" :key="o.value" class="opt" :class="{ selected: treeWorkflows.model === o.value }" @click.stop="selectTreeOption('model', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>BOOTSTRAP 随机采样: {{ treeWorkflows.bootstrap }}</label>
              <input type="range" v-model.number="treeWorkflows.bootstrap" min="0" max="1000" step="100" class="neo-range" />
            </div>
            
            <div class="section-actions" style="margin-top: 30px;">
                <button class="btn-block-primary" @click="requestAnalysis" :disabled="isLoading">启动分析管线</button>
            </div>
          </div>

          <!-- 视图控制 -->
          <div v-if="activeSideTool === 'display'" class="panel-section">
            <h3 class="section-title">💡 视图控制</h3>
            <div class="form-group">
              <label>拓扑形态</label>
              <div class="select-box-neo" @click.stop="toggleTreeDropdown('layoutMode', $event)">
                {{ getLayoutLabel() }} <span class="arrow">▼</span>
                <div v-if="openDropdown === 'layoutMode'" class="dropdown-list">
                  <div v-for="o in layoutModeOptions" :key="o.value" class="opt" :class="{ selected: settings.mode === o.value }" @click.stop="selectTreeOption('mode', o.value)">{{ o.label }}</div>
                </div>
              </div>
            </div>
            <div class="neo-checkbox-group">
               <label><input type="checkbox" v-model="settings.showLabels" style="accent-color: #2563eb;" /> 显示样本标签</label>
               <label><input type="checkbox" v-model="settings.useBranchLengths" style="accent-color: #2563eb;" /> 使用原始进化长度</label>
            </div>
            <div class="form-group">
               <label>字体缩放: {{ settings.fontSize }}px</label>
               <input type="range" v-model.number="settings.fontSize" min="8" max="24" class="neo-range" />
            </div>
            <div class="form-group" style="margin-top: 16px;">
               <button class="btn-block-primary" @click="midpointRooting">中点定根 (Midpoint Root)</button>
            </div>

            <div class="divider-line"></div>
            
            <div class="form-group" style="margin-bottom: 20px;">
              <label>渲染内核引擎 (Engine Switch)</label>
              <div class="neo-checkbox-group" style="margin-top: 10px;">
                <label><input type="radio" value="hybrid" v-model="renderEngine" style="accent-color: #2563eb;" /> Hybrid Canvas (超大树性能级)</label>
                <label><input type="radio" value="phylotree" v-model="renderEngine" style="accent-color: #2563eb;" /> PhyloTreeJS (枝干高级交互与折叠)</label>
              </div>
            </div>

            <div class="section-actions">
                <button class="btn-block-secondary" @click="exportSVG" :disabled="!hasTree || renderEngine !== 'hybrid'">导出进化树 (Hybrid SVG)</button>
            </div>
          </div>

        </div>

        <!-- 显隐控制 Handle -->
        <div class="sidebar-collapse-toggle" @click="isSidebarOpen = !isSidebarOpen">
          {{ isSidebarOpen ? '◀' : '▶' }}
        </div>
      </aside>

      <!-- 结果显示栏 (板块3) -->
      <main class="tree-results">
        
        <!-- Hybrid Canvas Engine -->
        <div v-show="renderEngine === 'hybrid'" ref="containerRef" class="canvas-container"></div>
        
        <!-- PhyloTree D3 Engine -->
        <PhylotreeWidget 
             v-if="renderEngine === 'phylotree' && hasTree" 
             :newick="rawNewick" 
             :mode="settings.mode" 
             style="width: 100%; height: 100%;" 
        />
        
        <div v-if="!hasTree && !isLoading" class="empty-state">
           <div class="empty-content">
             <span class="icon">🧬</span>
             <h3>NCBI Tree Station 2.0</h3>
             <p>请上传序列文件或拖入数据，启动专业的系统发育分析管线。</p>
           </div>
        </div>

        <div v-if="isLoading" class="loading-overlay">
           <div class="loader"></div>
           <p>{{ loadingMsg }}</p>
           <div v-if="loadingProgress > 0" class="progress-bar-container">
             <div class="progress-bar-fill" :style="{ width: loadingProgress + '%' }"></div>
           </div>
        </div>

        <!-- 右分屏右键菜单 -->
        <div v-if="menuVisible" class="node-context-menu" :style="{ left: menuPos.x + 'px', top: menuPos.y + 'px' }" v-click-outside="closeMenu">
          <div class="menu-title">{{ selectedNode?.name }}</div>
          <div class="menu-action" @click="handleReroot">🎯 重定根 (Reroot)</div>
          <div class="menu-action" @click="openNCBI">🌐 在 NCBI 查看</div>
          <div class="menu-sep"></div>
          <div class="menu-action danger" @click="closeMenu">关闭菜单</div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.tree-workspace-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  overflow: hidden;
}

/* 顶部菜单栏 */
.tree-toolbar-top {
  height: 60px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 100;
}
.tool-items { display: flex; align-items: center; gap: 8px; }
.tool-btn {
  display: flex; align-items: center; gap: 10px; padding: 8px 16px;
  cursor: pointer; border-radius: 10px; color: #64748b; font-weight: 600; font-size: 0.82rem;
}
.tool-btn:hover { background: #f8fafc; color: #1e293b; }
.tool-btn.active { color: #2563eb; background: #eff6ff; }
.tool-divider { width: 1px; height: 24px; background: #e2e8f0; margin: 0 10px; }

.btn-primary-run {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white; padding: 10px 24px; border-radius: 10px;
  font-weight: 700; font-size: 0.85rem; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
  display: flex; align-items: center; gap: 10px;
}
.btn-export {
  background: #f8fafc; border: 1px solid #e2e8f0; color: #475569;
  padding: 8px 18px; border-radius: 10px; font-weight: 800; font-size: 0.78rem;
}

/* 下方板块容器 */
.tree-main-area { flex: 1; display: flex; overflow: hidden; background: #f8fafc; }

/* 侧边栏 */
.tree-sidebar {
  width: 360px; background: white; transition: none;
  display: flex; flex-direction: column; position: relative; z-index: 5;
  border-right: 1px solid #e2e8f0; overflow: visible;
}
.tree-sidebar.collapsed { width: 0; border-right: none; }
.sidebar-content { padding: 24px; flex: 1; overflow-y: auto; white-space: nowrap; }
.collapsed .sidebar-content { display: none; }

.sidebar-collapse-toggle {
  position: absolute; left: 100%; top: 50%; transform: translateY(-50%);
  width: 20px; height: 60px; background: white; border: 1px solid #e2e8f0;
  border-left: none; border-radius: 0 10px 10px 0;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; z-index: 10; font-size: 0.61rem; color: #94a3b8;
  box-shadow: 2px 0 6px rgba(0,0,0,0.06);
}

.section-title { font-size: 1rem; font-weight: 800; color: #0f172a; margin-bottom: 20px; }

/* UI 组件 */
.upload-zone-neo {
  border: 2px dashed #cbd5e1; border-radius: 12px; padding: 24px; text-align: center;
  cursor: pointer; transition: all 0.2s; background: #f8fafc;
}
.upload-zone-neo:hover { border-color: #2563eb; background: #f0f7ff; }
.dz-icon { font-size: 1.8rem; display: block; margin-bottom: 8px; }
.dz-text { font-size: 0.82rem; font-weight: 700; color: #475569; }

/* 工作区列表样式 */
.workspace-list-neo {
  height: 320px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 8px; margin-top: 10px;
}
.empty-list-hint {
  height: 100%; display: flex; align-items: center; justify-content: center;
  color: #94a3b8; font-size: 0.8rem; font-style: italic;
}
.workspace-item {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px;
  background: white; border: 1px solid #f1f5f9; border-radius: 8px; margin-bottom: 6px;
  font-size: 0.8rem; font-family: 'JetBrains Mono', monospace;
}
.workspace-item.new-item { border-left: 3px solid #3b82f6; }
.workspace-item.selectable-result { cursor: pointer; border-left: 3px solid #2563eb; background: #f0f7ff; }
.workspace-item.selectable-result:hover { background: #e0efff; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #334155; }
.file-badge { font-size: 0.65rem; background: #f1f5f9; color: #64748b; padding: 2px 6px; border-radius: 4px; }
.file-badge.badge-result { background: #2563eb; color: white; }
.btn-mini-load { 
    background: #2563eb; color: white; border: none; padding: 2px 8px; 
    border-radius: 4px; font-size: 0.65rem; cursor: pointer; margin-left: 5px;
}

/* UI 组件 - BLAST 同款自定义下拉栏 */
.select-box-neo {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 10px 14px; font-size: 0.82rem; cursor: pointer; position: relative;
  display: flex; justify-content: space-between; align-items: center;
  transition: border-color 0.2s;
}
.select-box-neo:hover { border-color: #cbd5e1; }
.select-box-neo .arrow { color: #94a3b8; font-size: 0.6rem; margin-left: 8px; }

.dropdown-list {
  position: absolute; top: 110%; left: 0; right: 0; background: white;
  border: 1px solid #e2e8f0; border-radius: 10px;
  box-shadow: 0 8px 20px rgba(0,0,0,0.12); z-index: 100;
  max-height: 250px; overflow-y: auto; padding: 6px;
}
.dropdown-list .opt {
  padding: 10px 12px; font-size: 0.82rem; border-radius: 6px; cursor: pointer;
}
.dropdown-list .opt:hover { background: #f1f5f9; color: #2563eb; }
.dropdown-list .opt.selected { color: #2563eb; font-weight: 700; background: #eff6ff; }

.form-group { margin-bottom: 20px; }
.form-group label {
  font-size: 0.75rem; font-weight: 800; color: #64748b; margin-bottom: 8px;
  display: block; text-transform: uppercase; letter-spacing: 0.02em;
}

.neo-checkbox-group { display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }
.neo-checkbox-group label { display: flex; align-items: center; gap: 10px; font-size: 0.85rem; font-weight: 500; cursor: pointer; }

/* 结果区 */
.tree-results { flex: 1; background: white; position: relative; overflow: hidden; }
.canvas-container { width: 100%; height: 100%; }

.empty-state {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  text-align: center; background: white; z-index: 5;
}
.empty-content .icon { font-size: 4rem; opacity: 0.1; }

.loading-overlay {
  position: absolute; inset: 0; background: rgba(255,255,255,0.8);
  display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 10;
}
.loader {
  width: 40px; height: 40px; border: 4px solid #f3f3f3; border-top: 4px solid #2563eb;
  border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 20px;
}
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

/* Context Menu */
.node-context-menu {
  position: fixed; z-index: 1000; background: white; padding: 6px; border-radius: 10px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.15); border: 1px solid #e2e8f0; min-width: 160px;
}
.menu-title { font-size: 0.7rem; font-weight: 800; padding: 6px 12px; border-bottom: 1px solid #f1f5f9; color: #94a3b8; }
.menu-action { padding: 10px 12px; font-size: 0.85rem; border-radius: 6px; cursor: pointer; }
.menu-action:hover { background: #f1f5f9; }
.menu-action.danger { color: #ef4444; }
.menu-sep { height: 1px; background: #f1f5f9; margin: 4px 0; }

.actions-footer { margin-top: 20px; display: flex; flex-direction: column; gap: 10px; }
.btn-block-primary {
  width: 100%; background: #2563eb; color: white; padding: 12px; border-radius: 10px;
  font-weight: 700; font-size: 0.85rem; border: none; cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
}
.btn-block-primary:hover { background: #1d4ed8; }
.btn-block-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-block-secondary {
  width: 100%; padding: 12px; border-radius: 10px;
  font-weight: 600; font-size: 0.85rem; cursor: pointer;
  background: #f8fafc; border: 1px solid #cbd5e1; color: #334155;
  transition: all 0.2s;
}
.btn-block-secondary:hover { background: #f1f5f9; border-color: #94a3b8; }
.btn-block-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

.divider-line {
  height: 1px; background: #e2e8f0; margin: 20px 0;
}

.btn-text-link { background: none; border: none; color: #64748b; font-size: 0.75rem; text-decoration: underline; cursor: pointer; }

.scroll-v { overflow-y: auto; scrollbar-width: thin; }
.scroll-v::-webkit-scrollbar { width: 6px; }
.scroll-v::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }

.progress-bar-container {
  width: 240px; height: 6px; background: #e2e8f0; border-radius: 3px;
  overflow: hidden; margin-top: 15px;
}
.progress-bar-fill {
  height: 100%; background: #2563eb; transition: width 0.3s ease;
}
</style>
