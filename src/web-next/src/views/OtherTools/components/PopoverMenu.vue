<script setup lang="ts">
/**
 * PopoverMenu - 通用下拉浮层组件
 * 职责：点击触发区展开浮层；浮层传送到 body 并使用固定定位，避免被表格容器裁剪；
 * 点击外部、页面滚动或窗口缩放时自动收起；底部空间不足时向上展开。
 * 触发按钮与浮层内容均由父组件通过插槽提供，以便沿用父组件样式。
 */
import { ref, nextTick, onBeforeUnmount } from 'vue'

const props = withDefaults(
  defineProps<{
    align?: 'left' | 'right'
    disabled?: boolean
    width?: number
  }>(),
  {
    align: 'right',
    disabled: false,
    width: 0
  }
)

const open = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})

const GAP = 4
const EDGE = 8

function computePosition(): void {
  const el = triggerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const style: Record<string, string> = { top: `${rect.bottom + GAP}px` }
  if (props.align === 'right') {
    style.right = `${Math.max(EDGE, window.innerWidth - rect.right)}px`
  } else {
    style.left = `${Math.max(EDGE, rect.left)}px`
  }
  if (props.width) style.width = `${props.width}px`
  panelStyle.value = style
}

function flipIfOverflow(): void {
  const panel = panelRef.value
  const el = triggerRef.value
  if (!panel || !el) return
  const rect = el.getBoundingClientRect()
  const height = panel.offsetHeight
  const overflowBottom = rect.bottom + GAP + height > window.innerHeight - EDGE
  const fitsTop = rect.top - GAP - height > EDGE
  if (overflowBottom && fitsTop) {
    panelStyle.value = { ...panelStyle.value, top: `${rect.top - GAP - height}px` }
  }
}

function onDocPointerDown(ev: MouseEvent): void {
  const target = ev.target as Node | null
  if (!target) return
  if (triggerRef.value?.contains(target) || panelRef.value?.contains(target)) return
  close()
}

function onViewportChange(ev: Event): void {
  const target = ev.target
  if (panelRef.value && target instanceof Node && panelRef.value.contains(target)) return
  close()
}

function bindListeners(): void {
  document.addEventListener('mousedown', onDocPointerDown, true)
  window.addEventListener('scroll', onViewportChange, true)
  window.addEventListener('resize', onViewportChange)
}

function unbindListeners(): void {
  document.removeEventListener('mousedown', onDocPointerDown, true)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
}

async function toggle(): Promise<void> {
  if (props.disabled) return
  if (open.value) {
    close()
    return
  }
  computePosition()
  open.value = true
  bindListeners()
  await nextTick()
  flipIfOverflow()
}

function close(): void {
  if (!open.value) return
  open.value = false
  unbindListeners()
}

onBeforeUnmount(unbindListeners)

defineExpose({ close })
</script>

<template>
  <span ref="triggerRef" class="pm-trigger" @click.stop="toggle">
    <slot name="trigger" :open="open" />
  </span>
  <Teleport to="body">
    <div v-if="open" ref="panelRef" class="pm-panel" :style="panelStyle" @click.stop>
      <slot :close="close" />
    </div>
  </Teleport>
</template>

<style scoped>
.pm-trigger {
  display: inline-flex;
}

.pm-panel {
  position: fixed;
  z-index: 1200;
  min-width: 160px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 10px 24px -6px rgba(15, 23, 42, 0.18);
  padding: 6px;
}
</style>

