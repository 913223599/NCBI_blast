import { useAppStore } from '../stores/app'

const FALLBACK_TRANSLATIONS: Record<string, Record<string, string>> = {
  zh_CN: {
    'dash.quick': '快速开始',
    'dash.sys': '工作站实时概览',
    'blast.nav.input': '序列输入',
    'blast.nav.params': '比对参数',
    'blast.nav.history': '任务历史',
    'blast.btn.run': '执行比对',
    'blast.input.text_placeholder': '请粘贴 FASTA 格式序列（支持单条或多条 >header 序列）...',
  },
  en_US: {
    'dash.quick': 'Quick Start',
    'dash.sys': 'Workstation Overview',
    'blast.nav.input': 'Input',
    'blast.nav.params': 'Parameters',
    'blast.nav.history': 'History',
    'blast.btn.run': 'Run BLAST',
    'blast.input.text_placeholder': 'Paste FASTA sequences here (single or multi-FASTA supported)...',
  },
}

export function useI18n() {
  const appStore = useAppStore()

  const t = (key: string, params?: Record<string, unknown>): string => {
    const localePack = FALLBACK_TRANSLATIONS[appStore.locale] ?? FALLBACK_TRANSLATIONS.zh_CN
    let text =
      (appStore.translations && appStore.translations[key]) ||
      (localePack && localePack[key]) ||
      key

    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, String(v))
      })
    }

    return text
  }

  return { t }
}
