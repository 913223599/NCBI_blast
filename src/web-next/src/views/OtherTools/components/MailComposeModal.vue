<script setup lang="ts">
/**
 * MailComposeModal - 通用可编辑邮件撰写与发送弹窗
 * 职责：
 * 1. 支持查看并自由修改：发信标题（发件人名称）、收件人、抄送(CC)、邮件主题、邮件正文内容、附件压缩包文件名；
 * 2. 支持一键「恢复默认模板」、「设为自己 / 填回传地址」快捷填入，以及安全隔离的「发给自己测试」。
 */
import { computed, ref, watch } from 'vue'

export interface MailDraftPayload {
  to: string
  replyTo?: string
  fromName: string
  cc: string
  subject: string
  body: string
  attachmentName: string
}

export interface MailComposeSubmitPayload {
  toSelf: boolean
  to: string
  fromName: string
  cc: string
  subject: string
  body: string
  attachmentName: string
  attachLatestReport: boolean
}

const props = withDefaults(
  defineProps<{
    visible: boolean
    title: string
    contextTitle: string
    attachSummary?: string
    draft: MailDraftPayload
    loadingDraft?: boolean
    sending?: boolean
    selfAddress?: string
    defaultDisplayName?: string
    showAttachLatestReport?: boolean
    latestReportName?: string
    attachLatestReport?: boolean
    safetyNote?: string
  }>(),
  {
    attachSummary: '',
    loadingDraft: false,
    sending: false,
    selfAddress: '',
    defaultDisplayName: '',
    showAttachLatestReport: false,
    latestReportName: '',
    attachLatestReport: false,
    safetyNote: ''
  }
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'resetDraft', payload: { attachLatestReport: boolean }): void
  (e: 'toggleAttachReport', value: boolean): void
  (e: 'send', payload: MailComposeSubmitPayload): void
}>()

const form = ref<MailDraftPayload>({
  to: '',
  replyTo: '',
  fromName: '',
  cc: '',
  subject: '',
  body: '',
  attachmentName: ''
})

const attachReportChecked = ref(false)
const showAdvanced = ref(false)
let modalUidSeed = 0
const uid = ++modalUidSeed
const toInputId = `mail-compose-to-${uid}`
const bodyInputId = `mail-compose-body-${uid}`

function syncFromDraft(src: MailDraftPayload, preserveRecipients: boolean): void {
  form.value = {
    to: preserveRecipients ? (form.value.to || src.to || '') : (src.to || ''),
    replyTo: src.replyTo || '',
    fromName: src.fromName || '',
    cc: preserveRecipients ? (form.value.cc || src.cc || '') : (src.cc || ''),
    subject: src.subject || '',
    body: src.body || '',
    attachmentName: src.attachmentName || ''
  }
}

watch(
  () => props.visible,
  (open) => {
    if (open) {
      showAdvanced.value = Boolean(props.draft?.cc)
      attachReportChecked.value = Boolean(props.attachLatestReport)
      syncFromDraft(props.draft, false)
    }
  }
)

watch(
  () => props.draft,
  (nextDraft) => {
    if (!props.visible || !nextDraft) return
    syncFromDraft(nextDraft, true)
  },
  { deep: true }
)

watch(
  () => props.attachLatestReport,
  (val) => {
    attachReportChecked.value = Boolean(val)
  }
)

const bodyLineCount = computed(() => {
  if (!form.value.body) return 0
  return form.value.body.split('\n').length
})

const hasDistinctReplyTo = computed(() => {
  const rep = (props.draft?.replyTo || form.value.replyTo || '').trim()
  const selfAddr = (props.selfAddress || '').trim()
  return Boolean(rep && rep !== selfAddr)
})

function fillSelfAddress(): void {
  if (props.selfAddress) {
    form.value.to = props.selfAddress
  }
}

function fillReplyToAddress(): void {
  const rep = (props.draft?.replyTo || form.value.replyTo || '').trim()
  if (rep) {
    form.value.to = rep
  }
}

function handleToggleAttachReport(): void {
  emit('toggleAttachReport', attachReportChecked.value)
}

