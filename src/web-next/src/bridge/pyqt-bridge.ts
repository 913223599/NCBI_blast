/**
 * PyQt Bridge - QWebChannel 通信层统一封装
 * 
 * 所有前端与 Python 后端的通信都通过此模块进行，
 * 消除了旧架构中散落在各处的 window.py_bridge 调用。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** 扩展 Window 接口以支持 QWebChannel */
declare global {
    interface Window {
        QWebChannel?: new (
            transport: unknown,
            callback: (channel: { objects: { py_bridge: PyBridge } }) => void
        ) => void
        qt?: { webChannelTransport: unknown }
        [key: string]: any
    }
}

/** Python 端 WebBridge 暴露的 Slot 接口类型定义 */
export interface PyBridge {
    /* 文件操作 */
    request_file_load(fileType: string): void
    save_file(content: string, filenameHint: string, callback?: (success: boolean) => void): void
    open_results_dir(path: string): void
    open_external_url(url: string): void

    /* BLAST 作业 */
    run_blast_job(paramsJson: string, callback?: (res: string) => void): void
    stop_blast_job(taskId: string): void
    pause_blast_job(taskId: string): void
    resume_blast_job(taskId: string): void
    get_task_status(taskId: string, callback?: (res: string) => void): void
    get_task_results(taskId: string, callback?: (res: string) => void): void
    get_all_tasks(callback?: (res: string) => void): void
    delete_single_task(taskId: string): void
    resume_task(taskId: string): void
    list_tree_sequences(callback: (res: string) => void): void
    clear_all_history(): void
    rename_task(taskId: string, newName: string): void
    get_detailed_blast_results(csvFile: string, callback?: (res: string) => void): void

    /* 进化树 */
    request_tree_analysis(mode: string): void
    request_tree_reroot(nodeId: string): void
    clear_tree_workspace(callback?: (res: boolean) => void): void

    /* 配置 */
    get_ui_translations(callback?: (res: string) => void): void
    get_ui_language(callback?: (res: string) => void): void
    save_ui_language(langCode: string): void
    get_api_key(service: string, callback?: (res: string) => void): void
    save_api_key(service: string, key: string): void
    save_selected_model(modelKey: string, callback?: (res: boolean) => void): void
    get_selected_model(callback?: (res: string) => void): void

    /* 历史记录 */
    translate_text(text: string, category: string, callback?: (res: string) => void): void
    search_dictionary(query: string, proofread_mode?: boolean | ((res: string) => void), callback?: (res: string) => void): void
    save_dictionary_term(english: string, chinese: string, category: string, callback?: (res: boolean) => void): void
    delete_dictionary_term(english: string, callback?: (res: boolean) => void): void
    verify_dictionary_term(english: string, callback?: (res: boolean) => void): void
    get_all_dictionary_terms(proofread_mode?: boolean | ((res: string) => void), callback?: (res: string) => void): void

    /* 帮助 */
    get_help_structure(): void
    get_help_content(topicId: string): void

    /* 日志 */
    on_page_ready(): void
    log_message(message: string): void
    on_js_error(message: string): void

    /* 数据库存储 (SQLite) */
    db_save_freezer(freezerJson: string, callback?: (res: boolean) => void): void
    db_delete_freezer(freezerId: string, callback?: (res: boolean) => void): void
    db_save_record(recordJson: string, callback?: (res: boolean) => void): void
    db_delete_record(recordId: string, callback?: (res: boolean) => void): void
    db_load_all(callback?: (res: string) => void): void
    db_clear_all(callback?: (res: boolean) => void): void
    db_save_code_lookup(lookupJson: string, callback?: (res: boolean) => void): void

    [key: string]: (...args: any[]) => any
}

/** 全局桥接单例 */
let bridgeInstance: PyBridge | null = null
let bridgeReadyPromise: Promise<PyBridge> | null = null

/**
 * 初始化桥接连接（在 QWebEngineView 中通过 QWebChannel 建立连接）
 * 在普通浏览器中将返回一个 Mock 对象供开发调试
 */
function initBridge(): Promise<PyBridge> {
    if (bridgeReadyPromise) return bridgeReadyPromise

    bridgeReadyPromise = new Promise<PyBridge>((resolve) => {
        if (window.QWebChannel && window.qt) {
            // 在 QWebEngineView 内运行
            new window.QWebChannel(
                window.qt.webChannelTransport,
                (channel) => {
                    bridgeInstance = channel.objects.py_bridge
                    console.log('[Bridge] QWebChannel 已建立连接')
                    resolve(bridgeInstance)
                }
            )
        } else {
            // 浏览器开发模式 - 提供 Mock
            console.warn('[Bridge] QWebChannel 不可用，使用 Mock 模式')
            const mockBridge = new Proxy({} as PyBridge, {
                get(_target, prop) {
                    return (...args: unknown[]) => {
                        console.log(`[Bridge Mock] ${String(prop)}(`, ...args, ')')
                    }
                }
            })
            bridgeInstance = mockBridge
            resolve(mockBridge)
        }
    })

    return bridgeReadyPromise
}

/**
 * 获取已初始化的桥接实例
 * @throws 如果桥接尚未初始化
 */
function getBridge(): PyBridge {
    if (!bridgeInstance) {
        throw new Error('[Bridge] 桥接尚未初始化，请先调用 initBridge()')
    }
    return bridgeInstance
}

/**
 * 注册从 Python 端调用 JS 的回调函数
 * Python 通过 page.runJavaScript() 调用这些全局方法
 */
function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
    window[name] = handler
}

export { initBridge, getBridge, registerGlobalHandler }

