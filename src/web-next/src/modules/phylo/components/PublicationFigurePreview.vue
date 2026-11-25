<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, type CSSProperties } from 'vue'
import { phyloApi } from '../api/phyloApi'
import {
  formatFileSize,
  groupPublicationFiguresByLayout,
  isImagePreviewFormat,
  isPdfPreviewFormat,
  type PublicationLayoutGroup,
} from '../core/FigurePreviewHelper'
import { usePhyloStore } from '../stores/usePhyloStore'
import type { ItolPullResponse, PublicationFigureItem } from '../types/phylo'

const MIN_SCALE = 0.08
const MAX_SCALE = 8.0

const store = usePhyloStore()

const stageRef = ref<HTMLElement | null>(null)
const scale = ref<number>(1)
const tx = ref<number>(0)
const ty = ref<number>(0)
const naturalW = ref<number>(0)
const naturalH = ref<number>(0)
const isFitMode = ref<boolean>(true)
const isLoading = ref<boolean>(false)
const loadError = ref<string>('')
const isDragging = ref<boolean>(false)

let dragStartX = 0
let dragStartY = 0
let originTx = 0
let originTy = 0
let activePointerId: number | null = null
let resizeObserver: ResizeObserver | null = null

const layoutGroups = computed<PublicationLayoutGroup[]>(() =>
  groupPublicationFiguresByLayout(store.availablePublicationFigures)
)

const itolExports = computed<ItolPullResponse[]>(() => store.availableItolExports)

interface ResolvedTarget {
  kind: 'publication' | 'itol'
  filename: string
  format: string
  sizeBytes: number
  label: string
  group: PublicationLayoutGroup | null
}

const activeTarget = computed<ResolvedTarget | null>(() => {
  const fname = store.previewFigureFilename
  if (fname) {
    for (const grp of layoutGroups.value) {
      const hit = grp.formats.find((f) => f.filename === fname)
      if (hit) {
        return {
          kind: 'publication',
          filename: hit.filename,
          format: hit.format,
          sizeBytes: hit.size_bytes,
          label: grp.label,
          group: grp,
        }
      }
    }
    const itolHit = itolExports.value.find((it) => it.filename === fname)
    if (itolHit) {
      return {
        kind: 'itol',
        filename: itolHit.filename,
        format: itolHit.format,
        sizeBytes: itolHit.size_bytes,
        label: `iTOL: ${itolHit.filename}`,
        group: null,
      }
    }
  }

  const fallbackGrp = layoutGroups.value[0]
  if (fallbackGrp?.preferredPreview) {
    const item = fallbackGrp.preferredPreview
    return {
      kind: 'publication',
      filename: item.filename,
      format: item.format,
      sizeBytes: item.size_bytes,
      label: fallbackGrp.label,
      group: fallbackGrp,
    }
  }
  const fallbackItol = itolExports.value[0]
  if (fallbackItol) {
    return {
      kind: 'itol',
      filename: fallbackItol.filename,
      format: fallbackItol.format,
      sizeBytes: fallbackItol.size_bytes,
      label: `iTOL: ${fallbackItol.filename}`,
      group: null,
    }
  }
  return null
})

const activeFormat = computed<string>(() => activeTarget.value?.format.toLowerCase() ?? '')
const isImageTarget = computed<boolean>(() => isImagePreviewFormat(activeFormat.value))
const isPdfTarget = computed<boolean>(() => isPdfPreviewFormat(activeFormat.value))

const previewUrl = computed<string>(() => {
  if (!store.currentJob || !activeTarget.value) return ''
  return phyloApi.getFigureUrl(store.currentJob.job_id, activeTarget.value.filename, {
    inline: true,
    cacheBust: store.figurePreviewVersion,
  })
})

const imgStyle = computed<CSSProperties>(() => {
  const base: CSSProperties = {
    transform: `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`,
    transformOrigin: '0 0',
  }
  if (naturalW.value > 0 && naturalH.value > 0) {
    base.width = `${naturalW.value}px`
    base.height = `${naturalH.value}px`
  }
  return base
})

const zoomPercent = computed<number>(() => Math.round(scale.value * 100))

function clampScale(val: number): number {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, val))
}

