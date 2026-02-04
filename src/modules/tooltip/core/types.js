/**
 * Tooltip 模块类型定义
 * 定义所有接口和类型约束
 */

/**
 * Tooltip 配置选项接口
 * @typedef {Object} TooltipOptions
 * @property {number} [delay=600] - 显示延迟时间(毫秒)
 * @property {'light'|'dark'|'auto'} [theme='auto'] - 主题样式
 * @property {'auto'|'top'|'bottom'|'left'|'right'} [position='auto'] - 显示位置
 * @property {number} [maxWidth=280] - 最大宽度(像素)
 * @property {boolean} [animation=true] - 是否启用动画效果
 * @property {HTMLElement} [container=document.body] - 容器元素
 * @property {Object} [translations=null] - 翻译字典
 * @property {string} [selector='[data-i18n-help]'] - 触发元素选择器
 */

/**
 * Tooltip 实例接口
 * @typedef {Object} TooltipInstance
 * @property {Function} attach - 附加提示到元素
 * @property {Function} detach - 从元素移除提示
 * @property {Function} show - 显示提示
 * @property {Function} hide - 隐藏提示
 * @property {Function} update - 更新配置
 * @property {Function} destroy - 销毁实例
 */

/**
 * 位置信息接口
 * @typedef {Object} PositionInfo
 * @property {number} top - 顶部坐标
 * @property {number} left - 左侧坐标
 * @property {string} placement - 实际放置位置
 */

/**
 * 事件处理回调接口
 * @typedef {Object} EventCallbacks
 * @property {Function} [onShow] - 显示时回调
 * @property {Function} [onHide] - 隐藏时回调
 * @property {Function} [onPosition] - 位置计算时回调
 */

// 默认配置常量
export const DEFAULT_OPTIONS = {
    delay: 600,
    theme: 'auto',
    position: 'auto',
    maxWidth: 280,
    animation: true,
    container: null,
    translations: null,
    selector: '[data-i18n-help]'
};

// 位置常量
export const POSITIONS = {
    TOP: 'top',
    BOTTOM: 'bottom',
    LEFT: 'left',
    RIGHT: 'right',
    AUTO: 'auto'
};

// 主题常量
export const THEMES = {
    LIGHT: 'light',
    DARK: 'dark',
    AUTO: 'auto'
};

// 事件常量
export const EVENTS = {
    MOUSE_ENTER: 'mouseenter',
    MOUSE_LEAVE: 'mouseleave',
    TOUCH_START: 'touchstart',
    TOUCH_END: 'touchend',
    CLICK: 'click'
};