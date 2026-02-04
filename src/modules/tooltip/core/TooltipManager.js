/**
 * Tooltip 管理器核心类
 * 整合所有组件，提供统一的API接口
 */

import { TooltipConfig } from './TooltipConfig.js';
import { EventHandler } from '../handlers/EventHandler.js';
import { PositionHandler } from '../handlers/PositionHandler.js';
import { DOMAdapter } from '../ui/DOMAdapter.js';
import { Renderer } from '../ui/Renderer.js';

export class TooltipManager {
    /**
     * 构造函数
     * @param {Object} options - 配置选项
     */
    constructor(options = {}) {
        // 初始化配置管理器
        this.config = new TooltipConfig(options);
        
        // 初始化各个组件
        this.domAdapter = new DOMAdapter(this.config);
        this.positionHandler = new PositionHandler(this.config);
        this.eventHandler = new EventHandler(this);
        this.renderer = new Renderer(this.domAdapter, this.positionHandler, this.config);
        
        // 状态管理
        this.isInitialized = false;
        this.attachedElements = new Map();
        this.activeElement = null;
        
        // 验证配置
        try {
            this.config.validate();
        } catch (error) {
            console.error('Tooltip配置验证失败:', error.message);
            throw error;
        }
    }

    /**
     * 初始化tooltip管理器
     * @returns {TooltipManager} 当前实例
     */
    init() {
        if (this.isInitialized) {
            console.warn('TooltipManager已经初始化');
            return this;
        }
        
        try {
            // 添加全局事件监听器
            this.eventHandler.addGlobalListeners();
            
            // 如果指定了选择器，自动绑定事件
            const selector = this.config.get('selector');
            if (selector) {
                this.autoBind(selector);
            }
            
            this.isInitialized = true;
            console.log('TooltipManager初始化完成');
            
            return this;
        } catch (error) {
            console.error('TooltipManager初始化失败:', error);
            throw error;
        }
    }

