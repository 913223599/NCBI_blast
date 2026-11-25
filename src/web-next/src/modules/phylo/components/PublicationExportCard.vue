<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAppStore } from '../../../stores/app'
import { phyloApi } from '../api/phyloApi'
import {
  formatFileSize,
  groupPublicationFiguresByLayout,
  isImagePreviewFormat,
  isPdfPreviewFormat,
  pickPreferredPreviewFilename,
  type PublicationLayoutGroup,
} from '../core/FigurePreviewHelper'
import { usePhyloStore } from '../stores/usePhyloStore'
import type {
  CladeShadingModeType,
  ItolDisplayModeType,
  ItolExportFormatType,
  ItolPullResponse,
  JournalPaletteType,
  JournalWidthPresetType,
  LabelDensityType,
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
const pubLayout = ref<PublicationLayoutType>('composite')
const pubSupportStyle = ref<PublicationSupportStyle>('dots')
const pubLabelFormat = ref<LabelFormatType>('name_acc')
const pubPalette = ref<JournalPaletteType>('nature')
const pubJournalWidth = ref<JournalWidthPresetType>('auto')
const pubLabelDensity = ref<LabelDensityType>('auto')
const pubDpi = ref<number>(300)
const showGenusStrip = ref<boolean>(true)
const showHostStrip = ref<boolean>(true)
const showGenomeLength = ref<boolean>(true)
const showGcBar = ref<boolean>(true)
const cladeShadingMode = ref<CladeShadingModeType>('query_clade')
const showQueryStar = ref<boolean>(true)
const showFigureTitle = ref<boolean>(false)
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

const layoutGroups = computed<PublicationLayoutGroup[]>(() =>
  groupPublicationFiguresByLayout(pubFigures.value)
)

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
      show_host_strip: showHostStrip.value,
      show_genome_length: showGenomeLength.value,
      show_gc_bar: showGcBar.value,
      show_clade_shading: cladeShadingMode.value !== 'none',
      clade_shading_mode: cladeShadingMode.value,
      show_query_star: showQueryStar.value,
      palette: pubPalette.value,
      journal_width: pubJournalWidth.value,
      label_density: pubLabelDensity.value,
      show_figure_title: showFigureTitle.value,
      ladderize: true,
      label_format: pubLabelFormat.value,
      title: job.value.title,
    })
    await refreshCurrentJobArtifacts(job.value.job_id)
    store.refreshFigurePreviewVersion()
    const previewTarget = pickPreferredPreviewFilename(res.figures)
    if (previewTarget) {
      store.openFigurePreview(previewTarget)
    }
    appStore.showNotification(
      `已生成 ${res.figures.length} 个离线出版级图件 (${res.layout})，已在右侧打开预览`,
      'success'
    )
  } catch (err) {
    appStore.showNotification(`离线出版级出图失败: ${String(err)}`, 'error')
  } finally {
    pubLoading.value = false
  }
}

function previewFigure(filename: string): void {
  store.openFigurePreview(filename)
}

function getThumbUrl(filename: string): string {
  if (!job.value) return ''
  return phyloApi.getFigureUrl(job.value.job_id, filename, {
    inline: true,
    cacheBust: store.figurePreviewVersion,
  })
}

