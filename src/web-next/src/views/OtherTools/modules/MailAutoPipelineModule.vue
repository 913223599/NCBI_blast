<script setup lang="ts">
/**
 * MailAutoPipelineModule - 邮件收件 -> 注释 -> Word 报告 -> SMTP 回传（薄视图外壳）
 * 核心状态与接口调度已抽离至 ./mail_pipeline/useMailPipeline.ts
 */
import { useI18n } from '../../../locales'
import PathField from '../components/PathField.vue'
import CleanupDialog from '../components/CleanupDialog.vue'
import PaginationBar from '../components/PaginationBar.vue'
import MailComposeModal from '../components/MailComposeModal.vue'
import { useMailPipeline } from './mail_pipeline/useMailPipeline'

const { t } = useI18n()

const {
  openLocalPath, actionMessage, errorMessage, busy, showConfigModal, showAuthModal, showCleanup,
  showTestSendModal, loadingTestSendDraft, testingSend, testSendAttachReport, testSendAttachedFiles,
  testSendDraft, showBatchRunModal, batchRunForm, showPkgSendModal, loadingPkgDraft, sendingPkg,
  pkgSendTarget, pkgSendDraft, activeSubTab, inboxMails, inboxLoaded, inboxLoading, inboxFilter,
  inboxStats, batchPage, batchPageSize, outboundPage, outboundPageSize, docxPage, docxPageSize,
  processedPage, processedPageSize, auth, authForm, runtime, configForm, resolvedDownloadDir,
  resolvedSendDir, runOptions, batches, pendingBatchesCount, ignoredBatchesCount, outboundPackages,
  docxReports, processedItems, processedCount, pipelineLogs, cleanupOptions, pagedBatches,
  pagedOutboundPackages, pagedDocxReports, pagedProcessedItems, inboxStatusLabel, stageLabel,
  loadOverview, handleFetchOnly, loadInboxMails, showAllInboxMails, openInboxTab, handleRunPipeline,
  openBatchRunModal, confirmBatchRun, handleSaveConfig, handleSaveDir, openAuthModal,
  handleSaveAuth, runCleanup, deleteOne, handleToggleBatchIgnore, loadTestSendDraft,
  openTestSendModal, handleToggleTestAttachReport, confirmTestSend, openPkgSendModal,
  resetPkgSendDraft, confirmPkgSend,
} = useMailPipeline()
</script>

