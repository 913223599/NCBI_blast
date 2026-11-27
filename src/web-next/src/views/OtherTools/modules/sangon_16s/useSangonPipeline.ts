/**
 * useSangonPipeline - 生工 16S 测序结果自动化 BLAST 与导出状态机（聚合 Facade）
 * 辅助函数已拆离至 ./sangonHelpers.ts，邮件操作至 ./useSangonMailActions.ts，订单与认证操作至 ./useSangonOrderActions.ts。
 */
import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { MailDraftPayload } from '../../components/MailComposeModal.vue'
import type { CleanupOption } from '../../components/CleanupDialog.vue'
import type {
  BrowserEnvStatus,
  DownloadCandidateItem,
  IgnoredOrderRule,
  MailScanSummary,
  OrderFilterKey,
  SangonAuthMeta,
  SangonOrderItem,
  SangonRuntimeState,
  SangonSettingsMeta,
  ScannedMailItem,
} from '../../sangonTypes'
import { getJson, openLocalPath } from '../../api'
import {
  extractErrorMessage,
  isProcessingStatus,
  normalizeOrderKeyFrontend,
  statusLabel,
} from './sangonHelpers'
import { hasOrderDownloadChannelImpl, isOrderDownloadableImpl } from './useSangonPipelineShared'
import { useSangonMailActions } from './useSangonMailActions'
import { useSangonOrderActions } from './useSangonOrderActions'

export { isProcessingStatus, normalizeOrderKeyFrontend, statusLabel }

const API = '/api/other_tools/sangon_16s'
const MAIL_API = '/api/other_tools/mail_pipeline'

interface OrderResultsResponse {
  headers?: string[]
  rows?: Array<Record<string, string>>
}

interface OverviewResponse {
  sangon_root?: string
  downloads_dir?: string
  root_exists?: boolean
  db_16s_ready?: boolean
  orders?: SangonOrderItem[]
  download_candidates?: DownloadCandidateItem[]
  ignored_download_count?: number
  settings?: Partial<SangonSettingsMeta>
  sangon_auth?: SangonAuthMeta
  browser_env?: BrowserEnvStatus
  runtime?: SangonRuntimeState
}

interface MailOverviewConfigResponse {
  config?: {
    account?: string
    smtp_account?: string
    smtp_display_name?: string
    reply_to?: string
  }
}

