<script setup lang="ts">
/**
 * CommandPaletteDialog - 全局 Ctrl+K 命令与导航面板
 * 遵循 Modern Web Guidance `dialog` 与 `ime-safe-enter-submit` 准则：
 * - 原生 <dialog> + showModal() + closedby="any" + pointerdown/pointerup 回退
 * - 关闭时立即重置 dialog.returnValue = ''
 * - 上下方向键选择、Enter 执行时严格守卫中文输入法组字状态
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { shouldSubmitOnEnter } from '../../utils/ime'
import { useI18n } from '../../locales'

export interface PaletteCommand {
  id: string
  label: string
  group: string
  keywords: string
  shortcut?: string
  route?: string
  action?: 'citations' | 'toggle-locale' | 'probe-health'
}

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
  (e: 'navigate', route: string, title: string): void
  (e: 'action', action: 'citations' | 'toggle-locale' | 'probe-health'): void
}>()

const { t } = useI18n()
const dialogRef = ref<HTMLDialogElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)
const query = ref('')
const activeIndex = ref(0)
let pressedOutside = false

const commands = computed<PaletteCommand[]>(() => [
  { id: 'nav-dashboard', label: t('palette.cmd_dashboard'), group: t('palette.group_modules'), keywords: 'dashboard home 首页 概览', route: '/' },
  { id: 'nav-blast', label: t('palette.cmd_blast'), group: t('palette.group_modules'), keywords: 'blast 16s 比对 序列 鉴定', route: '/blast' },
  { id: 'nav-assembly', label: t('palette.cmd_assembly'), group: t('palette.group_modules'), keywords: 'assembly ngcs 拼接 组装 fastq', route: '/assembly' },
  { id: 'nav-analysis', label: t('palette.cmd_analysis'), group: t('palette.group_modules'), keywords: 'analysis annotation phage structure pangenome sanger viewer 注释 噬菌体', route: '/analysis' },
  { id: 'nav-tree', label: t('palette.cmd_tree'), group: t('palette.group_modules'), keywords: 'tree phylo figure studio viridic lovis4u clinker 绘图 发育树', route: '/tree' },
  { id: 'nav-strain', label: t('palette.cmd_strain'), group: t('palette.group_modules'), keywords: 'strain freezer 3d 菌种 冰箱', route: '/strain' },
  { id: 'nav-other', label: t('palette.cmd_other'), group: t('palette.group_modules'), keywords: 'other tools mail sangon 邮件 生工 自动化', route: '/other-tools' },
  { id: 'nav-help', label: t('palette.cmd_help'), group: t('palette.group_modules'), keywords: 'help docs manual 帮助 手册', route: '/help' },
  { id: 'nav-settings', label: t('palette.cmd_settings'), group: t('palette.group_modules'), keywords: 'settings config update lan 设置 配置 更新', route: '/settings' },
  { id: 'act-citations', label: t('palette.cmd_citations'), group: t('palette.group_actions'), keywords: 'citation bibtex reference doi 引文 文献', action: 'citations' },
  { id: 'act-locale', label: t('palette.cmd_locale'), group: t('palette.group_actions'), keywords: 'locale language zh en 语言 中英文', action: 'toggle-locale' },
  { id: 'act-health', label: t('palette.cmd_health'), group: t('palette.group_actions'), keywords: 'health ping cpu gpu metrics 检测 健康', action: 'probe-health' },
])

const filteredCommands = computed<PaletteCommand[]>(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return commands.value
  return commands.value.filter(
    (cmd) =>
      cmd.label.toLowerCase().includes(q) ||
      cmd.group.toLowerCase().includes(q) ||
      cmd.keywords.toLowerCase().includes(q)
  )
})

watch(filteredCommands, () => {
  activeIndex.value = 0
})

function closeDialog(): void {
  const dialog = dialogRef.value
  if (dialog && typeof dialog.close === 'function') {
    dialog.close('close')
  } else {
    handleDialogClose()
  }
}

function handleDialogClose(): void {
  const dialog = dialogRef.value
  if (dialog) {
    dialog.returnValue = ''
  }
  query.value = ''
  activeIndex.value = 0
  emit('update:open', false)
}

function executeCommand(cmd: PaletteCommand): void {
  closeDialog()
  if (cmd.route) {
    emit('navigate', cmd.route, cmd.label)
  } else if (cmd.action) {
    emit('action', cmd.action)
  }
}

function handleInputKeydown(event: KeyboardEvent): void {
  const total = filteredCommands.value.length
  if (event.key === 'ArrowDown' && total > 0) {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % total
    return
  }
  if (event.key === 'ArrowUp' && total > 0) {
    event.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + total) % total
    return
  }
  if (shouldSubmitOnEnter(event) && total > 0) {
    event.preventDefault()
    const target = filteredCommands.value[activeIndex.value] ?? filteredCommands.value[0]
    if (target) executeCommand(target)
  }
}

function isPointerOutside(event: PointerEvent, dialog: HTMLDialogElement): boolean {
  const rect = dialog.getBoundingClientRect()
  return (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
}

function handlePointerDown(event: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  pressedOutside = isPointerOutside(event, dialog)
}

function handlePointerUp(event: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  if (pressedOutside && isPointerOutside(event, dialog)) {
    dialog.close('close')
  }
  pressedOutside = false
}

watch(
  () => props.open,
  async (val) => {
    await nextTick()
    const dialog = dialogRef.value
    if (!dialog) return
    if (val && !dialog.open && typeof dialog.showModal === 'function') {
      dialog.showModal()
      searchInputRef.value?.focus()
    } else if (!val && dialog.open && typeof dialog.close === 'function') {
      dialog.close('close')
    }
  }
)

onMounted(() => {
  const dialog = dialogRef.value
  if (!dialog) return
  dialog.addEventListener('pointerdown', handlePointerDown)
  dialog.addEventListener('pointerup', handlePointerUp)
  if (props.open && !dialog.open && typeof dialog.showModal === 'function') {
    dialog.showModal()
    searchInputRef.value?.focus()
  }
})

onUnmounted(() => {
  const dialog = dialogRef.value
  if (!dialog) return
  dialog.removeEventListener('pointerdown', handlePointerDown)
  dialog.removeEventListener('pointerup', handlePointerUp)
})
</script>

<template>
  <dialog
    ref="dialogRef"
    class="command-palette-dialog"
    closedby="any"
    aria-labelledby="command-palette-title"
    @close="handleDialogClose"
  >
    <div class="palette-shell">
      <div class="palette-input-row">
        <span id="command-palette-title" class="sr-only">{{ t('palette.title') }}</span>
        <svg class="palette-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          ref="searchInputRef"
          v-model="query"
          type="search"
          class="palette-input"
          :placeholder="t('palette.placeholder')"
          :aria-label="t('palette.search_aria')"
          @keydown="handleInputKeydown"
        />
        <kbd class="esc-hint">ESC</kbd>
      </div>

      <div class="palette-list" role="listbox" :aria-label="t('palette.list_aria')">
        <div v-if="filteredCommands.length === 0" class="palette-empty">
          {{ t('palette.empty') }}
        </div>
        <button
          v-for="(cmd, idx) in filteredCommands"
          :key="cmd.id"
          type="button"
          class="palette-item"
          :class="{ active: idx === activeIndex }"
          @mouseenter="activeIndex = idx"
          @click="executeCommand(cmd)"
        >
          <span class="palette-item-label">{{ cmd.label }}</span>
          <span class="palette-item-group">{{ cmd.group }}</span>
        </button>
      </div>

      <footer class="palette-footer">
        <span>{{ t('palette.footer_nav') }}</span>
        <span>{{ t('palette.footer_enter') }}</span>
        <span>{{ t('palette.footer_shortcut') }}</span>
      </footer>
    </div>
  </dialog>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.command-palette-dialog {
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  color: var(--text-primary);
  width: min(580px, calc(100vw - 32px));
  max-height: 70vh;
  margin: 12vh auto auto;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.command-palette-dialog:modal {
  overscroll-behavior: contain;
}

.command-palette-dialog::backdrop {
  background: rgba(15, 23, 42, 0.42);
  overflow: hidden;
  overscroll-behavior: contain;
}

.palette-shell {
  display: flex;
  flex-direction: column;
  max-height: 70vh;
}

.palette-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.palette-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.palette-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 0.92rem;
  color: var(--text-primary);
  outline: none;
}

.esc-hint {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-muted);
  background: #f1f5f9;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 2px 6px;
}

.palette-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.palette-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 28px 0;
  font-size: 0.85rem;
}

.palette-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  font-size: 0.86rem;
}

.palette-item.active,
.palette-item:hover {
  background: #eff6ff;
  color: #1d4ed8;
}

.palette-item-label {
  font-weight: 500;
}

.palette-item-group {
  font-size: 0.72rem;
  color: var(--text-muted);
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.palette-footer {
  padding: 8px 16px;
  border-top: 1px solid var(--border-color);
  background: #f8fafc;
  display: flex;
  gap: 16px;
  font-size: 0.72rem;
  color: var(--text-muted);
}
</style>
