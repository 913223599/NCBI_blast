<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { phyloApi } from '../api/phyloApi'
import { usePhyloStore } from '../stores/usePhyloStore'
import type {
  ItolDisplayModeType,
  ItolExportFormatType,
  ItolPullResponse,
  LabelFormatType,
  PublicationFigureItem,
  PublicationLayoutType,
  PublicationSupportStyle,
} from '../types/phylo'

const ITOL_UPLOAD_PAGE_URL = 'https://itol.embl.de/upload.cgi'

const appStore = useAppStore()
const store = usePhyloStore()

const job = computed(() => store.currentJob)

// 方案 C：离线出版级渲染表单状态
const pubLayout = ref<PublicationLayoutType>('circular')
const pubSupportStyle = ref<PublicationSupportStyle>('dots')
const pubLabelFormat = ref<LabelFormatType>('name_acc')
const pubDpi = ref<number>(300)
const showGenusStrip = ref<boolean>(true)
const showGenomeLength = ref<boolean>(true)
const showGcBar = ref<boolean>(true)
const pubLoading = ref<boolean>(false)

// 方案 B：iTOL 免费联动表单状态
const itolTreeInput = ref<string>('')
const itolFormat = ref<ItolExportFormatType>('pdf')
const itolMode = ref<ItolDisplayModeType>('circular')
const itolBootstrap = ref<boolean>(true)
const itolLoading = ref<boolean>(false)

const pubFigures = computed<PublicationFigureItem[]>(() => {
  const raw = job.value?.artifacts?.publication_figures
  return Array.isArray(raw) ? (raw as PublicationFigureItem[]) : []
})

const itolExports = computed<ItolPullResponse[]>(() => {
  const raw = job.value?.artifacts?.itol_exports
  return Array.isArray(raw) ? (raw as ItolPullResponse[]) : []
})

const hasNodeMetadata = computed<boolean>(() => {
  const meta = job.value?.node_metadata
  return Boolean(meta && Object.keys(meta).length > 0)
})

async function refreshCurrentJobArtifacts(jobId: string): Promise<void> {
  try {
    const latest = await phyloApi.getJob(jobId)
    if (store.currentJob && store.currentJob.job_id === jobId) {
      store.currentJob = latest
    }
    const idx = store.historyJobs.findIndex((item) => item.job_id === jobId)
    if (idx >= 0) {
      store.historyJobs[idx] = latest
    }
  } catch {
    // 忽略后台刷新失败，局部数据已由响应体回填
  }
}

async function handleRenderPublication(): Promise<void> {
  if (!job.value || pubLoading.value) return
  pubLoading.value = true
  try {
    const res = await phyloApi.renderPublicationFigure(job.value.job_id, {
      layout: pubLayout.value,
      formats: ['pdf', 'svg', 'png'],
      dpi: pubDpi.value,
      use_branch_lengths: store.visual.useBranchLengths,
      support_style: pubSupportStyle.value,
      show_genus_strip: showGenusStrip.value,
      show_genome_length: showGenomeLength.value,
      show_gc_bar: showGcBar.value,
      ladderize: true,
      label_format: pubLabelFormat.value,
      title: job.value.title,
    })
    await refreshCurrentJobArtifacts(job.value.job_id)
    appStore.showNotification(
      `已生成 ${res.figures.length} 个离线出版级图件 (${res.layout})`,
      'success'
    )
  } catch (err) {
    appStore.showNotification(`离线出版级出图失败: ${String(err)}`, 'error')
  } finally {
    pubLoading.value = false
  }
}

function downloadFigureFile(filename: string): void {
  if (!job.value) return
  window.open(phyloApi.getFigureUrl(job.value.job_id, filename), '_blank')
}

function downloadItolBundle(): void {
  if (!job.value) return
  window.open(phyloApi.getItolUploadBundleUrl(job.value.job_id, pubLabelFormat.value), '_blank')
}

function downloadItolNewick(): void {
  if (!job.value) return
  window.open(phyloApi.getItolNewickUrl(job.value.job_id), '_blank')
}

