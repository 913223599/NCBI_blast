/**
 * Electron Preload Bridge 全局强类型声明
 * 与 electron-shell/preload.js 暴露的 11 个 contextBridge 方法保持 1:1 精确对齐。
 */

export interface ElectronDialogFilter {
  name: string
  extensions: string[]
}

export interface ElectronOpenDialogOptions {
  title?: string
  defaultPath?: string
  filters?: ElectronDialogFilter[]
  properties?: string[]
}

export interface ElectronSaveDialogOptions {
  title?: string
  defaultPath?: string
  filters?: ElectronDialogFilter[]
}

export interface ElectronAPI {
  /** 获取拖拽文件的本地绝对路径（适配 Electron Context Isolation） */
  getPathForFile: (file: File) => string
  /** 打开原生文件选择对话框 */
  openFileDialog: (options?: ElectronOpenDialogOptions) => Promise<string[] | null>
  /** 打开原生文件保存对话框 */
  saveFileDialog: (options?: ElectronSaveDialogOptions) => Promise<string | null>
  /** 使用系统默认浏览器打开外部 URL（白名单校验） */
  openExternal: (url: string) => Promise<void>
  /** 使用系统资源管理器打开指定本地目录 */
  openPath: (dirPath: string) => Promise<void>
  /** 异步读取白名单文本文件 */
  readFile: (filePath: string) => Promise<string | null>
  /** 异步写入白名单 UTF-8 文本文件 */
  writeFile: (filePath: string, content: string) => Promise<boolean>
  /** 异步写入白名单 Base64 二进制文件 */
  writeBinaryFile: (filePath: string, base64Data: string) => Promise<boolean>
  /** 获取本地 Python FastAPI 服务端口 */
  getApiPort: () => Promise<number>
  /** 获取当前工作站项目根目录 */
  getProjectRoot: () => Promise<string>
  /** 安全重启 Electron 桌面宿主进程 */
  relaunchApp: () => Promise<boolean | void>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
    handleBridgeEvent?: (event: string, payload?: unknown) => void
    app?: {
      showNotification?: (message: string, type?: string) => void
    }
  }
}

export {}
