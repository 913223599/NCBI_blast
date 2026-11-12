<script setup lang="ts">
/**
 * SangonIgnoreModal - 生工 16S 全局忽略规则与主题关键词配置弹窗
 * 职责：
 * 1. 展示并管理全局忽略订单号列表（单条取消忽略、批量粘贴添加、附带备注）；
 * 2. 展示并保存非测序通知邮件主题过滤关键词（同步持久化至 sangon_16s_config.json）。
 */
import { ref, computed, watch } from 'vue'
import type { IgnoredOrderRule } from '../sangonTypes'

const props = defineProps<{
  visible: boolean
  ignoredOrders: Record<string, IgnoredOrderRule>
  ignoreKeywords: string[]
  ignoredDownloadCount: number
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'addIgnore', payload: { orderKeys: string[]; reason: string }): void
  (e: 'unignore', orderKey: string): void
  (e: 'saveKeywords', keywords: string[]): void
}>()

const batchOrderInput = ref('')
const batchReasonInput = ref('')
const keywordsInput = ref('')

watch(
  () => props.visible,
  (open) => {
    if (open) {
      batchOrderInput.value = ''
      batchReasonInput.value = ''
      keywordsInput.value = (props.ignoreKeywords || []).join(', ')
    }
  }
)

const ignoredList = computed(() => {
  const entries = Object.values(props.ignoredOrders || {})
  return entries.sort((a, b) => (b.ignored_at || '').localeCompare(a.ignored_at || '') || a.order_no.localeCompare(b.order_no))
})

function handleBatchAdd(): void {
  const tokens = batchOrderInput.value
    .split(/[\s,，;；]+/)
    .map(s => s.trim())
    .filter(Boolean)
  if (!tokens.length) return
  emit('addIgnore', {
    orderKeys: tokens,
    reason: batchReasonInput.value.trim()
  })
  batchOrderInput.value = ''
  batchReasonInput.value = ''
}

function handleSaveKeywords(): void {
  const kws = keywordsInput.value
    .split(/[,，;；\n]+/)
    .map(s => s.trim())
    .filter(Boolean)
  emit('saveKeywords', kws)
}
</script>

<template>
  <div v-if="visible" class="modal-backdrop" @click.self="emit('close')">
    <div class="modal-card wide">
      <div class="modal-header">
        <h3>跳过与忽略规则配置</h3>
        <button class="close-btn" @click="emit('close')">&times;</button>
      </div>

      <div class="modal-body">
        <p class="rule-desc">
          按 10 位订单号全局跳过：被忽略的订单会移入「已忽略」标签页隐藏，不计入待处理任务、不触发下载目录待认领提醒、扫描新邮件时也不会自动建目录（本地文件与下载包均安全保留不删除）。
        </p>

        <!-- 批量新增忽略 -->
        <div class="section-block">
          <div class="section-title">添加忽略订单号（支持粘贴多个订单号或目录名，逗号/空格/换行分隔）</div>
          <div class="add-grid">
            <textarea
              v-model="batchOrderInput"
              rows="2"
              placeholder="例如：2140608938, 20260919_2140601771"
              class="text-area mono"
            ></textarea>
            <div class="add-row">
              <input
                v-model="batchReasonInput"
                type="text"
                placeholder="忽略原因备注（可选，例如：线下已比对 / 废单）"
                class="text-input"
              />
              <button
                class="btn-primary"
                :disabled="busy || !batchOrderInput.trim()"
                @click="handleBatchAdd"
              >
                加入忽略名单
              </button>
            </div>
          </div>
        </div>

        <!-- 当前已忽略清单 -->
        <div class="section-block">
          <div class="section-header-row">
            <span class="section-title">
              当前已忽略订单（{{ ignoredList.length }}）
              <template v-if="ignoredDownloadCount > 0"> · 其中 {{ ignoredDownloadCount }} 个存在下载目录旧压缩包已静默</template>
            </span>
          </div>
          <div class="ignored-list-scroll">
            <table class="mini-table">
              <thead>
                <tr>
                  <th>订单号</th>
                  <th>关联目录</th>
                  <th>忽略原因</th>
                  <th>添加时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in ignoredList" :key="item.order_no">
                  <td class="mono">{{ item.order_no }}</td>
                  <td class="mono muted">{{ item.dir_name || '-' }}</td>
                  <td>{{ item.reason || '-' }}</td>
                  <td class="muted">{{ item.ignored_at || '-' }}</td>
                  <td>
                    <button
                      class="btn-mini"
                      :disabled="busy"
                      @click="emit('unignore', item.order_no)"
                    >
                      取消忽略
                    </button>
                  </td>
                </tr>
                <tr v-if="ignoredList.length === 0">
                  <td colspan="5" class="empty-cell">暂无全局忽略的订单条目</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 非测序通知邮件主题关键词 -->
        <div class="section-block">
          <div class="section-title">非测序通知邮件过滤关键词（主题不含“测序”且命中任一关键词时跳过，逗号分隔）</div>
          <div class="add-row">
            <input
              v-model="keywordsInput"
              type="text"
              placeholder="已发货, 物流, 快递, 发票, 对账, 付款"
              class="text-input"
            />
            <button class="btn-outline" :disabled="busy" @click="handleSaveKeywords">
              保存关键词
            </button>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn-outline" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card.wide {
  background: white;
  border-radius: 12px;
  width: 680px;
  max-width: 94vw;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
}
.modal-header h3 { margin: 0; font-size: 15px; color: #0f172a; }
.close-btn { background: none; border: none; font-size: 20px; cursor: pointer; color: #64748b; }

.modal-body {
  padding: 16px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rule-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
}

.section-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}

.add-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.add-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.text-area, .text-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #0f172a;
}
.text-area { resize: vertical; }
.mono { font-family: Consolas, monospace; }
.muted { color: #64748b; }

.ignored-list-scroll {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.mini-table th {
  text-align: left;
  padding: 8px 10px;
  background: #f8fafc;
  color: #475569;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
}
.mini-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}
.empty-cell {
  text-align: center;
  color: #94a3b8;
  padding: 18px !important;
}

.btn-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-outline {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.btn-outline:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
  color: #334155;
}
.btn-mini:hover:not(:disabled) { background: #eff6ff; color: #2563eb; border-color: #93c5fd; }

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
}
</style>

