<script setup lang="ts">
/**
 * Sangon16SPipelineModule - 生工 16S 测序结果自动化 BLAST 与导出
 * 职责：邮件扫描建目录、根目录修改与自动迁移、解压与 16S BLAST 比对、CSV 导出预览、历史数据清理、邮箱 Key 编辑
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import PathField from '../components/PathField.vue'
import CleanupDialog from '../components/CleanupDialog.vue'
import PaginationBar from '../components/PaginationBar.vue'
import type { CleanupOption } from '../components/CleanupDialog.vue'
import { getJson, postJson, openLocalPath, describeMigration } from '../api'

interface SangonOrderItem {
  dir_name: string
  order_date: string
  order_no: string
  order_path: string
  status: 'completed' | 'blasted' | 'extracted' | 'downloaded' | 'pending'
  zip_count: number
  zip_files: Array<{ name: string; size_kb: number }>
  raw_file_count: number
  consensus_fasta_count: number
  ab1_count: number
  blast_task_id: string
  blast_report_count: number
  has_result_csv: boolean
  result_csv_path: string
  result_mtime: string
  total_samples: number
  with_hits: number
  no_hits: number
}

interface ScannedMailItem {
  seq: number
  message_id: string
  subject: string
  date: string
  order_no: string
  dir_name: string
  is_sequencing?: boolean
  cx_order_id: string
  download_url: string
  dir_ready: boolean
  dedup_status: 'created' | 'existing' | 'history_skipped' | 'new' | 'non_sequencing'
  duplicate_count: number
}

interface DownloadCandidateItem {
  order_no: string
  zip_name: string
  zip_path: string
  size_kb: number
  mtime_str: string
  matched_dir_name: string
  matched_status: string
  archived: boolean
}

const API = '/api/other_tools/sangon_16s'
const MAIL_API = '/api/other_tools/mail_pipeline'

const sangonRoot = ref('')
const downloadsDir = ref('')
const rootExists = ref(false)
const db16sReady = ref(false)
const orders = ref<SangonOrderItem[]>([])
const downloadCandidates = ref<DownloadCandidateItem[]>([])
const pendingDownloadCount = ref(0)
const mailAccount = ref('')
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
const showMailsPanel = ref(false)
const scanningMail = ref(false)
const mailFilter = ref({
  dedup: true,
  onlyNew: false,
  autoCreate: true,
  ignoreHistory: false
})
const mailScanStats = ref({
  page: 1,
  pageSize: 10,
  total: 0,
  totalPages: 1,
  rawTotal: 0,
  uniqueTotal: 0,
  dedupRemoved: 0,
  skippedKnown: 0
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

const showSendModal = ref(false)
const sendingMail = ref(false)
const sendForm = ref({
  orderDirName: '',
  to: '',
  subject: '',
  extraNote: ''
})

const runtime = ref<any>({
  running: false,
  current_order: null,
  current_stage: 'idle',
  progress: 0,
  started_at: null,
  finished_at: null,
  last_message: '',
  logs: []
})

const cleanupOptions: CleanupOption[] = [
  { key: 'raw_extracted', label: '解压数据 (原始数据/)', desc: '删除解压出的文件，保留原始压缩包', checked: true },
  { key: 'blast_cache', label: 'BLAST 中间缓存', desc: '删除 results/blast/<订单>_16s 报告缓存', checked: true },
  { key: 'result_csv', label: '鉴定结果 CSV', desc: '删除 BLAST结果/16S鉴定结果.csv' },
  { key: 'order_dir', label: '整个订单目录', desc: '删除该订单全部文件夹与压缩包（同时保留清理记忆防止扫描重建）', danger: true },
  { key: 'scan_index', label: '清除扫描去重记忆', desc: '清空选中订单的已扫描/已清理记录，之后可被扫描邮件再次识别' }
]

let pollTimer: ReturnType<typeof setInterval> | null = null

const pagedOrders = computed(() => {
  const start = (orderPage.value - 1) * orderPageSize.value
  return orders.value.slice(start, start + orderPageSize.value)
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

watch(() => orders.value.length, (len) => {
  const maxPage = Math.max(1, Math.ceil(len / orderPageSize.value))
  if (orderPage.value > maxPage) orderPage.value = maxPage
})

const completedOrdersCount = computed(() => orders.value.filter(o => o.status === 'completed').length)
const totalIdentifiedSamples = computed(() => orders.value.reduce((acc, o) => acc + (o.total_samples || 0), 0))
const allChecked = computed(() => orders.value.length > 0 && checkedOrderNames.value.length === orders.value.length)

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

function dedupStatusLabel(st: string): string {
  const map: Record<string, string> = {
    created: '新建目录',
    existing: '目录已存在',
    history_skipped: '已清理跳过',
    new: '待新建',
    non_sequencing: '非测序邮件'
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
  checkedOrderNames.value = checked ? orders.value.map(o => o.dir_name) : []
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
    pendingDownloadCount.value = data.pending_download_count || 0
    runtime.value = data.runtime || runtime.value

    if (!mailAccount.value) {
      try {
        const mailMeta = await getJson(`${MAIL_API}/overview`)
        mailAccount.value = mailMeta.config?.account || mailMeta.config?.smtp_account || ''
      } catch {
        // ignore
      }
    }

    checkedOrderNames.value = checkedOrderNames.value.filter(n => orders.value.some(o => o.dir_name === n))

    if (selectedOrder.value) {
      const updated = orders.value.find(o => o.dir_name === selectedOrder.value?.dir_name) || null
      selectedOrder.value = updated
    }
    if (!selectedOrder.value && orders.value.length > 0) {
      const firstCompleted = orders.value.find(o => o.has_result_csv) || orders.value[0]
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

async function handleImportDownloads(autoCreateOrder = false): Promise<void> {
  busy.value = true
  setInfo('正在从浏览器下载目录认领生工压缩包...')
  try {
    const data = await postJson(`${API}/import_downloads`, {
      sangon_root: sangonRoot.value || null,
      downloads_dir: downloadsDir.value || null,
      order_names: checkedOrderNames.value,
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

async function handleScanSangonMails(page = 1, pageSize = mailScanStats.value.pageSize): Promise<void> {
  scanningMail.value = true
  setInfo(`正在扫描生工通知邮件（第 ${page} 页）...`)
  try {
    const data = await postJson(`${API}/scan_mail`, {
      sangon_root: sangonRoot.value || null,
      page,
      page_size: pageSize,
      dedup: mailFilter.value.dedup,
      only_new: mailFilter.value.onlyNew,
      auto_create: mailFilter.value.autoCreate,
      ignore_history: mailFilter.value.ignoreHistory
    })
    scannedMails.value = data.mails || []
    mailScanStats.value = {
      page: data.page || 1,
      pageSize: data.page_size || pageSize,
      total: data.total || 0,
      totalPages: data.total_pages || 1,
      rawTotal: data.raw_total || 0,
      uniqueTotal: data.unique_total || 0,
      dedupRemoved: data.dedup_removed || 0,
      skippedKnown: data.skipped_known || 0
    }
    showMailsPanel.value = true
    const createdCnt = (data.created_dirs || []).length
    setInfo(
      `扫描完成：原始 ${mailScanStats.value.rawTotal} 封，去重合并 ${mailScanStats.value.dedupRemoved} 封，历史跳过 ${mailScanStats.value.skippedKnown} 条，本次新建目录 ${createdCnt} 个`
    )
    if (createdCnt > 0) await loadOverview()
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
    mail.dedup_status = 'existing'
    setInfo(`已创建订单目录: ${mail.dir_name}`)
    await loadOverview()
  } catch (err) {
    setError(err)
  } finally {
    busy.value = false
  }
}

async function handleRunPipeline(orderNames: string[] = []): Promise<void> {
  const targets = orderNames.length ? orderNames : checkedOrderNames.value
  setInfo(targets.length ? `启动订单处理: ${targets.join(', ')}` : '启动待处理订单...')
  try {
    const data = await postJson(`${API}/run_pipeline`, {
      sangon_root: sangonRoot.value,
      downloads_dir: downloadsDir.value || null,
      order_names: targets,
      evalue: '0.05',
      hitlist_size: '50',
      force_reblast: forceReblast.value
    })
    runtime.value = data.runtime
    setInfo('任务已在后台运行')
  } catch (err) {
    setError(err)
  }
}

function openCleanupModal(orderNames?: string[]): void {
  const targets = orderNames && orderNames.length
    ? orderNames
    : (checkedOrderNames.value.length
        ? checkedOrderNames.value
        : (orders.value.length ? orders.value.map(o => o.dir_name) : ['__ALL__']))
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

onMounted(() => {
  loadOverview()
  pollTimer = setInterval(() => {
    if (runtime.value?.running) loadOverview()
  }, 3500)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="sangon-module">
    <!-- 流程步骤 -->
    <div class="steps-strip">
      <div class="step-pill"><span>1</span> 扫描邮件</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>2</span> 浏览器下载</div>
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
        <div class="metric-label">已完成 / 总订单</div>
        <div class="metric-val">{{ completedOrdersCount }} / {{ orders.length }}</div>
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
        <div class="metric-sub">{{ runtime.last_message || '-' }}</div>
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
      <div v-if="pendingDownloadCount > 0" class="pending-dl-bar">
        <div class="pending-dl-info">
          <strong>发现 {{ pendingDownloadCount }} 个待认领测序压缩包：</strong>
          <span
            v-for="cand in downloadCandidates.filter(c => !c.archived)"
            :key="cand.zip_path"
            class="dl-chip"
            :title="cand.zip_path"
          >
            {{ cand.zip_name }} ({{ cand.matched_dir_name ? `匹配 ${cand.matched_dir_name}` : '未建目录' }})
          </span>
        </div>
        <div class="pending-dl-actions">
          <button class="btn-mini primary" :disabled="busy || runtime.running" @click="handleImportDownloads(false)">
            认领匹配订单
          </button>
          <button class="btn-mini" :disabled="busy || runtime.running" @click="handleImportDownloads(true)">
            新建并全部认领
          </button>
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

    <!-- 操作栏 -->
    <div class="control-bar">
      <div class="control-left">
        <label class="ctrl-item">
          <input type="checkbox" v-model="forceReblast" />
          <span>强制重新比对</span>
        </label>
        <label class="ctrl-item">
          <input type="checkbox" v-model="mailFilter.dedup" />
          <span>扫描去重</span>
        </label>
        <label class="ctrl-item">
          <input type="checkbox" v-model="mailFilter.autoCreate" />
          <span>自动建目录</span>
        </label>
        <label class="ctrl-item">
          <input type="checkbox" v-model="mailFilter.onlyNew" />
          <span>仅显示新邮件</span>
        </label>
        <span v-if="checkedOrderNames.length" class="sel-hint">已勾选 {{ checkedOrderNames.length }} 个订单</span>
      </div>
      <div class="control-right">
        <button class="btn-secondary" @click="handleScanSangonMails(1)" :disabled="scanningMail || runtime.running">
          {{ scanningMail ? '扫描中...' : '扫描邮件' }}
        </button>
        <button class="btn-outline" @click="handleImportDownloads(false)" :disabled="busy || runtime.running">
          认领下载包{{ pendingDownloadCount > 0 ? ` (${pendingDownloadCount})` : '' }}
        </button>
        <button class="btn-primary" @click="handleRunPipeline([])" :disabled="runtime.running">
          {{ runtime.running ? '运行中...' : (checkedOrderNames.length ? '运行所选订单' : '运行待处理订单') }}
        </button>
        <button class="btn-outline" @click="openAuthEditor">邮箱 Key</button>
        <button class="btn-outline danger" @click="openCleanupModal()" :disabled="runtime.running">
          {{ checkedOrderNames.length ? `清理所选 (${checkedOrderNames.length})` : '清理历史' }}
        </button>
        <button class="btn-outline" @click="loadOverview">刷新</button>
      </div>
    </div>

    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <!-- 邮件列表 -->
    <div v-if="showMailsPanel" class="mails-drawer">
      <div class="drawer-header">
        <div class="drawer-title-group">
          <h4>生工通知邮件 ({{ mailScanStats.total }} / 去重前 {{ mailScanStats.rawTotal }})</h4>
          <span v-if="mailScanStats.dedupRemoved > 0" class="dedup-badge">已合并重复 {{ mailScanStats.dedupRemoved }} 封</span>
          <span v-if="mailScanStats.skippedKnown > 0" class="dedup-badge warn">历史跳过 {{ mailScanStats.skippedKnown }} 条</span>
        </div>
        <div class="drawer-tools">
          <label class="ctrl-item">
            <input type="checkbox" v-model="mailFilter.dedup" @change="handleScanSangonMails(1)" />
            <span>去重</span>
          </label>
          <label class="ctrl-item">
            <input type="checkbox" v-model="mailFilter.onlyNew" @change="handleScanSangonMails(1)" />
            <span>仅新邮件</span>
          </label>
          <label class="ctrl-item">
            <input type="checkbox" v-model="mailFilter.ignoreHistory" @change="handleScanSangonMails(1)" />
            <span>忽略清理记忆</span>
          </label>
          <button class="btn-mini" @click="showMailsPanel = false">收起</button>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>订单目录</th>
            <th>订单号</th>
            <th>邮件主题</th>
            <th>时间</th>
            <th>去重/目录状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in scannedMails" :key="`${m.seq}-${m.order_no}-${m.subject}`">
            <td class="mono-cell">{{ m.dir_name || '-' }}</td>
            <td class="bold-cell">{{ m.order_no || '-' }}</td>
            <td>
              <span>{{ m.subject }}</span>
              <span v-if="m.duplicate_count > 1" class="dup-count-tag">合并 {{ m.duplicate_count }} 封</span>
            </td>
            <td>{{ m.date }}</td>
            <td>
              <span :class="['status-pill', m.dedup_status === 'non_sequencing' ? 'non_sequencing' : (m.dir_ready ? 'completed' : 'pending')]">
                {{ dedupStatusLabel(m.dedup_status) }}
              </span>
            </td>
            <td class="actions-cell">
              <button
                v-if="!m.dir_ready && m.dir_name && m.dedup_status !== 'non_sequencing'"
                class="btn-mini primary"
                :disabled="busy"
                @click="handleInitOrderFromMail(m)"
              >
                建目录
              </button>
              <a
                v-if="m.download_url"
                :href="m.download_url"
                target="_blank"
                rel="noopener noreferrer"
                class="link-btn"
              >
                打开下载页
              </a>
              <span v-else-if="m.dir_ready">-</span>
            </td>
          </tr>
          <tr v-if="scannedMails.length === 0">
            <td colspan="6" class="empty-cell">当前筛选条件下暂无匹配生工邮件</td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="mailScanStats.total > 0"
        :total="mailScanStats.total"
        :page="mailScanStats.page"
        :page-size="mailScanStats.pageSize"
        :page-size-options="[5, 10, 20, 50]"
        :loading="scanningMail"
        @change="p => handleScanSangonMails(p.page, p.pageSize)"
      />
    </div>

    <!-- 订单列表 -->
    <div class="panel-box">
      <div class="panel-box-header">
        <h4>订单列表 ({{ orders.length }})</h4>
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
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="ord in pagedOrders"
            :key="ord.dir_name"
            :class="{ 'selected-row': selectedOrder?.dir_name === ord.dir_name }"
            @click="selectOrderAndLoadResults(ord)"
          >
            <td @click.stop>
              <input type="checkbox" v-model="checkedOrderNames" :value="ord.dir_name" />
            </td>
            <td class="mono-cell bold-cell">{{ ord.dir_name }}</td>
            <td><span :class="['status-pill', ord.status]">{{ statusLabel(ord.status) }}</span></td>
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
              <button v-if="ord.has_result_csv" class="btn-mini primary" @click="selectOrderAndLoadResults(ord)">预览</button>
              <button v-if="ord.has_result_csv" class="btn-mini" @click="openSendResultModal(ord)">发信</button>
              <button class="btn-mini" @click="handleRunPipeline([ord.dir_name])" :disabled="runtime.running">运行</button>
              <button class="btn-mini" @click="openLocalPath(ord.order_path)">打开</button>
              <button class="btn-mini danger" @click="openCleanupModal([ord.dir_name])" :disabled="runtime.running">清理</button>
            </td>
          </tr>
          <tr v-if="orders.length === 0">
            <td colspan="9" class="empty-cell">暂无订单目录</td>
          </tr>
        </tbody>
      </table>
      <PaginationBar
        v-if="orders.length > 0"
        v-model:page="orderPage"
        v-model:page-size="orderPageSize"
        :total="orders.length"
        :page-size-options="[6, 10, 20, 50]"
      />
    </div>

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

.ctrl-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #334155;
}

.sel-hint { font-size: 12px; color: #2563eb; font-weight: 600; }

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
.btn-outline.danger, .btn-mini.danger {
  color: #b91c1c;
  border-color: #fecaca;
}
.btn-outline.danger:hover:not(:disabled), .btn-mini.danger:hover:not(:disabled) {
  background: #fef2f2;
}
.btn-outline:disabled, .btn-mini:disabled { opacity: 0.5; cursor: not-allowed; }

.alert-banner {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}
.alert-banner.info { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
.alert-banner.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.mails-drawer, .panel-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.drawer-header, .panel-box-header {
  padding: 10px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drawer-header h4, .panel-box-header h4 { margin: 0; font-size: 13px; color: #1e293b; }
.drawer-title-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.drawer-tools { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.dedup-badge {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.dedup-badge.warn {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}
.dup-count-tag {
  margin-left: 6px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
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
.mono-cell { font-family: Consolas, monospace; color: #2563eb; }
.bold-cell { font-weight: 600; }

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.status-pill.completed { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
.status-pill.blasted, .status-pill.extracted { background: #eff6ff; color: #2563eb; border: 1px solid #bfdbfe; }
.status-pill.downloaded, .status-pill.pending { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
.status-pill.non_sequencing { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }

.pending-dl-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  font-size: 12px;
}
.pending-dl-info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: #166534;
}
.dl-chip {
  background: white;
  border: 1px solid #86efac;
  border-radius: 5px;
  padding: 2px 8px;
  font-family: Consolas, monospace;
  font-size: 11px;
  color: #15803d;
}
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

.actions-cell { display: flex; gap: 6px; }
.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
}
.btn-mini.primary { background: #eff6ff; color: #2563eb; border-color: #93c5fd; }
.link-btn { color: #2563eb; text-decoration: none; font-weight: 500; }

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
