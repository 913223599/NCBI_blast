/**
 * useSangonMailActions.ts - 生工 16S 邮件扫描、忽略规则同步与结果邮件发送逻辑
 */
import type { Ref } from 'vue'
import type { MailComposeSubmitPayload, MailDraftPayload } from '../../components/MailComposeModal.vue'
import type {
  IgnoredOrderRule,
  MailScanSummary,
  OrderFilterKey,
  SangonOrderItem,
  ScannedMailItem,
} from '../../sangonTypes'
import { postJson } from '../../api'
import { normalizeOrderKeyFrontend } from './sangonHelpers'

const API = '/api/other_tools/sangon_16s'

interface IgnoreOrdersResponse {
  ignored_orders?: Record<string, IgnoredOrderRule>
  affected_orders?: string[]
  updated_count?: number
}

interface SettingsUpdateResponse {
  settings?: {
    ignore_subject_keywords?: string[]
  }
}

interface SendPreviewResponse {
  from_name?: string
  reply_to?: string
  to?: string
  cc?: string
  subject?: string
  body?: string
  attachment_name?: string
}

interface SendResultResponse {
  to?: string
  attachment?: string
  attachment_size?: number
  total_samples?: number
  with_hits?: number
}

interface ScanMailResponse {
  mails?: ScannedMailItem[]
  created_dirs?: string[]
  raw_total?: number
  unique_total?: number
  dedup_removed?: number
  skipped_known?: number
  ignored_count?: number
  new_count?: number
  created_count?: number
  existing_count?: number
  non_sequencing_count?: number
}

export interface SangonMailActionsContext {
  mailRecordsRef: Ref<{ expand?: () => void } | null>
  sangonRoot: Ref<string>
  mailAccount: Ref<string>
  mailDisplayName: Ref<string>
  mailReplyTo: Ref<string>
  orders: Ref<SangonOrderItem[]>
  scannedMails: Ref<ScannedMailItem[]>
  hasScannedMails: Ref<boolean>
  scanningMail: Ref<boolean>
  recentCreatedDirs: Ref<string[]>
  mailFilter: Ref<{ dedup: boolean; autoCreate: boolean; ignoreHistory: boolean }>
  mailSummary: Ref<MailScanSummary>
  ignoredOrdersMap: Ref<Record<string, IgnoredOrderRule>>
  ignoreKeywords: Ref<string[]>
  checkedOrderNames: Ref<string[]>
  orderFilter: Ref<OrderFilterKey>
  orderPage: Ref<number>
  showSendModal: Ref<boolean>
  loadingSendDraft: Ref<boolean>
  sendingMail: Ref<boolean>
  sendOrderTarget: Ref<SangonOrderItem | null>
  sendDraft: Ref<MailDraftPayload>
  busy: Ref<boolean>
  setInfo: (msg: string) => void
  setError: (err: unknown) => void
  loadOverview: () => Promise<void>
}

