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
const fs = require('fs');

// ─── 启动日志落盘 (electron-shell/dev.log) ─────────────
// Windows 下 electron.exe 是 GUI 子系统进程，快速退出或崩溃时控制台输出容易丢失，
// 因此主进程日志同时写入文件，便于事后定位“闪一下就没了”的问题。
const LOG_FILE = path.join(__dirname, 'dev.log');
const LOG_MAX_BYTES = 2 * 1024 * 1024;

function rotateLogIfNeeded() {
    try {
        if (fs.existsSync(LOG_FILE) && fs.statSync(LOG_FILE).size > LOG_MAX_BYTES) {
            fs.renameSync(LOG_FILE, `${LOG_FILE}.old`);
        }
    } catch (e) {
        // 忽略日志轮转失败
    }
}

function writeLogLine(level, args) {
    const text = args.map((arg) => {
        if (typeof arg === 'string') return arg;
        if (arg instanceof Error) return arg.stack || arg.message;
        try { return JSON.stringify(arg); } catch (e) { return String(arg); }
    }).join(' ');
    try {
        fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] [${level}] ${text}\r\n`);
    } catch (e) {
        // 忽略日志写入失败
    }
}

rotateLogIfNeeded();
for (const [level, method] of [['INFO', 'log'], ['WARN', 'warn'], ['ERROR', 'error']]) {
    const original = console[method].bind(console);
    console[method] = (...args) => {
        original(...args);
        writeLogLine(level, args);
    };
}

console.log('=======================================');
console.log('  NCBI BLAST Pro — Electron Shell');
console.log(`  启动于 ${new Date().toLocaleString()}`);
console.log('=======================================');

// ─── 环境自检：ELECTRON_RUN_AS_NODE 会让 electron.exe 退化为纯 Node ───
// 该变量被上层宿主进程注入时，app 为 undefined，此处会立刻抛错并静默退出。
if (!app || typeof app.whenReady !== 'function') {
    console.error('[Electron] 当前进程不具备 Electron 主进程 API (app 未定义)。');
    console.error('[Electron] 常见原因: 环境变量 ELECTRON_RUN_AS_NODE=1 使 electron.exe 以纯 Node 模式运行。');
    console.error('[Electron] 处理办法: 清除该环境变量后重启 (RUN_DEV_ELECTRON.bat 会自动清理)。');
    process.exit(1);
}

// ─── 屏蔽 Chromium 内部噪音 ──────────────────────────
app.commandLine.appendSwitch('disable-features', 'AutofillServerCommunication,AutofillEnableAccountWalletStorage');
app.commandLine.appendSwitch('log-level', '3');
// 注意: 不要启用 'remote-debugging-pipe'。该开关要求由外部控制端提供 fd3/fd4 管道，
// 独立运行时会干扰调试端点初始化 (见 electron/electron#27287)，仅自动化测试时才需要。

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

function killPortProcess(port) {
    if (process.platform === 'win32') {
        try {
            const { execSync } = require('child_process');
            const cmd = `powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"`;
            const out = execSync(cmd).toString().trim();
            if (out) {
                const pids = [...new Set(out.split(/\r?\n/).map(p => p.trim()).filter(Boolean))];
                for (const pid of pids) {
                    if (pid && pid !== '0' && pid !== String(process.pid)) {
                        console.log(`[Electron] 检测到残留孤儿进程 PID ${pid} 占用端口 ${port}，正在执行端口清理自愈...`);
                        try {
                            execSync(`taskkill /F /PID ${pid}`, { stdio: 'ignore' });
                            console.log(`[Electron] 成功释放端口 ${port} (已终止进程 PID ${pid})`);
                        } catch (e) {
                            // 忽略单个杀进程失败
                        }
                    }
                }
            }
        } catch (e) {
            console.warn('[Electron] 检查端口占用提示:', e.message);
        }
    }
}

function startPythonSidecar() {
    killPortProcess(API_PORT);
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
        
        // 强力物理关断：如果存在运行中的 WSL，动态检测并关闭运行中的发行版
        // 注意：这能解决 Python 未能安全退出导致 WSL 挂起的问题
        try {
            const { execSync } = require('child_process');
            const rawDistros = execSync('wsl --list --running --quiet', { stdio: ['ignore', 'pipe', 'ignore'] }).toString('utf16le');
            const runningDistros = rawDistros.split(/\r?\n/).map(s => s.replace(/\0/g, '').trim()).filter(Boolean);
            for (const distro of runningDistros) {
                console.log(`[Electron] 正在强制清理 WSL (${distro}) 分发版...`);
                execSync(`wsl --terminate "${distro}"`, { stdio: 'ignore' });
            }
        } catch (e) {
            // 忽略错误（说明可能已经关闭）
        }

        setTimeout(() => {
            if (pythonProcess && !pythonProcess.killed) {
                pythonProcess.kill('SIGKILL');
            }
        }, 1500);
    }
}

// ─── 窗口管理 ─────────────────────────────────────

