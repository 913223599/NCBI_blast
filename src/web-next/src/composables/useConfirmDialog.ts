import { ref } from 'vue'
import { useI18n } from '../locales'

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
  const { t } = useI18n()

  function confirm(options: ConfirmDialogOptions): Promise<boolean> {
    return new Promise((resolve) => {
      cancelPendingRequest()
      activeRequest.value = {
        mode: 'confirm',
        confirmText: t('common.confirm'),
        cancelText: t('common.cancel'),
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
        confirmText: t('common.confirm'),
        cancelText: t('common.cancel'),
        danger: false,
        inputLabel: t('common.prompt_default_label'),
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
