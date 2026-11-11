<script setup lang="ts">
/**
 * MailAutoPipelineModule - 邮件自动收件 -> 注释 -> Word 报告 -> SMTP 回传工作台
 * 职责：可视化监控与驱动噬菌体基因组邮件自动化注释、Word 交付报告构建与 SMTP 自动回传全流程
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { resolveApiUrl } from '../../../utils/fileDownloader'

interface AttachmentItem {
  filename: string
  size_bytes: number
  sha256?: string
  path: string
}

interface BatchItem {
  batch_name: string
  batch_path: string
  download_time: string
  sender: string
  subject: string
  mail_date: string
  attachments: AttachmentItem[]
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
  filename: string
  first_seen: string
  batch: string
  sender: string
  subject: string
  mail_date: string
}

const loading = ref(false)
const actionMessage = ref('')
const errorMessage = ref('')
const showConfigModal = ref(false)
const activeSubTab = ref<'batches' | 'outbound' | 'processed' | 'logs'>('batches')

const authReady = ref(false)
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
  account: '913223599@qq.com',
  sender_whitelist_str: 'yssw_service@163.com',
  since_days: 7,
  download_dir: 'results/email_downloads',
  smtp_server: 'smtp.qq.com',
  smtp_port: 465,
  smtp_account: '913223599@qq.com',
  smtp_display_name: '元昇生物注释服务',
  reply_to: 'yssw_service@163.com',
  send_dir: 'results/email_sends'
})

const runOptions = ref({
  since_days: 7,
  no_send: false,
  subject_prefix: '【自动】',
  extra_note: ''
})

const batches = ref<BatchItem[]>([])
const outboundPackages = ref<OutboundPackage[]>([])
const docxReports = ref<DocxReportItem[]>([])
const processedItems = ref<ProcessedItem[]>([])
const processedCount = ref(0)
const pipelineLogs = ref<string[]>([])

let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadOverview() {
  loading.value = true
  errorMessage.value = ''
  try {
    const resp = await fetch(resolveApiUrl('/api/other_tools/mail_pipeline/overview'))
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    authReady.value = Boolean(data.auth_ready)
    runtime.value = data.runtime || runtime.value
    batches.value = data.batches || []
    outboundPackages.value = data.outbound_packages || []
    docxReports.value = data.docx_reports || []
    processedItems.value = data.processed_items || []
    processedCount.value = data.processed_count || 0
    pipelineLogs.value = data.pipeline_logs || []

    if (data.config) {
      const c = data.config
      configForm.value = {
        imap_server: c.imap_server || 'imap.qq.com',
        imap_port: c.imap_port || 993,
        account: c.account || '',
        sender_whitelist_str: (c.sender_whitelist || []).join(', '),
        since_days: c.since_days ?? 7,
        download_dir: c.download_dir || 'results/email_downloads',
        smtp_server: c.smtp_server || 'smtp.qq.com',
        smtp_port: c.smtp_port || 465,
        smtp_account: c.smtp_account || '',
        smtp_display_name: c.smtp_display_name || '元昇生物注释服务',
        reply_to: c.reply_to || '',
        send_dir: c.send_dir || 'results/email_sends'
      }
      runOptions.value.since_days = c.since_days ?? 7
    }
  } catch (err: any) {
    errorMessage.value = `加载邮件流水线状态失败: ${err.message || err}`
  } finally {
    loading.value = false
  }
}

async function handleFetchOnly() {
  actionMessage.value = '正在连接 IMAP 扫描收件箱...'
  errorMessage.value = ''
  try {
    const resp = await fetch(resolveApiUrl('/api/other_tools/mail_pipeline/fetch'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ since_days: runOptions.value.since_days })
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '收件扫描失败')
    actionMessage.value = `收件扫描完成：共扫描 ${data.scanned} 封，命中 ${data.matched} 封，新保存 ${data.saved_count} 个附件（跨次去重跳过 ${data.skipped_processed} 个）`
    await loadOverview()
  } catch (err: any) {
    errorMessage.value = err.message || String(err)
    actionMessage.value = ''
  }
}

async function handleRunPipeline(annotateOnlyBatch?: string) {
  actionMessage.value = annotateOnlyBatch
    ? `正在启动单批次注释与报告流水线: ${annotateOnlyBatch}`
    : '正在启动端到端邮件自动注释回传流水线...'
  errorMessage.value = ''
  try {
    const payload: Record<string, any> = {
      since_days: runOptions.value.since_days,
      no_send: annotateOnlyBatch ? true : runOptions.value.no_send,
      subject_prefix: runOptions.value.subject_prefix,
      extra_note: runOptions.value.extra_note || null
    }
    if (annotateOnlyBatch) {
      payload.annotate_only_batch = annotateOnlyBatch
    }
    const resp = await fetch(resolveApiUrl('/api/other_tools/mail_pipeline/run'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '启动流水线失败')
    runtime.value = data.runtime
    actionMessage.value = '流水线已在后台启动，系统将自动刷新运行进度'
  } catch (err: any) {
    errorMessage.value = err.message || String(err)
    actionMessage.value = ''
  }
}

async function handleSaveConfig() {
  errorMessage.value = ''
  try {
    const whitelist = configForm.value.sender_whitelist_str
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
    const resp = await fetch(resolveApiUrl('/api/other_tools/mail_pipeline/config'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...configForm.value,
        sender_whitelist: whitelist
      })
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '保存配置失败')
    showConfigModal.value = false
    actionMessage.value = '邮件流水线配置已保存至 mail_config.json'
    await loadOverview()
  } catch (err: any) {
    errorMessage.value = err.message || String(err)
  }
}

async function openLocalPath(pathStr: string) {
  try {
    await fetch(resolveApiUrl('/api/other_tools/open_path'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: pathStr })
    })
  } catch (err) {
    console.error(err)
  }
}

onMounted(() => {
  loadOverview()
  pollTimer = setInterval(() => {
    if (runtime.value?.running) {
      loadOverview()
    }
  }, 4000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="mail-pipeline-module">
    <!-- 顶部五阶段流程架构条 -->
    <div class="pipeline-steps-banner">
      <div class="step-node">
        <span class="step-idx">STEP 1</span>
        <div class="step-info">
          <strong>IMAP 自动收件与指纹去重</strong>
          <span>{{ configForm.account }} | SHA256 跨次幂等</span>
        </div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">STEP 2</span>
        <div class="step-info">
          <strong>噬菌体多引擎级联注释</strong>
          <span>Pharokka / Prodigal / Phold / 安全审计</span>
        </div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">STEP 3</span>
        <div class="step-info">
          <strong>Word 交付报告构建</strong>
          <span>数据驱动排版 + 参考文献 [1]-[8] 注入</span>
        </div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">STEP 4</span>
        <div class="step-info">
          <strong>标准产物归档打包</strong>
          <span>GBK / TSV / FAA / DOCX 打包 + Manifest</span>
        </div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">STEP 5</span>
        <div class="step-info">
          <strong>SMTP 自动回传邮件</strong>
          <span>回传至 {{ configForm.reply_to }}</span>
        </div>
      </div>
    </div>

    <!-- 核心指标统计栏 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">邮箱授权凭证状态</div>
        <div class="metric-val" :class="authReady ? 'ok' : 'warn'">
          {{ authReady ? '已就绪 (.mail_auth)' : '未配置授权码' }}
        </div>
        <div class="metric-sub">白名单: {{ configForm.sender_whitelist_str }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已去重附件指纹库</div>
        <div class="metric-val">{{ processedCount }}</div>
        <div class="metric-sub">processed_index.json 累计记录</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已下载邮件批次</div>
        <div class="metric-val">{{ batches.length }}</div>
        <div class="metric-sub">{{ configForm.download_dir }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已生成 Word 报告 / 回传包</div>
        <div class="metric-val">{{ docxReports.length }} / {{ outboundPackages.length }}</div>
        <div class="metric-sub">{{ configForm.send_dir }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">流水线运行状态</div>
        <div class="metric-val" :class="runtime.running ? 'running' : 'idle'">
          {{ runtime.running ? '运行中 (Running)' : '空闲就绪 (Idle)' }}
        </div>
        <div class="metric-sub">{{ runtime.finished_at ? `上次完成: ${runtime.finished_at}` : '等待调度触发' }}</div>
      </div>
    </div>

    <!-- 控制与触发面板 -->
    <div class="control-bar">
      <div class="control-left">
        <label class="ctrl-item">
          <span>收件时间窗 (天):</span>
          <input type="number" v-model.number="runOptions.since_days" min="1" max="90" class="num-input" />
        </label>
        <label class="ctrl-item checkbox-item">
          <input type="checkbox" v-model="runOptions.no_send" />
          <span>仅注释+报告+打包 (跳过 SMTP 回传)</span>
        </label>
        <label class="ctrl-item">
          <span>报告附加备注:</span>
          <input type="text" v-model="runOptions.extra_note" placeholder="可选，写入 Word 报告备注栏" class="text-input" />
        </label>
      </div>
      <div class="control-right">
        <button class="btn-secondary" @click="handleFetchOnly" :disabled="runtime.running">
          仅扫描收件箱
        </button>
        <button class="btn-primary" @click="handleRunPipeline()" :disabled="runtime.running">
          {{ runtime.running ? '流水线执行中...' : '启动完整自动流水线' }}
        </button>
        <button class="btn-outline" @click="showConfigModal = true">
          邮箱与回传配置
        </button>
        <button class="btn-outline" @click="openLocalPath(configForm.send_dir)">
          打开产物目录
        </button>
        <button class="btn-outline" @click="loadOverview">
          刷新
        </button>
      </div>
    </div>

    <!-- 消息提示条 -->
    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <!-- 详情子标签切换 -->
    <div class="sub-tabs-bar">
      <button
        :class="['sub-tab-btn', { active: activeSubTab === 'batches' }]"
        @click="activeSubTab = 'batches'"
      >
        已下载邮件批次 ({{ batches.length }})
      </button>
      <button
        :class="['sub-tab-btn', { active: activeSubTab === 'outbound' }]"
        @click="activeSubTab = 'outbound'"
      >
        已生成报告与回传压缩包 ({{ outboundPackages.length }})
      </button>
      <button
        :class="['sub-tab-btn', { active: activeSubTab === 'processed' }]"
        @click="activeSubTab = 'processed'"
      >
        SHA256 幂等去重索引 ({{ processedCount }})
      </button>
      <button
        :class="['sub-tab-btn', { active: activeSubTab === 'logs' }]"
        @click="activeSubTab = 'logs'"
      >
        流水线执行日志 ({{ pipelineLogs.length }})
      </button>
    </div>

    <!-- 子面板 1：已下载邮件批次 -->
    <div v-if="activeSubTab === 'batches'" class="table-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>批次目录名</th>
            <th>原邮件主题</th>
            <th>发件人</th>
            <th>下载时间</th>
            <th>包含 FASTA 附件</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.batch_name">
            <td class="mono-cell">{{ b.batch_name }}</td>
            <td class="bold-cell">{{ b.subject }}</td>
            <td>{{ b.sender }}</td>
            <td>{{ b.download_time }}</td>
            <td>
              <span v-for="att in b.attachments" :key="att.filename" class="file-pill">
                {{ att.filename }} ({{ (att.size_bytes / 1024).toFixed(1) }} KB)
              </span>
            </td>
            <td class="actions-cell">
              <button class="btn-mini primary" @click="handleRunPipeline(b.batch_name)" :disabled="runtime.running">
                重跑注释与报告
              </button>
              <button class="btn-mini" @click="openLocalPath(b.batch_path)">
                打开文件夹
              </button>
            </td>
          </tr>
          <tr v-if="batches.length === 0">
            <td colspan="6" class="empty-cell">暂无已下载的邮件批次记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 子面板 2：已生成 Word 报告与回传包 -->
    <div v-else-if="activeSubTab === 'outbound'" class="split-panel">
      <div class="panel-box">
        <div class="panel-box-header">
          <h4>回传 ZIP 结果包 ({{ outboundPackages.length }})</h4>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>任务编号 (Task ID)</th>
              <th>ZIP 文件名</th>
              <th>内含文件数</th>
              <th>大小</th>
              <th>打包时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pkg in outboundPackages" :key="pkg.zip_name">
              <td class="mono-cell">{{ pkg.task_id }}</td>
              <td class="bold-cell">{{ pkg.zip_name }}</td>
              <td>{{ pkg.file_count }} 个产物</td>
              <td>{{ pkg.size_kb }} KB</td>
              <td>{{ pkg.pack_time }}</td>
              <td>
                <button class="btn-mini" @click="openLocalPath(pkg.zip_path)">定位文件</button>
              </td>
            </tr>
            <tr v-if="outboundPackages.length === 0">
              <td colspan="6" class="empty-cell">暂无已打包回传记录</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel-box">
        <div class="panel-box-header">
          <h4>Word 交付注释报告 ({{ docxReports.length }})</h4>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>报告文件名 (.docx)</th>
              <th>大小</th>
              <th>生成时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in docxReports" :key="doc.name">
              <td class="bold-cell">{{ doc.name }}</td>
              <td>{{ doc.size_kb }} KB</td>
              <td>{{ doc.mtime }}</td>
              <td>
                <button class="btn-mini" @click="openLocalPath(doc.path)">定位报告</button>
              </td>
            </tr>
            <tr v-if="docxReports.length === 0">
              <td colspan="4" class="empty-cell">暂无 Word 报告文件</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 子面板 3：SHA256 幂等去重索引 -->
    <div v-else-if="activeSubTab === 'processed'" class="table-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>附件文件名</th>
            <th>内容指纹 (SHA256 前16位)</th>
            <th>所属批次</th>
            <th>发件人</th>
            <th>原邮件主题</th>
            <th>首次处理时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in processedItems" :key="item.sha256">
            <td class="bold-cell">{{ item.filename }}</td>
            <td class="mono-cell" :title="item.sha256">{{ item.sha256 ? item.sha256.slice(0, 16) + '...' : '-' }}</td>
            <td class="mono-cell">{{ item.batch }}</td>
            <td>{{ item.sender }}</td>
            <td>{{ item.subject }}</td>
            <td>{{ item.first_seen }}</td>
          </tr>
          <tr v-if="processedItems.length === 0">
            <td colspan="6" class="empty-cell">暂无去重索引记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 子面板 4：流水线执行日志 -->
    <div v-else-if="activeSubTab === 'logs'" class="log-panel">
      <div v-if="runtime.last_output" class="last-run-box">
        <div class="log-title">最近一次触发输出 (Exit Code: {{ runtime.last_exit_code ?? 'running' }})</div>
        <pre>{{ runtime.last_output }}</pre>
      </div>
      <div class="log-title">pipeline.log 历史流水线日志 (最新 {{ pipelineLogs.length }} 行)</div>
      <pre class="log-console">{{ pipelineLogs.join('\n') || '暂无日志记录' }}</pre>
    </div>

    <!-- 邮箱配置弹窗 -->
    <div v-if="showConfigModal" class="modal-backdrop" @click.self="showConfigModal = false">
      <div class="modal-card">
        <div class="modal-header">
          <h3>邮件自动收发流水线配置 (mail_config.json)</h3>
          <button class="close-btn" @click="showConfigModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label>
              <span>IMAP 服务器</span>
              <input v-model="configForm.imap_server" type="text" />
            </label>
            <label>
              <span>IMAP 端口</span>
              <input v-model.number="configForm.imap_port" type="number" />
            </label>
            <label>
              <span>收件邮箱账号</span>
              <input v-model="configForm.account" type="text" />
            </label>
            <label>
              <span>发件人白名单 (逗号分隔)</span>
              <input v-model="configForm.sender_whitelist_str" type="text" />
            </label>
            <label>
              <span>SMTP 服务器</span>
              <input v-model="configForm.smtp_server" type="text" />
            </label>
            <label>
              <span>SMTP 端口</span>
              <input v-model.number="configForm.smtp_port" type="number" />
            </label>
            <label>
              <span>默认回传收件人 (reply_to)</span>
              <input v-model="configForm.reply_to" type="text" />
            </label>
            <label>
              <span>发件显示名称</span>
              <input v-model="configForm.smtp_display_name" type="text" />
            </label>
            <label>
              <span>附件下载目录</span>
              <input v-model="configForm.download_dir" type="text" />
            </label>
            <label>
              <span>结果打包与回传目录</span>
              <input v-model="configForm.send_dir" type="text" />
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-outline" @click="showConfigModal = false">取消</button>
          <button class="btn-primary" @click="handleSaveConfig">保存配置</button>
        </div>
      </div>
    </div>
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
</style>
