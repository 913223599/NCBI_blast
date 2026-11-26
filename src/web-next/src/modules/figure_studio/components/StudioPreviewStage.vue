<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, type CSSProperties } from 'vue'
import { useI18n } from '../../../locales'
import { formatFileSize, isImagePreviewFormat, isPdfPreviewFormat } from '../../phylo/core/FigurePreviewHelper'
import { studioApi } from '../api/studioApi'
import type { StudioFigureFile, StudioRenderResponse } from '../types/studio'

const { t } = useI18n()
const MIN_SCALE = 0.08
const MAX_SCALE = 8.0

const props = defineProps<{
  result: StudioRenderResponse | null
  loading?: boolean
  emptyTitle?: string
  emptyDesc?: string
}>()

const stageRef = ref<HTMLElement | null>(null)
const selectedFilename = ref<string | null>(null)
const version = ref<number>(Date.now())
const scale = ref<number>(1)
const tx = ref<number>(0)
const ty = ref<number>(0)
const naturalW = ref<number>(0)
const naturalH = ref<number>(0)
const isFitMode = ref<boolean>(true)
const imgLoading = ref<boolean>(false)
const loadError = ref<string>('')
const isDragging = ref<boolean>(false)

let dragStartX = 0
let dragStartY = 0
let originTx = 0
let originTy = 0
let activePointerId: number | null = null
let resizeObserver: ResizeObserver | null = null

const figures = computed<StudioFigureFile[]>(() => props.result?.figures ?? [])
const pngFile = computed(() => figures.value.find((f) => f.format.toLowerCase() === 'png') ?? null)
const svgFile = computed(() => figures.value.find((f) => f.format.toLowerCase() === 'svg') ?? null)

const activeFile = computed<StudioFigureFile | null>(() => {
  if (!figures.value.length) return null
  if (selectedFilename.value) {
    const found = figures.value.find((f) => f.filename === selectedFilename.value)
    if (found) return found
  }
  return pngFile.value ?? svgFile.value ?? figures.value[0] ?? null
})

const isImage = computed(() => (activeFile.value ? isImagePreviewFormat(activeFile.value.format) : false))
const isPdf = computed(() => (activeFile.value ? isPdfPreviewFormat(activeFile.value.format) : false))