    /**
     * 自动绑定事件到符合条件的元素
     * @param {string} selector - CSS选择器
     */
    autoBind(selector) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            this.attach(element);
        });
    }

    /**
     * 附加tooltip到指定元素
     * @param {HTMLElement} element - 目标元素
     * @param {string} [content] - 自定义内容（可选）
     */
    attach(element, content = null) {
        if (!(element instanceof HTMLElement)) {
            console.error('attach方法需要HTMLElement类型的参数');
            return;
        }
        
        // 存储元素和内容的关联
        this.attachedElements.set(element, content);
        
        // 绑定事件处理器
        this.bindElementEvents(element);
        
        // 添加标识类
        element.classList.add('tooltip-enabled');
    }

    /**
     * 从元素移除tooltip
     * @param {HTMLElement} element - 目标元素
     */
    detach(element) {
        if (!(element instanceof HTMLElement)) {
            console.error('detach方法需要HTMLElement类型的参数');
            return;
        }
        
        // 移除事件监听器
        this.unbindElementEvents(element);
        
        // 从存储中移除
        this.attachedElements.delete(element);
        
        // 移除标识类
        element.classList.remove('tooltip-enabled');
        
        // 如果当前显示的是这个元素，隐藏tooltip
        if (this.activeElement === element) {
            this.hide();
        }
    }

    /**
     * 绑定元素事件
     * @param {HTMLElement} element - 目标元素
     */
    bindElementEvents(element) {
        // 鼠标事件
        this.eventHandler.bind(element, 'mouseenter', this.eventHandler.handleMouseEnter.bind(this.eventHandler));
        this.eventHandler.bind(element, 'mouseleave', this.eventHandler.handleMouseLeave.bind(this.eventHandler));
        
        // 触摸事件（如果支持）
        if (this.eventHandler.isTouchDevice) {
            this.eventHandler.bind(element, 'touchstart', this.eventHandler.handleTouchStart.bind(this.eventHandler));
            this.eventHandler.bind(element, 'touchend', this.eventHandler.handleTouchEnd.bind(this.eventHandler));
        }
        
        // 键盘事件
        this.eventHandler.bind(element, 'focus', this.eventHandler.handleFocus.bind(this.eventHandler));
        this.eventHandler.bind(element, 'blur', this.eventHandler.handleBlur.bind(this.eventHandler));
    }

    /**
     * 解绑元素事件
     * @param {HTMLElement} element - 目标元素
     */
    unbindElementEvents(element) {
        this.eventHandler.unbind(element, 'mouseenter');
        this.eventHandler.unbind(element, 'mouseleave');
        this.eventHandler.unbind(element, 'touchstart');
        this.eventHandler.unbind(element, 'touchend');
        this.eventHandler.unbind(element, 'focus');
        this.eventHandler.unbind(element, 'blur');
    }

    /**
     * 显示tooltip
     * @param {HTMLElement} element - 目标元素
     * @param {string} [content] - 自定义内容
     */
    show(element, content = null) {
        if (!this.isInitialized) {
            console.warn('TooltipManager尚未初始化，请先调用init()');
            return;
        }
        
        if (!(element instanceof HTMLElement)) {
            console.error('show方法需要HTMLElement类型的参数');
            return;
        }
        
        // 获取要显示的内容
        let displayContent = content || this.attachedElements.get(element);
        
        // 如果没有内容，尝试从元素属性获取
        if (!displayContent) {
            displayContent = this.eventHandler.getContentFromElement(element);
        }
        
        if (!displayContent) {
            console.warn('没有找到要显示的内容');
            return;
        }
        
        // 渲染tooltip
        this.renderer.render(element, displayContent);
        this.activeElement = element;
        
        // 触发回调
        if (this.config.options.onShow) {
            this.config.options.onShow(element, displayContent);
        }
    }

    /**
     * 隐藏tooltip
     */
    hide() {
        if (!this.isInitialized) return;
        
        this.renderer.hide();
        
        // 触发回调
        if (this.activeElement && this.config.options.onHide) {
            this.config.options.onHide(this.activeElement);
        }
        
        this.activeElement = null;
    }

    /**
     * 更新配置
     * @param {Object} newOptions - 新的配置选项
     * @returns {boolean} 是否更新成功
     */
    update(newOptions) {
        try {
            const success = this.config.update(newOptions);
            if (success) {
                // 更新渲染器配置
                this.renderer.updateConfig(newOptions);
                
                // 如果主题改变，更新显示的tooltip
                if (newOptions.theme !== undefined && this.activeElement) {
                    this.renderer.updateTheme();
                }
            }
            return success;
        } catch (error) {
            console.error('配置更新失败:', error.message);
            return false;
        }
    }

    /**
     * 获取当前配置
     * @returns {Object} 当前配置
     */
    getConfig() {
        return this.config.getAll();
    }

    /**
     * 获取所有已附加的元素
     * @returns {Array} 元素数组
     */
    getAttachedElements() {
        return Array.from(this.attachedElements.keys());
    }

    /**
     * 检查元素是否已附加
     * @param {HTMLElement} element - 要检查的元素
     * @returns {boolean} 是否已附加
     */
    isAttached(element) {
        return this.attachedElements.has(element);
    }

    /**
     * 手动更新当前tooltip位置
     */
    updatePosition() {
        if (this.activeElement) {
            this.renderer.updatePosition(this.activeElement);
        }
    }

    /**
     * 销毁tooltip管理器
     */
    destroy() {
        // 隐藏当前显示的tooltip
        this.hide();
        
        // 移除所有附加元素的事件
        this.attachedElements.forEach((content, element) => {
            this.detach(element);
        });
        
        // 销毁各个组件
        this.eventHandler.destroy();
        this.renderer.destroy();
        this.domAdapter.destroy();
        
        // 移除全局监听器
        this.eventHandler.removeGlobalListeners();
        
        // 重置状态
        this.isInitialized = false;
        this.attachedElements.clear();
        this.activeElement = null;
        
        console.log('TooltipManager已销毁');
    }

    /**
     * 静态初始化方法（向后兼容）
     * @param {Object} options - 配置选项
     * @returns {TooltipManager} tooltip实例
     */
    static init(options = {}) {
        const tooltip = new TooltipManager(options);
        return tooltip.init();
    }
}