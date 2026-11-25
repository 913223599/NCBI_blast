<script setup lang="ts">
/**
 * AppConfirmDialog - 基于原生 <dialog> 的全局异步确认/输入弹窗
 * 遵循 Modern Web Guidance `dialog` 与 `ime-safe-enter-submit` 规范：
 * - 使用原生 showModal() 获取 inert、top-layer、焦点管理与 Esc 关闭，不附加冗余 role/aria-modal
 * - 危险操作将 autofocus 置于安全“取消”按钮；输入模式使用带 <label> 的输入框并拦截 IME 候选态 Enter
 * - 在 close 事件中读取并重置 dialog.returnValue = '' 防止陈旧返回值泄漏
 * - 为不支持 closedby 的浏览器补充 pointerdown+pointerup 坐标边界回退
 */
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useConfirmDialog } from '../../composables/useConfirmDialog'
import { shouldSubmitOnEnter } from '../../utils/ime'
import { useI18n } from '../../locales'

const { t } = useI18n()
const { activeRequest, settle } = useConfirmDialog()
const dialogRef = ref<HTMLDialogElement | null>(null)
const promptInput = ref('')
let pressedOutside = false

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
    dialog.close('cancel')
  }
  pressedOutside = false
}

function onPromptKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter') return
  if (!shouldSubmitOnEnter(event)) {
    event.preventDefault()
    return
  }
  event.preventDefault()
  dialogRef.value?.close('confirm')
}

function handleDialogClose(): void {
  const dialog = dialogRef.value
  const val = dialog?.returnValue ?? ''
  if (dialog) {
    dialog.returnValue = ''
  }
  const currentInput = promptInput.value
  promptInput.value = ''
  settle(val === 'confirm', currentInput)
}

watch(activeRequest, async (req) => {
  if (req && req.mode === 'prompt') {
    promptInput.value = req.initialValue ?? ''
  } else {
    promptInput.value = ''
  }
  await nextTick()
  const dialog = dialogRef.value
  if (!dialog) return
  if (req) {
    if (!dialog.open && typeof dialog.showModal === 'function') {
      dialog.showModal()
    }
  } else if (dialog.open) {
    dialog.close('cancel')
  }
})

onMounted(() => {
  const dialog = dialogRef.value
  if (!dialog) return
  dialog.addEventListener('pointerdown', handlePointerDown)
  dialog.addEventListener('pointerup', handlePointerUp)
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
    class="app-confirm-dialog"
    closedby="any"
    aria-labelledby="app-confirm-title"
    aria-describedby="app-confirm-desc"
    @close="handleDialogClose"
  >
    <div v-if="activeRequest" class="dialog-inner">
      <h1 id="app-confirm-title" class="dialog-title">{{ activeRequest.title }}</h1>
      <p id="app-confirm-desc" class="dialog-message">{{ activeRequest.message }}</p>
      <form method="dialog" class="dialog-form">
        <div v-if="activeRequest.mode === 'prompt'" class="dialog-input-group">
          <label for="app-confirm-prompt-input" class="dialog-input-label">
            {{ activeRequest.inputLabel || t('common.prompt_default_label') }}
          </label>
          <input
            id="app-confirm-prompt-input"
            v-model="promptInput"
            type="text"
            class="dialog-prompt-input"
            :placeholder="activeRequest.placeholder"
            autocomplete="off"
            autofocus
            @keydown="onPromptKeydown"
          />
        </div>
        <div class="dialog-actions">
          <button
            type="submit"
            value="cancel"
            class="btn-cancel"
            :autofocus="activeRequest.mode === 'confirm' && Boolean(activeRequest.danger)"
          >
            {{ activeRequest.cancelText }}
          </button>
          <button
            type="submit"
            value="confirm"
            class="btn-confirm"
            :class="{ danger: activeRequest.danger }"
            :autofocus="activeRequest.mode === 'confirm' && !activeRequest.danger"
          >
            {{ activeRequest.confirmText }}
          </button>
        </div>
      </form>
    </div>
  </dialog>
</template>

<style scoped>
.app-confirm-dialog {
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  color: var(--text-primary);
  max-width: 440px;
  width: calc(100vw - 32px);
  margin: auto;
  box-shadow: var(--shadow-lg);
}

.app-confirm-dialog:modal {
  overscroll-behavior: contain;
}

.app-confirm-dialog::backdrop {
  background: rgba(15, 23, 42, 0.45);
  overflow: hidden;
  overscroll-behavior: contain;
}

.dialog-inner {
  padding: 22px 24px 20px;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.dialog-message {
  font-size: 0.9rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
  white-space: pre-line;
}

.dialog-input-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 18px;
}

.dialog-input-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.dialog-prompt-input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  color: var(--text-primary);
  background: #ffffff;
}

.dialog-prompt-input:focus {
  border-color: var(--accent-blue);
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn-cancel,
.btn-confirm {
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-cancel {
  background: #f1f5f9;
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-cancel:hover {
  background: #e2e8f0;
}

.btn-confirm {
  background: var(--accent-blue);
  color: #ffffff;
}

.btn-confirm:hover {
  background: #2563eb;
}

.btn-confirm.danger {
  background: var(--error-color);
}

.btn-confirm.danger:hover {
  background: #dc2626;
}
</style>
