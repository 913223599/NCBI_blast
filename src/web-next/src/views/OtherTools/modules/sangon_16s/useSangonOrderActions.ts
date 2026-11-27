/**
 * useSangonOrderActions.ts - 生工 16S 目录迁移、下载认领、队列执行、清理与认证操作
 */
import type { ComputedRef, Ref } from 'vue'
import type {
  BrowserEnvStatus,
  DownloadCandidateItem,
  OrderFilterKey,
  SangonAuthMeta,
  SangonOrderItem,
  SangonRuntimeState,
} from '../../sangonTypes'
import { describeMigration, getJson, postJson, type MigrationInfo } from '../../api'
import { extractErrorMessage, isOrderDownloadableImpl } from './useSangonPipelineShared'

const API = '/api/other_tools/sangon_16s'
const MAIL_API = '/api/other_tools/mail_pipeline'
const BROWSER_ENV_API = '/api/other_tools/browser_env'

interface SettingsResponse {
  settings?: {
    sangon_root?: string
    downloads_dir?: string
  }
  migration?: MigrationInfo
  sangon_auth?: SangonAuthMeta
}

interface ImportDownloadsResponse {
  created_dirs?: string[]
  scanned_zips?: number
  imported_count?: number
  skipped_existing?: number
}

interface RunPipelineResponse {
  runtime?: SangonRuntimeState
}

interface CleanupResponse {
  scan_index_cleared?: number
  removed_count?: number
  freed_mb?: number
}

interface MailOverviewAuthResponse {
  auth?: {
    imap_ready?: boolean
    imap_masked?: string
    imap_file?: string
  }
}

interface SangonAuthResponse {
  sangon_auth?: SangonAuthMeta
}

export interface SangonOrderActionsContext {
  sangonRoot: Ref<string>
  downloadsDir: Ref<string>
  activeOrders: ComputedRef<SangonOrderItem[]>
  checkedOrderNames: Ref<string[]>
  selectedOrder: Ref<SangonOrderItem | null>
  orderFilter: Ref<OrderFilterKey>
  checkedDownloadableNames: ComputedRef<string[]>
  downloadableOrders: ComputedRef<SangonOrderItem[]>
  awaitingDownloadCount: ComputedRef<number>
  runnableOrdersCount: ComputedRef<number>
  forceReblast: Ref<boolean>
  autoBlastAfterDownload: Ref<boolean>
  autoConfirmFee: Ref<boolean>
  sangonAuth: Ref<SangonAuthMeta>
  browserEnv: Ref<BrowserEnvStatus | null>
  repairingBrowser: Ref<boolean>
  showSangonAuthModal: Ref<boolean>
  sangonAuthHint: Ref<string>
  pendingDownloadTask: Ref<{ orderNames: string[]; autoRunBlast: boolean } | null>
  showCleanup: Ref<boolean>
  cleanupTargetOrders: Ref<string[]>
  showAuthModal: Ref<boolean>
  imapMasked: Ref<string>
  imapReady: Ref<boolean>
  imapFile: Ref<string>
  imapKeyInput: Ref<string>
  recentCreatedDirs: Ref<string[]>
  runtime: Ref<SangonRuntimeState>
  trackingRun: Ref<boolean>
  showLogs: Ref<boolean>
  busy: Ref<boolean>
  setInfo: (msg: string) => void
  setError: (err: unknown) => void
  loadOverview: () => Promise<void>
  selectOrderAndLoadResults: (order: SangonOrderItem) => Promise<void>
  scheduleFollowUpRefresh: () => void
  clearFollowUpTimer: () => void
}

