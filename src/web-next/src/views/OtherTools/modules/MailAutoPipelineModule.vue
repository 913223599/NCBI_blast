<script setup lang="ts">
/**
 * MailAutoPipelineModule - 邮件收件 -> 注释 -> Word 报告 -> SMTP 回传
 * 职责：流水线状态展示与触发、邮箱配置与授权码编辑、目录修改迁移、历史数据清理
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import PathField from '../components/PathField.vue'
import CleanupDialog from '../components/CleanupDialog.vue'
import PaginationBar from '../components/PaginationBar.vue'
import type { CleanupOption } from '../components/CleanupDialog.vue'
import { getJson, postJson, openLocalPath, describeMigration } from '../api'

interface AttachmentItem {
  filename: string
  size_bytes: number
  sha256?: string
  path: string
}

interface InboxAttachmentItem {
  filename: string
  size_bytes: number
  sha256: string
  already_processed: boolean
}

interface InboxMailItem {
  seq: number
  message_id: string
  sender: string
  subject: string
  date: string
  duplicate_count: number
  status: 'new' | 'partial' | 'processed' | 'no_attachment'
  new_attachment_count: number
  processed_attachment_count: number
  attachments: InboxAttachmentItem[]
}

interface BatchItem {
  batch_name: string
  batch_path: string
  download_time: string
  sender: string
  subject: string
  mail_date: string
  attachments: AttachmentItem[]
  pipeline_status?: string
  pipeline_status_label?: string
  send_status?: string
  task_ids?: string[]
  last_error?: string
  pending?: boolean
}

interface OutboundPackage {
  task_id: string
  pack_time: string
  zip_name: string
  zip_path: string
  size_kb: number
  file_count: number
}

interface DocxReportItem {
  name: string
  path: string
  size_kb: number
  mtime: string
}

interface ProcessedItem {
  sha256: string
  message_id?: string
  filename: string
  first_seen: string
  batch: string
  sender: string
  subject: string
  mail_date: string
}

interface AuthInfo {
  imap_ready: boolean
  imap_masked: string
  imap_file: string
  smtp_ready: boolean
  smtp_masked: string
  smtp_file: string
  smtp_separate: boolean
}

const API = '/api/other_tools/mail_pipeline'

const actionMessage = ref('')
const errorMessage = ref('')
const busy = ref(false)
const showConfigModal = ref(false)
const showAuthModal = ref(false)
const showCleanup = ref(false)
const showTestSendModal = ref(false)
const testingSend = ref(false)
const testSendForm = ref({
  to: '',
  subject: '',
  note: '',
  attachLatestReport: false
})
const showBatchRunModal = ref(false)
const batchRunForm = ref({
  batchName: '',
  subject: '',
  attachmentsDesc: '',
  sendMode: 'only_pack' as 'only_pack' | 'self' | 'custom',
  customTo: '',
  subjectPrefix: '【自动】',
  extraNote: ''
})
const showPkgSendModal = ref(false)
const sendingPkg = ref(false)
const pkgSendForm = ref({
  zipName: '',
  taskId: '',
  sizeKb: 0,
  fileCount: 0,
  to: '',
  subject: '',
  extraNote: ''
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
  totalPages: 1
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
  imap_ready: false, imap_masked: '', imap_file: '',
  smtp_ready: false, smtp_masked: '', smtp_file: '', smtp_separate: false
})
const authForm = ref({ imap: '', smtp: '', clearSmtp: false })

const runtime = ref<any>({
  running: false,
  started_at: null,
  finished_at: null,
  last_exit_code: null,
  last_command: '',
  last_output: '',
  current_stage: 'idle'
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
  send_dir: 'results/email_sends'
})

const resolvedDownloadDir = ref('')
const resolvedSendDir = ref('')

const runOptions = ref({
  since_days: 7,
  send_mode: 'config' as 'config' | 'self' | 'none',
  subject_prefix: '【自动】',
  extra_note: ''
})

const batches = ref<BatchItem[]>([])
const pendingBatchesCount = ref(0)
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
  { key: 'index', label: '去重记录', desc: '清除后已处理过的附件会被重新下载处理', danger: true }
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

function inboxStatusLabel(status: string): string {
  const map: Record<string, string> = {
    new: '待收新邮件',
    partial: '部分新附件',
    processed: '已全部去重',
    no_attachment: '无匹配附件'
  }
  return map[status] || status
}

function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    idle: '空闲',
    running: '执行中',
    fetching: '扫描收件箱',
    queued: '准备处理批次',
    annotating: '基因组注释中',
    reporting: '构建 Word 报告中',
    packing: '打包产物中',
    sending: 'SMTP 回传中',
    completed: '完成',
    failed: '异常退出'
  }
  return map[stage || 'idle'] || (stage || '空闲')
}

function extractLastLine(text: string): string {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean)
  return lines[lines.length - 1] ?? ''
}

function setInfo(msg: string): void {
  actionMessage.value = msg
  errorMessage.value = ''
}

function setError(err: any): void {
  errorMessage.value = err?.message || String(err)
  actionMessage.value = ''
}

async function loadOverview(): Promise<void> {
  try {
    const data = await getJson(`${API}/overview`)
    if (data.auth) auth.value = data.auth
    const nextRuntime = data.runtime || runtime.value
    runtime.value = nextRuntime
    batches.value = data.batches || []
    pendingBatchesCount.value = data.pending_batches_count || 0
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
      send_dir: data.resolved_send_dir || c.send_dir || 'results/email_sends'
    }
    if (!initializedOverview.value) {
      runOptions.value.since_days = c.since_days ?? 7
      initializedOverview.value = true
    }

    if (nextRuntime?.running) {
      trackingRun.value = true
      const liveLine = extractLastLine(nextRuntime.last_output || '')
      setInfo(
        `流水线执行中（${stageLabel(nextRuntime.current_stage)}）${liveLine ? '：' + liveLine : '...'}`
      )
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
  } catch (err: any) {
    errorMessage.value = `加载失败: ${err.message || err}`
  }
}

async function handleFetchOnly(): Promise<void> {
  setInfo('正在收件...')
  try {
    const data = await postJson(`${API}/fetch`, { since_days: runOptions.value.since_days })
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

async function loadInboxMails(page = 1, pageSize = inboxStats.value.pageSize): Promise<void> {
  inboxLoading.value = true
  try {
    const data = await postJson(`${API}/list_mails`, {
      page,
      page_size: pageSize,
      since_days: runOptions.value.since_days,
      dedup: inboxFilter.value.dedup,
      only_new: inboxFilter.value.onlyNew
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
      totalPages: data.total_pages || 1
    }
  } catch (err) {
    setError(err)
  } finally {
    inboxLoading.value = false
  }
}

function openInboxTab(): void {
  activeSubTab.value = 'inbox'
  if (!inboxLoaded.value && auth.value.imap_ready) {
    loadInboxMails(1)
  }
}

async function handleRunPipeline(): Promise<void> {
  const mode = runOptions.value.send_mode
  const modeTip = mode === 'self' ? '（完成后发给自己测试）' : mode === 'none' ? '（仅注释打包，不发信）' : ''
  setInfo(`启动流水线${modeTip}...`)
  try {
    const payload: Record<string, any> = {
      since_days: runOptions.value.since_days,
      no_send: mode === 'none',
      subject_prefix: runOptions.value.subject_prefix,
      extra_note: runOptions.value.extra_note || null
    }
    if (mode === 'self') payload.to = 'self'
    const data = await postJson(`${API}/run`, payload)
    runtime.value = data.runtime
    trackingRun.value = true
    setInfo(`流水线已在后台启动${modeTip}`)
  } catch (err) {
    setError(err)
  }
}

function openBatchRunModal(batch: BatchItem): void {
  const files = (batch.attachments || []).map(a => a.filename).filter(Boolean).join('、')
  batchRunForm.value = {
    batchName: batch.batch_name,
    subject: batch.subject || '-',
    attachmentsDesc: files || '-',
    sendMode: 'only_pack',
    customTo: configForm.value.account || configForm.value.smtp_account || '',
    subjectPrefix: runOptions.value.subject_prefix || '【自动】',
    extraNote: runOptions.value.extra_note || ''
  }
  showBatchRunModal.value = true
}

async function confirmBatchRun(overrideMode?: 'only_pack' | 'self' | 'custom'): Promise<void> {
  const mode = overrideMode || batchRunForm.value.sendMode
  const batchName = batchRunForm.value.batchName
  if (!batchName) return
  const payload: Record<string, any> = {
    annotate_only_batch: batchName,
    no_send: mode === 'only_pack',
    force_send: mode === 'custom',
    subject_prefix: batchRunForm.value.subjectPrefix || '【自动】',
    extra_note: batchRunForm.value.extraNote.trim() || null
  }
  if (mode === 'self') {
    payload.to = 'self'
  } else if (mode === 'custom' && batchRunForm.value.customTo.trim()) {
    payload.to = batchRunForm.value.customTo.trim()
  }
  setInfo(`启动批次重跑: ${batchName}`)
  try {
    const data = await postJson(`${API}/run`, payload)
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

function buildConfigPayload(overrides: Record<string, any> = {}): Record<string, any> {
  const whitelist = configForm.value.sender_whitelist_str.split(',').map(s => s.trim()).filter(Boolean)
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
      const authRes = await postJson(`${API}/auth`, authPayload)
      auth.value = authRes.auth
      authForm.value = { imap: '', smtp: '', clearSmtp: false }
    }

    const data = await postJson(`${API}/config`, buildConfigPayload())
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
    const data = await postJson(`${API}/config`, buildConfigPayload({ [field]: value }))
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
    const data = await postJson(`${API}/auth`, payload)
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
    const data = await postJson(`${API}/cleanup`, { targets, older_than_days: olderThanDays, names })
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

function deleteOne(target: string, name: string, label: string): void {
  if (!window.confirm(`确认删除 ${label}？此操作不可恢复。`)) return
  runCleanup([target], null, [name])
}

function openTestSendModal(): void {
  testSendForm.value = {
    to: configForm.value.account || configForm.value.smtp_account || '',
    subject: '',
    note: '桌面工作台自检发信验证',
    attachLatestReport: docxReports.value.length > 0
  }
  showTestSendModal.value = true
}

async function confirmTestSend(toSelf = true): Promise<void> {
  testingSend.value = true
  try {
    const targetTo = toSelf ? 'self' : (testSendForm.value.to.trim() || 'self')
    const data = await postJson(`${API}/test_send`, {
      to: targetTo,
      subject: testSendForm.value.subject.trim() || null,
      note: testSendForm.value.note.trim() || null,
      attach_latest_report: testSendForm.value.attachLatestReport
    })
    showTestSendModal.value = false
    setInfo(
      `测试邮件已发至 ${data.to}：附件 ${data.attachment} (${(data.attachment_size / 1024).toFixed(1)} KB)`
    )
  } catch (err) {
    setError(err)
  } finally {
    testingSend.value = false
  }
}

function openPkgSendModal(pkg: OutboundPackage): void {
  pkgSendForm.value = {
    zipName: pkg.zip_name,
    taskId: pkg.task_id,
    sizeKb: pkg.size_kb,
    fileCount: pkg.file_count,
    to: configForm.value.account || configForm.value.smtp_account || '',
    subject: '',
    extraNote: ''
  }
  showPkgSendModal.value = true
}

async function confirmPkgSend(toSelf = true): Promise<void> {
  if (!pkgSendForm.value.zipName) return
  sendingPkg.value = true
  try {
    const targetTo = toSelf ? 'self' : (pkgSendForm.value.to.trim() || 'self')
    const data = await postJson(`${API}/send_package`, {
      zip_name: pkgSendForm.value.zipName,
      to: targetTo,
      subject: pkgSendForm.value.subject.trim() || null,
      extra_note: pkgSendForm.value.extraNote.trim() || null
    })
    showPkgSendModal.value = false
    setInfo(
      `结果包已发至 ${data.to}：${data.attachment} (${(data.attachment_size / 1024).toFixed(1)} KB)`
    )
  } catch (err) {
    setError(err)
  } finally {
    sendingPkg.value = false
  }
}

onMounted(() => {
  loadOverview()
  pollTimer = setInterval(() => {
    if (runtime.value?.running || trackingRun.value) loadOverview()
  }, 2500)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="mail-pipeline-module">
    <!-- 流程 -->
    <div class="pipeline-steps-banner">
      <div class="step-node">
        <span class="step-idx">1</span>
        <div class="step-info"><strong>收件</strong><span>IMAP 拉取附件，SHA256 去重</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">2</span>
        <div class="step-info"><strong>注释</strong><span>Pharokka / Phold</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">3</span>
        <div class="step-info"><strong>Word 报告</strong><span>生成 .docx</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">4</span>
        <div class="step-info"><strong>打包</strong><span>结果文件压缩为 .zip</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">5</span>
        <div class="step-info"><strong>回传</strong><span>SMTP 发送至 {{ configForm.reply_to || '-' }}</span></div>
      </div>
    </div>

    <!-- 指标 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">授权码</div>
        <div class="metric-val" :class="auth.imap_ready ? 'ok' : 'warn'">{{ auth.imap_ready ? '已配置' : '未配置' }}</div>
        <div class="metric-sub">{{ configForm.account || '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">去重记录</div>
        <div class="metric-val">{{ processedCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">收件批次</div>
        <div class="metric-val">{{ batches.length }}</div>
        <div class="metric-sub">{{ pendingBatchesCount > 0 ? `待注释处理: ${pendingBatchesCount}` : '无待处理批次' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Word 报告 / 回传包</div>
        <div class="metric-val">{{ docxReports.length }} / {{ outboundPackages.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">运行状态</div>
        <div
          class="metric-val"
          :class="runtime.running ? 'running' : (runtime.current_stage === 'failed' ? 'warn' : 'idle')"
        >
          {{ runtime.running ? '运行中' : (runtime.current_stage === 'failed' ? '上次异常' : '空闲') }}
        </div>
        <div class="metric-sub">
          {{ runtime.running ? stageLabel(runtime.current_stage) : (runtime.finished_at ? `上次完成: ${runtime.finished_at}` : '-') }}
        </div>
      </div>
    </div>

    <!-- 目录 -->
    <div class="paths-panel">
      <PathField
        label="附件下载目录（输入）"
        :path="resolvedDownloadDir"
        :busy="busy || runtime.running"
        @save="v => handleSaveDir('download_dir', v)"
        @open="openLocalPath"
      />
      <PathField
        label="结果回传目录（输出）"
        :path="resolvedSendDir"
        :busy="busy || runtime.running"
        @save="v => handleSaveDir('send_dir', v)"
        @open="openLocalPath"
      />
    </div>

    <!-- 操作 -->
    <div class="control-bar">
      <div class="control-left">
        <label class="ctrl-item">
          <span>收件天数</span>
          <input type="number" v-model.number="runOptions.since_days" min="1" max="90" class="num-input" />
        </label>
        <label class="ctrl-item">
          <span>回传目标</span>
          <select v-model="runOptions.send_mode" class="select-input">
            <option value="config">按配置回传 ({{ configForm.reply_to || '-' }})</option>
            <option value="self">仅发给自己测试 ({{ configForm.account || configForm.smtp_account || '本人' }})</option>
            <option value="none">仅注释打包（不发信）</option>
          </select>
        </label>
        <label class="ctrl-item">
          <span>报告备注</span>
          <input type="text" v-model="runOptions.extra_note" placeholder="可选" class="text-input" />
        </label>
      </div>
      <div class="control-right">
        <button class="btn-secondary" @click="handleFetchOnly" :disabled="runtime.running">仅收件</button>
        <button class="btn-primary" @click="handleRunPipeline()" :disabled="runtime.running">
          {{ runtime.running ? '运行中...' : '运行流水线' }}
        </button>
        <button class="btn-outline" @click="openTestSendModal" :disabled="runtime.running">测试发信</button>
        <button class="btn-outline" @click="showConfigModal = true">邮箱配置</button>
        <button class="btn-outline" @click="openAuthModal">授权码</button>
        <button class="btn-outline danger" @click="showCleanup = true" :disabled="runtime.running">清理历史</button>
        <button class="btn-outline" @click="loadOverview">刷新</button>
      </div>
    </div>

    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <div class="sub-tabs-bar">
      <button :class="['sub-tab-btn', { active: activeSubTab === 'batches' }]" @click="activeSubTab = 'batches'">
        收件批次 ({{ batches.length }}<template v-if="pendingBatchesCount > 0"> · 待处理 {{ pendingBatchesCount }}</template>)
      </button>
      <button :class="['sub-tab-btn', { active: activeSubTab === 'inbox' }]" @click="openInboxTab">
        收件箱邮件{{ inboxLoaded ? ` (${inboxStats.total})` : '' }}
      </button>
      <button :class="['sub-tab-btn', { active: activeSubTab === 'outbound' }]" @click="activeSubTab = 'outbound'">
        报告与回传包 ({{ outboundPackages.length }})
      </button>
      <button :class="['sub-tab-btn', { active: activeSubTab === 'processed' }]" @click="activeSubTab = 'processed'">
        去重记录 ({{ processedCount }})
      </button>
      <button :class="['sub-tab-btn', { active: activeSubTab === 'logs' }]" @click="activeSubTab = 'logs'">
        日志
      </button>
    </div>

    <!-- 收件批次 -->
    <div v-if="activeSubTab === 'batches'" class="table-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>批次</th>
            <th>处理状态</th>
            <th>邮件主题</th>
            <th>发件人</th>
            <th>下载时间</th>
            <th>附件</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in pagedBatches" :key="b.batch_name">
            <td class="mono-cell">{{ b.batch_name }}</td>
            <td>
              <span
                :class="['batch-status-pill', b.pipeline_status || 'downloaded']"
                :title="b.last_error || (b.task_ids && b.task_ids.length ? b.task_ids.join(', ') : '')"
              >
                {{ b.pipeline_status_label || '待注释处理' }}
              </span>
            </td>
            <td class="bold-cell">{{ b.subject }}</td>
            <td>{{ b.sender }}</td>
            <td>{{ b.download_time }}</td>
            <td>
              <span v-for="att in b.attachments" :key="att.filename" class="file-pill">
                {{ att.filename }} ({{ (att.size_bytes / 1024).toFixed(1) }} KB)
              </span>
            </td>
            <td class="actions-cell">
              <button class="btn-mini primary" @click="openBatchRunModal(b)" :disabled="runtime.running">重跑</button>
              <button class="btn-mini" @click="openLocalPath(b.batch_path)">打开</button>
              <button class="btn-mini danger" @click="deleteOne('batches', b.batch_name, b.batch_name)" :disabled="runtime.running">删除</button>
            </td>
          </tr>
          <tr v-if="batches.length === 0">
            <td colspan="7" class="empty-cell">暂无数据</td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="batches.length > 0"
        v-model:page="batchPage"
        v-model:page-size="batchPageSize"
        :total="batches.length"
        :page-size-options="[5, 8, 20, 50]"
      />
    </div>

    <!-- 收件箱邮件预览（支持去重与翻页） -->
    <div v-else-if="activeSubTab === 'inbox'" class="table-panel">
      <div class="inbox-toolbar">
        <div class="inbox-toolbar-left">
          <label class="ctrl-item checkbox-item">
            <input type="checkbox" v-model="inboxFilter.dedup" @change="loadInboxMails(1)" />
            <span>邮件级去重（Message-ID / 主题）</span>
          </label>
          <label class="ctrl-item checkbox-item">
            <input type="checkbox" v-model="inboxFilter.onlyNew" @change="loadInboxMails(1)" />
            <span>仅看含未处理附件邮件</span>
          </label>
          <span v-if="inboxLoaded" class="inbox-stats-hint">
            搜索 {{ inboxStats.rawTotal }} 封 · 去重合并 {{ inboxStats.dedupRemoved }} 封 · 当前筛选 {{ inboxStats.total }} 封
          </span>
        </div>
        <button class="btn-secondary" :disabled="inboxLoading" @click="loadInboxMails(1)">
          {{ inboxLoading ? '拉取中...' : '拉取收件箱' }}
        </button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>去重状态</th>
            <th>邮件主题</th>
            <th>发件人</th>
            <th>邮件时间</th>
            <th>匹配附件（指纹判重）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="mail in inboxMails" :key="`${mail.seq}-${mail.message_id}-${mail.subject}`">
            <td>
              <span :class="['inbox-pill', mail.status]">{{ inboxStatusLabel(mail.status) }}</span>
            </td>
            <td class="bold-cell">
              <div>
                <span>{{ mail.subject || '(无主题)' }}</span>
                <span v-if="mail.duplicate_count > 1" class="dup-tag">合并 {{ mail.duplicate_count }} 封</span>
              </div>
              <div v-if="mail.message_id" class="meta-sub">{{ mail.message_id }}</div>
            </td>
            <td>{{ mail.sender }}</td>
            <td>{{ mail.date }}</td>
            <td>
              <span
                v-for="att in mail.attachments"
                :key="`${att.filename}-${att.sha256}`"
                :class="['file-pill', att.already_processed ? 'processed' : 'fresh']"
                :title="att.sha256"
              >
                {{ att.filename }} ({{ (att.size_bytes / 1024).toFixed(1) }} KB · {{ att.already_processed ? '已处理' : '新' }})
              </span>
              <span v-if="!mail.attachments.length" class="meta-sub">无符合后缀的附件</span>
            </td>
          </tr>
          <tr v-if="!inboxLoaded && !inboxLoading">
            <td colspan="5" class="empty-cell">点击右上角“拉取收件箱”加载近期白名单邮件</td>
          </tr>
          <tr v-else-if="inboxLoaded && inboxMails.length === 0">
            <td colspan="5" class="empty-cell">当前时间窗与筛选条件下暂无邮件</td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="inboxStats.total > 0"
        :total="inboxStats.total"
        :page="inboxStats.page"
        :page-size="inboxStats.pageSize"
        :page-size-options="[5, 10, 20, 50]"
        :loading="inboxLoading"
        @change="p => loadInboxMails(p.page, p.pageSize)"
      />
    </div>

    <!-- 报告与回传包 -->
    <div v-else-if="activeSubTab === 'outbound'" class="split-panel">
      <div class="panel-box">
        <div class="panel-box-header"><h4>回传压缩包 ({{ outboundPackages.length }})</h4></div>
        <table class="data-table">
          <thead>
            <tr>
              <th>任务编号</th>
              <th>文件名</th>
              <th>文件数</th>
              <th>大小</th>
              <th>打包时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pkg in pagedOutboundPackages" :key="pkg.zip_name">
              <td class="mono-cell">{{ pkg.task_id }}</td>
              <td class="bold-cell">{{ pkg.zip_name }}</td>
              <td>{{ pkg.file_count }}</td>
              <td>{{ pkg.size_kb }} KB</td>
              <td>{{ pkg.pack_time }}</td>
              <td class="actions-cell">
                <button class="btn-mini primary" @click="openPkgSendModal(pkg)" :disabled="runtime.running">发信</button>
                <button class="btn-mini" @click="openLocalPath(pkg.zip_path)">定位</button>
                <button class="btn-mini danger" @click="deleteOne('outbound', pkg.task_id, pkg.zip_name)" :disabled="runtime.running">删除</button>
              </td>
            </tr>
            <tr v-if="outboundPackages.length === 0">
              <td colspan="6" class="empty-cell">暂无数据</td>
            </tr>
          </tbody>
        </table>
        <PaginationBar
          v-if="outboundPackages.length > 0"
          v-model:page="outboundPage"
          v-model:page-size="outboundPageSize"
          :total="outboundPackages.length"
          :page-size-options="[5, 10, 20, 50]"
        />
      </div>

      <div class="panel-box">
        <div class="panel-box-header"><h4>Word 报告 ({{ docxReports.length }})</h4></div>
        <table class="data-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>生成时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in pagedDocxReports" :key="doc.name">
              <td class="bold-cell">{{ doc.name }}</td>
              <td>{{ doc.size_kb }} KB</td>
              <td>{{ doc.mtime }}</td>
              <td class="actions-cell">
                <button class="btn-mini" @click="openLocalPath(doc.path)">定位</button>
                <button class="btn-mini danger" @click="deleteOne('docx', doc.name, doc.name)" :disabled="runtime.running">删除</button>
              </td>
            </tr>
            <tr v-if="docxReports.length === 0">
              <td colspan="4" class="empty-cell">暂无数据</td>
            </tr>
          </tbody>
        </table>
        <PaginationBar
          v-if="docxReports.length > 0"
          v-model:page="docxPage"
          v-model:page-size="docxPageSize"
          :total="docxReports.length"
          :page-size-options="[5, 10, 20, 50]"
        />
      </div>
    </div>

    <!-- 去重记录 -->
    <div v-else-if="activeSubTab === 'processed'" class="table-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th>SHA256</th>
            <th>批次</th>
            <th>发件人</th>
            <th>邮件主题</th>
            <th>首次处理</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in pagedProcessedItems" :key="item.sha256">
            <td class="bold-cell">{{ item.filename }}</td>
            <td class="mono-cell" :title="item.sha256">{{ item.sha256 ? item.sha256.slice(0, 16) + '...' : '-' }}</td>
            <td class="mono-cell">{{ item.batch }}</td>
            <td>{{ item.sender }}</td>
            <td>
              <div>{{ item.subject }}</div>
              <div v-if="item.message_id" class="meta-sub">{{ item.message_id }}</div>
            </td>
            <td>{{ item.first_seen }}</td>
            <td class="actions-cell">
              <button class="btn-mini danger" @click="deleteOne('index', item.sha256, `${item.filename} 的去重记录`)" :disabled="runtime.running">移除</button>
            </td>
          </tr>
          <tr v-if="processedItems.length === 0">
            <td colspan="7" class="empty-cell">暂无数据</td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="processedItems.length > 0"
        v-model:page="processedPage"
        v-model:page-size="processedPageSize"
        :total="processedItems.length"
        :page-size-options="[10, 20, 50, 100]"
      />
    </div>

    <!-- 日志 -->
    <div v-else-if="activeSubTab === 'logs'" class="log-panel">
      <div v-if="runtime.last_output" class="last-run-box">
        <div class="log-title">最近一次运行输出（退出码: {{ runtime.last_exit_code ?? '运行中' }}）</div>
        <pre>{{ runtime.last_output }}</pre>
      </div>
      <div class="log-title">pipeline.log（最近 {{ pipelineLogs.length }} 行）</div>
      <pre class="log-console">{{ pipelineLogs.join('\n') || '暂无日志' }}</pre>
    </div>

    <!-- 邮箱配置 -->
    <div v-if="showConfigModal" class="modal-backdrop" @click.self="showConfigModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>邮箱配置</h3>
          <button class="close-btn" @click="showConfigModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label><span>IMAP 服务器</span><input v-model="configForm.imap_server" type="text" /></label>
            <label><span>IMAP 端口</span><input v-model.number="configForm.imap_port" type="number" /></label>
            <label><span>收件账号</span><input v-model="configForm.account" type="text" /></label>
            <label>
              <span>收件邮箱 Key ({{ auth.imap_ready ? `当前: ${auth.imap_masked}` : '未配置' }})</span>
              <input v-model="authForm.imap" type="password" autocomplete="new-password" placeholder="输入新授权码，留空不修改" />
            </label>
            <label><span>SMTP 服务器</span><input v-model="configForm.smtp_server" type="text" /></label>
            <label><span>SMTP 端口</span><input v-model.number="configForm.smtp_port" type="number" /></label>
            <label><span>发件账号</span><input v-model="configForm.smtp_account" type="text" /></label>
            <label>
              <span>发件邮箱 Key ({{ auth.smtp_ready ? `当前: ${auth.smtp_masked}` : '复用收件 Key' }})</span>
              <input v-model="authForm.smtp" type="password" autocomplete="new-password" placeholder="同账号可留空，留空不修改" />
            </label>
            <label><span>发件人白名单（逗号分隔）</span><input v-model="configForm.sender_whitelist_str" type="text" /></label>
            <label><span>默认回传收件人</span><input v-model="configForm.reply_to" type="text" /></label>
            <label><span>发件显示名称</span><input v-model="configForm.smtp_display_name" type="text" /></label>
            <label><span>默认收件天数</span><input v-model.number="configForm.since_days" type="number" min="1" /></label>
            <label class="full-span">
              <span>附件下载目录（输入，修改后自动迁移）</span>
              <input v-model="configForm.download_dir" type="text" class="mono-input" />
            </label>
            <label class="full-span">
              <span>结果回传目录（输出，修改后自动迁移）</span>
              <input v-model="configForm.send_dir" type="text" class="mono-input" />
            </label>
          </div>
          <p class="form-note">邮箱 Key 独立保存在本机 .mail_auth 文件中，不写入配置文件；修改输入/输出目录后已有数据自动迁移至新目录。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showConfigModal = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="handleSaveConfig">{{ busy ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 授权码 -->
    <div v-if="showAuthModal" class="modal-backdrop" @click.self="showAuthModal = false">
      <div class="modal-card narrow">
        <div class="modal-header">
          <h3>邮箱授权码</h3>
          <button class="close-btn" @click="showAuthModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-block">
            <div class="auth-title">
              收件授权码（IMAP，{{ configForm.account || '-' }}）
              <span :class="['auth-state', auth.imap_ready ? 'ok' : 'warn']">{{ auth.imap_ready ? `当前: ${auth.imap_masked}` : '未配置' }}</span>
            </div>
            <input v-model="authForm.imap" type="password" autocomplete="new-password" placeholder="输入新授权码，留空不修改" />
            <div class="auth-file">保存位置: {{ auth.imap_file }}</div>
          </div>
          <div class="auth-block">
            <div class="auth-title">
              发件授权码（SMTP，{{ configForm.smtp_account || '-' }}）
              <span :class="['auth-state', auth.smtp_ready ? 'ok' : 'warn']">
                {{ auth.smtp_ready ? `当前: ${auth.smtp_masked}${auth.smtp_separate ? '' : '（复用收件授权码）'}` : '未配置' }}
              </span>
            </div>
            <input v-model="authForm.smtp" type="password" autocomplete="new-password" :disabled="authForm.clearSmtp" placeholder="发件账号与收件账号相同时可留空" />
            <label v-if="auth.smtp_separate" class="auth-clear">
              <input v-model="authForm.clearSmtp" type="checkbox" />
              <span>删除独立发件授权码</span>
            </label>
            <div class="auth-file">保存位置: {{ auth.smtp_file }}</div>
          </div>
          <p class="form-note">授权码只保存在本机密钥文件中，不写入 mail_config.json，不提交到 Git。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showAuthModal = false">取消</button>
          <button class="btn-primary" @click="handleSaveAuth">保存</button>
        </div>
      </div>
    </div>

    <!-- SMTP 测试发信 -->
    <div v-if="showTestSendModal" class="modal-backdrop" @click.self="showTestSendModal = false">
      <div class="modal-card narrow">
        <div class="modal-header">
          <h3>SMTP 发信链路自检</h3>
          <button class="close-btn" @click="showTestSendModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-block">
            <div class="auth-title">
              目标收件人（留空或点发给自己测试则发送至 {{ configForm.account || configForm.smtp_account || '本人邮箱' }}）
            </div>
            <input v-model="testSendForm.to" type="text" :placeholder="configForm.account || '例如 913223599@qq.com'" class="key-input-plain" />
          </div>
          <div class="auth-block">
            <div class="auth-title">自定义主题（可选，默认自动生成带时间戳的自检主题）</div>
            <input v-model="testSendForm.subject" type="text" placeholder="留空自动生成" class="key-input-plain" />
          </div>
          <div class="auth-block">
            <div class="auth-title">自检备注（可选）</div>
            <input v-model="testSendForm.note" type="text" placeholder="例如：自测 SMTP 中文与附件编码" class="key-input-plain" />
          </div>
          <label v-if="docxReports.length > 0" class="auth-clear test-check">
            <input v-model="testSendForm.attachLatestReport" type="checkbox" />
            <span>同时打包附带最新 Word 报告（{{ docxReports[0]?.name }}）</span>
          </label>
          <p class="form-note">注：自检发信不会发送至默认回传客户邮箱 ({{ configForm.reply_to || '-' }})，除非您在上方显式指定。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showTestSendModal = false">取消</button>
          <button class="btn-secondary" :disabled="testingSend" @click="confirmTestSend(true)">
            {{ testingSend ? '发送中...' : '发给自己测试' }}
          </button>
          <button class="btn-primary" :disabled="testingSend" @click="confirmTestSend(false)">
            {{ testingSend ? '发送中...' : '发送邮件' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 批次重跑注释与回传 -->
    <div v-if="showBatchRunModal" class="modal-backdrop" @click.self="showBatchRunModal = false">
      <div class="modal-card narrow">
        <div class="modal-header">
          <h3>批次重跑注释与回传</h3>
          <button class="close-btn" @click="showBatchRunModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-block">
            <div class="auth-title">目标批次：{{ batchRunForm.batchName }}</div>
            <div class="meta-sub">主题：{{ batchRunForm.subject }}</div>
            <div class="meta-sub">序列附件：{{ batchRunForm.attachmentsDesc }}</div>
          </div>
          <div class="auth-block">
            <div class="auth-title">重跑完成后的回传方式</div>
            <div class="radio-group">
              <label class="radio-item">
                <input type="radio" v-model="batchRunForm.sendMode" value="only_pack" />
                <span>仅注释与打包（不发送邮件）</span>
              </label>
              <label class="radio-item">
                <input type="radio" v-model="batchRunForm.sendMode" value="self" />
                <span>完成后发给自己测试（{{ configForm.account || configForm.smtp_account || '本人邮箱' }}）</span>
              </label>
              <label class="radio-item">
                <input type="radio" v-model="batchRunForm.sendMode" value="custom" />
                <span>完成后回传给指定收件人（留空则发往 {{ configForm.reply_to || '-' }}）</span>
              </label>
            </div>
            <input
              v-if="batchRunForm.sendMode === 'custom'"
              v-model="batchRunForm.customTo"
              type="text"
              :placeholder="configForm.reply_to || '留空使用默认回传地址'"
              class="key-input-plain"
            />
          </div>
          <div class="auth-block">
            <div class="auth-title">回传主题前缀与报告备注（可选）</div>
            <input v-model="batchRunForm.subjectPrefix" type="text" placeholder="【自动】" class="key-input-plain" />
            <input v-model="batchRunForm.extraNote" type="text" placeholder="追加写入 Word 报告备注" class="key-input-plain" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showBatchRunModal = false">取消</button>
          <button class="btn-secondary" :disabled="runtime.running" @click="confirmBatchRun('self')">
            重跑并发给自己
          </button>
          <button class="btn-primary" :disabled="runtime.running" @click="confirmBatchRun()">
            开始重跑
          </button>
        </div>
      </div>
    </div>

    <!-- 发送已打包注释结果压缩包 -->
    <div v-if="showPkgSendModal" class="modal-backdrop" @click.self="showPkgSendModal = false">
      <div class="modal-card narrow">
        <div class="modal-header">
          <h3>发送注释结果压缩包</h3>
          <button class="close-btn" @click="showPkgSendModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="auth-block">
            <div class="auth-title">目标结果包：{{ pkgSendForm.zipName }}</div>
            <div class="meta-sub">任务编号：{{ pkgSendForm.taskId }} | 文件数：{{ pkgSendForm.fileCount }} | 大小：{{ pkgSendForm.sizeKb }} KB</div>
          </div>
          <div class="auth-block">
            <div class="auth-title">
              目标收件人（留空或点发给自己测试则发送至 {{ configForm.account || configForm.smtp_account || '本人邮箱' }}）
            </div>
            <input v-model="pkgSendForm.to" type="text" :placeholder="configForm.account || '例如 913223599@qq.com'" class="key-input-plain" />
          </div>
          <div class="auth-block">
            <div class="auth-title">邮件主题（可选）</div>
            <input v-model="pkgSendForm.subject" type="text" :placeholder="`噬菌体注释结果回传 - ${pkgSendForm.taskId}`" class="key-input-plain" />
          </div>
          <div class="auth-block">
            <div class="auth-title">附加备注（可选）</div>
            <input v-model="pkgSendForm.extraNote" type="text" placeholder="可选写入邮件正文" class="key-input-plain" />
          </div>
          <p class="form-note">注：仅在点击“发送邮件”且填写地址时发送至对应收件人；点“发给自己测试”始终仅发送至本人邮箱，不会触碰默认客户地址。</p>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showPkgSendModal = false">取消</button>
          <button class="btn-secondary" :disabled="sendingPkg" @click="confirmPkgSend(true)">
            {{ sendingPkg ? '发送中...' : '发给自己测试' }}
          </button>
          <button class="btn-primary" :disabled="sendingPkg" @click="confirmPkgSend(false)">
            {{ sendingPkg ? '发送中...' : '发送邮件' }}
          </button>
        </div>
      </div>
    </div>

    <CleanupDialog
      :visible="showCleanup"
      title="清理历史数据"
      subtitle="按类型删除邮件流水线产生的历史文件。"
      :options="cleanupOptions"
      :show-days="true"
      :busy="busy"
      @close="showCleanup = false"
      @confirm="p => runCleanup(p.targets, p.older_than_days)"
    />
  </div>
</template>

<style scoped>
.mail-pipeline-module {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 28px;
}

.pipeline-steps-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 18px;
  gap: 10px;
  overflow-x: auto;
}

.step-node {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 170px;
}

.step-idx {
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid #bfdbfe;
  white-space: nowrap;
}

.step-info {
  display: flex;
  flex-direction: column;
}

.step-info strong {
  font-size: 13px;
  color: #1e293b;
}

.step-info span {
  font-size: 11px;
  color: #64748b;
}

.step-arrow {
  color: #94a3b8;
  font-weight: 700;
  font-size: 16px;
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.metric-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
}

.metric-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.metric-val {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

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
  gap: 12px;
  flex-wrap: wrap;
}

.ctrl-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #334155;
}

.num-input {
  width: 64px;
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.text-input {
  width: 200px;
  padding: 5px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.select-input {
  padding: 5px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  background: white;
  color: #1e293b;
}

.radio-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
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

.btn-outline:hover { background: #f1f5f9; }

.alert-banner {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}

.alert-banner.info {
  background: #eff6ff;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}

.alert-banner.error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.sub-tabs-bar {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 8px;
}

.sub-tab-btn {
  background: transparent;
  border: 1px solid transparent;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
}

.sub-tab-btn.active {
  background: #eff6ff;
  color: #2563eb;
  border-color: #bfdbfe;
}

.table-panel, .panel-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.split-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-box-header {
  padding: 10px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.panel-box-header h4 {
  margin: 0;
  font-size: 13px;
  color: #1e293b;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  text-align: left;
  padding: 10px 14px;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
}

.data-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}

.mono-cell {
  font-family: Consolas, monospace;
  color: #2563eb;
}

.bold-cell {
  font-weight: 600;
  color: #0f172a;
}

.file-pill {
  display: inline-block;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 2px 8px;
  border-radius: 4px;
  margin-right: 6px;
  font-size: 11px;
}

.actions-cell {
  display: flex;
  gap: 6px;
}

.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
}

.btn-mini.primary {
  background: #eff6ff;
  color: #2563eb;
  border-color: #93c5fd;
}

.empty-cell {
  text-align: center;
  color: #94a3b8;
  padding: 24px !important;
}

.log-panel {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  padding: 16px;
}

.log-title {
  font-size: 12px;
  font-weight: 600;
  color: #93c5fd;
  margin-bottom: 8px;
}

.log-console, .last-run-box pre {
  font-family: Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 360px;
  overflow-y: auto;
  margin: 0 0 12px;
  white-space: pre-wrap;
}

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
  width: 640px;
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

.modal-body { padding: 20px; }
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: #475569;
}

.form-grid input {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.paths-panel {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
}

.btn-outline.danger, .btn-mini.danger {
  color: #b91c1c;
  border-color: #fecaca;
}

.btn-outline.danger:hover:not(:disabled), .btn-mini.danger:hover:not(:disabled) {
  background: #fef2f2;
}

.btn-outline:disabled, .btn-mini:disabled, .btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.modal-card.narrow { width: 520px; }

.form-grid label.full-span {
  grid-column: 1 / -1;
}

.mono-input {
  font-family: Consolas, monospace;
}

.form-note {
  margin: 12px 0 0;
  font-size: 11px;
  color: #94a3b8;
}

.auth-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.auth-title {
  font-size: 12px;
  color: #334155;
  font-weight: 600;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.auth-state { font-weight: 500; font-family: Consolas, monospace; }
.auth-state.ok { color: #059669; }
.auth-state.warn { color: #d97706; }

.auth-block input[type="password"],
.key-input-plain {
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.auth-clear.test-check {
  color: #334155;
}

.auth-clear {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #b91c1c;
}

.auth-file {
  font-size: 11px;
  color: #94a3b8;
  font-family: Consolas, monospace;
  word-break: break-all;
}

.inbox-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.inbox-toolbar-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}

.inbox-stats-hint {
  font-size: 12px;
  color: #2563eb;
  font-weight: 500;
}

.inbox-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.inbox-pill.new { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
.inbox-pill.partial { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.inbox-pill.processed { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }
.inbox-pill.no_attachment { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }

.dup-tag {
  margin-left: 6px;
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
}

.meta-sub {
  margin-top: 2px;
  font-size: 11px;
  font-weight: 400;
  color: #94a3b8;
  font-family: Consolas, monospace;
  word-break: break-all;
}

.file-pill.fresh {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.file-pill.processed {
  background: #f1f5f9;
  color: #64748b;
}

.batch-status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.batch-status-pill.downloaded { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }
.batch-status-pill.running { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.batch-status-pill.completed { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
.batch-status-pill.failed { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.batch-status-pill.empty { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }
</style>