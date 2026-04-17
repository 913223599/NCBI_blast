<script setup lang="ts">
import { computed } from 'vue'
import ExcelJS from 'exceljs'
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

/**
 * 核心逻辑：导出一份排版精美的 XLSX 清单
 */
const handleExportManifest = async () => {
  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('入库清单 (Manifest)')

  // 1. 设置表头与列宽
  sheet.columns = [
    { header: '系统编号 (System ID)', key: 'code', width: 25 },
    { header: '样本名称 (Name)', key: 'name', width: 25 },
    { header: '物种 (Species)', key: 'species', width: 30 },
    { header: '存储路径 (Full Path)', key: 'path', width: 45 },
    { header: '格位 (Pos)', key: 'pos', width: 10 }
  ]

  // 2. 填充数据
  props.results.forEach(res => {
    sheet.addRow({
      code: res.record?.sampleCode || '-',
      name: res.sampleName,
      species: res.species,
      path: res.allocatedPath.replace(/\//g, ' > '),
      pos: res.positionLabel
    })
  })

  // 3. 样式美化
  const headerRow = sheet.getRow(1)
  headerRow.font = { bold: true, size: 12, color: { argb: 'FFFFFFFF' } }
  headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1E293B' } } // 深色表头
  headerRow.alignment = { horizontal: 'center', vertical: 'middle' }
  
  sheet.eachRow((row, rowNumber) => {
    row.height = 25 
    row.eachCell((cell) => {
      cell.border = {
        top: { style: 'thin' },
        left: { style: 'thin' },
        bottom: { style: 'thin' },
        right: { style: 'thin' }
      }
      if (rowNumber > 1) {
        cell.alignment = { vertical: 'middle', horizontal: 'left' }
      }
    })
  })

  // 4. 执行文件下载
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `Manifest_${new Date().toISOString().slice(0, 10)}_${props.results.length}pcs.xlsx`
  link.click()
  window.URL.revokeObjectURL(url)
}

// 统计解析
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
      <!-- 头部 -->
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
        <div class="summary-bar">
          <div v-for="(count, reason) in stats" :key="reason" class="summary-item">
            <span class="label">{{ reason }}:</span>
            <span class="value">{{ count }}</span>
          </div>
        </div>

        <div class="table-frame">
          <table class="report-table">
            <thead>
              <tr>
                <th width="15%">系统编号</th>
                <th width="20%">样本名称</th>
                <th width="25%">物种 (Species)</th>
                <th width="30%">存储路径</th>
                <th width="10%">格位</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in results" :key="item.sampleId">
                <td class="cell-code">{{ item.record?.sampleCode || '-' }}</td>
                <td class="cell-name">{{ item.sampleName }}</td>
                <td class="cell-species"><span class="latin">{{ item.species }}</span></td>
                <td class="cell-path"><span class="path-text">{{ item.allocatedPath.replace(/\//g, ' > ') }}</span></td>
                <td class="cell-pos"><span class="pos-mono">{{ item.positionLabel }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="receipt-footer">
        <div class="sign-hint">请保存 [发放清单] 以备实验记录，点击 [确认入库] 完成流程。</div>
        <div class="action-group">
          <button class="btn-cancel" @click="close">取消</button>
          <button class="btn-print" @click="handleExportManifest">
            导出发放清单
          </button>
          <button class="btn-submit" @click="handleConfirm">
            确认入库
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.receipt-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.receipt-panel {
  background: #ffffff;
  width: 920px;
  max-width: 95vw;
  max-height: 85vh;
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(0,0,0,0.15);
  display: flex;
  flex-direction: column;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.receipt-header {
  padding: 20px 24px;
  background: #1e293b;
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-main { display: flex; align-items: center; gap: 16px; }
.header-line { width: 4px; height: 32px; background: #3b82f6; border-radius: 2px; }
.title-group h3 { margin: 0; font-size: 1.1rem; font-weight: 600; }
.subtitle { font-size: 0.75rem; opacity: 0.6; }
.close-x { background: transparent; border: none; color: white; cursor: pointer; font-size: 1.2rem; }

.receipt-body { flex: 1; padding: 24px; overflow-y: auto; background: #fcfcfc; }
.summary-bar { display: flex; gap: 24px; margin-bottom: 20px; padding: 12px 16px; background: #f1f5f9; border-radius: 6px; border: 1px solid #e2e8f0; }
.summary-item { font-size: 0.85rem; color: #475569; }
.summary-item .value { font-weight: 700; margin-left: 6px; color: #1e293b; }

.table-frame { border: 1px solid #e2e8f0; border-radius: 4px; overflow: hidden; background: white; }
.report-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.report-table th { background: #f8fafc; padding: 12px 14px; text-align: left; border-bottom: 2px solid #e2e8f0; color: #64748b; font-weight: 600; }
.report-table td { padding: 12px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }

.cell-code { font-family: 'Consolas', monospace; font-weight: 700; color: #2563eb; font-size: 0.8rem; }
.cell-name { font-weight: 600; color: #334155; }
.latin { font-style: italic; color: #1e293b; }
.cell-path { font-size: 0.8rem; color: #64748b; }
.pos-mono { display: inline-block; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-family: 'Consolas', monospace; font-weight: 700; color: #0f172a; border: 1px solid #e2e8f0; }

.receipt-footer { padding: 16px 24px; border-top: 1px solid #e2e8f0; background: #ffffff; display: flex; justify-content: space-between; align-items: center; }
.sign-hint { font-size: 0.8rem; color: #94a3b8; }
.action-group { display: flex; gap: 12px; }

button { padding: 8px 16px; font-size: 0.85rem; font-weight: 500; cursor: pointer; border-radius: 6px; transition: all 0.2s; }
.btn-cancel { background: white; border: 1px solid #cbd5e1; color: #64748b; }
.btn-cancel:hover { background: #f8fafc; }
.btn-print { background: #ffffff; border: 1px solid #3b82f6; color: #3b82f6; }
.btn-print:hover { background: #eff6ff; }
.btn-submit { background: #3b82f6; border: 1px solid #3b82f6; color: white; }
.btn-submit:hover { background: #2563eb; }
</style>