async function copyItolNewickText(): Promise<void> {
  if (!job.value) return
  try {
    const nwkText = await phyloApi.fetchItolNewickText(job.value.job_id)
    await navigator.clipboard.writeText(nwkText)
    appStore.showNotification(
      '已复制纯 ASCII 版 Newick，请去 iTOL 上传页直接粘贴到 Tree text 框提交',
      'success'
    )
  } catch (err) {
    appStore.showNotification(`复制 iTOL 树文本失败: ${String(err)}`, 'error')
  }
}

function openItolUploadPage(): void {
  window.open(ITOL_UPLOAD_PAGE_URL, '_blank')
}

async function handlePullFromItol(): Promise<void> {
  if (!job.value || itolLoading.value) return
  const target = itolTreeInput.value.trim()
  if (!target) {
    appStore.showNotification('请先粘贴 iTOL 树 URL 或 Tree ID', 'warning')
    return
  }
  itolLoading.value = true
  try {
    const res = await phyloApi.pullItolFigure(job.value.job_id, {
      tree_id_or_url: target,
      format: itolFormat.value,
      display_mode: itolMode.value,
      bootstrap_display: itolBootstrap.value,
      ignore_branch_length: false,
      datasets_visible: '',
      dpi: 300,
    })
    await refreshCurrentJobArtifacts(job.value.job_id)
    appStore.showNotification(`已从官方 iTOL 拉取 ${res.filename}`, 'success')
    window.open(phyloApi.getFigureUrl(job.value.job_id, res.filename), '_blank')
  } catch (err) {
    appStore.showNotification(`从 iTOL 拉取出图失败: ${String(err)}`, 'error')
  } finally {
    itolLoading.value = false
  }
}
</script>