function fitToStage(): void {
  const stageEl = stageRef.value
  if (!stageEl || naturalW.value <= 0 || naturalH.value <= 0) return
  const sw = stageEl.clientWidth
  const sh = stageEl.clientHeight
  if (!sw || !sh) return
  const pad = 28
  const availW = Math.max(80, sw - pad * 2)
  const availH = Math.max(80, sh - pad * 2)
  const fit = Math.min(availW / naturalW.value, availH / naturalH.value, 2.0)
  scale.value = clampScale(fit)
  tx.value = (sw - naturalW.value * scale.value) / 2
  ty.value = (sh - naturalH.value * scale.value) / 2
  isFitMode.value = true
}

function zoomToActual(): void {
  const stageEl = stageRef.value
  if (!stageEl || naturalW.value <= 0 || naturalH.value <= 0) return
  const sw = stageEl.clientWidth
  const sh = stageEl.clientHeight
  if (!sw || !sh) return
  scale.value = 1
  tx.value = (sw - naturalW.value) / 2
  ty.value = (sh - naturalH.value) / 2
  isFitMode.value = false
}

function toggleFitOrActual(): void {
  if (!isImageTarget.value || naturalW.value <= 0) return
  if (isFitMode.value) {
    zoomToActual()
  } else {
    fitToStage()
  }
}

function zoomAtClientPoint(factor: number, clientX: number, clientY: number): void {
  const stageEl = stageRef.value
  if (!stageEl || !isImageTarget.value) return
  const rect = stageEl.getBoundingClientRect()
  const px = clientX - rect.left
  const py = clientY - rect.top
  const next = clampScale(scale.value * factor)
  const ratio = next / scale.value
  tx.value = px - (px - tx.value) * ratio
  ty.value = py - (py - ty.value) * ratio
  scale.value = next
  isFitMode.value = false
}

function zoomByCenter(factor: number): void {
  const stageEl = stageRef.value
  if (!stageEl) return
  const rect = stageEl.getBoundingClientRect()
  zoomAtClientPoint(factor, rect.left + rect.width / 2, rect.top + rect.height / 2)
}

function onWheel(e: WheelEvent): void {
  if (!isImageTarget.value || isLoading.value || loadError.value) return
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
  zoomAtClientPoint(factor, e.clientX, e.clientY)
}

function onPointerDown(e: PointerEvent): void {
  if (!isImageTarget.value || e.button !== 0 || isLoading.value || loadError.value) return
  const stageEl = stageRef.value
  if (!stageEl) return
  activePointerId = e.pointerId
  dragStartX = e.clientX
  dragStartY = e.clientY
  originTx = tx.value
  originTy = ty.value
  isDragging.value = true
  stageEl.setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent): void {
  if (!isDragging.value || activePointerId !== e.pointerId) return
  tx.value = originTx + (e.clientX - dragStartX)
  ty.value = originTy + (e.clientY - dragStartY)
  isFitMode.value = false
}

function onPointerUp(e: PointerEvent): void {
  if (activePointerId !== e.pointerId) return
  const stageEl = stageRef.value
  if (stageEl && stageEl.hasPointerCapture(e.pointerId)) {
    stageEl.releasePointerCapture(e.pointerId)
  }
  activePointerId = null
  isDragging.value = false
}

function onImageLoad(e: Event): void {
  const img = e.target as HTMLImageElement | null
  if (!img) return
  const w = img.naturalWidth || img.clientWidth || 1200
  const h = img.naturalHeight || img.clientHeight || 800
  naturalW.value = w
  naturalH.value = h
  isLoading.value = false
  loadError.value = ''
  fitToStage()
}

function onImageError(): void {
  isLoading.value = false
  loadError.value = '图件加载失败，请检查后端服务状态或尝试重新渲染。'
}

function switchGroup(group: PublicationLayoutGroup): void {
  const currentFmt = activeTarget.value?.format.toLowerCase()
  const matched = currentFmt
    ? group.formats.find((f) => f.format.toLowerCase() === currentFmt && isImagePreviewFormat(f.format))
    : undefined
  const target = matched ?? group.preferredPreview
  if (target) {
    store.openFigurePreview(target.filename)
  }
}

function switchSourceFormat(item: PublicationFigureItem | null): void {
  if (item) {
    store.openFigurePreview(item.filename)
  }
}

function isGroupSelected(group: PublicationLayoutGroup): boolean {
  return activeTarget.value?.kind === 'publication' && activeTarget.value.group?.layout === group.layout
}

function downloadFile(filename: string): void {
  if (!store.currentJob) return
  window.open(phyloApi.getFigureUrl(store.currentJob.job_id, filename), '_blank', 'noopener,noreferrer')
}

function reloadPreview(): void {
  store.refreshFigurePreviewVersion()
}

