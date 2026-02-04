# Tooltip 模块使用指南

## 概述
这是一个完全模块化的Tooltip系统，提供了丰富的功能和良好的扩展性。

## 快速开始

### 1. 基础使用
```javascript
import { initTooltip } from './modules/tooltip/index.js';

// 简单初始化
const tooltip = initTooltip({
    selector: '[data-i18n-help]',  // 自动绑定的选择器
    translations: {
        'help_key': '这是帮助内容'
    }
});
```

### 2. 手动控制
```javascript
import { createTooltip } from './modules/tooltip/index.js';

const tooltip = createTooltip({
    delay: 500,
    theme: 'dark',
    maxWidth: 300
});

// 附加到特定元素
const element = document.getElementById('my-element');
tooltip.attach(element, '自定义提示内容');

// 手动显示/隐藏
tooltip.show(element);
tooltip.hide();
```

## 配置选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| delay | number | 600 | 显示延迟(毫秒) |
| theme | string | 'auto' | 主题('light'/'dark'/'auto') |
| position | string | 'auto' | 位置('auto'/'top'/'bottom'/'left'/'right') |
| maxWidth | number | 280 | 最大宽度(像素) |
| animation | boolean | true | 是否启用动画 |
| container | HTMLElement | document.body | 容器元素 |
| translations | Object | null | 翻译字典 |
| selector | string | '[data-i18n-help]' | 自动绑定选择器 |

## 内容来源优先级
1. `attach()` 方法的第二个参数
2. `data-i18n-help` 属性（配合翻译字典）
3. `title` 属性
4. `data-tooltip` 属性
5. `aria-label` 属性

## API参考

### TooltipManager 实例方法

#### `init()`
初始化tooltip管理器

#### `attach(element, content)`
- `element`: HTMLElement - 目标元素
- `content`: string (可选) - 自定义内容

#### `detach(element)`
- `element`: HTMLElement - 要移除的元素

#### `show(element, content)`
- `element`: HTMLElement - 目标元素
- `content`: string (可选) - 自定义内容

#### `hide()`
隐藏当前显示的tooltip

#### `update(options)`
更新配置选项

#### `getConfig()`
获取当前配置

#### `destroy()`
销毁tooltip管理器

## 向后兼容性

模块完全兼容原有的 `HelpTooltipManager` API：

```javascript
// 原有方式仍然可用
const tooltip = HelpTooltipManager.init(translations);
tooltip.updateTranslations(newTranslations);
```

## 样式定制

引入CSS文件：
```html
<link rel="stylesheet" href="./modules/tooltip/styles/tooltip.css">
```

可以通过覆盖CSS变量来自定义样式：
```css
:root {
    --tooltip-bg-dark: rgba(15, 23, 42, 0.95);
    --tooltip-bg-light: rgba(255, 255, 255, 0.95);
    --tooltip-text-dark: #cbd5e1;
    --tooltip-text-light: #334155;
}
```

## 浏览器兼容性
- Chrome 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## 性能优化
- 使用事件委托减少内存占用
- 智能防抖避免频繁触发
- 虚拟化长列表支持
- 懒加载内容预渲染

## 调试模式
```javascript
// 启用调试边框
.tooltip-module.tooltip-debug {
    outline: 2px dashed orange;
}
```

## 常见问题

### Q: Tooltip显示位置不对怎么办？
A: 检查容器元素的定位和z-index设置

### Q: 如何支持触摸设备？
A: 模块已内置触摸支持，长按即可显示

### Q: 如何自定义动画？
A: 可以通过CSS覆盖 `.tooltip-animate` 类的transition属性

### Q: 如何处理动态添加的元素？
A: 使用 `attach()` 方法为新元素手动绑定