export function useSangonMailActions(ctx: SangonMailActionsContext) {
  function syncScannedMailsIgnoreState(targetKeys: Set<string>, ignored: boolean): void {
    if (!ctx.scannedMails.value.length || !targetKeys.size) return
    const existingOrderNos = new Set(ctx.orders.value.map((o) => normalizeOrderKeyFrontend(o.order_no || o.dir_name)))
    let changed = false
    ctx.scannedMails.value = ctx.scannedMails.value.map((m) => {
      const key = normalizeOrderKeyFrontend(m.order_no || m.dir_name)
      if (!key || !targetKeys.has(key) || m.dedup_status === 'non_sequencing') return m
      changed = true
      if (ignored) return { ...m, ignored: true, dedup_status: 'ignored' }
      const hasDir = Boolean(m.dir_ready || existingOrderNos.has(key))
      return { ...m, ignored: false, dir_ready: hasDir, dedup_status: hasDir ? 'existing' : 'new' }
    })
    if (changed) {
      ctx.mailSummary.value = {
        ...ctx.mailSummary.value,
        ignoredCount: ctx.scannedMails.value.filter((m) => m.dedup_status === 'ignored').length,
        existingCount: ctx.scannedMails.value.filter((m) => m.dedup_status === 'existing' || m.dedup_status === 'created')
          .length,
        newCount: ctx.scannedMails.value.filter((m) => m.dedup_status === 'new').length,
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
    ctx.busy.value = true
    try {
      const data = await postJson<IgnoreOrdersResponse>(`${API}/ignore`, {
        order_keys: orderKeys,
        ignore,
        reason,
        dir_names: dirNames,
      })
      ctx.ignoredOrdersMap.value = data.ignored_orders || {}
      const affected = new Set<string>((data.affected_orders || []).map((k: string) => normalizeOrderKeyFrontend(k)))
      for (const k of orderKeys) {
        const nk = normalizeOrderKeyFrontend(k)
        if (nk) affected.add(nk)
      }
      ctx.checkedOrderNames.value = ctx.checkedOrderNames.value.filter(
        (name) => !affected.has(normalizeOrderKeyFrontend(name))
      )
      syncScannedMailsIgnoreState(affected, ignore)
      ctx.setInfo(
        ignore
          ? `已将 ${data.updated_count ?? 0} 个订单设为全局忽略（已移入「已忽略」标签隐藏，本地文件与压缩包安全保留）`
          : `已取消忽略 ${data.updated_count ?? 0} 个订单，已恢复至正常待办队列`
      )
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
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
    ctx.busy.value = true
    try {
      const data = await postJson<SettingsUpdateResponse>(`${API}/settings`, { ignore_subject_keywords: keywords })
      ctx.ignoreKeywords.value = data.settings?.ignore_subject_keywords || []
      ctx.setInfo(`非测序邮件主题过滤关键词已更新（共 ${ctx.ignoreKeywords.value.length} 项）`)
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  async function loadSangonSendDraft(order: SangonOrderItem): Promise<void> {
    ctx.loadingSendDraft.value = true
    try {
      const data = await postJson<SendPreviewResponse>(`${API}/send_preview`, {
        order_dir_name: order.dir_name,
        sangon_root: ctx.sangonRoot.value || null,
      })
      if (data.from_name) ctx.mailDisplayName.value = data.from_name
      if (data.reply_to !== undefined) ctx.mailReplyTo.value = data.reply_to || ''
      ctx.sendDraft.value = {
        to: data.to || ctx.mailAccount.value || '',
        replyTo: data.reply_to || ctx.mailReplyTo.value || '',
        fromName: data.from_name || ctx.mailDisplayName.value || '元昇生物注释服务',
        cc: data.cc || '',
        subject: data.subject || `生工 16S 测序鉴定结果 - ${order.dir_name}（共 ${order.total_samples} 样本）`,
        body: data.body || '',
        attachmentName: data.attachment_name || `16S鉴定结果_${order.dir_name}.zip`,
      }
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.loadingSendDraft.value = false
    }
  }

  async function openSendResultModal(order: SangonOrderItem): Promise<void> {
    ctx.sendOrderTarget.value = order
    ctx.sendDraft.value = {
      to: ctx.mailAccount.value || '',
      replyTo: ctx.mailReplyTo.value || '',
      fromName: ctx.mailDisplayName.value || '元昇生物注释服务',
      cc: '',
      subject: `生工 16S 测序鉴定结果 - ${order.dir_name}（共 ${order.total_samples} 样本）`,
      body: '',
      attachmentName: `16S鉴定结果_${order.dir_name}.zip`,
    }
    ctx.showSendModal.value = true
    await loadSangonSendDraft(order)
  }

  async function resetSangonSendDraft(): Promise<void> {
    if (!ctx.sendOrderTarget.value) return
    await loadSangonSendDraft(ctx.sendOrderTarget.value)
  }

  async function confirmSendResultMail(payload: MailComposeSubmitPayload): Promise<void> {
    if (!ctx.sendOrderTarget.value) return
    ctx.sendingMail.value = true
    try {
      const targetTo = payload.toSelf ? 'self' : payload.to.trim() || 'self'
      const data = await postJson<SendResultResponse>(`${API}/send_result`, {
        order_dir_name: ctx.sendOrderTarget.value.dir_name,
        sangon_root: ctx.sangonRoot.value || null,
        to: targetTo,
        cc: payload.cc.trim() || null,
        from_name: payload.fromName.trim() || null,
        subject: payload.subject.trim() || null,
        body: payload.body.trim() ? payload.body : null,
        attachment_name: payload.attachmentName.trim() || null,
      })
      ctx.showSendModal.value = false
      const kb = ((data.attachment_size ?? 0) / 1024).toFixed(1)
      ctx.setInfo(
        `结果邮件已发送至 ${data.to ?? targetTo}：附件 ${data.attachment ?? ''} (${kb} KB)，样本 ${data.total_samples ?? 0}（命中 ${data.with_hits ?? 0}）`
      )
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.sendingMail.value = false
    }
  }

  async function handleCheckNewOrders(): Promise<void> {
    ctx.scanningMail.value = true
    ctx.setInfo('正在连接邮箱检查生工新订单...')
    try {
      const data = await postJson<ScanMailResponse>(`${API}/scan_mail`, {
        sangon_root: ctx.sangonRoot.value || null,
        page: 1,
        page_size: 200,
        dedup: ctx.mailFilter.value.dedup,
        only_new: false,
        auto_create: ctx.mailFilter.value.autoCreate,
        ignore_history: ctx.mailFilter.value.ignoreHistory,
      })
      ctx.scannedMails.value = data.mails || []
      ctx.hasScannedMails.value = true
      const createdDirs: string[] = data.created_dirs || []
      ctx.recentCreatedDirs.value = createdDirs

      ctx.mailSummary.value = {
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

      await ctx.loadOverview()

      const s = ctx.mailSummary.value
      if (createdDirs.length > 0) {
        const previewNames = createdDirs.slice(0, 3).join('、') + (createdDirs.length > 3 ? ' 等' : '')
        ctx.setInfo(`发现 ${createdDirs.length} 个新订单，已自动建目录：${previewNames}`)
        ctx.orderFilter.value = 'all'
        ctx.orderPage.value = 1
      } else if (s.newCount > 0 && !ctx.mailFilter.value.autoCreate) {
        ctx.setInfo(`发现 ${s.newCount} 封待建目录的新测序邮件（当前已关闭自动建目录，可在下方邮件记录中手动创建）`)
        ctx.mailRecordsRef.value?.expand?.()
      } else {
        const extraParts: string[] = [`已有订单 ${s.existingCount} 个`]
        if (s.dedupRemoved > 0) extraParts.push(`合并重复 ${s.dedupRemoved} 封`)
        if (s.nonSequencingCount > 0) extraParts.push(`过滤非测序通知 ${s.nonSequencingCount} 封`)
        if (s.ignoredCount > 0) extraParts.push(`跳过已全局忽略 ${s.ignoredCount} 条`)
        if (s.skippedKnown > 0) extraParts.push(`历史清理跳过 ${s.skippedKnown} 条`)
        ctx.setInfo(`检查完成：暂无新测序订单（${extraParts.join('，')}）`)
      }
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.scanningMail.value = false
    }
  }

  async function handleInitOrderFromMail(mail: ScannedMailItem): Promise<void> {
    if (!mail.dir_name) return
    ctx.busy.value = true
    try {
      await postJson(`${API}/init_order`, {
        sangon_root: ctx.sangonRoot.value || null,
        dir_name: mail.dir_name,
        order_no: mail.order_no,
        subject: mail.subject,
        date_text: mail.date,
        cx_order_id: mail.cx_order_id,
        download_url: mail.download_url,
      })
      mail.dir_ready = true
      mail.dedup_status = 'created'
      if (!ctx.recentCreatedDirs.value.includes(mail.dir_name)) {
        ctx.recentCreatedDirs.value = [...ctx.recentCreatedDirs.value, mail.dir_name]
      }
      ctx.setInfo(`已创建订单目录: ${mail.dir_name}`)
      await ctx.loadOverview()
    } catch (err: unknown) {
      ctx.setError(err)
    } finally {
      ctx.busy.value = false
    }
  }

  return {
    handleIgnoreOrders,
    handleToggleMailIgnore,
    handleSaveIgnoreKeywords,
    openSendResultModal,
    resetSangonSendDraft,
    confirmSendResultMail,
    handleCheckNewOrders,
    handleInitOrderFromMail,
  }
}