watch(
  previewUrl,
  (url) => {
    naturalW.value = 0
    naturalH.value = 0
    loadError.value = ''
    isFitMode.value = true
    isLoading.value = Boolean(url && isImageTarget.value)
  },
  { immediate: true }
)

onMounted(() => {
  if (stageRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      if (isFitMode.value && naturalW.value > 0 && naturalH.value > 0) {
        fitToStage()
      }
    })
    resizeObserver.observe(stageRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})
</script>

<template>
  <div class="pub-preview-wrap">
    <!-- 顶部子工具栏：图件/版式切换、PNG/SVG 源切换、缩放与快捷下载 -->
    <div class="pub-subbar">
      <div class="subbar-left">
        <button
          v-for="grp in layoutGroups"
          :key="grp.layout"
          class="pill-btn"
          :class="{ active: isGroupSelected(grp) }"
          @click="switchGroup(grp)"
        >
          {{ grp.label }}
        </button>
        <button
          v-for="item in itolExports"
          :key="item.filename"
          class="pill-btn itol-pill"
          :class="{ active: activeTarget?.filename === item.filename }"
          :title="item.filename"
          @click="store.openFigurePreview(item.filename)"
        >
          iTOL · {{ item.format.toUpperCase() }}
        </button>

        <template v-if="activeTarget?.group && (activeTarget.group.previewPng || activeTarget.group.previewSvg)">
          <span class="sub-sep"></span>
          <div class="fmt-switch" title="切换预览渲染源">
            <button
              v-if="activeTarget.group.previewPng"
              class="fmt-btn"
              :class="{ active: activeTarget.filename === activeTarget.group.previewPng.filename }"
              @click="switchSourceFormat(activeTarget.group.previewPng)"
            >
              PNG
            </button>
            <button
              v-if="activeTarget.group.previewSvg"
              class="fmt-btn"
              :class="{ active: activeTarget.filename === activeTarget.group.previewSvg.filename }"
              @click="switchSourceFormat(activeTarget.group.previewSvg)"
            >
              SVG 矢量
            </button>
          </div>
        </template>
      </div>

      <div class="subbar-right">
        <template v-if="isImageTarget">
          <button class="tb-btn" :disabled="isLoading" @click="zoomByCenter(0.83)">缩小</button>
          <span class="zoom-readout">{{ zoomPercent }}%</span>
          <button class="tb-btn" :disabled="isLoading" @click="zoomByCenter(1.2)">放大</button>
          <button class="tb-btn" :disabled="isLoading" @click="fitToStage">适应窗口</button>
          <button class="tb-btn" :disabled="isLoading" @click="zoomToActual">100%</button>
          <span class="sub-sep"></span>
        </template>

        <template v-if="activeTarget?.group">
          <button
            v-for="fmt in activeTarget.group.formats"
            :key="fmt.filename"
            class="tb-btn dl-btn"
            :title="`下载 ${fmt.filename} (${formatFileSize(fmt.size_bytes)})`"
            @click="downloadFile(fmt.filename)"
          >
            下载 {{ fmt.format.toUpperCase() }}
          </button>
        </template>
        <button
          v-else-if="activeTarget"
          class="tb-btn dl-btn"
          @click="downloadFile(activeTarget.filename)"
        >
          下载 {{ activeTarget.format.toUpperCase() }}
        </button>

        <button class="tb-btn back-btn" @click="store.closeFigurePreview()">返回交互树</button>
      </div>
    </div>

    <!-- 预览舞台 -->
    <div
      v-if="activeTarget"
      ref="stageRef"
      class="preview-stage"
      :class="{ dragging: isDragging, 'is-image': isImageTarget }"
      @wheel.prevent="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="toggleFitOrActual"
    >
      <template v-if="isImageTarget">
        <img
          v-show="!loadError"
          :key="previewUrl"
          :src="previewUrl"
          :alt="activeTarget.filename"
          draggable="false"
          class="preview-img"
          :style="imgStyle"
          @load="onImageLoad"
          @error="onImageError"
        />

        <div v-if="isLoading" class="stage-overlay">
          <div class="overlay-card">正在加载高清出版图件...</div>
        </div>

        <div v-if="loadError" class="stage-overlay">
          <div class="overlay-card error-card">
            <div class="err-title">{{ loadError }}</div>
            <button class="tb-btn" @click="reloadPreview">重试加载</button>
          </div>
        </div>
      </template>

      <iframe
        v-else-if="isPdfTarget"
        :key="previewUrl"
        :src="previewUrl"
        class="pdf-frame"
        title="出版图件 PDF 预览"
      />

      <div v-else class="stage-overlay">
        <div class="overlay-card">
          <div class="err-title">当前格式 ({{ activeTarget.format.toUpperCase() }}) 暂不支持网页内直接预览</div>
          <button class="tb-btn dl-btn" @click="downloadFile(activeTarget.filename)">
            立即下载查看 ({{ activeTarget.filename }})
          </button>
        </div>
      </div>
    </div>

    <div v-else class="stage-overlay static-empty">
      <div class="overlay-card">
        <div class="err-title">暂无可预览的出版级图件</div>
        <div class="empty-sub">请先在左侧「出版级导出」卡片生成离线矢量图件或从 iTOL 拉取出图。</div>
      </div>
    </div>

    <!-- 底部状态信息栏 -->
    <div v-if="activeTarget" class="pub-statusbar">
      <div class="status-meta">
        <span class="meta-name">{{ activeTarget.filename }}</span>
        <span class="meta-sep">|</span>
        <span>{{ activeTarget.format.toUpperCase() }}</span>
        <span class="meta-sep">|</span>
        <span>{{ formatFileSize(activeTarget.sizeBytes) }}</span>
        <template v-if="naturalW > 0 && naturalH > 0">
          <span class="meta-sep">|</span>
          <span>{{ naturalW }} x {{ naturalH }} px</span>
        </template>
      </div>
      <div class="status-hint">
        {{
          isImageTarget
            ? '滚轮以鼠标为中心缩放 · 左键拖拽平移 · 双击切换适应/原始比例'
            : '可使用上方工具栏切换版式或直接下载本地文件'
        }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.pub-preview-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #e2e8f0;
  position: relative;
}

