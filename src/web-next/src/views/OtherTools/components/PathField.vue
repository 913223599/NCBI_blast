<script setup lang="ts">
/**
 * PathField - 目录路径显示与修改
 * 显示完整路径；修改保存后由父组件调用后端完成迁移。
 */
import { ref, watch } from 'vue'

const props = defineProps<{
  label: string
  path: string
  busy?: boolean
  hint?: string
  saveLabel?: string
}>()

const emit = defineEmits<{
  (e: 'save', value: string): void
  (e: 'open', value: string): void
}>()

const editing = ref(false)
const draft = ref(props.path)

watch(() => props.path, (v) => {
  if (!editing.value) draft.value = v
})

function startEdit(): void {
  draft.value = props.path
  editing.value = true
}

function cancelEdit(): void {
  editing.value = false
  draft.value = props.path
}

function submit(): void {
  const v = draft.value.trim()
  if (!v || v === props.path) {
    cancelEdit()
    return
  }
  emit('save', v)
  editing.value = false
}
</script>

<template>
  <div class="path-field">
    <div class="path-label">{{ label }}</div>
    <div v-if="!editing" class="path-row">
      <code class="path-text" :title="path">{{ path || '-' }}</code>
      <button class="pf-btn" :disabled="busy" @click="startEdit">修改</button>
      <button class="pf-btn" :disabled="!path" @click="emit('open', path)">打开</button>
    </div>
    <div v-else class="path-row">
      <input v-model="draft" class="path-input" type="text" @keyup.enter="submit" @keyup.esc="cancelEdit" />
      <button class="pf-btn primary" :disabled="busy" @click="submit">{{ saveLabel || '保存并迁移' }}</button>
      <button class="pf-btn" @click="cancelEdit">取消</button>
    </div>
    <div v-if="editing" class="path-hint">{{ hint || '保存后旧目录中的数据将自动迁移到新目录，同名文件不覆盖。' }}</div>
  </div>
</template>

<style scoped>
.path-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.path-label {
  font-size: 12px;
  color: #64748b;
}

.path-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.path-text {
  flex: 1;
  min-width: 0;
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #0f172a;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 5px 8px;
  word-break: break-all;
  white-space: normal;
}

.path-input {
  flex: 1;
  min-width: 0;
  font-family: Consolas, monospace;
  font-size: 12px;
  padding: 5px 8px;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  outline: none;
}

.pf-btn {
  flex-shrink: 0;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
}

.pf-btn.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

.pf-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.path-hint {
  font-size: 11px;
  color: #94a3b8;
}
</style>

