/**
 * Tooltip 配置管理器
 * 负责处理配置选项的验证、合并和管理
 */

import { DEFAULT_OPTIONS } from './types.js';

export class TooltipConfig {
    /**
     * 构造函数
     * @param {Object} options - 用户配置选项
     */
    constructor(options = {}) {
        this.options = this.mergeOptions(options);
        this.validators = this.createValidators();
    }

    /**
     * 合并默认配置和用户配置
     * @param {Object} userOptions - 用户提供的配置
     * @returns {Object} 合并后的配置
     */
    mergeOptions(userOptions) {
        const merged = { ...DEFAULT_OPTIONS };
        
        // 深度合并配置
        Object.keys(userOptions).forEach(key => {
            if (userOptions[key] !== undefined) {
                merged[key] = userOptions[key];
            }
        });
        
        return merged;
    }

    /**
     * 验证配置选项
     * @throws {Error} 当配置无效时抛出错误
     */
    validate() {
        const errors = [];
        
        // 验证数值类型配置
        ['delay', 'maxWidth'].forEach(key => {
            if (typeof this.options[key] !== 'number' || this.options[key] < 0) {
                errors.push(`${key} 必须是非负数`);
            }
        });
        
        // 验证主题配置
        if (!['light', 'dark', 'auto'].includes(this.options.theme)) {
            errors.push('theme 必须是 light、dark 或 auto');
        }
        
        // 验证位置配置
        if (!['auto', 'top', 'bottom', 'left', 'right'].includes(this.options.position)) {
            errors.push('position 必须是 auto、top、bottom、left 或 right');
        }
        
        // 验证布尔类型配置
        ['animation'].forEach(key => {
            if (typeof this.options[key] !== 'boolean') {
                errors.push(`${key} 必须是布尔值`);
            }
        });
        
        // 验证容器元素
        if (this.options.container && !(this.options.container instanceof HTMLElement)) {
            errors.push('container 必须是有效的 HTMLElement');
        }
        
        if (errors.length > 0) {
            throw new Error(`配置验证失败:\n${errors.join('\n')}`);
        }
    }

    /**
     * 创建验证器函数
     * @returns {Object} 验证器映射
     */
    createValidators() {
        return {
            delay: (value) => typeof value === 'number' && value >= 0,
            maxWidth: (value) => typeof value === 'number' && value > 0,
            theme: (value) => ['light', 'dark', 'auto'].includes(value),
            position: (value) => ['auto', 'top', 'bottom', 'left', 'right'].includes(value),
            animation: (value) => typeof value === 'boolean',
            container: (value) => !value || value instanceof HTMLElement,
            translations: (value) => !value || typeof value === 'object',
            selector: (value) => typeof value === 'string' && value.length > 0
        };
    }

    /**
     * 更新配置选项
     * @param {Object} newOptions - 新的配置选项
     * @returns {boolean} 是否更新成功
     */
    update(newOptions) {
        try {
            const updatedOptions = { ...this.options };
            
            // 验证并更新每个选项
            Object.keys(newOptions).forEach(key => {
                if (this.validators[key]) {
                    if (this.validators[key](newOptions[key])) {
                        updatedOptions[key] = newOptions[key];
                    } else {
                        console.warn(`无效的配置选项 ${key}:`, newOptions[key]);
                    }
                }
            });
            
            this.options = updatedOptions;
            return true;
        } catch (error) {
            console.error('配置更新失败:', error.message);
            return false;
        }
    }

    /**
     * 获取配置值
     * @param {string} key - 配置键名
     * @returns {*} 配置值
     */
    get(key) {
        return this.options[key];
    }

    /**
     * 获取所有配置
     * @returns {Object} 完整配置对象
     */
    getAll() {
        return { ...this.options };
    }

    /**
     * 重置为默认配置
     */
    reset() {
        this.options = { ...DEFAULT_OPTIONS };
    }

    /**
     * 获取计算后的容器元素
     * @returns {HTMLElement} 容器元素
     */
    getContainer() {
        return this.options.container || document.body;
    }

    /**
     * 检查是否启用了动画
     * @returns {boolean} 动画是否启用
     */
    isAnimationEnabled() {
        return this.options.animation;
    }

    /**
     * 获取主题配置
     * @returns {string} 主题名称
     */
    getTheme() {
        const theme = this.options.theme;
        if (theme === 'auto') {
            // 根据系统主题自动判断
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return theme;
    }
}