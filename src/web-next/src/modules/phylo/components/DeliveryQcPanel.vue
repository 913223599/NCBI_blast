<script setup lang="ts">
import { computed } from 'vue'
import { useAppStore } from '../../../stores/app'
import { phyloApi } from '../api/phyloApi'
import { usePhyloStore } from '../stores/usePhyloStore'
import PublicationExportCard from './PublicationExportCard.vue'

const emit = defineEmits<{
  (e: 'back-to-refs'): void
}>()

const appStore = useAppStore()
const store = usePhyloStore()

const qc = computed(() => store.currentJob?.qc_report || null)

async function copyText(txt: string, label: string) {
  try {
    await navigator.clipboard.writeText(txt)
    appStore.showNotification(`已复制${label}`, 'success')
  } catch {
    appStore.showNotification('复制失败，请手动选中文本复制', 'warning')
  }
}

function downloadDeliveryZip() {
  if (!store.currentJob) return
  window.open(phyloApi.getExportUrl(store.currentJob.job_id, 'delivery_zip'), '_blank', 'noopener,noreferrer')
}

function downloadItol(filename: string) {
  if (!store.currentJob) return
  window.open(phyloApi.getItolFileUrl(store.currentJob.job_id, filename), '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <div class="phylo-panel">
    <h3 class="panel-title">第 6-8 步：质检清单与交付导出</h3>

    <div v-if="!qc" class="empty-box">
      当前展示的进化树尚未包含噬菌体交付质检报告（请先运行噬菌体 8 步分类流水线）。
    </div>

    <template v-else>
      <div class="overall-banner" :class="`st-${qc.overall_status}`">
        <div>
          <div class="ov-title">综合交付质量状态: {{ qc.overall_status.toUpperCase() }}</div>
          <div class="ov-sub" v-if="qc.best_model">
            最优模型: <b>{{ qc.best_model }}</b>
            <span v-if="qc.best_model_bic !== null"> | BIC: {{ qc.best_model_bic }}</span>
          </div>
        </div>
        <button type="button" class="btn-zip" @click="downloadDeliveryZip()">打包交付 ZIP</button>
      </div>

      <!-- 6 项交付前质检清单 -->
      <div class="qc-list">
        <div v-for="chk in qc.checks" :key="chk.key" class="qc-card">
          <div class="qc-head">
            <span class="qc-title">{{ chk.title }}</span>
            <span class="qc-badge" :class="`badge-${chk.status}`">{{ chk.status.toUpperCase() }}</span>
          </div>
          <div class="qc-obs">{{ chk.observed }}</div>
          <div class="qc-exp">{{ chk.explanation }}</div>
        </div>
      </div>

      <!-- 如果 ANI 与树冲突或存在警告，支持一键退回调整参考集 -->
      <button
        type="button"
        v-if="!qc.ani_tree_consistent || qc.overall_status !== 'pass'"
        class="btn-recheck"
        @click="emit('back-to-refs')"
      >
        返回第 2 步调整参考集 / 外群重跑 (已算比对缓存可复用)
      </button>

      <!-- 规范学术表述 -->
      <div class="statement-box">
        <div class="st-head">
          <span>ICTV 规范分类结论草稿 (中文)</span>
          <button type="button" class="btn-mini" @click="copyText(qc.conclusion_zh, '中文结论')">复制</button>
        </div>
        <div class="st-text">{{ qc.conclusion_zh }}</div>

        <div class="st-head" style="margin-top: 8px">
          <span>Manuscript Statement (English)</span>
          <button type="button" class="btn-mini" @click="copyText(qc.conclusion_en, '英文结论')">Copy</button>
        </div>
        <div class="st-text">{{ qc.conclusion_en }}</div>
      </div>

      <!-- 方案 C 离线出版级矢量图 + 方案 B 官方 iTOL 免费联动 -->
      <PublicationExportCard />

      <!-- iTOL 注释模板逐项下载 -->
      <div v-if="qc.itol_files.length" class="itol-box">
        <div class="st-head">
          <span>iTOL 注释模板文件 (可直接拖入 iTOL 上传区)</span>
        </div>
        <div class="itol-grid">
          <button
            type="button"
            v-for="fname in qc.itol_files"
            :key="fname"
            class="btn-itol"
            @click="downloadItol(fname)"
          >
            {{ fname }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 10px; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.empty-box { text-align: center; padding: 20px 12px; font-size: 11px; color: #94a3b8; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; }
.overall-banner { display: flex; justify-content: space-between; align-items: center; padding: 10px; border-radius: 8px; border: 1px solid; }
.st-pass { background: #f0fdf4; border-color: #bbf7d0; color: #14532d; }
.st-warn { background: #fffbeb; border-color: #fde68a; color: #78350f; }
.st-fail { background: #fef2f2; border-color: #fecaca; color: #7f1d1d; }
.ov-title { font-size: 12px; font-weight: 700; }
.ov-sub { font-size: 10px; margin-top: 2px; }
.btn-zip { border: none; border-radius: 6px; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; padding: 6px 10px; cursor: pointer; white-space: nowrap; }
.qc-list { display: flex; flex-direction: column; gap: 6px; }
.qc-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; padding: 7px 9px; display: flex; flex-direction: column; gap: 3px; }
.qc-head { display: flex; justify-content: space-between; align-items: center; }
.qc-title { font-size: 11px; font-weight: 700; color: #0f172a; }
.qc-badge { font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 999px; }
.badge-pass { background: #dcfce7; color: #166534; }
.badge-warn { background: #fef3c7; color: #92400e; }
.badge-fail { background: #fee2e2; color: #991b1b; }
.qc-obs { font-size: 10px; font-weight: 600; color: #334155; font-family: monospace; }
.qc-exp { font-size: 10px; color: #64748b; line-height: 1.4; }
.btn-recheck { width: 100%; padding: 7px; border: 1px solid #f59e0b; border-radius: 6px; background: #fffbeb; color: #b45309; font-size: 11px; font-weight: 700; cursor: pointer; }
.statement-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px; display: flex; flex-direction: column; gap: 4px; }
.st-head { display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 700; color: #334155; }
.btn-mini { border: 1px solid #cbd5e1; background: #fff; border-radius: 4px; font-size: 10px; padding: 1px 6px; cursor: pointer; color: #2563eb; }
.st-text { font-size: 11px; color: #1e293b; line-height: 1.5; background: #fff; border: 1px solid #e2e8f0; border-radius: 5px; padding: 6px; user-select: text; }
.itol-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px; display: flex; flex-direction: column; gap: 6px; }
.itol-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.btn-itol { padding: 5px 6px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; color: #1e293b; font-size: 10px; font-family: monospace; cursor: pointer; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.btn-itol:hover { border-color: #3b82f6; color: #1d4ed8; background: #eff6ff; }
</style>
