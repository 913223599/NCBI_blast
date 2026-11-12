<script setup lang="ts">
/**
 * Sangon16SPipelineModule - 生工 16S 测序结果自动化 BLAST 与导出
 * 职责：
 * 1. 一键检查新订单（扫描邮件、去重、过滤非测序通知、自动建目录并缓存下载链接）；
 * 2. 以订单表为核心视图，提供纯前端阶段筛选（全部 / 待下载 / 处理中 / 已完成）与按状态自适应的行内主操作；
 * 3. 支持浏览器下载目录压缩包自动识别与单订单/批量认领、自动解压、16S BLAST 比对、11 列 CSV 导出预览及发信；
 * 4. 将低频开关收敛至顶栏「更多」菜单，原始邮件记录下沉至默认折叠的辅助组件。
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import PathField from '../components/PathField.vue'
import CleanupDialog from '../components/CleanupDialog.vue'
import PaginationBar from '../components/PaginationBar.vue'
import PopoverMenu from '../components/PopoverMenu.vue'
import SangonMailRecords from '../components/SangonMailRecords.vue'
import SangonIgnoreModal from '../components/SangonIgnoreModal.vue'
import SangonAccountModal from '../components/SangonAccountModal.vue'
import type { CleanupOption } from '../components/CleanupDialog.vue'
import type {
  SangonAuthMeta,
  SangonOrderItem,
  ScannedMailItem,
  MailScanSummary,
  DownloadCandidateItem,
  IgnoredOrderRule,
  OrderFilterKey,
  SangonRuntimeState
} from '../sangonTypes'
import { getJson, postJson, openLocalPath, describeMigration } from '../api'

const API = '/api/other_tools/sangon_16s'
const MAIL_API = '/api/other_tools/mail_pipeline'

const sangonRoot = ref('')
const downloadsDir = ref('')
const rootExists = ref(false)
const db16sReady = ref(false)
const orders = ref<SangonOrderItem[]>([])
const downloadCandidates = ref<DownloadCandidateItem[]>([])
const ignoredDownloadCount = ref(0)
const ignoredOrdersMap = ref<Record<string, IgnoredOrderRule>>({})
const ignoreKeywords = ref<string[]>([])
const showIgnoreModal = ref(false)
const mailAccount = ref('')

const orderFilter = ref<OrderFilterKey>('all')
const orderPage = ref(1)
const orderPageSize = ref(6)

const checkedOrderNames = ref<string[]>([])
const selectedOrder = ref<SangonOrderItem | null>(null)
const resultHeaders = ref<string[]>([])
const resultRows = ref<Array<Record<string, string>>>([])
const searchKeyword = ref('')
const resultPage = ref(1)
const resultPageSize = ref(20)
const forceReblast = ref(false)

const scannedMails = ref<ScannedMailItem[]>([])
const hasScannedMails = ref(false)
const scanningMail = ref(false)
const recentCreatedDirs = ref<string[]>([])
const mailRecordsRef = ref<InstanceType<typeof SangonMailRecords> | null>(null)

const mailFilter = ref({
  dedup: true,
  autoCreate: true,
  ignoreHistory: false
})

const mailSummary = ref<MailScanSummary>({
  rawTotal: 0,
  uniqueTotal: 0,
  dedupRemoved: 0,
  skippedKnown: 0,
  ignoredCount: 0,
  newCount: 0,
  createdCount: 0,
  existingCount: 0,
  nonSequencingCount: 0
})

const busy = ref(false)
const actionMessage = ref('')
const errorMessage = ref('')

const showCleanup = ref(false)
const cleanupTargetOrders = ref<string[]>([])

const showAuthModal = ref(false)
const imapMasked = ref('')
const imapReady = ref(false)
const imapFile = ref('')
const imapKeyInput = ref('')

const sangonAuth = ref<SangonAuthMeta>({
  account: '',
  password_ready: false,
  password_masked: '',
  password_file: '',
  auto_confirm_fee: true
})
const showSangonAuthModal = ref(false)
const sangonAuthHint = ref('')
const autoConfirmFee = ref(true)
const initializedSangonSettings = ref(false)
const autoBlastAfterDownload = ref(true)
const pendingDownloadTask = ref<{ orderNames: string[]; autoRunBlast: boolean } | null>(null)

const showSendModal = ref(false)
const sendingMail = ref(false)
const sendForm = ref({
  orderDirName: '',
  to: '',
  subject: '',
  extraNote: ''
})

const runtime = ref<SangonRuntimeState>({
  running: false,
  current_order: null,
  current_stage: 'idle',
  progress: 0,
  started_at: null,
  finished_at: null,
  last_message: '',
  summary: { total: 0, processed: 0, skipped_missing: 0, failed: 0 },
  logs: []
})
const trackingRun = ref(false)
const showLogs = ref(false)

const cleanupOptions: CleanupOption[] = [
  { key: 'raw_extracted', label: '解压数据 (原始数据/)', desc: '删除解压出的文件，保留原始压缩包', checked: true },
  { key: 'blast_cache', label: 'BLAST 中间缓存', desc: '删除 results/blast/<订单>_16s 报告缓存', checked: true },
  { key: 'result_csv', label: '鉴定结果 CSV', desc: '删除 BLAST结果/16S鉴定结果.csv' },
  { key: 'order_dir', label: '整个订单目录', desc: '删除该订单全部文件夹与压缩包（同时保留清理记忆防止扫描重建）', danger: true },
  { key: 'scan_index', label: '清除扫描去重记忆', desc: '清空选中订单的已扫描/已清理记录，之后可被检查新订单再次识别' }
]

let pollTimer: ReturnType<typeof setInterval> | null = null
let followUpTimer: ReturnType<typeof setTimeout> | null = null

function isProcessingStatus(status: SangonOrderItem['status']): boolean {
  return status === 'downloaded' || status === 'extracted' || status === 'blasted'
}

function isOrderMarkedNew(ord: SangonOrderItem): boolean {
  return !ord.ignored && Boolean(ord.is_new || recentCreatedDirs.value.includes(ord.dir_name))
}

function normalizeOrderKeyFrontend(raw: string): string {
  const s = String(raw || '').trim()
  const m = s.match(/(?<!\d)(\d{10})(?!\d)/)
  if (m && m[1]) return m[1]
  if (s.includes('_')) return s.split('_', 2)[1]?.trim() || s
  return s
}

const activeOrders = computed(() => orders.value.filter(o => !o.ignored))
const ignoredOrders = computed(() => orders.value.filter(o => Boolean(o.ignored)))
const ignoredOrdersCount = computed(() => Object.keys(ignoredOrdersMap.value || {}).length)
const claimableCandidates = computed(() =>
  downloadCandidates.value.filter(c => !c.archived && !c.ignored)
)

const orderFilterTabs = computed(() => {
  let pending = 0
  let processing = 0
  let completed = 0
  for (const o of activeOrders.value) {
    if (o.status === 'pending') pending += 1
    else if (o.status === 'completed') completed += 1
    else processing += 1
  }
  return [
    { key: 'all' as OrderFilterKey, label: '全部', count: activeOrders.value.length },
    { key: 'pending' as OrderFilterKey, label: '待下载', count: pending },
    { key: 'processing' as OrderFilterKey, label: '处理中', count: processing },
    { key: 'completed' as OrderFilterKey, label: '已完成', count: completed },
    { key: 'ignored' as OrderFilterKey, label: '已忽略', count: ignoredOrders.value.length }
  ]
})

const filteredOrders = computed(() => {
  const f = orderFilter.value
  if (f === 'ignored') return ignoredOrders.value
  if (f === 'all') return activeOrders.value
  if (f === 'pending') return activeOrders.value.filter(o => o.status === 'pending')
  if (f === 'completed') return activeOrders.value.filter(o => o.status === 'completed')
  return activeOrders.value.filter(o => isProcessingStatus(o.status))
})

const pagedOrders = computed(() => {
  const start = (orderPage.value - 1) * orderPageSize.value
  return filteredOrders.value.slice(start, start + orderPageSize.value)
})

function hasOrderSourceData(ord: SangonOrderItem): boolean {
  return Boolean(
    ord.zip_count > 0 ||
    ord.consensus_fasta_count > 0 ||
    ord.blast_report_count > 0 ||
    ord.download_zip_ready
  )
}

function isOrderRunnable(ord: SangonOrderItem, reblast = forceReblast.value): boolean {
  if (ord.ignored) return false
  if (ord.status !== 'completed') return hasOrderSourceData(ord)
  return reblast && (ord.zip_count > 0 || ord.consensus_fasta_count > 0 || ord.blast_report_count > 0)
}

const runnableOrdersCount = computed(() =>
  activeOrders.value.filter(o => isOrderRunnable(o)).length
)

function hasOrderDownloadChannel(ord: SangonOrderItem): boolean {
  return Boolean(ord.download_zip_ready || ord.download_url || ord.cx_order_id)
}

function isOrderDownloadable(ord: SangonOrderItem): boolean {
  return !ord.ignored && ord.status === 'pending' && ord.zip_count === 0 && hasOrderDownloadChannel(ord)
}

const downloadableOrders = computed(() =>
  activeOrders.value.filter(o => isOrderDownloadable(o))
)

const checkedDownloadableNames = computed(() =>
  checkedOrderNames.value.filter(name => {
    const ord = activeOrders.value.find(o => o.dir_name === name)
    return ord ? isOrderDownloadable(ord) : false
  })
)

const targetDownloadCount = computed(() =>
  checkedDownloadableNames.value.length > 0
    ? checkedDownloadableNames.value.length
    : downloadableOrders.value.length
)

const awaitingDownloadCount = computed(() =>
  activeOrders.value.filter(o => o.status === 'pending' && !hasOrderSourceData(o)).length
)

const runtimeLogsList = computed(() => runtime.value?.logs || [])

const activeAdvancedTags = computed(() => {
  const tags: string[] = []
  if (forceReblast.value) tags.push('强制重新比对')
  if (!autoBlastAfterDownload.value) tags.push('仅下载暂不比对')
  if (!autoConfirmFee.value) tags.push('遇费用弹窗暂停')
  if (!mailFilter.value.dedup) tags.push('已关闭去重')
  if (!mailFilter.value.autoCreate) tags.push('仅识别不自动建目录')
  if (mailFilter.value.ignoreHistory) tags.push('忽略清理记忆')
  return tags
})

const filteredResultRows = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return resultRows.value
  return resultRows.value.filter(row =>
    Object.values(row).some(v => String(v || '').toLowerCase().includes(kw))
  )
})

const pagedResultRows = computed(() => {
  const start = (resultPage.value - 1) * resultPageSize.value
  return filteredResultRows.value.slice(start, start + resultPageSize.value)
})

watch(searchKeyword, () => {
  resultPage.value = 1
})

watch(orderFilter, () => {
  const visible = new Set(filteredOrders.value.map(o => o.dir_name))
  checkedOrderNames.value = checkedOrderNames.value.filter(n => visible.has(n))
})

watch([orderFilter, () => filteredOrders.value.length], () => {
  const maxPage = Math.max(1, Math.ceil(filteredOrders.value.length / orderPageSize.value))
  if (orderPage.value > maxPage) orderPage.value = maxPage
})

const completedOrdersCount = computed(() => activeOrders.value.filter(o => o.status === 'completed').length)
const totalIdentifiedSamples = computed(() => activeOrders.value.reduce((acc, o) => acc + (o.total_samples || 0), 0))
const allChecked = computed(
  () => filteredOrders.value.length > 0 && filteredOrders.value.every(o => checkedOrderNames.value.includes(o.dir_name))
)

function statusLabel(st: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    blasted: '待导出',
    extracted: '待比对',
    downloaded: '待解压',
    pending: '待下载'
  }
  return map[st] || st
}

function setInfo(msg: string): void {
  actionMessage.value = msg
  errorMessage.value = ''
}

function setError(err: any): void {
  errorMessage.value = err?.message || String(err)
  actionMessage.value = ''
}

function toggleCheckAll(ev: Event): void {
  const checked = (ev.target as HTMLInputElement).checked
  const currentNames = filteredOrders.value.map(o => o.dir_name)
  if (checked) {
    const merged = new Set([...checkedOrderNames.value, ...currentNames])
    checkedOrderNames.value = Array.from(merged)
  } else {
    checkedOrderNames.value = checkedOrderNames.value.filter(n => !currentNames.includes(n))
  }
}

async function loadOverview(): Promise<void> {
  try {
    const data = await getJson(`${API}/overview`)
    sangonRoot.value = data.sangon_root || sangonRoot.value
    downloadsDir.value = data.downloads_dir || downloadsDir.value
    rootExists.value = Boolean(data.root_exists)
    db16sReady.value = Boolean(data.db_16s_ready)
    orders.value = data.orders || []
    downloadCandidates.value = data.download_candidates || []
    ignoredDownloadCount.value = data.ignored_download_count || 0
    if (data.settings) {
      ignoredOrdersMap.value = data.settings.ignored_orders || {}
      ignoreKeywords.value = data.settings.ignore_subject_keywords || []
    }
    if (data.sangon_auth) {
      sangonAuth.value = data.sangon_auth
      if (!initializedSangonSettings.value) {
        autoConfirmFee.value = data.sangon_auth.auto_confirm_fee ?? true
        initializedSangonSettings.value = true
      }
    }
    const nextRuntime: SangonRuntimeState = data.runtime || runtime.value
    runtime.value = nextRuntime

    if (nextRuntime?.running) {
      trackingRun.value = true
      const pct = Number(nextRuntime.progress ?? 0)
      setInfo(`流水线运行中 (${pct}%)：${nextRuntime.last_message || '正在处理...'}`)
    } else if (trackingRun.value) {
      trackingRun.value = false
      const summary = nextRuntime?.summary
      const msg = nextRuntime?.last_message || '生工 16S 流水线处理结束'
      if (nextRuntime?.current_stage === 'failed') {
        setError(msg)
        showLogs.value = true
      } else {
        setInfo(msg)
        if (summary && ((summary.skipped_missing > 0 && summary.processed === 0) || summary.failed > 0)) {
          showLogs.value = true
        }
      }
      if (selectedOrder.value) {
        const refreshed = orders.value.find(o => o.dir_name === selectedOrder.value?.dir_name)
        if (refreshed?.has_result_csv) {
          await selectOrderAndLoadResults(refreshed)
        }
      }
    }

    if (!mailAccount.value) {
      try {
        const mailMeta = await getJson(`${MAIL_API}/overview`)
        mailAccount.value = mailMeta.config?.account || mailMeta.config?.smtp_account || ''
      } catch {
        // ignore
      }
    }

    const visibleSet = new Set(filteredOrders.value.map(o => o.dir_name))
    checkedOrderNames.value = checkedOrderNames.value.filter(n => visibleSet.has(n))

    if (selectedOrder.value) {
      const updated = orders.value.find(o => o.dir_name === selectedOrder.value?.dir_name) || null
      if (updated && updated.ignored && orderFilter.value !== 'ignored') {
        selectedOrder.value = null
        resultRows.value = []
      } else {
        selectedOrder.value = updated
      }
    }
    if (!selectedOrder.value && activeOrders.value.length > 0) {
      const firstCompleted = activeOrders.value.find(o => o.has_result_csv) || activeOrders.value[0]
      if (firstCompleted) await selectOrderAndLoadResults(firstCompleted)
    }
  } catch (err: any) {
    errorMessage.value = `加载失败: ${err.message || err}`
  }
}

async function selectOrderAndLoadResults(order: SangonOrderItem): Promise<void> {
  selectedOrder.value = order
  resultPage.value = 1
  if (!order.has_result_csv) {
    resultRows.value = []
    return
  }
  try {
    const data = await getJson(`${API}/order/${encodeURIComponent(order.dir_name)}/results`)
    resultHeaders.value = data.headers || []
    resultRows.value = data.rows || []
  } catch (err: any) {
    setError(err)
  }
}

async function handleSaveRoot(newRoot: string): Promise<void> {
  busy.value = true
  setInfo('正在更新目录并迁移数据...')
  try {
    const data = await postJson(`${API}/settings`, { sangon_root: newRoot, migrate: true })
    sangonRoot.value = data.settings?.sangon_root || newRoot
    const migMsg = describeMigration(data.migration)
    setInfo(migMsg ? `目录已更新。${migMsg}` : '目录已更新')
    selectedOrder.value = null
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleSaveDownloadsDir(newDl: string): Promise<void> {
  busy.value = true
  setInfo('正在更新浏览器下载目录...')
  try {
    const data = await postJson(`${API}/settings`, { downloads_dir: newDl, migrate: false })
    downloadsDir.value = data.settings?.downloads_dir || newDl
    setInfo('浏览器下载目录已更新')
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleImportDownloads(autoCreateOrder = false, targetOrders: string[] = []): Promise<void> {
  busy.value = true
  const orderScope = targetOrders.length ? targetOrders : checkedOrderNames.value
  setInfo(targetOrders.length === 1 ? `正在认领订单 ${targetOrders[0]} 的下载包...` : '正在从浏览器下载目录认领生工压缩包...')
  try {
    const data = await postJson(`${API}/import_downloads`, {
      sangon_root: sangonRoot.value || null,
      downloads_dir: downloadsDir.value || null,
      order_names: orderScope,
      auto_create_order: autoCreateOrder
    })
    const createdCnt = (data.created_dirs || []).length
    const createdPart = createdCnt ? `，新建订单目录 ${createdCnt} 个` : ''
    setInfo(
      `下载包认领完成：扫描到 ${data.scanned_zips} 个压缩包，新导入 ${data.imported_count} 个${createdPart}，跳过已归档 ${data.skipped_existing} 个`
    )
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleClaimSingleOrder(order: SangonOrderItem): Promise<void> {
  await handleImportDownloads(false, [order.dir_name])
}

async function handleClaimSingleCandidate(cand: DownloadCandidateItem): Promise<void> {
  if (cand.matched_dir_name) {
    await handleImportDownloads(false, [cand.matched_dir_name])
  } else {
    await handleImportDownloads(true, [cand.order_no])
  }
}

function _syncScannedMailsIgnoreState(targetKeys: Set<string>, ignored: boolean): void {
  if (!scannedMails.value.length || !targetKeys.size) return
  const existingOrderNos = new Set(
    orders.value.map(o => normalizeOrderKeyFrontend(o.order_no || o.dir_name))
  )
  let changed = false
  scannedMails.value = scannedMails.value.map(m => {
    const key = normalizeOrderKeyFrontend(m.order_no || m.dir_name)
    if (!key || !targetKeys.has(key) || m.dedup_status === 'non_sequencing') return m
    changed = true
    if (ignored) {
      return { ...m, ignored: true, dedup_status: 'ignored' }
    }
    const hasDir = Boolean(m.dir_ready || existingOrderNos.has(key))
    return {
      ...m,
      ignored: false,
      dir_ready: hasDir,
      dedup_status: hasDir ? 'existing' : 'new'
    }
  })
  if (changed) {
    mailSummary.value = {
      ...mailSummary.value,
      ignoredCount: scannedMails.value.filter(m => m.dedup_status === 'ignored').length,
      existingCount: scannedMails.value.filter(m => m.dedup_status === 'existing' || m.dedup_status === 'created').length,
      newCount: scannedMails.value.filter(m => m.dedup_status === 'new').length
    }
  }
}

async function handleIgnoreOrders(
  orderKeys: string[],
  ignore: boolean,
  reason = '',
  dirNames: Record<string, string> = {}
): Promise<void> {
  if (!orderKeys.length) return
  busy.value = true
  try {
    const data = await postJson(`${API}/ignore`, {
      order_keys: orderKeys,
      ignore,
      reason,
      dir_names: dirNames
    })
    ignoredOrdersMap.value = data.ignored_orders || {}
    const affected = new Set<string>((data.affected_orders || []).map((k: string) => normalizeOrderKeyFrontend(k)))
    for (const k of orderKeys) {
      const nk = normalizeOrderKeyFrontend(k)
      if (nk) affected.add(nk)
    }
    checkedOrderNames.value = checkedOrderNames.value.filter(
      name => !affected.has(normalizeOrderKeyFrontend(name))
    )
    _syncScannedMailsIgnoreState(affected, ignore)
    setInfo(
      ignore
        ? `已将 ${data.updated_count} 个订单设为全局忽略（已移入「已忽略」标签隐藏，本地文件与压缩包安全保留）`
        : `已取消忽略 ${data.updated_count} 个订单，已恢复至正常待办队列`
    )
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleToggleMailIgnore(mail: ScannedMailItem): Promise<void> {
  const key = mail.order_no || mail.dir_name
  if (!key) return
  const willIgnore = mail.dedup_status !== 'ignored'
  const dirMap = mail.order_no && mail.dir_name ? { [mail.order_no]: mail.dir_name } : {}
  await handleIgnoreOrders(
    [key],
    willIgnore,
    willIgnore ? `从通知邮件忽略 (${mail.dir_name || mail.order_no})` : '',
    dirMap
  )
}

async function handleSaveIgnoreKeywords(keywords: string[]): Promise<void> {
  busy.value = true
  try {
    const data = await postJson(`${API}/settings`, { ignore_subject_keywords: keywords })
    ignoreKeywords.value = data.settings?.ignore_subject_keywords || []
    setInfo(`非测序邮件主题过滤关键词已更新（共 ${ignoreKeywords.value.length} 项）`)
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

function openSendResultModal(order: SangonOrderItem): void {
  sendForm.value = {
    orderDirName: order.dir_name,
    to: mailAccount.value || '',
    subject: `生工 16S 测序鉴定结果 - ${order.dir_name}（共 ${order.total_samples} 样本）`,
    extraNote: ''
  }
  showSendModal.value = true
}

async function confirmSendResultMail(toSelf = false): Promise<void> {
  if (!sendForm.value.orderDirName) return
  sendingMail.value = true
  try {
    const targetTo = toSelf ? 'self' : (sendForm.value.to.trim() || 'self')
    const data = await postJson(`${API}/send_result`, {
      order_dir_name: sendForm.value.orderDirName,
      sangon_root: sangonRoot.value || null,
      to: targetTo,
      subject: sendForm.value.subject.trim() || null,
      extra_note: sendForm.value.extraNote.trim() || null
    })
    showSendModal.value = false
    setInfo(
      `结果邮件已发送至 ${data.to}：附件 ${data.attachment} (${(data.attachment_size / 1024).toFixed(1)} KB)，样本 ${data.total_samples}（命中 ${data.with_hits}）`
    )
  } catch (err) {
    setError(err)
  } finally {
    sendingMail.value = false
  }
}

async function handleCheckNewOrders(): Promise<void> {
  scanningMail.value = true
  setInfo('正在连接邮箱检查生工新订单...')
  try {
    const data = await postJson(`${API}/scan_mail`, {
      sangon_root: sangonRoot.value || null,
      page: 1,
      page_size: 200,
      dedup: mailFilter.value.dedup,
      only_new: false,
      auto_create: mailFilter.value.autoCreate,
      ignore_history: mailFilter.value.ignoreHistory
    })
    scannedMails.value = data.mails || []
    hasScannedMails.value = true
    const createdDirs: string[] = data.created_dirs || []
    recentCreatedDirs.value = createdDirs

    mailSummary.value = {
      rawTotal: data.raw_total || 0,
      uniqueTotal: data.unique_total || 0,
      dedupRemoved: data.dedup_removed || 0,
      skippedKnown: data.skipped_known || 0,
      ignoredCount: data.ignored_count || 0,
      newCount: data.new_count || 0,
      createdCount: data.created_count || 0,
      existingCount: data.existing_count || 0,
      nonSequencingCount: data.non_sequencing_count || 0
    }

    await loadOverview()

    const s = mailSummary.value
    if (createdDirs.length > 0) {
      const previewNames = createdDirs.slice(0, 3).join('、') + (createdDirs.length > 3 ? ' 等' : '')
      setInfo(`发现 ${createdDirs.length} 个新订单，已自动建目录：${previewNames}`)
      orderFilter.value = 'all'
      orderPage.value = 1
    } else if (s.newCount > 0 && !mailFilter.value.autoCreate) {
      setInfo(`发现 ${s.newCount} 封待建目录的新测序邮件（当前已关闭自动建目录，可在下方邮件记录中手动创建）`)
      mailRecordsRef.value?.expand()
    } else {
      const extraParts: string[] = [`已有订单 ${s.existingCount} 个`]
      if (s.dedupRemoved > 0) extraParts.push(`合并重复 ${s.dedupRemoved} 封`)
      if (s.nonSequencingCount > 0) extraParts.push(`过滤非测序通知 ${s.nonSequencingCount} 封`)
      if (s.ignoredCount > 0) extraParts.push(`跳过已全局忽略 ${s.ignoredCount} 条`)
      if (s.skippedKnown > 0) extraParts.push(`历史清理跳过 ${s.skippedKnown} 条`)
      setInfo(`检查完成：暂无新测序订单（${extraParts.join('，')}）`)
    }
  } catch (err) {
    setError(err)
  } finally {
    scanningMail.value = false
  }
}

async function handleInitOrderFromMail(mail: ScannedMailItem): Promise<void> {
  if (!mail.dir_name) return
  busy.value = true
  try {
    await postJson(`${API}/init_order`, {
      sangon_root: sangonRoot.value || null,
      dir_name: mail.dir_name,
      order_no: mail.order_no,
      subject: mail.subject,
      date_text: mail.date,
      cx_order_id: mail.cx_order_id,
      download_url: mail.download_url
    })
    mail.dir_ready = true
    mail.dedup_status = 'created'
    if (!recentCreatedDirs.value.includes(mail.dir_name)) {
      recentCreatedDirs.value = [...recentCreatedDirs.value, mail.dir_name]
    }
    setInfo(`已创建订单目录: ${mail.dir_name}`)
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleRunPipeline(orderNames: string[] = []): Promise<void> {
  const targets = orderNames.length
    ? orderNames
    : (orderFilter.value !== 'ignored' ? checkedOrderNames.value : [])

  if (!targets.length && runnableOrdersCount.value === 0) {
    setInfo(
      awaitingDownloadCount.value > 0
        ? `当前没有可执行比对的订单：剩余 ${awaitingDownloadCount.value} 个订单尚未下载压缩包，可点击「自动下载」自动拉取，或手动「打开下载页」下载后认领（非测序通知单可忽略）`
        : '当前没有需要处理的生工 16S 订单'
    )
    return
  }

  if (followUpTimer) {
    clearTimeout(followUpTimer)
    followUpTimer = null
  }
  setInfo(targets.length ? `正在启动订单处理: ${targets.join(', ')}...` : '正在启动生工 16S 待处理流水线...')
  try {
    const data = await postJson(`${API}/run_pipeline`, {
      sangon_root: sangonRoot.value,
      downloads_dir: downloadsDir.value || null,
      order_names: targets,
      evalue: '0.05',
      hitlist_size: '50',
      force_reblast: forceReblast.value
    })
    trackingRun.value = true
    runtime.value = data.runtime || runtime.value
    setInfo(runtime.value?.last_message || '任务已在后台运行')
    followUpTimer = setTimeout(() => {
      void loadOverview()
    }, 450)
  } catch (err) {
    trackingRun.value = false
    setError(err)
  }
}

function openCleanupModal(orderNames?: string[]): void {
  const targets = orderNames && orderNames.length
    ? orderNames
    : (checkedOrderNames.value.length
        ? checkedOrderNames.value
        : (activeOrders.value.length ? activeOrders.value.map(o => o.dir_name) : ['__ALL__']))
  cleanupTargetOrders.value = targets
  showCleanup.value = true
}

async function confirmCleanup(targets: string[]): Promise<void> {
  busy.value = true
  try {
    const data = await postJson(`${API}/cleanup`, {
      order_names: cleanupTargetOrders.value,
      targets
    })
    showCleanup.value = false
    recentCreatedDirs.value = []
    const clearedPart = data.scan_index_cleared ? `，清除扫描记忆 ${data.scan_index_cleared} 条` : ''
    setInfo(`已清理 ${data.removed_count} 项${clearedPart}，释放 ${data.freed_mb} MB`)
    await loadOverview()
    if (selectedOrder.value) await selectOrderAndLoadResults(selectedOrder.value)
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function openAuthEditor(): Promise<void> {
  imapKeyInput.value = ''
  try {
    const data = await getJson(`${MAIL_API}/overview`)
    imapReady.value = Boolean(data.auth?.imap_ready)
    imapMasked.value = data.auth?.imap_masked || ''
    imapFile.value = data.auth?.imap_file || ''
  } catch {
    // ignore
  }
  showAuthModal.value = true
}

async function saveImapAuth(): Promise<void> {
  if (!imapKeyInput.value.trim()) {
    showAuthModal.value = false
    return
  }
  busy.value = true
  try {
    const data = await postJson(`${MAIL_API}/auth`, {
      imap_auth_code: imapKeyInput.value.trim(),
      smtp_auth_code: null
    })
    imapReady.value = Boolean(data.auth?.imap_ready)
    imapMasked.value = data.auth?.imap_masked || ''
    showAuthModal.value = false
    setInfo('邮箱 Key 已更新')
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

function openSangonAuthEditor(hint = ''): void {
  sangonAuthHint.value = hint
  showSangonAuthModal.value = true
}

function closeSangonAuthEditor(): void {
  showSangonAuthModal.value = false
  pendingDownloadTask.value = null
}

async function handleSaveSangonAuth(payload: {
  account: string
  password: string | null
  auto_confirm_fee: boolean
}): Promise<void> {
  busy.value = true
  try {
    const data = await postJson(`${API}/auth`, payload)
    if (data.sangon_auth) {
      sangonAuth.value = data.sangon_auth
      autoConfirmFee.value = data.sangon_auth.auto_confirm_fee ?? payload.auto_confirm_fee
    }
    showSangonAuthModal.value = false
    const nextTask = pendingDownloadTask.value
    pendingDownloadTask.value = null
    if (nextTask && sangonAuth.value.account && sangonAuth.value.password_ready) {
      setInfo('生工账号配置已保存，正在自动接续下载流程...')
      await handleAutoDownloadOrders(nextTask.orderNames, nextTask.autoRunBlast)
      return
    }
    setInfo('生工官网账号配置已保存（密码已独立存放于本地 .sangon_auth）')
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleClearSangonPassword(): Promise<void> {
  busy.value = true
  try {
    const data = await postJson(`${API}/auth`, { password: '' })
    if (data.sangon_auth) {
      sangonAuth.value = data.sangon_auth
    }
    setInfo('已清除本地保存的生工登录密码')
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleToggleAutoConfirmFee(): Promise<void> {
  try {
    const data = await postJson(`${API}/settings`, { auto_confirm_fee: autoConfirmFee.value })
    if (data.sangon_auth) {
      sangonAuth.value = data.sangon_auth
    } else {
      sangonAuth.value = { ...sangonAuth.value, auto_confirm_fee: autoConfirmFee.value }
    }
    setInfo(autoConfirmFee.value ? '已开启：遇到 KBSeq 费用确认弹窗将自动点击确定下载' : '已关闭：遇到费用确认弹窗将跳过并等待人工确认')
  } catch (err) {
    setError(err)
  }
}

async function handleAutoDownloadOrders(
  orderNames: string[] = [],
  autoRunBlast = autoBlastAfterDownload.value
): Promise<void> {
  const targets = orderNames.length
    ? orderNames
    : (orderFilter.value !== 'ignored' && checkedDownloadableNames.value.length > 0
        ? checkedDownloadableNames.value
        : [])

  const targetOrderObjs = targets.length
    ? activeOrders.value.filter(o => targets.includes(o.dir_name) && isOrderDownloadable(o))
    : downloadableOrders.value

  if (!targetOrderObjs.length) {
    setInfo('当前没有可自动下载的待处理订单（请确认已运行「检查新订单」获取下载链接，或直接点击待认领下载包）')
    return
  }

  const needsWebLogin = targetOrderObjs.some(
    o => !o.download_zip_ready && Boolean(o.download_url || o.cx_order_id)
  )
  if (needsWebLogin && (!sangonAuth.value.account || !sangonAuth.value.password_ready)) {
    pendingDownloadTask.value = { orderNames: targets, autoRunBlast }
    openSangonAuthEditor('检测到需登录生工官网下载压缩包，请先保存一次生工账号与登录密码（保存后将自动继续下载）。')
    return
  }

  if (followUpTimer) {
    clearTimeout(followUpTimer)
    followUpTimer = null
  }
  setInfo(
    autoRunBlast
      ? `正在启动自动下载并接续 16S 比对（待处理 ${targetOrderObjs.length} 个）...`
      : `正在启动自动认领/官网下载（待处理 ${targetOrderObjs.length} 个）...`
  )
  try {
    const data = await postJson(`${API}/download_orders`, {
      sangon_root: sangonRoot.value || null,
      downloads_dir: downloadsDir.value || null,
      order_names: targets,
      auto_run_blast: autoRunBlast,
      auto_confirm_fee: autoConfirmFee.value,
      evalue: '0.05',
      hitlist_size: '50',
      force_reblast: forceReblast.value
    })
    trackingRun.value = true
    showLogs.value = true
    runtime.value = data.runtime || runtime.value
    setInfo(runtime.value?.last_message || '自动下载任务已在后台启动')
    followUpTimer = setTimeout(() => {
      void loadOverview()
    }, 450)
  } catch (err: any) {
    trackingRun.value = false
    const detail = String(err?.message || err || '')
    if (detail.includes('生工账号配置') || detail.includes('账号与登录密码')) {
      pendingDownloadTask.value = { orderNames: targets, autoRunBlast }
      openSangonAuthEditor(detail)
    } else {
      setError(err)
    }
  }
}

onMounted(() => {
  loadOverview()
  pollTimer = setInterval(() => {
    if (runtime.value?.running || trackingRun.value) loadOverview()
  }, 1200)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (followUpTimer) clearTimeout(followUpTimer)
})
</script>

<template>
  <div class="sangon-module">
    <!-- 流程步骤 -->
    <div class="steps-strip">
      <div class="step-pill"><span>1</span> 检查新订单</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>2</span> 自动 / 网页下载</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>3</span> 认领下载包</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>4</span> 解压提取</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>5</span> 16S BLAST</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>6</span> 翻译导出</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>7</span> 邮件发送</div>
    </div>

    <!-- 指标 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">数据根目录</div>
        <div class="metric-val" :class="rootExists ? 'ok' : 'warn'">{{ rootExists ? '已就绪' : '不存在' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">本地 16S 库</div>
        <div class="metric-val" :class="db16sReady ? 'ok' : 'warn'">{{ db16sReady ? '已就绪' : '缺失' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已完成 / 有效订单</div>
        <div class="metric-val">{{ completedOrdersCount }} / {{ activeOrders.length }}</div>
        <div v-if="ignoredOrders.length > 0" class="metric-sub">已忽略 {{ ignoredOrders.length }} 个（移至已忽略标签）</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已鉴定样本</div>
        <div class="metric-val">{{ totalIdentifiedSamples }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">运行状态</div>
        <div class="metric-val" :class="runtime.running ? 'running' : 'idle'">
          {{ runtime.running ? `运行中 (${runtime.progress}%)` : '空闲' }}
        </div>
        <div class="metric-sub" :title="runtime.last_message || ''">{{ runtime.last_message || '-' }}</div>
      </div>
    </div>

    <!-- 目录完整路径展示与修改迁移 -->
    <div class="paths-panel">
      <PathField
        label="生工 16S 订单根目录（修改后自动迁移全部订单）"
        :path="sangonRoot"
        :busy="busy || runtime.running"
        @save="handleSaveRoot"
        @open="openLocalPath"
      />
      <PathField
        label="浏览器下载目录（扫描已下载的生工 *.zip 测序包，修改后不迁移原文件）"
        :path="downloadsDir"
        :busy="busy || runtime.running"
        save-label="保存目录"
        hint="仅切换浏览器下载目录用于识别生工测序压缩包，不会移动目录中的已有文件。"
        @save="handleSaveDownloadsDir"
        @open="openLocalPath"
      />
      <div v-if="claimableCandidates.length > 0" class="pending-dl-bar">
        <div class="pending-dl-header">
          <div class="pending-dl-title">
            <strong>发现 {{ claimableCandidates.length }} 个未归档测序压缩包（位于浏览器下载目录）</strong>
            <span class="pending-dl-desc">
              “认领”是指将从生工网页手动下载的 .zip 复制归档到对应订单「原始压缩包/」目录以便自动解压比对（保留下载原文件）；已处理或无需比对可点单包右侧「忽略」。
            </span>
          </div>
          <div class="pending-dl-actions">
            <button
              v-if="claimableCandidates.some(c => Boolean(c.matched_dir_name))"
              class="btn-mini primary"
              :disabled="busy || runtime.running"
              @click="handleImportDownloads(false)"
            >
              认领已匹配订单
            </button>
            <button class="btn-mini" :disabled="busy || runtime.running" @click="handleImportDownloads(true)">
              全部新建并认领
            </button>
          </div>
        </div>
        <div class="pending-dl-chips">
          <div
            v-for="cand in claimableCandidates"
            :key="cand.zip_path"
            class="dl-chip-card"
            :title="cand.zip_path"
          >
            <span class="dl-chip-name">{{ cand.zip_name }}</span>
            <span class="dl-chip-match">
              {{ cand.matched_dir_name ? `匹配 ${cand.matched_dir_name}` : '尚无订单目录' }}
            </span>
            <button
              class="chip-btn primary"
              :disabled="busy || runtime.running"
              @click="handleClaimSingleCandidate(cand)"
            >
              {{ cand.matched_dir_name ? '归档' : '建目录并归档' }}
            </button>
            <button
              class="chip-btn"
              :disabled="busy || runtime.running"
              @click="handleIgnoreOrders([cand.order_no], true, '从待认领下载包忽略')"
            >
              忽略
            </button>
          </div>
        </div>
      </div>
      <div v-if="selectedOrder" class="sub-paths">
        <div class="sub-path-item">
          <span class="sp-label">当前订单输入目录:</span>
          <code class="sp-code">{{ selectedOrder.order_path }}\原始压缩包</code>
          <button class="btn-mini" @click="openLocalPath(selectedOrder.order_path + '\\原始压缩包')">打开</button>
        </div>
        <div class="sub-path-item">
          <span class="sp-label">当前订单输出目录:</span>
          <code class="sp-code">{{ selectedOrder.order_path }}\BLAST结果</code>
          <button class="btn-mini" @click="openLocalPath(selectedOrder.order_path + '\\BLAST结果')">打开</button>
        </div>
      </div>
    </div>

    <!-- 精简操作栏 -->
    <div class="control-bar">
      <div class="control-left">
        <button class="btn-secondary" @click="handleCheckNewOrders" :disabled="scanningMail || runtime.running">
          {{ scanningMail ? '正在检查...' : '检查新订单' }}
        </button>
        <button
          class="btn-download"
          @click="handleAutoDownloadOrders([])"
          :disabled="runtime.running || targetDownloadCount === 0"
          :title="
            targetDownloadCount === 0
              ? '当前没有具备生工下载链接或本地待认领包的待下载订单'
              : (autoBlastAfterDownload
                  ? '优先认领本地包并登录生工官网自动下载其余订单，完成后直接接续解压与 16S BLAST 比对导出'
                  : '优先认领本地包并登录生工官网顺序下载压缩包')
          "
        >
          {{
            checkedDownloadableNames.length > 0
              ? (autoBlastAfterDownload ? `下载并比对所选 (${checkedDownloadableNames.length})` : `自动下载所选 (${checkedDownloadableNames.length})`)
              : (autoBlastAfterDownload ? `下载并比对 (${targetDownloadCount})` : `自动下载 (${targetDownloadCount})`)
          }}
        </button>
        <button
          class="btn-primary"
          @click="handleRunPipeline([])"
          :disabled="runtime.running || (orderFilter !== 'ignored' && checkedOrderNames.length === 0 && runnableOrdersCount === 0) || (orderFilter === 'ignored' && runnableOrdersCount === 0)"
          :title="runnableOrdersCount === 0 && checkedOrderNames.length === 0 && awaitingDownloadCount > 0 ? `剩余 ${awaitingDownloadCount} 个待处理订单尚无压缩包，可点击「自动下载」或手动「打开下载页」下载后认领` : ''"
        >
          {{
            runtime.running
              ? `运行中 (${runtime.progress ?? 0}%)...`
              : orderFilter !== 'ignored' && checkedOrderNames.length
                ? `运行所选 (${checkedOrderNames.length})`
                : `运行待处理 (${runnableOrdersCount})`
          }}
        </button>
        <span
          v-if="awaitingDownloadCount > 0 && runnableOrdersCount === 0 && !runtime.running"
          class="awaiting-dl-hint"
          title="订单目录内尚无 .zip 压缩包或 .1.fasta 主序列，需先从生工网页下载后认领"
        >
          待下载压缩包 {{ awaitingDownloadCount }} 个
        </span>
        <button
          v-if="checkedOrderNames.length > 0 && orderFilter !== 'ignored'"
          class="btn-outline"
          :disabled="busy || runtime.running"
          @click="handleIgnoreOrders(checkedOrderNames, true, '从订单列表批量忽略')"
        >
          批量忽略 ({{ checkedOrderNames.length }})
        </button>
        <button
          v-else-if="checkedOrderNames.length > 0 && orderFilter === 'ignored'"
          class="btn-outline highlight-claim"
          :disabled="busy || runtime.running"
          @click="handleIgnoreOrders(checkedOrderNames, false)"
        >
          批量取消忽略 ({{ checkedOrderNames.length }})
        </button>
        <span v-if="checkedOrderNames.length" class="sel-hint">已勾选 {{ checkedOrderNames.length }} 个订单</span>
        <span v-for="tag in activeAdvancedTags" :key="tag" class="adv-active-tag">{{ tag }}</span>
      </div>

      <div class="control-right">
        <button
          v-if="runtimeLogsList.length > 0"
          class="btn-outline"
          :class="{ 'active-trigger': showLogs }"
          @click="showLogs = !showLogs"
        >
          {{ showLogs ? '收起日志' : `运行日志 (${runtimeLogsList.length})` }}
        </button>
        <button class="btn-outline" @click="loadOverview" :disabled="scanningMail">刷新</button>
        <PopoverMenu align="right" :width="250">
          <template #trigger="{ open }">
            <button class="btn-outline" :class="{ 'active-trigger': open || activeAdvancedTags.length > 0 || ignoredOrdersCount > 0 }">
              更多与设置 ▾
            </button>
          </template>
          <template #default="{ close }">
            <div class="menu-section">
              <button class="menu-item" @click="close(); openSangonAuthEditor()">
                {{ sangonAuth.password_ready ? `生工账号配置 (${sangonAuth.account || '已配置'})` : '生工账号配置 (未配置)...' }}
              </button>
              <button class="menu-item" @click="close(); openAuthEditor()">邮箱 Key 配置</button>
              <button class="menu-item" @click="close(); showIgnoreModal = true">
                跳过与忽略规则{{ ignoredOrdersCount > 0 ? ` (${ignoredOrdersCount})` : '...' }}
              </button>
              <button
                class="menu-item"
                :disabled="busy || runtime.running"
                @click="close(); handleImportDownloads(false)"
              >
                扫描并认领浏览器下载包
              </button>
              <button
                class="menu-item danger"
                :disabled="runtime.running"
                @click="close(); openCleanupModal()"
              >
                {{ checkedOrderNames.length ? `清理所选订单 (${checkedOrderNames.length})...` : '清理历史数据...' }}
              </button>
            </div>
            <div class="menu-divider"></div>
            <div class="menu-section">
              <div class="menu-title">高级扫描与比对设置</div>
              <label class="menu-check">
                <input type="checkbox" v-model="autoBlastAfterDownload" />
                <span>自动下载后直接接续 16S 比对</span>
              </label>
              <label class="menu-check">
                <input type="checkbox" v-model="autoConfirmFee" @change="handleToggleAutoConfirmFee" />
                <span>自动确认 KBSeq 费用明细弹窗</span>
              </label>
              <label class="menu-check">
                <input type="checkbox" v-model="forceReblast" />
                <span>强制重新比对（清理旧缓存）</span>
              </label>
              <label class="menu-check">
                <input type="checkbox" v-model="mailFilter.dedup" />
                <span>扫描邮件按订单号去重</span>
              </label>
              <label class="menu-check">
                <input type="checkbox" v-model="mailFilter.autoCreate" />
                <span>发现新订单自动建目录</span>
              </label>
              <label class="menu-check">
                <input type="checkbox" v-model="mailFilter.ignoreHistory" />
                <span>忽略历史清理跳过记忆</span>
              </label>
            </div>
          </template>
        </PopoverMenu>
      </div>
    </div>

    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <div v-if="showLogs && runtimeLogsList.length > 0" class="panel-box sangon-log-panel">
      <div class="panel-box-header">
        <div class="order-header-left">
          <h4>生工 16S 运行日志（{{ runtimeLogsList.length }} 条）</h4>
          <span v-if="runtime.finished_at && !runtime.running" class="order-tip">
            最近结束于 {{ runtime.finished_at }}
          </span>
        </div>
        <button class="btn-mini" @click="showLogs = false">收起</button>
      </div>
      <pre class="sangon-log-console">{{ runtimeLogsList.join('\n') }}</pre>
    </div>

    <!-- 订单列表（带纯前端阶段筛选与自适应主操作） -->
    <div class="panel-box">
      <div class="panel-box-header order-header">
        <div class="order-header-left">
          <h4>订单列表</h4>
          <div class="seg-group">
            <button
              v-for="tab in orderFilterTabs"
              :key="tab.key"
              :class="['seg-btn', { active: orderFilter === tab.key }]"
              @click="orderFilter = tab.key"
            >
              <span>{{ tab.label }}</span>
              <span class="seg-count">{{ tab.count }}</span>
            </button>
          </div>
        </div>
        <div class="order-header-right">
          <span class="order-tip">点击行可切换下方结果预览</span>
        </div>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 32px"><input type="checkbox" :checked="allChecked" @change="toggleCheckAll" /></th>
            <th>订单目录</th>
            <th>状态</th>
            <th>压缩包</th>
            <th>*.1.fasta / AB1</th>
            <th>BLAST 报告</th>
            <th>样本数 (命中 / 未命中)</th>
            <th>更新时间</th>
            <th>下一步 / 操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="ord in pagedOrders"
            :key="ord.dir_name"
            :class="{ 'selected-row': selectedOrder?.dir_name === ord.dir_name, 'ignored-row': ord.ignored }"
            @click="selectOrderAndLoadResults(ord)"
          >
            <td @click.stop>
              <input type="checkbox" v-model="checkedOrderNames" :value="ord.dir_name" />
            </td>
            <td class="mono-cell bold-cell">
              <span>{{ ord.dir_name }}</span>
              <span v-if="isOrderMarkedNew(ord)" class="new-order-badge" title="新发现且尚未下载测序包的订单">新</span>
              <span
                v-if="ord.download_zip_ready && !ord.ignored"
                class="zip-ready-badge"
                :title="`浏览器下载目录已识别到压缩包: ${ord.download_zip_name}`"
              >
                包已就绪
              </span>
              <span
                v-if="ord.ignored && ord.ignore_reason"
                class="ignore-reason-tag"
                :title="`忽略原因: ${ord.ignore_reason}`"
              >
                {{ ord.ignore_reason }}
              </span>
            </td>
            <td>
              <span
                :class="['status-pill', ord.ignored ? 'ignored' : ord.status]"
                :title="ord.ignored ? `原状态: ${statusLabel(ord.status)}${ord.ignored_at ? ' · 忽略于 ' + ord.ignored_at : ''}` : ''"
              >
                {{ ord.ignored ? '已忽略' : statusLabel(ord.status) }}
              </span>
            </td>
            <td>{{ ord.zip_count }}</td>
            <td>{{ ord.consensus_fasta_count }} / {{ ord.ab1_count }}</td>
            <td>{{ ord.blast_report_count }}</td>
            <td>
              <template v-if="ord.has_result_csv">
                <strong>{{ ord.total_samples }}</strong>
                (<span class="hit-ok">{{ ord.with_hits }}</span> / <span class="hit-none">{{ ord.no_hits }}</span>)
              </template>
              <span v-else>-</span>
            </td>
            <td>{{ ord.result_mtime || '-' }}</td>
            <td class="actions-cell" @click.stop>
              <!-- 已忽略订单展示恢复入口，其它订单按阶段提供唯一主操作 -->
              <template v-if="ord.ignored">
                <button
                  class="btn-mini primary"
                  :disabled="busy"
                  @click="handleIgnoreOrders([ord.order_no || ord.dir_name], false)"
                >
                  取消忽略
                </button>
              </template>
              <template v-else-if="ord.status === 'pending'">
                <button
                  v-if="ord.download_zip_ready"
                  class="btn-mini primary"
                  :disabled="busy || runtime.running"
                  :title="`认领 ${ord.download_zip_name}`"
                  @click="handleClaimSingleOrder(ord)"
                >
                  认领下载包
                </button>
                <button
                  v-else-if="ord.download_url || ord.cx_order_id"
                  class="btn-mini primary"
                  :disabled="busy || runtime.running"
                  :title="autoBlastAfterDownload ? '自动登录生工官网下载压缩包并接续 16S BLAST 比对导出' : '自动登录生工官网下载压缩包至订单目录'"
                  @click="handleAutoDownloadOrders([ord.dir_name], autoBlastAfterDownload)"
                >
                  自动下载
                </button>
                <template v-else>
                  <span class="missing-zip-tip" title="目录内无原始压缩包且未识别到生工下载页链接">缺压缩包</span>
                  <button
                    class="btn-mini"
                    :disabled="busy || runtime.running"
                    title="若为已发货通知或无需比对订单，可点击全局忽略并移入已忽略标签"
                    @click="handleIgnoreOrders([ord.order_no || ord.dir_name], true, '缺少压缩包/非测序通知', { [ord.order_no || ord.dir_name]: ord.dir_name })"
                  >
                    忽略
                  </button>
                </template>
              </template>

              <template v-else-if="ord.status === 'completed'">
                <button class="btn-mini primary" @click="selectOrderAndLoadResults(ord)">预览</button>
                <button class="btn-mini" @click="openSendResultModal(ord)">发信</button>
              </template>

              <template v-else>
                <button
                  class="btn-mini primary"
                  :disabled="runtime.running"
                  @click="handleRunPipeline([ord.dir_name])"
                >
                  运行
                </button>
              </template>

              <!-- 次要操作收敛至行尾“更多”浮层 -->
              <PopoverMenu align="right" :width="190">
                <template #trigger>
                  <button class="btn-mini">更多 ▾</button>
                </template>
                <template #default="{ close }">
                  <div class="menu-section">
                    <template v-if="!ord.ignored">
                      <button
                        v-if="ord.status === 'pending' && ord.zip_count === 0 && Boolean(ord.download_url || ord.cx_order_id)"
                        class="menu-item"
                        :disabled="busy || runtime.running"
                        @click="close(); handleAutoDownloadOrders([ord.dir_name], false)"
                      >
                        仅自动下载此订单
                      </button>
                      <button
                        v-if="ord.status === 'pending' && ord.zip_count === 0 && Boolean(ord.download_url || ord.cx_order_id)"
                        class="menu-item"
                        :disabled="busy || runtime.running"
                        @click="close(); handleAutoDownloadOrders([ord.dir_name], true)"
                      >
                        自动下载并比对
                      </button>
                      <button
                        class="menu-item"
                        :disabled="runtime.running"
                        @click="close(); handleRunPipeline([ord.dir_name])"
                      >
                        {{ ord.status === 'completed' ? '重新运行比对' : '立即运行此订单' }}
                      </button>
                      <button
                        v-if="ord.download_zip_ready"
                        class="menu-item"
                        :disabled="busy || runtime.running"
                        @click="close(); handleClaimSingleOrder(ord)"
                      >
                        认领浏览器下载包
                      </button>
                      <a
                        v-if="ord.download_url"
                        :href="ord.download_url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="menu-item link-menu-item"
                        @click="close()"
                      >
                        打开生工下载页（手动）
                      </a>
                    </template>
                    <button class="menu-item" @click="close(); openLocalPath(ord.order_path)">
                      打开本地文件夹
                    </button>
                    <button
                      v-if="!ord.ignored"
                      class="menu-item"
                      :disabled="busy || runtime.running"
                      @click="close(); handleIgnoreOrders([ord.order_no || ord.dir_name], true, '从订单列表忽略', { [ord.order_no || ord.dir_name]: ord.dir_name })"
                    >
                      忽略此订单（全局跳过）
                    </button>
                    <button
                      v-else
                      class="menu-item"
                      :disabled="busy"
                      @click="close(); handleIgnoreOrders([ord.order_no || ord.dir_name], false)"
                    >
                      取消忽略并恢复显示
                    </button>
                    <button
                      class="menu-item danger"
                      :disabled="runtime.running"
                      @click="close(); openCleanupModal([ord.dir_name])"
                    >
                      清理此订单...
                    </button>
                  </div>
                </template>
              </PopoverMenu>
            </td>
          </tr>
          <tr v-if="filteredOrders.length === 0">
            <td colspan="9" class="empty-cell">
              <template v-if="orderFilter === 'ignored'">
                <span>暂无已忽略的订单条目</span>
                <button v-if="activeOrders.length > 0" class="btn-mini primary inline-action-btn" @click="orderFilter = 'all'">
                  返回有效订单 ({{ activeOrders.length }})
                </button>
              </template>
              <template v-else-if="activeOrders.length > 0 && orderFilter !== 'all'">
                <span>当前阶段下暂无订单</span>
                <button class="btn-mini primary inline-action-btn" @click="orderFilter = 'all'">
                  查看全部 ({{ activeOrders.length }})
                </button>
              </template>
              <template v-else-if="ignoredOrders.length > 0">
                <span>当前有效订单为空（另有 {{ ignoredOrders.length }} 个订单已全局忽略）</span>
                <button class="btn-mini primary inline-action-btn" @click="orderFilter = 'ignored'">
                  查看已忽略 ({{ ignoredOrders.length }})
                </button>
              </template>
              <span v-else>暂无订单目录，可点击上方“检查新订单”从邮箱同步</span>
            </td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="filteredOrders.length > 0"
        v-model:page="orderPage"
        v-model:page-size="orderPageSize"
        :total="filteredOrders.length"
        :page-size-options="[6, 10, 20, 50]"
      />
    </div>

    <!-- 默认折叠的生工通知邮件记录（辅助排查与手动补建目录） -->
    <SangonMailRecords
      ref="mailRecordsRef"
      :mails="scannedMails"
      :summary="mailSummary"
      :scanning="scanningMail"
      :busy="busy"
      :has-scanned="hasScannedMails"
      @scan="handleCheckNewOrders"
      @init-order="handleInitOrderFromMail"
      @toggle-ignore="handleToggleMailIgnore"
    />

    <!-- 结果预览 -->
    <div v-if="selectedOrder" class="panel-box result-preview-box">
      <div class="panel-box-header preview-header">
        <h4>
          {{ selectedOrder.dir_name }} 鉴定结果
          <span class="sub-count">（{{ filteredResultRows.length }} / {{ resultRows.length }}）</span>
        </h4>
        <div class="preview-tools">
          <input v-model="searchKeyword" type="text" placeholder="搜索序列号、物种名、访问号..." class="search-input" />
          <button v-if="selectedOrder.has_result_csv" class="btn-outline" @click="openSendResultModal(selectedOrder)">
            发送结果邮件
          </button>
          <button v-if="selectedOrder.result_csv_path" class="btn-outline" @click="openLocalPath(selectedOrder.result_csv_path)">
            定位 CSV
          </button>
        </div>
      </div>

      <div v-if="resultRows.length > 0" class="csv-table-scroll">
        <table class="data-table csv-table">
          <thead>
            <tr>
              <th v-for="h in resultHeaders" :key="h">{{ h }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rIdx) in pagedResultRows" :key="rIdx">
              <td v-for="h in resultHeaders" :key="h" :class="{ 'highlight-species': h === '鉴定物种(中文翻译)' }">
                {{ row[h] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-cell">尚未生成 16S鉴定结果.csv</div>
      <PaginationBar
        v-if="filteredResultRows.length > 0"
        v-model:page="resultPage"
        v-model:page-size="resultPageSize"
        :total="filteredResultRows.length"
        :page-size-options="[10, 20, 50, 100]"
      />
    </div>

    <!-- 邮箱 Key 弹窗 -->
    <div v-if="showAuthModal" class="modal-backdrop" @click.self="showAuthModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>邮箱 Key（IMAP 授权码）</h3>
          <button class="close-btn" @click="showAuthModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-row">
            <span>当前状态: {{ imapReady ? `已配置 (${imapMasked})` : '未配置' }}</span>
          </div>
          <input v-model="imapKeyInput" type="password" autocomplete="new-password" placeholder="输入新的邮箱授权码，留空不修改" class="key-input" />
          <div v-if="imapFile" class="auth-file">保存位置: {{ imapFile }}</div>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showAuthModal = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="saveImapAuth">保存</button>
        </div>
      </div>
    </div>

    <!-- 发送 16S 结果邮件弹窗 -->
    <div v-if="showSendModal" class="modal-backdrop" @click.self="showSendModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>发送 16S 鉴定结果邮件</h3>
          <button class="close-btn" @click="showSendModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-row">目标订单: {{ sendForm.orderDirName }}</div>
          <label class="modal-field">
            <span>收件人邮箱（留空默认发送给自己 {{ mailAccount || '当前配置账号' }}）</span>
            <input v-model="sendForm.to" type="text" :placeholder="mailAccount || '例如 913223599@qq.com'" class="key-input" />
          </label>
          <label class="modal-field">
            <span>邮件主题</span>
            <input v-model="sendForm.subject" type="text" class="key-input" />
          </label>
          <label class="modal-field">
            <span>附加说明（可选）</span>
            <input v-model="sendForm.extraNote" type="text" placeholder="例如：自测验证 / 补充说明" class="key-input" />
          </label>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showSendModal = false">取消</button>
          <button class="btn-secondary" :disabled="sendingMail" @click="confirmSendResultMail(true)">
            {{ sendingMail ? '发送中...' : '发给自己测试' }}
          </button>
          <button class="btn-primary" :disabled="sendingMail" @click="confirmSendResultMail(false)">
            {{ sendingMail ? '发送中...' : '发送邮件' }}
          </button>
        </div>
      </div>
    </div>

    <CleanupDialog
      :visible="showCleanup"
      title="清理生工 16S 历史数据"
      :subtitle="cleanupTargetOrders.includes('__ALL__') ? '目标范围：全局扫描去重记录' : `目标订单（共 ${cleanupTargetOrders.length} 个）: ${cleanupTargetOrders.join(', ')}`"
      :options="cleanupOptions"
      :show-days="false"
      :busy="busy"
      @close="showCleanup = false"
      @confirm="p => confirmCleanup(p.targets)"
    />

    <SangonIgnoreModal
      :visible="showIgnoreModal"
      :ignored-orders="ignoredOrdersMap"
      :ignore-keywords="ignoreKeywords"
      :ignored-download-count="ignoredDownloadCount"
      :busy="busy"
      @close="showIgnoreModal = false"
      @add-ignore="p => handleIgnoreOrders(p.orderKeys, true, p.reason)"
      @unignore="k => handleIgnoreOrders([k], false)"
      @save-keywords="handleSaveIgnoreKeywords"
    />

    <SangonAccountModal
      :visible="showSangonAuthModal"
      :auth-meta="sangonAuth"
      :busy="busy"
      :hint-text="sangonAuthHint"
      @close="closeSangonAuthEditor"
      @save="handleSaveSangonAuth"
      @clear-password="handleClearSangonPassword"
    />
  </div>
</template>

<style scoped>
.sangon-module {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 28px;
}

.steps-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
  overflow-x: auto;
  gap: 6px;
}

.step-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
}

.step-pill span {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.step-sep { color: #94a3b8; font-size: 14px; }

.metrics-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.metric-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
}

.metric-label { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.metric-val { font-size: 17px; font-weight: 700; color: #0f172a; }
.metric-val.ok { color: #059669; }
.metric-val.warn { color: #d97706; }
.metric-val.running { color: #2563eb; }
.metric-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.paths-panel {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sub-paths {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}

.sub-path-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}

.sp-label { color: #64748b; white-space: nowrap; }
.sp-code {
  flex: 1;
  min-width: 0;
  font-family: Consolas, monospace;
  font-size: 12px;
  color: #0f172a;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 4px 8px;
  border-radius: 5px;
  word-break: break-all;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
}

.control-left, .control-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sel-hint { font-size: 12px; color: #2563eb; font-weight: 600; }

.adv-active-tag {
  font-size: 11px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}

.btn-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-secondary {
  background: #059669;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-secondary:hover:not(:disabled) { background: #047857; }
.btn-secondary:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-download {
  background: #0284c7;
  color: white;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-download:hover:not(:disabled) { background: #0369a1; }
.btn-download:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-outline {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.btn-outline.highlight-claim {
  background: #ecfdf5;
  color: #047857;
  border-color: #6ee7b7;
  font-weight: 600;
}
.btn-outline.active-trigger {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}
.btn-outline.danger, .btn-mini.danger {
  color: #b91c1c;
  border-color: #fecaca;
}
.btn-outline.danger:hover:not(:disabled), .btn-mini.danger:hover:not(:disabled) {
  background: #fef2f2;
}
.btn-outline:disabled, .btn-mini:disabled { opacity: 0.5; cursor: not-allowed; }

.menu-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.menu-title {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  padding: 4px 8px 2px;
}

.menu-divider {
  height: 1px;
  background: #e2e8f0;
  margin: 5px 0;
}

.menu-item {
  text-align: left;
  background: transparent;
  border: none;
  padding: 6px 10px;
  border-radius: 5px;
  font-size: 12px;
  color: #1e293b;
  cursor: pointer;
  display: block;
  width: 100%;
  box-sizing: border-box;
}
.menu-item:hover:not(:disabled) {
  background: #f1f5f9;
}
.menu-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.menu-item.danger {
  color: #b91c1c;
}
.menu-item.danger:hover:not(:disabled) {
  background: #fef2f2;
}
.link-menu-item {
  text-decoration: none;
}

.menu-check {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
  border-radius: 5px;
}
.menu-check:hover {
  background: #f8fafc;
}

.alert-banner {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}
.alert-banner.info { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.alert-banner.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.awaiting-dl-hint {
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 3px 8px;
  border-radius: 999px;
}

.missing-zip-tip {
  font-size: 11px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 2px 6px;
  border-radius: 4px;
}

.sangon-log-console {
  margin: 0;
  padding: 10px 14px;
  max-height: 220px;
  overflow-y: auto;
  background: #0f172a;
  color: #e2e8f0;
  font-family: Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.panel-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.panel-box-header {
  padding: 10px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.panel-box-header h4 { margin: 0; font-size: 13px; color: #1e293b; }

.order-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.order-tip {
  font-size: 11px;
  color: #94a3b8;
}

.seg-group {
  display: inline-flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: 7px;
  gap: 2px;
}

.seg-btn {
  border: none;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.seg-btn.active {
  background: white;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.seg-count {
  font-size: 11px;
  color: #64748b;
  background: rgba(148, 163, 184, 0.25);
  padding: 0 5px;
  border-radius: 999px;
}

.seg-btn.active .seg-count {
  background: #eff6ff;
  color: #2563eb;
}

.new-order-badge {
  margin-left: 6px;
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #6ee7b7;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  font-family: sans-serif;
}

.zip-ready-badge {
  margin-left: 6px;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #93c5fd;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  font-family: sans-serif;
}

.inline-action-btn {
  margin-left: 10px;
}
.sub-count { font-weight: 400; color: #64748b; font-size: 12px; }

.preview-tools { display: flex; align-items: center; gap: 10px; }
.search-input {
  width: 260px;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th {
  text-align: left;
  padding: 10px 12px;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}
.data-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}
.selected-row { background: #f0f7ff; }
.ignored-row td { opacity: 0.72; }
.mono-cell { font-family: Consolas, monospace; color: #2563eb; }
.bold-cell { font-weight: 600; }

.ignore-reason-tag {
  margin-left: 6px;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #cbd5e1;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
  font-family: sans-serif;
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.status-pill.completed { background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; }
.status-pill.blasted, .status-pill.extracted { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.status-pill.downloaded, .status-pill.pending { background: #fffbeb; color: #b45309; border: 1px solid #fcd34d; }
.status-pill.ignored { background: #f1f5f9; color: #64748b; border: 1px dashed #94a3b8; }

.pending-dl-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  font-size: 12px;
}
.pending-dl-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 10px;
}
.pending-dl-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #166534;
  flex: 1;
  min-width: 240px;
}
.pending-dl-desc {
  font-size: 11px;
  color: #15803d;
  line-height: 1.4;
}
.pending-dl-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dl-chip-card {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  background: white;
  border: 1px solid #86efac;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  color: #15803d;
}
.dl-chip-name {
  font-family: Consolas, monospace;
  font-weight: 600;
}
.dl-chip-match {
  color: #64748b;
}
.chip-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 11px;
  cursor: pointer;
}
.chip-btn.primary {
  background: #eff6ff;
  color: #2563eb;
  border-color: #93c5fd;
  font-weight: 600;
}
.chip-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pending-dl-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.modal-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #475569;
}

.hit-ok { color: #059669; font-weight: 600; }
.hit-none { color: #94a3b8; }

.actions-cell { display: flex; gap: 6px; align-items: center; }
.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
  color: #334155;
}
.btn-mini.primary { background: #eff6ff; color: #2563eb; border-color: #93c5fd; font-weight: 600; }
.link-as-btn { text-decoration: none; display: inline-block; }

.csv-table-scroll { max-height: 460px; overflow: auto; }
.csv-table td {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.highlight-species { color: #059669 !important; font-weight: 700; }
.empty-cell { text-align: center; color: #94a3b8; padding: 24px !important; }

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-card {
  background: white;
  border-radius: 12px;
  width: 480px;
  max-width: 92vw;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
}
.modal-header h3 { margin: 0; font-size: 15px; }
.close-btn { background: none; border: none; font-size: 20px; cursor: pointer; }
.modal-body { padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; }
.auth-row { font-size: 12px; color: #334155; font-weight: 600; }
.key-input {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}
.auth-file { font-size: 11px; color: #94a3b8; font-family: Consolas, monospace; word-break: break-all; }
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
