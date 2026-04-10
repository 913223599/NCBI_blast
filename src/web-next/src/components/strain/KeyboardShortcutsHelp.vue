<template>
  <div class="shortcuts-help" v-if="visible">
    <div class="help-panel">
      <div class="help-header">
        <h3>⌨️ 快捷键帮助</h3>
        <button class="close-btn" @click="$emit('close')">✕</button>
      </div>
      <div class="help-content">
        <div class="shortcut-group">
          <h4>全局快捷键</h4>
          <div class="shortcut-item">
            <span class="keys"><kbd>Ctrl</kbd> + <kbd>N</kbd></span>
            <span class="desc">添加新冰箱</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>Ctrl</kbd> + <kbd>I</kbd></span>
            <span class="desc">批量导入样本</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>Ctrl</kbd> + <kbd>S</kbd></span>
            <span class="desc">保存数据（自动）</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>Esc</kbd></span>
            <span class="desc">关闭对话框</span>
          </div>
        </div>

        <div class="shortcut-group">
          <h4>导航快捷键</h4>
          <div class="shortcut-item">
            <span class="keys"><kbd>1</kbd></span>
            <span class="desc">切换到冰箱详情视图</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>2</kbd></span>
            <span class="desc">切换到 3D 视图</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>3</kbd></span>
            <span class="desc">切换到统计分析</span>
          </div>
        </div>

        <div class="shortcut-group">
          <h4>操作快捷键</h4>
          <div class="shortcut-item">
            <span class="keys"><kbd>Enter</kbd></span>
            <span class="desc">确认/录入样本</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>Delete</kbd></span>
            <span class="desc">删除选中项</span>
          </div>
          <div class="shortcut-item">
            <span class="keys"><kbd>Space</kbd></span>
            <span class="desc">切换占用状态</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
}>()

defineEmits(['close'])
</script>

<style scoped>
.shortcuts-help {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.help-panel {
  background: white;
  border-radius: 16px;
  max-width: 600px;
  width: 90%;
  max-height: 80vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.help-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.help-header h3 {
  margin: 0;
  font-size: 1.2rem;
  color: #1e293b;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.help-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.shortcut-group {
  margin-bottom: 24px;
}

.shortcut-group:last-child {
  margin-bottom: 0;
}

.shortcut-group h4 {
  font-size: 0.9rem;
  font-weight: 700;
  color: #2563eb;
  margin: 0 0 12px 0;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.shortcut-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  margin-bottom: 8px;
}

.shortcut-item:last-child {
  margin-bottom: 0;
}

.keys {
  display: flex;
  gap: 4px;
  align-items: center;
}

kbd {
  display: inline-block;
  padding: 4px 8px;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
  font-weight: 700;
  color: #475569;
  box-shadow: 0 2px 0 #cbd5e1;
  min-width: 24px;
  text-align: center;
}

.desc {
  font-size: 0.85rem;
  color: #64748b;
}
</style>
