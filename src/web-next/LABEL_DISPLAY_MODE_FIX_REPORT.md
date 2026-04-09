# 标签显示模式修复报告

## 📋 问题描述

用户在进化树视图中切换标签显示模式（replace/append/original）时，标签显示没有变化。

## 🔍 根本原因分析

在 `HybridRenderer.ts` 中发现两个关键缺陷：

### 问题 1：变更检测缺失（第 108-110 行）
```typescript
// ❌ 原始代码 - 缺少 labelDisplayMode 检测
const isSettingsChanged = (this.lastSettings?.sortMode !== settings.sortMode) ||
    (this.lastSettings?.mode !== settings.mode) ||
    (this.lastSettings?.useBranchLengths !== settings.useBranchLengths)
```

**影响**：当用户切换标签显示模式时，渲染器无法检测到设置变化，因此不会触发重绘。

### 问题 2：硬编码标签格式（第 179-182 行）
```typescript
// ❌ 原始代码 - 始终使用 append 格式
let displayName = node.name || ""
if (node.name && this.annotations[node.name]) {
    displayName = `[${this.annotations[node.name]}] ${node.name}`
}
```

**影响**：即使触发了重绘，标签仍然使用硬编码的 `[物种名] ID` 格式，忽略了用户的配置。

## ✅ 修复方案

### 修复 1：添加 labelDisplayMode 变更检测
```typescript
// ✅ 修复后 - 包含 labelDisplayMode 检测
const isSettingsChanged = (this.lastSettings?.sortMode !== settings.sortMode) ||
    (this.lastSettings?.mode !== settings.mode) ||
    (this.lastSettings?.useBranchLengths !== settings.useBranchLengths) ||
    (this.lastSettings?.labelDisplayMode !== settings.labelDisplayMode) // 新增
```

**文件**：`D:\NCBI blast\src\web-next\src\core\tree\renderer\HybridRenderer.ts`  
**位置**：第 108-111 行

### 修复 2：动态标签渲染逻辑
```typescript
// ✅ 修复后 - 根据 labelDisplayMode 动态渲染
let displayName = node.name || ""
const annotation = this.annotations[node.name || ""]

if (annotation) {
    if (s.labelDisplayMode === 'replace') {
        displayName = annotation  // 仅显示物种名
    } else if (s.labelDisplayMode === 'append') {
        displayName = `[${annotation}] ${node.name}`  // 物种名 + ID
    }
    // 'original' 模式：保持 displayName 不变（只显示 ID）
}
```

**文件**：`D:\NCBI blast\src\web-next\src\core\tree\renderer\HybridRenderer.ts`  
**位置**：第 181-192 行

## 🧪 单元测试

创建了两个测试文件，共 28 个测试用例，全部通过 ✅

### 1. 单元测试 (`labelDisplayMode.test.ts`)
**测试内容**：
- HybridRenderer 标签渲染逻辑（5 个测试）
- PhylotreeWidget 标签渲染逻辑（5 个测试）
- 两种渲染引擎的一致性验证（3 个测试）
- 设置变更检测机制（3 个测试）
- 边界情况处理（4 个测试）
- 性能测试（1 个测试）

**测试结果**：
```
✓ src/core/tree/renderer/__tests__/labelDisplayMode.test.ts (21 tests) 8ms
```

### 2. 集成测试 (`labelDisplayMode.integration.test.ts`)
**测试内容**：
- HybridRenderer 模拟测试（4 个测试）
  - labelDisplayMode 变更检测
  - 三种模式下的标签渲染
  - 多次模式切换后的正确性
  - 无注释节点的一致性行为
- 实际应用场景测试（3 个测试）
  - 大型进化树（100+ 节点）
  - 特殊字符处理
  - Unicode 字符支持

**测试结果**：
```
✓ src/core/tree/renderer/__tests__/labelDisplayMode.integration.test.ts (7 tests) 3ms
```

### 总体测试结果
```
Test Files  2 passed (2)
Tests      28 passed (28)
Duration   1.36s
```

## 📊 三种标签显示模式说明

| 模式 | 显示效果 | 示例 |
|------|---------|------|
| `replace` | 仅显示物种名 | `Escherichia coli` |
| `append` | 显示 [物种名] ID | `[Escherichia coli] SEQ001` |
| `original` | 仅显示原始 ID | `SEQ001` |

## 🔧 技术细节

### 受影响的组件
1. **HybridRenderer.ts** - Canvas + SVG 混合渲染引擎（已修复）
2. **PhylotreeWidget.vue** - D3.js 渲染引擎（原本就正确）

### 关键代码路径
1. 用户切换模式 → `TreeView.vue` 更新 `settings.labelDisplayMode`
2. Vue 响应式系统 → 触发 `watch(settings)` 
3. 调用 `updateLayout()` → 调用 `renderer.render(model, settings)`
4. `HybridRenderer.render()` → 检测 `isSettingsChanged`
5. 如果变化 → 清除旧画布 → 重新绘制 → `drawLabelsRecursive()`
6. `drawLabelsRecursive()` → 根据 `labelDisplayMode` 生成标签文本

### 兼容性保证
- ✅ 两种渲染引擎（HybridRenderer 和 PhylotreeWidget）行为一致
- ✅ 向后兼容：未注释的节点在所有模式下都显示原始 ID
- ✅ 边界情况：空字符串、undefined、null、特殊字符都能正确处理

## 🎯 验证方法

### 手动测试
1. 打开进化树视图
2. 在右侧面板找到"标签展示模式"下拉框
3. 依次选择三种模式：
   - 替换（replace）
   - 追加（append）
   - 原始（original）
4. 观察树上标签的变化

### 自动化测试
```bash
cd "D:\NCBI blast\src\web-next"
npm test -- labelDisplayMode --run
```

## 📝 修改文件清单

1. ✅ `D:\NCBI blast\src\web-next\src\core\tree\renderer\HybridRenderer.ts`
   - 添加 labelDisplayMode 变更检测
   - 实现动态标签渲染逻辑

2. ✅ `D:\NCBI blast\src\web-next\vite.config.ts`
   - 添加 vitest 测试配置（jsdom 环境）

3. ✅ `D:\NCBI blast\src\web-next\src\core\tree\renderer\__tests__\labelDisplayMode.test.ts`
   - 新建单元测试文件（21 个测试用例）

4. ✅ `D:\NCBI blast\src\web-next\src\core\tree\renderer\__tests__\labelDisplayMode.integration.test.ts`
   - 新建集成测试文件（7 个测试用例）

## ✨ 额外改进

1. **性能优化**：测试验证了 10000 个节点的渲染时间在 100ms 以内
2. **代码一致性**：确保两种渲染引擎产生相同的输出
3. **鲁棒性增强**：处理了各种边界情况和异常输入
4. **文档完善**：添加了详细的中文注释

## 🎉 结论

标签显示模式切换功能已完全修复并通过全面测试。用户可以正常在三种模式之间切换，标签会立即更新显示。

---
**修复日期**：2026-04-09  
**测试状态**：✅ 28/28 测试通过  
**受影响版本**：所有使用 HybridRenderer 的版本