.pub-subbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 7px 14px;
  background: #ffffff;
  border-bottom: 1px solid #cbd5e1;
  flex-wrap: wrap;
}

.subbar-left,
.subbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.pill-btn {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.pill-btn:hover {
  border-color: #0f766e;
  color: #0f766e;
}

.pill-btn.active {
  background: #0f766e;
  border-color: #0f766e;
  color: #ffffff;
}

.pill-btn.itol-pill.active {
  background: #2563eb;
  border-color: #2563eb;
}

.sub-sep {
  width: 1px;
  height: 16px;
  background: #cbd5e1;
  margin: 0 2px;
}

.fmt-switch {
  display: inline-flex;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  overflow: hidden;
  background: #f8fafc;
}

.fmt-btn {
  border: none;
  background: transparent;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.fmt-btn.active {
  background: #0f172a;
  color: #ffffff;
}

.tb-btn {
  padding: 4px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #334155;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.tb-btn:hover:not(:disabled) {
  border-color: #2563eb;
  color: #2563eb;
  background: #eff6ff;
}

.tb-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tb-btn.dl-btn {
  border-color: #99f6e4;
  background: #f0fdfa;
  color: #0f766e;
}

.tb-btn.dl-btn:hover {
  border-color: #0f766e;
  background: #ccfbf1;
  color: #115e59;
}

.tb-btn.back-btn {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #0f172a;
}

.zoom-readout {
  min-width: 44px;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: #334155;
  font-variant-numeric: tabular-nums;
}

.preview-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background-color: #e2e8f0;
  background-image: radial-gradient(#cbd5e1 1px, transparent 1px);
  background-size: 16px 16px;
  user-select: none;
}

.preview-stage.is-image {
  cursor: grab;
}

.preview-stage.is-image.dragging {
  cursor: grabbing;
}

.preview-img {
  position: absolute;
  top: 0;
  left: 0;
  display: block;
  max-width: none;
  max-height: none;
  background: #ffffff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.16);
  border-radius: 2px;
  will-change: transform;
}

.pdf-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #ffffff;
}

.stage-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
}

.stage-overlay.static-empty {
  position: relative;
  flex: 1;
}

.overlay-card {
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 18px 24px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #334155;
}

.err-title {
  font-weight: 700;
  color: #0f172a;
}

.empty-sub {
  font-size: 12px;
  color: #64748b;
}

.pub-statusbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 5px 14px;
  background: #f8fafc;
  border-top: 1px solid #cbd5e1;
  font-size: 11px;
  color: #475569;
  flex-wrap: wrap;
}

.status-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-name {
  font-family: monospace;
  font-weight: 600;
  color: #0f172a;
}

.meta-sep {
  color: #cbd5e1;
}

.status-hint {
  color: #64748b;
}
</style>