export function useSangonPipeline(mailRecordsRef: Ref<{ expand?: () => void } | null>) {
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
  const mailDisplayName = ref('元昇生物注释服务')
  const mailReplyTo = ref('')

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

  const mailFilter = ref({
    dedup: true,
    autoCreate: true,
    ignoreHistory: false,
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
    nonSequencingCount: 0,
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
    auto_confirm_fee: true,
  })
  const browserEnv = ref<BrowserEnvStatus | null>(null)
  const repairingBrowser = ref(false)
  const showSangonAuthModal = ref(false)
  const sangonAuthHint = ref('')
  const autoConfirmFee = ref(true)
  const initializedSangonSettings = ref(false)
  const autoBlastAfterDownload = ref(true)
  const pendingDownloadTask = ref<{ orderNames: string[]; autoRunBlast: boolean } | null>(null)

  const showSendModal = ref(false)
  const loadingSendDraft = ref(false)
  const sendingMail = ref(false)
  const sendOrderTarget = ref<SangonOrderItem | null>(null)
  const sendDraft = ref<MailDraftPayload>({
    to: '',
    replyTo: '',
    fromName: '元昇生物注释服务',
    cc: '',
    subject: '',
    body: '',
    attachmentName: '',
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
    logs: [],
  })
  const trackingRun = ref(false)
  const showLogs = ref(false)

  const cleanupOptions: CleanupOption[] = [
    { key: 'raw_extracted', label: '解压数据 (原始数据/)', desc: '删除解压出的文件，保留原始压缩包', checked: true },
    { key: 'blast_cache', label: 'BLAST 中间缓存', desc: '删除 results/blast/<订单>_16s 报告缓存', checked: true },
    { key: 'result_csv', label: '鉴定结果 CSV', desc: '删除 BLAST结果/16S鉴定结果.csv' },
    { key: 'order_dir', label: '整个订单目录', desc: '删除该订单全部文件夹与压缩包（同时保留清理记忆防止扫描重建）', danger: true },
    { key: 'scan_index', label: '清除扫描去重记忆', desc: '清空选中订单的已扫描/已清理记录，之后可被检查新订单再次识别' },
  ]

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let followUpTimer: ReturnType<typeof setTimeout> | null = null

  function isOrderMarkedNew(ord: SangonOrderItem): boolean {
    return !ord.ignored && Boolean(ord.is_new || recentCreatedDirs.value.includes(ord.dir_name))
  }

  const activeOrders = computed(() => orders.value.filter((o) => !o.ignored))
  const ignoredOrders = computed(() => orders.value.filter((o) => Boolean(o.ignored)))
  const ignoredOrdersCount = computed(() => Object.keys(ignoredOrdersMap.value || {}).length)
  const claimableCandidates = computed(() => downloadCandidates.value.filter((c) => !c.archived && !c.ignored))

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
      { key: 'ignored' as OrderFilterKey, label: '已忽略', count: ignoredOrders.value.length },
    ]
  })

  const filteredOrders = computed(() => {
    const f = orderFilter.value
    if (f === 'ignored') return ignoredOrders.value
    if (f === 'all') return activeOrders.value
    if (f === 'pending') return activeOrders.value.filter((o) => o.status === 'pending')
    if (f === 'completed') return activeOrders.value.filter((o) => o.status === 'completed')
    return activeOrders.value.filter((o) => isProcessingStatus(o.status))
  })

  const pagedOrders = computed(() => {
    const start = (orderPage.value - 1) * orderPageSize.value
    return filteredOrders.value.slice(start, start + orderPageSize.value)
  })

  function hasOrderSourceData(ord: SangonOrderItem): boolean {
    return Boolean(ord.zip_count > 0 || ord.consensus_fasta_count > 0 || ord.blast_report_count > 0 || ord.download_zip_ready)
  }

  function isOrderRunnable(ord: SangonOrderItem, reblast = forceReblast.value): boolean {
    if (ord.ignored) return false
    if (ord.status !== 'completed') return hasOrderSourceData(ord)
    return reblast && (ord.zip_count > 0 || ord.consensus_fasta_count > 0 || ord.blast_report_count > 0)
  }

  const runnableOrdersCount = computed(() => activeOrders.value.filter((o) => isOrderRunnable(o)).length)
  const downloadableOrders = computed(() => activeOrders.value.filter((o) => isOrderDownloadableImpl(o)))

  const checkedDownloadableNames = computed(() =>
    checkedOrderNames.value.filter((name) => {
      const ord = activeOrders.value.find((o) => o.dir_name === name)
      return ord ? isOrderDownloadableImpl(ord) : false
    })
  )

  const targetDownloadCount = computed(() =>
    checkedDownloadableNames.value.length > 0 ? checkedDownloadableNames.value.length : downloadableOrders.value.length
  )

  const awaitingDownloadCount = computed(() =>
    activeOrders.value.filter((o) => o.status === 'pending' && !hasOrderSourceData(o)).length
  )

  const needsWebLoginCount = computed(() =>
    downloadableOrders.value.filter((o) => !o.download_zip_ready && Boolean(o.download_url || o.cx_order_id)).length
  )

  const browserEnvShortLabel = computed(() => {
    if (!browserEnv.value) return '未检测'
    if (!browserEnv.value.enabled) return '已禁用'
    return browserEnv.value.ready ? '已就绪' : '需修复'
  })

  const showBrowserWarningBar = computed(() => {
    if (!browserEnv.value) return false
    if (!browserEnv.value.enabled) return needsWebLoginCount.value > 0
    return !browserEnv.value.ready
  })

  const browserFirstIssueText = computed(() => {
    const first = browserEnv.value?.issues?.[0]?.message
    if (first) return first
    if (browserEnv.value && !browserEnv.value.enabled) {
      return 'config.json 已配置 headless_browser.enabled=false，生工官网自动下载功能当前不可用'
    }
    return '无头浏览器 (Playwright Chromium) 尚未就绪，建议先执行自修复检查'
  })

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
    return resultRows.value.filter((row) => Object.values(row).some((v) => String(v || '').toLowerCase().includes(kw)))
  })

  const pagedResultRows = computed(() => {
    const start = (resultPage.value - 1) * resultPageSize.value
    return filteredResultRows.value.slice(start, start + resultPageSize.value)
  })

  watch(searchKeyword, () => {
    resultPage.value = 1
  })

  watch(orderFilter, () => {
    const visible = new Set(filteredOrders.value.map((o) => o.dir_name))
    checkedOrderNames.value = checkedOrderNames.value.filter((n) => visible.has(n))
  })

  watch([orderFilter, () => filteredOrders.value.length], () => {
    const maxPage = Math.max(1, Math.ceil(filteredOrders.value.length / orderPageSize.value))
    if (orderPage.value > maxPage) orderPage.value = maxPage
  })

  const completedOrdersCount = computed(() => activeOrders.value.filter((o) => o.status === 'completed').length)
  const totalIdentifiedSamples = computed(() => activeOrders.value.reduce((acc, o) => acc + (o.total_samples || 0), 0))
  const allChecked = computed(
    () => filteredOrders.value.length > 0 && filteredOrders.value.every((o) => checkedOrderNames.value.includes(o.dir_name))
  )

  function setInfo(msg: string): void {
    actionMessage.value = msg
    errorMessage.value = ''
  }

  function setError(err: unknown): void {
    errorMessage.value = extractErrorMessage(err)
    actionMessage.value = ''
  }

  function toggleCheckAll(ev: Event): void {
    const checked = (ev.target as HTMLInputElement).checked
    const currentNames = filteredOrders.value.map((o) => o.dir_name)
    if (checked) {
      checkedOrderNames.value = Array.from(new Set([...checkedOrderNames.value, ...currentNames]))
    } else {
      checkedOrderNames.value = checkedOrderNames.value.filter((n) => !currentNames.includes(n))
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
      const data = await getJson<OrderResultsResponse>(`${API}/order/${encodeURIComponent(order.dir_name)}/results`)
      resultHeaders.value = data.headers || []
      resultRows.value = data.rows || []
    } catch (err: unknown) {
      setError(err)
    }
  }

  async function loadOverview(): Promise<void> {
    try {
      const data = await getJson<OverviewResponse>(`${API}/overview`)
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
      if (data.browser_env) {
        browserEnv.value = data.browser_env
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
          const refreshed = orders.value.find((o) => o.dir_name === selectedOrder.value?.dir_name)
          if (refreshed?.has_result_csv) {
            await selectOrderAndLoadResults(refreshed)
          }
        }
      }

      if (!mailAccount.value) {
        try {
          const mailMeta = await getJson<MailOverviewConfigResponse>(`${MAIL_API}/overview`)
          mailAccount.value = mailMeta.config?.account || mailMeta.config?.smtp_account || ''
          if (mailMeta.config?.smtp_display_name) mailDisplayName.value = mailMeta.config.smtp_display_name
          mailReplyTo.value = mailMeta.config?.reply_to || ''
        } catch {
          // 忽略邮件配置加载异常
        }
      }

      const visibleSet = new Set(filteredOrders.value.map((o) => o.dir_name))
      checkedOrderNames.value = checkedOrderNames.value.filter((n) => visibleSet.has(n))

      if (selectedOrder.value) {
        const updated = orders.value.find((o) => o.dir_name === selectedOrder.value?.dir_name) || null
        if (updated && updated.ignored && orderFilter.value !== 'ignored') {
          selectedOrder.value = null
          resultRows.value = []
        } else {
          selectedOrder.value = updated
        }
      }
      if (!selectedOrder.value && activeOrders.value.length > 0) {
        const firstCompleted = activeOrders.value.find((o) => o.has_result_csv) || activeOrders.value[0]
        if (firstCompleted) await selectOrderAndLoadResults(firstCompleted)
      }
    } catch (err: unknown) {
      errorMessage.value = `加载失败: ${extractErrorMessage(err)}`
    }
  }

  function clearFollowUpTimer(): void {
    if (followUpTimer) {
      clearTimeout(followUpTimer)
      followUpTimer = null
    }
  }

  function scheduleFollowUpRefresh(): void {
    followUpTimer = setTimeout(() => {
      void loadOverview()
    }, 450)
  }

  const mailActions = useSangonMailActions({
    mailRecordsRef,
    sangonRoot,
    mailAccount,
    mailDisplayName,
    mailReplyTo,
    orders,
    scannedMails,
    hasScannedMails,
    scanningMail,
    recentCreatedDirs,
    mailFilter,
    mailSummary,
    ignoredOrdersMap,
    ignoreKeywords,
    checkedOrderNames,
    orderFilter,
    orderPage,
    showSendModal,
    loadingSendDraft,
    sendingMail,
    sendOrderTarget,
    sendDraft,
    busy,
    setInfo,
    setError,
    loadOverview,
  })

  const orderActions = useSangonOrderActions({
    sangonRoot,
    downloadsDir,
    activeOrders,
    checkedOrderNames,
    selectedOrder,
    orderFilter,
    checkedDownloadableNames,
    downloadableOrders,
    awaitingDownloadCount,
    runnableOrdersCount,
    forceReblast,
    autoBlastAfterDownload,
    autoConfirmFee,
    sangonAuth,
    browserEnv,
    repairingBrowser,
    showSangonAuthModal,
    sangonAuthHint,
    pendingDownloadTask,
    showCleanup,
    cleanupTargetOrders,
    showAuthModal,
    imapMasked,
    imapReady,
    imapFile,
    imapKeyInput,
    recentCreatedDirs,
    runtime,
    trackingRun,
    showLogs,
    busy,
    setInfo,
    setError,
    loadOverview,
    selectOrderAndLoadResults,
    scheduleFollowUpRefresh,
    clearFollowUpTimer,
  })

  onMounted(() => {
    void loadOverview()
    pollTimer = setInterval(() => {
      if (runtime.value?.running || trackingRun.value) void loadOverview()
    }, 1200)
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
    clearFollowUpTimer()
  })

  return {
    openLocalPath,
    sangonRoot,
    downloadsDir,
    rootExists,
    db16sReady,
    orders,
    downloadCandidates,
    ignoredDownloadCount,
    ignoredOrdersMap,
    ignoreKeywords,
    showIgnoreModal,
    mailAccount,
    mailDisplayName,
    mailReplyTo,
    orderFilter,
    orderPage,
    orderPageSize,
    checkedOrderNames,
    selectedOrder,
    resultHeaders,
    resultRows,
    searchKeyword,
    resultPage,
    resultPageSize,
    forceReblast,
    scannedMails,
    hasScannedMails,
    scanningMail,
    recentCreatedDirs,
    mailFilter,
    mailSummary,
    busy,
    actionMessage,
    errorMessage,
    showCleanup,
    cleanupTargetOrders,
    showAuthModal,
    imapMasked,
    imapReady,
    imapFile,
    imapKeyInput,
    sangonAuth,
    browserEnv,
    repairingBrowser,
    showSangonAuthModal,
    sangonAuthHint,
    autoConfirmFee,
    autoBlastAfterDownload,
    showSendModal,
    loadingSendDraft,
    sendingMail,
    sendOrderTarget,
    sendDraft,
    runtime,
    showLogs,
    cleanupOptions,
    activeOrders,
    ignoredOrders,
    ignoredOrdersCount,
    claimableCandidates,
    orderFilterTabs,
    filteredOrders,
    pagedOrders,
    runnableOrdersCount,
    downloadableOrders,
    checkedDownloadableNames,
    targetDownloadCount,
    awaitingDownloadCount,
    needsWebLoginCount,
    browserEnvShortLabel,
    showBrowserWarningBar,
    browserFirstIssueText,
    runtimeLogsList,
    activeAdvancedTags,
    filteredResultRows,
    pagedResultRows,
    completedOrdersCount,
    totalIdentifiedSamples,
    allChecked,
    isProcessingStatus,
    isOrderMarkedNew,
    hasOrderSourceData,
    isOrderRunnable,
    hasOrderDownloadChannel: hasOrderDownloadChannelImpl,
    isOrderDownloadable: isOrderDownloadableImpl,
    statusLabel,
    toggleCheckAll,
    loadOverview,
    selectOrderAndLoadResults,
    ...orderActions,
    ...mailActions,
  }
}
