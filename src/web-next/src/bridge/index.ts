import { initBridge as initElectron, onEvent as electronOnEvent, getClientId } from './electron-bridge';
import { initBridge as initPyQt } from './pyqt-bridge';

/** 检测当前是否运行在 Electron 环境中 */
function isElectronEnvironment(): boolean {
    return !!(window as any).electronAPI;
}

/** 内部缓存单例 */
let _cachedBridge: any = null;
let _isInitializing = false;
const _readyCallbacks: Array<(bridge: any) => void> = [];

/**
 * 初始化桥接并缓存单例
 * 在 App.vue 的 onMounted 中最先调用
 */
async function initBridge() {
    if (_cachedBridge) return _cachedBridge;
    if (_isInitializing) {
        return new Promise(resolve => _readyCallbacks.push(resolve));
    }

    _isInitializing = true;
    try {
        if (isElectronEnvironment()) {
            console.log('[Bridge] 检测到 Electron 环境，正在初始化...');
            _cachedBridge = await initElectron();
        } else if ((window as any).qt) {
            console.log('[Bridge] 检测到遗留 PyQt 环境，正在重度初始化...');
            _cachedBridge = await initPyQt();
        } else {
            console.log('[Bridge] 检测到 Web/局域网环境，正在初始化 FastAPI 桥接...');
            _cachedBridge = await initElectron();
        }
        
        (window as any).pybridge = _cachedBridge;
        console.log('[Bridge] 初始化完成，正在触发回调队列...');
        
        _readyCallbacks.forEach(cb => cb(_cachedBridge));
        _readyCallbacks.length = 0;
        
        return _cachedBridge;
    } finally {
        _isInitializing = false;
    }
}

/**
 * 同步获取桥接实例
 * 改进版：返回一个深层递归的 Proxy，支持在初始化完成前注册事件
 */
function getBridge() {
    if (_cachedBridge) return _cachedBridge;
    
    // 递归 Proxy：处理 bridge.module.event.connect 这种多级调用
    const createProxy = (path: string[] = []): any => {
        return new Proxy(() => {}, {
            get(_target, prop) {
                if (typeof prop === 'string') {
                    return createProxy([...path, prop]);
                }
                return null;
            },
            apply(_target, _thisArg, args) {
                const propPath = path.join('.');
                console.warn(`[Bridge Pending] 异步队列化调用: ${propPath}`);
                
                // 将调用推入就绪队列
                _readyCallbacks.push((bridge) => {
                    let current: any = bridge;
                    for (let i = 0; i < path.length - 1; i++) {
                        current = (current as any)[path[i]!];
                        if (!current) return;
                    }
                    const method = (current as any)[path[path.length - 1]!];
                    if (typeof method === 'function') {
                        method.apply(current, args);
                    }
                });
            }
        });
    };

    return createProxy();
}

/** 全局事件转发 */
function onEvent(handler: (eventType: string, data: any) => void): () => void {
    if (_cachedBridge) {
        if (isElectronEnvironment()) return electronOnEvent(handler);
        return () => {};
    }
    
    // 如果桥接没好，先存起来
    let cleanup: any = null;
    _readyCallbacks.push((bridge) => {
        if (isElectronEnvironment()) {
            cleanup = electronOnEvent(handler);
        }
    });
    
    return () => { if (cleanup) cleanup(); };
}

function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
    (window as any)[name] = handler;
}

async function setupBridge() {
    return await initBridge();
}

export { initBridge, getBridge, registerGlobalHandler, setupBridge, isElectronEnvironment, onEvent, getClientId };