function isGroupActive(group: PublicationLayoutGroup): boolean {
  return (
    store.viewportMode === 'publication' &&
    group.formats.some((f) => f.filename === store.previewFigureFilename)
  )
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
    store.refreshFigurePreviewVersion()
    if (isImagePreviewFormat(res.format) || isPdfPreviewFormat(res.format)) {
      store.openFigurePreview(res.filename)
      appStore.showNotification(`已从官方 iTOL 拉取 ${res.filename}，已在右侧打开预览`, 'success')
    } else {
      appStore.showNotification(`已从官方 iTOL 拉取 ${res.filename}`, 'success')
      window.open(phyloApi.getFigureUrl(job.value.job_id, res.filename), '_blank')
    }
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
            <option value="composite">复合双拼论文图 (a 全局环 + b 局部详图) [推荐]</option>
            <option value="circular">环形多环出版树 (Circular)</option>
            <option value="half_circular">180° 半圆扇形全景树 (双栏宽幅)</option>
            <option value="rectangular">矩形多轨出版树 (Rectangular)</option>
          </select>
        </div>
        <div class="field">
          <label>支持率显示</label>
          <select v-model="pubSupportStyle" class="neo-select">
            <option value="dots">实心/空心圆点分级 (推荐)</option>
            <option value="both">圆点 + 双支持率数值</option>
            <option value="text">仅数值 (SH-aLRT/UFBoot)</option>
            <option value="none">不显示</option>
          </select>
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>期刊色板风格</label>
          <select v-model="pubPalette" class="neo-select">
            <option value="nature">Nature / NPG (推荐)</option>
            <option value="lancet">The Lancet 柳叶刀</option>
            <option value="okabe_ito">Okabe-Ito (色盲安全)</option>
            <option value="monochrome">MBE 黑白极简印刷</option>
          </select>
        </div>
        <div class="field">
          <label>期刊栏宽预设</label>
          <select v-model="pubJournalWidth" class="neo-select">
            <option value="auto">自适应标准画幅</option>
            <option value="single_col">单栏紧凑 (89mm 比例)</option>
            <option value="double_col">双栏通栏 (183mm 比例)</option>
          </select>
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>大规模环形标签密度</label>
          <select v-model="pubLabelDensity" class="neo-select">
            <option value="auto">智能适配 (N&gt;80 仅标查询株)</option>
            <option value="smart_query">仅外圈引出标注查询株</option>
            <option value="all">全部叶节点显示标签</option>
          </select>
        </div>
        <div class="field">
          <label>叶节点标签格式</label>
          <select v-model="pubLabelFormat" class="neo-select">
            <option value="name_acc">实际名称 (登录号) [推荐]</option>
            <option value="name">仅实际名称</option>
            <option value="accession">仅登录号</option>
          </select>
        </div>
      </div>

      <div class="form-row">
        <div class="field">
          <label>PNG 分辨率</label>
          <select v-model.number="pubDpi" class="neo-select">
            <option :value="300">300 DPI (期刊标准)</option>
            <option :value="600">600 DPI (高清精印)</option>
          </select>
        </div>
        <div class="field">
          <label>支系底色块策略</label>
          <select v-model="cladeShadingMode" class="neo-select">
            <option value="query_clade">仅高亮查询株支系 (推荐)</option>
            <option value="all_clades">全部单系支系着色</option>
            <option value="none">关闭背景底色块</option>
          </select>
        </div>
      </div>

      <div class="title-check-row">
        <label class="chk">
          <input type="checkbox" v-model="showFigureTitle" />
          <span>图顶显示任务标题</span>
        </label>
      </div>

      <div v-if="hasNodeMetadata" class="track-checks">
        <label class="chk">
          <input type="checkbox" v-model="showQueryStar" />
          <span>查询株矢量星标</span>
        </label>
        <label class="chk">
          <input type="checkbox" v-model="showGenusStrip" />
          <span>ICTV 属色带环</span>
        </label>
        <label class="chk">
          <input type="checkbox" v-model="showHostStrip" />
          <span>宿主门分类环 (Host)</span>
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

      <div v-if="layoutGroups.length" class="figure-group-list">
        <div
          v-for="grp in layoutGroups"
          :key="grp.layout"
          class="fig-group-card"
          :class="{ active: isGroupActive(grp) }"
        >
          <div class="fig-group-head">
            <span class="fig-group-title">{{ grp.label }}</span>
            <button
              v-if="grp.preferredPreview"
              class="btn-preview-sm"
              @click="previewFigure(grp.preferredPreview.filename)"
            >
              {{ isGroupActive(grp) ? '预览中' : '主视口预览' }}
            </button>
          </div>

          <div
            v-if="grp.preferredPreview && isImagePreviewFormat(grp.preferredPreview.format)"
            class="thumb-box"
            title="点击在右侧主画布放大预览"
            @click="previewFigure(grp.preferredPreview.filename)"
          >
            <img
              :src="getThumbUrl(grp.preferredPreview.filename)"
              :alt="grp.label"
              loading="lazy"
              class="thumb-img"
            />
          </div>

          <div class="fig-dl-row">
            <button
              v-for="fig in grp.formats"
              :key="fig.filename"
              class="btn-fmt-dl"
              :title="`${fig.filename} (${formatFileSize(fig.size_bytes)})`"
              @click="downloadFigureFile(fig.filename)"
            >
              {{ fig.format.toUpperCase() }}
            </button>
          </div>
        </div>
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

      <div v-if="itolExports.length" class="itol-export-list">
        <div
          v-for="item in itolExports"
          :key="item.filename"
          class="itol-export-row"
        >
          <span class="itol-export-name" :title="item.filename">
            iTOL: {{ item.filename }} ({{ formatFileSize(item.size_bytes) }})
          </span>
          <div class="itol-export-actions">
            <button
              v-if="isImagePreviewFormat(item.format) || isPdfPreviewFormat(item.format)"
              class="btn-preview-sm"
              @click="previewFigure(item.filename)"
            >
              预览
            </button>
            <button
              class="btn-fmt-dl"
              @click="downloadFigureFile(item.filename)"
            >
              下载
            </button>
          </div>
        </div>
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
.title-check-row { display: flex; align-items: center; }
.figure-group-list { display: flex; flex-direction: column; gap: 7px; margin-top: 2px; }
.fig-group-card { border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; padding: 6px; display: flex; flex-direction: column; gap: 5px; }
.fig-group-card.active { border-color: #0f766e; box-shadow: 0 0 0 1px rgba(15, 118, 110, 0.25); }
.fig-group-head { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.fig-group-title { font-size: 10px; font-weight: 700; color: #0f172a; }
.btn-preview-sm { border: 1px solid #99f6e4; background: #f0fdfa; color: #0f766e; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700; cursor: pointer; }
.btn-preview-sm:hover { background: #ccfbf1; border-color: #0f766e; }
.thumb-box { width: 100%; height: 106px; border: 1px solid #e2e8f0; border-radius: 4px; background: #ffffff; display: flex; align-items: center; justify-content: center; overflow: hidden; cursor: pointer; }
.thumb-box:hover { border-color: #0f766e; }
.thumb-img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
.fig-dl-row { display: flex; gap: 4px; flex-wrap: wrap; }
.btn-fmt-dl { flex: 1; min-width: 44px; border: 1px solid #cbd5e1; background: #f8fafc; color: #334155; border-radius: 4px; padding: 3px 6px; font-size: 10px; font-family: monospace; font-weight: 600; cursor: pointer; }
.btn-fmt-dl:hover { border-color: #2563eb; color: #1d4ed8; background: #eff6ff; }
.itol-export-list { display: flex; flex-direction: column; gap: 5px; }
.itol-export-row { display: flex; justify-content: space-between; align-items: center; gap: 6px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; }
.itol-export-name { font-size: 10px; font-family: monospace; color: #0f172a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.itol-export-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
</style>