const previewUrl = computed(() => {
  if (!props.result || !activeFile.value) return ''
  return studioApi.getFileUrl(props.result.render_id, activeFile.value.filename, {
    inline: true,
    cacheBust: version.value,
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

const zoomPercent = computed(() => Math.round(scale.value * 100))

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
  scale.value = 1
  tx.value = (stageEl.clientWidth - naturalW.value) / 2
  ty.value = (stageEl.clientHeight - naturalH.value) / 2
  isFitMode.value = false
}

function toggleFitOrActual(): void {
  if (!isImage.value || naturalW.value <= 0) return
  if (isFitMode.value) zoomToActual()
  else fitToStage()
}

function zoomAtClientPoint(factor: number, clientX: number, clientY: number): void {
  const stageEl = stageRef.value
  if (!stageEl || !isImage.value) return
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
  if (!isImage.value || imgLoading.value || loadError.value) return
  zoomAtClientPoint(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY)
}

function onPointerDown(e: PointerEvent): void {
  if (!isImage.value || e.button !== 0 || imgLoading.value || loadError.value) return
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
  naturalW.value = img.naturalWidth || img.clientWidth || 1200
  naturalH.value = img.naturalHeight || img.clientHeight || 800
  imgLoading.value = false
  loadError.value = ''
  fitToStage()
}

function onImageError(): void {
  imgLoading.value = false
  loadError.value = t('studio.stage.img_error')
}

function downloadFile(fname: string): void {
  if (!props.result) return
  window.open(studioApi.getFileUrl(props.result.render_id, fname), '_blank', 'noopener,noreferrer')
}

watch(
  () => props.result?.render_id,
  () => {
    selectedFilename.value = pngFile.value?.filename ?? svgFile.value?.filename ?? null
    version.value = Date.now()
  }
)

watch(
  previewUrl,
  (url) => {
    naturalW.value = 0
    naturalH.value = 0
    loadError.value = ''
    isFitMode.value = true
    imgLoading.value = Boolean(url && isImage.value)
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
  <div class="studio-stage-wrap">
    <div class="stage-toolbar">
      <div class="tb-left">
        <div v-if="pngFile || svgFile" class="fmt-switch">
          <button
            v-if="pngFile"
            type="button"
            class="fmt-btn"
            :class="{ active: activeFile?.filename === pngFile.filename }"
            @click="selectedFilename = pngFile.filename"
          >
            {{ t('studio.stage.png_btn') }}
          </button>
          <button
            v-if="svgFile"
            type="button"
            class="fmt-btn"
            :class="{ active: activeFile?.filename === svgFile.filename }"
            @click="selectedFilename = svgFile.filename"
          >
            {{ t('studio.stage.svg_btn') }}
          </button>
        </div>
        <span v-else class="tb-title-muted">{{ t('studio.stage.title_muted') }}</span>
      </div>

      <div class="tb-right">
        <template v-if="activeFile && isImage">
          <button type="button" class="tb-btn" :disabled="imgLoading" @click="zoomByCenter(0.83)">{{ t('studio.stage.zoom_out') }}</button>
          <span class="zoom-readout">{{ zoomPercent }}%</span>
          <button type="button" class="tb-btn" :disabled="imgLoading" @click="zoomByCenter(1.2)">{{ t('studio.stage.zoom_in') }}</button>
          <button type="button" class="tb-btn" :disabled="imgLoading" @click="fitToStage">{{ t('studio.stage.fit_window') }}</button>
          <button type="button" class="tb-btn" :disabled="imgLoading" @click="zoomToActual">100%</button>
          <span class="tb-sep"></span>
        </template>

        <button
          v-for="f in figures"
          :key="f.filename"
          type="button"
          class="tb-btn dl-btn"
          :title="t('studio.stage.download_title', { filename: f.filename, size: formatFileSize(f.size_bytes) })"
          @click="downloadFile(f.filename)"
        >
          {{ t('studio.stage.download_fmt', { format: f.format.toUpperCase() }) }}
        </button>
      </div>
    </div>

    <div
      ref="stageRef"
      class="preview-stage"
      :class="{ dragging: isDragging, 'is-image': isImage && Boolean(activeFile) }"
      @wheel.prevent="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="toggleFitOrActual"
    >
      <div v-if="loading" class="stage-overlay">
        <div class="overlay-card">{{ t('studio.stage.rendering_overlay') }}</div>
      </div>

      <template v-else-if="activeFile && isImage">
        <img
          v-show="!loadError"
          :key="previewUrl"
          :src="previewUrl"
          :alt="activeFile.filename"
          draggable="false"
          class="preview-img"
          :style="imgStyle"
          @load="onImageLoad"
          @error="onImageError"
        />
        <div v-if="imgLoading" class="stage-overlay">
          <div class="overlay-card">{{ t('studio.stage.img_loading') }}</div>
        </div>
        <div v-if="loadError" class="stage-overlay">
          <div class="overlay-card">
            <div class="err-title">{{ loadError }}</div>
            <button type="button" class="tb-btn" @click="version = Date.now()">{{ t('studio.stage.retry') }}</button>
          </div>
        </div>
      </template>

      <iframe
        v-else-if="activeFile && isPdf"
        :key="previewUrl"
        :src="previewUrl"
        class="pdf-frame"
        :title="t('studio.stage.pdf_title')"
      />

      <div v-else class="stage-overlay">
        <div class="overlay-card empty-card">
          <div class="empty-title">{{ emptyTitle || t('studio.stage.empty_title') }}</div>
          <div class="empty-desc">
            {{ emptyDesc || t('studio.stage.empty_desc') }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="activeFile" class="stage-statusbar">
      <div class="meta-left">
        <span class="meta-name">{{ activeFile.filename }}</span>
        <span class="meta-sep">|</span>
        <span>{{ activeFile.format.toUpperCase() }}</span>
        <span class="meta-sep">|</span>
        <span>{{ formatFileSize(activeFile.size_bytes) }}</span>
        <template v-if="naturalW > 0 && naturalH > 0">
          <span class="meta-sep">|</span>
          <span>{{ naturalW }} x {{ naturalH }} px</span>
        </template>
      </div>
      <div class="meta-hint">{{ t('studio.stage.hint') }}</div>
    </div>
  </div>
</template>

<style scoped>
.studio-stage-wrap { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; background: #e2e8f0; }
.stage-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 14px; background: #fff; border-bottom: 1px solid #cbd5e1; flex-wrap: wrap; }
.tb-left, .tb-right { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tb-title-muted { font-size: 12px; font-weight: 700; color: #475569; }
.fmt-switch { display: inline-flex; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; background: #f8fafc; }
.fmt-btn { border: none; background: transparent; padding: 4px 10px; font-size: 11px; font-weight: 600; color: #475569; cursor: pointer; }
.fmt-btn.active { background: #0f172a; color: #ffffff; }
.tb-btn { padding: 4px 9px; border: 1px solid #cbd5e1; border-radius: 6px; background: #ffffff; color: #334155; font-size: 11px; font-weight: 600; cursor: pointer; }
.tb-btn:hover:not(:disabled) { border-color: #2563eb; color: #2563eb; background: #eff6ff; }
.tb-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.tb-btn.dl-btn { border-color: #99f6e4; background: #f0fdfa; color: #0f766e; }
.tb-btn.dl-btn:hover { border-color: #0f766e; background: #ccfbf1; color: #115e59; }
.tb-sep { width: 1px; height: 16px; background: #cbd5e1; margin: 0 2px; }
.zoom-readout { min-width: 44px; text-align: center; font-size: 11px; font-weight: 700; color: #334155; font-variant-numeric: tabular-nums; }
.preview-stage { position: relative; flex: 1; min-height: 0; overflow: hidden; background-color: #e2e8f0; background-image: radial-gradient(#cbd5e1 1px, transparent 1px); background-size: 16px 16px; user-select: none; }
.preview-stage.is-image { cursor: grab; }
.preview-stage.is-image.dragging { cursor: grabbing; }
.preview-img { position: absolute; top: 0; left: 0; display: block; max-width: none; max-height: none; background: #fff; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.16); border-radius: 2px; will-change: transform; }
.pdf-frame { width: 100%; height: 100%; border: none; background: #fff; }
.stage-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: auto; }
.overlay-card { background: rgba(255, 255, 255, 0.96); border: 1px solid #cbd5e1; border-radius: 10px; padding: 20px 26px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1); display: flex; flex-direction: column; align-items: center; gap: 10px; font-size: 13px; color: #334155; }
.empty-card { max-width: 460px; text-align: center; }
.empty-title { font-size: 15px; font-weight: 700; color: #0f172a; }
.empty-desc { font-size: 12px; color: #64748b; line-height: 1.6; }
.err-title { font-weight: 700; color: #0f172a; }
.stage-statusbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 5px 14px; background: #f8fafc; border-top: 1px solid #cbd5e1; font-size: 11px; color: #475569; flex-wrap: wrap; }
.meta-left { display: flex; align-items: center; gap: 6px; }
.meta-name { font-family: monospace; font-weight: 600; color: #0f172a; }
.meta-sep { color: #cbd5e1; }
.meta-hint { color: #64748b; }
</style>
