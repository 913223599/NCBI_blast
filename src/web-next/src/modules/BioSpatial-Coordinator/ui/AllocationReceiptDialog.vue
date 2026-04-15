<script setup lang="ts">
import { computed } from 'vue'
import type { AllocationResult } from '../strategies/SpeciesZoningStrategy'

const props = defineProps<{
  show: boolean
  results: AllocationResult[]
}>()

const emit = defineEmits(['update:show', 'confirm'])

const close = () => emit('update:show', false)

const handleConfirm = () => {
  emit('confirm')
  close()
}

// 统计逻辑分布
const stats = computed(() => {
  const map: Record<string, number> = {}
  props.results.forEach(r => {
    map[r.reason] = (map[r.reason] || 0) + 1
  })
  return map
})

const getReasonClass = (reason: string) => {
  if (reason.includes('聚类')) return 'reason-affinity'
  if (reason.includes('新开辟')) return 'reason-new'
  return 'reason-default'
}
</script>

<template>
  <div v-if="show" class="receipt-overlay" @click.self="close">
    <div class="receipt-panel">
      <!-- 头部：回归专业沉稳 -->
      <div class="receipt-header">
        <div class="header-main">
          <span class="header-line"></span>
          <div class="title-group">
            <h3>样本智能入库建议</h3>
            <span class="subtitle">已依据[种属分区]算法完成存储规划</span>
          </div>
        </div>
        <button class="close-x" @click="close">✕</button>
      </div>

      <div class="receipt-body">
        <!-- 统计摘要：精简为单色背景条 -->
        <div class="summary-bar">
          <div v-for="(count, reason) in stats" :key="reason" class="summary-item">
            <span class="label">{{ reason }}:</span>
            <span class="value">{{ count }}</span>
          </div>
        </div>

        <!-- 表格区域：报表风格 -->
        <div class="table-frame">
          <table class="report-table">
            <thead>
              <tr>
                <th width="25%">样本名称</th>
                <th width="30%">物种 (Species)</th>
                <th width="25%">存储路径</th>
                <th width="10%">格位</th>
                <th width="10%">依据</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in results" :key="item.sampleId">
                <td class="cell-name">{{ item.sampleName }}</td>
                <td class="cell-species">
                  <span class="latin">{{ item.species }}</span>
                </td>
                <td class="cell-path">
                  <span class="path-text">{{ item.allocatedPath.replace(/\//g, ' > ') }}</span>
                </td>
                <td class="cell-pos">
                  <span class="pos-mono">{{ item.positionLabel }}</span>
                </td>
                <td class="cell-reason">
                  <span :class="['tag-reason', getReasonClass(item.reason)]">{{ item.reason }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 底部操作：强化主要操作 -->
      <div class="receipt-footer">
        <div class="sign-hint">请按照回执路径放置样本，点击 [完成摆放] 以记录到数据库。</div>
        <div class="action-group">
          <button class="btn-cancel" @click="close">取消</button>
          <button class="btn-print" title="打印纸质回执清单">
            打印清单
          </button>
          <button class="btn-submit" @click="handleConfirm">
            完成摆放并入库
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.receipt-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.receipt-panel {
  background: #ffffff;
  width: 880px;
  max-width: 95vw;
  max-height: 85vh;
  border-radius: 8px; /* 减小圆角，增强严谨感 */
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.receipt-header {
  padding: 20px 24px;
  background: #1e293b; /* 沉稳的深色 */
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-main {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-line {
  width: 4px;
  height: 32px;
  background: #3b82f6;
  border-radius: 2px;
}

.title-group h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.subtitle {
  font-size: 0.75rem;
  opacity: 0.6;
  font-weight: 400;
}

.close-x {
  background: transparent;
  border: none;
  color: white;
  cursor: pointer;
  opacity: 0.5;
  font-size: 1.2rem;
}

.close-x:hover { opacity: 1; }

.receipt-body {
  flex: 1;
  padding: 20px 24px;
  overflow-y: auto;
  background: #fcfcfc;
}

.summary-bar {
  display: flex;
  gap: 24px;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #f1f5f9;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.summary-item {
  font-size: 0.85rem;
  color: #475569;
}

.summary-item .value {
  font-weight: 700;
  margin-left: 6px;
  color: #1e293b;
}

.table-frame {
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  background: white;
}

.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.report-table th {
  background: #f8fafc;
  padding: 12px 14px;
  text-align: left;
  border-bottom: 2px solid #e2e8f0;
  color: #64748b;
  font-weight: 600;
}

.report-table td {
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}

.cell-name { font-weight: 600; color: #334155; }

.latin { font-style: italic; color: #1e293b; }

.cell-path { font-size: 0.8rem; color: #64748b; }

.pos-mono {
  display: inline-block;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'Consolas', monospace;
  font-weight: 700;
  color: #0f172a;
  border: 1px solid #e2e8f0;
}

.tag-reason {
  font-size: 0.7rem;
  padding: 2px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

.tag-reason.reason-affinity { color: #059669; border: 1px solid #059669; }
.tag-reason.reason-new { color: #d97706; border: 1px solid #d97706; }
.tag-reason.reason-default { color: #2563eb; border: 1px solid #2563eb; }

.receipt-footer {
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sign-hint {
  font-size: 0.8rem;
  color: #94a3b8;
}

.action-group {
  display: flex;
  gap: 12px;
}

button {
  padding: 8px 16px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}

.btn-cancel {
  background: white;
  border: 1px solid #cbd5e1;
  color: #64748b;
}

.btn-cancel:hover { background: #f8fafc; border-color: #94a3b8; }

.btn-print {
  background: #ffffff;
  border: 1px solid #3b82f6;
  color: #3b82f6;
}

.btn-print:hover { background: #eff6ff; }

.btn-submit {
  background: #3b82f6;
  border: 1px solid #3b82f6;
  color: white;
}

.btn-submit:hover { background: #2563eb; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2); }
</style>
