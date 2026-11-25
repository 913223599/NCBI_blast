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

const PROJECT_ROOT = path.resolve(__dirname, '..');

function loadAppMetadata() {
    const fallback = { name: 'NCBI Bio-Station', version: '2.1.0' };
    try {
        const versionPath = path.join(PROJECT_ROOT, 'version.json');
        if (fs.existsSync(versionPath)) {
            const parsed = JSON.parse(fs.readFileSync(versionPath, 'utf-8'));
            return {
                name: typeof parsed.name === 'string' && parsed.name.trim() ? parsed.name.trim() : fallback.name,
                version: typeof parsed.version === 'string' && parsed.version.trim() ? parsed.version.trim() : fallback.version,
            };
        }
    } catch (e) {
        // 回退默认元信息
    }
    return fallback;
}

const APP_META = loadAppMetadata();

console.log('=======================================');
console.log(`  ${APP_META.name} v${APP_META.version} — Electron Shell`);
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
const PYTHON_EXE = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
const API_SERVER_SCRIPT = path.join(PROJECT_ROOT, 'src', 'backend', 'api_server.py');
const API_PORT = 8765;
const VITE_PORT = 5173;
const IS_DEV = process.argv.includes('--dev');

// ─── 状态变量 ─────────────────────────────────────
let pythonProcess = null;
let mainWindow = null;
let isQuitting = false;

// IPC 安全校验与路径授权白名单
const ALLOWED_DEV_ORIGINS = new Set([
    `http://localhost:${VITE_PORT}`,
    `http://127.0.0.1:${VITE_PORT}`,
    `http://localhost:${API_PORT}`,
    `http://127.0.0.1:${API_PORT}`,
]);
const approvedReadPaths = new Set();
const approvedWritePaths = new Set();
const SENSITIVE_BASENAMES = new Set([
    '.mail_auth',
    '.mail_smtp_auth',
    '.sangon_auth',
    '.env',
    'config.json',
    'mail_config.json',
    'sangon_16s_config.json',
]);
const ALLOWED_WRITE_SUBDIRS = ['results', 'reports', 'data', 'temp'];

function validateSender(frame) {
    if (!frame) return false;
    const origin = frame.origin || '';
    if (ALLOWED_DEV_ORIGINS.has(origin)) return true;
    const url = frame.url || '';
    if (!IS_DEV && url.startsWith('file://')) {
        const expectedPrefix = `file:///${path.join(PROJECT_ROOT, 'src', 'web-next', 'dist').replace(/\\/g, '/').toLowerCase()}`;
        const normalizedUrl = decodeURIComponent(url).replace(/\\/g, '/').toLowerCase();
        if (normalizedUrl.startsWith(expectedPrefix)) return true;
    }
    console.warn(`[Electron:Security] 拦截未授权 IPC 来源: origin=${origin}, url=${url}`);
    return false;
}

function isAllowedExternalUrl(rawUrl) {
    if (typeof rawUrl !== 'string' || !rawUrl.trim()) return false;
    try {
        const parsed = new URL(rawUrl);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
        return false;
    }
}

function normalizeResolvedPath(targetPath) {
    if (typeof targetPath !== 'string' || !targetPath.trim() || targetPath.includes('\0')) {
        return null;
    }
    return path.resolve(targetPath);
}

