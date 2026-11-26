<script setup lang="ts">
/**
 * Protein3DViewerModal.vue - 零首屏负担的交互式 3D 蛋白结构可视化弹窗
 * - 使用原生 <dialog> + showModal() + closedby="any"（附非 Chromium pointerdown/pointerup 回退）
 * - 动态按需 import('3dmol')（独立 vendor-3dmol chunk，未打开时不加载）
 * - 支持：当前任务本地 .pdb/.cif、AlphaFold DB (UniProt ID)、RCSB PDB (4位ID)、本地文件上传、离线示例结构
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from '../../../../../locales'
import { shouldSubmitOnEnter } from '../../../../../utils/ime'
import {
  DEMO_HELIX_PDB,
  expandResidueIndices,
  parseResidueRanges,
  plddtColorHex,
  type ColorScheme,
  type RenderStyle,
  type StructurePayload,
  type TaskStructureFileItem,
} from './viewer3d/structure3dHelper'

export interface Protein3DInitialContext {
  taskId?: string
  locusTag?: string
  product?: string
  lengthAa?: number
  defaultResidueRange?: string
}

const props = defineProps<{
  open: boolean
  context?: Protein3DInitialContext | null
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const canvasHostRef = ref<HTMLDivElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const sourceMode = ref<'alphafold' | 'rcsb'>('alphafold')
const accessionInput = ref<string>('')
const taskFiles = ref<TaskStructureFileItem[]>([])
const selectedTaskFile = ref<string>('')
const renderStyle = ref<RenderStyle>('cartoon')
const colorScheme = ref<ColorScheme>('plddt')
const showSurface = ref<boolean>(false)
const isSpinning = ref<boolean>(false)
const highlightRangeInput = ref<string>('')

const isLoading = ref<boolean>(false)
const errorMsg = ref<string>('')
const loadedMeta = ref<{
  filename: string
  format: 'pdb' | 'mmcif'
  source: string
  sizeBytes: number
  cached: boolean
} | null>(null)

interface ThreeDMolAtom {
  b?: number
}

interface ThreeDMolStyleOptions {
  color?: string
  colorscheme?: string
  colorfunc?: (atom: ThreeDMolAtom) => string
  thickness?: number
  radius?: number
  scale?: number
}

interface ThreeDMolStyleSpec {
  cartoon?: ThreeDMolStyleOptions
  stick?: ThreeDMolStyleOptions
  sphere?: ThreeDMolStyleOptions
  line?: ThreeDMolStyleOptions
}

interface ThreeDMolViewerInstance {
  spin: (axis: string | false) => void
  clear: () => void
  removeAllSurfaces: () => void
  setStyle: (sel: Record<string, unknown>, style: ThreeDMolStyleSpec) => void
  addStyle: (sel: Record<string, unknown>, style: ThreeDMolStyleSpec) => void
  addSurface: (type: unknown, style: Record<string, unknown>) => void
  addModel: (data: string, format: string) => void
  zoomTo: () => void
  render: () => void
  pngURI?: () => string
}

interface ThreeDMolLib {
  createViewer: (
    element: HTMLElement,
    config?: Record<string, unknown>
  ) => ThreeDMolViewerInstance
  SurfaceType?: { VDW: unknown }
}

let viewerInstance: ThreeDMolViewerInstance | null = null
let cached3Dmol: ThreeDMolLib | null = null
let currentContent = ''
let pressedOutside = false

const { t } = useI18n()

const titleText = computed(() => {
  if (props.context?.locusTag) {
    return `${t('structure3d.dialog_title')} · ${props.context.locusTag}`
  }
  return t('structure3d.dialog_title')
})

const subtitleText = computed(() => {
  if (!props.context) return '支持本地 .pdb/.cif、AlphaFold DB 与 RCSB PDB 交互式渲染'
  const parts: string[] = []
  if (props.context.product) parts.push(props.context.product)
  if (props.context.lengthAa) parts.push(`${props.context.lengthAa} aa`)
  return parts.join(' · ') || '支持本地 .pdb/.cif、AlphaFold DB 与 RCSB PDB 交互式渲染'
})

async function ensure3Dmol(): Promise<ThreeDMolLib> {
  if (cached3Dmol) return cached3Dmol
  const mod = (await import('3dmol')) as Partial<ThreeDMolLib> & { default?: Partial<ThreeDMolLib> }
  const globalLib = (globalThis as { $3Dmol?: Partial<ThreeDMolLib> }).$3Dmol
  const candidate = mod?.createViewer ? mod : (mod?.default || globalLib)
  if (!candidate || typeof candidate.createViewer !== 'function') {
    throw new Error('3Dmol 渲染引擎初始化失败')
  }
  const lib = candidate as ThreeDMolLib
  cached3Dmol = lib
  return lib
}

function disposeViewer(): void {
  if (viewerInstance) {
    try {
      viewerInstance.spin(false)
      viewerInstance.clear()
    } catch {
      // 忽略 WebGL 上下文销毁期非关键异常
    }
    viewerInstance = null
  }
  if (canvasHostRef.value) {
    canvasHostRef.value.replaceChildren()
  }
}

async function applyStyleAndRender(): Promise<void> {
  if (!viewerInstance || !currentContent) return
  try {
    viewerInstance.removeAllSurfaces()
    const baseColorSpec: ThreeDMolStyleOptions =
      colorScheme.value === 'plddt'
        ? { colorfunc: (atom: ThreeDMolAtom) => plddtColorHex(Number(atom?.b ?? 0)) }
        : colorScheme.value === 'ss'
          ? { colorscheme: 'ssPyMOL' }
          : { color: 'spectrum' }

    const styleObj: ThreeDMolStyleSpec = {}
    if (renderStyle.value === 'cartoon') {
      styleObj.cartoon = { ...baseColorSpec, thickness: 0.45 }
    } else if (renderStyle.value === 'stick') {
      styleObj.stick = { ...baseColorSpec, radius: 0.22 }
    } else if (renderStyle.value === 'sphere') {
      styleObj.sphere = { ...baseColorSpec, scale: 0.35 }
    } else {
      styleObj.line = { ...baseColorSpec }
    }

    viewerInstance.setStyle({}, styleObj)

    const ranges = parseResidueRanges(highlightRangeInput.value)
    if (ranges.length > 0) {
      const resi = expandResidueIndices(ranges)
      if (resi.length > 0) {
        viewerInstance.addStyle(
          { resi },
          {
            cartoon: { color: '#ef4444', thickness: 0.65 },
            stick: { color: '#dc2626', radius: 0.24 },
          }
        )
      }
    }

    if (showSurface.value && cached3Dmol?.SurfaceType) {
      viewerInstance.addSurface(cached3Dmol.SurfaceType.VDW, {
        opacity: 0.48,
        color: '#93c5fd',
      })
    }

    viewerInstance.spin(isSpinning.value ? 'y' : false)
    viewerInstance.render()
  } catch (err) {
    errorMsg.value = `样式渲染异常: ${String(err)}`
  }
}

async function renderStructureText(payload: StructurePayload): Promise<void> {
  await nextTick()
  if (!canvasHostRef.value) return
  errorMsg.value = ''
  const lib = await ensure3Dmol()

  if (!viewerInstance) {
    viewerInstance = lib.createViewer(canvasHostRef.value, {
      backgroundColor: '#f8fafc',
      antialias: true,
    })
  } else {
    viewerInstance.clear()
  }

  currentContent = payload.content
  loadedMeta.value = {
    filename: payload.filename,
    format: payload.format,
    source: payload.source,
    sizeBytes: payload.size_bytes,
    cached: payload.cached,
  }

  viewerInstance.addModel(payload.content, payload.format)
  await applyStyleAndRender()
  viewerInstance.zoomTo()
  viewerInstance.render()
}

async function loadTaskStructureList(): Promise<void> {
  taskFiles.value = []
  selectedTaskFile.value = ''
  const tid = props.context?.taskId
  if (!tid) return
  try {
    const resp = await fetch(`/api/analysis/phage_structure/${encodeURIComponent(tid)}/structures`)
    if (!resp.ok) return
    const data = await resp.json()
    taskFiles.value = Array.isArray(data?.files) ? data.files : []
    if (taskFiles.value.length > 0) {
      const locus = (props.context?.locusTag || '').toLowerCase()
      const matched = locus
        ? taskFiles.value.find((f) => f.name.toLowerCase().includes(locus))
        : null
      selectedTaskFile.value = (matched || taskFiles.value[0])?.rel_path || ''
    }
  } catch {
    // 离线单测或服务未启时静默忽略
  }
}

async function handleLoadTaskFile(): Promise<void> {
  const tid = props.context?.taskId
  if (!tid || !selectedTaskFile.value) return
  isLoading.value = true
  errorMsg.value = ''
  try {
    const url = `/api/analysis/phage_structure/${encodeURIComponent(tid)}/structure-file?path=${encodeURIComponent(selectedTaskFile.value)}`
    const resp = await fetch(url)
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      throw new Error(err?.detail || `加载失败 (${resp.status})`)
    }
    const payload: StructurePayload = await resp.json()
    await renderStructureText(payload)
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    isLoading.value = false
  }
}

async function handleFetchPublicStructure(): Promise<void> {
  const acc = accessionInput.value.trim()
  if (!acc) {
    errorMsg.value = sourceMode.value === 'alphafold'
      ? '请输入 UniProt Accession（例如 P00533）'
      : '请输入 4 位 PDB ID（例如 1EMA）'
    return
  }
  isLoading.value = true
  errorMsg.value = ''
  try {
    const url = `/api/analysis/phage_structure/public-structure?source=${encodeURIComponent(sourceMode.value)}&accession=${encodeURIComponent(acc)}`
    const resp = await fetch(url)
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      throw new Error(err?.detail || `拉取失败 (${resp.status})`)
    }
    const payload: StructurePayload = await resp.json()
    await renderStructureText(payload)
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    isLoading.value = false
  }
}

function onAccessionKeydown(e: KeyboardEvent): void {
  if (shouldSubmitOnEnter(e)) {
    handleFetchPublicStructure()
  }
}

function onHighlightKeydown(e: KeyboardEvent): void {
  if (shouldSubmitOnEnter(e)) {
    applyStyleAndRender()
  }
}

async function handleLocalFileSelect(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  isLoading.value = true
  errorMsg.value = ''
  try {
    const content = await file.text()
    const lower = file.name.toLowerCase()
    const format: 'pdb' | 'mmcif' = lower.endsWith('.cif') || lower.endsWith('.mmcif') ? 'mmcif' : 'pdb'
    await renderStructureText({
      source: 'local_upload',
      filename: file.name,
      format,
      size_bytes: file.size,
      content,
      cached: true,
    })
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    isLoading.value = false
    if (input) input.value = ''
  }
}

async function handleLoadDemo(): Promise<void> {
  isLoading.value = true
  errorMsg.value = ''
  try {
    await renderStructureText({
      source: 'builtin_demo',
      filename: 'demo_alpha_helix.pdb',
      format: 'pdb',
      size_bytes: DEMO_HELIX_PDB.length,
      content: DEMO_HELIX_PDB,
      cached: true,
    })
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    isLoading.value = false
  }
}

function resetCamera(): void {
  if (!viewerInstance) return
  viewerInstance.zoomTo()
  viewerInstance.render()
}

function exportPngSnapshot(): void {
  if (!viewerInstance || typeof viewerInstance.pngURI !== 'function') return
  const dataUrl: string = viewerInstance.pngURI()
  if (!dataUrl) return
  const link = document.createElement('a')
  const baseName = (loadedMeta.value?.filename || 'protein_3d').replace(/\.[^.]+$/, '')
  link.href = dataUrl
  link.download = `${baseName}_3d.png`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function isPointerOutsideDialog(e: PointerEvent, dialog: HTMLDialogElement): boolean {
  const r = dialog.getBoundingClientRect()
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
}

function onDialogPointerDown(e: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  pressedOutside = isPointerOutsideDialog(e, dialog)
}

function onDialogPointerUp(e: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  if (pressedOutside && isPointerOutsideDialog(e, dialog)) {
    requestCloseDialog()
  }
  pressedOutside = false
}

function requestCloseDialog(): void {
  const dialog = dialogRef.value
  if (dialog && typeof dialog.close === 'function' && dialog.open) {
    dialog.close('close')
  } else {
    handleDialogClose()
  }
}

function handleDialogClose(): void {
  const dialog = dialogRef.value
  if (dialog) {
    dialog.returnValue = ''
  }
  disposeViewer()
  if (props.open) {
    emit('update:open', false)
  }
}

watch([renderStyle, colorScheme, showSurface, isSpinning], () => {
  if (viewerInstance && currentContent) {
    applyStyleAndRender()
  }
})

watch(
  () => props.open,
  async (isOpen) => {
    await nextTick()
    const dialog = dialogRef.value
    if (!dialog) return
    if (isOpen) {
      errorMsg.value = ''
      highlightRangeInput.value = props.context?.defaultResidueRange || ''
      if (!dialog.open) {
        if (typeof dialog.showModal === 'function') {
          dialog.showModal()
        } else {
          dialog.setAttribute('open', '')
        }
      }
      await loadTaskStructureList()
      if (selectedTaskFile.value) {
        await handleLoadTaskFile()
      }
    } else if (dialog.open) {
      requestCloseDialog()
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  disposeViewer()
})
</script>

<template>
  <dialog
    ref="dialogRef"
    class="protein-3d-dialog"
    aria-labelledby="protein-3d-title"
    closedby="any"
    @close="handleDialogClose"
    @pointerdown="onDialogPointerDown"
    @pointerup="onDialogPointerUp"
  >
    <header class="p3d-header">
      <div class="p3d-title-wrap">
        <h1 id="protein-3d-title" class="p3d-title">{{ titleText }}</h1>
        <p class="p3d-subtitle">{{ subtitleText }}</p>
      </div>
      <form method="dialog">
        <button type="submit" value="close" class="p3d-close-btn" aria-label="关闭 3D 结构检视窗">
          {{ t('structure3d.close_btn') }}
        </button>
      </form>
    </header>

    <!-- 1. 结构来源加载条 -->
    <section class="p3d-source-bar" aria-label="3D 结构数据源">
      <div v-if="taskFiles.length > 0" class="p3d-source-group">
        <label class="p3d-lbl" for="p3d-task-file-sel">任务结构</label>
        <select id="p3d-task-file-sel" v-model="selectedTaskFile" class="p3d-select">
          <option v-for="f in taskFiles" :key="f.rel_path" :value="f.rel_path">
            {{ f.name }} ({{ (f.size_bytes / 1024).toFixed(1) }} KB)
          </option>
        </select>
        <button type="button" class="p3d-btn primary" :disabled="isLoading" @click="handleLoadTaskFile">
          加载
        </button>
      </div>

      <div class="p3d-source-group">
        <label class="p3d-lbl" for="p3d-db-sel">在线库</label>
        <select id="p3d-db-sel" v-model="sourceMode" class="p3d-select compact">
          <option value="alphafold">AlphaFold DB</option>
          <option value="rcsb">RCSB PDB</option>
        </select>
        <input
          v-model="accessionInput"
          type="text"
          class="p3d-input"
          :placeholder="sourceMode === 'alphafold' ? 'UniProt ID (如 P00533)' : 'PDB ID (如 1EMA)'"
          autofocus
          @keydown="onAccessionKeydown"
        />
        <button type="button" class="p3d-btn primary" :disabled="isLoading" @click="handleFetchPublicStructure">
          {{ isLoading ? '拉取中...' : '获取 3D' }}
        </button>
      </div>

      <div class="p3d-source-group">
        <input
          ref="fileInputRef"
          type="file"
          accept=".pdb,.cif,.mmcif"
          class="sr-only-input"
          @change="handleLocalFileSelect"
        />
        <button type="button" class="p3d-btn" :disabled="isLoading" @click="fileInputRef?.click()">
          打开本地 PDB/CIF
        </button>
        <button type="button" class="p3d-btn" :disabled="isLoading" @click="handleLoadDemo">
          加载示例结构
        </button>
      </div>
    </section>

    <!-- 2. 渲染控制条 -->
    <section class="p3d-control-bar" aria-label="3D 渲染与着色控制">
      <div class="p3d-ctrl-group">
        <label class="p3d-lbl" for="p3d-style-sel">样式</label>
        <select id="p3d-style-sel" v-model="renderStyle" class="p3d-select compact">
          <option value="cartoon">Cartoon 飘带</option>
          <option value="stick">Stick 棍棒</option>
          <option value="sphere">Sphere 球体</option>
          <option value="line">Line 线框</option>
        </select>

        <label class="p3d-lbl" for="p3d-color-sel">着色</label>
        <select id="p3d-color-sel" v-model="colorScheme" class="p3d-select compact">
          <option value="plddt">pLDDT 置信度</option>
          <option value="ss">二级结构</option>
          <option value="spectrum">N→C 光谱</option>
        </select>

        <label class="p3d-check">
          <input v-model="showSurface" type="checkbox" />
          <span>分子表面</span>
        </label>
        <label class="p3d-check">
          <input v-model="isSpinning" type="checkbox" />
          <span>自转</span>
        </label>
      </div>

      <div class="p3d-ctrl-group">
        <input
          v-model="highlightRangeInput"
          type="text"
          class="p3d-input narrow"
          placeholder="高亮残基区间 (如 1-5, 10-25)"
          @keydown="onHighlightKeydown"
        />
        <button type="button" class="p3d-btn" @click="applyStyleAndRender">应用高亮</button>
        <button type="button" class="p3d-btn" :disabled="!loadedMeta" @click="resetCamera">重置视角</button>
        <button type="button" class="p3d-btn" :disabled="!loadedMeta" @click="exportPngSnapshot">导出 PNG</button>
      </div>
    </section>

    <div v-if="errorMsg" class="p3d-error-banner" role="alert">{{ errorMsg }}</div>

    <!-- 3. WebGL 3D 视口 -->
    <div class="p3d-stage-wrap">
      <div ref="canvasHostRef" class="p3d-canvas-host"></div>
      <div v-if="!loadedMeta && !isLoading" class="p3d-empty-hint">
        <p>请选择任务目录内结构文件、输入 AlphaFold/PDB 编号，或直接导入本地 `.pdb` / `.cif` 文件。</p>
        <p class="p3d-empty-sub">左键拖拽旋转 · 滚轮缩放 · 中键/右键平移</p>
      </div>
    </div>

    <!-- 4. 底部图例与元数据状态栏 -->
    <footer class="p3d-footer">
      <div class="p3d-legend">
        <span class="leg-title">pLDDT 置信度:</span>
        <span class="leg-item"><i class="leg-dot" style="background:#0053D6"></i>&ge;90 极高</span>
        <span class="leg-item"><i class="leg-dot" style="background:#65CBF3"></i>70-90 良好</span>
        <span class="leg-item"><i class="leg-dot" style="background:#FFDB13"></i>50-70 较低</span>
        <span class="leg-item"><i class="leg-dot" style="background:#FF7D45"></i>&lt;50 无序</span>
      </div>
      <div class="p3d-meta">
        <template v-if="loadedMeta">
          <span>{{ loadedMeta.filename }}</span>
          <span>{{ loadedMeta.format.toUpperCase() }}</span>
          <span>{{ (loadedMeta.sizeBytes / 1024).toFixed(1) }} KB</span>
          <span>{{ loadedMeta.cached ? '本地/缓存' : '已缓存' }}</span>
        </template>
        <span v-else>就绪（3Dmol 按需引擎）</span>
      </div>
    </footer>
  </dialog>
</template>

<style scoped>
dialog.protein-3d-dialog {
  width: min(1040px, 94vw);
  height: min(740px, 90vh);
  padding: 0;
  border: 1px solid #cbd5e1;
  border-radius: 14px;
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
  overflow: hidden;
}

dialog.protein-3d-dialog[open] {
  display: flex;
  flex-direction: column;
}

dialog.protein-3d-dialog:modal {
  overscroll-behavior: contain;
}

dialog.protein-3d-dialog::backdrop {
  background: rgba(15, 23, 42, 0.52);
  backdrop-filter: blur(3px);
  overflow: hidden;
  overscroll-behavior: contain;
}

.p3d-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.p3d-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  color: #0f172a;
}

.p3d-subtitle {
  margin: 2px 0 0 0;
  font-size: 0.78rem;
  color: #64748b;
}

.p3d-close-btn {
  padding: 5px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  color: #334155;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.p3d-close-btn:hover {
  background: #f1f5f9;
}

.p3d-source-bar,
.p3d-control-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.p3d-control-bar {
  background: #f8fafc;
}

.p3d-source-group,
.p3d-ctrl-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.p3d-lbl {
  font-size: 0.76rem;
  font-weight: 600;
  color: #475569;
}

.p3d-select,
.p3d-input {
  height: 30px;
  padding: 0 8px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  font-size: 0.78rem;
  color: #0f172a;
  background: #ffffff;
}

.p3d-select.compact {
  min-width: 108px;
}

.p3d-input {
  width: 170px;
}

.p3d-input.narrow {
  width: 180px;
}

.p3d-btn {
  height: 30px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
  color: #1e293b;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
}

.p3d-btn:hover:not(:disabled) {
  background: #eff6ff;
  border-color: #93c5fd;
}

.p3d-btn.primary {
  border-color: #2563eb;
  background: #2563eb;
  color: #ffffff;
}

.p3d-btn.primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.p3d-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.p3d-check {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.76rem;
  color: #334155;
  cursor: pointer;
}

.sr-only-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

.p3d-error-banner {
  padding: 8px 16px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 0.8rem;
  border-bottom: 1px solid #fecaca;
}

.p3d-stage-wrap {
  position: relative;
  flex: 1;
  min-height: 360px;
  background: #f8fafc;
}

.p3d-canvas-host {
  position: relative;
  width: 100%;
  height: 100%;
}

.p3d-empty-hint {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  color: #64748b;
  pointer-events: none;
}

.p3d-empty-hint p {
  margin: 4px 0;
  font-size: 0.86rem;
}

.p3d-empty-sub {
  font-size: 0.76rem;
  color: #94a3b8;
}

.p3d-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
  font-size: 0.74rem;
  color: #64748b;
}

.p3d-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.leg-title {
  font-weight: 600;
  color: #334155;
}

.leg-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.leg-dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.p3d-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
