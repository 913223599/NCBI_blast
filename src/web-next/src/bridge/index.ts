import { initBridge as initElectron } from './electron-bridge';
import { initBridge as initPyQt } from './pyqt-bridge';

/** 检测当前是否运行在 Electron 环境中 */
function isElectronEnvironment(): boolean {
    return !!(window as any).electronAPI;
}

/** 内部缓存单例 */
let _cachedBridge: any = null;

/**
 * 初始化桥接并缓存单例
 * 在 App.vue 的 onMounted 中最先调用
 */
async function initBridge() {
    if (_cachedBridge) return _cachedBridge;

    if (isElectronEnvironment()) {
        console.log('[Bridge] 检测到 Electron 环境，正在初始化...');
        _cachedBridge = await initElectron();
    } else {
        console.log('[Bridge] 检测到 PyQt 环境，正在初始化...');
        _cachedBridge = await initPyQt();
    }
    
    // 同时也挂载到全局，方便调试和老项目访问
    (window as any).pybridge = _cachedBridge;
    
    return _cachedBridge;
}

/**
 * 同步获取桥接实例
 * 如果尚未初始化，则返回一个安全的 Proxy 或抛出有意义的错误
 */
function getBridge() {
    if (_cachedBridge) return _cachedBridge;
    
    // 容错：如果还在初始化中就被调用，返回一个降级的 Proxy 避免崩溃
    console.warn('[Bridge] 尝试在初始化完成前使用桥接。');
    return new Proxy({} as any, {
        get(_target, prop) {
            return (...args: any[]) => {
                console.warn(`[Bridge Pending] 调用了 ${String(prop)}，但桥接尚未就绪。`);
                // 找到参数中的最后一个 function 作为 callback 模拟空响应
                const callback = args.find(a => typeof a === 'function');
                if (callback) callback(null);
            };
        }
    });
}

function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
    (window as any)[name] = handler;
}

/** 用于首次启动的包装器 */
async function setupBridge() {
    return await initBridge();
}

export { initBridge, getBridge, registerGlobalHandler, setupBridge, isElectronEnvironment };
