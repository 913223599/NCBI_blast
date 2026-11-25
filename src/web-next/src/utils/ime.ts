/**
 * 中文/日韩输入法 (IME) 安全 Enter 判断工具
 * 遵循 Modern Web Guidance `ime-safe-enter-submit`：
 * 同时检测 `event.isComposing` 与 `event.keyCode === 229`，兼容 Safari compositionend 乱序缺陷。
 */
export function isImeComposingKey(event: KeyboardEvent): boolean {
  return Boolean(event.isComposing || event.keyCode === 229)
}

export function shouldSubmitOnEnter(
  event: KeyboardEvent,
  options: { allowShiftNewline?: boolean } = {}
): boolean {
  if (event.key !== 'Enter') return false
  if (options.allowShiftNewline && event.shiftKey) return false
  if (isImeComposingKey(event)) return false
  return true
}