function handleResetDraft(): void {
  emit('resetDraft', { attachLatestReport: attachReportChecked.value })
}

function handleSubmit(toSelf: boolean): void {
  emit('send', {
    toSelf,
    to: form.value.to.trim(),
    fromName: form.value.fromName.trim(),
    cc: toSelf ? '' : form.value.cc.trim(),
    subject: form.value.subject.trim(),
    body: form.value.body,
    attachmentName: form.value.attachmentName.trim(),
    attachLatestReport: attachReportChecked.value
  })
}
</script>

<template>
  <div v-if="visible" class="modal-backdrop" @click.self="emit('close')">
    <div class="compose-card">
      <div class="modal-header">
        <h3>{{ title }}</h3>
        <button class="close-btn" type="button" @click="emit('close')">&times;</button>
      </div>

      <div class="compose-body">
        <div class="context-banner">
          <div class="context-main">{{ contextTitle }}</div>
          <div v-if="attachSummary" class="context-sub">{{ attachSummary }}</div>
        </div>

        <div class="compose-grid">
          <div class="compose-field">
            <div class="field-label-row">
              <label :for="toInputId">收件人邮箱 (To)</label>
              <span class="field-quick-links">
                <button
                  v-if="selfAddress"
                  type="button"
                  class="link-btn"
                  @click="fillSelfAddress"
                >
                  设为自己
                </button>
                <button
                  v-if="hasDistinctReplyTo"
                  type="button"
                  class="link-btn"
                  :title="`填入默认回传地址: ${draft.replyTo}`"
                  @click="fillReplyToAddress"
                >
                  填回传地址
                </button>
              </span>
            </div>
            <input
              :id="toInputId"
              v-model="form.to"
              type="text"
              :placeholder="selfAddress ? `留空默认发给自己 (${selfAddress})，多邮箱用逗号分隔` : '留空默认发给自己，多邮箱用逗号分隔'"
              class="compose-input"
            />
          </div>

          <label class="compose-field">
            <span class="field-label-row">
              <span>发信标题（发件人名称）</span>
              <span class="field-hint">默认: {{ defaultDisplayName || '邮箱配置名称' }}</span>
            </span>
            <input
              v-model="form.fromName"
              type="text"
              :placeholder="defaultDisplayName || '例如：元昇生物注释服务'"
              class="compose-input"
            />
          </label>
        </div>

        <label class="compose-field">
          <span class="field-label-row">
            <span>邮件主题</span>
            <span class="field-hint">支持直接修改</span>
          </span>
          <input
            v-model="form.subject"
            type="text"
            placeholder="请输入邮件主题"
            class="compose-input"
          />
        </label>

        <div class="compose-field">
          <div class="field-label-row">
            <label :for="bodyInputId">
              邮件正文内容
              <span class="line-counter">({{ bodyLineCount }} 行 · {{ form.body.length }} 字)</span>
            </label>
            <button
              type="button"
              class="reset-btn"
              :disabled="loadingDraft || sending"
              @click="handleResetDraft"
            >
              {{ loadingDraft ? '加载中...' : '恢复默认内容' }}
            </button>
          </div>
          <textarea
            :id="bodyInputId"
            v-model="form.body"
            rows="8"
            :disabled="loadingDraft"
            :placeholder="loadingDraft ? '正在加载默认邮件正文...' : '可直接编辑邮件正文内容；留空发送时自动使用默认模板'"
            class="compose-textarea"
          />
        </div>

        <label v-if="showAttachLatestReport && latestReportName" class="report-check-row">
          <input v-model="attachReportChecked" type="checkbox" @change="handleToggleAttachReport" />
          <span>同时打包附带最新 Word 报告（{{ latestReportName }}）</span>
        </label>

        <div class="advanced-section">
          <button
            type="button"
            class="advanced-toggle"
            @click="showAdvanced = !showAdvanced"
          >
            <span>{{ showAdvanced ? 'v 收起更多发信选项' : '> 更多发信选项（抄送 CC、附件压缩包文件名）' }}</span>
            <span class="adv-summary">
              <template v-if="form.cc.trim()">抄送: {{ form.cc.trim() }} | </template>
              附件: {{ form.attachmentName.trim() || '默认压缩包名称' }}
            </span>
          </button>

          <div v-if="showAdvanced" class="advanced-panel">
            <label class="compose-field">
              <span class="field-label-row">
                <span>抄送邮箱 (CC，可选)</span>
                <span class="field-hint">多邮箱用逗号或分号分隔；点「发给自己测试」时不会抄送外部邮箱</span>
              </span>
              <input
                v-model="form.cc"
                type="text"
                placeholder="例如：leader@lab.com, team@lab.com"
                class="compose-input"
              />
            </label>

            <label class="compose-field">
              <span class="field-label-row">
                <span>附件压缩包文件名</span>
                <span class="field-hint">支持自定义名称，未写 .zip 后缀将自动补全</span>
              </span>
              <input
                v-model="form.attachmentName"
                type="text"
                placeholder="例如：结果包.zip"
                class="compose-input mono-input"
              />
            </label>
          </div>
        </div>

        <p v-if="safetyNote" class="safety-note">{{ safetyNote }}</p>
      </div>

      <div class="modal-footer">
        <button class="btn-outline" type="button" @click="emit('close')">取消</button>
        <button
          class="btn-secondary"
          type="button"
          :disabled="loadingDraft || sending"
          title="仅发送给自己配置的本人邮箱，忽略外部收件人与抄送，安全验证排版与附件效果"
          @click="handleSubmit(true)"
        >
          {{ sending ? '发送中...' : '发给自己测试' }}
        </button>
        <button
          class="btn-primary"
          type="button"
          :disabled="loadingDraft || sending"
          @click="handleSubmit(false)"
        >
          {{ sending ? '发送中...' : '发送邮件' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.compose-card {
  background: white;
  border-radius: 12px;
  width: 680px;
  max-width: 94vw;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}

.modal-header h3 {
  margin: 0;
  font-size: 15px;
  color: #0f172a;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #64748b;
  line-height: 1;
}

.compose-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.context-banner {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 9px 12px;
}

.context-main {
  font-size: 12px;
  font-weight: 600;
  color: #1e293b;
}

.context-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #64748b;
}

.compose-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 12px;
}