function createWindow() {
    try {
        console.log('[Electron] 正在创建主窗口...');
        mainWindow = new BrowserWindow({
            width: 1280,
            height: 800,
            minWidth: 1024,
            minHeight: 720,
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

        // 开发模式下先自检 Vite 是否可达，避免窗口白屏却没有任何日志线索
        if (IS_DEV) {
            const probe = http.get(`http://localhost:${VITE_PORT}`, (res) => {
                console.log(`[Electron] Vite 探测成功 (HTTP ${res.statusCode}) - ${frontendUrl}`);
                res.resume();
            });
            probe.on('error', (err) => {
                console.error(`[Electron] Vite 探测失败 (${frontendUrl}): ${err.message}`);
                console.error('[Electron] 若前端端口不是 5173，说明 Vite 被旧进程占用后发生了端口漂移。');
            });
            probe.setTimeout(3000, () => {
                probe.destroy();
                console.error(`[Electron] Vite 探测超时 (${frontendUrl})`);
            });
        }

        console.log(`[Electron] 加载前端: ${frontendUrl}`);
        mainWindow.loadURL(frontendUrl).catch(err => {
            console.error(`[Electron] 加载前端 URL 失败: ${err.message}`);
        });

        // 前端加载失败时明确记录，避免只看到一片空白窗口而无任何线索
        mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
            console.error(`[Electron] 前端加载失败 (${errorCode} ${errorDescription}): ${validatedURL}`);
        });

        // 拦截所有新窗口创建请求（例如 window.open），防止出现白屏空白子窗口
        mainWindow.webContents.setWindowOpenHandler(({ url }) => {
            if (url.startsWith('http:') || url.startsWith('https:')) {
                shell.openExternal(url);
            }
            return { action: 'deny' };
        });

        // 监听下载事件（兜底保障）
        mainWindow.webContents.session.on('will-download', (_event, item, _webContents) => {
            console.log(`[Electron] 触发原生下载: ${item.getFilename()} (${item.getURL()})`);
            item.once('done', (_e, state) => {
                if (state === 'completed') {
                    console.log(`[Electron] 下载成功: ${item.getSavePath()}`);
                } else {
                    console.warn(`[Electron] 下载未完成状态: ${state}`);
                }
            });
        });

        mainWindow.once('ready-to-show', () => {
            mainWindow.show();
            console.log('[Electron] 窗口已显示');
        });

        // 兜底：页面加载异常时 ready-to-show 可能永不触发，窗口将一直隐藏，
        // 表现就是“双击后什么都没发生”。这里强制显示，让问题可见。
        setTimeout(() => {
            if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
                console.warn('[Electron] ready-to-show 未在 8 秒内触发，强制显示窗口。请检查上方前端加载日志。');
                mainWindow.show();
            }
        }, 8000);

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

ipcMain.handle('fs:writeBinaryFile', async (_event, filePath, base64Data) => {
    const fs = require('fs');
    try {
        const buffer = Buffer.from(base64Data, 'base64');
        fs.writeFileSync(filePath, buffer);
        return true;
    } catch (err) {
        console.error('[Electron] 写入二进制文件失败:', err);
        return false;
    }
});

ipcMain.handle('app:getApiPort', () => API_PORT);
ipcMain.handle('app:getProjectRoot', () => PROJECT_ROOT);

ipcMain.handle('app:relaunch', async () => {
    console.log('[Electron] 收到应用重启请求，正在切断 Sidecar 并重启...');
    try {
        stopPythonSidecar();
    } catch (err) {
        console.error('[Electron] 停止 Python Sidecar 异常:', err);
    }
    app.relaunch();
    app.exit(0);
    return true;
});

// ─── 应用生命周期 ─────────────────────────────────

app.whenReady().then(async () => {
    try {
        console.log(`[Electron] 运行模式: ${IS_DEV ? '开发 (dev)' : '生产'}`);

        pythonProcess = startPythonSidecar();

        const pythonReady = await waitForPythonReady();
        if (!pythonReady) {
            console.error('[Electron] 无法启动 Python API 服务器，退出。');
            try {
                dialog.showErrorBox(
                    '后端服务启动失败',
                    `Python API 服务器未能在 30 秒内就绪。\n\n请检查 electron-shell\\dev.log 与终端输出中的 [Python:ERR] 行。`
                );
            } catch (e) {
                // 忽略对话框失败
            }
            stopPythonSidecar();
            app.exit(1);
            return;
        }

        createWindow();
    } catch (err) {
        console.error('[Electron] 启动过程发生未捕获异常:', err);
        app.exit(1);
    }
});

// 窗口全部关闭时的退出行为必须显式声明：
// 若该事件未注册，Electron 会在“所有窗口关闭”后静默退出（退出码 0），
// 看起来就像应用启动后立刻消失，且没有任何日志。
app.on('window-all-closed', () => {
    console.log('[Electron] window-all-closed 事件触发，窗口已全部关闭');
    if (process.platform !== 'darwin') {
        stopPythonSidecar();
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
