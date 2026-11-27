/**
 * Electron 开发模式日志转发器 (dev-runner.js)
 *
 * 解决 Windows 下 electron.exe 作为 GUI 子系统进程启动时，
 * 控制台窗口丢失主进程与 Python Sidecar 实时 stdout/stderr 日志的问题。
 */
const { spawn } = require('child_process');
const path = require('path');

const overrideBinary = (process.env.ELECTRON_DEV_RUNNER_BINARY || '').trim();
const binaryPath = overrideBinary || require('electron');
const userArgs = process.argv.slice(2);
const launchArgs = overrideBinary ? userArgs : ['.', ...userArgs];

const childEnv = { ...process.env };
delete childEnv.ELECTRON_RUN_AS_NODE;
delete childEnv.ELECTRON_NO_ATTACH_CONSOLE;
childEnv.ELECTRON_ENABLE_LOGGING = '1';
childEnv.PYTHONUTF8 = '1';
childEnv.PYTHONIOENCODING = 'utf-8';
childEnv.FORCE_COLOR = '1';

const child = spawn(binaryPath, launchArgs, {
    cwd: overrideBinary ? process.cwd() : path.resolve(__dirname),
    env: childEnv,
    stdio: ['inherit', 'pipe', 'pipe'],
    windowsHide: false,
});

if (child.stdout) {
    child.stdout.on('data', (chunk) => {
        process.stdout.write(chunk);
    });
}

if (child.stderr) {
    child.stderr.on('data', (chunk) => {
        process.stderr.write(chunk);
    });
}

for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => {
        if (!child.killed) {
            try {
                child.kill(sig);
            } catch (err) {
                process.stderr.write(`[dev-runner] 转发信号 ${sig} 失败: ${err && err.message ? err.message : err}\n`);
            }
        }
    });
}

child.on('error', (err) => {
    console.error(`[dev-runner] 启动目标进程失败 (${binaryPath}):`, err);
    process.exit(1);
});

child.on('exit', (code, signal) => {
    if (typeof code === 'number') {
        process.exit(code);
    }
    console.error(`[dev-runner] 子进程被信号终止: ${signal || 'unknown'}`);
    process.exit(1);
});
