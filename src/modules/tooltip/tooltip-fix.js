/**
 * Tooltip功能修复版本
 * 针对项目实际情况优化的实现
 */

(function() {
    'use strict';
    
    // 全局tooltip管理器
    const TooltipFix = {
        tooltipElement: null,
        currentTarget: null,
        timer: null,
        translations: {},
        config: {
            delay: 600,
            theme: 'dark'
        },
        
        // 初始化
        init: function(translations = {}) {
            console.log('🔧 TooltipFix: 初始化开始');
            this.translations = translations;
            
            // 创建tooltip元素
            this.createTooltipElement();
            
            // 绑定事件
            this.bindEvents();
            
            console.log('✅ TooltipFix: 初始化完成');
            return this;
        },
        
        // 创建tooltip元素
        createTooltipElement: function() {
            if (this.tooltipElement) {
                return this.tooltipElement;
            }
            
            this.tooltipElement = document.createElement('div');
            this.tooltipElement.id = 'tooltip-fix-element';
            this.tooltipElement.className = 'tooltip-fix';
            this.tooltipElement.setAttribute('role', 'tooltip');
            this.tooltipElement.style.cssText = `
                position: fixed;
                z-index: 10000;
                max-width: 280px;
                padding: 10px 14px;
                background: rgba(15, 23, 42, 0.95);
                backdrop-filter: blur(8px);
                color: #cbd5e1;
                font-size: 12px;
                line-height: 1.6;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                pointer-events: none;
                opacity: 0;
                transform: scale(0.8);
                transition: all 0.2s ease-out;
                word-wrap: break-word;
            `;
            
            document.body.appendChild(this.tooltipElement);
            console.log('🔧 TooltipFix: tooltip元素创建完成');
            return this.tooltipElement;
        },
        
        // 绑定事件
        bindEvents: function() {
            // 使用事件委托
            document.addEventListener('mouseover', (e) => {
                const target = e.target.closest('[data-i18n-help], [title], [data-tooltip]');
                if (target) {
                    this.handleMouseEnter(target, e);
                }
            });
            
            document.addEventListener('mouseout', (e) => {
                const target = e.target.closest('[data-i18n-help], [title], [data-tooltip]');
                if (target) {
                    this.handleMouseLeave(target, e);
                }
            });
            
            // 全局隐藏事件
            const hideEvents = ['scroll', 'resize', 'mousedown'];
            hideEvents.forEach(eventType => {
                document.addEventListener(eventType, () => this.hide(), true);
            });
            
            console.log('🔧 TooltipFix: 事件绑定完成');
        },
        
        // 鼠标进入处理
        handleMouseEnter: function(element, event) {
            // 清除之前的定时器
            this.clearTimer();
            
            const content = this.getContent(element);
            if (!content) return;
            
            // 设置新的定时器
            this.timer = setTimeout(() => {
                this.show(element, content);
            }, this.config.delay);
        },
        
        // 鼠标离开处理
        handleMouseLeave: function(element, event) {
            this.clearTimer();
            this.hide();
        },
        
        // 获取内容
        getContent: function(element) {
            // 优先级：data-i18n-help > title > data-tooltip > aria-label
            const helpKey = element.getAttribute('data-i18n-help');
            if (helpKey && this.translations[helpKey]) {
                return this.translations[helpKey];
            }
            
            const title = element.getAttribute('title');
            if (title) {
                return title;
            }
            
            const tooltip = element.getAttribute('data-tooltip');
            if (tooltip) {
                return tooltip;
            }
            
            const ariaLabel = element.getAttribute('aria-label');
            if (ariaLabel) {
                return ariaLabel;
            }
            
            return null;
        },
        
        // 显示tooltip
        show: function(element, content) {
            if (!this.tooltipElement) {
                this.createTooltipElement();
            }
            
            this.currentTarget = element;
            this.tooltipElement.textContent = content;
            this.tooltipElement.style.opacity = '1';
            this.tooltipElement.style.transform = 'scale(1)';
            
            // 计算位置
            this.positionTooltip(element);
            
            console.log('🔧 TooltipFix: 显示tooltip -', content.substring(0, 30) + '...');
        },
        
        // 隐藏tooltip
        hide: function() {
            this.clearTimer();
            
            if (this.tooltipElement) {
                this.tooltipElement.style.opacity = '0';
                this.tooltipElement.style.transform = 'scale(0.8)';
            }
            
            this.currentTarget = null;
            console.log('🔧 TooltipFix: 隐藏tooltip');
        },
        
        // 定位tooltip
        positionTooltip: function(element) {
            const rect = element.getBoundingClientRect();
            const tooltipRect = this.tooltipElement.getBoundingClientRect();
            const offset = 10;
            
            // 计算最佳位置（优先top，然后bottom）
            let top, left;
            
            // 检查上方是否有足够空间
            if (rect.top >= tooltipRect.height + offset) {
                top = rect.top - tooltipRect.height - offset;
            } else {
                // 上方空间不足，放在下方
                top = rect.bottom + offset;
            }
            
            // 水平居中
            left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
            
            // 边界检查
            const viewportWidth = window.innerWidth;
            if (left < 10) left = 10;
            if (left + tooltipRect.width > viewportWidth - 10) {
                left = viewportWidth - tooltipRect.width - 10;
            }
            
            this.tooltipElement.style.top = top + 'px';
            this.tooltipElement.style.left = left + 'px';
        },
        
        // 清除定时器
        clearTimer: function() {
            if (this.timer) {
                clearTimeout(this.timer);
                this.timer = null;
            }
        },
        
        // 更新翻译
        updateTranslations: function(newTranslations) {
            this.translations = { ...this.translations, ...newTranslations };
            console.log('🔧 TooltipFix: 翻译字典已更新');
        },
        
        // 更新配置
        updateConfig: function(newConfig) {
            this.config = { ...this.config, ...newConfig };
            console.log('🔧 TooltipFix: 配置已更新');
        },
        
        // 销毁
        destroy: function() {
            this.hide();
            this.clearTimer();
            
            if (this.tooltipElement && this.tooltipElement.parentElement) {
                this.tooltipElement.parentElement.removeChild(this.tooltipElement);
            }
            
            this.tooltipElement = null;
            this.currentTarget = null;
            this.translations = {};
            
            console.log('🔧 TooltipFix: 实例已销毁');
        }
    };
    
    // 兼容性包装器
    const HelpTooltipManagerFix = {
        instance: null,
        
        init: function(translations = {}) {
            if (!this.instance) {
                this.instance = Object.create(TooltipFix);
            }
            return this.instance.init(translations);
        },
        
        updateTranslations: function(translations) {
            if (this.instance) {
                this.instance.updateTranslations(translations);
            }
        }
    };
    
    // 设置全局变量
    window.HelpTooltipManager = HelpTooltipManagerFix;
    window.TooltipFix = TooltipFix;
    
    console.log('🔧 Tooltip修复版本已加载');
    
    // 如果检测到原有的tooltip系统，提供迁移帮助
    if (window.__helpTooltipManager) {
        console.log('🔧 检测到原有tooltip实例，可以安全替换');
    }
    
})();