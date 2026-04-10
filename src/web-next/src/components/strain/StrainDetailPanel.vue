<template>
  <div class="detail-panel-overlay" @click.self="emit('close')">
    <div class="detail-panel">
      <!-- 头部 -->
      <div class="detail-header">
        <h3 class="detail-title">序列详情</h3>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <!-- 内容 -->
      <div class="detail-content">
        <!-- 基本信息 -->
        <div class="info-section">
          <h4 class="section-label">基本信息</h4>
          <div class="info-grid">
            <div class="info-item">
              <label>登录号</label>
              <value>{{ record.accession }}</value>
            </div>
            <div class="info-item">
              <label>名称</label>
              <value>{{ record.name }}</value>
            </div>
            <div class="info-item">
              <label>物种</label>
              <value>{{ record.species }}</value>
            </div>
            <div class="info-item">
              <label>菌株</label>
              <value>{{ record.strain || '-' }}</value>
            </div>
            <div class="info-item">
              <label>序列类型</label>
              <value>
                <span class="type-badge" :class="record.sequenceType.toLowerCase()">
                  {{ record.sequenceType }}
                </span>
              </value>
            </div>
            <div class="info-item">
              <label>来源</label>
              <value>{{ record.source || '-' }}</value>
            </div>
            <div class="info-item">
              <label>宿主</label>
              <value>{{ record.host || '-' }}</value>
            </div>
            <div class="info-item">
              <label>地区</label>
              <value>{{ record.country || '-' }}</value>
            </div>
            <div class="info-item">
              <label>采集日期</label>
              <value>{{ record.collectionDate || '-' }}</value>
            </div>
            <div class="info-item">
              <label>添加时间</label>
              <value>{{ formatDate(record.addedAt) }}</value>
            </div>
          </div>
        </div>

        <!-- 序列信息 -->
        <div class="info-section">
          <h4 class="section-label">序列信息</h4>
          <div class="sequence-display">
            <pre class="sequence-text">{{ record.sequence }}</pre>
            <div class="sequence-stats">
              <span>长度: {{ record.sequence.length }} bp</span>
              <button class="btn-copy" @click="copySequence">📋 复制序列</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="detail-footer">
        <button class="btn-secondary" @click="handleNCBI">
          🌐 在NCBI查看
        </button>
        <button class="btn-danger" @click="handleDelete">
          🗑️ 删除此记录
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

interface Props {
  record: any
}

const props = defineProps<Props>()
const emit = defineEmits(['close'])

const strain = useStrainStore()
const appStore = useAppStore()

function formatDate(isoString: string): string {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function copySequence() {
  navigator.clipboard.writeText(props.record.sequence).then(() => {
    appStore.showNotification('序列已复制到剪贴板', 'success')
  }).catch(() => {
    appStore.showNotification('复制失败', 'error')
  })
}

function handleNCBI() {
  const url = `https://www.ncbi.nlm.nih.gov/nuccore/${props.record.accession}`
  window.open(url, '_blank')
}

function handleDelete() {
  if (window.confirm('确定要删除这条记录吗？')) {
    strain.removeRecord(props.record.id)
    appStore.showNotification('已删除记录', 'success')
    emit('close')
  }
}
</script>

<style scoped>
.detail-panel-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.detail-panel {
  background: white;
  border-radius: 16px;
  width: 90%;
  max-width: 700px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.detail-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.detail-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.info-section {
  margin-bottom: 24px;
}

.section-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 12px 0;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-item label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
}

.info-item value {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
}

.type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.type-badge.dna {
  background: #dbeafe;
  color: #1e40af;
}

.type-badge.rna {
  background: #fce7f3;
  color: #9d174d;
}

.type-badge.protein {
  background: #d1fae5;
  color: #065f46;
}

.sequence-display {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.sequence-text {
  padding: 16px;
  margin: 0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.85rem;
  line-height: 1.6;
  color: #1e293b;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
}

.sequence-stats {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: white;
  border-top: 1px solid #e2e8f0;
}

.sequence-stats span {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 600;
}

.btn-copy {
  padding: 6px 12px;
  background: #f1f5f9;
  border: none;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-copy:hover {
  background: #e2e8f0;
}

.detail-footer {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.btn-secondary,
.btn-danger {
  flex: 1;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-secondary {
  background: #f1f5f9;
  color: #475569;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-danger {
  background: #fee2e2;
  color: #dc2626;
}

.btn-danger:hover {
  background: #fecaca;
}
</style>