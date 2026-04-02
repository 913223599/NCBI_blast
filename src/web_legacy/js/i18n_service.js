/**
 * Bio-Station I18n Service
 * 
 * 模块化语言管理器，负责加载、存储和应用翻译。
 * 支持主窗口和 iFrame 环境（只要有 py_bridge 访问权限）。
 */

class I18nService {
    constructor() {
        this.translations = {};
        this.currentLang = 'zh_CN'; // Default
        this.initialized = false;
        this.bridge = null;

        // 立即尝试同步，无需等待 init
        this.trySyncFromParent();
    }

    init(bridgeInstance) {
        if (bridgeInstance) {
            this.bridge = bridgeInstance;
            this.initialized = true;
        }

        // 优先从父窗口同步翻译数据，规避 Bridge 异步造成的白屏/未翻译状态
        if (this.trySyncFromParent()) {
            console.log("I18nService: Synchronized from parent window.");
        }
    }

    /** 尝试从父窗口同步翻译 */
    trySyncFromParent() {
        try {
            // 兼容多种可能的父窗口对象结构
            const parentI18n = window.parent.i18n || (window.parent.app && window.parent.app.i18n);
            if (parentI18n && parentI18n.translations && Object.keys(parentI18n.translations).length > 0) {
                this.translations = { ...parentI18n.translations };
                this.initialized = true;
                this.applyTranslations();
                return true;
            }
        } catch (e) {
            // 跨域安全限制或未就绪
        }
        return false;
    }

    async loadTranslations() {
        // 如果已经同步过数据，视为初步就绪
        if (this.translations && Object.keys(this.translations).length > 0) {
            this.initialized = true;
        }

        if (!this.bridge || !this.bridge.get_ui_translations) {
            console.warn("I18nService: Bridge method get_ui_translations missing.");
            this.initialized = true;
            return;
        }

        return new Promise((resolve) => {
            try {
                this.bridge.get_ui_translations((json) => {
                    try {
                        const newTranslations = JSON.parse(json);
                        this.translations = { ...this.translations, ...newTranslations };
                        console.log(`I18nService: Loaded ${Object.keys(newTranslations).length} translations.`);
                        this.applyTranslations();
                    } catch (e) {
                        console.error("I18nService: Failed to parse translations:", e);
                    }
                    this.initialized = true;
                    resolve();
                });
            } catch (err) {
                console.error("I18nService: Bridge call interrupted:", err);
                this.initialized = true;
                resolve();
            }
        });
    }

    /**
     * 获取指定 Key 的翻译并支持变量替换
     * @param {string} key 
     * @param {Object} params - e.g. { name: 'World' } replacements for {name}
     * @returns {string} Translated text or key
     */
    t(key, params = {}) {
        if (!key) return '';
        if (!this.translations) return key;

        // Case-insensitive lookup
        const lowerKey = key.toLowerCase();
        let translation = key;

        // Find if any key in translations (lowercased) matches
        const foundKey = Object.keys(this.translations).find(k => k.toLowerCase() === lowerKey);
        if (foundKey) {
            translation = this.translations[foundKey];
        }

        // Handle interpolation: replace {var} with params.var
        if (params && typeof params === 'object') {
            Object.keys(params).forEach(p => {
                const regex = new RegExp(`\\{${p}\\}`, 'g');
                translation = translation.replace(regex, params[p]);
            });
        }

        return translation;
    }

    /**
     * 更新当前页面所有 data-i18n 元素
     * OPTIONAL: rootElement 可指定只更新某个容器
     */
    applyTranslations(rootElement = document) {
        if (!rootElement || !rootElement.querySelectorAll) return;

        // Text Content
        rootElement.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.t(key);
            if (translation !== key) {
                el.textContent = translation;
            }
        });

        // Placeholders
        rootElement.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            const translation = this.t(key);
            if (translation !== key) {
                el.placeholder = translation;
            }
        });

        // Titles
        rootElement.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            const translation = this.t(key);
            if (translation !== key) {
                el.title = translation;
            }
        });
    }

    /**
     * 保存 UI 语言设置
     * @param {string} langCode e.g. 'zh_CN', 'en_US'
     * @param {Function} callback (success) => {}
     */
    saveLanguage(langCode, callback) {
        if (this.bridge && this.bridge.save_ui_language) {
            this.bridge.save_ui_language(langCode, callback);
        } else {
            console.error("I18nService: save_ui_language not available.");
            if (callback) callback(false);
        }
    }
}

// 导出类和单例
window.I18nService = I18nService;
window.i18n = new I18nService();
