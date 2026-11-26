/**
 * 全局国际化模块（强类型静态双语兜底 + 后端自定义热覆盖）
 * - 直接从 src/resources/locales/{zh_CN,en_US}/*.json 静态汇总，保证单一事实源、首屏零闪烁、离线可用
 * - 当后端下发同语言自定义词典时优先使用后端热覆盖，并兼容 `{key}` 与 `${key}` 两种模板占位符
 */
import { getActivePinia } from 'pinia'
import { useAppStore } from '../stores/app'
import type { LocaleKey, TranslationKey } from './localeTypes'

export type { LocaleKey, TranslationKey }
export type AppLocale = 'zh_CN' | 'en_US'

type JsonModule = { default?: Record<string, string> } | Record<string, string>

const zhModules = import.meta.glob<JsonModule>('../../../resources/locales/zh_CN/*.json', { eager: true })
const enModules = import.meta.glob<JsonModule>('../../../resources/locales/en_US/*.json', { eager: true })

function mergeLocaleModules(modules: Record<string, JsonModule>): Record<string, string> {
  const merged: Record<string, string> = {}
  for (const mod of Object.values(modules)) {
    const record =
      mod && typeof mod === 'object' && 'default' in mod && mod.default && typeof mod.default === 'object'
        ? (mod.default as Record<string, string>)
        : (mod as Record<string, string>)
    if (!record || typeof record !== 'object') continue
    for (const [k, v] of Object.entries(record)) {
      if (typeof v === 'string') {
        merged[k] = v
      }
    }
  }
  return merged
}

export const STATIC_LOCALES: Record<AppLocale, Record<string, string>> = {
  zh_CN: mergeLocaleModules(zhModules),
  en_US: mergeLocaleModules(enModules),
}

export function isKnownLocaleKey(key: string): key is LocaleKey {
  return Object.prototype.hasOwnProperty.call(STATIC_LOCALES.zh_CN, key)
}

export function translateKey(
  key: TranslationKey,
  locale: AppLocale = 'zh_CN',
  overrides?: Record<string, string> | null,
  params?: Record<string, unknown>
): string {
  const staticPack = STATIC_LOCALES[locale] ?? STATIC_LOCALES.zh_CN
  let text =
    (overrides && typeof overrides[key] === 'string' && overrides[key]) ||
    staticPack[key] ||
    STATIC_LOCALES.zh_CN[key] ||
    key

  if (params) {
    for (const [paramKey, paramVal] of Object.entries(params)) {
      const valueStr = String(paramVal)
      text = text.replaceAll(`{${paramKey}}`, valueStr).replaceAll(`\${${paramKey}}`, valueStr)
    }
  }

  return text
}

export function useI18n() {
  const activePinia = getActivePinia()
  const appStore = activePinia ? useAppStore(activePinia) : null

  const t = (key: TranslationKey, params?: Record<string, unknown>): string => {
    const activeLocale: AppLocale = appStore?.locale === 'en_US' ? 'en_US' : 'zh_CN'
    // 仅当后端下发的翻译包属于当前激活语种时才作为热覆盖，防止切语言后旧语种残留覆盖静态包
    const activeOverrides =
      appStore && appStore.translationsLocale === activeLocale ? appStore.translations : null
    return translateKey(key, activeLocale, activeOverrides, params)
  }

  return { t }
}
