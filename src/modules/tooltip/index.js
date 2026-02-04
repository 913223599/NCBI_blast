/**
 * Tooltip 模块入口文件
 * 提供统一的导出接口
 */

// 核心类导出
export { TooltipManager } from './core/TooltipManager.js';
export { TooltipConfig } from './core/TooltipConfig.js';

// 类型定义导出
export { DEFAULT_OPTIONS, POSITIONS, THEMES, EVENTS } from './core/types.js';

/**
 * 简化的初始化函数
 * @param {Object} options - 配置选项
 * @returns {TooltipManager} tooltip管理器实例
 */
export function initTooltip(options = {}) {
    return TooltipManager.init(options);
}

/**
 * 创建独立的tooltip实例
 * @param {Object} options - 配置选项
 * @returns {TooltipManager} tooltip管理器实例
 */
export function createTooltip(options = {}) {
    const tooltip = new TooltipManager(options);
    return tooltip.init();
}

// 默认导出
export default {
    init: initTooltip,
    create: createTooltip,
    TooltipManager,
    TooltipConfig
};