<template>
  <div class="mail-pipeline-module">
    <!-- 流程 -->
    <div class="pipeline-steps-banner">
      <div class="step-node">
        <span class="step-idx">1</span>
        <div class="step-info"><strong>{{ t('other.mail.step1_title') }}</strong><span>{{ t('other.mail.step1_desc') }}</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">2</span>
        <div class="step-info"><strong>{{ t('other.mail.step2_title') }}</strong><span>Pharokka / Phold</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">3</span>
        <div class="step-info"><strong>{{ t('other.mail.step3_title') }}</strong><span>{{ t('other.mail.step3_desc') }}</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">4</span>
        <div class="step-info"><strong>{{ t('other.mail.step4_title') }}</strong><span>{{ t('other.mail.step4_desc') }}</span></div>
      </div>
      <div class="step-arrow">&rarr;</div>
      <div class="step-node">
        <span class="step-idx">5</span>
        <div class="step-info"><strong>{{ t('other.mail.step5_title') }}</strong><span>{{ t('other.mail.step5_desc', { target: configForm.reply_to || '-' }) }}</span></div>
      </div>
    </div>

    <!-- 指标 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">{{ t('other.mail.metric_auth') }}</div>
        <div class="metric-val" :class="auth.imap_ready ? 'ok' : 'warn'">{{ auth.imap_ready ? t('other.mail.configured') : t('other.mail.unconfigured') }}</div>
        <div class="metric-sub">{{ configForm.account || '-' }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.mail.metric_dedup') }}</div>
        <div class="metric-val">{{ processedCount }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.mail.metric_batches') }}</div>
        <div class="metric-val">{{ batches.length }}</div>
        <div class="metric-sub">
          <template v-if="pendingBatchesCount > 0">{{ t('other.mail.pending_batches', { count: pendingBatchesCount }) }}</template>
          <template v-else>{{ t('other.mail.no_pending') }}</template>
          <template v-if="ignoredBatchesCount > 0"> · {{ t('other.mail.ignored_suffix', { count: ignoredBatchesCount }) }}</template>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.mail.metric_outputs') }}</div>
        <div class="metric-val">{{ docxReports.length }} / {{ outboundPackages.length }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.mail.metric_status') }}</div>
        <div
          class="metric-val"
          :class="runtime.running ? 'running' : (runtime.current_stage === 'failed' ? 'warn' : 'idle')"
        >
          {{ runtime.running ? t('other.mail.status_running') : (runtime.current_stage === 'failed' ? t('other.mail.status_failed') : t('other.mail.status_idle')) }}
        </div>
        <div class="metric-sub">
          {{ runtime.running ? stageLabel(runtime.current_stage) : (runtime.finished_at ? t('other.mail.last_finished', { time: runtime.finished_at }) : '-') }}
        </div>
      </div>
    </div>

    <!-- 目录 -->
    <div class="paths-panel">
      <PathField
        :label="t('other.mail.dir_download')"
        :path="resolvedDownloadDir"
        :busy="busy || runtime.running"
        @save="v => handleSaveDir('download_dir', v)"
        @open="openLocalPath"
      />
      <PathField
        :label="t('other.mail.dir_send')"
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
          <span>{{ t('other.mail.since_days') }}</span>
          <input type="number" v-model.number="runOptions.since_days" min="1" max="90" class="num-input" />
        </label>
        <label class="ctrl-item">
          <span>{{ t('other.mail.send_mode') }}</span>
          <select v-model="runOptions.send_mode" class="select-input">
            <option value="config">{{ t('other.mail.send_config', { target: configForm.reply_to || '-' }) }}</option>
            <option value="self">{{ t('other.mail.send_self', { target: configForm.account || configForm.smtp_account || '-' }) }}</option>
            <option value="none">{{ t('other.mail.send_none') }}</option>
          </select>
        </label>
        <label class="ctrl-item">
          <span>{{ t('other.mail.report_note') }}</span>
          <input type="text" v-model="runOptions.extra_note" :placeholder="t('other.mail.optional_placeholder')" class="text-input" />
        </label>
      </div>
      <div class="control-right">
        <button type="button" class="btn-secondary" @click="handleFetchOnly" :disabled="runtime.running">{{ t('other.mail.btn_fetch_only') }}</button>
        <button type="button" class="btn-primary" @click="handleRunPipeline()" :disabled="runtime.running">
          {{ runtime.running ? t('other.mail.btn_running') : t('other.mail.btn_run') }}
        </button>
        <button type="button" class="btn-outline" @click="openTestSendModal" :disabled="runtime.running">{{ t('other.mail.btn_test_send') }}</button>
        <button type="button" class="btn-outline" @click="showConfigModal = true">{{ t('other.mail.btn_config') }}</button>
        <button type="button" class="btn-outline" @click="openAuthModal">{{ t('other.mail.btn_auth') }}</button>
        <button type="button" class="btn-outline danger" @click="showCleanup = true" :disabled="runtime.running">{{ t('other.mail.btn_cleanup') }}</button>
        <button type="button" class="btn-outline" @click="loadOverview">{{ t('other.mail.btn_refresh') }}</button>
      </div>
    </div>

    <div v-if="actionMessage" class="alert-banner info">{{ actionMessage }}</div>
    <div v-if="errorMessage" class="alert-banner error">{{ errorMessage }}</div>

    <div class="sub-tabs-bar">
      <button :class="['sub-tab-btn', { active: activeSubTab === 'batches' }]" @click="activeSubTab = 'batches'">
        收件批次 ({{ batches.length }}<template v-if="pendingBatchesCount > 0"> · 待处理 {{ pendingBatchesCount }}</template><template v-if="ignoredBatchesCount > 0"> · 已跳过 {{ ignoredBatchesCount }}</template>)
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
          <tr
            v-for="b in pagedBatches"
            :key="b.batch_name"
            :class="{ 'ignored-row': b.ignored || b.pipeline_status === 'ignored' }"
          >
            <td class="mono-cell">{{ b.batch_name }}</td>
            <td>
              <span
                :class="['batch-status-pill', b.pipeline_status || 'downloaded']"
                :title="(b.ignored || b.pipeline_status === 'ignored') ? (b.ignore_reason ? `跳过原因: ${b.ignore_reason}${b.ignored_at ? ' (' + b.ignored_at + ')' : ''}` : '已设为忽略跳过，运行流水线将自动略过') : (b.last_error || (b.task_ids && b.task_ids.length ? b.task_ids.join(', ') : ''))"
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
              <button
                class="btn-mini primary"
                @click="openBatchRunModal(b)"
                :disabled="runtime.running || b.pipeline_status === 'running' || Boolean(b.ignored || b.pipeline_status === 'ignored')"
              >
                重跑
              </button>
              <button
                class="btn-mini"
                @click="handleToggleBatchIgnore(b)"
                :disabled="busy || runtime.running || b.pipeline_status === 'running'"
              >
                {{ (b.ignored || b.pipeline_status === 'ignored') ? '恢复' : '跳过' }}
              </button>
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
          <label class="ctrl-item checkbox-item" title="按 Message-ID 和发送时间合并同一封邮件的重复投递">
            <input type="checkbox" v-model="inboxFilter.dedup" @change="loadInboxMails(1)" />
            <span>邮件级去重（Message-ID / 主题）</span>
          </label>
          <label class="ctrl-item checkbox-item" title="对比 processed_index.json 中的 Message-ID 与附件 SHA256，仅显示含新附件邮件">
            <input type="checkbox" v-model="inboxFilter.onlyNew" @change="loadInboxMails(1)" />
            <span>仅看含未处理附件邮件</span>
          </label>
          <span v-if="inboxLoaded" class="inbox-stats-hint">
            搜索 {{ inboxStats.rawTotal }} 封 · 去重合并 {{ inboxStats.dedupRemoved }} 封 · 当前筛选 {{ inboxStats.total }} 封
            <template v-if="inboxStats.processedSkipped > 0"> · 已隐藏已处理/无新附件 {{ inboxStats.processedSkipped }} 封</template>
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
            <td colspan="5" class="empty-cell">
              <template v-if="inboxFilter.onlyNew">
                <span>
                  当前时间窗内暂无含未处理附件的新邮件（已过滤 {{ inboxStats.processedSkipped }} 封已处理或无匹配附件邮件）
                </span>
                <button class="btn-mini primary inline-action-btn" @click="showAllInboxMails">显示全部邮件</button>
              </template>
              <span v-else>当前时间窗与筛选条件下暂无邮件</span>
            </td>
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
    <MailComposeModal
      :visible="showTestSendModal"
      title="SMTP 发信链路自检"
      :context-title="`测试账号：${configForm.smtp_account || configForm.account || '未配置'} -> 安全测试发信`"
      :attach-summary="`压缩包内含：${testSendAttachedFiles.join('、')}`"
      :draft="testSendDraft"
      :loading-draft="loadingTestSendDraft"
      :sending="testingSend"
      :self-address="configForm.account || configForm.smtp_account || ''"
      :default-display-name="configForm.smtp_display_name || '元昇生物注释服务'"
      :show-attach-latest-report="docxReports.length > 0"
      :latest-report-name="docxReports[0]?.name || ''"
      :attach-latest-report="testSendAttachReport"
      :safety-note="`注：所有字段均可直接修改；点「发给自己测试」绝不触碰默认回传地址 (${configForm.reply_to || '-'})。`"
      @close="showTestSendModal = false"
      @toggle-attach-report="handleToggleTestAttachReport"
      @reset-draft="p => loadTestSendDraft(p.attachLatestReport)"
      @send="confirmTestSend"
    />

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
    <MailComposeModal
      :visible="showPkgSendModal"
      title="发送注释结果压缩包"
      :context-title="`目标结果包：${pkgSendTarget?.zip_name || ''}`"
      :attach-summary="`任务编号：${pkgSendTarget?.task_id || '-'} | 文件数：${pkgSendTarget?.file_count || 0} | 大小：${pkgSendTarget?.size_kb || 0} KB`"
      :draft="pkgSendDraft"
      :loading-draft="loadingPkgDraft"
      :sending="sendingPkg"
      :self-address="configForm.account || configForm.smtp_account || ''"
      :default-display-name="configForm.smtp_display_name || '元昇生物注释服务'"
      safety-note="注：支持修改发信标题、主题、正文、抄送与附件显示文件名；点「发给自己测试」始终仅发送至本人邮箱，不会触碰外部收件人。"
      @close="showPkgSendModal = false"
      @reset-draft="resetPkgSendDraft"
      @send="confirmPkgSend"
    />

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

<style scoped src="./mail_pipeline/mailPipeline.css"></style>
