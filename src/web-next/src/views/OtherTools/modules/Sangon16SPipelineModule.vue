<script setup lang="ts">
/**
 * Sangon16SPipelineModule - 生工 16S 测序结果自动化 BLAST 与导出（薄视图外壳）
 * 核心状态机与异步流水线调度已拆离至 ./sangon_16s/useSangonPipeline.ts
 */
import { ref } from 'vue'
import { useI18n } from '../../../locales'
import PathField from '../components/PathField.vue'
import CleanupDialog from '../components/CleanupDialog.vue'
import PaginationBar from '../components/PaginationBar.vue'
import PopoverMenu from '../components/PopoverMenu.vue'
import SangonMailRecords from '../components/SangonMailRecords.vue'
import SangonIgnoreModal from '../components/SangonIgnoreModal.vue'
import SangonAccountModal from '../components/SangonAccountModal.vue'
import MailComposeModal from '../components/MailComposeModal.vue'
import { useSangonPipeline } from './sangon_16s/useSangonPipeline'

const { t } = useI18n()
const mailRecordsRef = ref<InstanceType<typeof SangonMailRecords> | null>(null)

const {
  openLocalPath, sangonRoot, downloadsDir, rootExists, db16sReady, orders, downloadCandidates,
  ignoredDownloadCount, ignoredOrdersMap, ignoreKeywords, showIgnoreModal, mailAccount, mailDisplayName,
  orderFilter, orderPage, orderPageSize, checkedOrderNames, selectedOrder, resultHeaders,
  resultRows, searchKeyword, resultPage, resultPageSize, forceReblast, scannedMails,
  hasScannedMails, scanningMail, mailFilter, mailSummary, busy, actionMessage, errorMessage,
  showCleanup, cleanupTargetOrders, showAuthModal, imapMasked, imapReady, imapFile, imapKeyInput,
  sangonAuth, browserEnv, repairingBrowser, showSangonAuthModal, sangonAuthHint, autoConfirmFee,
  autoBlastAfterDownload, showSendModal, loadingSendDraft, sendingMail, sendOrderTarget, sendDraft,
  runtime, showLogs, cleanupOptions, activeOrders, ignoredOrders, ignoredOrdersCount,
  claimableCandidates, orderFilterTabs, filteredOrders, pagedOrders, runnableOrdersCount,
  downloadableOrders, checkedDownloadableNames, targetDownloadCount, awaitingDownloadCount,
  needsWebLoginCount, browserEnvShortLabel, showBrowserWarningBar, browserFirstIssueText,
  runtimeLogsList, activeAdvancedTags, filteredResultRows, pagedResultRows, completedOrdersCount,
  totalIdentifiedSamples, allChecked, isProcessingStatus, isOrderMarkedNew, hasOrderSourceData,
  isOrderRunnable, hasOrderDownloadChannel, isOrderDownloadable, statusLabel, toggleCheckAll,
  loadOverview, selectOrderAndLoadResults, handleSaveRoot, handleSaveDownloadsDir,
  handleImportDownloads, handleClaimSingleOrder, handleClaimSingleCandidate, handleIgnoreOrders,
  handleToggleMailIgnore, handleSaveIgnoreKeywords, openSendResultModal, resetSangonSendDraft,
  confirmSendResultMail, handleCheckNewOrders, handleInitOrderFromMail, handleRunPipeline,
  openCleanupModal, confirmCleanup, openAuthEditor, saveImapAuth, openSangonAuthEditor,
  closeSangonAuthEditor, handleSaveSangonAuth, handleClearSangonPassword,
  handleToggleAutoConfirmFee, handleRepairBrowser, handleAutoDownloadOrders,
} = useSangonPipeline(mailRecordsRef)
</script>

