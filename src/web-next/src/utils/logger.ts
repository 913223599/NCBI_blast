/**
 * 前端受控日志工具 (Logger)
 * - 开发环境（import.meta.env.DEV）完整输出 debug/info/warn/error；
 * - 生产构建自动静默低级别 debug/info 控制台噪音，仅保留 warn 与 error 便于故障定位。
 */

const isDev = Boolean(import.meta.env?.DEV)

export function createLogger(scope: string) {
  const prefix = `[${scope}]`
  return {
    debug(...args: unknown[]): void {
      if (isDev) console.debug(prefix, ...args)
    },
    info(...args: unknown[]): void {
      if (isDev) console.info(prefix, ...args)
    },
    warn(...args: unknown[]): void {
      console.warn(prefix, ...args)
    },
    error(...args: unknown[]): void {
      console.error(prefix, ...args)
    },
  }
}

export const appLogger = createLogger('BioStation')
