import { ref } from 'vue'

export interface ConfirmDialogOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

export interface PromptDialogOptions extends ConfirmDialogOptions {
  inputLabel?: string
  placeholder?: string
  initialValue?: string
}

interface PendingConfirmRequest extends ConfirmDialogOptions {
  mode: 'confirm'
  resolve: (confirmed: boolean) => void
}

interface PendingPromptRequest extends PromptDialogOptions {
  mode: 'prompt'
  resolve: (value: string | null) => void
}

type PendingDialogRequest = PendingConfirmRequest | PendingPromptRequest

const activeRequest = ref<PendingDialogRequest | null>(null)

function cancelPendingRequest(): void {
  const prev = activeRequest.value
  if (!prev) return
  if (prev.mode === 'prompt') {
    prev.resolve(null)
  } else {
    prev.resolve(false)
  }
}

export function useConfirmDialog() {
  function confirm(options: ConfirmDialogOptions): Promise<boolean> {
    return new Promise((resolve) => {
      cancelPendingRequest()
      activeRequest.value = {
        mode: 'confirm',
        confirmText: '确认',
        cancelText: '取消',
        danger: false,
        ...options,
        resolve,
      }
    })
  }

  function prompt(options: PromptDialogOptions): Promise<string | null> {
    return new Promise((resolve) => {
      cancelPendingRequest()
      activeRequest.value = {
        mode: 'prompt',
        confirmText: '确认',
        cancelText: '取消',
        danger: false,
        inputLabel: '请输入确认内容',
        placeholder: '',
        initialValue: '',
        ...options,
        resolve,
      }
    })
  }

  function settle(confirmed: boolean, inputValue = ''): void {
    const req = activeRequest.value
    activeRequest.value = null
    if (!req) return
    if (req.mode === 'prompt') {
      req.resolve(confirmed ? inputValue : null)
    } else {
      req.resolve(confirmed)
    }
  }

  return {
    activeRequest,
    confirm,
    prompt,
    settle,
  }
}
