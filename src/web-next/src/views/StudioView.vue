<script setup lang="ts">
/**
 * StudioView - 节点工作台视图
 * 核心可视化工作流编辑器
 * 替代旧版基于 iframe 的 node_studio.html
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStudioStore, type NodeData } from '../stores/studio'
import { getBridge } from '../bridge/pyqt-bridge'
import { useAppStore } from '../stores/app'
import NodeCard from '../components/studio/NodeCard.vue'
import ConnectionLine from '../components/studio/ConnectionLine.vue'
import NodeLibrary from '../components/studio/NodeLibrary.vue'
import BaseButton from '../components/ui/BaseButton.vue'

const studio = useStudioStore()
const appStore = useAppStore()
const canvasRef = ref<HTMLDivElement | null>(null)

/* -------- 视口拖拽 -------- */
const isPanning = ref(false)
const panStart = ref({ x: 0, y: 0 })

function onCanvasMouseDown(event: MouseEvent): void {
  // 右键或中键拖拽画布
  if (event.button === 1 || event.button === 2) {
    isPanning.value = true
    panStart.value = { x: event.clientX, y: event.clientY }
    event.preventDefault()
  } else if (event.button === 0 && (event.target as HTMLElement)?.id === 'canvas-surface') {
    // 左键点击空白处 -> 取消选择
    studio.clearSelection()
  }
}

function onCanvasMouseMove(event: MouseEvent): void {
  if (isPanning.value) {
    const deltaX = event.clientX - panStart.value.x
    const deltaY = event.clientY - panStart.value.y
    studio.panViewport(deltaX, deltaY)
    panStart.value = { x: event.clientX, y: event.clientY }
  }
  if (studio.isDrawingConnection) {
    const rect = canvasRef.value?.getBoundingClientRect()
    if (rect) {
      studio.drawingEndPos = {
        x: (event.clientX - rect.left - studio.viewport.offsetX) / studio.viewport.scale,
        y: (event.clientY - rect.top - studio.viewport.offsetY) / studio.viewport.scale
      }
    }
  }
}

function onCanvasMouseUp(): void {
  isPanning.value = false
  studio.isDrawingConnection = false
  studio.drawingFrom = null
}

function onCanvasWheel(event: WheelEvent): void {
  event.preventDefault()
  const delta = event.deltaY > 0 ? -0.08 : 0.08
  studio.zoomViewport(delta, event.clientX, event.clientY)
}

/* -------- 键盘快捷键 -------- */
function onKeyDown(event: KeyboardEvent): void {
  if (event.ctrlKey && event.key === 'z') {
    event.preventDefault()
    studio.undo()
  } else if (event.ctrlKey && event.key === 'y') {
    event.preventDefault()
    studio.redo()
  } else if (event.key === 'Delete' || event.key === 'Backspace') {
    deleteSelected()
  }
}

function deleteSelected(): void {
  for (const nodeId of studio.selectedNodeIds) {
    studio.removeNode(nodeId)
  }
  for (const connId of studio.selectedConnIds) {
    studio.removeConnection(connId)
  }
  studio.clearSelection()
}

/* -------- 工具栏操作 -------- */
function saveTopology(): void {
  try {
    getBridge().save_topology(studio.serialize())
    appStore.showNotification('拓扑已保存', 'success')
  } catch (error) {
    console.warn('[Studio] Save failed:', error)
  }
}

function runWorkflow(): void {
  try {
    getBridge().run_workflow(studio.serialize())
    appStore.showNotification('工作流已开始执行', 'success')
  } catch (error) {
    console.warn('[Studio] Run failed:', error)
  }
}

function clearCanvas(): void {
  studio.clear()
}

/* -------- 节点拖入处理 -------- */
function handleNodeDrop(nodeType: string, label: string, posX: number, posY: number, config?: Partial<NodeData>): void {
  studio.addNode(nodeType, label, posX, posY, config)
}

/* -------- 画布变换 CSS -------- */
const canvasTransform = computed(() =>
  `translate(${studio.viewport.offsetX}px, ${studio.viewport.offsetY}px) scale(${studio.viewport.scale})`
)

const scalePercent = computed(() => Math.round(studio.viewport.scale * 100))

const drawingStartPos = computed(() => {
  if (!studio.drawingFrom) return { x: 0, y: 0 }
  const node = studio.nodeList.find(n => n.pins.some(p => p.pinId === studio.drawingFrom))
  if (!node) return { x: 0, y: 0 }
  
  const pin = node.pins.find(p => p.pinId === studio.drawingFrom)
  const isInput = pin?.direction === 'input'
  const w = node.width || 200
  const h = node.height || 150
  
  return {
    x: node.posX + (isInput ? 0 : w),
    y: node.posY + h / 2
  }
})