function isInsideDir(targetPath, baseDir) {
    const rel = path.relative(path.resolve(baseDir), path.resolve(targetPath));
    return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

function isSensitiveFile(resolvedPath) {
    const base = path.basename(resolvedPath).toLowerCase();
    if (SENSITIVE_BASENAMES.has(base)) return true;
    const lowered = resolvedPath.toLowerCase();
    return lowered.includes(`${path.sep}.ssh${path.sep}`) || lowered.includes(`${path.sep}.git${path.sep}`);
}

function isSafeReadPath(targetPath) {
    const resolved = normalizeResolvedPath(targetPath);
    if (!resolved || isSensitiveFile(resolved)) return false;
    if (approvedReadPaths.has(resolved.toLowerCase())) return true;
    // 允许工作区内非敏感文件与用户主动拖入的普通数据文件（排除敏感凭证与系统关键目录）
    if (isInsideDir(resolved, PROJECT_ROOT)) return true;
    const winDir = (process.env.SystemRoot || 'C:\\Windows').toLowerCase();
    if (resolved.toLowerCase().startsWith(winDir)) return false;
    return true;
}

function isSafeWritePath(targetPath) {
    const resolved = normalizeResolvedPath(targetPath);
    if (!resolved || isSensitiveFile(resolved)) return false;
    if (approvedWritePaths.has(resolved.toLowerCase())) return true;
    return ALLOWED_WRITE_SUBDIRS.some((sub) => isInsideDir(resolved, path.join(PROJECT_ROOT, sub)));
}

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
            PYTHONUTF8: '1',
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
        const lines = data.toString().split(/\r?\n/);
        for (const rawLine of lines) {
            const line = rawLine.trim();
            if (!line) continue;
            if (/^INFO:\s/.test(line)) {
                console.log(`[Python] ${line}`);
            } else {
                console.log(`[Python:ERR] ${line}`);
            }
        }
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
            const request = http.get(`http://127.0.0.1:${API_PORT}/api/health`, (res) => {
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
        const targetProc = pythonProcess;
        const targetPid = targetProc.pid;
        pythonProcess = null;
        console.log(`[Electron] 正在响应生命周期事件，停止 Python Sidecar (PID=${targetPid})...`);
        try {
            targetProc.kill('SIGTERM');
        } catch (e) {
            // 忽略信号发送异常
        }

        // 不再无差别执行全机 wsl --terminate（避免误杀用户本机其他 WSL 环境），
        // 交由 Python lifespan 优雅清理本项目关联资源，并在超时后仅强制终止自身子进程树。
        setTimeout(() => {
            if (targetProc && !targetProc.killed && targetPid) {
                try {
                    if (process.platform === 'win32') {
                        const { execSync } = require('child_process');
                        execSync(`taskkill /T /F /PID ${targetPid}`, { stdio: 'ignore' });
                    } else {
                        targetProc.kill('SIGKILL');
                    }
                } catch (e) {
                    // 进程已退出
                }
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
            title: 'NCBI Bio-Station | 生物序列分析工作站',
            backgroundColor: '#f1f5f9',
            show: false,
            webPreferences: {
                preload: path.join(__dirname, 'preload.js'),
                contextIsolation: true,
                nodeIntegration: false,
                sandbox: true,
                backgroundThrottling: false,
            }
        });

        // 注入 Content-Security-Policy 响应头（按开发/生产环境收口）
        const cspDirectives = IS_DEV
            ? [
                "default-src 'self'",
                `script-src 'self' 'unsafe-inline' 'unsafe-eval' http://localhost:${VITE_PORT} http://127.0.0.1:${VITE_PORT}`,
                "style-src 'self' 'unsafe-inline'",
                `connect-src 'self' http://127.0.0.1:${API_PORT} ws://127.0.0.1:${API_PORT} http://localhost:${API_PORT} ws://localhost:${API_PORT} http://localhost:${VITE_PORT} ws://localhost:${VITE_PORT}`,
                `img-src 'self' data: blob: http://127.0.0.1:${API_PORT} http://localhost:${API_PORT}`,
                "font-src 'self' data:",
                "worker-src 'self' blob:",
                "object-src 'none'",
            ].join('; ')
            : [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline'",
                "style-src 'self' 'unsafe-inline'",
                `connect-src 'self' http://127.0.0.1:${API_PORT} ws://127.0.0.1:${API_PORT} http://localhost:${API_PORT} ws://localhost:${API_PORT}`,
                `img-src 'self' data: blob: http://127.0.0.1:${API_PORT} http://localhost:${API_PORT}`,
                "font-src 'self' data:",
                "worker-src 'self' blob:",
                "object-src 'none'",
            ].join('; ');

        mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
            callback({
                responseHeaders: {
                    ...details.responseHeaders,
                    'Content-Security-Policy': [cspDirectives],
                },
            });
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

        // 拦截所有新窗口创建请求（例如 window.open），仅允许 http/https 协议外链
        mainWindow.webContents.setWindowOpenHandler(({ url }) => {
            if (isAllowedExternalUrl(url)) {
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

ipcMain.handle('dialog:openFile', async (event, options = {}) => {
    if (!validateSender(event.senderFrame)) return null;
    const result = await dialog.showOpenDialog(mainWindow, {
        title: options.title || '打开文件',
        filters: options.filters || [{ name: 'All Files', extensions: ['*'] }],
        properties: options.properties || ['openFile']
    });
    if (result.canceled) return null;
    for (const p of result.filePaths || []) {
        const resolved = normalizeResolvedPath(p);
        if (resolved) approvedReadPaths.add(resolved.toLowerCase());
    }
    return result.filePaths;
});

ipcMain.handle('dialog:saveFile', async (event, options = {}) => {
    if (!validateSender(event.senderFrame)) return null;
    const result = await dialog.showSaveDialog(mainWindow, {
        title: options.title || '保存文件',
        defaultPath: options.defaultPath || '',
        filters: options.filters || [{ name: 'All Files', extensions: ['*'] }]
    });
    if (result.canceled || !result.filePath) return null;
    const resolved = normalizeResolvedPath(result.filePath);
    if (resolved) approvedWritePaths.add(resolved.toLowerCase());
    return result.filePath;
});

ipcMain.handle('shell:openExternal', async (event, url) => {
    if (!validateSender(event.senderFrame)) return false;
    if (!isAllowedExternalUrl(url)) {
        console.warn(`[Electron:Security] 拦截非法外部协议 URL: ${String(url)}`);
        return false;
    }
    await shell.openExternal(url);
    return true;
});

ipcMain.handle('shell:openPath', async (event, dirPath) => {
    if (!validateSender(event.senderFrame)) return 'unauthorized';
    const resolved = normalizeResolvedPath(dirPath);
    if (!resolved || isSensitiveFile(resolved)) return 'forbidden';
    return shell.openPath(resolved);
});

ipcMain.handle('fs:readFile', async (event, filePath) => {
    if (!validateSender(event.senderFrame)) return null;
    if (!isSafeReadPath(filePath)) {
        console.warn(`[Electron:Security] 拦截受限文件读取请求: ${String(filePath)}`);
        return null;
    }
    try {
        return await fs.promises.readFile(path.resolve(filePath), 'utf-8');
    } catch {
        return null;
    }
});

ipcMain.handle('fs:writeFile', async (event, filePath, content) => {
    if (!validateSender(event.senderFrame)) return false;
    if (!isSafeWritePath(filePath)) {
        console.warn(`[Electron:Security] 拦截未授权文件写入请求: ${String(filePath)}`);
        return false;
    }
    try {
        await fs.promises.writeFile(path.resolve(filePath), String(content ?? ''), 'utf-8');
        return true;
    } catch (err) {
        console.error('[Electron] 写入文本文件失败:', err);
        return false;
    }
});

ipcMain.handle('fs:writeBinaryFile', async (event, filePath, base64Data) => {
    if (!validateSender(event.senderFrame)) return false;
    if (!isSafeWritePath(filePath)) {
        console.warn(`[Electron:Security] 拦截未授权二进制写入请求: ${String(filePath)}`);
        return false;
    }
    try {
        const buffer = Buffer.from(base64Data, 'base64');
        await fs.promises.writeFile(path.resolve(filePath), buffer);
        return true;
    } catch (err) {
        console.error('[Electron] 写入二进制文件失败:', err);
        return false;
    }
});

ipcMain.handle('app:getApiPort', (event) => (validateSender(event.senderFrame) ? API_PORT : null));
ipcMain.handle('app:getProjectRoot', (event) => (validateSender(event.senderFrame) ? PROJECT_ROOT : null));

ipcMain.handle('app:relaunch', async (event) => {
    if (!validateSender(event.senderFrame)) return false;
    console.log('[Electron] 收到应用重启请求，正在切断 Sidecar 并重启...');
    isQuitting = true;
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
            isQuitting = true;
            stopPythonSidecar();
            app.exit(1);
            return;
        }

        createWindow();
    } catch (err) {
        console.error('[Electron] 启动过程发生未捕获异常:', err);
        isQuitting = true;
        app.exit(1);
    }
});

app.on('window-all-closed', () => {
    console.log('[Electron] window-all-closed 事件触发，窗口已全部关闭');
    if (process.platform !== 'darwin') {
        isQuitting = true;
        stopPythonSidecar();
        app.quit();
    }
});

app.on('before-quit', () => {
    if (!isQuitting) {
        isQuitting = true;
    }
    console.log('[Electron] before-quit 事件触发');
    stopPythonSidecar();
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});