export function useSangonOrderActions(ctx: SangonOrderActionsContext) {
  async function handleSaveRoot(newRoot: string): Promise<void> {
    ctx.busy.value = true
    ctx.setInfo('正在更新目录并迁移数据...')
    try {
      const data = await postJson<SettingsResponse>(`${API}/settings`, { sangon_root: newRoot, migrate: true })
      ctx.sangonRoot.value = data.settings?.sangon_root || newRoot
      const migMsg = describeMigration(data.migration)
      ctx.setInfo(migMsg ? `目录已更新。${migMsg}` : '目录已更新')
      ctx.selectedOrder.value = null
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function handleSaveDownloadsDir(newDl: string): Promise<void> {
    ctx.busy.value = true
    ctx.setInfo('正在更新浏览器下载目录...')
    try {
      const data = await postJson<SettingsResponse>(`${API}/settings`, { downloads_dir: newDl, migrate: false })
      ctx.downloadsDir.value = data.settings?.downloads_dir || newDl
      ctx.setInfo('浏览器下载目录已更新')
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function handleImportDownloads(autoCreateOrder = false, targetOrders: string[] = []): Promise<void> {
    ctx.busy.value = true
    const orderScope = targetOrders.length ? targetOrders : ctx.checkedOrderNames.value
    ctx.setInfo(
      targetOrders.length === 1 ? `正在认领订单 ${targetOrders[0]} 的下载包...` : '正在从浏览器下载目录认领生工压缩包...'
    )
    try {
      const data = await postJson<ImportDownloadsResponse>(`${API}/import_downloads`, {
        sangon_root: ctx.sangonRoot.value || null,
        downloads_dir: ctx.downloadsDir.value || null,
        order_names: orderScope,
        auto_create_order: autoCreateOrder,
      })
      const createdCnt = (data.created_dirs || []).length
      const createdPart = createdCnt ? `，新建订单目录 ${createdCnt} 个` : ''
      ctx.setInfo(
        `下载包认领完成：扫描到 ${data.scanned_zips ?? 0} 个压缩包，新导入 ${data.imported_count ?? 0} 个${createdPart}，跳过已归档 ${data.skipped_existing ?? 0} 个`
      )
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
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

  async function handleRunPipeline(orderNames: string[] = []): Promise<void> {
    const targets = orderNames.length ? orderNames : ctx.orderFilter.value !== 'ignored' ? ctx.checkedOrderNames.value : []

    if (!targets.length && ctx.runnableOrdersCount.value === 0) {
      ctx.setInfo(
        ctx.awaitingDownloadCount.value > 0
          ? `当前没有可执行比对的订单：剩余 ${ctx.awaitingDownloadCount.value} 个订单尚未下载压缩包，可点击「自动下载」自动拉取，或手动「打开下载页」下载后认领（非测序通知单可忽略）`
          : '当前没有需要处理的生工 16S 订单'
      )
      return
    }

    ctx.clearFollowUpTimer()
    ctx.setInfo(targets.length ? `正在启动订单处理: ${targets.join(', ')}...` : '正在启动生工 16S 待处理流水线...')
    try {
      const data = await postJson<RunPipelineResponse>(`${API}/run_pipeline`, {
        sangon_root: ctx.sangonRoot.value,
        downloads_dir: ctx.downloadsDir.value || null,
        order_names: targets,
        evalue: '0.05',
        hitlist_size: '50',
        force_reblast: ctx.forceReblast.value,
      })
      ctx.trackingRun.value = true
      ctx.runtime.value = data.runtime || ctx.runtime.value
      ctx.setInfo(ctx.runtime.value?.last_message || '任务已在后台运行')
      ctx.scheduleFollowUpRefresh()
    } catch (err: unknown) {
      ctx.trackingRun.value = false
      ctx.setError(err)
    }
  }

  function openCleanupModal(orderNames?: string[]): void {
    const targets =
      orderNames && orderNames.length
        ? orderNames
        : ctx.checkedOrderNames.value.length
          ? ctx.checkedOrderNames.value
          : ctx.activeOrders.value.length
            ? ctx.activeOrders.value.map((o) => o.dir_name)
            : ['__ALL__']
    ctx.cleanupTargetOrders.value = targets
    ctx.showCleanup.value = true
  }

  async function confirmCleanup(targets: string[]): Promise<void> {
    ctx.busy.value = true
    try {
      const data = await postJson<CleanupResponse>(`${API}/cleanup`, {
        order_names: ctx.cleanupTargetOrders.value,
        targets,
      })
      ctx.showCleanup.value = false
      ctx.recentCreatedDirs.value = []
      const clearedPart = data.scan_index_cleared ? `，清除扫描记忆 ${data.scan_index_cleared} 条` : ''
      ctx.setInfo(`已清理 ${data.removed_count ?? 0} 项${clearedPart}，释放 ${data.freed_mb ?? 0} MB`)
      await ctx.loadOverview()
      if (ctx.selectedOrder.value) await ctx.selectOrderAndLoadResults(ctx.selectedOrder.value)
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function openAuthEditor(): Promise<void> {
    ctx.imapKeyInput.value = ''
    try {
      const data = await getJson<MailOverviewAuthResponse>(`${MAIL_API}/overview`)
      ctx.imapReady.value = Boolean(data.auth?.imap_ready)
      ctx.imapMasked.value = data.auth?.imap_masked || ''
      ctx.imapFile.value = data.auth?.imap_file || ''
    } catch {
      // ignore
    }
    ctx.showAuthModal.value = true
  }

  async function saveImapAuth(): Promise<void> {
    if (!ctx.imapKeyInput.value.trim()) {
      ctx.showAuthModal.value = false
      return
    }
    ctx.busy.value = true
    try {
      const data = await postJson<MailOverviewAuthResponse>(`${MAIL_API}/auth`, {
        imap_auth_code: ctx.imapKeyInput.value.trim(),
        smtp_auth_code: null,
      })
      ctx.imapReady.value = Boolean(data.auth?.imap_ready)
      ctx.imapMasked.value = data.auth?.imap_masked || ''
      ctx.showAuthModal.value = false
      ctx.setInfo('邮箱 Key 已更新')
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  function openSangonAuthEditor(hint = ''): void {
    ctx.sangonAuthHint.value = hint
    ctx.showSangonAuthModal.value = true
  }

  function closeSangonAuthEditor(): void {
    ctx.showSangonAuthModal.value = false
    ctx.pendingDownloadTask.value = null
  }

  async function handleAutoDownloadOrders(
    orderNames: string[] = [],
    autoRunBlast = ctx.autoBlastAfterDownload.value
  ): Promise<void> {
    const targets = orderNames.length
      ? orderNames
      : ctx.orderFilter.value !== 'ignored' && ctx.checkedDownloadableNames.value.length > 0
        ? ctx.checkedDownloadableNames.value
        : []

    const targetOrderObjs = targets.length
      ? ctx.activeOrders.value.filter((o) => targets.includes(o.dir_name) && isOrderDownloadableImpl(o))
      : ctx.downloadableOrders.value

    if (!targetOrderObjs.length) {
      ctx.setInfo('当前没有可自动下载的待处理订单（请确认已运行「检查新订单」获取下载链接，或直接点击待认领下载包）')
      return
    }

    const needsWebLogin = targetOrderObjs.some(
      (o) => !o.download_zip_ready && Boolean(o.download_url || o.cx_order_id)
    )
    if (needsWebLogin && (!ctx.sangonAuth.value.account || !ctx.sangonAuth.value.password_ready)) {
      ctx.pendingDownloadTask.value = { orderNames: targets, autoRunBlast }
      openSangonAuthEditor('检测到需登录生工官网下载压缩包，请先保存一次生工账号与登录密码（保存后将自动继续下载）。')
      return
    }
    if (needsWebLogin && ctx.browserEnv.value && !ctx.browserEnv.value.enabled) {
      openSangonAuthEditor(
        '检测到当前无头浏览器已被禁用 (enabled=false)，请先在下方勾选启用无头浏览器并点击「应用浏览器配置并检查自修复」。'
      )
      return
    }

    ctx.clearFollowUpTimer()
    ctx.setInfo(
      autoRunBlast
        ? `正在启动自动下载并接续 16S 比对（待处理 ${targetOrderObjs.length} 个）...`
        : `正在启动自动认领/官网下载（待处理 ${targetOrderObjs.length} 个）...`
    )
    try {
      const data = await postJson<RunPipelineResponse>(`${API}/download_orders`, {
        sangon_root: ctx.sangonRoot.value || null,
        downloads_dir: ctx.downloadsDir.value || null,
        order_names: targets,
        auto_run_blast: autoRunBlast,
        auto_confirm_fee: ctx.autoConfirmFee.value,
        evalue: '0.05',
        hitlist_size: '50',
        force_reblast: ctx.forceReblast.value,
      })
      ctx.trackingRun.value = true
      ctx.showLogs.value = true
      ctx.runtime.value = data.runtime || ctx.runtime.value
      ctx.setInfo(ctx.runtime.value?.last_message || '自动下载任务已在后台启动')
      ctx.scheduleFollowUpRefresh()
    } catch (err: unknown) {
      ctx.trackingRun.value = false
      const detail = extractErrorMessage(err)
      if (detail.includes('生工账号配置') || detail.includes('账号与登录密码')) {
        ctx.pendingDownloadTask.value = { orderNames: targets, autoRunBlast }
        openSangonAuthEditor(detail)
      } else {
        ctx.setError(err)
      }
    }
  }

  async function handleSaveSangonAuth(payload: {
    account: string
    password: string | null
    auto_confirm_fee: boolean
  }): Promise<void> {
    ctx.busy.value = true
    try {
      const data = await postJson<SangonAuthResponse>(`${API}/auth`, payload)
      if (data.sangon_auth) {
        ctx.sangonAuth.value = data.sangon_auth
        ctx.autoConfirmFee.value = data.sangon_auth.auto_confirm_fee ?? payload.auto_confirm_fee
      }
      ctx.showSangonAuthModal.value = false
      const nextTask = ctx.pendingDownloadTask.value
      ctx.pendingDownloadTask.value = null
      if (nextTask && ctx.sangonAuth.value.account && ctx.sangonAuth.value.password_ready) {
        ctx.setInfo('生工账号配置已保存，正在自动接续下载流程...')
        await handleAutoDownloadOrders(nextTask.orderNames, nextTask.autoRunBlast)
        return
      }
      ctx.setInfo('生工官网账号配置已保存（密码已独立存放于本地 .sangon_auth）')
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function handleClearSangonPassword(): Promise<void> {
    ctx.busy.value = true
    try {
      const data = await postJson<SangonAuthResponse>(`${API}/auth`, { password: '' })
      if (data.sangon_auth) ctx.sangonAuth.value = data.sangon_auth
      ctx.setInfo('已清除本地保存的生工登录密码')
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function handleToggleAutoConfirmFee(): Promise<void> {
    try {
      const data = await postJson<SettingsResponse>(`${API}/settings`, { auto_confirm_fee: ctx.autoConfirmFee.value })
      if (data.sangon_auth) {
        ctx.sangonAuth.value = data.sangon_auth
      } else {
        ctx.sangonAuth.value = { ...ctx.sangonAuth.value, auto_confirm_fee: ctx.autoConfirmFee.value }
      }
      ctx.setInfo(
        ctx.autoConfirmFee.value
          ? '已开启：遇到 KBSeq 费用确认弹窗将自动点击确定下载'
          : '已关闭：遇到费用确认弹窗将跳过并等待人工确认'
      )
    } catch (err: unknown) {
      ctx.setError(err)
    }
  }

  async function handleRepairBrowser(payload?: {
    enabled?: boolean
    headless?: boolean
    use_system_browser_fallback?: boolean
    auto_install?: boolean
    probe_launch?: boolean
  }): Promise<void> {
    ctx.repairingBrowser.value = true
    try {
      const data = await postJson<BrowserEnvStatus>(`${BROWSER_ENV_API}/repair`, {
        auto_install: true,
        probe_launch: true,
        ...(payload || {}),
      })
      ctx.browserEnv.value = data
      const acts = (data.actions || []).filter(Boolean)
      if (data.ready) {
        const modeName = data.mode || 'playwright_chromium'
        ctx.setInfo(acts.length ? `无头浏览器已自修复并就绪 (${modeName})：${acts.join('；')}` : `无头浏览器检查通过 (${modeName})`)
      } else if (!data.enabled) {
        ctx.setInfo('已保存无头浏览器配置：当前状态为已禁用 (enabled=false)')
      } else {
        const detail = (data.warnings || []).join('；') || data.issues?.[0]?.message || '仍未就绪，请检查网络或配置'
        ctx.setError(`无头浏览器自修复未完全就绪：${detail}`)
      }
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.repairingBrowser.value = false
    }
  }

  return {
    handleSaveRoot,
    handleSaveDownloadsDir,
    handleImportDownloads,
    handleClaimSingleOrder,
    handleClaimSingleCandidate,
    handleRunPipeline,
    openCleanupModal,
    confirmCleanup,
    openAuthEditor,
    saveImapAuth,
    openSangonAuthEditor,
    closeSangonAuthEditor,
    handleAutoDownloadOrders,
    handleSaveSangonAuth,
    handleClearSangonPassword,
    handleToggleAutoConfirmFee,
    handleRepairBrowser,
  }
}
