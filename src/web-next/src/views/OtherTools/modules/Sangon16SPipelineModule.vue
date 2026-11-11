<script setup lang="ts">
/**
 * Sangon16SPipelineModule - 生工 16S 测序结果自动化 BLAST 与导出流程工作台
 * 职责：连接 QQ 邮箱扫描 info1@sangon.com 新订单通知、管理订单三层目录、自动解压测序包、
 *      筛选 *.1.fasta 主序列比对 NCBI 16S 库、调用 BiologyTranslator 翻译并导出 11 列 CSV 及在线预览
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { resolveApiUrl } from '../../../utils/fileDownloader'

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
  subject: string
  date: string
  order_no: string
  dir_name: string
  cx_order_id: string
  download_url: string
  dir_ready: boolean
}

const sangonRoot = ref('G:\\测序数据\\生工16s')
const rootExists = ref(false)
const db16sReady = ref(false)
const orders = ref<SangonOrderItem[]>([])
const selectedOrder = ref<SangonOrderItem | null>(null)
const resultHeaders = ref<string[]>([])
const resultRows = ref<Array<Record<string, string>>>([])
const searchKeyword = ref('')
const forceReblast = ref(false)

const scannedMails = ref<ScannedMailItem[]>([])
const showMailsPanel = ref(false)
const scanningMail = ref(false)
const actionMessage = ref('')
const errorMessage = ref('')

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

let pollTimer: ReturnType<typeof setInterval> | null = null

const filteredResultRows = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return resultRows.value
  return resultRows.value.filter(row =>
    Object.values(row).some(v => String(v || '').toLowerCase().includes(kw))
  )
})

const completedOrdersCount = computed(() => orders.value.filter(o => o.status === 'completed').length)
const totalIdentifiedSamples = computed(() => orders.value.reduce((acc, o) => acc + (o.total_samples || 0), 0))

function statusLabel(st: string): string {
  const map: Record<string, string> = {
    completed: '已完成鉴定导出',
    blasted: '已 BLAST 待导出',
    extracted: '已解压待比对',
    downloaded: '已下载待解压',
    pending: '目录已建待下载'
  }
  return map[st] || st
}

async function loadOverview() {
  errorMessage.value = ''
  try {
    const url = resolveApiUrl(`/api/other_tools/sangon_16s/overview?sangon_root=${encodeURIComponent(sangonRoot.value)}`)
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    rootExists.value = Boolean(data.root_exists)
    db16sReady.value = Boolean(data.db_16s_ready)
    orders.value = data.orders || []
    runtime.value = data.runtime || runtime.value

    if (!selectedOrder.value && orders.value.length > 0) {
      const firstCompleted = orders.value.find(o => o.has_result_csv) || orders.value[0]
      if (firstCompleted) {
        await selectOrderAndLoadResults(firstCompleted)
      }
    }
  } catch (err: any) {
    errorMessage.value = `加载生工 16S 概览失败: ${err.message || err}`
  }
}

async function selectOrderAndLoadResults(order: SangonOrderItem) {
  selectedOrder.value = order
  if (!order.has_result_csv) {
    resultRows.value = []
    return
  }
  try {
    const url = resolveApiUrl(
      `/api/other_tools/sangon_16s/order/${encodeURIComponent(order.dir_name)}/results?sangon_root=${encodeURIComponent(sangonRoot.value)}`
    )
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    resultHeaders.value = data.headers || []
    resultRows.value = data.rows || []
  } catch (err: any) {
    errorMessage.value = `读取订单 ${order.dir_name} 鉴定结果失败: ${err.message || err}`
  }
}

async function handleScanSangonMails() {
  scanningMail.value = true
  actionMessage.value = '正在连接 QQ 邮箱扫描生工生物 (info1@sangon.com) 通知邮件...'
  errorMessage.value = ''
  try {
    const url = resolveApiUrl(`/api/other_tools/sangon_16s/scan_mail?sangon_root=${encodeURIComponent(sangonRoot.value)}`)
    const resp = await fetch(url, { method: 'POST' })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '扫描邮件失败')
    scannedMails.value = data.mails || []
    showMailsPanel.value = true
    const createdCnt = (data.created_dirs || []).length
    actionMessage.value = `邮件扫描完成：检出 ${scannedMails.value.length} 封生工通知邮件，新初始化 ${createdCnt} 个订单目录`
    await loadOverview()
  } catch (err: any) {
    errorMessage.value = err.message || String(err)
    actionMessage.value = ''
  } finally {
    scanningMail.value = false
  }
}

async function handleRunPipeline(orderNames: string[] = []) {
  actionMessage.value = orderNames.length
    ? `正在启动订单 ${orderNames.join(', ')} 的 16S BLAST 比对与中文翻译导出...`
    : '正在批量启动全部待处理生工 16S 订单的自动化比对与导出...'
  errorMessage.value = ''
  try {
    const resp = await fetch(resolveApiUrl('/api/other_tools/sangon_16s/run_pipeline'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sangon_root: sangonRoot.value,
        order_names: orderNames,
        evalue: '0.05',
        hitlist_size: '50',
        force_reblast: forceReblast.value
      })
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '启动流水线失败')
    runtime.value = data.runtime
    actionMessage.value = '生工 16S 自动化流水线已启动，正在后台执行'
  } catch (err: any) {
    errorMessage.value = err.message || String(err)
    actionMessage.value = ''
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
  }, 3500)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="sangon-module">
    <!-- 顶部七步标准流程条 -->
    <div class="steps-strip">
      <div class="step-pill"><span>1</span> 邮箱扫描 (info1@sangon.com)</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>2</span> 订单号与 cxOrderID 解析</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>3</span> 三层标准目录创建</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>4</span> 测序包解压至原始数据</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>5</span> *.1.fasta 主序列 16S BLAST</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>6</span> 物种拉丁文批量转中文</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>7</span> 11 列 GUI 标准 CSV 导出</div>
    </div>

    <!-- 指标概览卡片 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">生工 16S 订单数据根目录</div>
        <div class="metric-val" :class="rootExists ? 'ok' : 'warn'">
          {{ rootExists ? '目录已挂载' : '目录未就绪' }}
        </div>
        <div class="metric-sub">{{ sangonRoot }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">本地 NCBI 16S 数据库</div>
        <div class="metric-val" :class="db16sReady ? 'ok' : 'warn'">
          {{ db16sReady ? '16S_ribosomal_RNA 就绪' : '数据库缺失' }}
        </div>
        <div class="metric-sub">evalue=0.05 | hitlist_size=50</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已完成 / 总订单批次</div>
        <div class="metric-val">{{ completedOrdersCount }} / {{ orders.length }}</div>
        <div class="metric-sub">自动过滤 haplotype 变体</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">累计已鉴定 16S 样本数</div>
        <div class="metric-val">{{ totalIdentifiedSamples }}</div>
        <div class="metric-sub">11 列标准中文翻译 CSV</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">当前批处理引擎状态</div>
        <div class="metric-val" :class="runtime.running ? 'running' : 'idle'">
          {{ runtime.running ? `处理中 (${runtime.progress}%)` : '空闲就绪 (Idle)' }}
        </div>
        <div class="metric-sub">{{ runtime.last_message || '等待触发任务' }}</div>
      </div>
    </div>

    <!-- 控制操作栏 -->
    <div class="control-bar">
      <div class="control-left">
        <label class="ctrl-item">
          <span>生工数据根目录:</span>
          <input type="text" v-model="sangonRoot" class="root-input" />
        </label>
        <label class="ctrl-item">
          <input type="checkbox" v-model="forceReblast" />
          <span>强制重新运行 BLAST 比对</span>
        </label>
      </div>
      <div class="control-right">
        <button class="btn-secondary" @click="handleScanSangonMails" :disabled="scanningMail || runtime.running">
          {{ scanningMail ? '扫描邮件中...' : '扫描生工通知邮件并建目录' }}
        </button>
        <button class="btn-primary" @click="handleRunPipeline([])" :disabled="runtime.running">
          {{ runtime.running ? '批处理执行中...' : '一键运行待处理订单 BLAST 与导出' }}
        </button>
        <button class="btn-outline" @click="openLocalPath(sangonRoot)">
          打开生工根目录
        </button>
        <button class="btn-outline" @click="loadOverview">
          刷新列表
        </button>
      </div>
    </div>

    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <!-- 扫描到的生工邮件折叠面板 -->
    <div v-if="showMailsPanel && scannedMails.length > 0" class="mails-drawer">
      <div class="drawer-header">
        <h4>最近生工生物 (info1@sangon.com) 测序通知邮件 ({{ scannedMails.length }})</h4>
        <button class="btn-mini" @click="showMailsPanel = false">收起</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>订单目录名</th>
            <th>10位订单号</th>
            <th>邮件主题</th>
            <th>邮件时间</th>
            <th>本地目录状态</th>
            <th>生工订单页链接</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in scannedMails" :key="m.subject + m.date">
            <td class="mono-cell">{{ m.dir_name || '-' }}</td>
            <td class="bold-cell">{{ m.order_no || '-' }}</td>
            <td>{{ m.subject }}</td>
            <td>{{ m.date }}</td>
            <td>
              <span :class="['status-pill', m.dir_ready ? 'completed' : 'pending']">
                {{ m.dir_ready ? '三层目录已就绪' : '未创建' }}
              </span>
            </td>
            <td>
              <a v-if="m.download_url" :href="m.download_url" target="_blank" class="link-btn">
                打开生工下载页 (cxOrderID={{ m.cx_order_id }})
              </a>
              <span v-else>-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 订单列表表格 -->
    <div class="panel-box">
      <div class="panel-box-header">
        <h4>生工 16S 订单批次列表 ({{ orders.length }})</h4>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>订单目录 (YYYYMMDD_订单号)</th>
            <th>状态</th>
            <th>原始压缩包</th>
            <th>主序列 (*.1.fasta) / AB1</th>
            <th>BLAST 报告数</th>
            <th>鉴定统计 (总计 / 命中 / 未命中)</th>
            <th>结果更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="ord in orders"
            :key="ord.dir_name"
            :class="{ 'selected-row': selectedOrder?.dir_name === ord.dir_name }"
            @click="selectOrderAndLoadResults(ord)"
          >
            <td class="mono-cell bold-cell">{{ ord.dir_name }}</td>
            <td>
              <span :class="['status-pill', ord.status]">{{ statusLabel(ord.status) }}</span>
            </td>
            <td>{{ ord.zip_count }} 个 ZIP</td>
            <td>{{ ord.consensus_fasta_count }} 条主序列 / {{ ord.ab1_count }} 峰图</td>
            <td>{{ ord.blast_report_count }} 份</td>
            <td>
              <template v-if="ord.has_result_csv">
                <strong>{{ ord.total_samples }}</strong> 样本
                (<span class="hit-ok">{{ ord.with_hits }} 命中</span> /
                <span class="hit-none">{{ ord.no_hits }} 未命中</span>)
              </template>
              <span v-else class="muted">-</span>
            </td>
            <td>{{ ord.result_mtime || '-' }}</td>
            <td class="actions-cell" @click.stop>
              <button
                v-if="ord.has_result_csv"
                class="btn-mini primary"
                @click="selectOrderAndLoadResults(ord)"
              >
                预览鉴定表
              </button>
              <button
                class="btn-mini"
                @click="handleRunPipeline([ord.dir_name])"
                :disabled="runtime.running"
              >
                {{ ord.has_result_csv ? '重新导出/比对' : '执行比对导出' }}
              </button>
              <button class="btn-mini" @click="openLocalPath(ord.result_csv_path || ord.order_path)">
                打开目录
              </button>
            </td>
          </tr>
          <tr v-if="orders.length === 0">
            <td colspan="8" class="empty-cell">当前目录下未检测到生工 16S 订单文件夹</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 选中订单的 11 列 16S鉴定结果.csv 在线预览面板 -->
    <div v-if="selectedOrder" class="panel-box result-preview-box">
      <div class="panel-box-header preview-header">
        <div>
          <h4>
            订单 [{{ selectedOrder.dir_name }}] 16S 鉴定结果在线预览
            <span class="sub-count">（共 {{ filteredResultRows.length }} / {{ resultRows.length }} 条记录）</span>
          </h4>
        </div>
        <div class="preview-tools">
          <input
            v-model="searchKeyword"
            type="text"
            placeholder="搜索菌株编号、中文物种名、拉丁学名或访问号..."
            class="search-input"
          />
          <button
            v-if="selectedOrder.result_csv_path"
            class="btn-outline"
            @click="openLocalPath(selectedOrder.result_csv_path)"
          >
            在资源管理器中定位 CSV
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
            <tr v-for="(row, rIdx) in filteredResultRows" :key="rIdx">
              <td v-for="h in resultHeaders" :key="h" :class="{ 'highlight-species': h === '鉴定物种(中文翻译)' }">
                {{ row[h] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-cell">
        该订单尚未生成 16S鉴定结果.csv，请点击上方“执行比对导出”按钮运行自动化流程。
      </div>
    </div>
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

.step-sep {
  color: #94a3b8;
  font-size: 14px;
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
  font-size: 17px;
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

.root-input {
  width: 240px;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  font-family: Consolas, monospace;
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

.drawer-header h4, .panel-box-header h4 {
  margin: 0;
  font-size: 13px;
  color: #1e293b;
}

.sub-count {
  font-weight: 400;
  color: #64748b;
  font-size: 12px;
}

.preview-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  width: 280px;
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

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

.selected-row {
  background: #f0f7ff;
}

.mono-cell {
  font-family: Consolas, monospace;
  color: #2563eb;
}

.bold-cell {
  font-weight: 600;
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.status-pill.completed {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.status-pill.blasted, .status-pill.extracted {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}

.status-pill.downloaded, .status-pill.pending {
  background: #fffbeb;
  color: #d97706;
  border: 1px solid #fde68a;
}

.hit-ok { color: #059669; font-weight: 600; }
.hit-none { color: #94a3b8; }

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

.link-btn {
  color: #2563eb;
  text-decoration: none;
  font-weight: 500;
}

.csv-table-scroll {
  max-height: 460px;
  overflow: auto;
}

.csv-table td {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.highlight-species {
  color: #059669 !important;
  font-weight: 700;
}

.empty-cell {
  text-align: center;
  color: #94a3b8;
  padding: 24px !important;
}
</style>