/* -------- 生命周期 -------- */
onMounted(() => {
  document.addEventListener('keydown', onKeyDown)
  // 禁用右键菜单
  canvasRef.value?.addEventListener('contextmenu', (event) => event.preventDefault())
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <div class="studio-view">
    <!-- 顶部工具栏 -->
    <div class="studio-toolbar">
      <div class="toolbar-left">
        <BaseButton variant="ghost" size="sm" @click="studio.nodeLibraryOpen = !studio.nodeLibraryOpen" title="节点库">📦 节点库</BaseButton>
        <div class="tb-divider" />
        <BaseButton variant="ghost" size="sm" @click="studio.undo" title="撤销 (Ctrl+Z)">↩</BaseButton>
        <BaseButton variant="ghost" size="sm" @click="studio.redo" title="重做 (Ctrl+Y)">↪</BaseButton>
        <div class="tb-divider" />
        <BaseButton variant="ghost" size="sm" @click="deleteSelected" :disabled="!studio.hasSelection" title="删除选中">🗑</BaseButton>
      </div>
      <div class="toolbar-center">
        <span class="zoom-label">{{ scalePercent }}%</span>
        <BaseButton variant="ghost" size="sm" @click="studio.zoomViewport(-0.1, 0, 0)">−</BaseButton>
        <BaseButton variant="ghost" size="sm" @click="studio.resetViewport()">⟳</BaseButton>
        <BaseButton variant="ghost" size="sm" @click="studio.zoomViewport(0.1, 0, 0)">+</BaseButton>
      </div>
      <div class="toolbar-right">
        <BaseButton variant="secondary" size="sm" @click="saveTopology">💾 保存</BaseButton>
        <BaseButton variant="primary" size="sm" @click="runWorkflow">▶ 执行</BaseButton>
        <BaseButton variant="ghost" size="sm" style="color: #ef4444;" @click="clearCanvas">清空</BaseButton>
      </div>
    </div>

    <div class="studio-workspace">
      <!-- 节点库侧面板 -->
      <NodeLibrary
        v-if="studio.nodeLibraryOpen"
        @add-node="handleNodeDrop"
      />

      <!-- 画布 -->
      <div
        ref="canvasRef"
        class="canvas-container"
        @mousedown="onCanvasMouseDown"
        @mousemove="onCanvasMouseMove"
        @mouseup="onCanvasMouseUp"
        @wheel.prevent="onCanvasWheel"
      >
        <!-- 网格背景 -->
        <svg class="grid-bg" width="100%" height="100%">
          <defs>
            <pattern id="grid-small" width="20" height="20" patternUnits="userSpaceOnUse"
              :patternTransform="`translate(${studio.viewport.offsetX}, ${studio.viewport.offsetY}) scale(${studio.viewport.scale})`">
              <circle cx="10" cy="10" r="0.5" fill="#334155" opacity="0.2" />
            </pattern>
            <pattern id="grid-large" width="100" height="100" patternUnits="userSpaceOnUse"
              :patternTransform="`translate(${studio.viewport.offsetX}, ${studio.viewport.offsetY}) scale(${studio.viewport.scale})`">
              <circle cx="50" cy="50" r="1" fill="#334155" opacity="0.15" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid-small)" />
          <rect width="100%" height="100%" fill="url(#grid-large)" />
        </svg>

        <!-- 变换层 -->
        <div id="canvas-surface" class="canvas-transform" :style="{ transform: canvasTransform }">
          <!-- 连线 SVG 层 -->
          <svg class="connections-layer">
            <ConnectionLine
              v-for="conn in studio.connectionList"
              :key="conn.connId"
              :connection="conn"
            />
            <!-- 正在绘制的临时连线 -->
            <line
              v-if="studio.isDrawingConnection"
              :x1="drawingStartPos.x" :y1="drawingStartPos.y"
              :x2="studio.drawingEndPos.x" :y2="studio.drawingEndPos.y"
              stroke="#3b82f6" stroke-width="2" stroke-dasharray="6,4"
              style="pointer-events: none;"
            />
          </svg>

          <!-- 节点层 -->
          <NodeCard
            v-for="node in studio.nodeList"
            :key="node.nodeId"
            :node="node"
            :selected="studio.selectedNodeIds.has(node.nodeId)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.studio-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f172a;
}

/* 工具栏 */
.studio-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  z-index: 50;
}

.toolbar-left, .toolbar-right, .toolbar-center {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tb-btn {
  padding: 5px 10px;
  background: transparent;
  color: #94a3b8;
  border-radius: 4px;
  font-size: 0.78rem;
  transition: all 0.15s;
  white-space: nowrap;
}
.tb-btn:hover { background: rgba(255, 255, 255, 0.06); color: #e2e8f0; }
.tb-btn.sm { padding: 3px 7px; font-size: 0.85rem; }
.tb-btn.run { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.tb-btn.run:hover { background: rgba(59, 130, 246, 0.25); }
.tb-btn.danger { color: #f87171; }
.tb-btn.danger:hover { background: rgba(239, 68, 68, 0.1); }
.tb-btn:disabled { opacity: 0.3; cursor: not-allowed; }

.tb-divider { width: 1px; height: 16px; background: #334155; margin: 0 4px; }
.zoom-label { font-size: 0.72rem; color: #64748b; margin-right: 4px; min-width: 36px; text-align: right; }

/* 工作区 */
.studio-workspace {
  flex: 1;
  display: flex;
  overflow: hidden;
  position: relative;
}

/* 画布 */
.canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  cursor: grab;
}
.canvas-container:active { cursor: grabbing; }

.grid-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.canvas-transform {
  position: absolute;
  transform-origin: 0 0;
  will-change: transform;
}

.connections-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 10000px;
  height: 10000px;
  pointer-events: none;
  overflow: visible;
}
</style>
