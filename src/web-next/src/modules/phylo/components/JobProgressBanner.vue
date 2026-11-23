<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { usePhyloStore } from '../stores/usePhyloStore'

const store = usePhyloStore()
const showLogs = ref(false)
const nowSec = ref(Date.now() / 1000)
let timerId: ReturnType<typeof setInterval> | null = null

const liveElapsed = computed(() => {
  const job = store.activeJob
  if (!job) return 0
  const base = job.started_at || job.created_at
  return Math.max(job.elapsed_sec || 0, nowSec.value - base)
})

onMounted(() => {
  timerId = setInterval(() => {
    if (store.activeJob) {
      nowSec.value = Date.now() / 1000
    }
  }, 500)
})

onUnmounted(() => {
  if (timerId) {
    clearInterval(timerId)
    timerId = null
  }
})
</script>

<template>
  <div v-if="store.activeJob" class="job-banner">
    <div class="banner-top">
      <div class="status-left">
        <span class="pulse-dot"></span>
        <div>
          <div class="job-title">{{ store.activeJob.title }}</div>
          <div class="job-msg">{{ store.activeJob.message }} ({{ liveElapsed.toFixed(1) }}s)</div>
        </div>
      </div>

      <div class="banner-actions">
        <button class="btn-log" @click="showLogs = !showLogs">
          {{ showLogs ? '收起日志' : `实时日志 (${store.liveLogs.length})` }}
        </button>
        <button
          class="btn-cancel"
          :disabled="store.isCancelling"
          @click="store.cancelActiveJob()"
        >
          {{ store.isCancelling ? '正在终止...' : '终止任务' }}
        </button>
      </div>
    </div>

    <div class="progress-track">
      <div class="progress-fill" :style="{ width: `${store.activeJob.progress}%` }"></div>
    </div>

    <div class="stage-pills">
      <div
        v-for="st in store.activeJob.stages"
        :key="st.name"
        class="stage-pill"
        :class="st.status"
      >
        <span>{{ st.label }}</span>
        <span v-if="st.cached" class="cache-tag">缓存命中</span>
      </div>
    </div>

    <pre v-if="showLogs" class="log-terminal">{{ store.liveLogs.join('\n') || '等待输出日志...' }}</pre>
  </div>
</template>

<style scoped>
.job-banner { background: #ffffff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 10px 14px; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06); display: flex; flex-direction: column; gap: 8px; }
.banner-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.status-left { display: flex; align-items: center; gap: 10px; }
.pulse-dot { width: 10px; height: 10px; border-radius: 50%; background: #2563eb; animation: pulse 1.2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } }
.job-title { font-size: 13px; font-weight: 700; color: #0f172a; }
.job-msg { font-size: 11px; color: #475569; }
.banner-actions { display: flex; gap: 8px; }
.btn-log { padding: 5px 10px; border: 1px solid #cbd5e1; border-radius: 6px; background: #f8fafc; color: #334155; font-size: 11px; font-weight: 600; cursor: pointer; }
.btn-cancel { padding: 5px 12px; border: none; border-radius: 6px; background: #dc2626; color: #fff; font-size: 11px; font-weight: 700; cursor: pointer; }
.btn-cancel:disabled { background: #fca5a5; cursor: wait; }
.progress-track { width: 100%; height: 6px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
.progress-fill { height: 100%; background: #2563eb; transition: width 0.25s ease; }
.stage-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.stage-pill { font-size: 11px; padding: 3px 8px; border-radius: 6px; border: 1px solid #e2e8f0; background: #f8fafc; color: #64748b; display: inline-flex; align-items: center; gap: 4px; }
.stage-pill.running { border-color: #93c5fd; background: #eff6ff; color: #1d4ed8; font-weight: 600; }
.stage-pill.completed { border-color: #bbf7d0; background: #f0fdf4; color: #15803d; }
.stage-pill.cached { border-color: #a7f3d0; background: #ecfdf5; color: #047857; }
.stage-pill.failed { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.cache-tag { font-size: 9px; background: #059669; color: #fff; padding: 1px 4px; border-radius: 4px; }
.log-terminal { margin: 0; max-height: 180px; overflow-y: auto; background: #0f172a; color: #e2e8f0; padding: 8px 10px; border-radius: 6px; font-size: 11px; line-height: 1.45; white-space: pre-wrap; }
</style>