<template>
  <div v-if="job && job.newick" class="pub-wrap">
    <!-- 方案 C：本地离线出版级多环/矩形矢量出图 -->
    <div class="pub-card">
      <div class="card-head">
        <span>离线出版级矢量出图</span>
        <span class="tag-local">本地渲染 / 免联网</span>
      </div>

      <div class="form-row">
        <div class="field">
          <label>出版图版式</label>
          <select v-model="pubLayout" class="neo-select">
            <option value="circular">环形多环出版树 (Circular)</option>
            <option value="rectangular">矩形多轨出版树 (Rectangular)</option>
          </select>
        </div>
        <div class="field">
          <label>支持率显示</label>
          <select v-model="pubSupportStyle" class="neo-select">
            <option value="dots">实心圆点分级 (推荐)</option>
            <option value="both">圆点 + 双支持率数值</option>
            <option value="text">仅数值 (SH-aLRT/UFBoot)</option>
            <option value="none">不显示</option>
          </select>
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>叶节点标签格式</label>
          <select v-model="pubLabelFormat" class="neo-select">
            <option value="name_acc">实际名称 (登录号) [推荐]</option>
            <option value="name">仅实际名称</option>
            <option value="accession">仅登录号</option>
          </select>
        </div>
        <div class="field">
          <label>PNG 分辨率</label>
          <select v-model.number="pubDpi" class="neo-select">
            <option :value="300">300 DPI (期刊标准)</option>
            <option :value="600">600 DPI (高清精印)</option>
          </select>
        </div>
      </div>

      <div v-if="hasNodeMetadata" class="track-checks">
        <label class="chk">
          <input type="checkbox" v-model="showGenusStrip" />
          <span>ICTV 属色带环</span>
        </label>
        <label class="chk">
          <input type="checkbox" v-model="showGenomeLength" />
          <span>基因组大小柱环</span>
        </label>
        <label class="chk">
          <input type="checkbox" v-model="showGcBar" />
          <span>GC% 条带环</span>
        </label>
      </div>

      <button class="btn-primary" :disabled="pubLoading" @click="handleRenderPublication">
        {{ pubLoading ? '正在渲染 PDF / SVG / PNG...' : '一键生成出版级 PDF / SVG / PNG' }}
      </button>

      <div v-if="pubFigures.length" class="file-grid">
        <button
          v-for="fig in pubFigures"
          :key="fig.filename"
          class="btn-file"
          :title="fig.filename"
          @click="downloadFigureFile(fig.filename)"
        >
          {{ fig.layout }} · {{ fig.format.toUpperCase() }}
        </button>
      </div>
    </div>

    <!-- 方案 B：免费官方 iTOL 联动出图 -->
    <div class="pub-card">
      <div class="card-head">
        <span>官方 iTOL 免费联动出图</span>
        <span class="tag-itol">免 API Key</span>
      </div>
      <div class="hint-text">
        切勿把 .zip 直接传到 iTOL 的 Tree file 框。先点「复制 iTOL 树文本」去官网 Tree text 粘贴（或上传 .nwk），打开树后再解压 .zip 拖入注释 txt，最后粘贴 Tree ID 回填拉图。
      </div>

      <div class="btn-pair">
        <button class="btn-sec" @click="copyItolNewickText">复制 iTOL 树文本 (纯ASCII)</button>
        <button class="btn-sec" @click="downloadItolNewick">下载 iTOL 树 (.nwk)</button>
        <button class="btn-sec" @click="downloadItolBundle">下载注释包 (.zip)</button>
        <button class="btn-sec" @click="openItolUploadPage">打开 iTOL 上传页</button>
      </div>

      <input
        v-model="itolTreeInput"
        type="text"
        class="neo-input"
        placeholder="粘贴 iTOL 树 URL (如 https://itol.embl.de/tree/...) 或 Tree ID"
      />

      <div class="form-row">
        <div class="field">
          <label>导出格式</label>
          <select v-model="itolFormat" class="neo-select">
            <option value="pdf">PDF (矢量)</option>
            <option value="svg">SVG (矢量)</option>
            <option value="png">PNG (300 DPI)</option>
            <option value="eps">EPS (矢量)</option>
          </select>
        </div>
        <div class="field">
          <label>iTOL 版式</label>
          <select v-model="itolMode" class="neo-select">
            <option value="circular">环形 (Circular)</option>
            <option value="rectangular">矩形 (Rectangular)</option>
            <option value="unrooted">无根 (Unrooted)</option>
          </select>
        </div>
      </div>

      <label class="chk">
        <input type="checkbox" v-model="itolBootstrap" />
        <span>在 iTOL 导出图中显示支持率</span>
      </label>

      <button class="btn-itol-pull" :disabled="itolLoading" @click="handlePullFromItol">
        {{ itolLoading ? '正在连接 iTOL 导出成图...' : '从 iTOL 自动拉取出图' }}
      </button>

      <div v-if="itolExports.length" class="file-grid">
        <button
          v-for="item in itolExports"
          :key="item.filename"
          class="btn-file"
          :title="item.filename"
          @click="downloadFigureFile(item.filename)"
        >
          iTOL: {{ item.filename }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pub-wrap { display: flex; flex-direction: column; gap: 10px; }
.pub-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 9px; display: flex; flex-direction: column; gap: 7px; }
.card-head { display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 700; color: #0f172a; }
.tag-local { font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 999px; background: #dcfce7; color: #166534; }
.tag-itol { font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 999px; background: #dbeafe; color: #1d4ed8; }
.hint-text { font-size: 10px; color: #64748b; line-height: 1.4; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.field { display: flex; flex-direction: column; gap: 3px; }
.field label { font-size: 10px; font-weight: 600; color: #475569; }
.neo-select, .neo-input { width: 100%; border: 1px solid #cbd5e1; border-radius: 5px; padding: 5px 7px; font-size: 11px; background: #fff; color: #0f172a; box-sizing: border-box; }
.track-checks { display: flex; flex-wrap: wrap; gap: 8px; }
.chk { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #334155; cursor: pointer; }
.chk input { accent-color: #2563eb; }
.btn-primary { width: 100%; padding: 7px 10px; border: none; border-radius: 6px; background: #0f766e; color: #fff; font-size: 11px; font-weight: 700; cursor: pointer; }
.btn-primary:hover:not(:disabled) { background: #115e59; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-itol-pull { width: 100%; padding: 7px 10px; border: none; border-radius: 6px; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; cursor: pointer; }
.btn-itol-pull:hover:not(:disabled) { background: #1d4ed8; }
.btn-itol-pull:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.btn-sec { padding: 5px 7px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; color: #1e293b; font-size: 10px; font-weight: 600; cursor: pointer; }
.btn-sec:hover { border-color: #3b82f6; color: #1d4ed8; background: #eff6ff; }
.file-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
.btn-file { padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; color: #0f172a; font-size: 10px; font-family: monospace; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.btn-file:hover { border-color: #0f766e; color: #0f766e; background: #f0fdfa; }
</style>
