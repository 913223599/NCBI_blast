/**
 * NCBI Bio-Station — Electron Preload Script
 * 
 * 安全地将 Electron IPC 功能暴露给渲染进程（Vue 前端）。
 * 遵循 Context Isolation 最佳实践：
 * - ✅ 通过 contextBridge 暴露白名单 API
 * - ❌ 不暴露 Node.js 或 Electron 原始模块
 */

const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    /** 获取拖拽文件的真实路径 (解决 Context Isolation 限制) */
    getPathForFile: (file) => webUtils.getPathForFile(file),

    // ─── 文件对话框 ──────────────────────────────
    /** 
     * 打开文件对话框
     * @param {Object} options - {title, filters, properties}
     * @returns {Promise<string[]|null>}
     */
    openFileDialog: (options) => ipcRenderer.invoke('dialog:openFile', options),

    /** 
     * 保存文件对话框
     * @param {Object} options - {title, defaultPath, filters}  
     * @returns {Promise<string|null>}
     */
    saveFileDialog: (options) => ipcRenderer.invoke('dialog:saveFile', options),

    // ─── Shell 操作 ──────────────────────────────
    /** 打开外部 URL */
    openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),

    /** 打开文件夹 */
    openPath: (dirPath) => ipcRenderer.invoke('shell:openPath', dirPath),

    // ─── 文件系统 ────────────────────────────────
    /** 读取文件内容 */
    readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),

    /** 写入文件 */
    writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),

    // ─── 应用信息 ────────────────────────────────
    /** 获取 Python API 端口号 */
    getApiPort: () => ipcRenderer.invoke('app:getApiPort'),

    /** 获取项目根路径 */
    getProjectRoot: () => ipcRenderer.invoke('app:getProjectRoot'),
});
