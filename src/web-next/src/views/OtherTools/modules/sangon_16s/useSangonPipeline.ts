/**
 * useSangonPipeline - 生工 16S 测序结果自动化 BLAST 与导出状态机
 * 从 Sangon16SPipelineModule.vue 拆解而出，封装订单筛选、邮件扫描、自动下载与结果加载逻辑。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { MailComposeSubmitPayload, MailDraftPayload } from '../../components/MailComposeModal.vue'
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
  ScannedMailItem,
} from '../../sangonTypes'
import { describeMigration, getJson, openLocalPath, postJson } from '../../api'

const API = '/api/other_tools/sangon_16s'
const MAIL_API = '/api/other_tools/mail_pipeline'
const BROWSER_ENV_API = '/api/other_tools/browser_env'

export function isProcessingStatus(status: SangonOrderItem['status']): boolean {
  return status === 'downloaded' || status === 'extracted' || status === 'blasted'
}

export function normalizeOrderKeyFrontend(raw: string): string {
  const s = String(raw || '').trim()
  const m = s.match(/(?<!\d)(\d{10})(?!\d)/)
  if (m && m[1]) return m[1]
  if (s.includes('_')) return s.split('_', 2)[1]?.trim() || s
  return s
}

export function statusLabel(st: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    blasted: '待导出',
    extracted: '待比对',
    downloaded: '待解压',
    pending: '待下载',
  }
  return map[st] || st
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

  function hasOrderDownloadChannel(ord: SangonOrderItem): boolean {
    return Boolean(ord.download_zip_ready || ord.download_url || ord.cx_order_id)
  }

  function isOrderDownloadable(ord: SangonOrderItem): boolean {
    return !ord.ignored && ord.status === 'pending' && ord.zip_count === 0 && hasOrderDownloadChannel(ord)
  }

  const downloadableOrders = computed(() => activeOrders.value.filter((o) => isOrderDownloadable(o)))

  const checkedDownloadableNames = computed(() =>
    checkedOrderNames.value.filter((name) => {
      const ord = activeOrders.value.find((o) => o.dir_name === name)
      return ord ? isOrderDownloadable(ord) : false
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

  function setError(err: any): void {
    errorMessage.value = err?.message || String(err)
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
      const data = await getJson(`${API}/order/${encodeURIComponent(order.dir_name)}/results`)
      resultHeaders.value = data.headers || []
      resultRows.value = data.rows || []
    } catch (err: any) {
      setError(err)
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
          const mailMeta = await getJson(`${MAIL_API}/overview`)
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
    } catch (err: any) {
      errorMessage.value = `加载失败: ${err.message || err}`
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
        auto_create_order: autoCreateOrder,
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
    const existingOrderNos = new Set(orders.value.map((o) => normalizeOrderKeyFrontend(o.order_no || o.dir_name)))
    let changed = false
    scannedMails.value = scannedMails.value.map((m) => {
      const key = normalizeOrderKeyFrontend(m.order_no || m.dir_name)
      if (!key || !targetKeys.has(key) || m.dedup_status === 'non_sequencing') return m
      changed = true
      if (ignored) return { ...m, ignored: true, dedup_status: 'ignored' }
      const hasDir = Boolean(m.dir_ready || existingOrderNos.has(key))
      return { ...m, ignored: false, dir_ready: hasDir, dedup_status: hasDir ? 'existing' : 'new' }
    })
    if (changed) {
      mailSummary.value = {
        ...mailSummary.value,
        ignoredCount: scannedMails.value.filter((m) => m.dedup_status === 'ignored').length,
        existingCount: scannedMails.value.filter((m) => m.dedup_status === 'existing' || m.dedup_status === 'created').length,
        newCount: scannedMails.value.filter((m) => m.dedup_status === 'new').length,
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
      const data = await postJson(`${API}/ignore`, { order_keys: orderKeys, ignore, reason, dir_names: dirNames })
      ignoredOrdersMap.value = data.ignored_orders || {}
      const affected = new Set<string>((data.affected_orders || []).map((k: string) => normalizeOrderKeyFrontend(k)))
      for (const k of orderKeys) {
        const nk = normalizeOrderKeyFrontend(k)
        if (nk) affected.add(nk)
      }
      checkedOrderNames.value = checkedOrderNames.value.filter((name) => !affected.has(normalizeOrderKeyFrontend(name)))
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

  async function loadSangonSendDraft(order: SangonOrderItem): Promise<void> {
    loadingSendDraft.value = true
    try {
      const data = await postJson(`${API}/send_preview`, {
        order_dir_name: order.dir_name,
        sangon_root: sangonRoot.value || null,
      })
      if (data.from_name) mailDisplayName.value = data.from_name
      if (data.reply_to !== undefined) mailReplyTo.value = data.reply_to || ''
      sendDraft.value = {
        to: data.to || mailAccount.value || '',
        replyTo: data.reply_to || mailReplyTo.value || '',
        fromName: data.from_name || mailDisplayName.value || '元昇生物注释服务',
        cc: data.cc || '',
        subject: data.subject || `生工 16S 测序鉴定结果 - ${order.dir_name}（共 ${order.total_samples} 样本）`,
        body: data.body || '',
        attachmentName: data.attachment_name || `16S鉴定结果_${order.dir_name}.zip`,
      }
    } catch (err) {
      setError(err)
    } finally {
      loadingSendDraft.value = false
    }
  }

  async function openSendResultModal(order: SangonOrderItem): Promise<void> {
    sendOrderTarget.value = order
    sendDraft.value = {
      to: mailAccount.value || '',
      replyTo: mailReplyTo.value || '',
      fromName: mailDisplayName.value || '元昇生物注释服务',
      cc: '',
      subject: `生工 16S 测序鉴定结果 - ${order.dir_name}（共 ${order.total_samples} 样本）`,
      body: '',
      attachmentName: `16S鉴定结果_${order.dir_name}.zip`,
    }
    showSendModal.value = true
    await loadSangonSendDraft(order)
  }

  async function resetSangonSendDraft(): Promise<void> {
    if (!sendOrderTarget.value) return
    await loadSangonSendDraft(sendOrderTarget.value)
  }

  async function confirmSendResultMail(payload: MailComposeSubmitPayload): Promise<void> {
    if (!sendOrderTarget.value) return
    sendingMail.value = true
    try {
      const targetTo = payload.toSelf ? 'self' : payload.to.trim() || 'self'
      const data = await postJson(`${API}/send_result`, {
        order_dir_name: sendOrderTarget.value.dir_name,
        sangon_root: sangonRoot.value || null,
        to: targetTo,
        cc: payload.cc.trim() || null,
        from_name: payload.fromName.trim() || null,
        subject: payload.subject.trim() || null,
        body: payload.body.trim() ? payload.body : null,
        attachment_name: payload.attachmentName.trim() || null,
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
        ignore_history: mailFilter.value.ignoreHistory,
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
        nonSequencingCount: data.non_sequencing_count || 0,
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
        mailRecordsRef.value?.expand?.()
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
        download_url: mail.download_url,
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
    const targets = orderNames.length ? orderNames : orderFilter.value !== 'ignored' ? checkedOrderNames.value : []

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
        force_reblast: forceReblast.value,
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
    const targets =
      orderNames && orderNames.length
        ? orderNames
        : checkedOrderNames.value.length
          ? checkedOrderNames.value
          : activeOrders.value.length
            ? activeOrders.value.map((o) => o.dir_name)
            : ['__ALL__']
    cleanupTargetOrders.value = targets
    showCleanup.value = true
  }

  async function confirmCleanup(targets: string[]): Promise<void> {
    busy.value = true
    try {
      const data = await postJson(`${API}/cleanup`, { order_names: cleanupTargetOrders.value, targets })
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
        smtp_auth_code: null,
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

  async function handleAutoDownloadOrders(
    orderNames: string[] = [],
    autoRunBlast = autoBlastAfterDownload.value
  ): Promise<void> {
    const targets = orderNames.length
      ? orderNames
      : orderFilter.value !== 'ignored' && checkedDownloadableNames.value.length > 0
        ? checkedDownloadableNames.value
        : []

    const targetOrderObjs = targets.length
      ? activeOrders.value.filter((o) => targets.includes(o.dir_name) && isOrderDownloadable(o))
      : downloadableOrders.value

    if (!targetOrderObjs.length) {
      setInfo('当前没有可自动下载的待处理订单（请确认已运行「检查新订单」获取下载链接，或直接点击待认领下载包）')
      return
    }

    const needsWebLogin = targetOrderObjs.some((o) => !o.download_zip_ready && Boolean(o.download_url || o.cx_order_id))
    if (needsWebLogin && (!sangonAuth.value.account || !sangonAuth.value.password_ready)) {
      pendingDownloadTask.value = { orderNames: targets, autoRunBlast }
      openSangonAuthEditor('检测到需登录生工官网下载压缩包，请先保存一次生工账号与登录密码（保存后将自动继续下载）。')
      return
    }
    if (needsWebLogin && browserEnv.value && !browserEnv.value.enabled) {
      openSangonAuthEditor('检测到当前无头浏览器已被禁用 (enabled=false)，请先在下方勾选启用无头浏览器并点击「应用浏览器配置并检查自修复」。')
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
        force_reblast: forceReblast.value,
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
      if (data.sangon_auth) sangonAuth.value = data.sangon_auth
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

  async function handleRepairBrowser(payload?: {
    enabled?: boolean
    headless?: boolean
    use_system_browser_fallback?: boolean
    auto_install?: boolean
    probe_launch?: boolean
  }): Promise<void> {
    repairingBrowser.value = true
    try {
      const data = await postJson(`${BROWSER_ENV_API}/repair`, {
        auto_install: true,
        probe_launch: true,
        ...(payload || {}),
      })
      browserEnv.value = data as BrowserEnvStatus
      const acts = (data.actions || []).filter(Boolean)
      if (data.ready) {
        const modeName = data.mode || 'playwright_chromium'
        setInfo(acts.length ? `无头浏览器已自修复并就绪 (${modeName})：${acts.join('；')}` : `无头浏览器检查通过 (${modeName})`)
      } else if (!data.enabled) {
        setInfo('已保存无头浏览器配置：当前状态为已禁用 (enabled=false)')
      } else {
        const detail = (data.warnings || []).join('；') || data.issues?.[0]?.message || '仍未就绪，请检查网络或配置'
        setError(`无头浏览器自修复未完全就绪：${detail}`)
      }
    } catch (err) {
      setError(err)
    } finally {
      repairingBrowser.value = false
    }
  }

  onMounted(() => {
    void loadOverview()
    pollTimer = setInterval(() => {
      if (runtime.value?.running || trackingRun.value) void loadOverview()
    }, 1200)
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
    if (followUpTimer) clearTimeout(followUpTimer)
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
    hasOrderDownloadChannel,
    isOrderDownloadable,
    statusLabel,
    toggleCheckAll,
    loadOverview,
    selectOrderAndLoadResults,
    handleSaveRoot,
    handleSaveDownloadsDir,
    handleImportDownloads,
    handleClaimSingleOrder,
    handleClaimSingleCandidate,
    handleIgnoreOrders,
    handleToggleMailIgnore,
    handleSaveIgnoreKeywords,
    openSendResultModal,
    resetSangonSendDraft,
    confirmSendResultMail,
    handleCheckNewOrders,
    handleInitOrderFromMail,
    handleRunPipeline,
    openCleanupModal,
    confirmCleanup,
    openAuthEditor,
    saveImapAuth,
    openSangonAuthEditor,
    closeSangonAuthEditor,
    handleSaveSangonAuth,
    handleClearSangonPassword,
    handleToggleAutoConfirmFee,
    handleRepairBrowser,
    handleAutoDownloadOrders,
  }
}