<template>
  <div class="sangon-module">
    <!-- 流程步骤 -->
    <div class="steps-strip">
      <div class="step-pill"><span>1</span> {{ t('other.sangon.step1') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>2</span> {{ t('other.sangon.step2') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>3</span> {{ t('other.sangon.step3') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>4</span> {{ t('other.sangon.step4') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>5</span> {{ t('other.sangon.step5') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>6</span> {{ t('other.sangon.step6') }}</div>
      <div class="step-sep">&rarr;</div>
      <div class="step-pill"><span>7</span> {{ t('other.sangon.step7') }}</div>
    </div>

    <!-- 指标 -->
    <div class="metrics-row">
      <div class="metric-card">
        <div class="metric-label">{{ t('other.sangon.metric_root') }}</div>
        <div class="metric-val" :class="rootExists ? 'ok' : 'warn'">{{ rootExists ? t('other.sangon.ready') : t('other.sangon.missing_dir') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.sangon.metric_db16s') }}</div>
        <div class="metric-val" :class="db16sReady ? 'ok' : 'warn'">{{ db16sReady ? t('other.sangon.ready') : t('other.sangon.missing') }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.sangon.metric_orders') }}</div>
        <div class="metric-val">{{ completedOrdersCount }} / {{ activeOrders.length }}</div>
        <div v-if="ignoredOrders.length > 0" class="metric-sub">{{ t('other.sangon.ignored_orders', { count: ignoredOrders.length }) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.sangon.metric_samples') }}</div>
        <div class="metric-val">{{ totalIdentifiedSamples }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">{{ t('other.sangon.metric_status') }}</div>
        <div class="metric-val" :class="runtime.running ? 'running' : 'idle'">
          {{ runtime.running ? t('other.sangon.running_pct', { pct: runtime.progress }) : t('other.sangon.status_idle') }}
        </div>
        <div class="metric-sub" :title="runtime.last_message || ''">{{ runtime.last_message || '-' }}</div>
      </div>
    </div>

    <!-- 目录完整路径展示与修改迁移 -->
    <div class="paths-panel">
      <PathField
        :label="t('other.sangon.root_label')"
        :path="sangonRoot"
        :busy="busy || runtime.running"
        @save="handleSaveRoot"
        @open="openLocalPath"
      />
      <PathField
        :label="t('other.sangon.downloads_label')"
        :path="downloadsDir"
        :busy="busy || runtime.running"
        :save-label="t('other.sangon.save_dir')"
        :hint="t('other.sangon.downloads_hint')"
        @save="handleSaveDownloadsDir"
        @open="openLocalPath"
      />
      <div v-if="claimableCandidates.length > 0" class="pending-dl-bar">
        <div class="pending-dl-header">
          <div class="pending-dl-title">
            <strong>{{ t('other.sangon.unclaimed_title', { count: claimableCandidates.length }) }}</strong>
            <span class="pending-dl-desc">
              “认领”是指将从生工网页手动下载的 .zip 复制归档到对应订单「原始压缩包/」目录以便自动解压比对（保留下载原文件）；已处理或无需比对可点单包右侧「忽略」。
            </span>
          </div>
          <div class="pending-dl-actions">
            <button
              type="button"
              v-if="claimableCandidates.some(c => Boolean(c.matched_dir_name))"
              class="btn-mini primary"
              :disabled="busy || runtime.running"
              @click="handleImportDownloads(false)"
            >
              {{ t('other.sangon.claim_matched') }}
            </button>
            <button type="button" class="btn-mini" :disabled="busy || runtime.running" @click="handleImportDownloads(true)">
              {{ t('other.sangon.claim_all_new') }}
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
              type="button"
              class="chip-btn primary"
              :disabled="busy || runtime.running"
              @click="handleClaimSingleCandidate(cand)"
            >
              {{ cand.matched_dir_name ? t('other.sangon.archive_btn') : t('other.sangon.create_and_archive') }}
            </button>
            <button
              type="button"
              class="chip-btn"
              :disabled="busy || runtime.running"
              @click="handleIgnoreOrders([cand.order_no], true, '从待认领下载包忽略')"
            >
              {{ t('other.sangon.ignore_btn') }}
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
              <button class="menu-item" @click="close(); openSangonAuthEditor()">
                无头浏览器自检与修复 ({{ browserEnvShortLabel }})...
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

    <div v-if="showBrowserWarningBar" class="alert-banner warn browser-warn-bar">
      <div class="browser-warn-text">
        <strong>无头浏览器状态异常：</strong>{{ browserFirstIssueText }}
      </div>
      <div class="browser-warn-actions">
        <button
          class="btn-mini primary"
          :disabled="repairingBrowser || runtime.running"
          @click="handleRepairBrowser()"
        >
          {{ repairingBrowser ? '自修复中...' : '一键自修复浏览器' }}
        </button>
        <button class="btn-mini" @click="openSangonAuthEditor()">环境设置</button>
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
    <MailComposeModal
      :visible="showSendModal"
      title="发送 16S 鉴定结果邮件"
      :context-title="`目标订单：${sendOrderTarget?.dir_name || ''}（样本 ${sendOrderTarget?.total_samples || 0}，命中 ${sendOrderTarget?.with_hits || 0}，未命中 ${sendOrderTarget?.no_hits || 0}）`"
      :attach-summary="`压缩包内含：16S鉴定结果_${sendOrderTarget?.order_no || sendOrderTarget?.dir_name || ''}.csv 与 结果说明.txt（与上方正文内容同步）`"
      :draft="sendDraft"
      :loading-draft="loadingSendDraft"
      :sending="sendingMail"
      :self-address="mailAccount"
      :default-display-name="mailDisplayName"
      safety-note="提示：所有字段（发信标题、主题、正文、抄送、附件文件名）均可自由编辑；点「发给自己测试」仅发送至本人配置邮箱。"
      @close="showSendModal = false"
      @reset-draft="resetSangonSendDraft"
      @send="confirmSendResultMail"
    />

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
      :browser-env="browserEnv"
      :busy="busy"
      :repairing-browser="repairingBrowser"
      :hint-text="sangonAuthHint"
      @close="closeSangonAuthEditor"
      @save="handleSaveSangonAuth"
      @clear-password="handleClearSangonPassword"
      @repair-browser="handleRepairBrowser"
    />
  </div>
</template>

<style scoped src="./sangon_16s/sangon16s.css"></style>
