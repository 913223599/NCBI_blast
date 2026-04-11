import { useAppStore } from '../stores/app'

export function useI18n() {
  const appStore = useAppStore()
  
  const t = (key: string, params?: Record<string, any>): string => {
    // 1. Check if backend-injected JSON translation exists
    let text = (appStore.translations && appStore.translations[key]) || key
    
    // 2. Handle simple {variable} interpolation
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, String(v))
      })
    }
    
    return text
  }

  return { t }
}
