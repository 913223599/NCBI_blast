// -*- coding: utf-8 -*-
/**
 * 统一文件下载与保存服务
 * 
 * 核心特性：
 * 1. 自动根据协议与环境拼接 API_BASE（兼容 Electron file:// 协议与 Vite 开发代理与局域网访问）；
 * 2. 前置状态码检测，捕获 404/500 等异常并抛出结构化错误，严禁把错误 JSON 保存为假文件；
 * 3. 智能解析 Content-Disposition 响应头以获取服务端推荐文件名；
 * 4. 双模原生存储：
 *    - Electron 环境：唤起系统原生 SaveFileDialog 对话框，用户可自选路径与文件名，支持无损二进制与文本写入；
 *    - Web 浏览器环境：采用 Blob + ObjectURL + <a> 自动触发下载并延时销毁。
 */

import { API_BASE } from '../bridge/electron-bridge';

export interface DownloadResult {
  success: boolean;
  cancelled?: boolean;
  savedPath?: string;
  error?: string;
}

/**
 * 将相对路径或绝对路径规范化为完整网络请求 URL
 */
export function resolveApiUrl(rawUrl: string): string {
  if (!rawUrl) return '';
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://') || rawUrl.startsWith('blob:') || rawUrl.startsWith('data:')) {
    return rawUrl;
  }
  const base = API_BASE ? API_BASE.replace(/\/+$/, '') : 'http://127.0.0.1:8765';
  const path = rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`;
  return `${base}${path}`;
}

/**
 * 从 Content-Disposition 响应头提取文件名
 */
export function extractFilenameFromHeader(dispositionHeader: string | null): string | null {
  if (!dispositionHeader) return null;
  
  // 匹配 filename*=UTF-8''... 规范
  const utf8Match = dispositionHeader.match(/filename\*=(?:UTF-8|utf-8)''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }

  // 匹配 filename="..." 或 filename=...
  const standardMatch = dispositionHeader.match(/filename=["']?([^"';]+)["']?/i);
  if (standardMatch && standardMatch[1]) {
    return standardMatch[1].trim();
  }

  return null;
}

/**
 * 将 Blob 转换为 Base64 编码字符串
 */
export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const res = (reader.result as string) || '';
      const base64 = res.includes(',') ? (res.split(',')[1] || '') : res;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * 核心：将 Blob 保存到本地（支持 Electron 原生另存为与浏览器下载）
 */
export async function downloadFileFromBlob(
  blob: Blob,
  defaultFilename: string
): Promise<DownloadResult> {
  const electron = typeof window !== 'undefined' ? window.electronAPI : undefined;

  // 1. Electron 桌面端原生另存为模式
  if (electron && typeof electron.saveFileDialog === 'function') {
    try {
      const chosenPath = await electron.saveFileDialog({
        title: '保存文件',
        defaultPath: defaultFilename
      });

      if (!chosenPath) {
        return { success: false, cancelled: true };
      }

      let saveSuccess = false;
      if (typeof electron.writeBinaryFile === 'function') {
        const base64Data = await blobToBase64(blob);
        saveSuccess = await electron.writeBinaryFile(chosenPath, base64Data);
      } else if (typeof electron.writeFile === 'function') {
        const textContent = await blob.text();
        saveSuccess = await electron.writeFile(chosenPath, textContent);
      }

      if (saveSuccess) {
        return { success: true, savedPath: chosenPath };
      } else {
        return { success: false, error: '写入本地文件失败，请检查磁盘权限' };
      }
    } catch (e: any) {
      console.error('[FileDownloader] Electron 原生保存异常:', e);
      return { success: false, error: e?.message || String(e) };
    }
  }

  // 2. 浏览器标准 Blob 下载模式
  try {
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = defaultFilename || 'downloaded_file';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // 延迟 60 秒回收，防止大文件异步下载未完成就被取消
    setTimeout(() => {
      try {
        URL.revokeObjectURL(blobUrl);
      } catch {}
    }, 60000);

    return { success: true };
  } catch (err: any) {
    console.error('[FileDownloader] 浏览器 Blob 下载异常:', err);
    return { success: false, error: err?.message || String(err) };
  }
}

/**
 * 从指定服务端 URL 获取文件并执行可靠下载
 */
export async function downloadFileFromUrl(
  rawUrl: string,
  defaultFilename?: string
): Promise<DownloadResult> {
  const fullUrl = resolveApiUrl(rawUrl);

  try {
    const response = await fetch(fullUrl, {
      method: 'GET'
    });

    if (!response.ok) {
      let errorDetail = `HTTP ${response.status}`;
      try {
        const errJson = await response.json();
        if (errJson && errJson.detail) {
          errorDetail = errJson.detail;
        } else if (errJson && errJson.message) {
          errorDetail = errJson.message;
        }
      } catch {
        const text = await response.text().catch(() => '');
        if (text) errorDetail = text.slice(0, 150);
      }
      return {
        success: false,
        error: `服务器响应异常: ${errorDetail}`
      };
    }

    // 解析有效文件名
    const headerName = extractFilenameFromHeader(response.headers.get('content-disposition'));
    const finalFilename = headerName || defaultFilename || rawUrl.split('/').pop()?.split('?')[0] || 'downloaded_file';

    const blob = await response.blob();
    return await downloadFileFromBlob(blob, finalFilename);
  } catch (err: any) {
    console.error(`[FileDownloader] 下载网络请求失败 [${fullUrl}]:`, err);
    return {
      success: false,
      error: `无法连接服务器进行下载: ${err?.message || String(err)}`
    };
  }
}

/**
 * 将纯文本或代码直接导出为文件
 */
export async function downloadFileFromText(
  textContent: string,
  defaultFilename: string,
  mimeType: string = 'text/plain;charset=utf-8'
): Promise<DownloadResult> {
  const blob = new Blob([textContent], { type: mimeType });
  return await downloadFileFromBlob(blob, defaultFilename);
}
