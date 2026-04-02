<script setup lang="ts">
/**
 * NodeCard - 节点卡片组件
 * 渲染单个工作流节点：标题栏 + 端口 + 参数区
 */
import { ref } from 'vue'
import { useStudioStore, type NodeData } from '../../stores/studio'

const props = defineProps<{
  node: NodeData
  selected: boolean
}>()

const studio = useStudioStore()

/* -------- 拖拽节点 -------- */
const isDragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })

function onNodeMouseDown(event: MouseEvent): void {
  if (event.button !== 0) return
  event.stopPropagation()
  studio.selectNode(props.node.nodeId, event.shiftKey)
  isDragging.value = true
  dragOffset.value = {
    x: event.clientX / studio.viewport.scale - props.node.posX,
    y: event.clientY / studio.viewport.scale - props.node.posY
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(event: MouseEvent): void {
  if (!isDragging.value) return
  const newX = event.clientX / studio.viewport.scale - dragOffset.value.x
  const newY = event.clientY / studio.viewport.scale - dragOffset.value.y
  studio.updateNodePosition(props.node.nodeId, newX, newY)
}

function onDragEnd(): void {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
}

/* -------- 连线拖拽 -------- */
function onPinMouseDown(event: MouseEvent, pinId: string): void {
  event.stopPropagation()
  studio.isDrawingConnection = true
  studio.drawingFrom = pinId
}

/** 状态徽标颜色 */
/** 处理参数变更事件 */
function onParamChange(event: Event, paramKey: string): void {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  studio.updateNodeParam(props.node.nodeId, paramKey, target.value)
}

/** 状态徽标颜色 */
function statusColor(status: string): string {
  const colorMap: Record<string, string> = {
    idle: '#64748b', running: '#3b82f6', done: '#10b981', error: '#ef4444'
  }
  return colorMap[status] ?? '#64748b'
}
</script>

<template>
  <div
    class="node-card"
    :class="{ selected, dragging: isDragging }"
    :style="{
      left: node.posX + 'px',
      top: node.posY + 'px',
      width: node.width + 'px',
      '--node-color': node.color
    }"
    @mousedown="onNodeMouseDown"
  >
    <!-- 标题栏 -->
    <div class="node-header" :style="{ background: node.color }">
      <span class="node-title">{{ node.label }}</span>
      <span class="node-status" :style="{ background: statusColor(node.status) }" />
    </div>

    <!-- 端口区 -->
    <div class="node-pins">
      <div class="pin-col inputs">
        <div
          v-for="pin in node.pins.filter(p => p.direction === 'input')"
          :key="pin.pinId"
          class="pin input"
          @mouseup.stop
          @mousedown.stop
        >
          <span class="pin-dot" />
          <span class="pin-label">{{ pin.label }}</span>
        </div>
      </div>
      <div class="pin-col outputs">
        <div
          v-for="pin in node.pins.filter(p => p.direction === 'output')"
          :key="pin.pinId"
          class="pin output"
          @mousedown.stop="onPinMouseDown($event, pin.pinId)"
        >
          <span class="pin-label">{{ pin.label }}</span>
          <span class="pin-dot" />
        </div>
      </div>
    </div>

    <!-- 参数区 -->
    <div v-if="node.params.length > 0" class="node-params">
      <div v-for="param in node.params" :key="param.key" class="param-row">
        <label>{{ param.label }}</label>
        <input
          v-if="param.type === 'text' || param.type === 'number'"
          :type="param.type"
          :value="param.value"
          class="param-input"
          @change="onParamChange($event, param.key)"
          @mousedown.stop
        />
        <select
          v-else-if="param.type === 'select'"
          :value="param.value"
          class="param-input"
          @change="onParamChange($event, param.key)"
          @mousedown.stop
        >
          <option v-for="opt in param.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </div>
    </div>

    <!-- 进度条 -->
    <div v-if="node.status === 'running'" class="progress-bar">
      <div class="progress-fill" :style="{ width: node.progress + '%' }" />
    </div>
  </div>
</template>

<style scoped>
.node-card {
  position: absolute;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  cursor: move;
  transition: box-shadow 0.15s;
  user-select: none;
}
.node-card.selected { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3), 0 4px 12px rgba(0, 0, 0, 0.3); }
.node-card.dragging { opacity: 0.9; z-index: 100; }

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  color: white;
}
.node-title { font-size: 0.78rem; font-weight: 600; }
.node-status { width: 8px; height: 8px; border-radius: 50%; }

.node-pins { display: flex; justify-content: space-between; padding: 6px 0; }
.pin-col { display: flex; flex-direction: column; gap: 4px; }
.pin-col.inputs { align-items: flex-start; }
.pin-col.outputs { align-items: flex-end; }

.pin {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  cursor: pointer;
}
.pin-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #64748b;
  border: 2px solid #334155;
  transition: all 0.15s;
}
.pin:hover .pin-dot { background: #3b82f6; border-color: #3b82f6; transform: scale(1.3); }
.pin-label { font-size: 0.7rem; color: #94a3b8; }

.node-params { padding: 6px 12px 10px; border-top: 1px solid #334155; }
.param-row { margin-bottom: 6px; }
.param-row label { display: block; font-size: 0.65rem; color: #64748b; margin-bottom: 2px; }
.param-input {
  width: 100%;
  padding: 4px 8px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #e2e8f0;
  font-size: 0.75rem;
}
.param-input:focus { outline: none; border-color: #3b82f6; }

.progress-bar { height: 3px; background: #334155; }
.progress-fill { height: 100%; background: #3b82f6; transition: width 0.3s; }
</style>