.compose-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: #334155;
}

.field-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #334155;
}

.field-hint {
  font-size: 11px;
  font-weight: 400;
  color: #94a3b8;
}

.line-counter {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 400;
  color: #94a3b8;
}

.field-quick-links {
  display: inline-flex;
  gap: 8px;
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 11px;
  font-weight: 500;
  color: #2563eb;
  cursor: pointer;
}

.link-btn:hover {
  text-decoration: underline;
}

.reset-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  padding: 2px 9px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
}

.reset-btn:hover:not(:disabled) {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #93c5fd;
}

.reset-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.compose-input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  color: #0f172a;
  background: white;
}

.compose-input:focus,
.compose-textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.14);
}

.mono-input {
  font-family: Consolas, monospace;
}

.compose-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 11px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
  font-family: Consolas, 'Microsoft YaHei', sans-serif;
  resize: vertical;
  min-height: 148px;
}

.compose-textarea:disabled {
  background: #f8fafc;
  color: #94a3b8;
}

.report-check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #334155;
  cursor: pointer;
}

.advanced-section {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  overflow: hidden;
}

.advanced-toggle {
  width: 100%;
  background: transparent;
  border: none;
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  text-align: left;
}

.advanced-toggle:hover {
  background: #f1f5f9;
}

.adv-summary {
  font-size: 11px;
  font-weight: 400;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 310px;
}

.advanced-panel {
  padding: 10px 12px 12px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: white;
}

.safety-note {
  margin: 0;
  font-size: 11px;
  color: #64748b;
  line-height: 1.45;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: #f8fafc;
  flex-shrink: 0;
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

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

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

.btn-secondary:hover:not(:disabled) {
  background: #047857;
}

.btn-outline {
  background: white;
  color: #334155;
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.btn-outline:hover:not(:disabled) {
  background: #f1f5f9;
}

.btn-primary:disabled,
.btn-secondary:disabled,
.btn-outline:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
