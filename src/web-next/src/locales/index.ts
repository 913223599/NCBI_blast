import { useAppStore } from '../stores/app'

export function useI18n() {
  const appStore = useAppStore()
  
  const t = (key: string): string => {
    // 1. Check if backend-injected JSON translation exists
    if (appStore.translations && appStore.translations[key]) {
      return appStore.translations[key]
    }
    
    // 2. Fallback to key itself if not found
    return key
  }

  return { t }
}
