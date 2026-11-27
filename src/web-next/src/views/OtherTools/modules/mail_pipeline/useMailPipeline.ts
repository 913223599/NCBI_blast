/**
 * useMailPipeline - 邮件收件 -> 注释 -> Word 报告 -> SMTP 回传全流程状态机
 * 从 MailAutoPipelineModule.vue 拆解而出，封装轮询、收件、配置迁移、发信预览与清理逻辑。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MailComposeSubmitPayload, MailDraftPayload } from '../../components/MailComposeModal.vue'
import type { CleanupOption } from '../../components/CleanupDialog.vue'
import { describeMigration, getJson, openLocalPath, postJson, type MigrationInfo } from '../../api'
import { useConfirmDialog } from '../../../../composables/useConfirmDialog'
import {
  extractLastLine,
  inboxStatusLabel,
  stageLabel,
  type AuthInfo,
  type BatchItem,
  type DocxReportItem,
  type InboxMailItem,
  type OutboundPackage,
  type ProcessedItem,
} from './mailTypes'

const API = '/api/other_tools/mail_pipeline'

export interface MailPipelineRuntime {
  running: boolean
  started_at: string | null
  finished_at: string | null
  last_exit_code: number | null
  last_command: string
  last_output: string
  current_stage: string
}

interface MailPipelineConfigApi {
  imap_server?: string
  imap_port?: number
  account?: string
  sender_whitelist?: string[]
  since_days?: number
  download_dir?: string
  smtp_server?: string
  smtp_port?: number
  smtp_account?: string
  smtp_display_name?: string
  reply_to?: string
  send_dir?: string
}

interface MailOverviewResponse {
  auth?: AuthInfo
  runtime?: MailPipelineRuntime
  batches?: BatchItem[]
  pending_batches_count?: number
  ignored_batches_count?: number
  outbound_packages?: OutboundPackage[]
  docx_reports?: DocxReportItem[]
  processed_items?: ProcessedItem[]
  processed_count?: number
  pipeline_logs?: string[]
  resolved_download_dir?: string
  resolved_send_dir?: string
  config?: MailPipelineConfigApi
}

interface MailListResponse {
  items?: InboxMailItem[]
  scanned?: number
  raw_total?: number
  unique_total?: number
  dedup_removed?: number
  processed_skipped?: number
  page?: number
  page_size?: number
  total?: number
  total_pages?: number
}

interface MailFetchResponse {
  scanned: number
  matched: number
  saved_count: number
  skipped_processed: number
  skipped_dup_mails?: number
}

interface MailRunResponse {
  runtime: MailPipelineRuntime
}

interface MailAuthResponse {
  auth: AuthInfo
}

interface MailConfigResponse {
  migrations?: MigrationInfo[]
}

interface MailCleanupResponse {
  removed_count: number
  freed_mb: number
  index_removed?: number
}

interface MailSendPreviewResponse {
  attached_files?: string[]
  to?: string
  reply_to?: string
  from_name?: string
  cc?: string
  subject?: string
  body?: string
  attachment_name?: string
}

interface MailSendExecResponse {
  to: string
  attachment: string
  attachment_size: number
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const msg = (err as { message?: unknown }).message
    if (typeof msg === 'string' && msg) return msg
  }
  return String(err)
}

export function useMailPipeline() {
  const confirmDialog = useConfirmDialog()

  const actionMessage = ref('')
  const errorMessage = ref('')
  const busy = ref(false)
  const showConfigModal = ref(false)
  const showAuthModal = ref(false)
  const showCleanup = ref(false)
  const showTestSendModal = ref(false)
  const loadingTestSendDraft = ref(false)
  const testingSend = ref(false)
  const testSendAttachReport = ref(false)
  const testSendAttachedFiles = ref<string[]>(['smtp_self_test.txt'])
  const testSendDraft = ref<MailDraftPayload>({
    to: '',
    replyTo: '',
    fromName: '元昇生物注释服务',
    cc: '',
    subject: '',
    body: '',
    attachmentName: '',
  })
  const showBatchRunModal = ref(false)
  const batchRunForm = ref({
    batchName: '',
    subject: '',
    attachmentsDesc: '',
    sendMode: 'only_pack' as 'only_pack' | 'self' | 'custom',
    customTo: '',
    subjectPrefix: '【自动】',
    extraNote: '',
  })
  const showPkgSendModal = ref(false)
  const loadingPkgDraft = ref(false)
  const sendingPkg = ref(false)
  const pkgSendTarget = ref<OutboundPackage | null>(null)
  const pkgSendDraft = ref<MailDraftPayload>({
    to: '',
    replyTo: '',
    fromName: '元昇生物注释服务',
    cc: '',
    subject: '',
    body: '',
    attachmentName: '',
  })
  const activeSubTab = ref<'batches' | 'inbox' | 'outbound' | 'processed' | 'logs'>('batches')

  const inboxMails = ref<InboxMailItem[]>([])
  const inboxLoaded = ref(false)
  const inboxLoading = ref(false)
  const inboxFilter = ref({ dedup: true, onlyNew: false })
  const inboxStats = ref({
    scanned: 0,
    rawTotal: 0,
    uniqueTotal: 0,
    dedupRemoved: 0,
    processedSkipped: 0,
    page: 1,
    pageSize: 10,
    total: 0,
    totalPages: 1,
  })

  const batchPage = ref(1)
  const batchPageSize = ref(8)
  const outboundPage = ref(1)
  const outboundPageSize = ref(5)
  const docxPage = ref(1)
  const docxPageSize = ref(5)
  const processedPage = ref(1)
  const processedPageSize = ref(10)

  const auth = ref<AuthInfo>({
    imap_ready: false,
    imap_masked: '',
    imap_file: '',
    smtp_ready: false,
    smtp_masked: '',
    smtp_file: '',
    smtp_separate: false,
  })
  const authForm = ref({ imap: '', smtp: '', clearSmtp: false })

  const runtime = ref<MailPipelineRuntime>({
    running: false,
    started_at: null,
    finished_at: null,
    last_exit_code: null,
    last_command: '',
    last_output: '',
    current_stage: 'idle',
  })

  const configForm = ref({
    imap_server: 'imap.qq.com',
    imap_port: 993,
    account: '',
    sender_whitelist_str: '',
    since_days: 7,
    download_dir: 'results/email_downloads',
    smtp_server: 'smtp.qq.com',
    smtp_port: 465,
    smtp_account: '',
    smtp_display_name: '',
    reply_to: '',
    send_dir: 'results/email_sends',
  })

  const resolvedDownloadDir = ref('')
  const resolvedSendDir = ref('')

  const runOptions = ref({
    since_days: 7,
    send_mode: 'config' as 'config' | 'self' | 'none',
    subject_prefix: '【自动】',
    extra_note: '',
  })

  const batches = ref<BatchItem[]>([])
  const pendingBatchesCount = ref(0)
  const ignoredBatchesCount = ref(0)
  const initializedOverview = ref(false)
  const trackingRun = ref(false)
  const outboundPackages = ref<OutboundPackage[]>([])
  const docxReports = ref<DocxReportItem[]>([])
  const processedItems = ref<ProcessedItem[]>([])
  const processedCount = ref(0)
  const pipelineLogs = ref<string[]>([])

  const cleanupOptions: CleanupOption[] = [
    { key: 'batches', label: '收件批次 (up_*)', desc: '下载目录中的附件批次文件夹', checked: true },
    { key: 'outbound', label: '回传压缩包', desc: '回传目录中的 *.zip 与 *.manifest.json', checked: true },
    { key: 'docx', label: 'Word 报告', desc: '回传目录中的 *.docx' },
    { key: 'annotations', label: '注释中间目录', desc: 'results/annotations 下与回传包对应的 ANNO_* 目录' },
    { key: 'logs', label: '流水线日志', desc: '清空 pipeline.log 与 run_errors.log' },
    { key: 'index', label: '去重记录', desc: '清除后已处理过的附件会被重新下载处理', danger: true },
  ]

  let pollTimer: ReturnType<typeof setInterval> | null = null

  const pagedBatches = computed(() => {
    const start = (batchPage.value - 1) * batchPageSize.value
    return batches.value.slice(start, start + batchPageSize.value)
  })
  const pagedOutboundPackages = computed(() => {
    const start = (outboundPage.value - 1) * outboundPageSize.value
    return outboundPackages.value.slice(start, start + outboundPageSize.value)
  })
  const pagedDocxReports = computed(() => {
    const start = (docxPage.value - 1) * docxPageSize.value
    return docxReports.value.slice(start, start + docxPageSize.value)
  })
  const pagedProcessedItems = computed(() => {
    const start = (processedPage.value - 1) * processedPageSize.value
    return processedItems.value.slice(start, start + processedPageSize.value)
  })

  watch(() => batches.value.length, (len) => {
    const maxPage = Math.max(1, Math.ceil(len / batchPageSize.value))
    if (batchPage.value > maxPage) batchPage.value = maxPage
  })
  watch(() => outboundPackages.value.length, (len) => {
    const maxPage = Math.max(1, Math.ceil(len / outboundPageSize.value))
    if (outboundPage.value > maxPage) outboundPage.value = maxPage
  })
  watch(() => docxReports.value.length, (len) => {
    const maxPage = Math.max(1, Math.ceil(len / docxPageSize.value))
    if (docxPage.value > maxPage) docxPage.value = maxPage
  })
  watch(() => processedItems.value.length, (len) => {
    const maxPage = Math.max(1, Math.ceil(len / processedPageSize.value))
    if (processedPage.value > maxPage) processedPage.value = maxPage
  })

  function setInfo(msg: string): void {
    actionMessage.value = msg
    errorMessage.value = ''
  }

  function setError(err: unknown): void {
    errorMessage.value = getErrorMessage(err)
    actionMessage.value = ''
  }

  async function loadOverview(): Promise<void> {
    try {
      const data = await getJson<MailOverviewResponse>(`${API}/overview`)
      if (data.auth) auth.value = data.auth
      const nextRuntime = data.runtime || runtime.value
      runtime.value = nextRuntime
      batches.value = data.batches || []
      pendingBatchesCount.value = data.pending_batches_count || 0
      ignoredBatchesCount.value = data.ignored_batches_count || 0
      outboundPackages.value = data.outbound_packages || []
      docxReports.value = data.docx_reports || []
      processedItems.value = data.processed_items || []
      processedCount.value = data.processed_count || 0
      pipelineLogs.value = data.pipeline_logs || []
      resolvedDownloadDir.value = data.resolved_download_dir || ''
      resolvedSendDir.value = data.resolved_send_dir || ''

      const c = data.config || {}
      configForm.value = {
        imap_server: c.imap_server || 'imap.qq.com',
        imap_port: c.imap_port || 993,
        account: c.account || '',
        sender_whitelist_str: (c.sender_whitelist || []).join(', '),
        since_days: c.since_days ?? 7,
        download_dir: data.resolved_download_dir || c.download_dir || 'results/email_downloads',
        smtp_server: c.smtp_server || 'smtp.qq.com',
        smtp_port: c.smtp_port || 465,
        smtp_account: c.smtp_account || '',
        smtp_display_name: c.smtp_display_name || '',
        reply_to: c.reply_to || '',
        send_dir: data.resolved_send_dir || c.send_dir || 'results/email_sends',
      }
      if (!initializedOverview.value) {
        runOptions.value.since_days = c.since_days ?? 7
        initializedOverview.value = true
      }

      if (nextRuntime?.running) {
        trackingRun.value = true
        const liveLine = extractLastLine(nextRuntime.last_output || '')
        setInfo(`流水线执行中（${stageLabel(nextRuntime.current_stage)}）${liveLine ? '：' + liveLine : '...'}`)
      } else if (trackingRun.value) {
        trackingRun.value = false
        const summary = extractLastLine(nextRuntime?.last_output || '')
        if (nextRuntime?.last_exit_code === 0) {
          setInfo(summary ? `流水线执行完成：${summary}` : '流水线执行完成')
        } else {
          setError(
            `流水线执行失败（退出码 ${nextRuntime?.last_exit_code ?? -1}）${summary ? '：' + summary : '，请查看日志'}`
          )
        }
      }
    } catch (err: unknown) {
      errorMessage.value = `加载失败: ${getErrorMessage(err)}`
    }
  }

  async function loadInboxMails(page = 1, pageSize = inboxStats.value.pageSize): Promise<void> {
    inboxLoading.value = true
    try {
      const data = await postJson<MailListResponse>(`${API}/list_mails`, {
        page,
        page_size: pageSize,
        since_days: runOptions.value.since_days,
        dedup: inboxFilter.value.dedup,
        only_new: inboxFilter.value.onlyNew,
      })
      inboxMails.value = data.items || []
      inboxLoaded.value = true
      inboxStats.value = {
        scanned: data.scanned || 0,
        rawTotal: data.raw_total || 0,
        uniqueTotal: data.unique_total || 0,
        dedupRemoved: data.dedup_removed || 0,
        processedSkipped: data.processed_skipped || 0,
        page: data.page || 1,
        pageSize: data.page_size || pageSize,
        total: data.total || 0,
        totalPages: data.total_pages || 1,
      }
    } catch (err) {
      setError(err)
    } finally {
      inboxLoading.value = false
    }
  }

  async function handleFetchOnly(): Promise<void> {
    setInfo('正在收件...')
    try {
      const data = await postJson<MailFetchResponse>(`${API}/fetch`, { since_days: runOptions.value.since_days })
      const dupMailsPart = data.skipped_dup_mails ? `，邮件级去重 ${data.skipped_dup_mails} 封` : ''
      setInfo(
        `收件完成：扫描 ${data.scanned} 封，命中 ${data.matched} 封${dupMailsPart}，新保存 ${data.saved_count} 个附件，跳过已处理 ${data.skipped_processed} 个`
      )
      await loadOverview()
      if (inboxLoaded.value) await loadInboxMails(inboxStats.value.page, inboxStats.value.pageSize)
    } catch (err) {
      setError(err)
    }
  }

  function showAllInboxMails(): void {
    inboxFilter.value.onlyNew = false
    void loadInboxMails(1)
  }

  function openInboxTab(): void {
    activeSubTab.value = 'inbox'
    if (!inboxLoaded.value && auth.value.imap_ready) {
      void loadInboxMails(1)
    }
  }

  async function handleRunPipeline(): Promise<void> {
    const mode = runOptions.value.send_mode
    const modeTip = mode === 'self' ? '（完成后发给自己测试）' : mode === 'none' ? '（仅注释打包，不发信）' : ''
    setInfo(`启动流水线${modeTip}...`)
    try {
      const payload: Record<string, unknown> = {
        since_days: runOptions.value.since_days,
        no_send: mode === 'none',
        subject_prefix: runOptions.value.subject_prefix,
        extra_note: runOptions.value.extra_note || null,
      }
      if (mode === 'self') payload.to = 'self'
      const data = await postJson<MailRunResponse>(`${API}/run`, payload)
      runtime.value = data.runtime
      trackingRun.value = true
      setInfo(`流水线已在后台启动${modeTip}`)
    } catch (err) {
      setError(err)
    }
  }

  function openBatchRunModal(batch: BatchItem): void {
    const files = (batch.attachments || []).map((a) => a.filename).filter(Boolean).join('、')
    batchRunForm.value = {
      batchName: batch.batch_name,
      subject: batch.subject || '-',
      attachmentsDesc: files || '-',
      sendMode: 'only_pack',
      customTo: configForm.value.account || configForm.value.smtp_account || '',
      subjectPrefix: runOptions.value.subject_prefix || '【自动】',
      extraNote: runOptions.value.extra_note || '',
    }
    showBatchRunModal.value = true
  }

  async function confirmBatchRun(overrideMode?: 'only_pack' | 'self' | 'custom'): Promise<void> {
    const mode = overrideMode || batchRunForm.value.sendMode
    const batchName = batchRunForm.value.batchName
    if (!batchName) return
    const payload: Record<string, unknown> = {
      annotate_only_batch: batchName,
      no_send: mode === 'only_pack',
      force_send: mode === 'custom',
      subject_prefix: batchRunForm.value.subjectPrefix || '【自动】',
      extra_note: batchRunForm.value.extraNote.trim() || null,
    }
    if (mode === 'self') {
      payload.to = 'self'
    } else if (mode === 'custom' && batchRunForm.value.customTo.trim()) {
      payload.to = batchRunForm.value.customTo.trim()
    }
    setInfo(`启动批次重跑: ${batchName}`)
    try {
      const data = await postJson<MailRunResponse>(`${API}/run`, payload)
      runtime.value = data.runtime
      trackingRun.value = true
      showBatchRunModal.value = false
      setInfo(
        mode === 'self'
          ? `已启动批次 ${batchName} 重跑，完成后将发送至本人邮箱`
          : mode === 'custom'
            ? `已启动批次 ${batchName} 重跑并回传`
            : `已启动批次 ${batchName} 重跑（仅注释与打包，不发邮件）`
      )
    } catch (err) {
      setError(err)
    }
  }

  function buildConfigPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    const whitelist = configForm.value.sender_whitelist_str.split(',').map((s) => s.trim()).filter(Boolean)
    return { ...configForm.value, sender_whitelist: whitelist, migrate: true, ...overrides }
  }

  async function handleSaveConfig(): Promise<void> {
    busy.value = true
    try {
      const authPayload: Record<string, string | null> = { imap_auth_code: null, smtp_auth_code: null }
      if (authForm.value.imap.trim()) authPayload.imap_auth_code = authForm.value.imap.trim()
      if (authForm.value.clearSmtp) authPayload.smtp_auth_code = ''
      else if (authForm.value.smtp.trim()) authPayload.smtp_auth_code = authForm.value.smtp.trim()

      if (authPayload.imap_auth_code !== null || authPayload.smtp_auth_code !== null) {
        const authRes = await postJson<MailAuthResponse>(`${API}/auth`, authPayload)
        auth.value = authRes.auth
        authForm.value = { imap: '', smtp: '', clearSmtp: false }
      }

      const data = await postJson<MailConfigResponse>(`${API}/config`, buildConfigPayload())
      const msgs = (data.migrations || []).map(describeMigration).filter(Boolean)
      runOptions.value.since_days = configForm.value.since_days ?? 7
      showConfigModal.value = false
      setInfo(msgs.length ? `配置已保存。${msgs.join('；')}` : '配置已保存')
      await loadOverview()
    } catch (err) {
      setError(err)
    } finally {
      busy.value = false
    }
  }

  async function handleSaveDir(field: 'download_dir' | 'send_dir', value: string): Promise<void> {
    busy.value = true
    setInfo('正在迁移目录...')
    try {
      const data = await postJson<MailConfigResponse>(`${API}/config`, buildConfigPayload({ [field]: value }))
      const msgs = (data.migrations || []).map(describeMigration).filter(Boolean)
      setInfo(msgs.length ? `目录已更新。${msgs.join('；')}` : '目录已更新')
      await loadOverview()
    } catch (err) {
      setError(err)
    } finally {
      busy.value = false
    }
  }

  function openAuthModal(): void {
    authForm.value = { imap: '', smtp: '', clearSmtp: false }
    showAuthModal.value = true
  }

  async function handleSaveAuth(): Promise<void> {
    const payload: Record<string, string | null> = { imap_auth_code: null, smtp_auth_code: null }
    if (authForm.value.imap.trim()) payload.imap_auth_code = authForm.value.imap.trim()
    if (authForm.value.clearSmtp) payload.smtp_auth_code = ''
    else if (authForm.value.smtp.trim()) payload.smtp_auth_code = authForm.value.smtp.trim()
    if (payload.imap_auth_code === null && payload.smtp_auth_code === null) {
      showAuthModal.value = false
      return
    }
    try {
      const data = await postJson<MailAuthResponse>(`${API}/auth`, payload)
      auth.value = data.auth
      showAuthModal.value = false
      setInfo('授权码已更新')
    } catch (err) {
      setError(err)
    }
  }

  async function runCleanup(targets: string[], olderThanDays: number | null, names: string[] = []): Promise<void> {
    busy.value = true
    try {
      const data = await postJson<MailCleanupResponse>(`${API}/cleanup`, { targets, older_than_days: olderThanDays, names })
      showCleanup.value = false
      const idxPart = data.index_removed ? `，去重记录 ${data.index_removed} 条` : ''
      setInfo(`已清理 ${data.removed_count} 项${idxPart}，释放 ${data.freed_mb} MB`)
      await loadOverview()
    } catch (err) {
      setError(err)
    } finally {
      busy.value = false
    }
  }

  async function deleteOne(target: string, name: string, label: string): Promise<void> {
    const ok = await confirmDialog.confirm({
      title: '删除历史项目',
      message: `确认删除 ${label}？此操作不可恢复。`,
      confirmText: '确认删除',
      danger: true,
    })
    if (!ok) return
    await runCleanup([target], null, [name])
  }

  async function handleToggleBatchIgnore(batch: BatchItem): Promise<void> {
    const willIgnore = !batch.ignored && batch.pipeline_status !== 'ignored'
    busy.value = true
    try {
      await postJson(`${API}/batch_ignore`, {
        batch_name: batch.batch_name,
        ignore: willIgnore,
        reason: willIgnore ? '从收件批次列表手动跳过' : '',
      })
      setInfo(
        willIgnore
          ? `已将批次 ${batch.batch_name} 标记为跳过（运行流水线将自动略过，原序列附件保留）`
          : `已恢复批次 ${batch.batch_name} 原始状态`
      )
      await loadOverview()
    } catch (err) {
      setError(err)
    } finally {
      busy.value = false
    }
  }

  async function loadTestSendDraft(attachReport: boolean): Promise<void> {
    loadingTestSendDraft.value = true
    try {
      const data = await postJson<MailSendPreviewResponse>(`${API}/test_send_preview`, {
        note: '桌面工作台自检发信验证',
        attach_latest_report: attachReport,
      })
      testSendAttachedFiles.value = data.attached_files || ['smtp_self_test.txt']
      testSendDraft.value = {
        to: data.to || configForm.value.account || configForm.value.smtp_account || '',
        replyTo: data.reply_to || configForm.value.reply_to || '',
        fromName: data.from_name || configForm.value.smtp_display_name || '元昇生物注释服务',
        cc: data.cc || '',
        subject: data.subject || '',
        body: data.body || '',
        attachmentName: data.attachment_name || '',
      }
    } catch (err) {
      setError(err)
    } finally {
      loadingTestSendDraft.value = false
    }
  }

  async function openTestSendModal(): Promise<void> {
    const withReport = docxReports.value.length > 0
    testSendAttachReport.value = withReport
    testSendAttachedFiles.value =
      withReport && docxReports.value[0] ? ['smtp_self_test.txt', docxReports.value[0].name] : ['smtp_self_test.txt']
    testSendDraft.value = {
      to: configForm.value.account || configForm.value.smtp_account || '',
      replyTo: configForm.value.reply_to || '',
      fromName: configForm.value.smtp_display_name || '元昇生物注释服务',
      cc: '',
      subject: '【自检验证】邮件自动回传 SMTP 测试',
      body: '',
      attachmentName: 'SMTP_自检验证包.zip',
    }
    showTestSendModal.value = true
    await loadTestSendDraft(withReport)
  }

  async function handleToggleTestAttachReport(checked: boolean): Promise<void> {
    testSendAttachReport.value = checked
    await loadTestSendDraft(checked)
  }

  async function confirmTestSend(payload: MailComposeSubmitPayload): Promise<void> {
    testingSend.value = true
    try {
      const targetTo = payload.toSelf ? 'self' : payload.to.trim() || 'self'
      const data = await postJson<MailSendExecResponse>(`${API}/test_send`, {
        to: targetTo,
        cc: payload.cc.trim() || null,
        from_name: payload.fromName.trim() || null,
        subject: payload.subject.trim() || null,
        body: payload.body.trim() ? payload.body : null,
        attachment_name: payload.attachmentName.trim() || null,
        attach_latest_report: payload.attachLatestReport,
      })
      showTestSendModal.value = false
      setInfo(`测试邮件已发至 ${data.to}：附件 ${data.attachment} (${(data.attachment_size / 1024).toFixed(1)} KB)`)
    } catch (err) {
      setError(err)
    } finally {
      testingSend.value = false
    }
  }

  async function loadPkgSendDraft(pkg: OutboundPackage): Promise<void> {
    loadingPkgDraft.value = true
    try {
      const data = await postJson<MailSendPreviewResponse>(`${API}/send_package_preview`, { zip_name: pkg.zip_name })
      pkgSendDraft.value = {
        to: data.to || configForm.value.account || configForm.value.smtp_account || '',
        replyTo: data.reply_to || configForm.value.reply_to || '',
        fromName: data.from_name || configForm.value.smtp_display_name || '元昇生物注释服务',
        cc: data.cc || '',
        subject: data.subject || `噬菌体注释结果回传 - ${pkg.task_id}`,
        body: data.body || '',
        attachmentName: data.attachment_name || pkg.zip_name,
      }
    } catch (err) {
      setError(err)
    } finally {
      loadingPkgDraft.value = false
    }
  }

  async function openPkgSendModal(pkg: OutboundPackage): Promise<void> {
    pkgSendTarget.value = pkg
    pkgSendDraft.value = {
      to: configForm.value.account || configForm.value.smtp_account || '',
      replyTo: configForm.value.reply_to || '',
      fromName: configForm.value.smtp_display_name || '元昇生物注释服务',
      cc: '',
      subject: `噬菌体注释结果回传 - ${pkg.task_id}`,
      body: '',
      attachmentName: pkg.zip_name,
    }
    showPkgSendModal.value = true
    await loadPkgSendDraft(pkg)
  }

  async function resetPkgSendDraft(): Promise<void> {
    if (!pkgSendTarget.value) return
    await loadPkgSendDraft(pkgSendTarget.value)
  }

  async function confirmPkgSend(payload: MailComposeSubmitPayload): Promise<void> {
    if (!pkgSendTarget.value) return
    sendingPkg.value = true
    try {
      const targetTo = payload.toSelf ? 'self' : payload.to.trim() || 'self'
      const data = await postJson<MailSendExecResponse>(`${API}/send_package`, {
        zip_name: pkgSendTarget.value.zip_name,
        to: targetTo,
        cc: payload.cc.trim() || null,
        from_name: payload.fromName.trim() || null,
        subject: payload.subject.trim() || null,
        body: payload.body.trim() ? payload.body : null,
        attachment_name: payload.attachmentName.trim() || null,
      })
      showPkgSendModal.value = false
      setInfo(`结果包已发至 ${data.to}：${data.attachment} (${(data.attachment_size / 1024).toFixed(1)} KB)`)
    } catch (err) {
      setError(err)
    } finally {
      sendingPkg.value = false
    }
  }

  onMounted(() => {
    void loadOverview()
    pollTimer = setInterval(() => {
      if (runtime.value?.running || trackingRun.value) void loadOverview()
    }, 2500)
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
  })

  return {
    openLocalPath,
    actionMessage,
    errorMessage,
    busy,
    showConfigModal,
    showAuthModal,
    showCleanup,
    showTestSendModal,
    loadingTestSendDraft,
    testingSend,
    testSendAttachReport,
    testSendAttachedFiles,
    testSendDraft,
    showBatchRunModal,
    batchRunForm,
    showPkgSendModal,
    loadingPkgDraft,
    sendingPkg,
    pkgSendTarget,
    pkgSendDraft,
    activeSubTab,
    inboxMails,
    inboxLoaded,
    inboxLoading,
    inboxFilter,
    inboxStats,
    batchPage,
    batchPageSize,
    outboundPage,
    outboundPageSize,
    docxPage,
    docxPageSize,
    processedPage,
    processedPageSize,
    auth,
    authForm,
    runtime,
    configForm,
    resolvedDownloadDir,
    resolvedSendDir,
    runOptions,
    batches,
    pendingBatchesCount,
    ignoredBatchesCount,
    outboundPackages,
    docxReports,
    processedItems,
    processedCount,
    pipelineLogs,
    cleanupOptions,
    pagedBatches,
    pagedOutboundPackages,
    pagedDocxReports,
    pagedProcessedItems,
    inboxStatusLabel,
    stageLabel,
    loadOverview,
    handleFetchOnly,
    loadInboxMails,
    showAllInboxMails,
    openInboxTab,
    handleRunPipeline,
    openBatchRunModal,
    confirmBatchRun,
    handleSaveConfig,
    handleSaveDir,
    openAuthModal,
    handleSaveAuth,
    runCleanup,
    deleteOne,
    handleToggleBatchIgnore,
    loadTestSendDraft,
    openTestSendModal,
    handleToggleTestAttachReport,
    confirmTestSend,
    openPkgSendModal,
    resetPkgSendDraft,
    confirmPkgSend,
  }
}
