<script setup lang="ts">
/**
 * CleanupDialog - 历史数据清理确认弹窗
 * 父组件传入可清理项，确认后回传所选项与时间筛选条件。
 */
import { ref, computed, watch } from 'vue'

export interface CleanupOption {
  key: string
  label: string
  desc?: string
  danger?: boolean
  checked?: boolean
}

const props = defineProps<{
  visible: boolean
  title: string
  subtitle?: string
  options: CleanupOption[]
  showDays?: boolean
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', payload: { targets: string[]; older_than_days: number | null }): void
}>()

const selected = ref<string[]>([])
const olderThanDays = ref<number | null>(null)

watch(() => props.visible, (v) => {
  if (v) {
    selected.value = props.options.filter(o => o.checked).map(o => o.key)
    olderThanDays.value = null
  }
})

const hasDanger = computed(() => props.options.some(o => o.danger && selected.value.includes(o.key)))

function confirm(): void {
  if (!selected.value.length) return
  emit('confirm', {
    targets: [...selected.value],
    older_than_days: olderThanDays.value && olderThanDays.value > 0 ? olderThanDays.value : null
  })
}
</script>

<template>
  <div v-if="visible" class="cd-backdrop" @click.self="emit('close')">
    <div class="cd-card">
      <div class="cd-header">
        <h3>{{ title }}</h3>
        <button class="cd-close" @click="emit('close')">&times;</button>
      </div>
      <div class="cd-body">
        <p v-if="subtitle" class="cd-sub">{{ subtitle }}</p>
        <label v-for="opt in options" :key="opt.key" class="cd-opt" :class="{ danger: opt.danger }">
          <input v-model="selected" type="checkbox" :value="opt.key" />
          <div>
            <div class="cd-opt-label">{{ opt.label }}</div>
            <div v-if="opt.desc" class="cd-opt-desc">{{ opt.desc }}</div>
          </div>
        </label>
        <label v-if="showDays" class="cd-days">
          <span>仅清理早于</span>
          <input v-model.number="olderThanDays" type="number" min="0" placeholder="不限" />
          <span>天的数据（留空为全部）</span>
        </label>
        <div v-if="hasDanger" class="cd-warn">所选项包含不可恢复的删除操作，请确认。</div>
      </div>
      <div class="cd-footer">
        <button class="cd-btn" @click="emit('close')">取消</button>
        <button class="cd-btn danger" :disabled="busy || !selected.length" @click="confirm">
          {{ busy ? '清理中...' : '确认清理' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cd-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.cd-card {
  background: white;
  border-radius: 12px;
  width: 520px;
  max-width: 92vw;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
}

.cd-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.cd-header h3 { margin: 0; font-size: 15px; }
.cd-close { background: none; border: none; font-size: 20px; cursor: pointer; }

.cd-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cd-sub {
  margin: 0;
  font-size: 12px;
  color: #64748b;
}

.cd-opt {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  cursor: pointer;
}

.cd-opt.danger { border-color: #fecaca; background: #fef2f2; }
.cd-opt-label { font-size: 13px; font-weight: 600; color: #1e293b; }
.cd-opt-desc { font-size: 11px; color: #64748b; margin-top: 2px; }

.cd-days {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #334155;
}

.cd-days input {
  width: 70px;
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
}

.cd-warn {
  font-size: 12px;
  color: #b91c1c;
}

.cd-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.cd-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.cd-btn.danger {
  background: #dc2626;
  border-color: #dc2626;
  color: white;
}

.cd-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>

