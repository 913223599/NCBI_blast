<script setup lang="ts">
import { usePhyloStore } from '../stores/usePhyloStore'
import type { PhyloJobRecord } from '../types/phylo'

const store = usePhyloStore()

function selectJob(job: PhyloJobRecord) {
  if (job.newick) {
    store.loadNewickIntoViewer(job.newick, job)
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    running: '运行中',
    pending: '排队中',
    cancelled: '已终止',
    failed: '失败',
  }
  return map[status] || status
}
</script>

<template>
  <div class="phylo-panel">
    <div class="panel-header">
      <h3 class="panel-title">分析历史记录 ({{ store.historyJobs.length }})</h3>
      <button type="button" class="btn-link" @click="store.refreshHistory()">刷新</button>
    </div>

    <div v-if="store.historyJobs.length === 0" class="empty-hint">
      暂无历史分析记录
    </div>

    <div class="history-list">
      <div
        v-for="job in store.historyJobs"
        :key="job.job_id"
        class="history-card"
        :class="{ active: store.currentJob?.job_id === job.job_id }"
        @click="selectJob(job)"
      >
        <div class="h-top">
          <span class="h-title" :title="job.title">{{ job.title }}</span>
          <span class="h-status" :class="job.status">{{ statusLabel(job.status) }}</span>
        </div>

        <div class="h-meta">
          <span>{{ job.resolved_track === 'genome' ? 'Mash 全基因组' : job.config.msa.toUpperCase() }}</span>
          <span>/</span>
          <span>{{ job.config.engine.toUpperCase() }}</span>
          <span>({{ job.config.model }})</span>
          <span v-if="job.metrics">· {{ job.metrics.leaf_count }} 叶</span>
          <span>· {{ job.elapsed_sec.toFixed(1) }}s</span>
        </div>

        <div class="h-footer">
          <span class="h-time">{{ new Date(job.created_at * 1000).toLocaleString() }}</span>
          <div class="h-actions" @click.stop>
            <button type="button" class="btn-mini" @click="store.applyConfigFromJob(job)">复用参数</button>
            <button type="button" class="btn-mini danger" @click="store.deleteHistoryJob(job.job_id)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 10px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.btn-link { background: none; border: none; color: #2563eb; font-size: 12px; cursor: pointer; font-weight: 600; }
.empty-hint { font-size: 12px; color: #94a3b8; text-align: center; padding: 24px 0; background: #f8fafc; border-radius: 8px; }
.history-list { display: flex; flex-direction: column; gap: 8px; }
.history-card { border: 1px solid #e2e8f0; background: #f8fafc; border-radius: 8px; padding: 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; transition: border-color 0.15s, background 0.15s; }
.history-card:hover { border-color: #93c5fd; background: #ffffff; }
.history-card.active { border-color: #2563eb; background: #eff6ff; }
.h-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.h-title { font-size: 12px; font-weight: 700; color: #0f172a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h-status { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 999px; }
.h-status.completed { background: #dcfce7; color: #166534; }
.h-status.failed { background: #fee2e2; color: #991b1b; }
.h-status.cancelled { background: #fef3c7; color: #92400e; }
.h-status.running, .h-status.pending { background: #dbeafe; color: #1e40af; }
.h-meta { font-size: 11px; color: #475569; display: flex; flex-wrap: wrap; gap: 4px; }
.h-footer { display: flex; justify-content: space-between; align-items: center; }
.h-time { font-size: 10px; color: #94a3b8; }
.h-actions { display: flex; gap: 6px; }
.btn-mini { border: 1px solid #cbd5e1; background: #fff; color: #334155; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 600; cursor: pointer; }
.btn-mini.danger { color: #dc2626; border-color: #fecaca; }
</style>
