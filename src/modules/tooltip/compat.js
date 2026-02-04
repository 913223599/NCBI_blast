/**
 * 向后兼容层
 * 保持与原有HelpTooltipManager的API兼容性
 */

import { initTooltip } from './index.js';

/**
 * 全局HelpTooltipManager兼容类
 * 模拟原有的API接口
 */
class HelpTooltipManagerCompat {
    constructor() {
        this.tooltip = null;
        this.translations = {};
    }

    /**
     * 初始化方法（兼容原有API）
     * @param {Object} translations - 翻译字典
     * @returns {HelpTooltipManagerCompat} 实例
     */
    static init(translations = {}) {
        // 如果已经存在实例，返回现有实例
        if (!window.__helpTooltipManager) {
            window.__helpTooltipManager = new HelpTooltipManagerCompat();
        }
        
        // 更新翻译字典
        if (translations) {
            window.__helpTooltipManager.updateTranslations(translations);
        }
        
        return window.__helpTooltipManager;
    }

    /**
     * 更新翻译字典
     * @param {Object} translations - 新的翻译字典
     */
    updateTranslations(translations) {
        this.translations = translations || {};
        
        // 如果tooltip已初始化，更新其配置
        if (this.tooltip) {
            this.tooltip.update({ translations: this.translations });
        } else {
            // 初始化新的tooltip管理器
            this.tooltip = initTooltip({
                selector: '[data-i18n-help]',
                translations: this.translations,
                delay: 600
            });
        }
    }

    /**
     * 显示tooltip（兼容方法）
     * @param {HTMLElement} target - 目标元素
     * @param {string} text - 显示文本
     */
    show(target, text) {
        if (!this.tooltip) {
            this.initializeTooltip();
        }
        
        // 临时附加元素并显示
        this.tooltip.attach(target, text);
        this.tooltip.show(target, text);
    }

    /**
     * 隐藏tooltip（兼容方法）
     */
    hide() {
        if (this.tooltip) {
            this.tooltip.hide();
        }
    }

    /**
     * 初始化tooltip管理器
     */
    initializeTooltip() {
        this.tooltip = initTooltip({
            translations: this.translations,
            delay: 600,
            selector: '[data-i18n-help]'
        });
    }

    /**
     * 销毁方法
     */
    destroy() {
        if (this.tooltip) {
            this.tooltip.destroy();
            this.tooltip = null;
        }
    }
}

/**
 * 全局初始化函数（兼容原有调用）
 * @param {Object} translations - 翻译字典
 * @returns {HelpTooltipManagerCompat} 兼容实例
 */
export function initHelpTooltip(translations = {}) {
    return HelpTooltipManagerCompat.init(translations);
}

// 如果在浏览器环境中，设置全局变量
if (typeof window !== 'undefined') {
    // 保持原有的全局接口
    window.HelpTooltipManager = HelpTooltipManagerCompat;
    
    // 如果原有实例存在，进行迁移
    if (window.__helpTooltipManager && window.__helpTooltipManager.translations) {
        HelpTooltipManagerCompat.init(window.__helpTooltipManager.translations);
    }
}

export default HelpTooltipManagerCompat;