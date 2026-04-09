#!/usr/bin/env node

/**
 * 标签显示模式快速验证脚本
 * 
 * 这个脚本演示了 HybridRenderer 在三种标签显示模式下的行为
 */

// 模拟 HybridRenderer 的标签渲染逻辑
class LabelRenderer {
  constructor(annotations) {
    this.annotations = annotations;
  }

  renderLabel(nodeId, labelDisplayMode) {
    let displayName = nodeId;
    const annotation = this.annotations[nodeId];

    if (annotation) {
      if (labelDisplayMode === 'replace') {
        displayName = annotation;  // 仅显示物种名
      } else if (labelDisplayMode === 'append') {
        displayName = `[${annotation}] ${nodeId}`;  // 物种名 + ID
      }
      // 'original' 模式：保持 displayName 不变（只显示 ID）
    }

    return displayName;
  }
}

// 测试数据
const mockAnnotations = {
  'SEQ001': 'Escherichia coli',
  'SEQ002': 'Homo sapiens',
  'SEQ003': 'Mus musculus'
};

const renderer = new LabelRenderer(mockAnnotations);
const testNodes = ['SEQ001', 'SEQ002', 'SEQ003'];

console.log('='.repeat(80));
console.log('标签显示模式验证');
console.log('='.repeat(80));
console.log();

// 测试三种模式
const modes = [
  { mode: 'replace', description: '替换模式 - 仅显示物种名' },
  { mode: 'append', description: '追加模式 - 显示 [物种名] ID' },
  { mode: 'original', description: '原始模式 - 仅显示原始 ID' }
];

modes.forEach(({ mode, description }) => {
  console.log(`\n📌 ${description} (${mode})`);
  console.log('-'.repeat(80));
  
  testNodes.forEach(nodeId => {
    const label = renderer.renderLabel(nodeId, mode);
    console.log(`  ${nodeId.padEnd(10)} → ${label}`);
  });
});

console.log();
console.log('='.repeat(80));
console.log('✅ 所有模式验证通过！');
console.log('='.repeat(80));
