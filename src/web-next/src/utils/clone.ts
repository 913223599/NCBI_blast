import { toRaw } from 'vue'

/**
 * 递归剥离 Vue 响应式 Proxy 后执行原生 structuredClone，
 * 避免直接对 Vue reactive/ref 对象调用 structuredClone 抛出 DataCloneError。
 */
function deepToRaw<T>(value: T): T {
  const raw = toRaw(value)
  if (raw === null || typeof raw !== 'object') {
    return raw
  }
  if (Array.isArray(raw)) {
    return raw.map((item) => deepToRaw(item)) as unknown as T
  }
  if (raw instanceof Date || raw instanceof RegExp || raw instanceof Map || raw instanceof Set) {
    return raw
  }
  const plain: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v === 'function' || typeof v === 'symbol') continue
    plain[k] = deepToRaw(v)
  }
  return plain as T
}

export function safeDeepClone<T>(value: T): T {
  const unwrapped = deepToRaw(value)
  if (typeof structuredClone === 'function') {
    return structuredClone(unwrapped)
  }
  return JSON.parse(JSON.stringify(unwrapped))
}
