<script setup lang="ts">
/**
 * ConnectionLine - 连线组件
 * 以 SVG 贝塞尔曲线渲染节点之间的连线
 */
import { computed } from 'vue'
import { useStudioStore, type ConnectionData } from '../../stores/studio'

const props = defineProps<{
  connection: ConnectionData
}>()

const studio = useStudioStore()

/** 计算贝塞尔曲线路径 */
const pathData = computed(() => {
  const sourceNode = studio.nodes.get(props.connection.sourceNode)
  const targetNode = studio.nodes.get(props.connection.targetNode)

  if (!sourceNode || !targetNode) return ''

  // 简化：从源节点右侧中心到目标节点左侧中心
  const sW = sourceNode.width || 200
  const sH = sourceNode.height || 150
  const tH = targetNode.height || 150

  const sourceX = sourceNode.posX + sW
  const sourceY = sourceNode.posY + sH / 2
  const targetX = targetNode.posX
  const targetY = targetNode.posY + tH / 2

  const controlOffset = Math.abs(targetX - sourceX) * 0.5
  const controlMinOffset = 60

  const cpSourceX = sourceX + Math.max(controlOffset, controlMinOffset)
  const cpTargetX = targetX - Math.max(controlOffset, controlMinOffset)

  return `M ${sourceX} ${sourceY} C ${cpSourceX} ${sourceY}, ${cpTargetX} ${targetY}, ${targetX} ${targetY}`
})

const isSelected = computed(() => studio.selectedConnIds.has(props.connection.connId))

function onClick(): void {
  studio.selectedConnIds.clear()
  studio.selectedConnIds.add(props.connection.connId)
}
</script>

<template>
  <g class="connection-line" @click.stop="onClick">
    <!-- 不可见的宽区域用于易于点击 -->
    <path
      :d="pathData"
      fill="none"
      stroke="transparent"
      stroke-width="12"
      style="cursor: pointer; pointer-events: stroke;"
    />
    <!-- 可见线条 -->
    <path
      :d="pathData"
      fill="none"
      :stroke="isSelected ? '#60a5fa' : '#475569'"
      :stroke-width="isSelected ? 2.5 : 2"
      stroke-linecap="round"
      style="pointer-events: none; transition: stroke 0.15s;"
    />
  </g>
</template>
