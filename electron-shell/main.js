/**
 * NCBI Bio-Station — Electron Main Process
 * 
 * 职责：
 * 1. 管理 BrowserWindow 生命周期
 * 2. 启动/监控/停止 Python Sidecar (FastAPI)
 * 3. 提供 IPC 端点：文件对话框、外部链接、系统集成
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

// ─── 屏蔽 Chromium 内部噪音 ──────────────────────────
app.commandLine.appendSwitch('disable-features', 'AutofillServerCommunication,AutofillEnableAccountWalletStorage');
app.commandLine.appendSwitch('log-level', '3');
app.commandLine.appendSwitch('remote-debugging-pipe');

// ─── 配置常量 ─────────────────────────────────────
const PROJECT_ROOT = path.resolve(__dirname, '..');
const PYTHON_EXE = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
const API_SERVER_SCRIPT = path.join(PROJECT_ROOT, 'src', 'backend', 'api_server.py');
const API_PORT = 8765;
const VITE_PORT = 5173;
const IS_DEV = process.argv.includes('--dev');

// ─── 状态变量 ─────────────────────────────────────
let pythonProcess = null;
let mainWindow = null;

// ─── Python Sidecar 管理 ──────────────────────────

function startPythonSidecar() {
    console.log('[Electron] 启动 Python Sidecar...');
    console.log(`[Electron] Python: ${PYTHON_EXE}`);
    console.log(`[Electron] Script: ${API_SERVER_SCRIPT}`);

    const proc = spawn(PYTHON_EXE, ['-m', 'src.backend.api_server'], {
        cwd: PROJECT_ROOT,
        env: {
            ...process.env,
            PYTHONPATH: PROJECT_ROOT,
            PYTHONIOENCODING: 'utf-8',
            PYTHONLEGACYWINDOWSSTDIO: 'utf-8',
            PATH: process.env.PATH
        },
        stdio: ['pipe', 'pipe', 'pipe']
    });

    proc.stdout.on('data', (data) => {
        const msg = data.toString().trim();
        if (msg) console.log(`[Python] ${msg}`);
    });

    proc.stderr.on('data', (data) => {
        const msg = data.toString().trim();
        if (msg) console.log(`[Python:ERR] ${msg}`);
    });

    proc.on('exit', (code) => {
        console.log(`[Electron] Python Sidecar 退出，退出码: ${code}`);
        pythonProcess = null;
    });

    proc.on('error', (err) => {
        console.error(`[Electron] Python Sidecar 启动失败:`, err);
    });

    return proc;
}

function waitForPythonReady(maxRetries = 60, intervalMs = 500) {
    return new Promise((resolve) => {
        let attempt = 0;
        let isResolved = false;

        const check = () => {
            if (isResolved) return;
            attempt++;
            const request = http.get(`http://127.0.0.1:${API_PORT}/docs`, (res) => {
                if (res.statusCode === 200) {
                    if (!isResolved) {
                        isResolved = true;
                        console.log(`[Electron] Python API 已就绪 (${attempt} 次尝试)`);
                        resolve(true);
                    }
                } else {
                    res.resume();
                    retry(`HTTP ${res.statusCode}`);
                }
            });

            request.on('error', (err) => retry(err.message));
            request.setTimeout(1000, () => {
                request.destroy();
                retry('Timeout (1s)');
            });
        };

        const retry = (reason) => {
            if (isResolved) return;
            if (attempt >= maxRetries) {
                isResolved = true;
                console.error(`[Electron] Python API 启动超时 (${maxRetries} 次尝试)。原因: ${reason}`);
                resolve(false);
            } else {
                if (attempt % 10 === 0) {
                    console.log(`[Electron] 正在等待 Python API... (${attempt}/${maxRetries}) - 上次原因: ${reason}`);
                }
                setTimeout(check, intervalMs);
            }
        };

        check();
    });
}

function stopPythonSidecar() {
    if (pythonProcess) {
        console.log('[Electron] 正在响应生命周期事件，停止 Python Sidecar...');
        pythonProcess.kill('SIGTERM');
        setTimeout(() => {
            if (pythonProcess && !pythonProcess.killed) {
                pythonProcess.kill('SIGKILL');
            }
        }, 3000);
    }
}

// ─── 窗口管理 ─────────────────────────────────────

function createWindow() {
    try {
        console.log('[Electron] 正在创建主窗口...');
        mainWindow = new BrowserWindow({
            width: 1440,
            height: 920,
            minWidth: 1240,
            minHeight: 800,
            title: 'NCBI BLAST 专业版 | 工作台',
            backgroundColor: '#0f172a',
            show: false,
            webPreferences: {
                preload: path.join(__dirname, 'preload.js'),
                contextIsolation: true,
                nodeIntegration: false,
                backgroundThrottling: false,
            }
        });

        const frontendUrl = IS_DEV
            ? `http://localhost:${VITE_PORT}`
            : `file://${path.join(PROJECT_ROOT, 'src', 'web-next', 'dist', 'index.html')}`;

        console.log(`[Electron] 加载前端: ${frontendUrl}`);
        mainWindow.loadURL(frontendUrl).catch(err => {
            console.error(`[Electron] 加载前端 URL 失败: ${err.message}`);
        });

        mainWindow.once('ready-to-show', () => {
            mainWindow.show();
            console.log('[Electron] 窗口已显示');
            
            // 只有在窗口显示后，才监听全关事件，防止启动时的意外触发
            app.on('window-all-closed', () => {
                console.log('[Electron] window-all-closed 事件触发');
                if (process.platform !== 'darwin') {
                    stopPythonSidecar();
                    app.quit();
                }
            });
        });

        if (IS_DEV) {
            mainWindow.webContents.openDevTools({ mode: 'detach' });
        }

        mainWindow.on('closed', () => {
            console.log('[Electron] 主窗口已关闭');
            mainWindow = null;
        });
    } catch (err) {
        console.error('[Electron] 创建窗口失败:', err);
    }
}

// ─── IPC 处理器 ──────────────────────────────────

ipcMain.handle('dialog:openFile', async (_event, options) => {
    const result = await dialog.showOpenDialog(mainWindow, {
        title: options.title || '打开文件',
        filters: options.filters || [{ name: 'All Files', extensions: ['*'] }],
        properties: options.properties || ['openFile']
    });
    return result.canceled ? null : result.filePaths;
});

ipcMain.handle('dialog:saveFile', async (_event, options) => {
    const result = await dialog.showSaveDialog(mainWindow, {
        title: options.title || '保存文件',
        defaultPath: options.defaultPath || '',
        filters: options.filters || [{ name: 'All Files', extensions: ['*'] }]
    });
    return result.canceled ? null : result.filePath;
});

ipcMain.handle('shell:openExternal', async (_event, url) => shell.openExternal(url));
ipcMain.handle('shell:openPath', async (_event, dirPath) => shell.openPath(dirPath));

ipcMain.handle('fs:readFile', async (_event, filePath) => {
    const fs = require('fs');
    try { return fs.readFileSync(filePath, 'utf-8'); } catch { return null; }
});

ipcMain.handle('fs:writeFile', async (_event, filePath, content) => {
    const fs = require('fs');
    try { fs.writeFileSync(filePath, content, 'utf-8'); return true; } catch { return false; }
});

ipcMain.handle('app:getApiPort', () => API_PORT);
ipcMain.handle('app:getProjectRoot', () => PROJECT_ROOT);

// ─── 应用生命周期 ─────────────────────────────────

app.whenReady().then(async () => {
    try {
        console.log('=======================================');
        console.log('  NCBI BLAST Pro — Electron Shell');
        console.log('=======================================');

        pythonProcess = startPythonSidecar();

        const pythonReady = await waitForPythonReady();
        if (!pythonReady) {
            console.error('[Electron] 无法启动 Python API 服务器，退出。');
            app.quit();
            return;
        }

        createWindow();
    } catch (err) {
        console.error('[Electron] 启动过程发生未捕获异常:', err);
        app.quit();
    }
});

app.on('before-quit', (event) => {
    if (mainWindow === null) {
        console.log('[Electron] 拦截到一个过早的 before-quit 信号');
        event.preventDefault();
        return;
    }
    console.log('[Electron] before-quit 事件触发');
    stopPythonSidecar();
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});
