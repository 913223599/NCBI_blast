<script setup lang="ts">
/**
 * CitationsDialog - 学术引用与 BibTeX 一键导出原生弹窗
 * 遵循 Modern Web Guidance `dialog` 规范：
 * - 原生 <dialog> + showModal() + closedby="any" + pointerdown/pointerup 回退
 * - 关闭时立即重置 dialog.returnValue = ''
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { apiGet } from '../../bridge/electron-bridge'
import { notifyUser } from '../../utils/notify'
import { useI18n } from '../../locales'
import { createLogger } from '../../utils/logger'
const logger = createLogger('CitationsDialog')

export interface CitationItem {
  id: string
  name: string
  module: string
  authors: string
  year: number
  title: string
  journal: string
  doi: string
}

const props = withDefaults(
  defineProps<{
    open: boolean
    defaultModule?: string
  }>(),
  {
    defaultModule: 'all',
  }
)

const emit = defineEmits<{
  (e: 'update:open', val: boolean): void
}>()

const { t } = useI18n()
const dialogRef = ref<HTMLDialogElement | null>(null)
const isLoading = ref(false)
const citations = ref<CitationItem[]>([])
const selectedModule = ref<string>(props.defaultModule)
let pressedOutside = false

const moduleOptions = computed(() => [
  { id: 'all', label: t('citations.mod_all') },
  { id: 'figure_studio', label: t('citations.mod_figure_studio') },
  { id: 'phylo', label: t('citations.mod_phylo') },
  { id: 'annotation', label: t('citations.mod_annotation') },
  { id: 'analysis', label: t('citations.mod_analysis') },
  { id: 'assembly', label: t('citations.mod_assembly') },
  { id: 'blast', label: t('citations.mod_blast') },
  { id: 'viewer', label: t('citations.mod_viewer') },
])

const filteredCitations = computed(() => {
  if (selectedModule.value === 'all') return citations.value
  return citations.value.filter((item) => item.module === selectedModule.value)
})

function formatPlainReference(item: CitationItem): string {
  return `${item.authors} (${item.year}). ${item.title}. ${item.journal}. https://doi.org/${item.doi}`
}

function formatBibtexEntry(item: CitationItem): string {
  const key = `${item.id}_${item.year}`.replace(/[^a-zA-Z0-9_]/g, '_')
  return [
    `@article{${key},`,
    `  author  = {${item.authors}},`,
    `  title   = {${item.title}},`,
    `  journal = {${item.journal}},`,
    `  year    = {${item.year}},`,
    `  doi     = {${item.doi}}`,
    `}`,
  ].join('\n')
}

async function loadCitations(): Promise<void> {
  if (citations.value.length > 0 || isLoading.value) return
  isLoading.value = true
  try {
    const res = await apiGet('/api/core/citations')
    if (res && Array.isArray(res.tools)) {
      citations.value = res.tools
    }
  } catch (err) {
    logger.warn('[CitationsDialog] 加载文献库失败:', err)
    notifyUser(t('citations.load_failed'), 'warning')
  } finally {
    isLoading.value = false
  }
}

async function copyText(text: string, successMsg: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    notifyUser(successMsg, 'success')
  } catch {
    notifyUser(t('citations.clipboard_failed'), 'warning')
  }
}

function copyAllPlain(): void {
  const list = filteredCitations.value
  if (!list.length) return
  const text = list.map((item, idx) => `[${idx + 1}] ${formatPlainReference(item)}`).join('\n')
  void copyText(text, t('citations.copied_plain_all', { count: list.length }))
}

function copyAllBibtex(): void {
  const list = filteredCitations.value
  if (!list.length) return
  const text = list.map((item) => formatBibtexEntry(item)).join('\n\n')
  void copyText(text, t('citations.copied_bibtex_all', { count: list.length }))
}

function closeDialog(): void {
  const dialog = dialogRef.value
  if (dialog && typeof dialog.close === 'function') {
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
  emit('update:open', false)
}

function isPointerOutside(event: PointerEvent, dialog: HTMLDialogElement): boolean {
  const rect = dialog.getBoundingClientRect()
  return (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
}

function handlePointerDown(event: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  pressedOutside = isPointerOutside(event, dialog)
}

function handlePointerUp(event: PointerEvent): void {
  const dialog = dialogRef.value
  if (!dialog || 'closedBy' in HTMLDialogElement.prototype) return
  if (pressedOutside && isPointerOutside(event, dialog)) {
    dialog.close('close')
  }
  pressedOutside = false
}

watch(
  () => props.open,
  async (val) => {
    if (val) {
      selectedModule.value = props.defaultModule || 'all'
      void loadCitations()
    }
    await nextTick()
    const dialog = dialogRef.value
    if (!dialog) return
    if (val && !dialog.open && typeof dialog.showModal === 'function') {
      dialog.showModal()
    } else if (!val && dialog.open) {
      dialog.close('close')
    }
  }
)

onMounted(() => {
  const dialog = dialogRef.value
  if (!dialog) return
  dialog.addEventListener('pointerdown', handlePointerDown)
  dialog.addEventListener('pointerup', handlePointerUp)
  if (props.open) {
    void loadCitations()
    if (!dialog.open && typeof dialog.showModal === 'function') {
      dialog.showModal()
    }
  }
})

onUnmounted(() => {
  const dialog = dialogRef.value
  if (!dialog) return
  dialog.removeEventListener('pointerdown', handlePointerDown)
  dialog.removeEventListener('pointerup', handlePointerUp)
})
</script>

<template>
  <dialog
    ref="dialogRef"
    class="citations-dialog"
    closedby="any"
    aria-labelledby="citations-dialog-title"
    @close="handleDialogClose"
  >
    <div class="citations-shell">
      <header class="citations-header">
        <div>
          <h1 id="citations-dialog-title" class="citations-title">{{ t('citations.title') }}</h1>
          <p class="citations-sub">{{ t('citations.subtitle') }}</p>
        </div>
        <button type="button" class="close-icon-btn" :aria-label="t('citations.close_aria')" @click="closeDialog">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </header>

      <div class="citations-toolbar">
        <div class="module-tabs" role="tablist" :aria-label="t('citations.filter_aria')">
          <button
            v-for="mod in moduleOptions"
            :key="mod.id"
            type="button"
            class="mod-tab"
            :class="{ active: selectedModule === mod.id }"
            @click="selectedModule = mod.id"
          >
            {{ mod.label }}
          </button>
        </div>
        <div class="export-btns">
          <button type="button" class="btn-outline" :disabled="filteredCitations.length === 0" @click="copyAllPlain">
            {{ t('citations.copy_plain_all', { count: filteredCitations.length }) }}
          </button>
          <button type="button" class="btn-primary" :disabled="filteredCitations.length === 0" @click="copyAllBibtex">
            {{ t('citations.copy_bibtex_all') }}
          </button>
        </div>
      </div>

      <div class="citations-body">
        <div v-if="isLoading" class="state-hint">{{ t('citations.loading') }}</div>
        <div v-else-if="filteredCitations.length === 0" class="state-hint">{{ t('citations.empty') }}</div>
        <ul v-else class="citation-list">
          <li v-for="item in filteredCitations" :key="item.id" class="citation-card">
            <div class="cit-top">
              <div class="cit-name-row">
                <strong class="cit-name">{{ item.name }}</strong>
                <span class="cit-badge">{{ item.module }}</span>
                <span class="cit-year">{{ item.year }}</span>
              </div>
              <div class="cit-item-actions">
                <button
                  type="button"
                  class="mini-btn"
                  @click="copyText(formatPlainReference(item), t('citations.copied_item_plain', { name: item.name }))"
                >
                  {{ t('citations.btn_cite') }}
                </button>
                <button
                  type="button"
                  class="mini-btn"
                  @click="copyText(formatBibtexEntry(item), t('citations.copied_item_bibtex', { name: item.name }))"
                >
                  {{ t('citations.btn_bibtex') }}
                </button>
              </div>
            </div>
            <p class="cit-ref selectable">{{ formatPlainReference(item) }}</p>
            <div class="cit-doi">
              <span>DOI:</span>
              <a :href="`https://doi.org/${item.doi}`" target="_blank" rel="noopener noreferrer">{{ item.doi }}</a>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.citations-dialog {
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  color: var(--text-primary);
  width: min(820px, calc(100vw - 32px));
  max-height: 82vh;
  margin: auto;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.citations-dialog:modal {
  overscroll-behavior: contain;
}

.citations-dialog::backdrop {
  background: rgba(15, 23, 42, 0.45);
  overflow: hidden;
  overscroll-behavior: contain;
}

.citations-shell {
  display: flex;
  flex-direction: column;
  max-height: 82vh;
}

.citations-header {
  padding: 18px 22px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.citations-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.citations-sub {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.close-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: #f1f5f9;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.close-icon-btn:hover {
  background: #e2e8f0;
  color: var(--text-primary);
}

.citations-toolbar {
  padding: 12px 22px;
  background: #f8fafc;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.module-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mod-tab {
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background: #ffffff;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.mod-tab.active {
  background: #0f766e;
  color: #ffffff;
  border-color: #0f766e;
}

.export-btns {
  display: flex;
  gap: 8px;
}

.btn-outline,
.btn-primary {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  font-weight: 600;
}

.btn-outline {
  background: #ffffff;
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-outline:hover:not(:disabled) {
  background: #f1f5f9;
}

.btn-primary {
  background: #0f766e;
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: #115e59;
}

.btn-outline:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.citations-body {
  padding: 16px 22px;
  overflow-y: auto;
  flex: 1;
}

.state-hint {
  text-align: center;
  color: var(--text-muted);
  padding: 36px 0;
  font-size: 0.875rem;
}

.citation-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.citation-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  background: #ffffff;
}

.cit-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.cit-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cit-name {
  font-size: 0.9rem;
  color: var(--text-primary);
}

.cit-badge {
  font-size: 0.7rem;
  font-weight: 600;
  color: #0f766e;
  background: #ccfbf1;
  padding: 1px 7px;
  border-radius: 999px;
}

.cit-year {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.cit-item-actions {
  display: flex;
  gap: 6px;
}

.mini-btn {
  padding: 3px 8px;
  font-size: 0.74rem;
  font-weight: 600;
  border-radius: 5px;
  background: #f1f5f9;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.mini-btn:hover {
  background: #e2e8f0;
  color: var(--text-primary);
}

.cit-ref {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 4px;
}

.cit-doi {
  font-size: 0.76rem;
  color: var(--text-muted);
  display: flex;
  gap: 6px;
  align-items: center;
}
</style>
